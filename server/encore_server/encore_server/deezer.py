"""The ONE gate to the catalogue (Deezer's public API), and the one client that asks through it (P2-12 slice 1, docs/11 ADR-R47).

Every outside request of this server to the catalogue (a person's search, an artist or album page, the cover finder, the artist finder, the keeper's
cover) takes a turn at the [Gate], so the whole server has ONE budget at Deezer, like the one budget at YouTube (`sources/youtube/pace.py`). The gate
holds four things:

* **a rate**: a token bucket, 20 requests per 5 seconds sustained (Deezer's own documented figure is about 50 per 5 s; this is 40 % of it), after a
  burst of 6, and at most 4 in flight;
* **a priority**: a person waiting goes before background work, and background work keeps a quarter of a second between its own requests;
* **a rest** (the breaker): a refusal, a throttling answer or three timeouts in 30 seconds stop every request for 30 seconds, then one trial request
  is let through; a trial that fails doubles the rest (up to 10 minutes), one that succeeds ends it;
* **a switch**: a Host who sets `ENCORE_CATALOGUE=0` gets a gate that opens no connection at all ([CatalogueOff]).

A look-up has THREE possible answers, and they are told apart everywhere (audit B-124): **found**, **nothing there** (the catalogue answered and knows
none: an empty list, or [NotInCatalogue] for a thing that does not exist), and **could not ask** ([LookupUnavailable]: refused, throttled, timed out,
the network broken, an answer that is not an answer, the gate resting or switched off, the search's own ceiling spent). Only the first two are facts; the
third must never be remembered as "no picture" or "no such artist".

What this module is not: the cache (`catalogue.py`, used by the routes only) and the shapes the phone sees (`catalogue.py` as well).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Literal

import httpx

from . import __version__

BASE_URL = "https://api.deezer.com"
SEARCH_URL = f"{BASE_URL}/search"

#: The address shape Deezer gives an artist that has no picture of its own: any host serves the same grey silhouette (an empty image id).
#: It is a picture of nobody; it must never be chosen, and must be dropped *before* choosing between namesakes.
PLACEHOLDER_ARTIST_PICTURE = "/images/artist//"

Priority = Literal["interactive", "background"]
Outcome = Literal["ok", "refused", "timeout"]

#: The first rest after a refusal, how it grows (it doubles) and where it stops.
REST_FIRST_S = 30.0
REST_MAX_S = 600.0
#: This many timeouts (or broken connections) within [TIMEOUT_WINDOW_S] rest the gate; one on its own does not.
TIMEOUTS_TO_REST = 3
TIMEOUT_WINDOW_S = 30.0

#: How long a caller waits for its turn when it does not say: a person's request is worth one answer or none inside a couple of seconds, background
#: work is patient.
INTERACTIVE_WAIT_S = 2.5
BACKGROUND_WAIT_S = 120.0

#: Deezer answers HTTP 200 with `{"error": {"code": ...}}` when it throttles or has nothing. The codes with a known meaning (developers.deezer.com/api/errors):
#: 4 is "Quota limit exceeded", 700 "Service busy"; 800 is a DataException, "no data": the thing asked for does not exist. Any other code is a question
#: Deezer did not like (a bad parameter, a query it cannot read): not an answer, but also no sign that the catalogue is unwell, so it rests nobody.
_THROTTLED_CODES = frozenset({4, 700})
_NO_DATA_CODE = 800


class LookupUnavailable(Exception):
    """The catalogue could not be asked just now. Not an answer: nothing may be remembered about the song or the artist because of it."""


class CatalogueOff(LookupUnavailable):
    """The Host switched the catalogue off (`ENCORE_CATALOGUE=0`), or nothing is set up in this process: no connection is opened."""


class BudgetSpent(LookupUnavailable):
    """The ceiling of outside requests one search may make is used up: the rest of that search is not asked."""


class NotInCatalogue(Exception):
    """The catalogue answered, and the thing asked for (an artist, an album) does not exist there. A fact, not an outage: it is NOT a
    [LookupUnavailable], and it says nothing about the catalogue's health."""


