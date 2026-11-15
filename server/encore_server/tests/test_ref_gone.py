"""N-27 slice 2c: the server tells phones which song refs are gone (the design is in the notes of N-27, "slices 2c, 2b, 2e, 2d as ONE design").

Slice 2a's janitor deletes refs, and nothing told a phone: the files feed lists a ref that still exists, so a phone that was away never hears that an id is
gone. The precedent is `ref_merge`: a tiny table that is never purged, its own cursor (`goneSince`), the phone opts in (an old phone sends nothing and gets
nothing to act on) and a feature string (`ref-gone`) so an app never tries a route to find out.

This slice only makes the server ABLE to tell: the janitor writes one tombstone for EVERY ref it retires, in the same transaction as the delete, and the
files feed answers `goneSince`. The janitor still keeps a ref that once held a file (slice 2e lifts that, after the phone reads the tombstone: slice 2b).
The data is synthetic: fixed ids, a fixed "now".
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server import library, ref_janitor
from encore_server.db import Database, MigrationFailed
from encore_server.ref_janitor import POINTERS, RefJanitor
from tests.conftest import creds

V1 = "/encore/api/v1"
DAY = 24 * 3600 * 1000
NOW = 1_800_000_000_000
OLD = NOW - 15 * DAY


def rid(n: int) -> str:
    return f"sr_{n:026d}"


def add_ref(conn: sqlite3.Connection, n: int, created_at: int = OLD) -> str:
    ref = rid(n)
    conn.execute(
        "INSERT INTO song_ref (id, title, artists, norm_key, created_at) VALUES (?,?,?,?,?)",
        (ref, f"Song {n}", json.dumps(["Nobody"]), f"nobody|song {n}", created_at),
    )
    return ref


def like(conn: sqlite3.Connection, ref: str) -> None:
    conn.execute(
        "INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES ('pn_x', 'x', 'x', 1) ON CONFLICT DO NOTHING"
    )
    conn.execute("INSERT INTO library_item (person, kind, target, at) VALUES ('pn_x', 'like', ?, 1)", (ref,))


def janitor(db: Database, **kwargs: Any) -> RefJanitor:
    return RefJanitor(db, clock=lambda: NOW, **kwargs)


def tombstones(db: Database) -> list[tuple[str, int]]:
    with db.read() as conn:
        return [(r["ref_id"], r["at"]) for r in conn.execute("SELECT ref_id, at FROM ref_gone ORDER BY seq")]


# ------------------------------------------------------------------------------------------------ the table


def test_the_migration_adds_the_tombstone_table_and_nothing_else(db: Database) -> None:
    with db.read() as conn:
        columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(ref_gone)")}
        unique = [
            list(conn.execute(f"PRAGMA index_info({ix['name']})"))
            for ix in conn.execute("PRAGMA index_list(ref_gone)")
            if ix["unique"]
        ]
    assert set(columns) == {"seq", "ref_id", "at"}
    assert any([c["name"] for c in cols] == ["ref_id"] for cols in unique), "one tombstone per ref"
    with db.read() as conn:
        assert conn.execute("PRAGMA foreign_key_list(ref_gone)").fetchall() == [], (
            "no foreign key: the ref it names no longer exists"
        )


def test_two_migrations_with_one_number_are_refused_at_start_not_silently_skipped(tmp_path: Path) -> None:
    """Two branches that start from one main both take the next free number. On a database that ran the first, the second counts as applied, and its
    table is missing at run time with no error at start. Better: the server refuses to start and says so."""
    database = Database(tmp_path / "x.db")
    with pytest.raises(MigrationFailed, match="same number"):
        database.migrate(
            migrations=[
                (1, "0001_initial.sql", "CREATE TABLE a (x INTEGER);"),
                (2, "0002_one.sql", "CREATE TABLE b (x INTEGER);"),
                (2, "0002_other.sql", "CREATE TABLE c (x INTEGER);"),
            ]
        )


def test_the_migrations_the_server_ships_have_one_file_per_number() -> None:
    numbers = [number for number, _, _ in Database._migrations()]
    assert len(numbers) == len(set(numbers)), f"two files share a number: {sorted(n for n in numbers if numbers.count(n) > 1)}"
    assert 15 in numbers, "this slice takes 0015 on purpose (N-26 slice 2 has 0014)"


# ------------------------------------------------------------------------------------------------ the janitor writes them


def test_every_ref_the_janitor_retires_gets_one_tombstone_and_a_kept_one_gets_none(db: Database) -> None:
    with db.tx() as conn:
        gone_a, gone_b, kept = add_ref(conn, 1), add_ref(conn, 2), add_ref(conn, 3)
        like(conn, kept)

    assert janitor(db).run_once() == 2

    assert tombstones(db) == [(gone_a, NOW), (gone_b, NOW)]
    with db.read() as conn:
        assert conn.execute("SELECT id FROM song_ref").fetchall()[0]["id"] == kept


def test_a_second_pass_writes_nothing_more(db: Database) -> None:
    with db.tx() as conn:
        add_ref(conn, 1)
    janitor(db).run_once()
    first = tombstones(db)

    assert janitor(db).run_once() == 0

    assert tombstones(db) == first


def test_a_pass_that_fails_leaves_no_tombstone_for_a_ref_that_is_still_there(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tombstone and the delete are one transaction: a phone must never be told that a ref is gone while the server still has it. The chunk is ONE
    id, so the first ref is deleted and its tombstone written by statements of their own, and then the foreign key refuses the next ref."""
    monkeypatch.setattr(ref_janitor, "POINTERS", {k: v for k, v in POINTERS.items() if k != "play_event"})
    monkeypatch.setattr(ref_janitor, "_DELETE_CHUNK", 1)
    with db.tx() as conn:
        free = add_ref(conn, 1, OLD - DAY)
        pointed = add_ref(conn, 2)
        conn.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES ('pn_x', 'x', 'x', 1)")
        conn.execute("INSERT INTO play_event (id, person, ref, at, ms_played) VALUES ('pv_1', 'pn_x', ?, 1, 1000)", (pointed,))

    with pytest.raises(sqlite3.IntegrityError):
        janitor(db).run_once()

    assert tombstones(db) == []
    with db.read() as conn:
        assert {r["id"] for r in conn.execute("SELECT id FROM song_ref")} == {free, pointed}


