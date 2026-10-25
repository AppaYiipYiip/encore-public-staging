"""People (docs/21, docs/tasks P3-01): invitations, joining, the owner's list of people, password resets, and the limits that keep a stranger
from guessing a password.

Passwords live in the music server only; this module hands one over when an account is made or changed and keeps nothing of it. Codes
(an invitation, a reset) are shown once and kept as a hash. Everything a person *has* (likes, playlists, history) belongs to the `person`
row and is deleted with it.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from .auth import issue_device
from .db import Database
from .errors import ApiError
from .ids import is_id, new_id, now_ms
from .navidrome_admin import NameTaken, NavidromeAdmin
from .notifications import Notifications

log = logging.getLogger("encore_server.accounts")

INVITE_TTL_S = 7 * 24 * 3600
RESET_TTL_S = 3600
#: Wrong passwords for one account before it is locked until the owner unlocks it (docs/21 section 4).
LOCK_AFTER_FAILURES = 20

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no 0/O, 1/I/L: a code is read out and typed
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,30}[a-z0-9]$")
_RESERVED = frozenset(
    {"admin", "administrator", "root", "encore", "encore-admin", "navidrome", "system", "owner", "guest", "everyone"}
)

INVALID_CODE = "That invitation is not valid any more. Ask for a new one."


def new_code() -> str:
    """Twelve characters in three groups, like `K7M2-QX9P-4RTV`."""
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def hash_code(code: str) -> str:
    """The code as it is stored: typed in any case, with or without dashes and spaces, it is the same code."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", code).upper()
    return hashlib.sha256(cleaned.encode()).hexdigest()


def clean_username(value: object) -> str:
    name = value.strip().lower() if isinstance(value, str) else ""
    if not _USERNAME.match(name):
        raise ApiError(
            "validation",
            "A name is 3 to 32 letters, digits, dots, dashes or underscores, starting and ending with a letter or digit.",
        )
    if name in _RESERVED:
        raise ApiError("conflict", "That name is not available. Choose another.")
    return name


def clean_password(value: object, username: str = "") -> str:
    if not isinstance(value, str) or not 8 <= len(value) <= 128:
        raise ApiError("validation", "A password is 8 to 128 characters.")
    if value.lower() == username.lower():
        raise ApiError("validation", "The password cannot be the same as the name.")
    return value


