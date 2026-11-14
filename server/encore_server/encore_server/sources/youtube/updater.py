"""Keeping yt-dlp fresh without anyone running a command (docs/11 ADR-R39, docs/22 section 2).

Once a day the [Updater] asks PyPI for a yt-dlp newer than the one running, older than 24 hours. If there is one it downloads the wheel, checks it
against PyPI's checksum, and runs the canary (canary.py) with the wheel first on a child process's import path. Only a pass writes the pointer
(tools.py). The [Restarter] then waits until nothing is going through the server (quiet.py) and ends the process; Docker starts it again and it
starts on the new copy. Nothing in the running process ever changes, and nothing here forces a restart: a server that is never quiet keeps its copy.

The canary is a look-up at YouTube from the Host's address, so it takes the pacer's turn, does not run while the server rests, is counted with the
others, and a refusal during it starts the rest like any other (`rest.Guarded`). At most [MAX_CANARIES_PER_DAY] of them a day.
"""

from __future__ import annotations

import logging
import os
import random
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ...stopping import join_within
from .canary import CANARY_VIDEO, ChildCanary
from .errors import DownloadError
from .rest import Guarded, Lookups, Rest
from .tools import Active, Pointer, Release, ToolStore, image_version, newest_eligible, running_version, version_key

log = logging.getLogger("encore_server.youtube.updater")

PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
#: A healthy day uses none or one; a day on which a candidate fails uses two (the candidate, then the running copy) and may retry once.
MAX_CANARIES_PER_DAY = 4
CHECK_EVERY_S = 24 * 3600.0
RETRY_EVERY_S = 3600.0
#: What the canary can say: the copy works / YouTube was not asked or refused (no verdict) / the fixed video is gone (no verdict) / the copy fails.
Verdict = str


