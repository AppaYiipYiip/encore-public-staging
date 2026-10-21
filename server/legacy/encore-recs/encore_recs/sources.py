"""The public services recommendations are made from, and nothing else (docs/47 section 2).

* **MusicBrainz**: who an artist is (an id from a name, never guessed), and an artist's newest releases. One request a second and a
  User-Agent that names the program are the rules of the house.
* **ListenBrainz** (the labs "similar artists"): artists whose listeners overlap. Free, no account.
* **Deezer**: an artist's most played songs, for the songs of a recommendation. Free, no key.

Only names and public ids leave the server: no person, no listening history, no password. Every answer is cached; every call is spaced;
a service that says "slow down" or does not answer ends the build for now ([Throttled]) instead of being hammered.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .cache import MISSING, Cache
from .textnorm import norm_artist

log = logging.getLogger("encore_recs.sources")

#: `(url) -> (status, parsed JSON or None)`; status 0 means not reachable. The tests give a fake.
Get = Callable[[str], "tuple[int, Any]"]

# MusicBrainz answers 503 to a User-Agent that names an address that is not the program's (measured on the dev VM: an invented project URL was
# refused, an honest "program/version (what it is)" accepted). So the string says what this is and, only if the person who runs the server chose
# to give one, a way to reach them (the services ask for that and it is kind to give, but it is theirs to give).
SIMILAR_ALGORITHM = "session_based_days_9000_session_300_contribution_5_threshold_15_limit_50_skip_30"

DAY = 86400.0


class Throttled(Exception):
    """A service did not answer or asked to be left alone: stop for now, the last list stays and the build is tried again later."""


def user_agent(version: str, contact: str = "") -> str:
    contact = " ".join(contact.split())[:80]
    return f"EncoreServer/{version} (self-hosted music server{'; contact: ' + contact if contact else ''})"


def make_get(agent: str, timeout: float = 40.0) -> Get:
    def get(url: str) -> tuple[int, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": agent, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - public services, by design
                raw, status = response.read(4_000_000), response.status
        except urllib.error.HTTPError as error:
            return error.code, None
        except (urllib.error.URLError, OSError, TimeoutError):
            return 0, None
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, None

    return get


http_get = make_get(user_agent("0"))


class Throttle:
    """At most one call every [interval] seconds (shared by every caller of one service)."""

    def __init__(self, interval: float, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self._interval, self._clock, self._sleep = interval, clock, sleep
        self._next = 0.0

    def wait(self) -> None:
        now = self._clock()
        if now < self._next:
            self._sleep(self._next - now)
            now = self._next
        self._next = now + self._interval


#: A public service that is "busy" for a moment (MusicBrainz does this now and then: measured, the third request in a row answered 503 and the next
#: was fine) is asked again after these waits before the build gives up.
RETRY_WAITS_S = (5.0, 15.0, 40.0)


class Sources:
    def __init__(self, cache: Cache, get: Get = http_get, *, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._cache = cache
        self._get = get
        self._sleep = sleep
        self._mb = Throttle(1.1, clock, sleep)
        self._lb = Throttle(0.7, clock, sleep)
        self._dz = Throttle(0.25, clock, sleep)

    # ------------------------------------------------------------------ one call

    def _fetch(self, throttle: Throttle, url: str) -> Any:
        for wait in (*RETRY_WAITS_S, None):
            throttle.wait()
            status, data = self._get(url)
            if status == 200 and data is not None:
                return data
            if status == 404:
                return None
            if wait is None or status not in (0, 429) and not 500 <= status < 600:
                break
            self._sleep(wait)
        raise Throttled(f"{url.split('?')[0]} answered {status}")

    def _cached(self, key: str, ttl: float | None, make: Callable[[], Any]) -> Any:
        found = self._cache.get(key)
        if found is not MISSING:
            return found
        value = make()
        self._cache.put(key, value, ttl)
        return value

    # ------------------------------------------------------------------ MusicBrainz

    def musicbrainz_artist(self, name: str) -> str | None:
        """The MusicBrainz id of the artist called [name], or None. Taken only when exactly one artist of that exact name scores
        (nearly) perfectly: a wrong artist would bring the wrong music, so an ambiguous name is skipped, never guessed."""
        want = norm_artist(name)
        if not want:
            return None

        def make() -> str | None:
            url = "https://musicbrainz.org/ws/2/artist/?" + urllib.parse.urlencode({"query": f'artist:"{name}"', "fmt": "json", "limit": 5})
            data = self._fetch(self._mb, url)
            found = [a for a in (data or {}).get("artists", []) if int(a.get("score", 0)) >= 95 and norm_artist(str(a.get("name", ""))) == want]
            return str(found[0]["id"]) if len(found) == 1 else None

        return self._cached(f"mb:artist:{want}", 30 * DAY, make)

    def fresh_releases(self, mbid: str, since: str) -> list[dict]:
        """Albums, EPs and singles of the artist first released on or after [since] (`YYYY-MM-DD`), newest first."""

        def make() -> list[dict]:
            url = "https://musicbrainz.org/ws/2/release-group?" + urllib.parse.urlencode(
                {"artist": mbid, "type": "album|ep|single", "limit": 100, "fmt": "json"})
            data = self._fetch(self._mb, url)
            out = [{"title": str(g.get("title", "")), "date": str(g.get("first-release-date", "")), "type": str(g.get("primary-type") or "").lower(),
                    "mbid": str(g.get("id", ""))} for g in (data or {}).get("release-groups", []) if len(str(g.get("first-release-date", ""))) >= 10]
            return sorted(out, key=lambda g: g["date"], reverse=True)[:12]

        return [g for g in self._cached(f"mb:releases:{mbid}", 1 * DAY, make) if g["date"] >= since]

    # ------------------------------------------------------------------ ListenBrainz

    def similar_artists(self, mbid: str) -> list[dict]:
        """`[{"mbid", "name", "score"}]`, best first: artists whose listeners overlap with this artist's."""

        def make() -> list[dict]:
            url = "https://labs.api.listenbrainz.org/similar-artists/json?" + urllib.parse.urlencode(
                {"artist_mbids": mbid, "algorithm": SIMILAR_ALGORITHM})
            data = self._fetch(self._lb, url)
            return [{"mbid": str(a["artist_mbid"]), "name": str(a.get("name", "")), "score": float(a.get("score", 0))}
                    for a in (data if isinstance(data, list) else []) if a.get("artist_mbid") and a.get("name")]

        return self._cached(f"lb:similar:{mbid}", 7 * DAY, make)

    # ------------------------------------------------------------------ Deezer

    def deezer_artist(self, name: str) -> int | None:
        """The Deezer id of the best-known artist whose name is exactly [name], or None."""
        want = norm_artist(name)
        if not want:
            return None

        def make() -> int | None:
            url = "https://api.deezer.com/search/artist?" + urllib.parse.urlencode({"q": f'"{name}"', "limit": 5})
            data = self._fetch(self._dz, url)
            same = [a for a in (data or {}).get("data", []) if norm_artist(str(a.get("name", ""))) == want]
            return int(max(same, key=lambda a: int(a.get("nb_fan") or 0))["id"]) if same else None

        return self._cached(f"dz:artist:{want}", 30 * DAY, make)

    def deezer_top(self, artist_id: int) -> list[dict]:
        """`[{"title", "artist", "album", "duration", "rank"}]`: the artist's most played songs, most played first."""

        def make() -> list[dict]:
            data = self._fetch(self._dz, f"https://api.deezer.com/artist/{int(artist_id)}/top?limit=50")
            return [{"title": str(t.get("title_short") or t.get("title") or ""), "artist": str((t.get("artist") or {}).get("name") or ""),
                     "album": str((t.get("album") or {}).get("title") or ""), "duration": int(t.get("duration") or 0),
                     "rank": int(t.get("rank") or 0)} for t in (data or {}).get("data", []) if t.get("title")]

        return self._cached(f"dz:top:{int(artist_id)}", 7 * DAY, make)
