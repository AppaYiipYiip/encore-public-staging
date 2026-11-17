"""N-34 slice 1: a caller of the catalogue says WHO is waiting (`priority`) and for HOW LONG (`deadline_s`), and the two travel together.

Until now every request of `Catalogue` was `interactive` with the phone's 2.5 s (`catalogue.py` `_lead`, `_gather`), which is right for a person and wrong for
the album pass of N-34 (650 songs): it would jump the queue in front of a person's search, and a background request would still run on a person's
deadline, so anything slower came back as "could not ask" and stopped the pass. This file holds:

* the DEFAULTS, which must not move: a route still asks `interactive` with 2.5 s, at every outside request and at the wait for the parts;
* the new arguments reaching the gate (`priority`, and `wait_s` = the deadline) and the wait for the parts (`within`: the caller waits for the song list what is
  left of its deadline, each outside request keeps the whole deadline for its turn);
* the single flight: **a person is never made to wait behind a background request for the same thing** (the flight is per priority), and a follower waits
  for its OWN deadline, not for the phone's;
* `deezer.search_tracks(wait_s=)`: the keeper's short wait (N-34 slice 3) instead of the 120 s of a background turn.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from encore_server import catalogue, deezer
from encore_server.catalogue import Cache, Catalogue
from encore_server.deezer import DeezerClient, Gate, LookupUnavailable
from tests.catalogue_fakes import ALBUM_ID, RecordedDeezer, recorded
from tests.conftest import FakeVerifier
from tests.test_catalogue_api import Rig, make


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier) -> Iterator[Rig]:
    yield from make(tmp_path, verifier)


class Spy:
    """Wraps `DeezerClient.get` and `Catalogue._gather` of one catalogue: what was asked, for whom and with which wait."""

    def __init__(self, cat: Catalogue) -> None:
        self.gets: list[dict[str, Any]] = []
        self.gathers: list[float | None] = []
        #: the `deadline_s` each outside request was given by its caller: a follower of a request in flight waits twice it
        self.deadlines: list[float | None] = []
        real_get, real_gather, real_fetch = cat.client.get, cat._gather, cat._fetch

        def get(path: str, params: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
            self.gets.append({"path": path, **kw})
            return real_get(path, params, **kw)

        def gather(jobs: Any, *, within: float | None = None) -> Any:
            self.gathers.append(within)
            return real_gather(jobs, within=within)

        def fetch(*args: Any, **kw: Any) -> Any:
            self.deadlines.append(kw.get("deadline_s"))
            return real_fetch(*args, **kw)

        cat.client.get = get  # type: ignore[method-assign]
        cat._gather = gather  # type: ignore[method-assign]
        cat._fetch = fetch  # type: ignore[method-assign]


# ------------------------------------------------------------------------------------------------------------------ the defaults do not move


def test_the_numbers_a_route_is_built_on_are_still_what_they_were() -> None:
    assert catalogue.CALL_TIMEOUT_S == 2.5 and deezer.INTERACTIVE_WAIT_S == 2.5
    assert deezer.DeezerClient.TIMEOUTS["background"].read == 8.0, "a background request may take 8 s"


@pytest.mark.parametrize(
    "route",
    ["/catalogue/search?q=billie eilish", f"/catalogue/albums/{ALBUM_ID}", "/catalogue/artists/719", "/catalogue/genres/0"],
)
def test_a_route_still_asks_interactive_and_inside_two_and_a_half_seconds(rig: Rig, route: str) -> None:
    spy = Spy(rig.catalogue)
    path, _, query = route.partition("?")
    rig.ok(path, **dict(part.split("=") for part in query.split("&")) if query else {})
    assert spy.gets, "the route asked nothing (the recorded answer was cached?)"
    for call in spy.gets:
        assert call["priority"] == "interactive", call
        # EXACTLY what it was before slice 1: no `wait_s` (the gate's own interactive 2.5 s), and 2.5 s is what it is now. A song list that got "what is left of
        # 2.5 s" was a change of a default that the slice said it did not make.
        assert (deezer.INTERACTIVE_WAIT_S if call["wait_s"] is None else call["wait_s"]) == 2.5, call
    assert spy.deadlines and all(deadline in (None, 2.5) for deadline in spy.deadlines), spy.deadlines
    waits = [catalogue.CALL_TIMEOUT_S if within is None else within for within in spy.gathers]  # `None` is "the phone's 2.5 s"
    assert waits and all(0 < within <= 2.5 for within in waits), spy.gathers
    assert waits[0] == 2.5, "the first wait for the parts of a call is the phone's whole 2.5 s"


# ------------------------------------------------------------------------------------------------------------------ the new arguments arrive


def test_an_album_asked_in_the_background_arrives_at_the_gate_as_background_with_its_own_deadline(rig: Rig) -> None:
    spy = Spy(rig.catalogue)
    answer = rig.catalogue.album(ALBUM_ID, priority="background", deadline_s=30.0)
    assert answer["album"]["id"] == ALBUM_ID and answer["tracks"]
    assert [call["path"] for call in spy.gets] == [f"/album/{ALBUM_ID}", f"/album/{ALBUM_ID}/tracks"]
    assert [call["priority"] for call in spy.gets] == ["background", "background"]
    first, second = (call["wait_s"] for call in spy.gets)
    assert first == second == 30.0, "each request may wait for its turn at the gate as long as the caller's whole deadline"
    assert spy.gathers[0] == 30.0 and 29.0 < spy.gathers[1] <= 30.0, "and the caller waits for the song list what is left of it"


def slow_album(rig: Rig) -> None:
    """The first answer of an album takes 0.4 s: what is left of any deadline is less than the deadline when the song list is asked."""

    def slow(request: httpx.Request) -> httpx.Response:
        time.sleep(0.4)
        return httpx.Response(200, json=recorded("album"))

    rig.upstream.overrides[f"/album/{ALBUM_ID}"] = slow


def test_the_caller_waits_for_the_song_list_only_what_is_left_of_its_deadline_and_the_request_keeps_the_whole_deadline(
    rig: Rig,
) -> None:
    """Two different waits, kept apart. The CALLER waits for the parts of the call (`within`) for what is left of its deadline: a first answer that takes 0.4 s
    of a 1 s deadline leaves the song list at most 0.6 s, and the call never takes longer than its deadline in all. The song-list REQUEST waits for its turn at the
    gate, and a follower waits for the request, as long as the whole deadline, exactly as a person's route always did (see the next test): a slow answer that
    comes after the caller left still fills the cache (`_gather`), and nothing in the caller's patience changes."""
    slow_album(rig)
    spy = Spy(rig.catalogue)
    rig.catalogue.album(ALBUM_ID, deadline_s=1.0)
    assert spy.gets[0]["wait_s"] == 1.0 and spy.gets[1]["wait_s"] == 1.0, spy.gets
    assert spy.deadlines == [1.0, 1.0], "a follower of either request waits twice the deadline"
    assert spy.gathers[0] == 1.0 and spy.gathers[1] <= 0.62, spy.gathers


