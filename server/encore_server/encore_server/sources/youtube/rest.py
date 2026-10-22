"""When YouTube pushes back, the whole server rests (docs/04 section 5, ADR-R6).

YouTube judges the *address* the requests come from, not the person asking: a few refusals mean every request from this machine is about
to be refused, and every further try makes the next refusal last longer. So one refusal ("Sign in to confirm you're not a bot") puts the
server to rest for everybody: background work (matching, keeping) does not even try; a tap may try once in a while to find out whether
the rest is over. Each refusal in a row doubles the rest (30 minutes, 1 hour, 2 ... up to a day); one success ends it. The state is kept
in the database, so a restart does not start by hammering YouTube again.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .errors import DownloadError


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

    def snapshot(self) -> dict[str, Any]:
        left = self.remaining()
        return {"state": "resting" if left > 0 else "ok", "resumesInSec": int(left) if left > 0 else 0}

    def _save(self) -> None:
        if self._store is not None:
            self._store.save(self._until, self._streak)


class Guarded:
    """An extractor that obeys the rest: it does not ask YouTube while the server rests (except to probe), and tells the rest what happened."""

    def __init__(self, inner: Any, rest: Rest) -> None:
        self._inner = inner
        self._rest = rest

    def extract(self, video_id: str, info: Path, cookiefile: str | None = None) -> None:
        if not self._rest.allow_probe():
            raise DownloadError("blocked", "YouTube is being given a rest")
        try:
            self._inner.extract(video_id, info, cookiefile)
        except DownloadError as error:
            if error.code == "blocked":
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
