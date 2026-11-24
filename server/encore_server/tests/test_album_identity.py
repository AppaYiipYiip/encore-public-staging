"""N-34 slice 2, the storage half: the migration that remembers what the catalogue said of a song (`identity_*`), and `refs.release_facts_to_fill`, the ONE rule
that says which facts of a release a song's row may be given (design: section N-34, part 3).

**Fill only, never rewrite.** A song's identity is its id (likes, playlist entries and the kept file point at it) and a stamped album is effectively permanent
(slice 5 files the song by it), so every fact is written only where the row has none, and nothing is written that the catalogue's release does not describe.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from encore_server import refs
from encore_server.album_finder import Match
from encore_server.db import Database

COVER = "https://cdn-images.dzcdn.net/images/cover/abc/1000x1000-000000-80-0-0.jpg"


def _the_identity_migration() -> tuple[int, str, str]:
    found = [m for m in Database._migrations() if "album_identity" in m[1]]
    assert len(found) == 1, "N-34 slice 2 adds exactly one migration, `NNNN_album_identity.sql`"
    return found[0]


def test_the_migration_only_adds_four_nullable_columns_and_no_value() -> None:
    """No `DEFAULT` (an old row would read as that value: NULL is "never asked", as before), no `CHECK` (a fourth outcome would need a table rebuild: the value is
    checked in `album_pass`), no `UPDATE` (nothing is derived for old rows), and NO journal table: that is slice 5's (`refile_log`)."""
    _, _, sql = _the_identity_migration()
    statements = [
        " ".join(part.split())
        for part in "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--")).split(";")
        if part.strip()
    ]
    assert statements == [
        "ALTER TABLE song_ref ADD COLUMN identity_tried_at INTEGER",
        "ALTER TABLE song_ref ADD COLUMN identity_rev INTEGER",
        "ALTER TABLE song_ref ADD COLUMN identity_outcome TEXT",
        "ALTER TABLE song_ref ADD COLUMN identity_reason TEXT",
    ]


def test_the_migration_number_is_not_taken_twice_and_comes_after_the_rehome_s() -> None:
    """Main's schema was 18 (`0018_ref_recheck`) when this step was cut, so it is 0019; a later branch takes the next number after whatever main has (`Database.migrate` refuses two
    steps with one number, and this checks it for this one)."""
    numbers = [number for number, _, _ in Database._migrations()]
    number, _, _ = _the_identity_migration()
    assert numbers.count(number) == 1, "`Database.migrate` refuses two steps with one number"
    assert number == 19


def test_the_migration_leaves_every_old_row_as_it_was_and_takes_a_backup_first(tmp_path: Path) -> None:
    number, _, _ = _the_identity_migration()
    db = Database(tmp_path / "encore.db")
    # Exactly the steps up to the one under test (`test_db.py`'s convention): a step added LATER must not change what this test says.
    before_this_one = [m for m in Database._migrations() if m[0] < number]
    up_to_this_one = [m for m in Database._migrations() if m[0] <= number]
    db.migrate(version="before", migrations=before_this_one)
    with db.tx() as conn:
        for index, (title, album) in enumerate([("Requiem", None), ("Creature", "[Unknown Album]"), ("Hollow", "Hollow")]):
            conn.execute(
                "INSERT INTO song_ref (id, title, artists, album, duration_ms, norm_key, created_at) VALUES (?,?,?,?,?,?,?)",
                (f"sr_{index:026d}", title, '["LANDMVRKS"]', album, 240000 + index, f"landmvrks|{title.lower()}|", 1000 + index),
            )
    with db.read() as conn:
        old = [tuple(row) for row in conn.execute("SELECT * FROM song_ref ORDER BY id")]
        width = len(old[0])

    assert db.migrate(version="n34-slice2", migrations=up_to_this_one) == [number]

    with db.read() as conn:
        new = [tuple(row) for row in conn.execute("SELECT * FROM song_ref ORDER BY id")]
        columns = {c["name"]: c for c in conn.execute("PRAGMA table_info(song_ref)")}
    assert [row[:width] for row in new] == old, "every column an old row had is byte for byte what it was"
    assert [row[width:] for row in new] == [(None, None, None, None)] * 3, 'NULL is "never asked", the state every old row is in'
    for name, kind in (
        ("identity_tried_at", "INTEGER"),
        ("identity_rev", "INTEGER"),
        ("identity_outcome", "TEXT"),
        ("identity_reason", "TEXT"),
    ):
        assert columns[name]["type"] == kind and not columns[name]["notnull"] and columns[name]["dflt_value"] is None, name
    assert list(db.path.parent.glob("*n34-slice2*")) or list(db.path.parent.glob("**/*n34-slice2*")), (
        "a backup was taken before the step"
    )


# ------------------------------------------------------------------------------------------------------------------ release_facts_to_fill


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "e.db")
    database.migrate(version="test")
    return database


def make_ref(db: Database, title: str = "Requiem", artist: str = "LANDMVRKS", **given: Any) -> str:
    """A ref made the way every ref is (`refs.resolve`), then the columns the test names set directly."""
    with db.tx() as conn:
        ref = refs.resolve(conn, {"title": title, "artists": [artist], "duration_ms": 240_000})
        for column, value in given.items():
            conn.execute(f"UPDATE song_ref SET {column} = ? WHERE id = ?", (value, ref["id"]))  # noqa: S608 - the test's own column names
    return str(ref["id"])