class Budget:
    """The most outside requests one search may make (the plan's ceiling is 7). A cached answer costs nothing; every request that goes out costs one."""

    def __init__(self, ceiling: int) -> None:
        self._left = ceiling
        self._lock = threading.Lock()

    @property
    def left(self) -> int:
        return self._left

    def spend(self) -> None:
        with self._lock:
            if self._left <= 0:
                raise BudgetSpent("the ceiling of outside requests for this search is used up")
            self._left -= 1


class Ticket:
    """A turn at the gate. Returned by [Gate.acquire]; given back, once, to [Gate.done]."""

    __slots__ = ("finished", "priority", "trial")

    def __init__(self, priority: Priority, *, trial: bool) -> None:
        self.priority = priority
        self.trial = trial
        self.finished = False


class Gate:
    """The rate, the order, the number in flight and the rest of every outside request to the catalogue. Thread-safe.

    The clock and the sleep are the caller's to give, so a test runs a whole day of requests on a fake clock. Waiting for a place or for a person's
    turn is a real wait on a condition (a fake clock never moves while a thread waits), so those waits are bounded by the real clock."""

    def __init__(
        self,
        *,
        burst: int = 6,
        rate: int = 20,
        per_s: float = 5.0,
        in_flight: int = 4,
        background_gap_s: float = 0.25,
        enabled: bool = True,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._enabled = enabled
        self._burst = float(burst)
        self._refill_per_s = rate / per_s
        self._in_flight = in_flight
        self._gap = background_gap_s
        self._clock = clock
        self._sleep = sleep
        self._cond = threading.Condition()
        self._tokens = float(burst)
        self._stamp = clock()
        self._busy = 0
        self._waiting_interactive = 0
        self._background_ready_at = float("-inf")
        #: When the rest ends (`None`: the catalogue is not resting), how many rests in a row it has had, and whether the one trial request is out.
        self._rest_until: float | None = None
        self._streak = 0
        self._trial_out = False
        self._timeouts: deque[float] = deque()

    # ------------------------------------------------------------------ the state

    @property
    def enabled(self) -> bool:
        return self._enabled

    def state(self) -> dict[str, Any]:
        """`{state: off|ok|resting, resumesInSec}`: whether the catalogue is holding this server back, and for how long (`info.catalogue`)."""
        if not self._enabled:
            return {"state": "off", "resumesInSec": 0}
        with self._cond:
            if self._rest_until is None:
                return {"state": "ok", "resumesInSec": 0}
            return {"state": "resting", "resumesInSec": max(0, math.ceil(self._rest_until - self._clock()))}

    # ------------------------------------------------------------------ taking a turn

    def acquire(self, priority: Priority = "interactive", *, wait_s: float | None = None) -> Ticket:
        """A turn, or [LookupUnavailable] (nothing is asked then): at once when the catalogue is resting or switched off, and after [wait_s] when the
        place, the token or the pause between background requests does not come in time. Give the ticket back to [done] when the request is over."""
        if not self._enabled:
            raise CatalogueOff("the catalogue is switched off on this server")
        limit = wait_s if wait_s is not None else (INTERACTIVE_WAIT_S if priority == "interactive" else BACKGROUND_WAIT_S)
        deadline = time.monotonic() + limit  # for the waits on the condition: a fake clock does not move while a thread waits
        slept = 0.0  # for the waits for a token: what the injected sleep has been asked to wait
        registered = False
        try:
            while True:
                pause = 0.0
                with self._cond:
                    now = self._clock()
                    trial = self._rest_over_trial(now)
                    delay = self._refill_and_delay(now, priority)
                    place = self._busy < self._in_flight
                    yielding = priority == "background" and self._waiting_interactive > 0  # a person is waiting: they go first
                    if delay is None and place and not yielding:
                        return self._take(now, priority, trial=trial)
                    if priority == "interactive" and not registered:
                        self._waiting_interactive += 1
                        registered = True
                    if place and not yielding and delay is not None:
                        if slept + delay > limit + 1e-9:
                            raise LookupUnavailable("the catalogue could not be asked in time: its turn did not come")
                        pause = delay
                    else:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise LookupUnavailable("the catalogue could not be asked in time: no place was free")
                        self._cond.wait(timeout=remaining)
                if pause > 0:
                    self._sleep(
                        pause
                    )  # for a token or the gap; outside the lock, so a finished request can still give its place back
                    slept += pause
        finally:
            if registered:
                with self._cond:
                    self._waiting_interactive -= 1
                    self._cond.notify_all()

    def _rest_over_trial(self, now: float) -> bool:
        """Raises while the catalogue rests or the trial is out; True when the rest is over and this caller would be the one trial request."""
        if self._rest_until is None:
            return False
        if now < self._rest_until:
            raise LookupUnavailable(f"the catalogue is resting for another {math.ceil(self._rest_until - now)} seconds")
        if self._trial_out:
            raise LookupUnavailable("the catalogue is being tried again; no other request goes meanwhile")
        return True

    def _refill_and_delay(self, now: float, priority: Priority) -> float | None:
        """Fills the bucket for the time that passed, and says how long this caller must pause for a token and (background work) for its gap:
        `None` when it may go now. A delay is never zero (a pause of nothing is not made)."""
        elapsed = max(0.0, now - self._stamp)
        self._stamp = now
        self._tokens = min(self._burst, self._tokens + elapsed * self._refill_per_s)
        delay = 0.0
        if self._tokens < 1.0 - 1e-9:
            delay = (1.0 - self._tokens) / self._refill_per_s
        if priority == "background":
            delay = max(delay, self._background_ready_at - now)
        return delay if delay > 1e-9 else None

    def _take(self, now: float, priority: Priority, *, trial: bool) -> Ticket:
        self._tokens = max(0.0, self._tokens - 1.0)
        self._busy += 1
        if priority == "background":
            self._background_ready_at = now + self._gap
        if trial:
            self._trial_out = True
        return Ticket(priority, trial=trial)

    # ------------------------------------------------------------------ giving it back

    def done(self, ticket: Ticket, outcome: Outcome) -> None:
        """The request is over: its place is free again and its outcome counts. `ok` (an answer, including "nothing there"), `refused` (a refusal or a
        throttling answer: the catalogue rests) or `timeout` (no answer: three within 30 seconds rest it). A ticket counts once, however often it is
        given back."""
        with self._cond:
            if ticket.finished:
                return
            ticket.finished = True
            self._busy = max(0, self._busy - 1)
            now = self._clock()
            if ticket.trial:
                self._trial_out = False
                if outcome == "ok":
                    self._end_rest()
                else:
                    self._begin_rest(now)
            elif outcome == "ok":
                self._timeouts.clear()
                if self._rest_until is None:
                    self._streak = 0
            elif outcome == "refused":
                self._begin_rest(now)
            else:
                while self._timeouts and now - self._timeouts[0] >= TIMEOUT_WINDOW_S:
                    self._timeouts.popleft()
                self._timeouts.append(now)
                if len(self._timeouts) >= TIMEOUTS_TO_REST:
                    self._begin_rest(now)
            self._cond.notify_all()

    def _begin_rest(self, now: float) -> None:
        if self._rest_until is not None and now < self._rest_until:
            return  # already resting (another request that was in flight failed too): not a second doubling
        rest = min(REST_MAX_S, REST_FIRST_S * 2**self._streak)
        self._streak += 1
        self._rest_until = now + rest
        self._timeouts.clear()

    def _end_rest(self) -> None:
        self._rest_until = None
        self._streak = 0
        self._timeouts.clear()


class DeezerClient:
    """Asks the catalogue, through a [Gate]. `get` returns Deezer's answer as a dict, or raises one of [LookupUnavailable] (could not ask) and
    [NotInCatalogue] (asked, and it is not there); it never returns an error as if it were an answer."""

    #: What a request may take: a person is waiting (2 s, 1 s to connect), background work may take its time (8 s, as the finders always did).
    TIMEOUTS = {"interactive": httpx.Timeout(2.0, connect=1.0), "background": httpx.Timeout(8.0)}

    def __init__(self, gate: Gate | None = None, http: httpx.Client | None = None, *, base_url: str = BASE_URL) -> None:
        self.gate = gate or Gate()
        self._own_http = http is None
        self._http = http or httpx.Client()
        self._base = base_url.rstrip("/")

    def close(self) -> None:
        if self._own_http:
            self._http.close()

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        priority: Priority = "interactive",
        budget: Budget | None = None,
        wait_s: float | None = None,
    ) -> dict[str, Any]:
        if budget is not None:
            budget.spend()
        ticket = self.gate.acquire(priority, wait_s=wait_s)
        outcome: Outcome = "refused"  # a request that ends in a surprise is not counted as a good answer
        try:
            body = self._ask(path, params, priority)
            outcome = "ok"
            return body
        except _Failed as failed:
            outcome = failed.outcome
            raise failed.error from failed.__cause__
        finally:
            self.gate.done(ticket, outcome)

    def _ask(self, path: str, params: dict[str, Any] | None, priority: Priority) -> dict[str, Any]:
        """One request: Deezer's answer, or a [_Failed] that says what the gate is to be told (and what the caller is to be raised)."""
        wanted = {key: value for key, value in (params or {}).items() if value is not None}
        try:
            response = self._http.get(
                self._base + path,
                params=wanted,
                headers={"User-Agent": f"encore-server/{__version__}"},
                timeout=self.TIMEOUTS[priority],
            )
        except httpx.HTTPError as error:  # a timeout, a refused connection, a broken network: no answer
            raise _Failed("timeout", LookupUnavailable(type(error).__name__)) from error
        status = response.status_code
        if status == 404:
            raise _Failed("ok", NotInCatalogue(path))
        if status == 429 or status >= 500 or status == 403:
            raise _Failed("refused", LookupUnavailable(f"HTTP {status}"))
        if status != 200:
            raise _Failed("ok", LookupUnavailable(f"HTTP {status}"))  # a question the catalogue did not like: it is not unwell
        try:
            body = response.json()
        except ValueError as error:
            raise _Failed("refused", LookupUnavailable("an answer that is not JSON")) from error
        if not isinstance(body, dict):
            raise _Failed("refused", LookupUnavailable("an answer that is not an object"))
        error_body = body.get("error")
        if error_body is not None:
            code = error_body.get("code") if isinstance(error_body, dict) else None
            if code == _NO_DATA_CODE:
                raise _Failed("ok", NotInCatalogue(path))
            if code in _THROTTLED_CODES:
                raise _Failed("refused", LookupUnavailable(f"throttled (code {code})"))
            raise _Failed("ok", LookupUnavailable(f"an error answer (code {code})"))
        return body