def test_a_ref_that_once_held_a_file_is_still_kept_in_this_slice(db: Database) -> None:
    """Slice 2c only makes the server able to tell; 2e lifts `file_history` once the phone reads the tombstone (2b)."""
    with db.tx() as conn:
        ex_file = add_ref(conn, 1)
        conn.execute("INSERT INTO file_log (ref, at) VALUES (?, ?)", (ex_file, NOW - 100 * DAY))

    assert janitor(db).run_once() == 0
    assert tombstones(db) == []


# ------------------------------------------------------------------------------------------------ the feed tells phones


def test_the_files_feed_lists_the_gone_refs_after_the_phones_own_cursor(db: Database) -> None:
    with db.tx() as conn:
        ids = [add_ref(conn, n) for n in (1, 2, 3)]
    janitor(db).run_once()

    with db.read() as conn:
        first = library.files_since(conn, 0, gone_since=0)
        again = library.files_since(conn, 0, gone_since=int(first["goneCursor"]))

    assert [g["id"] for g in first["gone"]] == ids
    assert all(isinstance(g["seq"], int) for g in first["gone"])
    assert first["goneMore"] is False
    assert again["gone"] == [] and again["goneCursor"] == first["goneCursor"], "nothing new: the same cursor comes back"


def test_the_gone_list_pages_like_the_merges_do(db: Database) -> None:
    with db.tx() as conn:
        ids = [add_ref(conn, n) for n in (1, 2, 3)]
    janitor(db).run_once()

    with db.read() as conn:
        page1 = library.files_since(conn, 0, limit=2, gone_since=0)
        page2 = library.files_since(conn, 0, limit=2, gone_since=int(page1["goneCursor"]))

    assert [g["id"] for g in page1["gone"]] == ids[:2] and page1["goneMore"] is True
    assert [g["id"] for g in page2["gone"]] == ids[2:] and page2["goneMore"] is False


