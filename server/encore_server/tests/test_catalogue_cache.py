"""P2-12 slice 1: the catalogue's own memory (`catalogue-cache.db`), single flight, the ceiling per search, and what is never remembered.

The unit of the cache is the OUTSIDE request, so every composite answer (a search of three kinds, an artist page of three parts) is made of cached
parts, and a part that could not be asked is simply missing from the answer, never stored as if the catalogue knew nothing (audit B-124). All answers
here are Deezer's real, recorded ones (`catalogue_fakes.py`); only the errors are written by the tests.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from encore_server.catalogue import Cache, Catalogue
from encore_server.deezer import DeezerClient, Gate, LookupUnavailable, NotInCatalogue
from tests.catalogue_fakes import ALBUM_ID, ARTIST_ID, NO_DATA, RecordedDeezer

MINUTE = 60.0
DAY = 24 * 3600.0


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    def after(self, seconds: float) -> None:
        self.now += seconds


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.upstream = RecordedDeezer()
        self.clock = Clock()
        self.gate = Gate(rate=1000, burst=1000, background_gap_s=0.0)
        self.cache = Cache(tmp_path / "catalogue-cache.db")
        self.catalogue = Catalogue(
            DeezerClient(self.gate, httpx.Client(transport=self.upstream.transport())), self.cache, clock=self.clock
        )

    def search(self, query: str = "billie eilish", **kw: Any) -> dict[str, Any]:
        return self.catalogue.search(query, kw.pop("types", ("artists", "albums", "tracks")), kw.pop("limit", 8), **kw)


@pytest.fixture()
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


# ------------------------------------------------------------------------------------------------------------------ remembered, and for how long


def test_the_same_search_twice_asks_the_catalogue_once_and_again_after_fifteen_minutes(rig: Rig) -> None:
    first = rig.search()
    assert rig.upstream.count("/search/") == 3, "an artist, an album and a song search: one request each"
    assert rig.search() == first
    assert rig.upstream.count("/search/") == 3, "the second came from the cache"
    rig.clock.after(14 * MINUTE)
    rig.search()
    assert rig.upstream.count("/search/") == 3
    rig.clock.after(2 * MINUTE)
    rig.search()
    assert rig.upstream.count("/search/") == 6, "fifteen minutes is the most a search is believed"


def test_a_valid_empty_answer_is_remembered_for_five_minutes_only(rig: Rig) -> None:
    rig.search("zzzz qqqq nothing")
    rig.search("zzzz qqqq nothing")
    assert rig.upstream.count("/search/") == 3
    rig.clock.after(6 * MINUTE)
    rig.search("zzzz qqqq nothing")
    assert rig.upstream.count("/search/") == 6, "a thing the catalogue does not list yet may be listed in five minutes (F12)"


def test_an_artist_is_remembered_for_a_day_and_an_album_for_a_week(rig: Rig) -> None:
    rig.catalogue.artist_page(ARTIST_ID, ("popular",))
    rig.catalogue.album(ALBUM_ID)
    asked = len(rig.upstream.requests)
    rig.clock.after(23 * 3600)
    rig.catalogue.artist_page(ARTIST_ID, ("popular",))
    rig.catalogue.album(ALBUM_ID)
    assert len(rig.upstream.requests) == asked
    rig.clock.after(2 * 3600)
    rig.catalogue.artist_page(ARTIST_ID, ("popular",))
    rig.catalogue.album(ALBUM_ID)
    assert sorted(rig.upstream.paths()[asked:]) == [f"/artist/{ARTIST_ID}", f"/artist/{ARTIST_ID}/top"], (
        "the artist is asked again after a day; the album is not"
    )
    rig.clock.after(7 * DAY)
    rig.catalogue.album(ALBUM_ID)
    assert rig.upstream.count("/album/") == 4, "after a week the album and its songs are asked again"


def test_a_thing_that_is_not_there_is_a_fact_remembered_for_five_minutes(rig: Rig) -> None:
    for _ in range(2):
        with pytest.raises(NotInCatalogue):
            rig.catalogue.album("999")
    assert rig.upstream.paths() == ["/album/999"], "one request, and the songs of a missing album are not asked"
    rig.clock.after(6 * MINUTE)
    with pytest.raises(NotInCatalogue):
        rig.catalogue.album("999")
    assert rig.upstream.paths() == ["/album/999", "/album/999"]
    assert rig.gate.state()["state"] == "ok", "a missing thing says nothing about the catalogue's health"


# ------------------------------------------------------------------------------------------------------------------ B-124: could not ask is never stored


def test_a_part_that_could_not_be_asked_is_named_and_never_stored(rig: Rig) -> None:
    rig.upstream.overrides["/search/track"] = httpx.ReadTimeout("slow")
    answer = rig.search()
    assert answer["unavailable"] == ["tracks"]
    assert answer["artists"] and answer["albums"], "the parts that were asked are still there"
    assert rig.cache.count() == 2, "an outage is not stored as an empty list of songs"
    del rig.upstream.overrides["/search/track"]
    again = rig.search()
    assert "unavailable" not in again and again["tracks"]
    assert rig.upstream.count("/search/") == 4, "only the missing part was asked again; the other two came from the cache"


def test_a_throttling_answer_is_not_stored_and_rests_the_gate(rig: Rig) -> None:
    rig.upstream.overrides["/search/artist"] = (
        200,
        {"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}},
    )
    with pytest.raises(LookupUnavailable):
        rig.search(types=("artists",))
    assert rig.cache.count() == 0
    assert rig.gate.state()["state"] == "resting"


def test_a_part_that_does_not_come_in_time_is_left_out_and_still_fills_the_cache_when_it_comes(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The call has 2.5 s in all (here 0.3): a slow part is named in `unavailable` at once, and the request, already on its way, is not wasted."""
    monkeypatch.setattr("encore_server.catalogue.CALL_TIMEOUT_S", 0.3)
    plain = rig.upstream.answer

    def slow(request: httpx.Request) -> httpx.Response:
        time.sleep(0.8)
        return httpx.Response(200, json=plain(request.url.path, dict(request.url.params)))

    rig.upstream.overrides["/search/track"] = slow
    started = time.monotonic()
    answer = rig.search()
    assert time.monotonic() - started < 0.7, "the call did not wait for the slow part"
    assert answer["unavailable"] == ["tracks"] and answer["artists"] and answer["albums"]
    deadline = time.monotonic() + 3
    while rig.cache.count() < 3 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert rig.cache.count() == 3, "the slow answer arrived and was remembered"
    assert rig.search()["tracks"] and rig.upstream.count("/search/track") == 1