class _Failed(Exception):
    """Inside [DeezerClient.get]: a request that did not give an answer, with the outcome the gate is told and the exception the caller gets."""

    def __init__(self, outcome: Outcome, error: Exception) -> None:
        super().__init__(str(error))
        self.outcome = outcome
        self.error = error


def install(client: DeezerClient | None) -> None:
    """The client every look-up without a client of its own goes through: the application's, made once at start (`api.create_app`). `None` takes it
    away. Without one, [search_tracks] opens nothing and says [CatalogueOff] (a look-up must go through a gate or not at all)."""
    global _installed
    _installed = client


def installed() -> DeezerClient | None:
    return _installed


_installed: DeezerClient | None = None


def search_tracks(artist: str, title: str, *, client: httpx.Client | None = None, limit: int = 8) -> list[dict[str, Any]]:
    """The recordings the catalogue lists for "artist title" (a plain search: its field search finds nothing for many real songs), best first.

    An empty list means the catalogue answered and knows none. [LookupUnavailable] means it did not answer in a way that can be trusted.

    This is what the cover finder, the artist finder and the keeper's cover call: a *background* turn at the installed gate, so one budget covers the
    whole server. A caller that brings a client of its own (the finders' tests) is asked through that client, once, with a gate of its own that nobody
    else shares, so a refusal given to a test can never rest the gate of another."""
    asking = DeezerClient(Gate(background_gap_s=0.0), client) if client is not None else _installed
    if asking is None:
        raise CatalogueOff("no catalogue is set up in this process")
    try:
        body = asking.get("/search", {"q": f"{artist} {title}", "limit": limit}, priority="background")
    except NotInCatalogue as error:
        raise LookupUnavailable("an unexpected 'no data' answer to a search") from error
    data = body.get("data")
    if not isinstance(data, list):
        raise LookupUnavailable("an answer that is not a list of recordings")
    return [hit for hit in data if isinstance(hit, dict)]
