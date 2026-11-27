"""The owner's recovery key (docs/36 section 6, P3-16): five groups of four letters and digits, shown once, kept only as a hash.

What it is for: the proof of ownership of a server is **being at the computer**. A Host who forgot the only owner's password runs `sudo encore reset-password NAME` there. If the owner has a
recovery key, the command asks for it: a right key is what the audit line records ("with the recovery key"), a wrong one is refused (a mistyped key is told, not ignored), and the
person at the computer who has lost it may go on without one, which the line records too ("without the recovery key"). The key gives no other power and works nowhere but at the computer;
it is a second proof and a record, not a back door: root on the computer could always have reset the password.

It is made when the owner is made (the first-run page shows it once), or later by `encore recovery-key`, and **replaced every time it is used**: a key that has been typed on a terminal is
spent. Ninety-nine random bits, so a plain SHA-256 of the key is all that is kept: there is nothing to guess and nothing to stretch.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3

from .ids import now_ms
from .setup_code import ALPHABET, normalize

GROUPS = 5
GROUP_LEN = 4
LENGTH = GROUPS * GROUP_LEN


def new_key() -> str:
    """A fresh key as it is shown: `ABCD-EFGH-JKMN-PQRS-TUVW` (the alphabet of the setup code: no 0 O 1 I L)."""
    raw = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    return "-".join(raw[i : i + GROUP_LEN] for i in range(0, LENGTH, GROUP_LEN))


def well_formed(text: object) -> bool:
    bare = normalize(text)
    return len(bare) == LENGTH and all(ch in ALPHABET for ch in bare)


def hash_key(key: str) -> str:
    return hashlib.sha256(normalize(key).encode()).hexdigest()


def matches(stored_hash: str, given: object) -> bool:
    """Constant time; false for anything that is not a well formed key (an empty or a short string never matches)."""
    if not well_formed(given):
        return False
    return hmac.compare_digest(stored_hash.encode(), hash_key(str(given)).encode())


def store(conn: sqlite3.Connection, person_id: str) -> str:
    """Makes a new key for [person_id], replacing any earlier one, inside the caller's transaction. Returns the key: the one and only time it exists in clear."""
    key = new_key()
    conn.execute(
        "INSERT INTO recovery_key (person, key_hash, made_at) VALUES (?,?,?) ON CONFLICT(person) DO UPDATE SET key_hash = excluded.key_hash, made_at = excluded.made_at",
        (person_id, hash_key(key), now_ms()),
    )
    return key


def has_key(conn: sqlite3.Connection, person_id: str) -> bool:
    return conn.execute("SELECT 1 FROM recovery_key WHERE person = ?", (person_id,)).fetchone() is not None


def verify(conn: sqlite3.Connection, person_id: str, given: object) -> bool:
    row = conn.execute("SELECT key_hash FROM recovery_key WHERE person = ?", (person_id,)).fetchone()
    return row is not None and matches(row["key_hash"], given)
