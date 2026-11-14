"""P2-12 slice 1: the ONE gate to the catalogue (Deezer), and the one client that asks through it.

Every outside request of the server (a person's search, an artist page, the cover finder, the artist finder, the keeper's cover) takes a turn at the
gate, so the whole server has one budget at Deezer, like the one budget at YouTube (`sources/youtube/pace.py`). What these tests hold: the rate
(sustained 20 a second-fifth, a burst of 6), a person waiting before background work, the number in flight, the rest after a refusal and how it grows
and ends, the switch that opens no socket, and the three possible answers of a look-up (found, nothing there, could not ask) being told apart
(B-124). No test reaches the real catalogue: the transport is a mock and the clock is a fake.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import pytest

from encore_server import deezer
from encore_server.deezer import (
    Budget,
    BudgetSpent,
    CatalogueOff,
    DeezerClient,
    Gate,
    LookupUnavailable,
    NotInCatalogue,
)


class FakeTime:
    """A clock that only moves when somebody sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def gate(fake: FakeTime, **extra: Any) -> Gate:
    return Gate(clock=fake.clock, sleep=fake.sleep, **extra)


# ------------------------------------------------------------------------------------------------------------------ the rate


def test_a_burst_of_six_goes_at_once_and_after_it_the_rate_is_twenty_in_five_seconds() -> None:
    fake = FakeTime()
    g = gate(fake)
    stamps: list[float] = []
    for _ in range(100):
        ticket = g.acquire("interactive")
        stamps.append(fake.now)
        g.done(ticket, "ok")
    assert stamps[:6] == [1000.0] * 6, "the burst is not made to wait"
    assert stamps[6] > 1000.0, "the seventh waits for a token"
    # Sustained: 20 requests in 5 seconds is 4 a second, so 94 more take about 23.5 seconds.
    assert 23.0 <= stamps[-1] - stamps[5] <= 24.5
    # And in no window of five seconds more than the burst plus what was refilled (26), never Deezer's own 50.
    for i, t in enumerate(stamps):
        assert sum(1 for s in stamps if t - 5.0 < s <= t) <= 26, f"too many in the five seconds that end at request {i}"


def test_a_request_that_cannot_have_its_turn_in_time_is_not_an_answer_and_nothing_is_asked() -> None:
    fake = FakeTime()
    g = gate(fake, burst=1, rate=1, per_s=100.0)  # a token every 100 seconds
    g.done(g.acquire("interactive"), "ok")
    with pytest.raises(LookupUnavailable):
        g.acquire("interactive", wait_s=2.5)
    assert sum(fake.slept) <= 2.6, "it gave up at its limit instead of waiting for the token"


# ------------------------------------------------------------------------------------------------------------------ priority and in flight


def test_the_number_in_flight_is_limited_and_a_finished_request_makes_room() -> None:
    fake = FakeTime()
    g = gate(fake, in_flight=2, rate=1000, burst=1000)
    first, second = g.acquire("interactive"), g.acquire("interactive")
    with pytest.raises(LookupUnavailable):
        g.acquire("interactive", wait_s=0.2)
    g.done(first, "ok")
    third = g.acquire("interactive", wait_s=0.2)
    g.done(second, "ok")
    g.done(third, "ok")


def test_a_person_waiting_goes_before_background_work() -> None:
    """With the only place taken, a background caller and an interactive caller both wait; when the place is free the person gets it first, though the
    background caller asked first."""
    g = Gate(in_flight=1, rate=1000, burst=1000, background_gap_s=0.0)
    held = g.acquire("interactive")
    order: list[str] = []
    ready = threading.Barrier(3)

    def take(priority: str) -> None:
        ready.wait(timeout=2)
        ticket = g.acquire(priority, wait_s=5)
        order.append(priority)
        time.sleep(0.02)
        g.done(ticket, "ok")

    background = threading.Thread(target=take, args=("background",))
    background.start()
    time.sleep(0.05)  # the background caller is waiting first
    person = threading.Thread(target=take, args=("interactive",))
    person.start()
    ready.wait(timeout=2)
    time.sleep(0.15)  # both are waiting now
    g.done(held, "ok")
    background.join(timeout=5)
    person.join(timeout=5)
    assert order == ["interactive", "background"]


