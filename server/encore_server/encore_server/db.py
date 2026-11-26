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
from collections.abc import Iterable, Iterator
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
        numbers = [m[0] for m in pending_source]
        shared = sorted({n for n in numbers if numbers.count(n) > 1})
        if shared:
            # Two branches that start from one main both take the next free number. On a database that ran the first, the second would count as applied and
            # its tables would be missing at run time with no error at all: refuse to start, and say which number.
            raise MigrationFailed(
                f"Two of the server's database steps have the same number ({', '.join(f'{n:04d}' for n in shared)}). This is a mistake in this version of the "
                "server, not in your data: nothing was changed."
            )
        conn = self.connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, at INTEGER NOT NULL)"
            )
            done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
        finally:
            conn.close()
        # A database that has run steps this version does not know was made by a NEWER version (a rollback to an older image, or an old backup of the program on new
        # data). Starting on it would read tables and columns the old code does not understand and could write over what the newer version meant: refuse, in words, before
        # anything is read or changed (P3-29 part 2). There is no setting that turns this off: the way back is a backup made by this version.
        known = {m[0] for m in pending_source}
        unknown = sorted(done - known)
        if unknown and known:
            raise MigrationFailed(
                f"The data of this server was made by a newer version of Encore (it has database step {unknown[-1]:04d}; this version knows only up to {max(known):04d}). "
                "Starting this older version on it could damage the data, so it did not start and nothing was changed. "
                "Start the newer version again (encore update), or go back by restoring a backup made by this version (encore restore FILE)."
            )
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
        Returns where it is. It is kept: `backup` itself never deletes anything (a repair that takes copies at every start prunes its own label with
        [prune_backups]). A migration takes one named after the version; the repair of merged refs takes its own, named for what it is about to do
        (`refmerge.py`), and so does the repair of stored keys (`keyrepair.py`)."""
        self.backups.mkdir(parents=True, exist_ok=True)
        stem = f"encore-{label}-{time.strftime('%Y%m%d-%H%M%S')}"
        # Two copies in one second (a restart loop) never overwrite or refuse each other (VACUUM INTO will not write over a file), and the suffix always goes ABOVE the
        # ones that exist, never into a gap a pruned copy left: [copies] orders by (time, suffix), so a new copy must sort after every copy of its second.
        same_second = [
            int(match.group(1) or 1)
            for path in self.backups.glob(f"{stem}*.db")
            if (match := re.fullmatch(rf"{re.escape(stem)}(?:-(\d+))?\.db", path.name))
        ]
        again = max(same_second, default=0) + 1
        if again >= 1000:
            raise OSError(f"{again - 1} copies of the database were made in one second: something is looping")
        target = self.backups / (f"{stem}.db" if again == 1 else f"{stem}-{again}.db")
        source = self.connect()
        try:
            source.execute("VACUUM INTO ?", (str(target),))
        finally:
            source.close()
        return target

    def copies(self, label: str) -> list[Path]:
        """The copies [backup] made under exactly this label, OLDEST FIRST by their names (a folder that does not exist has none): the time in the name, then the
        `-2`, `-3`... of copies made in one second (as text `x-2.db` sorts before `x.db`, and `x-10.db` before `x-2.db`).

        **This order is a hint and nothing that must hold may depend on it.** The time in a name is the LOCAL time of the clock that made the copy, and a clock goes
        back: the end of daylight saving time repeats an hour, a time sync steps it, somebody sets it. A file's modification time is no better (the operating system stamps
        it from the same clock), and there is no sequence number in a name (names are the format docs/15 and docs/18 describe, shared with the migration and merge copies).
        So the only ordering use is [prune_backups]'s choice of WHICH surplus copy goes first, and a wrong choice there costs a spare copy, never the one a caller
        relies on: the caller names that one, and it is not a candidate."""
        pattern = re.compile(rf"^encore-{re.escape(label)}-(\d{{8}}-\d{{6}})(?:-(\d+))?\.db$")
        found: list[tuple[str, int, Path]] = []
        if self.backups.is_dir():
            for path in self.backups.iterdir():
                match = pattern.match(path.name)
                if match and path.is_file():
                    found.append((match.group(1), int(match.group(2) or 1), path))
        return [path for _stamp, _again, path in sorted(found)]

    def prune_backups(self, label: str, keep: int, *, protect: Iterable[Path | str]) -> list[Path]:
        """Removes copies of this label (and of no other label: a migration's copy and the merge's are never touched) until at most `keep` are left; returns the ones it
        removed. For a repair that takes a copy at every start it finds something to do: the cap that keeps a restart loop from filling the disk.

        **`protect` is required: the copies that must stay, whatever their names say** (the copy the caller has just taken and is about to rely on, and the one its last
        committed repair used). A protected copy is never a candidate and counts inside `keep`; more protected copies than `keep` are all kept. The rest go OLDEST FIRST
        by [copies]'s order, which a clock that went back can get wrong: then a spare copy goes before another, and nothing else. (This used to take only `keep`, ordered
        by the names alone: with three copies named in the future the copy taken just now was the OLDEST of four, was removed, and the repair that had taken it went on
        with a path that did not exist.) A protected copy that is not there is not an error here: whether the caller can rely on it is the caller's check."""
        if keep < 1:
            raise ValueError("keep at least one copy: the copy a repair just took is the one it needs")
        names = {Path(item).name for item in protect}
        if not names:
            raise ValueError(
                "name the copy that must stay: a prune that is not told which copy the caller relies on is the prune that removed it"
            )
        present = self.copies(label)
        spared = [path for path in present if path.name in names]
        candidates = [path for path in present if path.name not in names]
        room = max(keep - len(spared), 0)
        removed = candidates[: len(candidates) - room] if len(candidates) > room else []
        for path in removed:
            path.unlink(missing_ok=True)
        return removed

    def _restore(self, backup: Path | None) -> None:
        if backup is None:
            # A brand-new database: nothing to go back to, but nothing half-made either.
            for suffix in ("", "-wal", "-shm"):
                Path(str(self.path) + suffix).unlink(missing_ok=True)
            return
        for suffix in ("-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        shutil.copyfile(backup, self.path)
