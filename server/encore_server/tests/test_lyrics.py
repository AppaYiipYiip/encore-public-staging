"""Lyrics on the server (docs/tasks P2-14, docs/11 ADR-R38): the phone stops asking LRCLIB itself, so a web or any other client gets the same words,
the person's address and what they play stay off a third party's logs, and one place remembers a miss sensibly (AUDIT F22: the phone remembered
"no lyrics" for a whole day even for a song that came out an hour ago).

LRCLIB is never really asked: a test gives the service a fake transport and counts what it was asked.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.lyrics import LyricsService, parse_lrc
from tests.conftest import FakeVerifier, creds, resolve, song

V1 = "/encore/api/v1"

SYNCED = "[ar:Radiohead]\n[00:12.50]First line\n[00:20.5][01:05.25]Chorus line\n[00:30.000]\n[00:41]Last line"
PLAIN = "[ar:Someone]\nLine one\nLine two\n\n\nLine three\n\n"
TAG_SHEET = "Artist: Pink Floyd\nAlbum: The Dark Side of the Moon\nTitle: Any Colour You Like"


class FakeLrclib:
    """What LRCLIB would answer: `exact` for /get (None = 404), `found` for /search; every question is written down."""

    def __init__(self) -> None:
        self.exact: dict[str, Any] | None = None
        self.found: list[dict[str, Any]] = []
        self.down: int | None = None  # an HTTP status to fail with, or None
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.gate: threading.Event | None = None
        self.entered = threading.Event()

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.url.path, dict(request.url.params)))
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(5)
        if self.down is not None:
            return httpx.Response(self.down, text="down")
        if request.url.path.endswith("/get"):
            return (
                httpx.Response(404, json={"message": "not found"}) if self.exact is None else httpx.Response(200, json=self.exact)
            )
        return httpx.Response(200, json=self.found)

    @property
    def paths(self) -> list[str]:
        return [path.rsplit("/", 1)[-1] for path, _ in self.calls]

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle), base_url="https://lrclib.net/api")


class Rig:
    def __init__(self, client: TestClient, lrclib: FakeLrclib, clock: list[float], service: LyricsService) -> None:
        self.client, self.lrclib, self.clock, self.service = client, lrclib, clock, service

    def ref(self, **extra: object) -> str:
        return str(resolve(self.client, "marwa", song(**extra))[0]["id"])  # type: ignore[arg-type]

    def ask(self, ref_id: str, user: str = "marwa", **params: str) -> httpx.Response:
        return self.client.get(f"{V1}/refs/{ref_id}/lyrics", params={**creds(user), **params})


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[Rig]:
    lrclib = FakeLrclib()
    clock = [1_000_000.0]
    config = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    app = create_app(config, verifier=FakeVerifier(), lyrics_client=lrclib.client())
    with TestClient(app) as client:
        service = LyricsService(app.state.services.db, lrclib.client(), clock=lambda: clock[0])
        app.state.services.lyrics = service
        client.get(f"{V1}/me", params=creds("marwa"))  # the first person is the owner
        yield Rig(client, lrclib, clock, service)


# ------------------------------------------------------------------------------------------------ reading the words


def test_synced_lyrics_become_timed_lines_in_order_with_every_stamp_of_a_line() -> None:
    kind, body = parse_lrc(SYNCED)

    assert kind == "synced"
    assert body == [
        {"ms": 12500, "text": "First line"},
        {"ms": 20500, "text": "Chorus line"},
        {"ms": 30000, "text": ""},
        {"ms": 41000, "text": "Last line"},
        {"ms": 65250, "text": "Chorus line"},
    ]


@pytest.mark.parametrize(
    ("stamp", "ms"), [("[00:01.5]", 1500), ("[00:01.50]", 1500), ("[00:01.500]", 1500), ("[00:01.25]", 1250), ("[00:01]", 1000)]
)
def test_the_fraction_of_a_second_is_read_as_a_fraction(stamp: str, ms: int) -> None:
    assert parse_lrc(f"{stamp}la")[1] == [{"ms": ms, "text": "la"}]


def test_plain_lyrics_keep_their_stanzas_and_lose_their_header_tags() -> None:
    kind, body = parse_lrc(PLAIN)

    assert kind == "plain"
    assert body == "Line one\nLine two\n\nLine three"


def test_a_sheet_of_the_songs_own_details_is_no_lyrics() -> None:
    """R1-3: the catalogue holds "Artist / Album / Title" as the lyrics of an instrumental; the player says so instead of showing a poem."""
    assert parse_lrc(TAG_SHEET)[0] == "none"
    assert parse_lrc("")[0] == "none"


# ------------------------------------------------------------------------------------------------ asking LRCLIB


def test_the_exact_answer_is_used_and_lrclib_is_told_only_what_it_needs(rig: Rig) -> None:
    rig.lrclib.exact = {"syncedLyrics": SYNCED, "plainLyrics": "x", "duration": 318}
    ref = rig.ref()

    answer = rig.ask(ref)

    assert answer.status_code == 200
    body = answer.json()
    assert body["kind"] == "synced" and body["source"] == "lrclib" and body["lines"][0] == {"ms": 12500, "text": "First line"}
    assert rig.lrclib.paths == ["get"]
    assert rig.lrclib.calls[0][1] == {
        "track_name": "Weird Fishes / Arpeggi",
        "artist_name": "Radiohead",
        "album_name": "In Rainbows",
        "duration": "318",
    }, "artist, title, album and length - never a person, an address or a ref id"


def test_a_plain_exact_answer_is_upgraded_when_a_synced_one_of_the_same_length_exists(rig: Rig) -> None:
    rig.lrclib.exact = {"plainLyrics": PLAIN, "duration": 318}
    rig.lrclib.found = [{"syncedLyrics": SYNCED, "duration": 319}, {"plainLyrics": PLAIN, "duration": 318}]

    body = rig.ask(rig.ref()).json()

    assert rig.lrclib.paths == ["get", "search"]
    assert body["kind"] == "synced"


def test_without_an_exact_answer_the_search_takes_the_synced_entry_nearest_in_length_and_skips_other_versions(rig: Rig) -> None:
    rig.lrclib.found = [
        {"syncedLyrics": "[00:01.00]live", "duration": 358},  # a live cut: 40 s off
        {"syncedLyrics": "[00:01.00]near", "duration": 321},
        {"syncedLyrics": "[00:01.00]nearest", "duration": 318},
        {"plainLyrics": "plain only", "duration": 318},
    ]

    body = rig.ask(rig.ref()).json()

    assert rig.lrclib.paths == ["get", "search"]
    assert body["kind"] == "synced" and body["lines"] == [{"ms": 1000, "text": "nearest"}]


def test_an_entry_of_another_length_is_not_this_song(rig: Rig) -> None:
    """A live cut, a remix, a different song with the same title: wrong words are worse than no words."""
    rig.lrclib.found = [{"syncedLyrics": "[00:01.00]live", "duration": 358}, {"plainLyrics": "remix", "duration": 280}]

    assert rig.ask(rig.ref()).json()["kind"] == "none"


def test_only_a_plain_entry_of_the_right_length_gives_plain_lyrics(rig: Rig) -> None:
    rig.lrclib.found = [{"plainLyrics": "wrong version", "duration": 400}, {"plainLyrics": PLAIN, "duration": 320}]

    body = rig.ask(rig.ref()).json()

    assert body["kind"] == "plain" and body["text"] == "Line one\nLine two\n\nLine three"


def test_an_instrumental_is_said_to_be_one(rig: Rig) -> None:
    rig.lrclib.exact = {"instrumental": True, "syncedLyrics": None, "plainLyrics": None, "duration": 318}

    assert rig.ask(rig.ref()).json()["kind"] == "instrumental"


def test_a_tag_sheet_from_lrclib_is_no_lyrics(rig: Rig) -> None:
    rig.lrclib.exact = {"plainLyrics": TAG_SHEET, "duration": 318}

    assert rig.ask(rig.ref()).json()["kind"] == "none"


# ------------------------------------------------------------------------------------------------ remembering (F22)


def test_an_answer_is_asked_for_once_and_then_remembered(rig: Rig) -> None:
    rig.lrclib.exact = {"syncedLyrics": SYNCED, "duration": 318}
    ref = rig.ref()

    first, second = rig.ask(ref).json(), rig.ask(ref).json()

    assert rig.lrclib.paths == ["get"], "the second question never reached LRCLIB"
    assert first["lines"] == second["lines"]


def test_a_miss_is_remembered_for_an_hour_then_longer_each_time_never_more_than_a_week(rig: Rig) -> None:
    ref = rig.ref()
    pauses = [3600, 6 * 3600, 24 * 3600, 7 * 24 * 3600, 7 * 24 * 3600]
    for pause in pauses:
        before = len(rig.lrclib.calls)
        assert rig.ask(ref).json()["kind"] == "none"
        asked = len(rig.lrclib.calls) - before
        assert asked == 2, "a fresh look is the exact question and the search"
        rig.clock[0] += pause - 60
        assert rig.ask(ref).json()["kind"] == "none"
        assert len(rig.lrclib.calls) - before == asked, f"{pause} s later (minus a minute) LRCLIB is still not asked"
        rig.clock[0] += 61


def test_a_song_that_gets_lyrics_after_a_miss_is_found_when_the_pause_is_over(rig: Rig) -> None:
    """The F22 case: a release is a day old, LRCLIB has no entry at first. The phone waited a whole day; the server asks again within the hour."""
    ref = rig.ref()
    assert rig.ask(ref).json()["kind"] == "none"
    rig.lrclib.exact = {"syncedLyrics": SYNCED, "duration": 318}
    rig.clock[0] += 3601

    assert rig.ask(ref).json()["kind"] == "synced"


def test_a_person_can_ask_again_at_once_but_not_more_than_once_a_minute(rig: Rig) -> None:
    ref = rig.ref()
    rig.ask(ref)
    rig.lrclib.exact = {"syncedLyrics": SYNCED, "duration": 318}

    too_soon = rig.ask(ref, refresh="true").json()
    rig.clock[0] += 61
    after_a_minute = rig.ask(ref, refresh="true").json()

    assert too_soon["kind"] == "none", "asking again straight away is not passed on to LRCLIB"
    assert after_a_minute["kind"] == "synced", "after a minute 'Try again' does ask, whatever the pause says"


def test_a_plain_answer_is_looked_at_again_after_two_weeks_for_a_synced_one(rig: Rig) -> None:
    rig.lrclib.exact = {"plainLyrics": PLAIN, "duration": 318}
    ref = rig.ref()
    assert rig.ask(ref).json()["kind"] == "plain"
    calls = len(rig.lrclib.calls)

    rig.clock[0] += 13 * 24 * 3600
    assert rig.ask(ref).json()["kind"] == "plain" and len(rig.lrclib.calls) == calls

    rig.lrclib.exact = {"syncedLyrics": SYNCED, "duration": 318}
    rig.clock[0] += 2 * 24 * 3600
    assert rig.ask(ref).json()["kind"] == "synced"


# ------------------------------------------------------------------------------------------------ when LRCLIB is not there


@pytest.mark.parametrize("status", [500, 503, 429])
def test_when_lrclib_is_down_the_answer_says_so_and_nothing_is_remembered(rig: Rig, status: int) -> None:
    rig.lrclib.down = status
    ref = rig.ref()

    failed = rig.ask(ref)
    rig.lrclib.down = None
    rig.lrclib.exact = {"syncedLyrics": SYNCED, "duration": 318}
    recovered = rig.ask(ref)

    assert failed.status_code == 502 and failed.json()["error"]["code"] == "source_unreachable"
    assert failed.json()["error"]["retryable"] is True
    assert recovered.json()["kind"] == "synced", "a failed look is not a miss: it is asked again at once"


def test_a_lrclib_that_does_not_answer_in_time_is_a_failed_look_not_a_miss(rig: Rig) -> None:
    def never(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    service = LyricsService(
        rig.service._db, httpx.Client(transport=httpx.MockTransport(never), base_url="https://lrclib.net/api")
    )  # noqa: SLF001
    rig.client.app.state.services.lyrics = service  # type: ignore[attr-defined]

    assert rig.ask(rig.ref()).status_code == 502


# ------------------------------------------------------------------------------------------------ many at once


def test_two_people_asking_for_the_same_new_song_cause_one_question_to_lrclib(rig: Rig) -> None:
    rig.lrclib.exact = {"syncedLyrics": SYNCED, "duration": 318}
    rig.lrclib.gate = threading.Event()
    ref_id = rig.ref()
    with rig.service._db.read() as conn:  # noqa: SLF001
        from encore_server import refs

        ref = refs.get_ref(conn, ref_id)
    answers: list[dict[str, Any]] = []

    def ask() -> None:
        answers.append(rig.service.get(ref))

    threads = [threading.Thread(target=ask) for _ in range(2)]
    threads[0].start()
    assert rig.lrclib.entered.wait(5), "the first question is on its way"
    threads[1].start()
    # Only when the second person is registered as waiting for this very song is LRCLIB allowed to answer; a moment is then left for a
    # server without the one-question rule to (wrongly) send a second question, so the second person cannot have arrived after the answer.
    deadline = time.monotonic() + 5
    while rig.service._inflight.get(ref_id, [None, 0])[1] < 2 and time.monotonic() < deadline:  # noqa: SLF001
        time.sleep(0.01)
    assert rig.service._inflight.get(ref_id, [None, 0])[1] == 2, "the second person is waiting for the same song"  # noqa: SLF001
    time.sleep(0.3)
    rig.lrclib.gate.set()
    for thread in threads:
        thread.join(5)

    assert len(answers) == 2 and answers[0]["kind"] == answers[1]["kind"] == "synced"
    assert rig.lrclib.paths == ["get"], "the second person waited for the first one's answer"


# ------------------------------------------------------------------------------------------------ who may ask


def test_no_login_no_lyrics(rig: Rig) -> None:
    ref = rig.ref()

    assert rig.client.get(f"{V1}/refs/{ref}/lyrics").status_code == 401
    assert rig.lrclib.calls == []


def test_a_song_the_server_does_not_know_is_not_found_and_not_asked_about(rig: Rig) -> None:
    answer = rig.ask("sr_doesnotexist0000000000")

    assert answer.status_code == 404 and rig.lrclib.calls == []


def test_a_locked_person_gets_nothing(rig: Rig) -> None:
    ref = rig.ref()
    rig.client.get(f"{V1}/me", params=creds("nina"))
    nina = next(p for p in rig.client.get(f"{V1}/people", params=creds("marwa")).json()["items"] if p["username"] == "nina")["id"]
    assert rig.client.patch(f"{V1}/people/{nina}", params=creds("marwa"), json={"locked": True}).status_code == 200

    assert rig.ask(ref, user="nina").status_code == 403
    assert rig.lrclib.calls == []
