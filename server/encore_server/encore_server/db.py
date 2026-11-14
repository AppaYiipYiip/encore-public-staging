"""SQLite (WAL) with numbered migrations (docs/18 section 1).

Migrations are SQL files run in order at start-up. Before the first pending one a copy of the database is taken
(`backups/encore-<version>-<time>.db`); a failed migration restores it and the server refuses to start with a plain message.
"""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from importlib import resources
from pathlib import Path

log = logging.getLogger("encore_server.db")

_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationFailed(RuntimeError):
    """A migration did not apply; the database was put back as it was."""


class Database:
    def __init__(self, path: Path | str, *, backups: Path | None = None) -> None:
        self.path = Path(path)
        self.backups = backups if backups is not None else self.path.parent / "backups"
        #: `journal_mode=WAL` is a property of the database file, not of a connection: set once, it holds for every later connection.
        self._wal_set = False
        #: One idle connection kept open while the server runs ([hold_open]); see there for why.
        self._held: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ connections

    def connect(self) -> sqlite3.Connection:
        """A new connection (cheap in SQLite): one per unit of work keeps threads apart."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        if not self._wal_set:
            conn.execute("PRAGMA journal_mode=WAL")
            self._wal_set = True
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def hold_open(self) -> None:
        """Keeps one idle connection open until [release]. In WAL mode SQLite checkpoints the journal and deletes its files whenever the LAST connection
        closes, and [tx] and [read] open and close one per call: with nothing else open, every write paid for that (measured in the server image,
        `evidence/scripts/audit_db_writes.py`: 144 writes a second; 2,796 with one idle connection kept open, no other change). The held connection runs
        no query. The server calls this when it starts, after the migrations: a migration that fails puts the backup back by deleting the journal files,
        and nothing may hold the database open while it does (P3-29 part 1b)."""
        if self._held is None:
            self._held = self.connect()

    def release(self) -> None:
        """Lets go of the connection [hold_open] kept (the server stopping). Harmless when none is held."""
        held, self._held = self._held, None
        if held is not None:
            with suppress(sqlite3.Error):
                held.close()

    @property
    def is_held_open(self) -> bool:
        return self._held is not None

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One transaction: everything inside happens or none of it does (a like and its change-log row are one write)."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ migrations

    @staticmethod
    def _migrations() -> list[tuple[int, str, str]]:
        found: list[tuple[int, str, str]] = []
        for entry in resources.files("encore_server").joinpath("migrations").iterdir():
            match = _NAME.match(entry.name)
            if match:
                found.append((int(match.group(1)), entry.name, entry.read_text(encoding="utf-8")))
        return sorted(found)

    def migrate(self, *, version: str = "dev", migrations: list[tuple[int, str, str]] | None = None) -> list[int]:
        """Applies what is pending; returns the versions applied. Raises [MigrationFailed] after restoring the backup."""
        pending_source = migrations if migrations is not None else self._migrations()
        conn = self.connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, at INTEGER NOT NULL)"
            )
            done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
        finally:
            conn.close()
        pending = [m for m in pending_source if m[0] not in done]
        if not pending:
            return []
        backup = self.backup(version) if self.path.exists() and self.path.stat().st_size > 0 and done else None
        applied: list[int] = []
        for number, name, sql in pending:
            conn = self.connect()
            try:
                conn.executescript("BEGIN;\n" + sql + "\n")
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, at) VALUES (?, ?, ?)", (number, name, int(time.time() * 1000))
                )
                conn.execute("COMMIT")
                applied.append(number)
            except Exception as error:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                conn.close()
                self._restore(backup)
                raise MigrationFailed(
                    f"The server's database could not be brought up to date (step {name}), so it was left as it was. {error}"
                ) from error
            finally:
                with suppress(sqlite3.Error):
                    conn.close()
        log.info("database migrated: %s", applied)
        return applied

    def backup(self, label: str) -> Path:
        """A whole copy of the database in the backups folder (`encore-<label>-<time>.db`), made with `VACUUM INTO` (a consistent copy taken under a read lock).
        Returns where it is. It is kept: nothing here deletes it. A migration takes one named after the version; the repair of merged refs takes
        its own, named for what it is about to do (`refmerge.py`)."""
        self.backups.mkdir(parents=True, exist_ok=True)
        stem = f"encore-{label}-{time.strftime('%Y%m%d-%H%M%S')}"
        target = self.backups / f"{stem}.db"
        for again in range(
            2, 100
        ):  # two copies in one second (a restart loop) never overwrite or refuse each other: VACUUM INTO will not write over a file
            if not target.exists():
                break
            target = self.backups / f"{stem}-{again}.db"
        source = self.connect()
        try:
            source.execute("VACUUM INTO ?", (str(target),))
        finally:
            source.close()
        return target

    def _restore(self, backup: Path | None) -> None:
        if backup is None:
            # A brand-new database: nothing to go back to, but nothing half-made either.
            for suffix in ("", "-wal", "-shm"):
                Path(str(self.path) + suffix).unlink(missing_ok=True)
            return
        for suffix in ("-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        shutil.copyfile(backup, self.path)