def test_a_person_route_gives_the_song_list_the_phones_whole_wait_exactly_as_before_slice_1(rig: Rig) -> None:
    """Slice 1 said that every route's defaults are unchanged. They were not: the song list of an album got `wait_s` = what was left of 2.5 s where the old code
    passed none (the gate reads that as its own interactive 2.5 s), and a follower of that request waited twice what was left instead of 5 s. A first answer
    that takes 0.4 s must change NOTHING for the song list: the same wait for its turn (2.5 s) and the same follower wait; only the caller's wait for the parts is
    what is left of the 2.5 s, as it always was."""
    slow_album(rig)
    spy = Spy(rig.catalogue)
    rig.ok(f"/catalogue/albums/{ALBUM_ID}")
    assert [call["path"] for call in spy.gets] == [f"/album/{ALBUM_ID}", f"/album/{ALBUM_ID}/tracks"]
    assert [(deezer.INTERACTIVE_WAIT_S if call["wait_s"] is None else call["wait_s"]) for call in spy.gets] == [2.5, 2.5]
    assert [deadline in (None, 2.5) for deadline in spy.deadlines] == [True, True], spy.deadlines
    assert spy.gathers[0] == 2.5 and 0 < spy.gathers[1] <= 2.1, "the caller's wait for the song list is what is left of its 2.5 s"


def test_search_tracks_waits_for_its_turn_as_long_as_it_is_told_and_by_default_as_a_background_turn_does(
    tmp_path: Path,
) -> None:
    upstream = RecordedDeezer()
    gate = Gate(rate=1000, burst=1000, background_gap_s=0.0)
    asked: list[dict[str, Any]] = []
    real = gate.acquire

    def acquire(priority: str = "interactive", *, wait_s: float | None = None) -> Any:
        asked.append({"priority": priority, "wait_s": wait_s})
        return real(priority, wait_s=wait_s)  # type: ignore[arg-type]

    gate.acquire = acquire  # type: ignore[method-assign]
    deezer.install(DeezerClient(gate, httpx.Client(transport=upstream.transport())))
    try:
        deezer.search_tracks("Pink Floyd", "Comfortably Numb")
        deezer.search_tracks("Pink Floyd", "Comfortably Numb", wait_s=7.5)
    finally:
        deezer.install(None)
    assert asked == [{"priority": "background", "wait_s": None}, {"priority": "background", "wait_s": 7.5}]
    assert deezer.BACKGROUND_WAIT_S == 120.0, "None still means the 120 s of a background turn"


