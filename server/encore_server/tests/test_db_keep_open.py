"""One connection is kept open while the server runs (P3-29 part 1b, audit B-10 family).

SQLite in WAL mode checkpoints the journal and DELETES its files when the last connection closes. `Database.tx()` opens and closes a connection per call, so
with nothing else open every single write paid that (measured in the server image: 144 writes a second; with one idle connection kept open: 2,796). These
tests pin the mechanism, not a timing: while the server runs, the journal stays; when it stops, the connection is closed.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from tests.conftest import FakeVerifier


def wal_of(db: Database) -> Path:
    return Path(str(db.path) + "-wal")


@pytest.fixture()
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "data" / "encore.db")
    database.migrate()
    yield database
    database.release()


def write(db: Database) -> None:
    with db.tx() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS scratch (n INTEGER)")
        conn.execute("INSERT INTO scratch (n) VALUES (1)")


def test_without_one_open_connection_every_write_removes_the_journal_files(db: Database) -> None:
    """The cause, shown: the last connection closing takes the journal with it."""
    write(db)

    assert not wal_of(db).exists()


def test_with_one_open_connection_the_journal_stays_between_writes(db: Database) -> None:
    db.hold_open()

    write(db)
    write(db)

    assert wal_of(db).exists(), "nothing checkpoints and deletes the journal after each write"
    assert db.is_held_open


def test_holding_open_twice_is_one_connection_and_releasing_closes_it(db: Database) -> None:
    db.hold_open()
    db.hold_open()
    assert db.is_held_open

    db.release()
    db.release()  # harmless

    assert not db.is_held_open
    write(db)
    assert not wal_of(db).exists(), "after release the database behaves as before"


def test_the_data_is_the_same_with_the_connection_held(db: Database) -> None:
    db.hold_open()
    write(db)

    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM scratch").fetchone()["n"] == 1


def test_the_running_server_holds_one_open_and_lets_go_when_it_stops(tmp_path: Path, verifier: FakeVerifier) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as client:
        database = client.app.state.services.db  # type: ignore[attr-defined]
        assert database.is_held_open

    assert not database.is_held_open


def test_a_migration_never_runs_with_a_held_connection(tmp_path: Path) -> None:
    """A failed migration deletes the journal files to put the backup back: nothing may hold the database open while that happens."""
    database = Database(tmp_path / "data" / "encore.db")

    assert not database.is_held_open
    database.migrate()
    assert not database.is_held_open, "migrating does not hold a connection; the server does, after it has migrated"