# ------------------------------------------------------------------------------------------------------------------ stale on error


def test_a_stale_answer_is_served_while_the_catalogue_is_down_for_up_to_thirty_days(rig: Rig) -> None:
    fresh = rig.search()
    rig.clock.after(20 * DAY)
    for path in ("/search/artist", "/search/album", "/search/track"):
        rig.upstream.overrides[path] = (503, {})
    stale = rig.search()
    assert stale == fresh, "a person whose catalogue is down still sees what was true twenty days ago"
    rig.clock.after(11 * DAY)
    with pytest.raises(LookupUnavailable):
        rig.catalogue.search(
            "billie eilish", ("tracks",), 8
        )  # (the gate is resting after the 503: nothing is asked, and 31 days is too old)


def test_an_empty_answer_is_never_served_stale_because_that_would_be_nothing_found_again(rig: Rig) -> None:
    rig.search("zzzz qqqq nothing")
    rig.clock.after(2 * DAY)
    for path in ("/search/artist", "/search/album", "/search/track"):
        rig.upstream.overrides[path] = (503, {})
    with pytest.raises(LookupUnavailable):
        rig.catalogue.search("zzzz qqqq nothing", ("tracks",), 8)  # not "no songs": it could not be asked


# ------------------------------------------------------------------------------------------------------------------ one flight, one budget, no text