def test_background_work_keeps_a_gap_between_its_own_requests() -> None:
    fake = FakeTime()
    g = gate(fake, rate=1000, burst=1000, background_gap_s=0.25)
    stamps = []
    for _ in range(4):
        ticket = g.acquire("background")
        stamps.append(fake.now)
        g.done(ticket, "ok")
    assert all(b - a >= 0.25 - 1e-9 for a, b in zip(stamps, stamps[1:], strict=False))
    fake2 = FakeTime()
    g2 = gate(fake2, rate=1000, burst=1000, background_gap_s=0.25)
    for _ in range(4):
        g2.done(g2.acquire("interactive"), "ok")
    assert fake2.slept == [], "a person is never paced"


# ------------------------------------------------------------------------------------------------------------------ the rest (the breaker)


def test_a_refusal_rests_the_catalogue_for_thirty_seconds_and_the_rest_grows_and_ends() -> None:
    fake = FakeTime()
    g = gate(fake)
    g.done(g.acquire("interactive"), "refused")
    assert g.state() == {"state": "resting", "resumesInSec": 30}
    with pytest.raises(LookupUnavailable):
        g.acquire("interactive")
    fake.now += 29
    with pytest.raises(LookupUnavailable):
        g.acquire("interactive")
    fake.now += 1.5  # the rest is over: one trial request is let through
    trial = g.acquire("interactive")
    with pytest.raises(LookupUnavailable):
        g.acquire("interactive", wait_s=0.2)  # only the one trial, not a rush
    g.done(trial, "refused")  # the trial is refused too: twice as long
    assert g.state() == {"state": "resting", "resumesInSec": 60}
    fake.now += 61
    g.done(g.acquire("interactive"), "ok")  # the trial succeeds: all is well again
    assert g.state() == {"state": "ok", "resumesInSec": 0}
    g.done(g.acquire("interactive"), "refused")
    assert g.state()["resumesInSec"] == 30, "after a good answer the next rest starts from thirty seconds again"


def test_the_rest_never_grows_beyond_ten_minutes() -> None:
    fake = FakeTime()
    g = gate(fake)
    for _ in range(12):
        fake.now += 700
        g.done(g.acquire("interactive"), "refused")
    assert g.state()["resumesInSec"] == 600


def test_three_timeouts_in_thirty_seconds_rest_it_and_one_does_not() -> None:
    fake = FakeTime()
    g = gate(fake)
    g.done(g.acquire("interactive"), "timeout")
    assert g.state()["state"] == "ok"
    fake.now += 31  # the first is forgotten
    g.done(g.acquire("interactive"), "timeout")
    g.done(g.acquire("interactive"), "timeout")
    assert g.state()["state"] == "ok"
    g.done(g.acquire("interactive"), "timeout")
    assert g.state()["state"] == "resting"


def test_a_good_answer_forgets_the_timeouts_before_it() -> None:
    fake = FakeTime()
    g = gate(fake)
    g.done(g.acquire("interactive"), "timeout")
    g.done(g.acquire("interactive"), "timeout")
    g.done(g.acquire("interactive"), "ok")
    g.done(g.acquire("interactive"), "timeout")
    assert g.state()["state"] == "ok"


def test_a_gate_that_is_switched_off_asks_nothing_and_says_so() -> None:
    g = Gate(enabled=False)
    assert g.state() == {"state": "off", "resumesInSec": 0}
    with pytest.raises(CatalogueOff):
        g.acquire("interactive")
    assert issubclass(CatalogueOff, LookupUnavailable), "so that the finders end their pass and remember nothing"


# ------------------------------------------------------------------------------------------------------------------ the client


