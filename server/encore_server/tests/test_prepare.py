"""Making the next songs of a queue ready (P1-04, audit B-107): the handler's rules and the route that asks for it."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from encore_server import refs
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.prepare import Preparer
from encore_server.scheduler import GiveUp, WorkItem
from encore_server.sources.youtube.errors import DownloadError
from encore_server.sources.youtube.source import Wanted
from encore_server.sources.youtube.stream import StreamError
from tests.conftest import FakeVerifier, creds, resolve, song
from tests.sources.test_stream import info_file
from tests.test_stream_route import DATA, V1, address
from tests.test_stream_route import Source as StreamSource


class Source:
    def __init__(self) -> None:
        self.asked: list[Wanted] = []
        self.found = True
        self.ready = False
        self.resting = 0.0
        self.error: Exception | None = None

    def is_ready(self, wanted: Wanted) -> bool:
        return self.ready

    def resting_for(self) -> float:
        return self.resting

    def prepare(self, wanted: Wanted) -> bool:
        self.asked.append(wanted)
        if self.error is not None:
            raise self.error
        return self.found


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_ref(db: Database, n: int = 1) -> str:
    with db.tx() as conn:
        return str(refs.resolve(conn, {"title": f"Song {n}", "artists": ["Artist"], "durationMs": 180000})["id"])


def item(ref: str) -> WorkItem:
    return WorkItem(id="wk_1", kind="prepare", ref=ref, priority=1, attempts=0, persons=())


def test_a_song_is_prepared_with_what_the_ref_knows(db: Database) -> None:
    source = Source()
    ref = make_ref(db)

    Preparer(db, source).handle(item(ref))

    assert [(w.ref_id, w.title, w.artist, w.duration_s) for w in source.asked] == [(ref, "Song 1", "Artist", 180)]


def test_a_song_the_server_keeps_is_not_prepared(db: Database) -> None:
    source = Source()
    ref = make_ref(db)
    with db.tx() as conn:
        refs.attach_file(conn, ref, navidrome_song_id="nd-1", path="a.opus", codec="opus", bitrate_kbps=130, source="youtube")

    Preparer(db, source).handle(item(ref))

    assert source.asked == []


def test_a_song_nobody_knows_is_given_up_not_retried(db: Database) -> None:
    with pytest.raises(GiveUp):
        Preparer(db, Source()).handle(item("sr_nobody"))


@pytest.mark.parametrize(
    "error",
    [DownloadError("blocked", "YouTube is being given a rest"), StreamError("slow"), DownloadError("download_failed", "x")],
)
def test_what_went_wrong_is_given_up_never_retried(db: Database, error: Exception) -> None:
    """A prepare that did not happen is not tried again: the person has pressed Next by then and the song is looked up as before."""
    source = Source()
    source.error = error
    with pytest.raises(GiveUp):
        Preparer(db, source).handle(item(make_ref(db)))


def test_no_upload_found_is_given_up(db: Database) -> None:
    source = Source()
    source.found = False
    with pytest.raises(GiveUp):
        Preparer(db, source).handle(item(make_ref(db)))


def test_skipping_through_a_long_list_cannot_become_a_burst(db: Database) -> None:
    """At most [per_hour] songs an hour, whoever asks: the pacer spaces the asking, this is the last stop. Nothing failed, so nothing is given up."""
    source = Source()
    clock = Clock()
    preparer = Preparer(db, source, per_hour=2, clock=clock)
    refs_ = [make_ref(db, n) for n in range(4)]

    preparer.handle(item(refs_[0]))
    preparer.handle(item(refs_[1]))
    preparer.handle(item(refs_[2]))
    assert len(source.asked) == 2, "the third was left to be looked up when it is played"

    clock.now += 3601.0
    preparer.handle(item(refs_[3]))
    assert len(source.asked) == 3


def test_a_song_that_needs_no_asking_costs_no_slot_of_the_hour(db: Database) -> None:
    """Listening in order prepares the next two songs each time, and the second was prepared when the song before it began: that is no request."""
    source = Source()
    preparer = Preparer(db, source, per_hour=1, clock=Clock())
    for n in range(5):
        source.ready = True
        preparer.handle(item(make_ref(db, n)))
    assert source.asked == []

    source.ready = False
    preparer.handle(item(make_ref(db, 9)))
    assert len(source.asked) == 1, "the one slot was still there"


def test_nothing_is_asked_and_nothing_fails_while_youtube_rests(db: Database) -> None:
    source = Source()
    source.resting = 120.0
    preparer = Preparer(db, source, per_hour=1, clock=Clock())

    preparer.handle(item(make_ref(db, 1)))

    assert source.asked == []
    source.resting = 0.0
    preparer.handle(item(make_ref(db, 2)))
    assert len(source.asked) == 1, "resting did not use the slot of the hour"


# ----------------------------------------------------------------------------------------------- the route


class PreparingSource(StreamSource):
    """The stream route's fake YouTube, with the address look-ups written down and `prepare` passed on."""

    def __init__(self, tmp: Path) -> None:
        self.extracted: list[str] = []
        inner = info_file(size=len(DATA))

        def extract(video_id, path):  # type: ignore[no-untyped-def]
            self.extracted.append(video_id)
            inner(video_id, path)

        super().__init__(tmp, extract=extract)

    def is_ready(self, wanted):  # type: ignore[no-untyped-def]
        return self.source.is_ready(wanted)

    def resting_for(self):  # type: ignore[no-untyped-def]
        return self.source.resting_for()

    def prepare(self, wanted):  # type: ignore[no-untyped-def]
        return self.source.prepare(wanted)


@pytest.fixture()
def prep(tmp_path: Path, verifier: FakeVerifier):  # type: ignore[no-untyped-def]
    source = PreparingSource(tmp_path / "work")
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=source)) as client:  # type: ignore[arg-type]
        yield client, source


def test_the_song_is_made_ready_before_it_is_played(prep) -> None:  # type: ignore[no-untyped-def]
    client, source = prep
    ref = resolve(client, "marwa", song())[0]["id"]

    response = client.post(f"{V1}/refs/prepare", params=creds("marwa"), json={"ids": [ref, ref, "sr_nobody"]})

    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == 1, "the same song once, the unknown song not at all"
    deadline = time.time() + 10
    while not source.extracted and time.time() < deadline:
        time.sleep(0.05)
    assert source.extracted == ["aaaaaaaaaaa"], "the background worker asked for the address"

    played = client.get(address(client, ref))
    assert played.status_code == 200
    assert source.extracted == ["aaaaaaaaaaa"], "the play found the address kept"


@pytest.mark.parametrize("body", [{}, {"ids": []}, {"ids": "x"}, {"ids": [1]}, {"ids": ["a", "b", "c", "d"]}])
def test_it_takes_one_to_three_songs(prep, body) -> None:  # type: ignore[no-untyped-def]
    client, _ = prep
    response = client.post(f"{V1}/refs/prepare", params=creds("marwa"), json=body)
    assert response.status_code in (400, 422), response.text
    assert response.json()["error"]["code"] == "validation"


def test_it_needs_a_login(prep) -> None:  # type: ignore[no-untyped-def]
    client, _ = prep
    assert client.post(f"{V1}/refs/prepare", json={"ids": ["x"]}).status_code in (401, 403)
