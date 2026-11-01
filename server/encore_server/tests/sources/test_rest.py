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


# ---------------------------------------------------------------------------------------------------- B8: the searches obey the rest too


class CountingResolver:
    """Stands for the search at YouTube Music: remembers how many times it was asked."""

    def __init__(self) -> None:
        self.asked = 0

    def resolve_ranked(self, want: Any) -> list[Any]:
        self.asked += 1
        return []


def _wanted() -> Any:
    from encore_server.sources.youtube.source import Wanted

    return Wanted(ref_id="sr_1", artist="A", title="T", album=None, duration_s=200, video_id=None)


def test_peeking_at_whether_a_probe_may_go_does_not_use_it_up() -> None:
    clock = Clock()
    rest = Rest(clock=clock, probe_every_s=30)
    rest.blocked()

    assert rest.probe_open() is True and rest.probe_open() is True, "looking does not spend it"
    assert rest.allow_probe() is True, "the tap that goes spends it"
    assert rest.probe_open() is False
    clock.now += 31
    assert rest.probe_open() is True


def test_while_youtube_rests_a_tap_makes_no_search_at_all(tmp_path: Path) -> None:
    """B8 (QA-BACKEND): the search ran BEFORE the guarded extractor, so every tap during a rest still made 2 to 3 YouTube Music searches,
    uncounted: a burst from the owner's home address that the rest exists to prevent."""
    from encore_server.sources.youtube.source import YoutubeSource

    clock = Clock()
    rest = Rest(clock=clock, probe_every_s=30)
    resolver = CountingResolver()
    youtube = YoutubeSource(tmp_path, resolver=resolver, extractor=Inner(), rest=rest)
    rest.blocked()
    assert rest.allow_probe() is True  # the first tap after the refusal has gone: its probe is spent

    for _ in range(5):
        with pytest.raises(Exception) as caught:  # noqa: PT011 - a StreamError with the code `blocked`
            youtube.open(_wanted(), None)
        assert getattr(caught.value, "code", None) == "blocked"

    assert resolver.asked == 0, "nothing was searched while YouTube rests"


def test_a_search_that_does_go_leaves_the_probe_to_the_extraction(tmp_path: Path) -> None:
    from encore_server.sources.youtube.source import YoutubeSource

    clock = Clock()
    rest = Rest(clock=clock, probe_every_s=30)
    resolver = CountingResolver()
    youtube = YoutubeSource(tmp_path, resolver=resolver, extractor=Inner(), rest=rest)
    rest.blocked()  # the window is open: the next tap may look

    with pytest.raises(Exception):  # noqa: B017, PT011 - nothing is found: not_found
        youtube.open(_wanted(), None)

    assert resolver.asked == 1
    assert rest.probe_open() is True, "the search did not spend the probe: the extraction still can"


def test_the_real_searcher_is_counted_per_search() -> None:
    from encore_server.sources.youtube.rest import CountedSearcher

    class Inner2:
        def songs(self, query: str, limit: int) -> list[dict[str, Any]]:
            return []

        def videos(self, query: str, limit: int) -> list[dict[str, Any]]:
            return []

    lookups = Lookups(clock=Clock())
    searcher = CountedSearcher(Inner2(), lookups)

    searcher.songs("a b", 8)
    searcher.songs("b a", 8)
    searcher.videos("b a", 8)

    assert lookups.today == 3, "a tap that is not clear-cut makes three: they are three requests"


def test_the_default_source_counts_its_own_searches_in_the_same_count_as_its_extractions(tmp_path: Path) -> None:
    """B8: without this, taking the counting wrapper out of `YoutubeSource` would break no test, and the number `encore logs` shows would go
    back to leaving the searches out."""
    from encore_server.sources.youtube.rest import CountedSearcher
    from encore_server.sources.youtube.source import YoutubeSource

    youtube = YoutubeSource(tmp_path)
    searcher = youtube._resolver._searcher  # type: ignore[attr-defined]  # noqa: SLF001 - the wiring is the point

    assert isinstance(searcher, CountedSearcher)
    assert searcher._lookups is youtube.lookups  # noqa: SLF001