class Upstream:
    """What the catalogue answers, request by request; counts them."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return httpx.Response(status, json=body)

    def client(self, g: Gate | None = None) -> DeezerClient:
        return DeezerClient(gate=g or Gate(rate=1000, burst=1000, background_gap_s=0.0), http=httpx.Client(transport=httpx.MockTransport(self)))


def test_a_good_answer_is_returned_and_asked_with_a_short_limit_and_a_name_for_the_server() -> None:
    upstream = Upstream((200, {"data": [{"id": 1}]}))
    answer = upstream.client().get("/search/artist", {"q": "bob marley", "limit": 8})
    assert answer == {"data": [{"id": 1}]}
    request = upstream.requests[0]
    assert request.url.host == "api.deezer.com" and request.url.path == "/search/artist"
    assert dict(request.url.params) == {"q": "bob marley", "limit": "8"}
    assert request.headers["user-agent"].startswith("encore-server/")


@pytest.mark.parametrize(
    "reply",
    [
        (429, {}),
        (503, {}),
        (500, {"data": []}),
        # Deezer answers HTTP 200 when it throttles, with the reason in the body (audit B-124).
        (200, {"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}}),
        (200, {"error": {"type": "Exception", "message": "something", "code": 999}}),
        (200, ["not", "an", "object"]),
        httpx.ConnectTimeout("slow"),
        httpx.ReadTimeout("slower"),
        httpx.ConnectError("down"),
    ],
)
def test_a_catalogue_that_could_not_be_asked_is_never_an_answer(reply: Any) -> None:
    """B-124: a refusal, a throttled 200, a timeout and a broken network all read as "could not ask", never as "nothing found"."""
    with pytest.raises(LookupUnavailable):
        Upstream(reply).client().get("/search/track", {"q": "a"})


def test_a_throttling_answer_and_a_timeout_rest_the_gate_but_a_plain_miss_does_not() -> None:
    g = Gate(rate=1000, burst=1000, background_gap_s=0.0)
    quota = Upstream((200, {"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}}))
    with pytest.raises(LookupUnavailable):
        quota.client(g).get("/search/artist", {"q": "a"})
    assert g.state()["state"] == "resting"

    g2 = Gate(rate=1000, burst=1000, background_gap_s=0.0)
    nothing = Upstream((200, {"data": [], "total": 0}))
    assert nothing.client(g2).get("/search/artist", {"q": "zzzz"}) == {"data": [], "total": 0}
    assert g2.state()["state"] == "ok"


@pytest.mark.parametrize("reply", [(200, {"error": {"type": "DataException", "message": "no data", "code": 800}}), (404, {})])
def test_an_artist_that_does_not_exist_is_a_fact_not_an_outage(reply: Any) -> None:
    g = Gate(rate=1000, burst=1000, background_gap_s=0.0)
    with pytest.raises(NotInCatalogue):
        Upstream(reply).client(g).get("/artist/123456789")
    assert g.state()["state"] == "ok", "a thing that is not there says nothing about the catalogue's health"


def test_a_switched_off_catalogue_opens_no_connection_at_all() -> None:
    upstream = Upstream((200, {"data": []}))
    client = upstream.client(Gate(enabled=False))
    with pytest.raises(CatalogueOff):
        client.get("/search/artist", {"q": "a"})
    assert upstream.requests == []


def test_a_budget_stops_the_asking_at_its_ceiling() -> None:
    upstream = Upstream((200, {"data": []}))
    client = upstream.client()
    budget = Budget(7)
    for _ in range(7):
        client.get("/search/track", {"q": "a"}, budget=budget)
    with pytest.raises(BudgetSpent):
        client.get("/search/track", {"q": "a"}, budget=budget)
    assert len(upstream.requests) == 7
    assert issubclass(BudgetSpent, LookupUnavailable)


# ------------------------------------------------------------------------------------------------------------------ the finders' own look-up


def test_the_finders_look_up_goes_through_the_installed_gate_and_not_around_it() -> None:
    """`search_tracks` (what the cover finder, the artist finder and the keeper call) takes a background turn at the installed gate, so one budget
    covers the whole server."""
    upstream = Upstream((200, {"data": [{"title": "Nude"}]}))
    g = Gate(rate=1000, burst=1000, background_gap_s=0.25)
    fake = FakeTime()
    g._clock, g._sleep = fake.clock, fake.sleep  # noqa: SLF001 - the test drives the gate's time
    deezer.install(DeezerClient(gate=g, http=httpx.Client(transport=httpx.MockTransport(upstream))))
    try:
        deezer.search_tracks("Radiohead", "Nude")
        deezer.search_tracks("Radiohead", "Nude")
    finally:
        deezer.install(None)
    assert len(upstream.requests) == 2
    assert fake.slept, "the second one was a background request and kept its gap"
    assert upstream.requests[0].url.params["q"] == "Radiohead Nude"


def test_a_look_up_with_a_client_of_its_own_does_not_touch_the_installed_gate() -> None:
    """The finders' tests give their own client; a refusal answered to one of them must not rest the gate of the next test."""
    g = Gate()
    deezer.install(DeezerClient(gate=g, http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))))
    try:
        own = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, json={})))
        with pytest.raises(LookupUnavailable):
            deezer.search_tracks("A", "B", client=own)
        assert g.state()["state"] == "ok"
    finally:
        deezer.install(None)
