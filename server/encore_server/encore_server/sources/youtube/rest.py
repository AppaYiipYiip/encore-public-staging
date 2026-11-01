"""When YouTube pushes back, the whole server rests (docs/04 section 5, ADR-R6).

YouTube judges the *address* the requests come from, not the person asking: a few refusals mean every request from this machine is about
to be refused, and every further try makes the next refusal last longer. So one refusal ("Sign in to confirm you're not a bot") puts the
server to rest for everybody: background work (matching, keeping) does not even try; a tap may try once in a while to find out whether
the rest is over. Each refusal in a row doubles the rest (30 minutes, 1 hour, 2 ... up to a day); one success ends it. The state is kept
in the database, so a restart does not start by hammering YouTube again.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .errors import DownloadError

log = logging.getLogger("encore_server.youtube")


class RestStore(Protocol):
    def load(self) -> tuple[float, int]: ...

    def save(self, until: float, streak: int) -> None: ...


class Rest:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        first_s: float = 1800.0,
        max_s: float = 24 * 3600.0,
        probe_every_s: float = 30.0,
        store: RestStore | None = None,
    ) -> None:
        self._clock = clock
        self._first = first_s
        self._max = max_s
        self._probe_every = probe_every_s
        self._store = store
        self._lock = threading.Lock()
        self._until, self._streak = store.load() if store is not None else (0.0, 0)
        self._last_probe = 0.0

    def blocked(self) -> None:
        """YouTube refused: rest, twice as long as last time when the last try also failed."""
        with self._lock:
            self._streak += 1
            self._until = self._clock() + min(self._max, self._first * 2 ** (self._streak - 1))
            self._save()

    def ok(self) -> None:
        """A request got through: the rest is over."""
        with self._lock:
            if self._streak or self._until:
                self._streak, self._until = 0, 0.0
                self._save()

    def remaining(self) -> float:
        """Seconds of rest left (0 when YouTube is being asked as usual)."""
        return max(0.0, self._until - self._clock())

    def allow_probe(self) -> bool:
        """May a person's tap ask YouTube now? Always when not resting; while resting once every [probe_every_s], to notice the end."""
        with self._lock:
            if self._until <= self._clock():
                return True
            if self._clock() - self._last_probe >= self._probe_every:
                self._last_probe = self._clock()
                return True
            return False

    def probe_open(self) -> bool:
        """Whether a probe may go now, WITHOUT using it up: the search that comes before an extraction looks here, so a tap during a rest that
        may not probe makes no search at all, and a tap that may leaves the probe to the extraction that follows (B8)."""
        with self._lock:
            return self._until <= self._clock() or self._clock() - self._last_probe >= self._probe_every

    def snapshot(self) -> dict[str, Any]:
        left = self.remaining()
        return {"state": "resting" if left > 0 else "ok", "resumesInSec": int(left) if left > 0 else 0}

    def _save(self) -> None:
        if self._store is not None:
            self._store.save(self._until, self._streak)


class Lookups:
    """How many times the server has asked YouTube today (UTC), for the log: two people using one home address every day is a number worth
    knowing (docs/tasks P3-12), and one a person can read with `encore logs`. Only the number: no person, no song. Kept in memory, told to the
    log every [every]th time and when a new day starts."""

    def __init__(self, *, clock: Callable[[], float] = time.time, every: int = 25) -> None:
        self._clock = clock
        self._every = max(1, every)
        self._lock = threading.Lock()
        self._day = self._today()
        self._count = 0

    def _today(self) -> int:
        return int(self._clock() // 86400)

    @property
    def today(self) -> int:
        with self._lock:
            return self._count if self._day == self._today() else 0

    def note(self) -> int:
        """One more look-up; returns today's count."""
        with self._lock:
            today = self._today()
            if today != self._day:
                if self._count:
                    log.info("youtube look-ups yesterday: %d", self._count)
                self._day, self._count = today, 0
            self._count += 1
            if self._count % self._every == 0:
                log.info("youtube look-ups today: %d", self._count)
            return self._count


class CountedSearcher:
    """A searcher (see lean.Searcher) that tells [Lookups] about every request it makes: a search at YouTube Music is a look-up like an
    extraction, and a tap that is not clear-cut makes up to three of them (B8: they were not in the count)."""

    def __init__(self, inner: Any, lookups: Lookups) -> None:
        self._inner = inner
        self._lookups = lookups

    def songs(self, query: str, limit: int) -> list[dict[str, Any]]:
        self._lookups.note()
        found: list[dict[str, Any]] = self._inner.songs(query, limit)
        return found

    def videos(self, query: str, limit: int) -> list[dict[str, Any]]:
        self._lookups.note()
        found: list[dict[str, Any]] = self._inner.videos(query, limit)
        return found


class Guarded:
    """An extractor that obeys the rest: it does not ask YouTube while the server rests (except to probe), and tells the rest what happened."""

    def __init__(self, inner: Any, rest: Rest, lookups: Lookups | None = None) -> None:
        self._inner = inner
        self._rest = rest
        self.lookups = lookups if lookups is not None else Lookups()

    def extract(self, video_id: str, info: Path, cookiefile: str | None = None) -> None:
        if not self._rest.allow_probe():
            raise DownloadError("blocked", "YouTube is being given a rest")
        self.lookups.note()
        try:
            self._inner.extract(video_id, info, cookiefile)
        except DownloadError as error:
            if error.code == "blocked":
                log.warning("youtube refused the server (look-up %d today): resting", self.lookups.today)
                self._rest.blocked()
            elif error.code in ("unavailable", "age_restricted", "not_found"):
                self._rest.ok()  # YouTube answered, about this video
            raise
        self._rest.ok()


class DbRestStore:
    """Keeps the rest in the `setting` table (`youtube_rest`: "<until epoch seconds>,<streak>")."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def load(self) -> tuple[float, int]:
        with self._db.read() as conn:
            row = conn.execute("SELECT value FROM setting WHERE key = 'youtube_rest'").fetchone()
        if row is None:
            return 0.0, 0
        try:
            until, streak = row["value"].split(",")
            return float(until), int(streak)
        except ValueError:
            return 0.0, 0

    def save(self, until: float, streak: int) -> None:
        with self._db.tx() as conn:
            conn.execute(
                "INSERT INTO setting (key, value) VALUES ('youtube_rest', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"{until:.0f},{streak}",),
            )
