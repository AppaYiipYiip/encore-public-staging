from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from encore_server.db import Database, MigrationFailed
from encore_server.ids import is_id, new_id, ulid


def test_a_new_database_gets_every_table(tmp_path: Path) -> None:
    db = Database(tmp_path / "encore.db")

    assert db.migrate() == [number for number, _, _ in Database._migrations()]

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
        "work_item",
        "work_item_person",
        "import",
        "import_entry",
        "file_log",
        "notification",
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

    broken = [(999, "0999_broken.sql", "CREATE TABLE half (x INTEGER); INSERT INTO nowhere VALUES (1);")]
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
    db.migrate(version="9.9", migrations=[(1, "0001_initial.sql", ""), (999, "0999_more.sql", "CREATE TABLE extra (x INTEGER);")])

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


def _the_migration_that_stores_the_artist_facts() -> tuple[int, str, str]:
    found = [m for m in Database._migrations() if m[1].startswith("0014")]
    assert len(found) == 1, "N-26 slice 2 is migration 0014"
    return found[0]


def test_the_migration_that_stores_the_artist_facts_only_adds_two_columns_and_no_value(tmp_path: Path) -> None:
    """No `DEFAULT` (an old row would read as that value), no `CHECK` (a fifth basis would need a table rebuild: the value is checked in `refs`), no
    `UPDATE` (nothing is derived for old rows): what an old row means is NULL, "as before"."""
    _, _, sql = _the_migration_that_stores_the_artist_facts()
    statements = [
        " ".join(part.split())
        for part in "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--")).split(";")
        if part.strip()
    ]
    assert statements == [
        "ALTER TABLE song_ref ADD COLUMN artist_basis TEXT",
        "ALTER TABLE song_ref ADD COLUMN uploader TEXT",
    ]


def test_the_artist_facts_migration_leaves_every_old_row_as_it_was_and_takes_a_backup_first(tmp_path: Path) -> None:
    db = Database(tmp_path / "encore.db")
    # Exactly the steps up to the one under test: a migration added LATER (N-27's 0015 came the next day) must not change what this test says.
    up_to_this_one = [m for m in Database._migrations() if m[0] <= 14]
    db.migrate(version="before", migrations=[m for m in up_to_this_one if m[0] <= 13])
    with db.tx() as conn:
        for number, (title, artists, video) in enumerate(
            [
                ("Heartbeat (Live on KEXP)", '["KEXP"]', "IY2WwzI_86k"),
                ("Windowpane", '["Opeth"]', None),
                ("Intro", '["Unknown Artist"]', "aaaaaaaaaaa"),
            ]
        ):
            conn.execute(
                "INSERT INTO song_ref (id, title, artists, album, duration_ms, ytm_video_id, norm_key, created_at, missing_reason, missing_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    f"sr_{number:026d}",
                    title,
                    artists,
                    None,
                    245000 + number,
                    video,
                    f"key{number}",
                    1000 + number,
                    "not_found" if number == 1 else None,
                    5,
                ),
            )
    with db.read() as conn:
        before = [tuple(row) for row in conn.execute("SELECT * FROM song_ref ORDER BY id")]
        width = len(before[0])

    assert db.migrate(version="n26-slice2", migrations=up_to_this_one) == [14]

    with db.read() as conn:
        after = [tuple(row) for row in conn.execute("SELECT * FROM song_ref ORDER BY id")]
        columns = {c["name"]: c for c in conn.execute("PRAGMA table_info(song_ref)")}
    assert [row[:width] for row in after] == before, "every column an old row had is byte for byte what it was"
    assert [row[width:] for row in after] == [(None, None)] * 3, (
        'the two new columns are NULL, which means "as before" and is never read as `channel`'
    )
    assert list(columns)[-2:] == ["artist_basis", "uploader"]
    assert all(columns[name]["notnull"] == 0 and columns[name]["dflt_value"] is None for name in ("artist_basis", "uploader"))
    backups = list((tmp_path / "backups").glob("encore-n26-slice2-*.db"))
    assert len(backups) == 1
    copy = sqlite3.connect(backups[0])
    try:
        names = {row[1] for row in copy.execute("PRAGMA table_info(song_ref)")}
        assert "artist_basis" not in names and copy.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0] == 3, (
            "the copy is from before"
        )
    finally:
        copy.close()
    assert db.migrate(migrations=up_to_this_one) == [], "and a second run does nothing"
