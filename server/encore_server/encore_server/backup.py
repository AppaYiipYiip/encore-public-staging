"""`python -m encore_server backup`: whole copies of an install's databases, taken while the servers keep running (docs/tasks P3-12).

SQLite's online backup copies a database page by page under a read lock and restarts if a write lands in the middle, so the copy is a
state the database really was in, never half of one. The `encore backup` command runs this in a throwaway container (the Encore server's
data and the music server's data are two folders) and packs the result with the install's settings file; `encore restore` checks the
copies again with `--verify` before it puts them in place.

    python -m encore_server backup --encore-db /data/encore.db --navidrome-db /nd/navidrome.db --out /out
    python -m encore_server backup --verify /somewhere

Nothing here prints a row of data: only file names, sizes and the word that the copy is whole.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import TextIO

#: The names the databases have inside a backup, whatever they are called where they came from.
ENCORE_DB = "encore.db"
MUSIC_SERVER_DB = "navidrome.db"


class BackupError(Exception):
    """A copy that cannot be made or is not whole. The message is a sentence for the person running `encore backup`."""


def verify_database(path: Path) -> None:
    """Raises [BackupError] unless [path] is an SQLite database that passes SQLite's own integrity check."""
    if not path.is_file():
        raise BackupError(f"{path.name} is missing.")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15)
        try:
            answer = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        finally:
            conn.close()
    except sqlite3.DatabaseError as error:
        raise BackupError(f"{path.name} is not a readable database ({type(error).__name__}).") from error
    if answer != ["ok"]:
        raise BackupError(f"{path.name} did not pass the integrity check.")


def copy_database(source: Path, target: Path) -> int:
    """Copies [source] into a new file [target] with SQLite's online backup, checks the copy and returns its size in bytes."""
    if not source.is_file():
        raise BackupError(f"{source.name} was not found where the server keeps it.")
    if target.exists():
        raise BackupError(f"{target.name} already exists in the backup folder.")
    try:
        origin = sqlite3.connect(source, timeout=30)
        try:
            copy = sqlite3.connect(target)
            try:
                origin.backup(copy)
            finally:
                copy.close()
        finally:
            origin.close()
    except sqlite3.Error as error:
        target.unlink(missing_ok=True)
        raise BackupError(f"{source.name} could not be copied ({type(error).__name__}).") from error
    try:
        verify_database(target)
    except BackupError:
        target.unlink(missing_ok=True)
        raise
    return target.stat().st_size


def command(argv: list[str] | None = None, *, out: TextIO | None = None, err: TextIO | None = None) -> int:
    """Entry point of `python -m encore_server backup`. Returns the exit status; a sentence goes to standard error on failure."""
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="encore_server backup", add_help=False)
    parser.add_argument("--encore-db", type=Path)
    parser.add_argument("--navidrome-db", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verify", type=Path)
    try:
        args = parser.parse_args(argv if argv is not None else sys.argv[2:])
    except SystemExit:
        print("backup: use --encore-db FILE [--navidrome-db FILE] --out DIR, or --verify DIR", file=err)
        return 2
    try:
        if args.verify is not None:
            found = [name for name in (ENCORE_DB, MUSIC_SERVER_DB) if (args.verify / name).exists()]
            if ENCORE_DB not in found:
                raise BackupError(f"There is no {ENCORE_DB} in this backup.")
            for name in found:
                verify_database(args.verify / name)
                print(f"{name} whole", file=out)
            return 0
        if args.encore_db is None or args.out is None:
            raise BackupError("Say where the Encore database is and where the copies go (--encore-db, --out).")
        args.out.mkdir(parents=True, exist_ok=True)
        copied = [(ENCORE_DB, copy_database(args.encore_db, args.out / ENCORE_DB))]
        if args.navidrome_db is not None:
            copied.append((MUSIC_SERVER_DB, copy_database(args.navidrome_db, args.out / MUSIC_SERVER_DB)))
        for name, size in copied:
            print(f"{name} {size} bytes, whole", file=out)
        return 0
    except BackupError as error:
        print(f"backup: {error}", file=err)
        return 1
