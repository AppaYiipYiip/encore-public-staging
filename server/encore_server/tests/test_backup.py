"""Backups of the databases (docs/tasks P3-12): a whole copy of a live database, a clear sentence for everything else, no data printed."""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest

from encore_server.backup import ENCORE_DB, MUSIC_SERVER_DB, BackupError, command, copy_database, verify_database


def make_db(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE person (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO person (name) VALUES (?)", [(f"person-{n}",) for n in range(rows)])
    conn.commit()
    conn.close()


def names(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT name FROM person ORDER BY id")]
    finally:
        conn.close()


def test_a_copy_has_everything_the_database_had(tmp_path: Path) -> None:
    source = tmp_path / "live.db"
    make_db(source, rows=5)
    size = copy_database(source, tmp_path / "copy.db")
    assert size > 0
    assert names(tmp_path / "copy.db") == [f"person-{n}" for n in range(5)]
    assert names(source) == names(tmp_path / "copy.db")


def test_a_copy_is_whole_while_the_server_is_writing(tmp_path: Path) -> None:
    """A writer that is mid-transaction (WAL) does not make the copy half a change."""
    source = tmp_path / "live.db"
    make_db(source, rows=2)
    writer = sqlite3.connect(source, isolation_level=None)
    writer.execute("BEGIN")
    writer.execute("INSERT INTO person (name) VALUES ('not committed yet')")
    try:
        copy_database(source, tmp_path / "copy.db")
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert names(tmp_path / "copy.db") == ["person-0", "person-1"]


def test_a_missing_database_is_a_sentence(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="not found"):
        copy_database(tmp_path / "nothing.db", tmp_path / "copy.db")
    assert not (tmp_path / "copy.db").exists()


def test_an_existing_copy_is_never_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "live.db"
    make_db(source)
    (tmp_path / "copy.db").write_bytes(b"older backup")
    with pytest.raises(BackupError, match="already exists"):
        copy_database(source, tmp_path / "copy.db")
    assert (tmp_path / "copy.db").read_bytes() == b"older backup"


def test_a_file_that_is_not_a_database_fails_the_check(tmp_path: Path) -> None:
    broken = tmp_path / ENCORE_DB
    broken.write_bytes(b"this is not sqlite" * 400)
    with pytest.raises(BackupError, match="not a readable database"):
        verify_database(broken)


def test_command_copies_both_databases_and_prints_no_rows(tmp_path: Path) -> None:
    make_db(tmp_path / "encore.db", rows=4)
    make_db(tmp_path / "nd.db", rows=2)
    out, err = io.StringIO(), io.StringIO()
    status = command(
        ["--encore-db", str(tmp_path / "encore.db"), "--navidrome-db", str(tmp_path / "nd.db"), "--out", str(tmp_path / "out")],
        out=out,
        err=err,
    )
    assert status == 0, err.getvalue()
    assert names(tmp_path / "out" / ENCORE_DB) == [f"person-{n}" for n in range(4)]
    assert names(tmp_path / "out" / MUSIC_SERVER_DB) == ["person-0", "person-1"]
    assert "person-" not in out.getvalue()
    assert ENCORE_DB in out.getvalue() and MUSIC_SERVER_DB in out.getvalue()


def test_command_without_the_music_server_database(tmp_path: Path) -> None:
    make_db(tmp_path / "encore.db")
    status = command(
        ["--encore-db", str(tmp_path / "encore.db"), "--out", str(tmp_path / "out")], out=io.StringIO(), err=io.StringIO()
    )
    assert status == 0
    assert not (tmp_path / "out" / MUSIC_SERVER_DB).exists()


def test_command_says_what_went_wrong_in_a_sentence(tmp_path: Path) -> None:
    err = io.StringIO()
    status = command(["--encore-db", str(tmp_path / "gone.db"), "--out", str(tmp_path / "out")], out=io.StringIO(), err=err)
    assert status == 1
    assert err.getvalue().startswith("backup: gone.db was not found")


def test_verify_accepts_a_good_backup_and_refuses_a_bad_one(tmp_path: Path) -> None:
    make_db(tmp_path / ENCORE_DB)
    out = io.StringIO()
    assert command(["--verify", str(tmp_path)], out=out, err=io.StringIO()) == 0
    assert "encore.db whole" in out.getvalue()
    (tmp_path / MUSIC_SERVER_DB).write_bytes(b"garbage" * 1000)
    err = io.StringIO()
    assert command(["--verify", str(tmp_path)], out=io.StringIO(), err=err) == 1
    assert "navidrome.db" in err.getvalue()


def test_verify_wants_the_encore_database(tmp_path: Path) -> None:
    err = io.StringIO()
    assert command(["--verify", str(tmp_path)], out=io.StringIO(), err=err) == 1
    assert "no encore.db" in err.getvalue()


def test_command_without_arguments_explains_itself() -> None:
    err = io.StringIO()
    assert command([], out=io.StringIO(), err=err) == 1
    assert "--encore-db" in err.getvalue()
