"""An older server never starts on the data of a newer one (P3-29 part 2, docs/36 section 8): the Update button's way back and any rollback image depend on it.

A database that has run steps the running code does not know was made by a newer version. Reading it with older code misreads tables the older code never had, and
writing could overwrite what the newer one meant, with no error at all. So the migration runner refuses before it reads or changes anything, says what happened and what to
do in one sentence, and the entry point prints that sentence, not a stack trace.
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest

from encore_server import __main__ as entry
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database, MigrationFailed
from tests.conftest import FakeVerifier


def newer_than_the_code(path: Path, version: int = 9999) -> bytes:
    """A database the code knows fully, plus a step that only a newer version has (what a rollback to an older image finds)."""
    db = Database(path)
    db.migrate()
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO schema_migrations (version, name, at) VALUES (?, ?, 0)", (version, f"{version:04d}_from_the_future.sql")
    )
    conn.commit()
    conn.close()
    return path.read_bytes()


def test_a_database_made_by_a_newer_version_is_refused_in_words_and_left_exactly_as_it_was(tmp_path: Path) -> None:
    path = tmp_path / "data" / "encore.db"
    path.parent.mkdir()
    before = newer_than_the_code(path)
    known = max(number for number, _, _ in Database._migrations())
    with pytest.raises(MigrationFailed) as refused:
        Database(path).migrate()
    text = str(refused.value)
    assert "newer version of Encore" in text and f"{9999:04d}" in text and f"{known:04d}" in text
    assert "nothing was changed" in text and "encore update" in text and "encore restore" in text
    assert path.read_bytes() == before, "not one byte of the data may change"
    assert not list((path.parent / "backups").glob("*")) if (path.parent / "backups").exists() else True, (
        "no copy is made either: nothing is about to change"
    )


STEP = "CREATE TABLE {name} (id INTEGER PRIMARY KEY);"


def steps(*numbers: int) -> list[tuple[int, str, str]]:
    return [(n, f"{n:04d}_step.sql", STEP.format(name=f"t{n}")) for n in numbers]


def test_a_step_that_is_unknown_but_lower_than_the_newest_is_refused_too(tmp_path: Path) -> None:
    """A step removed or renumbered in the code is as foreign to the running code as a newer one: the tables it made are not the code's."""
    path = tmp_path / "encore.db"
    Database(path).migrate(migrations=steps(1, 2, 3))
    before = path.read_bytes()
    with pytest.raises(MigrationFailed, match="newer version"):
        Database(path).migrate(migrations=steps(1, 3))  # step 2 is in the data and not in the code
    assert path.read_bytes() == before


def test_an_older_database_and_the_codes_own_database_still_start(tmp_path: Path) -> None:
    path = tmp_path / "encore.db"
    assert Database(path).migrate(migrations=steps(1, 2)) == [1, 2]
    assert Database(path).migrate(migrations=steps(1, 2)) == [], "the code's own data starts and has nothing to do"
    assert Database(path).migrate(migrations=steps(1, 2, 3)) == [3], "an older database is brought up to date, as always"


def test_the_application_does_not_start_on_such_data(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    newer_than_the_code(data / "encore.db")
    settings = Settings(data_dir=data, music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False)
    with pytest.raises(MigrationFailed, match="newer version of Encore"):
        create_app(settings, verifier=FakeVerifier())


def test_the_entry_point_prints_the_sentence_and_not_a_stack_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    newer_than_the_code(data / "encore.db")
    settings = Settings(
        data_dir=data, music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False, auto_tools=False
    )
    monkeypatch.setattr(entry.Settings, "from_env", staticmethod(lambda: settings))
    ran: list[object] = []
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: ran.append(a))
    error = io.StringIO()
    monkeypatch.setattr("sys.stderr", error)
    with pytest.raises(SystemExit) as stopped:
        entry.main([])
    assert stopped.value.code == 1 and ran == [], "the server must not be run"
    text = error.getvalue()
    assert (
        text.startswith("encore_server: The data of this server was made by a newer version of Encore")
        and "Traceback" not in text
    )