# ------------------------------------------------------------------------------------------------------------------ one flight per priority


class Held:
    """The FIRST request for [path] is held until [release] is set (it is in flight and nobody answers); every later one is answered at once."""

    def __init__(self, upstream: RecordedDeezer, path: str, body: dict[str, Any]) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self._first = True
        self._lock = threading.Lock()
        self._body = body

        def answer(request: httpx.Request) -> httpx.Response:
            with self._lock:
                first, self._first = self._first, False
            if first:
                self.entered.set()
                self.release.wait(timeout=20)
            return httpx.Response(200, json=body)

        upstream.overrides[path] = answer


def test_a_person_is_not_held_behind_a_background_request_for_the_same_album(rig: Rig) -> None:
    """The pass asks an album in the background while the owner opens that very album's page: single flight keyed by the cache key alone would make
    the person a FOLLOWER of the background request, waiting for it (and for the gate's priority to be useless) until the phone gives up. The flight is
    per priority: the person's own request goes out, ahead of background work, and is answered."""
    held = Held(rig.upstream, f"/album/{ALBUM_ID}", recorded("album"))
    results: list[Any] = []
    leader = threading.Thread(
        target=lambda: results.append(rig.catalogue.album(ALBUM_ID, priority="background", deadline_s=30.0)), daemon=True
    )
    leader.start()
    try:
        assert held.entered.wait(timeout=10), "the background request never went out"
        started = time.monotonic()
        answer = rig.catalogue.album(ALBUM_ID)  # the person: interactive, 2.5 s
        took = time.monotonic() - started
        assert answer["album"]["id"] == ALBUM_ID and "unavailable" not in answer, answer.get("unavailable")
        assert took < 1.5, f"the person waited {took:.1f} s behind the background request"
        assert rig.upstream.paths().count(f"/album/{ALBUM_ID}") == 2, (
            "one outside request each: a duplicate is the price, and it is harmless"
        )
    finally:
        held.release.set()
        leader.join(timeout=10)
    assert results and results[0]["album"]["id"] == ALBUM_ID


def test_two_background_callers_for_the_same_album_still_cause_one_outside_request(rig: Rig) -> None:
    held = Held(rig.upstream, f"/album/{ALBUM_ID}", recorded("album"))
    results: list[Any] = []

    def ask() -> None:
        results.append(rig.catalogue.album(ALBUM_ID, priority="background", deadline_s=30.0))

    first = threading.Thread(target=ask, daemon=True)
    first.start()
    assert held.entered.wait(timeout=10)
    second = threading.Thread(target=ask, daemon=True)
    second.start()
    time.sleep(0.3)  # the second has had every chance to start its own request
    held.release.set()
    first.join(timeout=10)
    second.join(timeout=10)
    assert len(results) == 2 and all(r["album"]["id"] == ALBUM_ID for r in results)
    assert rig.upstream.paths().count(f"/album/{ALBUM_ID}") == 1


def test_a_follower_waits_for_its_own_deadline_and_not_for_the_phones(rig: Rig) -> None:
    """The follower of a request in flight used to wait `2 * CALL_TIMEOUT_S` (5 s) whoever it was: a caller with a 0.3 s deadline held a worker of the
    pool the routes share for 5 s. It waits twice ITS deadline."""
    held = Held(rig.upstream, f"/album/{ALBUM_ID}", recorded("album"))
    leader = threading.Thread(target=lambda: rig.catalogue.album(ALBUM_ID), daemon=True)
    leader.start()
    try:
        assert held.entered.wait(timeout=10)
        started = time.monotonic()
        with pytest.raises(LookupUnavailable):
            rig.catalogue._fetch(
                "album", f"/album/{ALBUM_ID}", {}, lambda body: body, budget=deezer.Budget(2), charge=None, deadline_s=0.3
            )
        assert time.monotonic() - started < 1.5
    finally:
        held.release.set()
        leader.join(timeout=10)


def test_every_call_site_of_the_default_is_the_default_and_nothing_else_changed_in_the_answer(tmp_path: Path) -> None:
    """The same album, asked the old way (no new argument) and the new way with the defaults written out, is the same answer and the same two requests."""
    one, two = RecordedDeezer(), RecordedDeezer()
    plain = Catalogue(DeezerClient(Gate(rate=1000, burst=1000), httpx.Client(transport=one.transport())), Cache(None))
    written = Catalogue(DeezerClient(Gate(rate=1000, burst=1000), httpx.Client(transport=two.transport())), Cache(None))
    assert plain.album(ALBUM_ID) == written.album(ALBUM_ID, priority="interactive", deadline_s=catalogue.CALL_TIMEOUT_S)
    assert one.paths() == two.paths() == [f"/album/{ALBUM_ID}", f"/album/{ALBUM_ID}/tracks"]
