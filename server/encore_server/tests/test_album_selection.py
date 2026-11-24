"""N-34 slice 2, review fix 2 (the lead's read of PR 125): ONE selection for the album pass and its dry run.

The dry run is the gate before any image that holds the pass runs on a real server, so reading it must predict what the pass will ask and stamp. It used to select with a SQL
of its own (no like or playlist entry, no worklist, another order, no retry rule). Now `album_pass.wanting` is the one function, and these tests run the REAL pass and the dry
run's `entries` over one database and compare them.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from encore_server import album_dryrun, album_finder, album_pass
from encore_server.album_finder import refusal
from encore_server.db import Database
from tests.test_album_pass import DAY_MS, NOW, Catalogue, finder, make_ref, pdb  # noqa: F401 - `pdb` is a fixture


def open_copy(db: Database) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{db.path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def a_library(db: Database) -> dict[str, str]:
    """One song of each kind the selection must tell apart. [ids] maps a name to the ref."""
    ids: dict[str, str] = {}
    ids["kept"] = make_ref(db, "Kept", "Band A", 200_000)
    ids["liked only"] = make_ref(db, "Liked Only", "Band B", 200_000, kept=None, like=True)
    ids["in a playlist only"] = make_ref(db, "In A Playlist", "Band C", 200_000, kept=None)
    with db.tx() as conn:
        owner = "pn_1"
        conn.execute("INSERT INTO playlist (id, owner, name, created_at, updated_at) VALUES ('pl_1', ?, 'p', 1, 1)", (owner,))
        conn.execute(
            "INSERT INTO playlist_entry (id, playlist, position, ref, added_by, at) VALUES ('pe_1', 'pl_1', 1.0, ?, ?, 1)",
            (ids["in a playlist only"], owner),
        )
    ids["nobody has it"] = make_ref(db, "Nobody Has It", "Band D", 200_000, kept=None)
    ids["on the worklist"] = make_ref(db, "On The Worklist", "Band E", 200_000)
    with db.tx() as conn:
        conn.execute("INSERT INTO ref_recheck (ref, at, moved) VALUES (?, 1, 0)", (ids["on the worklist"],))
    ids["a channel"] = make_ref(db, "A Channel Upload", "Band F", 200_000, artist_basis="channel")
    ids["has an id"] = make_ref(db, "Has An Id", "Band G", 200_000, deezer_id="42")
    ids["has an album"] = make_ref(db, "Has An Album", "Band H", 200_000, album="Their Album")
    ids["none just now"] = make_ref(
        db,
        "None Just Now",
        "Band I",
        200_000,
        identity_outcome="none",
        identity_rev=album_finder.IDENTITY_REVISION,
        identity_tried_at=NOW,
    )
    ids["none a week ago"] = make_ref(
        db,
        "None A Week Ago",
        "Band J",
        200_000,
        identity_outcome="none",
        identity_rev=album_finder.IDENTITY_REVISION,
        identity_tried_at=NOW - 7 * DAY_MS,
    )
    ids["none of an older rule"] = make_ref(
        db, "None Of An Older Rule", "Band K", 200_000, identity_outcome="none", identity_rev=0, identity_tried_at=NOW
    )
    ids["held just now"] = make_ref(
        db,
        "Held Just Now",
        "Band L",
        200_000,
        identity_outcome="held",
        identity_rev=album_finder.IDENTITY_REVISION,
        identity_tried_at=NOW,
    )
    ids["nothing to compare"] = make_ref(db, "\U0001f3b5", "Band M", 200_000)
    ids["no length"] = make_ref(db, "No Length", "Band N", None)
    with db.tx() as conn:  # the order of making is the order of `created_at`, which refs made in one millisecond would tie on
        for number, ref in enumerate(ids.values()):
            conn.execute("UPDATE song_ref SET created_at = ? WHERE id = ?", (1000 + number, ref))
    return ids


def what_the_dry_run_would_ask(db: Database) -> list[str]:
    conn = open_copy(db)
    try:
        return [e.ref_id for e in album_dryrun.entries(conn, now=NOW)]
    finally:
        conn.close()


def test_the_dry_run_selects_exactly_the_songs_the_pass_asks_and_in_the_same_order(pdb: Database) -> None:  # noqa: F811
    ids = a_library(pdb)
    by_title = {pdb_title(pdb, ref): ref for ref in ids.values()}
    conn = open_copy(pdb)
    try:
        entries = album_dryrun.entries(conn, now=NOW)  # BEFORE the pass: after it the songs it asked are `none` for a week
    finally:
        conn.close()
    selected = [e.ref_id for e in entries]
    songs = {e.ref_id: e.song for e in entries}
    catalogue = Catalogue()
    finder(pdb, catalogue).run_once()
    asked = [by_title[title] for _, title in catalogue.searched]
    askable = [ref for ref in selected if refusal(songs[ref]) is None]
    assert asked == askable, "what the dry run says it would ask is what the pass asked"
    assert [name for name, ref in ids.items() if ref in asked] == [
        "kept",
        "liked only",
        "in a playlist only",
        "none a week ago",
        "none of an older rule",
    ], (
        "and it is the right set: a kept file first, then the songs somebody has; a recent none and a recent held wait; the worklist, a channel, an id and an album are not asked"
    )
    for name in ("nothing to compare", "no length"):
        assert ids[name] in selected, (
            f"{name}: the pass examines it (it forgets its placeholder) and asks nobody: the dry run lists it too, the report counts it apart"
        )


def test_the_dry_run_can_still_be_told_to_leave_out_the_songs_with_no_kept_file(pdb: Database) -> None:  # noqa: F811
    ids = a_library(pdb)
    conn = open_copy(pdb)
    try:
        kept_only = [e.ref_id for e in album_dryrun.entries(conn, kept_only=True, now=NOW)]
        everything = [e.ref_id for e in album_dryrun.entries(conn, now=NOW)]
    finally:
        conn.close()
    assert ids["liked only"] not in kept_only and ids["liked only"] in everything
    assert ids["kept"] in kept_only and kept_only == [ref for ref in everything if ref in kept_only], (
        "a filter on top of the one selection, same order"
    )


def test_the_limit_and_the_music_root_are_the_dry_runs_own_on_top_of_the_one_selection(pdb: Database) -> None:  # noqa: F811
    a_library(pdb)
    conn = open_copy(pdb)
    try:
        everything = [e.ref_id for e in album_dryrun.entries(conn, now=NOW)]
        assert [e.ref_id for e in album_dryrun.entries(conn, limit=2, now=NOW)] == everything[:2]
    finally:
        conn.close()


def test_one_function_is_the_selection_of_both(pdb: Database, monkeypatch: Any) -> None:  # noqa: F811
    """A change of the selection is a change of `album_pass.wanting`, for both: replace it and both follow."""
    ids = a_library(pdb)
    only = [ids["kept"]]

    def narrowed(conn: sqlite3.Connection, *, now: int, report: Any = None) -> list[sqlite3.Row]:
        return [row for row in real(conn, now=now, report=report) if row["id"] in only]

    real = album_pass.wanting
    monkeypatch.setattr(album_pass, "wanting", narrowed)
    assert what_the_dry_run_would_ask(pdb) == only
    catalogue = Catalogue()
    finder(pdb, catalogue).run_once()
    assert catalogue.searched == [("Band A", "Kept")]


def pdb_title(db: Database, ref: str) -> str:
    with db.read() as conn:
        return str(conn.execute("SELECT title FROM song_ref WHERE id = ?", (ref,)).fetchone()["title"])
