"""What the public services answered, remembered for a while (docs/47 section 4 step 6): artists change slowly, and the services ask to be
spared repeat questions. One small SQLite file; values are JSON. A *negative* answer ("no such artist") is cached too, or every night would
ask again about every artist the catalogue does not know."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

MISSING = object()  # "not in the cache" (None is a value: a cached "nothing found")


class Cache:
    def __init__(self, path: Path | str, clock: Callable[[], float] = time.time) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL)")
        self._lock = threading.Lock()
        self._clock = clock

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def get(self, key: str) -> Any:
        with self._lock:
            row = self._db.execute("SELECT value, expires FROM cache WHERE key=?", (key,)).fetchone()
        if row is None or (row[1] is not None and row[1] <= self._clock()):
            return MISSING
        return json.loads(row[0])

    def put(self, key: str, value: Any, ttl_s: float | None) -> None:
        expires = None if ttl_s is None else self._clock() + ttl_s
        with self._lock:
            self._db.execute("INSERT INTO cache (key, value, expires) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                             "expires=excluded.expires", (key, json.dumps(value), expires))
            self._db.commit()

    def sweep(self) -> int:
        """Forgets what has expired. How many entries went."""
        with self._lock:
            cursor = self._db.execute("DELETE FROM cache WHERE expires IS NOT NULL AND expires <= ?", (self._clock(),))
            self._db.commit()
            return cursor.rowcount