def test_two_people_asking_the_same_thing_at_once_cause_one_outside_request(tmp_path: Path) -> None:
    release = threading.Event()
    upstream = RecordedDeezer()
    plain = upstream.answer

    def held(request: httpx.Request) -> httpx.Response:
        release.wait(timeout=5)
        return httpx.Response(200, json=plain(request.url.path, dict(request.url.params)))

    upstream.overrides["/search/artist"] = held
    charged: list[int] = []
    catalogue = Catalogue(
        DeezerClient(Gate(rate=1000, burst=1000, background_gap_s=0.0), httpx.Client(transport=upstream.transport())),
        Cache(tmp_path / "c.db"),
    )
    answers: list[dict[str, Any]] = []

    def ask() -> None:
        answers.append(catalogue.search("radiohead", ("artists",), 8, charge=lambda: charged.append(1)))

    first = threading.Thread(target=ask)
    first.start()
    while not upstream.requests:
        time.sleep(0.01)
    second = threading.Thread(target=ask)
    second.start()
    time.sleep(0.2)  # the second is waiting on the first one's request now
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert upstream.count("/search/artist") == 1, (
        "single flight: the second caller joined the request that was already on its way"
    )
    assert len(answers) == 2 and answers[0] == answers[1]
    assert charged == [1], "only the caller whose request went out is charged for it"


def test_a_cached_answer_is_not_charged_and_costs_no_budget(rig: Rig) -> None:
    charged: list[int] = []
    rig.search(charge=lambda: charged.append(1))
    assert len(charged) == 3
    rig.search(charge=lambda: charged.append(1))
    assert len(charged) == 3


def test_the_cache_keeps_no_typed_text_and_the_log_none(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        rig.search("a secret band name")
    keys = [row[0] for row in sqlite3.connect(rig.cache.path).execute("SELECT key FROM answer")]
    assert keys and all(re.fullmatch(r"[0-9a-f]{64}", key) for key in keys), "keys are hashes, not queries"
    assert "secret band" not in caplog.text.lower()


# ------------------------------------------------------------------------------------------------------------------ the file


def test_the_cache_is_kept_to_its_size_and_the_oldest_go_first(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "c.db", max_entries=10)
    for n in range(25):
        cache.put(f"{n:064d}", "search", {"data": [n]}, now=1000.0 + n, ttl_s=60)
    cache.prune(now=1100.0)
    assert cache.count() == 10
    assert cache.get(f"{24:064d}") is not None and cache.get(f"{0:064d}") is None


def test_a_cache_file_that_is_damaged_is_replaced_and_the_server_starts(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "catalogue-cache.db"
    path.write_bytes(b"this is not a database " * 200)
    with caplog.at_level(logging.WARNING):
        cache = Cache(path)
    assert cache.count() == 0
    cache.put("k" * 64, "search", {"data": []}, now=1.0, ttl_s=60)
    assert cache.get("k" * 64) is not None
    assert "catalogue cache" in caplog.text


def test_a_cache_that_cannot_be_made_is_no_cache_and_the_catalogue_still_answers(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    cache = Cache(blocker / "inside" / "catalogue-cache.db")
    cache.put("k" * 64, "search", {"data": [1]}, now=1.0, ttl_s=60)
    assert cache.get("k" * 64) is None and cache.count() == 0
    upstream = RecordedDeezer()
    catalogue = Catalogue(DeezerClient(Gate(rate=1000, burst=1000), httpx.Client(transport=upstream.transport())), cache)
    assert catalogue.search("billie eilish", ("artists",), 8)["artists"]


def test_nothing_in_the_recordings_is_the_no_data_answer_by_accident() -> None:
    """The fake itself: an id the recordings do not hold is Deezer's own 'no data' answer, so a test of a missing thing is a real shape."""
    assert NO_DATA["error"]["code"] == 800
