"""N-34 slice 3: the dry run shows what NEW KEEPS would be filed under, before any image that carries slice 3 runs on a server the project runs (the lead's gate, rule 4 of the slice).

The report decides with the very function a keep asks with (`album_finder.decide`), selects with the very function (`album_pass.wanting`) and plans the place with the very
function (`keeper.placement.plan_for_ref`), so the last test here runs the REAL keeper over the same database and compares: what the report says is what a keep does.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from encore_server import album_dryrun, album_finder, album_pass, library
from encore_server.db import Database
from tests import test_album_pass
from tests.test_album_pass import Catalogue, landmvrks, make_ref
from tests.test_keeper_new_keeps import ALBUM_DIR, FILE_LENGTH_MS, KeepRig

pdb = test_album_pass.pdb


def open_copy(db: Database) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{db.path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def a_library(db: Database) -> dict[str, str]:
    """One song of each kind a new keep must tell apart: [ids] maps a name to the ref."""
    ids: dict[str, str] = {}
    ids["kept and linked"] = make_ref(db, "Requiem", "LANDMVRKS", 250_000)
    ids["new, known"] = make_ref(db, "Creature", "LANDMVRKS", FILE_LENGTH_MS, kept=None, like=True)
    ids["new, unknown"] = make_ref(db, "A Song Nobody Recorded", "Nobody At All", 200_000, kept=None, like=True)
    ids["the Hosts own file"] = make_ref(
        db, "The Hosts Song", "Somebody", 200_000, kept="Albums/Somebody/x.flac", source="library"
    )
    ids["placed, not linked yet"] = make_ref(
        db, "Placed Song", "Somebody Else", 200_000, kept="Encore/Somebody Else/Singles/Placed Song.opus"
    )
    with db.tx() as conn:
        conn.execute("UPDATE song_file SET navidrome_song_id = NULL WHERE ref = ?", (ids["placed, not linked yet"],))
    return ids


def test_the_new_keeps_mode_selects_only_songs_the_music_server_has_no_file_of(pdb: Database) -> None:
    ids = a_library(pdb)
    conn = open_copy(pdb)
    everything = album_dryrun.entries(conn, now=test_album_pass.NOW)
    only_new = album_dryrun.entries(conn, new_keeps_only=True, now=test_album_pass.NOW)

    assert {e.ref_id for e in only_new} == {ids["new, known"], ids["new, unknown"], ids["placed, not linked yet"]}
    flagged = {e.ref_id for e in everything if e.new_keep}
    assert flagged == {e.ref_id for e in only_new}, "the same songs are flagged in the full run"
    assert [e.ref_id for e in only_new] == [e.ref_id for e in everything if e.new_keep], (
        "and in the same order: it is ONE selection, filtered"
    )
    selected = {row["id"] for row in album_pass.wanting(conn, now=test_album_pass.NOW)}
    assert {e.ref_id for e in only_new} <= selected, "never a song the pass would not ask"


def test_a_song_a_keep_is_waiting_for_is_a_new_keep_even_when_nobody_likes_it(pdb: Database) -> None:
    """A song played on two days is kept with no like and no playlist entry (`test_keep_triggers`): the keeper asks its album, so the report must show it, though the pass
    (which asks songs somebody has or the server keeps) would not."""
    waiting = make_ref(pdb, "Creature", "LANDMVRKS", FILE_LENGTH_MS, album=None, kept=None)
    finished = make_ref(pdb, "Requiem", "LANDMVRKS", 250_000, album=None, kept=None)
    with pdb.tx() as conn:
        for item, ref, state in (("wk_1", waiting, "queued"), ("wk_2", finished, "done")):
            conn.execute(
                "INSERT INTO work_item (id, kind, ref, priority, state, attempts, next_try_at, created_at, updated_at) VALUES (?, 'keep', ?, 4, ?, 0, 0, 0, 0)",
                (item, ref, state),
            )
    conn = open_copy(pdb)
    assert waiting not in {e.ref_id for e in album_dryrun.entries(conn, now=test_album_pass.NOW)}, (
        "the pass asks nobody that nobody has"
    )
    in_the_mode = {e.ref_id for e in album_dryrun.entries(conn, new_keeps_only=True, now=test_album_pass.NOW)}
    assert in_the_mode == {waiting}, "a keep that is queued or running counts; a finished one does not"


def test_the_report_names_the_folder_each_new_keep_would_be_filed_under(pdb: Database, tmp_path: Path) -> None:
    ids = a_library(pdb)
    conn = open_copy(pdb)
    catalogue = landmvrks()
    items = album_dryrun.entries(conn, new_keeps_only=True, now=test_album_pass.NOW)

    rows = album_dryrun.run(conn, items, catalogue.search, catalogue.album, music_root=tmp_path)

    by_ref = {row.entry.ref_id: row for row in rows}
    assert by_ref[ids["new, known"]].keep_path == f"{ALBUM_DIR}/02 - Creature.opus"
    assert by_ref[ids["new, unknown"]].keep_path == "Encore/Nobody At All/Singles/A Song Nobody Recorded.opus"
    assert by_ref[ids["placed, not linked yet"]].keep_path is not None
    report = album_dryrun.Report(rows, album_finder.TOLERANCE_MS).render()
    assert "== NEW KEEPS" in report
    assert f"{ALBUM_DIR}/02 - Creature.opus" in report
    assert "Encore/Nobody At All/Singles/A Song Nobody Recorded.opus" in report
    assert "no_same_recording" in report.split("== NEW KEEPS")[1]


def test_a_song_that_is_not_a_new_keep_has_no_planned_path_and_is_not_in_the_section(pdb: Database, tmp_path: Path) -> None:
    ids = a_library(pdb)
    conn = open_copy(pdb)
    catalogue = landmvrks()
    rows = album_dryrun.run(
        conn, album_dryrun.entries(conn, now=test_album_pass.NOW), catalogue.search, catalogue.album, music_root=tmp_path
    )
    kept = next(row for row in rows if row.entry.ref_id == ids["kept and linked"])
    assert kept.keep_path is None and not kept.entry.new_keep
    section = album_dryrun.Report(rows, album_finder.TOLERANCE_MS).render().split("== NEW KEEPS")[1].split("\n== ")[0]
    assert "Requiem" not in section


def test_the_report_says_the_downloaded_files_length_is_not_known_before_the_keep(pdb: Database, tmp_path: Path) -> None:
    a_library(pdb)
    conn = open_copy(pdb)
    catalogue = landmvrks()
    rows = album_dryrun.run(
        conn,
        album_dryrun.entries(conn, new_keeps_only=True, now=test_album_pass.NOW),
        catalogue.search,
        catalogue.album,
        music_root=tmp_path,
    )
    section = album_dryrun.Report(rows, album_finder.TOLERANCE_MS).render().split("== NEW KEEPS")[1]
    assert "listing" in section and "downloaded file" in section, (
        "the reader must know these songs were measured by the import's listing, not by the file a keep will read"
    )


def test_with_no_new_keep_the_section_says_so(pdb: Database, tmp_path: Path) -> None:
    make_ref(pdb, "Requiem", "LANDMVRKS", 250_000)
    conn = open_copy(pdb)
    catalogue = landmvrks()
    rows = album_dryrun.run(
        conn, album_dryrun.entries(conn, now=test_album_pass.NOW), catalogue.search, catalogue.album, music_root=tmp_path
    )
    assert (
        "(no song would be a new keep)" in album_dryrun.Report(rows, album_finder.TOLERANCE_MS).render().split("== NEW KEEPS")[1]
    )


def test_the_command_has_a_new_keeps_mode(pdb: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a_library(pdb)
    answers = Path(__file__).parent / "fixtures" / "deezer"
    code = album_dryrun.main(
        ["--db", str(pdb.path), "--answers", str(answers), "--new-keeps", "--music-root", str(tmp_path)], out=lambda text: None
    )
    assert code == 0


# ------------------------------------------------------------------------------------------------------------------ what the report says is what a keep does


def test_the_report_predicts_what_the_real_keeper_does_over_the_same_database(tmp_path: Path, db: Database) -> None:
    """One definition, proved by running both: the dry run's planned path for each new keep is the path the REAL keeper files the song at."""
    krig = KeepRig(tmp_path, db)
    creature = krig.creature(duration=FILE_LENGTH_MS)
    unknown = krig.unknown()
    with (
        db.tx() as conn
    ):  # somebody likes both songs: that is why the server would keep them (and why the pass would ask about them)
        conn.execute(
            "INSERT INTO person (id, navidrome_user, display_name, role, created_at) VALUES ('pn_1','marwa','marwa','owner',0)"
        )
        for ref in (creature, unknown):
            library.set_item(conn, "pn_1", "like", ref)
    conn = open_copy(db)
    rows = album_dryrun.run(
        conn,
        album_dryrun.entries(conn, new_keeps_only=True),
        krig.catalogue.search,
        krig.catalogue.album,
        music_root=krig.music,
    )
    planned = {row.entry.ref_id: row.keep_path or "" for row in rows}
    assert set(planned) == {creature, unknown}

    krig.keep(creature)
    krig.keep(unknown)

    with db.read() as copy:
        kept = {
            ref: copy.execute("SELECT path FROM song_file WHERE ref = ?", (ref,)).fetchone()["path"]
            for ref in (creature, unknown)
        }
    assert kept[creature] == planned[creature] and kept[unknown] == planned[unknown]
    assert planned[creature] != planned[unknown] and "Singles" in planned[unknown] and "Singles" not in planned[creature]
    outcomes: dict[str, Any] = {row.entry.ref_id: row.verdict.outcome for row in rows}
    assert outcomes == {creature: "matched", unknown: "none"}


def test_a_catalogue_that_could_not_be_asked_files_a_new_keep_where_it_is_filed_today(pdb: Database, tmp_path: Path) -> None:
    """A verdict of `unavailable` writes nothing, so the report shows the folder the song has today and counts it apart from a `none`."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", FILE_LENGTH_MS, album=None, kept=None, like=True)
    conn = open_copy(pdb)
    catalogue = Catalogue(down=True)
    rows = album_dryrun.run(
        conn,
        album_dryrun.entries(conn, new_keeps_only=True, now=test_album_pass.NOW),
        catalogue.search,
        catalogue.album,
        music_root=tmp_path,
    )
    assert [(row.entry.ref_id, row.verdict.outcome, row.keep_path) for row in rows] == [
        (ref, "unavailable", "Encore/LANDMVRKS/Singles/Creature.opus")
    ]
    section = album_dryrun.Report(rows, album_finder.TOLERANCE_MS).render().split("== NEW KEEPS")[1]
    assert "the catalogue could not be asked" in section
