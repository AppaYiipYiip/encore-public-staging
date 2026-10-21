"""What the service remembers: who asked for a better copy of which song and how far it has got, the swaps it made (the upgrade map the
phones read), and a few settings. One small SQLite file; nothing in it is a password, and nothing about what anyone plays.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Callable

# --- the states of a request (docs/46 section 3). The first five are "in somebody's hands"; the rest are final or waiting to be retried.
QUEUED = "queued"                # asked for, not yet matched to a release
GETTING_READY = "getting_ready"  # matched; Lidarr is learning the artist's releases (minutes for a prolific artist)
SEARCHING = "searching"          # the album is wanted; Soulseek is being searched
DOWNLOADING = "downloading"      # peers are sending it
DELIVERING = "delivering"        # it is in the pool; being put in place
READY = "ready"                  # swapped: the better copy plays
NOT_FOUND = "not_found"          # nobody shares it (yet); tried again later, a few times
NO_MATCH = "no_match"            # the song could not be matched to a release, or the release is not the song's
CANCELLED = "cancelled"
FAILED = "failed"                # something broke that the person cannot fix; the owner's page says what

ACTIVE = (QUEUED, GETTING_READY, SEARCHING, DOWNLOADING, DELIVERING)
FINAL = (READY, NO_MATCH, CANCELLED, FAILED)


@dataclass(frozen=True)
class Want:
    id: int
    person: str
    song_id: str
    artist: str
    album: str
    title: str
    year: int | None
    track: int | None
    duration: float | None
    quick_path: str           # relative to the music folder: where the quick copy is
    state: str
    detail: str               # a plain sentence for the person ("Waiting for the artist's releases to load")
    release_group: str        # MusicBrainz id of the chosen album, '' until matched
    lidarr_artist: int | None
    lidarr_album: int | None
    attempts: int
    next_try: float | None
    created: float
    updated: float
    new_song_id: str          # after the swap


_COLUMNS = [f.name for f in fields(Want)]
_SCHEMA = """
CREATE TABLE IF NOT EXISTS wants (
  id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT NOT NULL, song_id TEXT NOT NULL, artist TEXT NOT NULL, album TEXT NOT NULL,
  title TEXT NOT NULL, year INTEGER, track INTEGER, duration REAL, quick_path TEXT NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
  release_group TEXT NOT NULL DEFAULT '', lidarr_artist INTEGER, lidarr_album INTEGER, attempts INTEGER NOT NULL DEFAULT 0, next_try REAL,
  created REAL NOT NULL, updated REAL NOT NULL, new_song_id TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS wants_person ON wants(person);
CREATE INDEX IF NOT EXISTS wants_state ON wants(state);
CREATE TABLE IF NOT EXISTS upgrades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT NOT NULL, old_id TEXT NOT NULL, new_id TEXT NOT NULL, quality TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS upgrades_person ON upgrades(person, id);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path | str, clock: Callable[[], float] = time.time) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._lock = threading.RLock()
        self._clock = clock

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------ wants

    @staticmethod
    def _want(row: sqlite3.Row | None) -> Want | None:
        return Want(**{name: row[name] for name in _COLUMNS}) if row is not None else None

    def add_want(self, *, person: str, song_id: str, artist: str, album: str, title: str, year: int | None, track: int | None,
                 duration: float | None, quick_path: str) -> tuple[Want, bool]:
        """`(want, created)`. A person who asks twice for the same song gets the first request back, not a second one."""
        with self._lock:
            row = self._db.execute(
                f"SELECT * FROM wants WHERE person=? AND song_id=? AND state IN ({','.join('?' * len(ACTIVE))}) ORDER BY id DESC LIMIT 1",
                (person, song_id, *ACTIVE)).fetchone()
            if row is not None:
                return self._want(row), False  # type: ignore[return-value]
            now = self._clock()
            cursor = self._db.execute(
                "INSERT INTO wants (person, song_id, artist, album, title, year, track, duration, quick_path, state, detail, created, updated) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (person, song_id, artist, album, title, year, track, duration, quick_path, QUEUED, "Waiting its turn.", now, now))
            self._db.commit()
            return self.get(cursor.lastrowid), True  # type: ignore[return-value,arg-type]

    def get(self, want_id: int) -> Want | None:
        with self._lock:
            return self._want(self._db.execute("SELECT * FROM wants WHERE id=?", (want_id,)).fetchone())

    def of_person(self, person: str, limit: int = 500) -> list[Want]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM wants WHERE person=? ORDER BY id DESC LIMIT ?", (person, limit)).fetchall()
        return [self._want(r) for r in rows]  # type: ignore[misc]

    def in_state(self, *states: str) -> list[Want]:
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM wants WHERE state IN ({','.join('?' * len(states))}) ORDER BY id", states).fetchall()
        return [self._want(r) for r in rows]  # type: ignore[misc]

    def recent(self, limit: int = 50) -> list[Want]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM wants ORDER BY updated DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return [self._want(r) for r in rows]  # type: ignore[misc]

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute("SELECT state, COUNT(*) AS n FROM wants GROUP BY state").fetchall()
        return {r["state"]: r["n"] for r in rows}

    def count_since(self, since: float, *, states: tuple[str, ...] | None = None) -> int:
        with self._lock:
            query, args = "SELECT COUNT(*) FROM wants WHERE created>=?", [since]
            if states:
                query += f" AND state IN ({','.join('?' * len(states))})"
                args += list(states)
            return int(self._db.execute(query, args).fetchone()[0])

    def update(self, want_id: int, **changes: object) -> Want | None:
        unknown = set(changes) - set(_COLUMNS) - {"id"}
        if unknown:
            raise ValueError(f"unknown columns {sorted(unknown)}")
        with self._lock:
            changes["updated"] = self._clock()
            names = ", ".join(f"{name}=?" for name in changes)
            self._db.execute(f"UPDATE wants SET {names} WHERE id=?", (*changes.values(), want_id))
            self._db.commit()
            return self.get(want_id)

    def forget_person(self, person: str) -> None:
        """A person who was removed from the server leaves nothing behind here."""
        with self._lock:
            self._db.execute("DELETE FROM wants WHERE person=?", (person,))
            self._db.commit()

    # ------------------------------------------------------------------ the upgrade map

    def add_upgrade(self, person: str, old_id: str, new_id: str, quality: str) -> int:
        """Records "song [old_id] is now song [new_id]". The map belongs to the whole server (two people can hold the same song, and a phone
        only acts on the ids it has), so a swap that is already in the map is not added twice; [person] is who asked."""
        with self._lock:
            row = self._db.execute("SELECT id FROM upgrades WHERE old_id=? AND new_id=?", (old_id, new_id)).fetchone()
            if row is not None:
                return int(row["id"])
            cursor = self._db.execute("INSERT INTO upgrades (person, old_id, new_id, quality, at) VALUES (?,?,?,?,?)",
                                      (person, old_id, new_id, quality, self._clock()))
            self._db.commit()
            return int(cursor.lastrowid)

    def upgrades_after(self, after: int, limit: int = 1000) -> list[dict]:
        """The swaps with a number above [after], oldest first: a phone remembers the last number it saw and moves its likes, playlist places
        and downloads for the ids it holds. Nothing in it is private: two song ids and a quality."""
        with self._lock:
            rows = self._db.execute("SELECT * FROM upgrades WHERE id>? ORDER BY id LIMIT ?", (after, limit)).fetchall()
        return [{"n": r["id"], "old": r["old_id"], "new": r["new_id"], "quality": r["quality"], "at": r["at"]} for r in rows]

    # ------------------------------------------------------------------ settings

    def setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            self._db.commit()
