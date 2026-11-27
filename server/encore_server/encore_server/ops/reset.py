"""Getting back in (docs/36 section 6, P3-16): a new password for a person, made at the server's own computer, and the owner's recovery key.

The proof of ownership is **being at the computer**: these functions run only from `encore reset-password` and `encore recovery-key`, which need root there, and no route calls them (a
button inside pages cannot help a person who cannot sign in). Each is one operation on the database and the music server, and each leaves an audit line.

* [reset_password]: a new password for anybody. The music server's password is changed first, so a failure there changes nothing here (a failure of this server's own part, a database that does not answer, is said in a sentence that tells the person to run it again: safe); then, in one transaction, every device of the person is
  signed out (a live connection notices within 25 seconds and closes), a lock and the count of wrong tries are cleared, and the audit line is written. For an owner with a recovery key the
  key is asked: a wrong one is refused, a right one is recorded ("with the recovery key"), none is allowed for root at the computer and recorded too ("without"). **An owner's key is
  replaced by every reset**, and the new one is returned once: the old one has been typed on a terminal and is spent.
* [new_recovery_key]: a key for an owner who has none (an owner made before this existed, or one who lost it), without touching the password.

The one thing this does not do: a music-server login with the OLD password that was accepted in the last ten minutes may still be remembered by the running server for up to ten minutes
(`auth.py`, a Subsonic app that signs every request); the phones' own device tokens end at once.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .. import audit, recovery
from ..accounts import clean_password
from ..db import Database
from ..errors import ApiError
from ..ids import now_ms
from ..navidrome_admin import NavidromeAdmin


def _find(conn: sqlite3.Connection, name: object) -> sqlite3.Row:
    """The person with this username (exactly, else without regard to case when only one matches), or a sentence."""
    text = name.strip() if isinstance(name, str) else ""
    if not text:
        raise ApiError("validation", "Say whose password: the person's username.")
    row = conn.execute("SELECT * FROM person WHERE navidrome_user = ?", (text,)).fetchone()
    if row is None:
        found = conn.execute("SELECT * FROM person WHERE lower(navidrome_user) = lower(?)", (text,)).fetchall()
        row = found[0] if len(found) == 1 else None
    if row is None:
        raise ApiError(
            "not_found", f'There is nobody called "{text[:64]}" on this server. Their username is what they sign in with.'
        )
    return row  # type: ignore[no-any-return]


def person_state(db: Database, name: object) -> str:
    """What the command needs to know before it asks anything: `owner-with-key` (the key is asked), `owner` (no key was ever made) or `member`."""
    with db.read() as conn:
        person = _find(conn, name)
        if person["role"] != "owner":
            return "member"
        return "owner-with-key" if recovery.has_key(conn, person["id"]) else "owner"


def reset_password(
    db: Database, admin: NavidromeAdmin, name: object, new_password: object, recovery_key: object = None
) -> dict[str, Any]:
    """Sets a new password for [name]; see the module's text. [ApiError] says what is wrong, in words for the person at the terminal."""
    with db.read() as conn:
        person = _find(conn, name)
        username = person["navidrome_user"]
        is_owner = person["role"] == "owner"
        keyed = is_owner and recovery.has_key(conn, person["id"])
        given = isinstance(recovery_key, str) and recovery_key.strip() != ""
        if keyed and given and not recovery.verify(conn, person["id"], recovery_key):
            raise ApiError(
                "forbidden",
                "That recovery key is not right. Check it, or leave it empty to go on without it (the line in the audit log says so).",
            )
        if given and not keyed:
            raise ApiError("validation", "There is no recovery key for this account: leave it empty.")
    secret = clean_password(new_password, username)
    if not admin.configured:
        raise ApiError("server_busy", "This server has no account for the music server, so it cannot change a password.")
    admin.set_password(username, secret)  # first: if the music server refuses, nothing else changed
    used_key = keyed and given
    try:
        with db.tx() as conn:
            ended = conn.execute(
                "UPDATE device SET revoked_at = ? WHERE person = ? AND revoked_at IS NULL", (now_ms(), person["id"])
            ).rowcount
            conn.execute("UPDATE person SET failed_logins = 0, locked = 0 WHERE id = ?", (person["id"],))
            new_key = recovery.store(conn, person["id"]) if is_owner else None
            how = "with the recovery key" if used_key else ("without the recovery key" if keyed else "from the server computer")
            audit.record(
                conn,
                "reset_password",
                username,
                f"The password of {username} was reset at the server computer ({how}); {ended} signed-in device{'s' if ended != 1 else ''} signed out.",
            )
    except sqlite3.Error as error:
        # The music server has the new password already; only this server's own part did not happen. Doing the same again is safe (the same password, the same steps).
        raise ApiError(
            "server_busy",
            f"The password of {username} was changed at the music server, but this server could not sign the devices out (its database did not answer). Run the same command again: that is safe.",
        ) from error
    return {"name": username, "role": person["role"], "usedKey": used_key, "devicesEnded": ended, "recoveryKey": new_key}


def owners_without_key(db: Database) -> list[str]:
    """The usernames of the owners who have no recovery key (an owner made before keys existed, or by the headless door): what `encore status` tells the Host about."""
    with db.read() as conn:
        rows = conn.execute(
            "SELECT p.navidrome_user AS name FROM person p WHERE p.role = 'owner' AND NOT EXISTS (SELECT 1 FROM recovery_key k WHERE k.person = p.id) ORDER BY p.created_at"
        ).fetchall()
    return [row["name"] for row in rows]


def new_recovery_key(db: Database, name: object = None) -> dict[str, Any]:
    """A new key for an owner, replacing any old one; the password is not touched. Without a name: the one owner, or a sentence when there are several."""
    with db.tx() as conn:
        if name is None or (isinstance(name, str) and not name.strip()):
            owners = conn.execute("SELECT * FROM person WHERE role = 'owner' ORDER BY created_at").fetchall()
            if not owners:
                raise ApiError(
                    "not_found", "This server has no owner yet: make the account first (the setup link, sudo encore status)."
                )
            if len(owners) > 1:
                names = ", ".join(row["navidrome_user"] for row in owners)
                raise ApiError(
                    "validation", f"There is more than one owner ({names}): say whose key, as in  encore recovery-key NAME"
                )
            person = owners[0]
        else:
            person = _find(conn, name)
        if person["role"] != "owner":
            raise ApiError("validation", "Only an owner has a recovery key.")
        key = recovery.store(conn, person["id"])
        audit.record(
            conn,
            "recovery_key",
            person["navidrome_user"],
            f"A new recovery key was made for {person['navidrome_user']} at the server computer; the old one no longer works.",
        )
    return {"name": person["navidrome_user"], "recoveryKey": key}
