"""What the owner has done to a person's account besides its role, and who has asked for help (docs/48).

* **paused**: the owner locked the account; its password was replaced by one nobody knows. Shown as "paused" in the list; ended by a reset.
* **must change**: the person is using a temporary password and is asked to choose their own at the next sign-in.
* **asks**: "I forgot my password" taps from the app's sign-in screen. The answer to the person is always the same (so nobody can find out who has
  an account); only the owner sees the name, as a card on the admin's front page. One ask per person per ten minutes.
* **reset codes**: a one-time link the owner sends to somebody who forgot their password; valid one hour, used once, kept only as a hash.

Everything lives in one small SQLite file in the service's data folder; nothing here is a password.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

CODE_TTL_S = 3600.0
ASK_EVERY_S = 600.0


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _key(name: str) -> str:
    return name.strip().lower()


class Standing:
    def __init__(self, db_path: Path | None = None, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        target = ":memory:"
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            target = str(db_path)
        self._db = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
        self._db.executescript(
            "CREATE TABLE IF NOT EXISTS flags(username TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0, must_change INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE IF NOT EXISTS asks(username TEXT PRIMARY KEY, asked_at REAL NOT NULL);"
            "CREATE TABLE IF NOT EXISTS resets(code_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------ flags

    def flags(self, name: str) -> tuple[bool, bool]:
        """`(paused, must_change)`."""
        with self._lock:
            row = self._db.execute("SELECT paused, must_change FROM flags WHERE username=?", (_key(name),)).fetchone()
        return (bool(row[0]), bool(row[1])) if row else (False, False)

    def all_flags(self) -> dict[str, tuple[bool, bool]]:
        with self._lock:
            rows = self._db.execute("SELECT username, paused, must_change FROM flags").fetchall()
        return {r[0]: (bool(r[1]), bool(r[2])) for r in rows}

    def set_flags(self, name: str, *, paused: bool | None = None, must_change: bool | None = None) -> None:
        current_paused, current_must = self.flags(name)
        with self._lock:
            self._db.execute(
                "INSERT INTO flags(username, paused, must_change) VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET "
                "paused=excluded.paused, must_change=excluded.must_change",
                (_key(name), int(current_paused if paused is None else paused), int(current_must if must_change is None else must_change)))

    # ------------------------------------------------------------------ "I forgot my password"

    def ask(self, name: str) -> bool:
        """Records that [name] asked for help. `False` when they asked less than ten minutes ago (the owner has the card already)."""
        now = self._clock()
        with self._lock:
            row = self._db.execute("SELECT asked_at FROM asks WHERE username=?", (_key(name),)).fetchone()
            if row and now - row[0] < ASK_EVERY_S:
                return False
            self._db.execute("INSERT INTO asks(username, asked_at) VALUES(?,?) ON CONFLICT(username) DO UPDATE SET asked_at=excluded.asked_at",
                             (_key(name), now))
        return True

    def asks(self) -> dict[str, float]:
        with self._lock:
            return {r[0]: r[1] for r in self._db.execute("SELECT username, asked_at FROM asks")}

    def dismiss(self, name: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM asks WHERE username=?", (_key(name),))

    # ------------------------------------------------------------------ one-time reset links

    def make_code(self, name: str) -> tuple[str, float]:
        """A new one-time code for [name] (older open ones for the same person stop working). Returns `(code, expires_at)`."""
        code = secrets.token_urlsafe(18)
        expires = self._clock() + CODE_TTL_S
        with self._lock:
            self._db.execute("DELETE FROM resets WHERE username=?", (_key(name),))
            self._db.execute("INSERT INTO resets(code_hash, username, expires_at) VALUES(?,?,?)", (_hash(code), _key(name), expires))
        return code, expires

    def peek(self, code: str) -> str | None:
        """Whose code this is, if it is still good; nothing is used up."""
        if not isinstance(code, str) or not 10 <= len(code) <= 100:
            return None
        with self._lock:
            row = self._db.execute("SELECT username, expires_at, used FROM resets WHERE code_hash=?", (_hash(code),)).fetchone()
        if not row or row[2] or row[1] < self._clock():
            return None
        return row[0]

    def redeem(self, code: str) -> str | None:
        """Uses the code up and says whose it was; `None` when it is not (or no longer) good."""
        who = self.peek(code)
        if who is None:
            return None
        with self._lock:
            done = self._db.execute("UPDATE resets SET used=1 WHERE code_hash=? AND used=0", (_hash(code),)).rowcount
        return who if done else None

    def forget(self, name: str) -> None:
        with self._lock:
            for table in ("flags", "asks", "resets"):
                self._db.execute(f"DELETE FROM {table} WHERE username=?", (_key(name),))
