"""When YouTube pushes back, the whole server rests: background work does not even try, a tap probes now and then, each refusal in a row
doubles the rest, one success ends it, and a restart does not forget."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.scheduler import Retry, WorkItem
from encore_server.sources.youtube.errors import DownloadError
from encore_server.sources.youtube.rest import DbRestStore, Guarded, Lookups, Rest
from tests.conftest import FakeVerifier, creds, resolve, song
from tests.test_keeper import Rig as KeeperRig


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_the_first_refusal_rests_for_half_an_hour_and_each_one_in_a_row_doubles_it() -> None:
    clock = Clock()
    rest = Rest(clock=clock)

    rest.blocked()
    assert rest.remaining() == 1800
    clock.now += 1801
    assert rest.remaining() == 0

    rest.blocked()
    assert rest.remaining() == 3600
    clock.now += 3601
    rest.blocked()
    assert rest.remaining() == 7200


def test_the_rest_never_goes_past_a_day_and_one_success_ends_it() -> None:
    rest = Rest(clock=Clock())
    for _ in range(12):
        rest.blocked()
    assert rest.remaining() == 24 * 3600

    rest.ok()

    assert rest.remaining() == 0 and rest.snapshot() == {"state": "ok", "resumesInSec": 0}
    rest.blocked()
    assert rest.remaining() == 1800, "the doubling starts again after a success"


def test_while_resting_a_tap_may_probe_once_in_a_while_and_nothing_else_may() -> None:
    clock = Clock()
    rest = Rest(clock=clock, probe_every_s=30)
    assert rest.allow_probe() is True

    rest.blocked()
    assert rest.allow_probe() is True, "the first tap after a refusal checks whether it is over"
    assert rest.allow_probe() is False
    clock.now += 31
    assert rest.allow_probe() is True


def test_the_rest_is_remembered_across_a_restart(tmp_path: Path) -> None:
    db = Database(tmp_path / "e.db")
    db.migrate()
    clock = Clock()
    Rest(clock=clock, store=DbRestStore(db)).blocked()

    after_restart = Rest(clock=clock, store=DbRestStore(db))

    assert after_restart.remaining() == 1800 and after_restart.snapshot()["state"] == "resting"
    after_restart.ok()
    assert Rest(clock=clock, store=DbRestStore(db)).remaining() == 0


class Inner:
    def __init__(self) -> None:
        self.calls = 0
        self.failure: DownloadError | None = None

    def extract(self, video_id: str, info: Path, cookiefile: str | None = None) -> None:
        self.calls += 1
        if self.failure is not None:
            raise self.failure


def test_a_guarded_extractor_stops_asking_once_refused_and_ends_the_rest_when_a_probe_gets_through() -> None:
    clock = Clock()
    rest = Rest(clock=clock, probe_every_s=30)
    inner = Inner()
    guarded = Guarded(inner, rest)
    inner.failure = DownloadError("blocked")

    with pytest.raises(DownloadError):
        guarded.extract("v", Path("x"))
    for _ in range(5):
        with pytest.raises(DownloadError) as caught:
            guarded.extract("v", Path("x"))
        assert caught.value.code == "blocked"
    assert inner.calls == 2, "the refusal, and one probe: the other four never reached YouTube"

    clock.now += 40
    inner.failure = None
    guarded.extract("v", Path("x"))

    assert rest.remaining() == 0 and inner.calls == 3


def test_a_video_that_is_gone_is_not_a_reason_to_rest() -> None:
    rest = Rest(clock=Clock())
    inner = Inner()
    inner.failure = DownloadError("unavailable")

    with pytest.raises(DownloadError):
        Guarded(inner, rest).extract("v", Path("x"))

    assert rest.remaining() == 0


def test_the_keeper_waits_out_the_rest_without_asking(tmp_path: Path, db: Database) -> None:
    rig = KeeperRig(tmp_path, db)
    ref = rig.make_ref()
    rig.source.resting = 1234.0

    with pytest.raises(Retry) as caught:
        rig.keep(ref)

    assert caught.value.after_s == 1234.0 and rig.source.asked == []


def test_a_refusal_while_keeping_waits_at_least_as_long_as_the_server_rests(tmp_path: Path, db: Database) -> None:
    rig = KeeperRig(tmp_path, db)
    ref = rig.make_ref()
    rig.source.failure = DownloadError("blocked")
    rig.source.resting = 0.0

    with pytest.raises(Retry) as caught:
        rig.keep(ref)
    assert caught.value.after_s == 900

    rig.source.resting_for = lambda: 3600.0  # type: ignore[method-assign]
    rig.source.failure = DownloadError("blocked")
    with pytest.raises(Retry) as again:
        rig.keep(ref)
    assert again.value.after_s == 3600.0


class Resting:
    """A source that is resting."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def resting_for(self) -> float:
        return self.seconds

    def status(self) -> dict[str, Any]:
        return {"state": "resting", "resumesInSec": int(self.seconds)}

    def open(self, wanted: Any, range_header: str | None) -> Any:
        from encore_server.sources.youtube.stream import StreamError

        raise StreamError("blocked")


