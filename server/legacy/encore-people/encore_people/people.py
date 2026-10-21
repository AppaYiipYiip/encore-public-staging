"""Who may do what on this server (ADR-092): owners, people who may invite, and guests.

* **owner**: invites (guests, or people who may invite), sees everybody, changes roles, removes people. There can be several.
  The music server's administrators and the names the person who runs the server lists (`PEOPLE_OWNERS`) are *founding owners*: always owners,
  never changed from the app, so the server can never be left without one.
* **inviter** ("Can invite"): makes invitations for guests, and sees and cancels only their own.
* **guest**: listens.

Only what differs from the default is stored: everybody the service has no record of is a guest, which is the safe answer for the accounts that
already exist (made by hand, or before this feature).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

OWNER, INVITER, GUEST = "owner", "inviter", "guest"
ROLES = (OWNER, INVITER, GUEST)


def normalize(name: str) -> str:
    """Account names are matched without regard to case (the music server does the same)."""
    return name.strip().lower()


class DirectoryUnavailable(Exception):
    """The music server did not let the service in (it limits sign-ins, or it is not answering): try again in a moment."""


class Directory(Protocol):
    """The music server's accounts, seen with an administrator's login."""

    def listing(self) -> list[dict]:
        """`[{"name": str, "admin": bool}, ...]`"""

    def remove_person(self, name: str) -> None:
        """Deletes the account. The person's music folder and files are never touched."""

    def set_password(self, name: str, password: str) -> None:
        """Gives the account a new password (the administrator's login does it; nobody's old password is needed)."""

    def add_person(self, username: str, password: str) -> None:
        """Makes an account with its own folder and library. Raises `ProvisionError` (a sentence) when the name will not do."""


@dataclass(frozen=True)
class Record:
    username: str
    role: str
    invited_by: str | None
    joined_at: float | None


class Roles:
    """The roles the service has been told about (an owner changed them, or an invitation carried one)."""

    def __init__(self, db_path: Path | None = None, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        target = ":memory:"
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            target = str(db_path)
        self._db = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS roles("
            " username TEXT PRIMARY KEY,"
            " role TEXT NOT NULL,"
            " invited_by TEXT,"
            " joined_at REAL)")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def get(self, username: str) -> Record | None:
        with self._lock:
            row = self._db.execute("SELECT username, role, invited_by, joined_at FROM roles WHERE username=?",
                                   (normalize(username),)).fetchone()
        return Record(*row) if row else None

    def all(self) -> dict[str, Record]:
        with self._lock:
            rows = self._db.execute("SELECT username, role, invited_by, joined_at FROM roles").fetchall()
        return {r[0]: Record(*r) for r in rows}

    def joined(self, username: str, role: str, invited_by: str) -> None:
        """A person who came through an invitation: their role, who invited them, when."""
        assert role in ROLES
        with self._lock:
            self._db.execute(
                "INSERT INTO roles(username, role, invited_by, joined_at) VALUES(?,?,?,?)"
                " ON CONFLICT(username) DO UPDATE SET role=excluded.role, invited_by=excluded.invited_by, joined_at=excluded.joined_at",
                (normalize(username), role, normalize(invited_by), self._clock()))

    def set_role(self, username: str, role: str) -> None:
        """Changes a role and keeps who invited the person and when they joined."""
        assert role in ROLES
        with self._lock:
            self._db.execute(
                "INSERT INTO roles(username, role) VALUES(?,?) ON CONFLICT(username) DO UPDATE SET role=excluded.role",
                (normalize(username), role))

    def forget(self, username: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM roles WHERE username=?", (normalize(username),))