def match(**changes: Any) -> Match:
    base: dict[str, Any] = {
        "deezer_id": "3116792141",
        "isrc": "DEYO62400324",
        "album_id": "676735071",
        "album": "The Darkest Place I've Ever Been",
        "record_type": "album",
        "release_date": "2025-04-18",
        "year": 2025,
        "track_no": 10,
        "disc_no": 1,
        "cover": COVER,
    }
    return Match(**{**base, **changes})


def facts(db: Database, ref_id: str, found: Match) -> dict[str, Any]:
    with db.read() as conn:
        row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref_id,)).fetchone()
        return refs.release_facts_to_fill(conn, row, found)


EVERYTHING = {
    "album": "The Darkest Place I've Ever Been",
    "track_no": 10,
    "disc_no": 1,
    "year": 2025,
    "deezer_id": "3116792141",
    "isrc": "DEYO62400324",
    "cover_url": COVER,
}


@pytest.mark.parametrize("album", [None, "", "   ", "[Unknown Album]", "unknown album", "[UNKNOWN ALBUM]"])
def test_a_song_with_no_album_or_the_placeholder_is_given_every_fact_of_the_release(db: Database, album: str | None) -> None:
    ref = make_ref(db, album=album)
    assert facts(db, ref, match()) == EVERYTHING


def test_an_album_the_song_already_has_is_never_rewritten_and_nothing_of_another_release_is_written(db: Database) -> None:
    """An import gave the album: the catalogue's track number, year and picture describe ANOTHER release, and the ids would assert a recording this row did not
    say it was. Nothing at all is written (the pass never asks such a song; slice 3's keeper and slice 5's repair may call the rule for any)."""
    ref = make_ref(db, album="Greatest Hits")
    assert facts(db, ref, match()) == {}


def test_an_album_of_the_same_release_keeps_its_own_title_and_takes_the_release_facts_it_lacks(db: Database) -> None:
    ref = make_ref(db, album="The Darkest Place I've Ever Been (Deluxe Edition)")
    assert facts(db, ref, match()) == {k: v for k, v in EVERYTHING.items() if k != "album"}


@pytest.mark.parametrize(
    ("column", "value", "left_out"),
    [
        ("track_no", 3, "track_no"),
        ("disc_no", 2, "disc_no"),
        ("year", 2019, "year"),
        ("cover_url", "https://cdn-images.dzcdn.net/images/cover/zzz/1000x1000.jpg", "cover_url"),
    ],
)
def test_a_fact_the_row_already_has_is_never_rewritten(db: Database, column: str, value: Any, left_out: str) -> None:
    ref = make_ref(db, **{column: value})
    assert facts(db, ref, match()) == {k: v for k, v in EVERYTHING.items() if k != left_out}


def test_an_id_the_row_already_has_is_never_rewritten(db: Database) -> None:
    ref = make_ref(db, deezer_id="111", isrc="XXAAA1100001")
    assert facts(db, ref, match()) == {k: v for k, v in EVERYTHING.items() if k not in ("deezer_id", "isrc")}


def test_an_id_another_song_holds_is_not_taken_from_it_and_the_rest_still_fills(db: Database) -> None:
    make_ref(db, "Another", "Someone", deezer_id="3116792141")
    make_ref(db, "Third", "Someone", isrc="DEYO62400324")
    ref = make_ref(db)
    assert facts(db, ref, match()) == {k: v for k, v in EVERYTHING.items() if k not in ("deezer_id", "isrc")}


def test_a_picture_that_is_not_the_catalogues_is_not_taken(db: Database) -> None:
    ref = make_ref(db)
    assert "cover_url" not in facts(db, ref, match(cover="https://evil.example/c.jpg"))
    assert "cover_url" not in facts(db, ref, match(cover=None))


def test_a_release_without_a_fact_gives_nothing_for_it(db: Database) -> None:
    ref = make_ref(db)
    found = match(isrc=None, year=None, track_no=None, disc_no=None, cover=None)
    assert facts(db, ref, found) == {"album": "The Darkest Place I've Ever Been", "deezer_id": "3116792141"}


def test_the_title_the_artists_the_key_and_the_album_artist_are_never_in_the_answer(db: Database) -> None:
    ref = make_ref(db)
    allowed = {"album", "track_no", "disc_no", "year", "deezer_id", "isrc", "cover_url"}
    assert set(facts(db, ref, match())) <= allowed


@pytest.mark.parametrize("literal", ["[Unknown Album]", "unknown album", "  [unknown album] ", "", "   "])
def test_the_placeholder_literal_or_a_blank_album_becomes_no_album_and_nothing_else_changes(db: Database, literal: str) -> None:
    ref = make_ref(db, album=literal)
    with db.read() as conn:
        row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref,)).fetchone()
    assert refs.forget_placeholder_album(row) == {"album": None}


@pytest.mark.parametrize("album", [None, "Hollow", "Unknown Album Vol. 2"])
def test_only_the_placeholder_is_forgotten(db: Database, album: str | None) -> None:
    ref = make_ref(db, album=album)
    with db.read() as conn:
        row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref,)).fetchone()
    assert refs.forget_placeholder_album(row) == {}