class Updater:
    def __init__(
        self,
        *,
        store: ToolStore,
        active: Active | None,
        fetch_meta: Callable[[], dict[str, Any]],
        fetch_wheel: Callable[[Release], bytes],
        canary: Callable[[Path | None, str | None], Verdict],
        image: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._active = active
        self._fetch_meta = fetch_meta
        self._fetch_wheel = fetch_wheel
        self._canary = canary
        self._image = image if image is not None else image_version()
        self._clock = clock
        self._lock = threading.Lock()
        self.running = running_version(active)

    # ---------------------------------------------------------------- what the rest of the server may ask

    def pending(self) -> str | None:
        """The version that is ready and waits for a quiet moment to be switched to, if any."""
        pointer = self._store.read_pointer()
        if pointer is None:
            return None
        wanted, have = version_key(pointer.version), version_key(self.running)
        return pointer.version if wanted is not None and (have is None or wanted > have) else None

    def degraded(self) -> bool:
        return bool(self._store.read_state().get("degraded"))

    def status(self) -> dict[str, Any]:
        return {"ytDlp": {"running": self.running, "pending": self.pending(), "state": "degraded" if self.degraded() else "ok"}}

    # ---------------------------------------------------------------- one check

    def check_once(self) -> str:
        """One pass. Returns what happened, for the log and the tests: `budget`, `offline`, `up-to-date`, `recovered`, `still-degraded`,
        `download-failed`, `staged`, `blocked`, `cannot-check`, `candidate-failed`, `degraded`."""
        with self._lock:
            return self._check()

    def _check(self) -> str:
        now = self._clock()
        state = self._store.read_state()
        if self._runs_today(state, now) >= MAX_CANARIES_PER_DAY:
            return "budget"
        try:
            meta = self._fetch_meta()
        except (httpx.HTTPError, ValueError) as error:
            log.info("yt-dlp: PyPI could not be asked (%s); trying again later", error)
            return "offline"
        state["last_check"] = now
        pointer = self._store.read_pointer()
        floor = max(
            (
                k
                for k in (
                    version_key(self._image or ""),
                    version_key(self.running),
                    version_key(pointer.version) if pointer else None,
                )
                if k
            ),
            default=(),
        )
        release = newest_eligible(meta, now=now, above=floor, skip=state.get("bad", []))
        if release is None:
            outcome = self._recheck_running(state, now) if state.get("degraded") else "up-to-date"
            self._store.write_state(state)
            return outcome
        try:
            wheel = self._store.save_wheel(release, self._fetch_wheel(release))
        except (httpx.HTTPError, ValueError, OSError) as error:
            log.warning("yt-dlp %s could not be fetched (%s); trying again later", release.version, error)
            self._store.write_state(state)
            return "download-failed"
        self._spend(state, now)
        verdict = self._canary(wheel, release.version)
        if verdict == "ok":
            self._store.write_pointer(Pointer(release.version, release.filename, release.sha256))
            self._store.clear_restart_note()  # a fresh staging earns its one restart, even if an earlier one of the same version did not take
            self._keep_only_needed()
            state["degraded"] = False
            self._store.write_state(state)
            log.info(
                "yt-dlp %s is ready and passed the check on the path that plays songs; the server switches to it at its next start, "
                "which waits for a quiet moment (now running %s)",
                release.version,
                self.running,
            )
            return "staged"
        if verdict == "blocked":
            self._store.write_state(state)
            log.info("yt-dlp %s was not checked: YouTube is resting or refused the check; trying again later", release.version)
            return "blocked"
        if verdict == "gone":
            self._store.write_state(state)
            log.warning(
                "yt-dlp %s was not checked: the fixed video of the check is not available; nothing is changed", release.version
            )
            return "cannot-check"
        # The candidate failed. Is it the candidate, or YouTube? Only the running copy can tell: it passes -> the release is bad and is never used;
        # it fails too -> YouTube is broken for everybody, and this release may be the one that fixes it, so it stays eligible.
        outcome = "candidate-failed"
        running_verdict = "blocked"
        if self._runs_today(state, now) < MAX_CANARIES_PER_DAY:
            running_verdict = self._canary(self._active.wheel if self._active else None, None)
            if running_verdict != "blocked":
                self._spend(state, now)
        if running_verdict == "ok":
            state.setdefault("bad", []).append(release.version)
            state["degraded"] = False
            log.warning("yt-dlp %s failed the check and is not used; staying on %s, which works", release.version, self.running)
        elif running_verdict == "failed":
            state["degraded"] = True
            outcome = "degraded"
            log.warning(
                "songs from YouTube are not working right now: neither yt-dlp %s nor the newer %s passed the check; trying again every hour",
                self.running,
                release.version,
            )
        else:
            log.warning(
                "yt-dlp %s failed the check; whether %s still works could not be told, so it will be tried again",
                release.version,
                self.running,
            )
        self._keep_only_needed()
        self._store.write_state(state)
        return outcome

    def _recheck_running(self, state: dict[str, Any], now: float) -> str:
        verdict = self._canary(self._active.wheel if self._active else None, None)
        if verdict != "blocked":
            self._spend(state, now)
        if verdict == "ok":
            state["degraded"] = False
            log.info("songs from YouTube work again with yt-dlp %s", self.running)
            return "recovered"
        return "still-degraded"

    def _keep_only_needed(self) -> None:
        pointer = self._store.read_pointer()
        keep = {pointer.wheel} if pointer else set()
        if self._active is not None:
            keep.add(self._active.wheel.name)
        self._store.prune(keep)

    @staticmethod
    def _runs_today(state: dict[str, Any], now: float) -> int:
        return int(state.get("runs", 0)) if state.get("day") == int(now // 86400) else 0

    def _spend(self, state: dict[str, Any], now: float) -> None:
        today = int(now // 86400)
        state["runs"] = self._runs_today(state, now) + 1
        state["day"] = today

    # ---------------------------------------------------------------- the daily rhythm

    def run_forever(self, stop: threading.Event, *, rng: random.Random | None = None) -> None:
        rng = rng or random.Random()
        last = float(self._store.read_state().get("last_check", 0.0))
        delay = max(rng.uniform(300.0, 1800.0), last + CHECK_EVERY_S - self._clock())
        while not stop.wait(delay):
            try:
                outcome = self.check_once()
            except Exception:  # noqa: BLE001 - the updater must outlive any one bad pass
                log.exception("the yt-dlp check failed unexpectedly")
                outcome = "offline"
            soon = outcome in ("offline", "budget", "blocked", "download-failed", "degraded", "still-degraded")
            delay = RETRY_EVERY_S if soon else CHECK_EVERY_S * rng.uniform(0.9, 1.1)


class Restarter:
    """Ends the process when a newer yt-dlp is waiting and nothing has gone through the server for [quiet_s]. Never forces."""

    def __init__(
        self,
        *,
        pending: Callable[[], str | None],
        busy: Callable[[], bool],
        restart: Callable[[], None],
        quiet_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        tried: Callable[[str], bool] = lambda version: False,
        note_tried: Callable[[str], None] = lambda version: None,
    ) -> None:
        self._pending = pending
        self._busy = busy
        self._restart = restart
        self._quiet_s = quiet_s
        self._clock = clock
        self._tried = tried
        self._note_tried = note_tried
        self._quiet_since: float | None = None
        self._told_at: float | None = None
        self._told_giving_up = False

    def poll(self) -> bool:
        """One look. True when the restart was started."""
        version = self._pending()
        if version is None:
            self._quiet_since = None
            return False
        if self._tried(version):
            # One restart per version: if it did not take, another will not either, and a restart every minute helps nobody.
            if not self._told_giving_up:
                self._told_giving_up = True
                log.warning(
                    "the server already restarted once to switch to yt-dlp %s and is not running it; not restarting for it again",
                    version,
                )
            return False
        now = self._clock()
        if self._busy():
            self._quiet_since = None
            if self._told_at is None or now - self._told_at >= 3600:
                self._told_at = now
                log.info("a newer yt-dlp (%s) is ready; waiting for a quiet moment to switch to it", version)
            return False
        if self._quiet_since is None:
            self._quiet_since = now
        if now - self._quiet_since < self._quiet_s:
            return False
        log.info("nothing has gone through the server for %d s: restarting to switch to yt-dlp %s", int(self._quiet_s), version)
        self._note_tried(version)
        self._restart()
        return True

    def run_forever(self, stop: threading.Event, *, poll_s: float = 5.0) -> None:
        while not stop.wait(poll_s):
            try:
                if self.poll():
                    return
            except Exception:  # noqa: BLE001 - a failed look must not end the watching
                log.exception("the quiet-moment check failed unexpectedly")


def restart_process() -> None:
    """A clean end (uvicorn finishes the requests that are open); Docker's `restart: unless-stopped` starts the server again. If it has not
    ended after 30 s, it is ended."""
    threading.Timer(30.0, os._exit, args=(0,)).start()
    os.kill(os.getpid(), signal.SIGTERM)


class Tools:
    """The updater and the restarter as the server owns them: started with its background work, stopped with it."""

    def __init__(self, updater: Updater, restarter: Restarter) -> None:
        self.updater = updater
        self.restarter = restarter
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def status(self) -> dict[str, Any]:
        return self.updater.status()

    def start(self) -> None:
        self._stop.clear()
        for name, target in (("ytdlp-updater", self.updater.run_forever), ("ytdlp-restarter", self.restarter.run_forever)):
            thread = threading.Thread(target=target, args=(self._stop,), name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        join_within(self._threads, timeout)
        self._threads.clear()


def create_tools(
    store: ToolStore,
    active: Active | None,
    *,
    rest: Rest,
    lookups: Lookups,
    wait_turn: Callable[[], float] | None,
    busy: Callable[[], bool],
    client: httpx.Client | None = None,
    restart: Callable[[], None] = restart_process,
    run: Callable[..., Any] = subprocess.run,
    image: str | None = None,
) -> Tools:
    """The real thing: PyPI over HTTPS, the canary in a child process, the server's own rest, pacer turn and look-up counter."""
    http = client or httpx.Client(
        timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True, headers={"User-Agent": "Encore-server (yt-dlp updater)"}
    )

    def fetch_meta() -> dict[str, Any]:
        response = http.get(PYPI_URL)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("PyPI's answer is not a mapping")
        return data

    def fetch_wheel(release: Release) -> bytes:
        response = http.get(release.url)
        response.raise_for_status()
        return response.content

    def canary(wheel: Path | None, expect: str | None) -> Verdict:
        if rest.remaining() > 0:
            return "blocked"
        if wait_turn is not None:
            wait_turn()
        child = ChildCanary(wheel, active=active.wheel if active else None, run=run)
        try:
            Guarded(child, rest, lookups).extract(CANARY_VIDEO, Path(os.devnull))
        except DownloadError as error:
            log.info("the yt-dlp check did not pass (%s): %s", error.code, error)
            if error.code == "blocked":
                return "blocked"
            if error.code in ("not_found", "unavailable", "age_restricted"):
                return "gone"
            return "failed"
        if expect is not None and child.version != expect:
            log.warning("the check ran yt-dlp %s and not the %s it was meant to test", child.version, expect)
            return "failed"
        return "ok"

    updater = Updater(store=store, active=active, fetch_meta=fetch_meta, fetch_wheel=fetch_wheel, canary=canary, image=image)
    return Tools(
        updater,
        Restarter(
            pending=updater.pending,
            busy=busy,
            restart=restart,
            # Written before the restart, so that a restart that does not switch cannot be repeated for the same version.
            tried=lambda version: store.restarted_for() == version,
            note_tried=store.note_restart,
        ),
    )
