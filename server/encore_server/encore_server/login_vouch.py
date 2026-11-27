"""The database half of the server's memory of a device it already knows (P3-34 slice 2a; `auth.NavidromeVerifier.vouched`, docs/21).

The memory is in the verifier's process for the per-request check; this keeps it across a restart. Everything here is a BEST EFFORT: a write that cannot be made (the database is busy, the
disk is full) is logged and dropped and never refuses, delays or fails the request that was being signed in; a read that cannot be made leaves the verifier with an empty memory and a key
of its own for this process, which is how it was before the memory was kept at all.
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
from typing import Protocol

from .db import Database

log = logging.getLogger("encore_server.login_vouch")

#: How long a write waits for the database's write lock before it gives up: a vouch must never hold a request up.
BUSY_MS = 250


class VouchStore(Protocol):
    def key(self) -> bytes: ...

    def load(self, oldest_ms: int) -> list[tuple[bytes, str, int]]: ...

    def put(self, digest: bytes, name: str, at_ms: int) -> None: ...

    def drop(self, digest: bytes) -> None: ...

    def drop_name(self, name: str) -> None: ...


class SqliteVouchStore:
    """`login_vouch` (migration 0025) and the key of the digests in `setting` (`login_vouch_key`)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def key(self) -> bytes:
        """The key the digests are made with: made once and kept with the server's other internal secrets, so a digest made before a restart is the digest made after it."""
        with self._db.tx() as conn:
            row = conn.execute("SELECT value FROM setting WHERE key = 'login_vouch_key'").fetchone()
            if row is None:
                conn.execute(
                    "INSERT OR IGNORE INTO setting (key, value) VALUES ('login_vouch_key', ?)", (secrets.token_bytes(32).hex(),)
                )
                row = conn.execute("SELECT value FROM setting WHERE key = 'login_vouch_key'").fetchone()
            return bytes.fromhex(str(row["value"]))

    def load(self, oldest_ms: int) -> list[tuple[bytes, str, int]]:
        """What is still good: the rows used since [oldest_ms]. The older ones are deleted on the way (a table that only grew would be a leak of every credential ever accepted)."""
        with self._db.tx() as conn:
            conn.execute("DELETE FROM login_vouch WHERE at < ?", (oldest_ms,))
            return [
                (bytes(r["digest"]), str(r["name"]), int(r["at"]))
                for r in conn.execute("SELECT digest, name, at FROM login_vouch")
            ]

    def _best_effort(self, sql: str, args: tuple[object, ...]) -> None:
        try:
            conn = self._db.connect()
            try:
                conn.execute(f"PRAGMA busy_timeout={BUSY_MS}")
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(sql, args)
                conn.execute("COMMIT")
            finally:
                conn.close()
        except sqlite3.Error as error:
            log.debug("a remembered login could not be written (%s): it stays in memory only", type(error).__name__)

    def put(self, digest: bytes, name: str, at_ms: int) -> None:
        self._best_effort(
            "INSERT INTO login_vouch (digest, name, at) VALUES (?, ?, ?) ON CONFLICT(digest) DO UPDATE SET at = excluded.at",
            (digest, name, at_ms),
        )

    def drop(self, digest: bytes) -> None:
        self._best_effort("DELETE FROM login_vouch WHERE digest = ?", (digest,))

    def drop_name(self, name: str) -> None:
        self._best_effort("DELETE FROM login_vouch WHERE name = ?", (name,))
