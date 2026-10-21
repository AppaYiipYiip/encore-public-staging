"""What the service remembers: each person's last lists, what each person said "not for me" to, which new releases they have been told about,
how the surfaces are doing (counts only), and the owner's switch. One small SQLite file; nothing in it is a password or a listening history
(the listening stays in the music server's database and is read at build time).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from .build import Hidden, Result
from .textnorm import norm_artist, norm_title

_SCHEMA = """
CREATE TABLE IF NOT EXISTS builds (person TEXT PRIMARY KEY, built_at REAL NOT NULL, state TEXT NOT NULL, rows TEXT NOT NULL, pool TEXT NOT NULL,
  seeds INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS hidden (id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT NOT NULL, artist TEXT NOT NULL, title TEXT, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS hidden_person ON hidden(person);
CREATE TABLE IF NOT EXISTS seen (person TEXT NOT NULL, release TEXT NOT NULL, PRIMARY KEY (person, release));
CREATE TABLE IF NOT EXISTS stats (surface TEXT NOT NULL, event TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (surface, event));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

SURFACES = {"made-for-you", "deeper-cuts", "because", "new-releases", "pool", "radio"}
EVENTS = {"shown", "played", "starred"}


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

    # ------------------------------------------------------------------ the lists

    def save_build(self, person: str, result: Result, at: float | None = None) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO builds (person, built_at, state, rows, pool, seeds) VALUES (?,?,?,?,?,?) ON CONFLICT(person) DO UPDATE SET "
                "built_at=excluded.built_at, state=excluded.state, rows=excluded.rows, pool=excluded.pool, seeds=excluded.seeds",
                (person, self._clock() if at is None else at, result.state, json.dumps(result.rows), json.dumps(result.pool), result.seeds))
            for release in result.releases_seen:
                self._db.execute("INSERT OR IGNORE INTO seen (person, release) VALUES (?, ?)", (person, release))
            self._db.commit()

    def build_of(self, person: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM builds WHERE person=?", (person,)).fetchone()
        if row is None:
            return None
        return {"builtAt": row["built_at"], "state": row["state"], "rows": json.loads(row["rows"]), "pool": json.loads(row["pool"]), "seeds": row["seeds"]}

    def built_count(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM builds WHERE state='ready'").fetchone()[0])

    def seen_releases(self, person: str) -> set[str]:
        with self._lock:
            return {r["release"] for r in self._db.execute("SELECT release FROM seen WHERE person=?", (person,))}

    # ------------------------------------------------------------------ "not for me"

    def hide(self, person: str, artist: str, title: str | None = None) -> int:
        """A person says "not for me" to an artist (no [title]) or to one song. Saying it twice is saying it once."""
        with self._lock:
            row = self._db.execute("SELECT id FROM hidden WHERE person=? AND lower(artist)=lower(?) AND COALESCE(lower(title),'')=COALESCE(lower(?),'')",
                                   (person, artist, title)).fetchone()
            if row is not None:
                return int(row["id"])
            cursor = self._db.execute("INSERT INTO hidden (person, artist, title, created) VALUES (?,?,?,?)", (person, artist, title, self._clock()))
            self._db.commit()
            return int(cursor.lastrowid)

    def hidden_list(self, person: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id, artist, title, created FROM hidden WHERE person=? ORDER BY id DESC", (person,)).fetchall()
        return [{"id": r["id"], "artist": r["artist"], "title": r["title"], "createdAt": r["created"]} for r in rows]

    def unhide(self, person: str, hidden_id: int) -> bool:
        with self._lock:
            cursor = self._db.execute("DELETE FROM hidden WHERE id=? AND person=?", (hidden_id, person))
            self._db.commit()
            return cursor.rowcount > 0

    def hidden_for(self, person: str) -> Hidden:
        hidden = Hidden()
        for item in self.hidden_list(person):
            if item["title"]:
                hidden.songs.add((norm_artist(item["artist"]), norm_title(item["title"])))
            else:
                hidden.artists.add(norm_artist(item["artist"]))
        return hidden

    # ------------------------------------------------------------------ how the surfaces are doing (counts for everybody together)

    def count(self, surface: str, event: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO stats (surface, event, n) VALUES (?,?,1) ON CONFLICT(surface, event) DO UPDATE SET n = n + 1", (surface, event))
            self._db.commit()

    def totals(self) -> dict[str, dict[str, int]]:
        """Per surface, how many suggestions were shown, played and starred, over all people. Never per person."""
        out: dict[str, dict[str, int]] = {}
        with self._lock:
            for row in self._db.execute("SELECT surface, event, n FROM stats"):
                out.setdefault(row["surface"], {})[row["event"]] = row["n"]
        return out

    # ------------------------------------------------------------------ settings, and forgetting a person

    def setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            self._db.commit()

    def forget_person(self, person: str) -> None:
        with self._lock:
            for table in ("builds", "hidden", "seen"):
                self._db.execute(f"DELETE FROM {table} WHERE person=?", (person,))
            self._db.commit()
