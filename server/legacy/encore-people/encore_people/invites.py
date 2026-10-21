"""Invites (docs/35 section 3, ADR-087): a code that lets one friend create their own account on this server.

* The code is random (192 bits) and only its hash is stored; the link is the only place it ever exists.
* One use, seven days, revocable. A wrong, an expired, a revoked and a used code are indistinguishable to the person holding it.
* Redeeming is an atomic claim, so two people racing for one code make exactly one account, and a failure (a bad name, a taken name,
  the music server down) gives the code back: a typo must never burn an invitation.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .people import GUEST, ROLES, normalize

log = logging.getLogger("encore_people.invites")

INVITE_TTL_S = 7 * 24 * 3600
_MAX_CODE_LEN = 200
NOT_VALID = "This invitation is not valid any more. Ask whoever sent it for a new one."

# Names an invited person may not take: they would confuse the people who use the server, or look like something they are not.
RESERVED_NAMES = frozenset({"admin", "administrator", "root", "owner", "everyone", "shared", "system", "navidrome", "encore",
                            "guest", "support", "server"})
# A letter first, like the account tool (encore_user.py) requires: a name it would refuse must not use up an invitation.
_USERNAME = re.compile(r"^[a-z][a-z0-9._-]{2,31}$")


class InviteError(Exception):
    """Safe to show to the person redeeming: it never carries internal detail."""


class ProvisionError(Exception):
    """The music server refused for a reason the person can act on (for example, the name is taken). Safe to show."""


class Provisioner(Protocol):
    def add_person(self, username: str, password: str) -> None:
        """Creates the folder, the library and the account (only their own library plus the shared one). Raises ProvisionError
        for something the person can fix; any other exception means the server is in trouble."""


def check_username(name: str) -> str | None:
    """`None` when acceptable, else a plain sentence."""
    if not isinstance(name, str) or not _USERNAME.match(name):
        return "Choose a name of 3 to 32 characters in lower case: letters, digits, dots, dashes or underscores, starting with a letter."
    if name in RESERVED_NAMES:
        return "That name is not available. Choose another."
    return None


def check_password(password: str) -> str | None:
    if not isinstance(password, str) or not 8 <= len(password) <= 200:
        return "Choose a password of at least 8 characters."
    return None


@dataclass(frozen=True)
class Made:
    id: int
    code: str
    expires_at: float


@dataclass(frozen=True)
class Info:
    id: int
    inviter: str
    expires_at: float
    role: str = GUEST  # what the invited person becomes


@dataclass(frozen=True)
class Row:
    id: int
    inviter: str
    created_at: float
    expires_at: float
    state: str  # open | used | revoked | expired
    redeemed_by: str | None
    redeemed_at: float | None
    role: str = GUEST


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class Invites:
    def __init__(self, db_path: Path, *, provisioner: Provisioner, clock: Callable[[], float] = time.time,
                 rand: Callable[[int], str] = secrets.token_urlsafe) -> None:
        self._prov = provisioner
        self._clock = clock
        self._rand = rand
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS invites("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " code_hash TEXT NOT NULL UNIQUE,"
            " inviter TEXT NOT NULL,"
            " created_at REAL NOT NULL,"
            " expires_at REAL NOT NULL,"
            " state TEXT NOT NULL,"
            " redeemed_by TEXT,"
            " redeemed_at REAL,"
            " role TEXT NOT NULL DEFAULT 'guest')")
        try:  # a database made before roles existed
            self._db.execute("ALTER TABLE invites ADD COLUMN role TEXT NOT NULL DEFAULT 'guest'")
        except sqlite3.OperationalError:
            pass  # already there
        # A crash between "claimed" and "finished" must not strand an invitation.
        self._db.execute("UPDATE invites SET state='open' WHERE state='redeeming'")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------ admin side
    def create(self, inviter: str, role: str = GUEST) -> Made:
        if role not in ROLES:
            raise ValueError(role)
        code = self._rand(24)
        now = self._clock()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO invites(code_hash, inviter, created_at, expires_at, state, role) VALUES(?,?,?,?, 'open', ?)",
                (_hash(code), normalize(inviter), now, now + INVITE_TTL_S, role))
        return Made(id=int(cur.lastrowid), code=code, expires_at=now + INVITE_TTL_S)

    def revoke(self, invite_id: int, *, inviter: str | None = None) -> bool:
        """Cancels an open invitation; with [inviter] only one that person made (somebody else's is "not there" to them)."""
        sql, args = "UPDATE invites SET state='revoked' WHERE id=? AND state='open'", [invite_id]
        if inviter is not None:
            sql, args = sql + " AND lower(inviter)=?", args + [normalize(inviter)]
        with self._lock:
            cur = self._db.execute(sql, args)
        return cur.rowcount == 1

    def revoke_all_from(self, inviter: str) -> int:
        """Cancels every open invitation a person made (when that person is removed from the server)."""
        with self._lock:
            cur = self._db.execute("UPDATE invites SET state='revoked' WHERE lower(inviter)=? AND state IN ('open','redeeming')",
                                   (normalize(inviter),))
        return cur.rowcount

    def list(self, *, inviter: str | None = None) -> list[Row]:
        now = self._clock()
        sql = "SELECT id, inviter, created_at, expires_at, state, redeemed_by, redeemed_at, role FROM invites"
        args: list[object] = []
        if inviter is not None:
            sql, args = sql + " WHERE lower(inviter)=?", [normalize(inviter)]
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY id DESC", args).fetchall()
        out = []
        for id_, who, created, expires, state, by, at, role in rows:
            if state == "redeeming":
                state = "open"
            if state == "open" and now > expires:
                state = "expired"
            out.append(Row(id_, who, created, expires, state, by, at, role))
        return out

    # ------------------------------------------------------------------ friend side
    def lookup(self, code: str) -> Info | None:
        """The invitation behind a code, or `None` for anything that is not a usable one."""
        if not isinstance(code, str) or not code or len(code) > _MAX_CODE_LEN:
            return None
        now = self._clock()
        with self._lock:
            row = self._db.execute(
                "SELECT id, inviter, expires_at, role FROM invites WHERE code_hash=? AND state='open' AND expires_at>=?",
                (_hash(code), now)).fetchone()
        return Info(id=row[0], inviter=row[1], expires_at=row[2], role=row[3]) if row else None

    def redeem(self, code: str, username: str, password: str) -> str:
        info = self.lookup(code)
        if info is None:
            raise InviteError(NOT_VALID)
        problem = check_username(username) or check_password(password)
        if problem:
            raise InviteError(problem)
        now = self._clock()
        with self._lock:  # the atomic claim: only one caller gets rowcount 1
            cur = self._db.execute(
                "UPDATE invites SET state='redeeming' WHERE id=? AND state='open' AND expires_at>=?", (info.id, now))
            if cur.rowcount != 1:
                raise InviteError(NOT_VALID)
        try:
            self._prov.add_person(username, password)
        except ProvisionError as error:
            self._give_back(info.id)
            raise InviteError(str(error)) from None
        except Exception:  # noqa: BLE001 - the server is in trouble; the person must not see why
            log.exception("creating the account for an invitation failed")
            self._give_back(info.id)
            raise InviteError("Something went wrong on the server. Try again in a minute.") from None
        with self._lock:
            self._db.execute("UPDATE invites SET state='used', redeemed_by=?, redeemed_at=? WHERE id=?",
                             (username, self._clock(), info.id))
        return username

    def _give_back(self, invite_id: int) -> None:
        with self._lock:
            self._db.execute("UPDATE invites SET state='open' WHERE id=? AND state='redeeming'", (invite_id,))