def test_info_says_how_youtube_is_and_a_refused_tap_says_when_to_try_again(tmp_path: Path, verifier: FakeVerifier) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=Resting(1800))) as client:  # type: ignore[arg-type]
        info = client.get("/encore/api/v1/info").json()
        ref = str(resolve(client, "marwa", song())[0]["id"])
        url = client.get(f"/encore/api/v1/refs/{ref}/stream-url", params=creds("marwa")).json()["url"]
        refused = client.get(url)

    assert info["youtube"] == {"state": "resting", "resumesInSec": 1800}
    assert refused.status_code == 503
    body = refused.json()["error"]
    assert body["code"] == "source_busy" and body["retryable"] is True and body["retryAfterMs"] == 1_800_000


def test_a_server_without_youtube_says_off(tmp_path: Path, verifier: FakeVerifier) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as client:
        assert client.get("/encore/api/v1/info").json()["youtube"]["state"] == "off"


def test_matching_waits_out_the_rest_without_asking(tmp_path: Path, db: Database) -> None:
    from encore_server.imports.service import ImportService
    from encore_server.live import Hub

    class Finder(Resting):
        def find(self, wanted: Any) -> str | None:
            raise AssertionError("YouTube must not be asked while it rests")

    service = ImportService(db, Hub(), Finder(900))  # type: ignore[arg-type]

    with pytest.raises(Retry) as caught:
        service.match(WorkItem("wk_x", "match", "sr_x", 3, 1, ()))

    assert caught.value.after_s == 900


def test_the_look_ups_of_a_day_are_counted_and_told_to_the_log(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    lookups = Lookups(clock=clock, every=3)
    caplog.set_level("INFO", logger="encore_server.youtube")

    for _ in range(7):
        lookups.note()

    assert lookups.today == 7
    assert [r.getMessage() for r in caplog.records] == ["youtube look-ups today: 3", "youtube look-ups today: 6"]


def test_a_new_day_starts_the_count_again_and_says_what_the_last_one_was(caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    lookups = Lookups(clock=clock, every=100)
    caplog.set_level("INFO", logger="encore_server.youtube")
    lookups.note()
    lookups.note()

    clock.now += 86400

    assert lookups.today == 0, "nothing yet today"
    lookups.note()
    assert lookups.today == 1
    assert [r.getMessage() for r in caplog.records] == ["youtube look-ups yesterday: 2"]


def test_a_guarded_extractor_counts_the_look_ups_that_reach_youtube_not_the_ones_stopped_by_the_rest() -> None:
    clock = Clock()
    rest = Rest(clock=clock, probe_every_s=30)
    inner = Inner()
    guarded = Guarded(inner, rest)

    guarded.extract("a", Path("x"))
    guarded.extract("b", Path("x"))
    inner.failure = DownloadError("blocked")
    with pytest.raises(DownloadError):
        guarded.extract("c", Path("x"))
    for _ in range(4):
        with pytest.raises(DownloadError):
            guarded.extract("d", Path("x"))

    assert guarded.lookups.today == inner.calls == 4, (
        "two that worked, the refusal and one probe; the three others during the rest were never sent"
    )