def test_a_phone_that_does_not_ask_is_told_nothing_to_act_on(db: Database) -> None:
    """An older app sends no goneSince: the answer carries an empty list and the cursor 0, as `merges` does for an app that predates merges."""
    with db.tx() as conn:
        add_ref(conn, 1)
    janitor(db).run_once()

    with db.read() as conn:
        answer = library.files_since(conn, 0)

    assert answer["gone"] == [] and answer["goneCursor"] == "0" and answer["goneMore"] is False


# ------------------------------------------------------------------------------------------------ the route and the feature string


def test_the_route_answers_goneSince_and_the_server_lists_the_feature(client: TestClient) -> None:
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    with db.tx() as conn:
        gone = add_ref(conn, 1)
    janitor(db).run_once()

    asked = client.get(f"{V1}/library/files", params={**creds("marwa"), "since": "0", "goneSince": "0"})
    plain = client.get(f"{V1}/library/files", params={**creds("marwa"), "since": "0"})
    bad = client.get(f"{V1}/library/files", params={**creds("marwa"), "goneSince": "soon"})

    assert asked.status_code == 200 and [g["id"] for g in asked.json()["gone"]] == [gone]
    assert plain.status_code == 200 and plain.json()["gone"] == []
    assert bad.status_code == 400, "a cursor is a number, as for the other feeds"
    assert "ref-gone" in client.get(f"{V1}/info").json()["features"]


def test_a_phone_that_was_away_over_a_prune_and_a_retirement_still_hears_it(client: TestClient) -> None:
    """The scenario of slice 2a, finished: the phone takes its cursors, goes away, the janitor retires refs, the phone returns with its OLD cursors."""
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    before = client.get(f"{V1}/library/files", params={**creds("marwa"), "since": "0", "goneSince": "0"}).json()["goneCursor"]
    with db.tx() as conn:
        tap = add_ref(conn, 1)  # a tap on a song the server could not find: the phone holds a row for it

    janitor(db).run_once()

    back = client.get(f"{V1}/library/files", params={**creds("marwa"), "since": "0", "goneSince": before}).json()
    assert [g["id"] for g in back["gone"]] == [tap]


# ------------------------------------------------------------------------------------------------ the saved real response (ADR-R41 T5)

FIXTURE = Path(__file__).resolve().parents[3] / "app" / "test" / "fixtures" / "server" / "library-files-with-gone.json"


def test_the_files_response_with_gone_is_the_saved_fixture_the_phones_parser_will_read(client: TestClient) -> None:
    """One contract: the server's own test saves a REAL response, built by the real endpoint on synthetic data, and the app's parser reads it (slice 2b). When
    this response changes, this test fails until the file is written again (`ENCORE_WRITE_FIXTURES=1 pytest tests/test_ref_gone.py -k saved_fixture`) and
    the app's parser is changed to read it. Nothing in it is a person's data."""
    import os

    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    with db.tx() as conn:
        add_ref(conn, 1)
        add_ref(conn, 2)
    janitor(db).run_once()
    response = client.get(f"{V1}/library/files", params={**creds("marwa"), "since": "0", "mergesSince": "0", "goneSince": "0"})
    assert response.status_code == 200
    body = response.json()
    body.pop("serverTime")  # the one value that is different every time
    text = json.dumps(body, indent=2, ensure_ascii=False) + "\n"

    if os.environ.get("ENCORE_WRITE_FIXTURES") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")

    assert FIXTURE.is_file(), "run with ENCORE_WRITE_FIXTURES=1 once to write it"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == body
    assert body["gone"] and all(set(g) == {"id", "seq"} for g in body["gone"])