class Limiter:
    """A sliding window per key, in memory: [allow] says how many milliseconds to wait, or `None` when the request may go on.

    A restart forgets it, which is fine for what it is for (five wrong passwords a minute); the lock after twenty is in the database."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float) -> int | None:
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= window_s:
                hits.popleft()
            if len(hits) >= limit:
                return int((hits[0] + window_s - now) * 1000) + 1
            hits.append(now)
            if len(self._hits) > 5000:  # a flood of different keys must not grow this for ever
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] >= window_s]:
                    del self._hits[stale]
        return None

    def refuse(self, key: str, limit: int, window_s: float) -> None:
        wait = self.allow(key, limit, window_s)
        if wait is not None:
            raise ApiError("rate_limited", "Too many tries. Wait a moment and try again.", retry_after_ms=wait)


class Accounts:
    def __init__(
        self,
        db: Database,
        admin: NavidromeAdmin | None,
        *,
        clock: Callable[[], float] = time.time,
        notifications: Notifications | None = None,
        server_name: str = "this server",
    ) -> None:
        self._db = db
        self._admin = admin
        self._clock = clock
        self._notifications = notifications
        self._server_name = server_name

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _need_admin(self) -> NavidromeAdmin:
        if self._admin is None or not self._admin.configured:
            raise ApiError("server_busy", "This server is not set up to add or change people yet.")
        return self._admin

    # ------------------------------------------------------------------ invitations

    def create_invite(self, owner: str, *, role: object = "member", note: object = None) -> dict[str, Any]:
        """A one-person invitation, valid for seven days. The code is in the answer once and nowhere else."""
        role_name = role if role in ("member", "owner") else "member"
        text = " ".join(note.split())[:80] if isinstance(note, str) and note.strip() else None
        code = new_code()
        now = self._now_ms()
        invite_id = new_id("iv")
        with self._db.tx() as conn:
            conn.execute(
                "INSERT INTO invite (id, code_hash, role, created_by, note, created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                (invite_id, hash_code(code), role_name, owner, text, now, now + INVITE_TTL_S * 1000),
            )
        return {
            "id": invite_id,
            "code": code,
            "role": role_name,
            "note": text,
            "createdAt": now,
            "expiresAt": now + INVITE_TTL_S * 1000,
        }

    def list_invites(self) -> list[dict[str, Any]]:
        now = self._now_ms()
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT i.*, p.display_name AS used_name FROM invite i LEFT JOIN person p ON p.id = i.used_by ORDER BY i.created_at DESC LIMIT 100"
            ).fetchall()
        return [
            {
                "id": r["id"],
                "role": r["role"],
                "note": r["note"],
                "createdAt": r["created_at"],
                "expiresAt": r["expires_at"],
                "state": "revoked"
                if r["revoked_at"]
                else "used"
                if r["used_at"]
                else "expired"
                if r["expires_at"] <= now
                else "open",
                "usedBy": r["used_name"],
                "usedAt": r["used_at"],
            }
            for r in rows
        ]

    def revoke_invite(self, invite_id: str) -> bool:
        with self._db.tx() as conn:
            return bool(
                conn.execute(
                    "UPDATE invite SET revoked_at = ? WHERE id = ? AND used_at IS NULL AND revoked_at IS NULL",
                    (self._now_ms(), invite_id),
                ).rowcount
            )

    def _open_invite(self, conn: sqlite3.Connection, code: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM invite WHERE code_hash = ?", (hash_code(code),)).fetchone()
        if row is None or row["used_at"] or row["revoked_at"] or row["expires_at"] <= self._now_ms():
            raise ApiError("not_found", INVALID_CODE)
        return row  # type: ignore[no-any-return]

    def check_invite(self, code: str) -> dict[str, Any]:
        """What the join screen shows before the person chooses a name: who invited them."""
        with self._db.read() as conn:
            row = self._open_invite(conn, code)
            inviter = conn.execute("SELECT display_name FROM person WHERE id = ?", (row["created_by"],)).fetchone()
        return {"invitedBy": inviter["display_name"] if inviter else None, "expiresAt": row["expires_at"]}

    def join(
        self, code: str, username: object, password: object, display_name: object, device_name: str, app_version: str | None
    ) -> dict[str, Any]:
        """The invited person chooses a name and a password: the music server makes the account, this server makes the person, the invitation
        is used up. Returns what a sign-in returns."""
        admin = self._need_admin()
        name = clean_username(username)
        secret = clean_password(password, name)
        shown = " ".join(display_name.split())[:60] if isinstance(display_name, str) and display_name.strip() else name
        with self._db.read() as conn:
            self._open_invite(conn, code)  # refuse a bad code before touching the music server
        try:
            admin.create_user(name, shown, secret)
        except NameTaken:
            raise ApiError("conflict", "That name is already taken. Choose another.") from None
        try:
            with self._db.tx() as conn:
                invite = self._open_invite(conn, code)  # another request may have used it meanwhile
                person_id = new_id("pn")
                conn.execute(
                    "INSERT INTO person (id, navidrome_user, display_name, role, invited_by, created_at) VALUES (?,?,?,?,?,?)",
                    (person_id, name, shown, invite["role"], invite["created_by"], now_ms()),
                )
                conn.execute("UPDATE invite SET used_by = ?, used_at = ? WHERE id = ?", (person_id, self._now_ms(), invite["id"]))
                device_id, token = issue_device(conn, person_id, device_name, "phone", app_version)
        except Exception:
            admin.delete_user(name)  # nobody is left half-made
            raise
        log.info("%s joined", name)
        if self._notifications is not None and invite["created_by"]:
            # The owner who made the invitation hears of it in the bell, once, however often this is retried.
            self._notifications.tell(
                invite["created_by"],
                "invite_used",
                f"{shown} joined {self._server_name}",
                body="With the invitation you made.",
                dedupe=f"invite:{invite['id']}",
            )
        return {
            "deviceToken": token,
            "device": {"id": device_id, "name": device_name},
            "person": {"id": person_id, "name": shown, "role": invite["role"]},
        }

    def heal_libraries(self) -> int:
        """A person whose music-server account has no library sees no songs and cannot stream; gives them the library. Returns how many."""
        admin = self._admin
        if admin is None or not admin.configured:
            return 0
        with self._db.read() as conn:
            names = [r["navidrome_user"] for r in conn.execute("SELECT navidrome_user FROM person")]
        return admin.give_libraries(names)

    # ------------------------------------------------------------------ the owner's list of people

    def people(self) -> list[dict[str, Any]]:
        """Who is on this server: names, roles, when last seen and how many devices. Counts only: an owner never sees what anybody listens to."""
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT p.*, (SELECT COUNT(*) FROM device d WHERE d.person = p.id AND d.revoked_at IS NULL) AS devices,"
                " (SELECT MAX(d.last_seen) FROM device d WHERE d.person = p.id) AS last_seen,"
                " (SELECT display_name FROM person i WHERE i.id = p.invited_by) AS invited_by_name"
                " FROM person p ORDER BY p.created_at"
            ).fetchall()
        return [
            {
                "id": r["id"],
                "username": r["navidrome_user"],
                "name": r["display_name"],
                "role": r["role"],
                "locked": bool(r["locked"]),
                "explicitOk": bool(r["explicit_ok"]),
                "devices": r["devices"],
                "lastSeen": r["last_seen"],
                "invitedBy": r["invited_by_name"],
                "createdAt": r["created_at"],
            }
            for r in rows
        ]

    def _person(self, conn: sqlite3.Connection, person_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,)).fetchone() if is_id(person_id, "pn") else None
        if row is None:
            raise ApiError("not_found", "There is nobody with that id.")
        return row  # type: ignore[no-any-return]

    def _only_owner(self, conn: sqlite3.Connection, person_id: str) -> bool:
        """Is this the one owner who can still sign in (so removing or demoting them would leave the server with nobody in charge)?"""
        others = conn.execute(
            "SELECT COUNT(*) FROM person WHERE role = 'owner' AND id != ? AND locked = 0", (person_id,)
        ).fetchone()[0]
        return bool(others == 0)

    def update_person(self, by: str, person_id: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._db.tx() as conn:
            row = self._person(conn, person_id)
            role = body.get("role", row["role"])
            if role not in ("owner", "member"):
                raise ApiError("validation", "A role is owner or member.")
            locked = body.get("locked", bool(row["locked"]))
            explicit = body.get("explicitOk", bool(row["explicit_ok"]))
            if not isinstance(locked, bool) or not isinstance(explicit, bool):
                raise ApiError("validation", "locked and explicitOk are true or false.")
            if (role != "owner" or locked) and row["role"] == "owner" and self._only_owner(conn, person_id):
                raise ApiError("conflict", "A server needs at least one owner who is not locked out.")
            if locked and person_id == by:
                raise ApiError("conflict", "You cannot lock yourself out.")
            conn.execute(
                "UPDATE person SET role = ?, locked = ?, explicit_ok = ?, failed_logins = CASE WHEN ? = 0 THEN 0 ELSE failed_logins END WHERE id = ?",
                (role, 1 if locked else 0, 1 if explicit else 0, 1 if locked else 0, person_id),
            )
            if locked:
                conn.execute("UPDATE device SET revoked_at = ? WHERE person = ? AND revoked_at IS NULL", (now_ms(), person_id))
        return next(p for p in self.people() if p["id"] == person_id)

    def remove_person(self, by: str, person_id: str) -> None:
        """Deletes the person: their account in the music server, their library, history and devices. The music files stay (docs/21 section 6)."""
        admin = self._need_admin()
        with self._db.read() as conn:
            row = self._person(conn, person_id)
            if person_id == by:
                raise ApiError("conflict", "You cannot remove yourself here.")
            if row["role"] == "owner" and self._only_owner(conn, person_id):
                raise ApiError("conflict", "A server needs at least one owner.")
        admin.delete_user(row["navidrome_user"])
        with self._db.tx() as conn:
            conn.execute("DELETE FROM playlist_entry WHERE added_by = ?", (person_id,))
            conn.execute("DELETE FROM person WHERE id = ?", (person_id,))

    # ------------------------------------------------------------------ passwords

    def create_reset(self, person_id: str) -> dict[str, Any]:
        """A one-hour link for somebody who forgot their password (the owner sends it; the owner never learns the new password)."""
        code = new_code()
        now = self._now_ms()
        with self._db.tx() as conn:
            self._person(conn, person_id)
            conn.execute("UPDATE reset_code SET used_at = ? WHERE person = ? AND used_at IS NULL", (now, person_id))
            conn.execute(
                "INSERT INTO reset_code (id, person, code_hash, created_at, expires_at) VALUES (?,?,?,?,?)",
                (new_id("rc"), person_id, hash_code(code), now, now + RESET_TTL_S * 1000),
            )
        return {"code": code, "expiresAt": now + RESET_TTL_S * 1000}

    def reset_password(self, code: str, password: object, device_name: str, app_version: str | None) -> dict[str, Any]:
        admin = self._need_admin()
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT r.id AS rid, p.* FROM reset_code r JOIN person p ON p.id = r.person WHERE r.code_hash = ? AND r.used_at IS NULL AND r.expires_at > ?",
                (hash_code(code), self._now_ms()),
            ).fetchone()
        if row is None:
            raise ApiError("not_found", "That link is not valid any more. Ask for a new one.")
        secret = clean_password(password, row["navidrome_user"])
        admin.set_password(row["navidrome_user"], secret)
        with self._db.tx() as conn:
            conn.execute("UPDATE reset_code SET used_at = ? WHERE id = ?", (self._now_ms(), row["rid"]))
            conn.execute("UPDATE person SET failed_logins = 0, locked = 0 WHERE id = ?", (row["id"],))
            conn.execute("UPDATE device SET revoked_at = ? WHERE person = ? AND revoked_at IS NULL", (now_ms(), row["id"]))
            device_id, token = issue_device(conn, row["id"], device_name, "phone", app_version)
        return {
            "deviceToken": token,
            "device": {"id": device_id, "name": device_name},
            "person": {"id": row["id"], "name": row["display_name"], "role": row["role"]},
        }

    def change_password(self, navidrome_user: str, password: object) -> None:
        self._need_admin().set_password(navidrome_user, clean_password(password, navidrome_user))

    # ------------------------------------------------------------------ wrong passwords

    def failed_login(self, username: str) -> None:
        """A wrong password for a person who exists: counted; at [LOCK_AFTER_FAILURES] the account is locked until the owner unlocks it."""
        with self._db.tx() as conn:
            row = conn.execute("SELECT id, failed_logins, locked FROM person WHERE navidrome_user = ?", (username,)).fetchone()
            if row is None or row["locked"]:
                return
            count = row["failed_logins"] + 1
            conn.execute(
                "UPDATE person SET failed_logins = ?, locked = ? WHERE id = ?",
                (count, 1 if count >= LOCK_AFTER_FAILURES else 0, row["id"]),
            )
            if count >= LOCK_AFTER_FAILURES:
                conn.execute("UPDATE device SET revoked_at = ? WHERE person = ? AND revoked_at IS NULL", (now_ms(), row["id"]))
                log.warning("%s was locked after %d wrong passwords", username, count)

    def good_login(self, person_id: str) -> None:
        with self._db.tx() as conn:
            conn.execute("UPDATE person SET failed_logins = 0 WHERE id = ? AND failed_logins != 0", (person_id,))
