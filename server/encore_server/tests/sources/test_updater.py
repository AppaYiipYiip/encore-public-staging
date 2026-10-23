"""Keeping yt-dlp fresh by itself (docs/11 ADR-R39): the daily check, what a pass and a failure do, the budget of look-ups, the canary's glue to the
server's rest/pacer/counter, and the restart that waits for a quiet moment. No network and no YouTube: PyPI is a mock, the canary a fake or a fake child."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from encore_server.sources.youtube import canary as canary_module
from encore_server.sources.youtube import updater as updater_module
from encore_server.sources.youtube.canary import CANARY_VIDEO, READ_BYTES, ChildCanary, child_env
from encore_server.sources.youtube.errors import DownloadError
from encore_server.sources.youtube.rest import Lookups, Rest
from encore_server.sources.youtube.stream import StreamError
from encore_server.sources.youtube.tools import Active, Pointer, ToolStore
from encore_server.sources.youtube.updater import MAX_CANARIES_PER_DAY, Restarter, Tools, Updater, create_tools
from tests.sources.test_tools import DAY, NOW, pypi, wheel_file

LOG = "encore_server.youtube.updater"


class Rig:
    """An updater whose PyPI, downloads and canary are fakes the test steers."""

    def __init__(self, tmp_path: Path, *, running: str = "2026.10.01", active: Active | None = None) -> None:
        self.now = NOW
        self.store = ToolStore(tmp_path / "tools")
        self.releases: dict[str, list[dict[str, Any]]] = {}
        self.bytes: dict[str, bytes] = {}
        self.verdicts: list[str] = []
        self.calls: list[tuple[Path | None, str | None]] = []
        self.meta_error: Exception | None = None
        self.active = active
        self.updater = Updater(
            store=self.store,
            active=active,
            fetch_meta=self._meta,
            fetch_wheel=lambda release: self.bytes[release.version],
            canary=self._canary,
            image=running if active is None else "2026.10.01",
            clock=lambda: self.now,
        )
        self.updater.running = running

    def release(self, version: str, age_s: float, *, data: bytes | None = None, wrong_hash: bool = False) -> None:
        body = data if data is not None else f"wheel {version}".encode()
        file = wheel_file(version, age_s)
        file["digests"]["sha256"] = hashlib.sha256(b"not it" if wrong_hash else body).hexdigest()
        self.releases[version] = [file]
        self.bytes[version] = body

    def _meta(self) -> dict[str, Any]:
        if self.meta_error is not None:
            raise self.meta_error
        return pypi(self.releases)

    def _canary(self, wheel: Path | None, expect: str | None) -> str:
        self.calls.append((wheel, expect))
        return self.verdicts.pop(0) if self.verdicts else "ok"

    def tomorrow(self) -> None:
        self.now += DAY


@pytest.fixture()
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


# ------------------------------------------------------------------------------------------------ the check


def test_with_nothing_newer_nothing_is_downloaded_or_asked_of_youtube(rig: Rig) -> None:
    rig.release("2026.10.01", 30 * DAY)

    assert rig.updater.check_once() == "up-to-date"
    assert rig.calls == [] and rig.store.read_pointer() is None
    assert rig.store.read_state()["last_check"] == NOW


def test_a_release_younger_than_a_day_is_left_alone(rig: Rig) -> None:
    rig.release("2026.10.02", 3600)

    assert rig.updater.check_once() == "up-to-date"
    assert rig.calls == []


def test_a_newer_release_that_passes_is_stored_pointed_to_and_waits_for_the_next_start(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.release("2026.10.02", 3 * DAY)

    with caplog.at_level(logging.INFO, logger=LOG):
        assert rig.updater.check_once() == "staged"

    pointer = rig.store.read_pointer()
    assert pointer is not None and pointer.version == "2026.10.02" and pointer.wheel == "yt_dlp-2026.10.02-py3-none-any.whl"
    assert (rig.store.wheels / pointer.wheel).read_bytes() == b"wheel 2026.10.02"
    assert rig.calls == [(rig.store.wheels / pointer.wheel, "2026.10.02")], "the candidate itself was checked, once"
    assert rig.updater.pending() == "2026.10.02" and rig.updater.running == "2026.10.01"
    assert rig.updater.status() == {"ytDlp": {"running": "2026.10.01", "pending": "2026.10.02", "state": "ok"}}
    assert "switches to it at its next start" in caplog.text


def test_a_staged_release_is_not_staged_again_and_an_even_newer_one_replaces_it(rig: Rig) -> None:
    rig.release("2026.10.02", 3 * DAY)
    assert rig.updater.check_once() == "staged"

    assert rig.updater.check_once() == "up-to-date", (
        "the pointer's version counts as already running for the purpose of looking further"
    )
    rig.release("2026.10.03", 3 * DAY)
    assert rig.updater.check_once() == "staged"

    pointer = rig.store.read_pointer()
    assert pointer is not None and pointer.version == "2026.10.03"
    assert [p.name for p in rig.store.wheels.iterdir()] == ["yt_dlp-2026.10.03-py3-none-any.whl"], (
        "only what the pointer names is kept"
    )


def test_a_start_on_the_new_copy_is_no_longer_pending(tmp_path: Path) -> None:
    wheel = tmp_path / "tools" / "wheels" / "yt_dlp-2026.10.02-py3-none-any.whl"
    rig = Rig(tmp_path, running="2026.10.02", active=Active("2026.10.02", wheel))
    rig.store.write_pointer(Pointer("2026.10.02", wheel.name, "x"))

    assert rig.updater.pending() is None


def test_a_candidate_that_fails_while_the_running_copy_works_is_bad_and_never_tried_again(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.release("2026.10.02", 3 * DAY)
    rig.verdicts = ["failed", "ok"]

    with caplog.at_level(logging.WARNING, logger=LOG):
        assert rig.updater.check_once() == "candidate-failed"

    assert rig.store.read_pointer() is None and not list(rig.store.wheels.iterdir()), (
        "nothing is switched to and the bad wheel is deleted"
    )
    assert rig.store.read_state()["bad"] == ["2026.10.02"] and not rig.updater.degraded()
    assert [expect for _, expect in rig.calls] == ["2026.10.02", None], (
        "the running copy was asked to tell YouTube's fault from the release's"
    )
    assert "staying on 2026.10.01, which works" in caplog.text
    rig.tomorrow()
    rig.calls.clear()
    assert rig.updater.check_once() == "up-to-date" and rig.calls == []


def test_when_the_running_copy_fails_too_youtube_is_the_problem_and_the_candidate_stays_eligible(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.release("2026.10.02", 3 * DAY)
    rig.verdicts = ["failed", "failed"]

    with caplog.at_level(logging.WARNING, logger=LOG):
        assert rig.updater.check_once() == "degraded"

    assert rig.updater.degraded() and rig.updater.status()["ytDlp"]["state"] == "degraded"
    assert "bad" not in rig.store.read_state(), "the release that may fix it is not condemned"
    assert "songs from YouTube are not working right now" in caplog.text
    rig.tomorrow()
    rig.verdicts = ["ok"]
    assert rig.updater.check_once() == "staged"
    assert not rig.updater.degraded(), "a pass ends the degraded state"


def test_a_degraded_server_with_nothing_newer_looks_at_its_own_copy_and_notices_when_it_works_again(rig: Rig) -> None:
    rig.release("2026.10.01", 30 * DAY)
    rig.store.write_state({"degraded": True})
    rig.verdicts = ["failed", "ok"]

    assert rig.updater.check_once() == "still-degraded" and rig.updater.degraded()
    assert rig.updater.check_once() == "recovered" and not rig.updater.degraded()
    assert [expect for _, expect in rig.calls] == [None, None]


def test_the_running_copy_is_the_stored_wheel_when_the_server_started_on_one(tmp_path: Path) -> None:
    wheel = tmp_path / "tools" / "wheels" / "yt_dlp-2026.10.01-py3-none-any.whl"
    rig = Rig(tmp_path, running="2026.10.01", active=Active("2026.10.01", wheel))
    rig.release("2026.10.02", 3 * DAY)
    rig.verdicts = ["failed", "ok"]

    rig.updater.check_once()

    assert rig.calls[1] == (wheel, None)


def test_a_check_that_youtube_would_not_answer_decides_nothing(rig: Rig) -> None:
    rig.release("2026.10.02", 3 * DAY)
    rig.verdicts = ["blocked"]

    assert rig.updater.check_once() == "blocked"

    assert rig.store.read_pointer() is None and "bad" not in rig.store.read_state() and not rig.updater.degraded()
    rig.verdicts = ["ok"]
    assert rig.updater.check_once() == "staged", "the same release is tried again next time"


def test_a_fixed_video_that_is_gone_decides_nothing_either(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    rig.release("2026.10.02", 3 * DAY)
    rig.verdicts = ["gone"]

    with caplog.at_level(logging.WARNING, logger=LOG):
        assert rig.updater.check_once() == "cannot-check"

    assert rig.store.read_pointer() is None and "bad" not in rig.store.read_state()
    assert "nothing is changed" in caplog.text


def test_a_download_that_is_not_what_pypi_described_is_refused_before_anything_runs(rig: Rig) -> None:
    rig.release("2026.10.02", 3 * DAY, wrong_hash=True)

    assert rig.updater.check_once() == "download-failed"

    assert rig.calls == [] and rig.store.read_pointer() is None and not rig.store.wheels.exists()


def test_when_pypi_cannot_be_reached_nothing_changes_and_nothing_is_spent(rig: Rig) -> None:
    rig.release("2026.10.02", 3 * DAY)
    rig.meta_error = httpx.ConnectError("no route")

    assert rig.updater.check_once() == "offline"

    assert rig.calls == [] and rig.store.read_state() == {}


def test_a_pypi_answer_that_is_not_json_is_the_same_as_unreachable(rig: Rig) -> None:
    rig.meta_error = json.JSONDecodeError("bad", "", 0)

    assert rig.updater.check_once() == "offline"


def test_a_day_has_a_limited_number_of_looks_at_youtube(rig: Rig) -> None:
    rig.store.write_state({"day": int(NOW // 86400), "runs": MAX_CANARIES_PER_DAY})
    rig.release("2026.10.02", 3 * DAY)

    assert rig.updater.check_once() == "budget" and rig.calls == []

    rig.tomorrow()
    assert rig.updater.check_once() == "staged", "the next day starts again"


def test_a_failing_day_spends_two_runs_and_a_pass_one(rig: Rig) -> None:
    rig.release("2026.10.02", 3 * DAY)
    rig.verdicts = ["failed", "ok"]
    rig.updater.check_once()
    assert rig.store.read_state()["runs"] == 2

    rig.tomorrow()
    rig.release("2026.10.03", 3 * DAY)
    rig.updater.check_once()
    assert rig.store.read_state()["runs"] == 1


def test_the_loop_waits_a_day_after_a_good_check_and_an_hour_after_a_problem(rig: Rig) -> None:
    waits: list[float] = []

    class Stop:
        """An event that records each wait and stops after three."""

        def wait(self, timeout: float | None = None) -> bool:
            waits.append(timeout or 0)
            return len(waits) > 3

    rig.release("2026.10.02", 3 * DAY)
    rig.verdicts = ["blocked", "ok", "ok"]
    rig.updater.run_forever(Stop(), rng=__import__("random").Random(1))  # type: ignore[arg-type]

    first, after_blocked, after_staged = waits[0], waits[1], waits[2]
    assert 300 <= first <= 1800, "the first check comes some minutes after the start, not at once"
    assert after_blocked == updater_module.RETRY_EVERY_S
    assert 0.9 * DAY <= after_staged <= 1.1 * DAY


def test_a_start_soon_after_a_check_does_not_check_again_at_once(rig: Rig) -> None:
    rig.store.write_state({"last_check": NOW - 3600})
    waits: list[float] = []

    class Stop:
        def wait(self, timeout: float | None = None) -> bool:
            waits.append(timeout or 0)
            return True

    rig.updater.run_forever(Stop())  # type: ignore[arg-type]

    assert waits[0] == pytest.approx(DAY - 3600)


# ------------------------------------------------------------------------------------------------ the restart


class Quiet:
    def __init__(self) -> None:
        self.now = 1000.0
        self.pending: str | None = "2026.10.02"
        self.busy = False
        self.restarts = 0
        self.restarter = Restarter(
            pending=lambda: self.pending, busy=lambda: self.busy, restart=self._restart, quiet_s=60.0, clock=lambda: self.now
        )

    def _restart(self) -> None:
        self.restarts += 1

    def after(self, seconds: float) -> bool:
        self.now += seconds
        return self.restarter.poll()


def test_the_server_restarts_only_after_a_full_minute_of_quiet() -> None:
    q = Quiet()

    assert q.after(0) is False
    assert q.after(59) is False and q.restarts == 0
    assert q.after(2) is True and q.restarts == 1


def test_anything_going_through_the_server_starts_the_minute_again() -> None:
    q = Quiet()
    q.after(0)
    q.after(50)
    q.busy = True
    assert q.after(10) is False
    q.busy = False
    assert q.after(0) is False
    assert q.after(59) is False
    assert q.after(2) is True


def test_a_server_that_is_never_quiet_is_never_restarted_and_says_so_once_an_hour(caplog: pytest.LogCaptureFixture) -> None:
    q = Quiet()
    q.busy = True

    with caplog.at_level(logging.INFO, logger=LOG):
        for _ in range(100):
            q.after(60)

    assert q.restarts == 0, "no force, however long it takes"
    assert caplog.text.count("waiting for a quiet moment") == 2


def test_a_restart_that_did_not_switch_is_not_repeated_for_the_same_version(caplog: pytest.LogCaptureFixture) -> None:
    tried: set[str] = set()
    now = {"t": 0.0}
    restarts: list[str] = []
    restarter = Restarter(
        pending=lambda: "2026.10.02",
        busy=lambda: False,
        restart=lambda: restarts.append("2026.10.02"),
        quiet_s=60.0,
        clock=lambda: now["t"],
        tried=lambda version: version in tried,
        note_tried=tried.add,
    )

    restarter.poll()
    now["t"] += 61
    assert restarter.poll() is True and tried == {"2026.10.02"}

    with caplog.at_level(logging.WARNING, logger=LOG):
        for _ in range(50):  # the server came back still pending, and is quiet for hours
            now["t"] += 600
            assert restarter.poll() is False

    assert restarts == ["2026.10.02"], "one restart per version, whatever went wrong with the first"
    assert caplog.text.count("not restarting for it again") == 1


def test_a_newer_version_gets_its_own_restart() -> None:
    seen: set[str] = set()  # the marker on disk: it outlives the process
    restarts: list[str] = []

    def new_process(pending: str, now: float) -> tuple[Restarter, dict[str, float]]:
        clock = {"t": now}
        return (
            Restarter(
                pending=lambda: pending,
                busy=lambda: False,
                restart=lambda: restarts.append(pending),
                quiet_s=60.0,
                clock=lambda: clock["t"],
                tried=seen.__contains__,
                note_tried=seen.add,
            ),
            clock,
        )

    first, clock = new_process("2026.10.02", 0.0)
    first.poll()
    clock["t"] += 61
    assert first.poll() is True

    again, clock = new_process("2026.10.02", 0.0)  # the server came back, still pending for the same version
    again.poll()
    clock["t"] += 61
    assert again.poll() is False

    newer, clock = new_process("2026.10.03", 0.0)  # a newer release was staged since
    newer.poll()
    clock["t"] += 61
    assert newer.poll() is True and restarts == ["2026.10.02", "2026.10.03"]


def test_the_restart_marker_survives_and_is_per_version(tmp_path: Path) -> None:
    store = ToolStore(tmp_path)
    assert store.restarted_for() is None

    store.note_restart("2026.10.02")

    assert store.restarted_for() == "2026.10.02"
    assert ToolStore(tmp_path).restarted_for() == "2026.10.02", "it is on disk, so a restart does not forget it"


def test_a_version_whose_first_restart_did_not_take_gets_one_more_when_it_is_staged_again(rig: Rig) -> None:
    from encore_server.sources.youtube.tools import activate

    rig.release("2026.10.02", 3 * DAY)
    rig.updater.check_once()
    rig.store.note_restart("2026.10.02")  # the server restarted for it ...
    wheel = rig.store.wheels / "yt_dlp-2026.10.02-py3-none-any.whl"
    wheel.write_bytes(b"cut")  # ... and the start could not use it (a transient disk problem)
    assert activate(rig.store, image="2026.10.01") is None and rig.store.restarted_for() == "2026.10.02"

    assert rig.updater.check_once() == "staged", "the next daily check fetches it again"

    assert rig.store.restarted_for() is None, "so the restarter may restart once more for it, and not for ever"


def test_a_pointer_that_the_start_could_not_use_is_no_longer_pending_so_no_restart_loop_can_begin(
    tmp_path: Path, rig: Rig
) -> None:
    from encore_server.sources.youtube.tools import activate

    rig.release("2026.10.02", 3 * DAY)
    assert rig.updater.check_once() == "staged" and rig.updater.pending() == "2026.10.02"
    wheel = rig.store.wheels / "yt_dlp-2026.10.02-py3-none-any.whl"
    wheel.write_bytes(wheel.read_bytes()[:5])  # the disk let it down between the check and the restart

    assert activate(rig.store, image="2026.10.01") is None  # the next start

    assert rig.updater.pending() is None, "the restarter has nothing to wait for"
    assert rig.updater.check_once() == "staged", "and the next daily check fetches the release again"


def test_nothing_pending_nothing_restarts() -> None:
    q = Quiet()
    q.pending = None

    assert not any(q.after(600) for _ in range(5)) and q.restarts == 0


def test_the_restarter_survives_a_failing_look_and_stops_after_restarting() -> None:
    calls = {"n": 0}

    def pending() -> str | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk gone")
        return "2026.10.02"

    now = {"t": 0.0}
    restarter = Restarter(pending=pending, busy=lambda: False, restart=lambda: None, quiet_s=0.0, clock=lambda: now["t"])

    class Stop:
        def __init__(self) -> None:
            self.waits = 0

        def wait(self, timeout: float | None = None) -> bool:
            self.waits += 1
            return self.waits > 10

    stop = Stop()
    restarter.run_forever(stop, poll_s=1.0)  # type: ignore[arg-type]

    assert calls["n"] == 2 and stop.waits == 2, "the first look failed, the second started the restart, and then the loop ended"


def test_restarting_the_process_sends_the_clean_stop_and_arms_the_hard_one(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[int, int]] = []
    armed: list[tuple[float, Any]] = []

    class FakeTimer:
        def __init__(self, interval: float, function: Any, args: tuple[Any, ...] = ()) -> None:
            armed.append((interval, function))

        def start(self) -> None:
            pass

    monkeypatch.setattr(updater_module.threading, "Timer", FakeTimer)
    monkeypatch.setattr(updater_module.os, "kill", lambda pid, sig: sent.append((pid, int(sig))))

    updater_module.restart_process()

    assert sent == [(os.getpid(), int(updater_module.signal.SIGTERM))]
    assert armed == [(30.0, os._exit)]


def test_tools_starts_both_loops_and_stops_them() -> None:
    started: list[str] = []
    gate = threading.Event()

    class Loop:
        def __init__(self, name: str) -> None:
            self.name = name

        def run_forever(self, stop: threading.Event) -> None:
            started.append(self.name)
            gate.set()
            stop.wait(30)

    tools = Tools(Loop("updater"), Loop("restarter"))  # type: ignore[arg-type]
    tools.start()
    gate.wait(5)
    tools.stop()

    assert sorted(started) == ["restarter", "updater"] and tools._threads == []


# ------------------------------------------------------------------------------------------------ the canary in a child process


def completed(stdout: str, stderr: str = "", code: int = 0) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=code)


def test_the_child_gets_the_candidate_first_on_its_path_and_the_running_copy_when_there_is_no_candidate() -> None:
    cand, active, sep = Path("/cand.whl"), Path("/active.whl"), os.pathsep
    base = {"PYTHONPATH": f"{active}{sep}/elsewhere", "KEEP": "1"}

    assert child_env(cand, active, base)["PYTHONPATH"] == f"{cand}{sep}/elsewhere"
    assert child_env(None, active, base)["PYTHONPATH"] == f"{active}{sep}/elsewhere"
    assert child_env(None, None, {"PYTHONPATH": "/x"})["PYTHONPATH"] == "/x"
    assert "PYTHONPATH" not in child_env(None, None, {"A": "b"}) and child_env(None, None, base)["KEEP"] == "1"


def test_a_child_that_answers_ok_is_a_pass_and_its_version_is_kept() -> None:
    seen: dict[str, Any] = {}

    def run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        seen.update(argv=argv, **kwargs)
        return completed('log noise\n{"ok": true, "version": "2026.10.02", "bytes": 65536}\n')

    child = ChildCanary(Path("/cand.whl"), run=run)
    child.extract(CANARY_VIDEO, Path(os.devnull))

    assert child.version == "2026.10.02"
    assert seen["argv"][1:] == ["-m", "encore_server.sources.youtube.canary", CANARY_VIDEO]
    assert seen["env"]["PYTHONPATH"].startswith(str(Path("/cand.whl"))) and seen["timeout"] == 150.0


@pytest.mark.parametrize("code", ["blocked", "not_found", "timeout", "download_failed"])
def test_a_child_that_answers_not_ok_raises_the_error_it_reported(code: str) -> None:
    child = ChildCanary(
        None, run=lambda argv, **kw: completed(json.dumps({"ok": False, "code": code, "message": "m" * 400, "version": "1.2.3"}))
    )

    with pytest.raises(DownloadError) as error:
        child.extract(CANARY_VIDEO, Path(os.devnull))

    assert error.value.code == code and len(str(error.value)) <= 300 and child.version == "1.2.3"


@pytest.mark.parametrize("stdout", ["", "not json at all", "[1, 2]", '{"nothing": 1}'])
def test_a_child_that_gives_no_answer_is_a_failure_with_the_last_line_of_what_it_said(stdout: str) -> None:
    child = ChildCanary(None, run=lambda argv, **kw: completed(stdout, "Traceback...\nImportError: no module named x", 1))

    with pytest.raises(DownloadError, match="ImportError: no module named x") as error:
        child.extract(CANARY_VIDEO, Path(os.devnull))

    assert error.value.code == "download_failed"


def test_a_child_that_takes_too_long_or_cannot_start_is_a_failure() -> None:
    def too_slow(argv: list[str], **kw: Any) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(argv, 1)

    def cannot(argv: list[str], **kw: Any) -> SimpleNamespace:
        raise FileNotFoundError("python")

    with pytest.raises(DownloadError) as slow:
        ChildCanary(None, run=too_slow).extract(CANARY_VIDEO, Path(os.devnull))
    with pytest.raises(DownloadError) as missing:
        ChildCanary(None, run=cannot).extract(CANARY_VIDEO, Path(os.devnull))

    assert slow.value.code == "timeout" and missing.value.code == "download_failed"


# ------------------------------------------------------------------------------------------------ what the child does


class Body:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeSource:
    def __init__(self, chunks: list[bytes] | Exception) -> None:
        self.chunks = chunks
        self.asked: list[tuple[str | None, str | None]] = []
        self.body: Body | None = None

    def open(self, wanted: Any, range_header: str | None) -> Any:
        self.asked.append((wanted.video_id, range_header))
        if isinstance(self.chunks, Exception):
            raise self.chunks
        self.body = Body(self.chunks)
        return SimpleNamespace(status=206, headers={}, body=iter(self.chunks), close=self.body.close)


def run_check(source: FakeSource) -> dict[str, Any]:
    return canary_module.check(CANARY_VIDEO, source_factory=lambda tmp: source)


def test_the_child_asks_the_servers_own_source_for_the_first_64_kb_of_the_fixed_video() -> None:
    source = FakeSource([b"x" * 40000, b"x" * 40000, b"x" * 40000])

    answer = run_check(source)

    assert answer["ok"] is True and answer["bytes"] >= READ_BYTES and isinstance(answer["version"], str)
    assert source.asked == [(CANARY_VIDEO, f"bytes=0-{READ_BYTES - 1}")]
    assert source.body is not None and source.body.closed, "the connection is let go"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (StreamError("blocked"), "blocked"),
        (StreamError("slow"), "timeout"),
        (StreamError("not_found"), "not_found"),
        (StreamError("failed"), "download_failed"),
        (DownloadError("age_restricted", "age"), "age_restricted"),
    ],
)
def test_the_childs_answer_names_what_went_wrong_in_the_codes_the_server_uses(error: Exception, code: str) -> None:
    answer = run_check(FakeSource(error))

    assert answer["ok"] is False and answer["code"] == code


def test_an_unexpected_failure_and_a_nearly_empty_answer_are_failed_checks_not_crashes() -> None:
    boom = run_check(FakeSource(RuntimeError("player code changed")))
    short = run_check(FakeSource([b"x" * 10]))

    assert boom["ok"] is False and boom["code"] == "download_failed" and "RuntimeError: player code changed" in boom["message"]
    assert short["ok"] is False and "only 10 bytes" in short["message"]


def test_main_prints_one_json_line(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(canary_module, "check", lambda video: {"ok": True, "version": "1", "video": video})

    assert canary_module.main(["abc"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "version": "1", "video": "abc"}


# ------------------------------------------------------------------------------------------------ the canary and the server's YouTube budget


class Glue:
    """`create_tools` against a fake PyPI and a fake child, with a real Rest, Lookups and a pacer that counts."""

    def __init__(self, tmp_path: Path, answer: dict[str, Any] | None = None) -> None:
        self.now = NOW
        self.rest = Rest(clock=lambda: self.now)
        self.lookups = Lookups(clock=lambda: self.now)
        self.turns = 0
        self.children: list[dict[str, Any]] = []
        self.answer = answer if answer is not None else {"ok": True, "version": "2026.10.02", "bytes": 65536}
        self.restarts = 0
        data = b"wheel 2026.10.02"
        file = wheel_file("2026.10.02", 3 * DAY)
        file["digests"]["sha256"] = hashlib.sha256(data).hexdigest()
        meta = pypi({"2026.10.02": [file]})

        def pypi_handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "pypi.org":
                return httpx.Response(200, json=meta)
            return httpx.Response(200, content=data)

        def run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
            self.children.append({"argv": argv, "env": kwargs["env"]})
            return completed(json.dumps(self.answer))

        self.store = ToolStore(tmp_path / "tools")
        self.tools = create_tools(
            self.store,
            None,
            rest=self.rest,
            lookups=self.lookups,
            wait_turn=self._turn,
            busy=lambda: False,
            client=httpx.Client(transport=httpx.MockTransport(pypi_handler)),
            restart=lambda: setattr(self, "restarts", self.restarts + 1),
            run=run,
            image="2026.10.01",
        )
        self.tools.updater.running = "2026.10.01"
        self.tools.updater._clock = lambda: self.now  # type: ignore[assignment]

    def _turn(self) -> float:
        self.turns += 1
        return 0.0


def test_the_real_canary_takes_the_pacers_turn_and_is_counted_as_a_look_up_and_tests_the_candidate(tmp_path: Path) -> None:
    glue = Glue(tmp_path)

    assert glue.tools.updater.check_once() == "staged"

    assert glue.turns == 1 and glue.lookups.today == 1, "the child cannot count, so the parent does"
    assert len(glue.children) == 1 and glue.children[0]["env"]["PYTHONPATH"].startswith(str(glue.store.wheels))
    assert glue.tools.updater.pending() == "2026.10.02"


def test_while_youtube_is_resting_the_canary_does_not_run_at_all(tmp_path: Path) -> None:
    glue = Glue(tmp_path)
    glue.rest.blocked()

    assert glue.tools.updater.check_once() == "blocked"

    assert glue.children == [] and glue.turns == 0 and glue.lookups.today == 0 and glue.store.read_pointer() is None


def test_a_refusal_during_the_canary_starts_the_rest_for_the_whole_server(tmp_path: Path) -> None:
    glue = Glue(
        tmp_path, {"ok": False, "code": "blocked", "message": "Sign in to confirm you're not a bot", "version": "2026.10.02"}
    )

    assert glue.tools.updater.check_once() == "blocked"

    assert glue.rest.remaining() > 0, "the refusal is fed to the same rest every other look-up obeys"
    assert glue.store.read_pointer() is None and "bad" not in glue.store.read_state()


def test_a_child_that_ran_another_version_than_the_candidate_is_a_failed_check(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    glue = Glue(tmp_path, {"ok": True, "version": "2026.10.01", "bytes": 65536})

    with caplog.at_level(logging.WARNING, logger=LOG):
        outcome = glue.tools.updater.check_once()

    assert outcome == "candidate-failed" and glue.store.read_pointer() is None
    assert "and not the 2026.10.02 it was meant to test" in caplog.text


def test_a_fixed_video_that_youtube_says_is_gone_is_not_a_verdict(tmp_path: Path) -> None:
    glue = Glue(tmp_path, {"ok": False, "code": "unavailable", "message": "Video unavailable", "version": "2026.10.02"})

    assert glue.tools.updater.check_once() == "cannot-check"


# ------------------------------------------------------------------------------------------------ one way to run yt-dlp


def test_the_playlist_fallback_runs_the_same_yt_dlp_as_the_rest_of_the_server() -> None:
    from encore_server.imports.readers import ytdlp_reader

    seen: dict[str, Any] = {}

    def run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        seen["argv"] = argv
        return completed(json.dumps({"title": "T", "entries": []}))

    ytdlp_reader(run=run)("https://www.youtube.com/playlist?list=PL1")

    import sys

    assert seen["argv"][:4] == [sys.executable, "-m", "yt_dlp", "--flat-playlist"], (
        "not the `yt-dlp` command, which ignores the switched copy"
    )


def test_no_code_starts_a_yt_dlp_command() -> None:
    """A command would run the image's copy whatever the server switched to; every use goes through the interpreter and `PYTHONPATH`."""
    root = Path(canary_module.__file__).resolve().parents[2]
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"""\[\s*["']yt-dlp["']""", text) or re.search(r"""shutil\.which\(\s*["']yt-dlp["']""", text):
            offenders.append(str(path.relative_to(root)))
    assert offenders == []
