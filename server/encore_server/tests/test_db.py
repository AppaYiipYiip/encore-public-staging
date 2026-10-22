from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from encore_server.db import Database, MigrationFailed
from encore_server.ids import is_id, new_id, ulid


def test_a_new_database_gets_every_table(tmp_path: Path) -> None:
    db = Database(tmp_path / "encore.db")

    assert db.migrate() == [1]

    with db.read() as conn:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {
        "person",
        "device",
        "song_ref",
        "song_file",
        "library_item",
        "playlist",
        "playlist_entry",
        "play_event",
        "playback_state",
        "change_log",
        "idempotency_key",
        "schema_migrations",
    } <= tables


def test_migrating_twice_does_nothing_the_second_time(tmp_path: Path) -> None:
    db = Database(tmp_path / "encore.db")
    db.migrate()
    assert db.migrate() == []


def test_the_database_is_in_wal_mode_with_foreign_keys(db: Database) -> None:
    with db.read() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_a_transaction_that_fails_leaves_nothing_behind(db: Database) -> None:
    with pytest.raises(RuntimeError), db.tx() as conn:
        conn.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES ('pn_x', 'u', 'u', 1)")
        raise RuntimeError("boom")

    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM person").fetchone()[0] == 0


def test_a_failed_migration_restores_the_database_and_says_so_plainly(tmp_path: Path) -> None:
    db = Database(tmp_path / "encore.db")
    db.migrate()
    with db.tx() as conn:
        conn.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES ('pn_keep', 'marwa', 'marwa', 1)")

    broken = [(2, "0002_broken.sql", "CREATE TABLE half (x INTEGER); INSERT INTO nowhere VALUES (1);")]
    with pytest.raises(MigrationFailed) as caught:
        db.migrate(migrations=[(1, "0001_initial.sql", "")] + broken)

    assert "left as it was" in str(caught.value)
    with db.read() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "half" not in names, "no half-applied step"
        assert conn.execute("SELECT navidrome_user FROM person").fetchone()["navidrome_user"] == "marwa", "the data is as it was"


def test_a_backup_is_taken_before_a_pending_migration(tmp_path: Path) -> None:
    db = Database(tmp_path / "encore.db")
    db.migrate()
    db.migrate(version="9.9", migrations=[(1, "0001_initial.sql", ""), (2, "0002_more.sql", "CREATE TABLE extra (x INTEGER);")])

    backups = list((tmp_path / "backups").glob("encore-9.9-*.db"))
    assert len(backups) == 1
    copy = sqlite3.connect(backups[0])
    assert copy.execute("SELECT name FROM sqlite_master WHERE name = 'person'").fetchone() is not None
    assert copy.execute("SELECT name FROM sqlite_master WHERE name = 'extra'").fetchone() is None, "the backup is from before"
    copy.close()


def test_ids_have_a_type_prefix_and_sort_by_creation() -> None:
    first, second = new_id("pl"), new_id("pl")
    assert is_id(first, "pl") and not is_id(first, "pe")
    assert first[:3] == "pl_" and len(first) == 29
    assert ulid(1000) < ulid(2000)
    assert not is_id("pl_short", "pl") and not is_id(None, "pl")
    assert second != first
