"""P2-25 slice 4, SECOND review round (22 Nov 2026): the rehome decides every file against ONE state, the one the music server's whole listing of THIS pass leaves.

The independent adversarial tester proved, on random worlds, that the first build did not lose a like, a file or a mapping; it also found three permanent-defect classes
that have ONE root: **a decision of the pass read state that the same pass changes** (the rows a later prune removes, the length and the ids a move wrote onto its target,
the file that arrived on a ref, the ref a move made). The tests below are the tester's probes, rebuilt by hand and kept (its throwaway files are gone), and each one
fails on the code of head 12a232a (page by page, moves enrich their target, the guard counts rows the prune removes next):

* PROBE 6 (prune order): a ref a person owns keeps its file when every OTHER file it holds is one the music server no longer lists. The hourly pass prunes those rows
  after the page that held them: the last-file guard counted them, so the listed file moved away and the like was left with no file and RELEASED from the worklist;
* SEED 7073 (a hold the rehome causes): moving a file onto a ref with no length (or no id) FILLED it, and a sibling file of another length (or with the same id) no longer
  fitted the ref at the next pass: the ref was held for good, while the uncut run released it;
* the SECOND PASS writes: a file that moves onto an owned ref frees its other wrong file only at the next pass; an id on a ref a move made names a nameless file only at the
  next pass. Each extra pass moved one more file and took one more copy of the database.

The permanent form of all three is the seeded property test in `test_rehome_worlds.py`.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from typing import Any

import pytest

from encore_server import refs, rehome
from encore_server.db import Database
from encore_server.ids import now_ms
from encore_server.link_listing import Listing
from encore_server.scanner import described, link_library
from tests.test_rehome import (
    DUP,
    LOG,
    OTHER,
    SELF,
    Music,
    add_file,
    add_ref,
    copies,
    files,
    listed,
    make_world,
    own,
    owned,
    rid,
    song,
    worklist,
)

K1 = ("كيفك إنت", "فيروز")
K2 = ("حبيتك بالصيف", "فيروز")
K3 = ("نسّم علينا الهوا", "فيروز")
K4 = ("سألوني الناس", "فيروز")


def digest(db: Database) -> str:
    """Every table the rehome and the scan write, whole: a pass that wrote nothing leaves the same digest."""
    h = hashlib.sha256()
    with db.read() as conn:
        for table in ("song_ref", "song_file", "ref_recheck", "file_log", "library_item", "ref_merge", "setting", "change_log"):
            rows = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]  # noqa: S608 - fixed names
            h.update(repr((table, rows)).encode())
    return h.hexdigest()


def with_isrc(tags: dict[str, Any], isrc: str) -> dict[str, Any]:
    return {**tags, "isrc": [isrc]}


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# PROBE 6: the guard counts only the files the music server lists in THIS pass


def probe6_world(db: Database) -> tuple[dict[str, Any], dict[str, Any]]:
    """R (SELF, a like) holds nd-2 (a file the music server no longer lists) and nd-1 (its tags name ANOTHER ref, OTHER, and SELF does not fit them)."""
    wrong = song("nd-1", *K2)
    unlisted = song("nd-2", *K1)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", added_at=100, song=wrong)
        add_file(c, SELF, "nd-2", added_at=200, song=unlisted)
        add_ref(c, OTHER, K2[0], [K2[1]], old=False, duration_ms=200_000)
        own(c, "like", SELF)

    make_world(db, build)
    listed(db, SELF)
    return wrong, unlisted


def test_probe6_the_only_listed_file_of_a_liked_song_stays_when_its_other_file_is_one_the_prune_removes_in_the_same_pass(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    """The tester's probe: the hourly pass (prune on) removes the row of nd-2 AFTER the page that held it, so the guard must not count it: nd-1 is the last file the
    song has, it stays, the like keeps a file and the song stays on the worklist (28 of 1,500 random worlds ended with the like on a song with no file and the song released)."""
    wrong, _unlisted = probe6_world(db)
    before = owned(db)

    with caplog.at_level(logging.INFO, logger=LOG):
        report = link_library(db, Music([wrong]))

    assert report.pruned == 1, "the unlisted file is pruned in this pass"
    assert files(db) == {"nd-1": (SELF,)}, "the one listed file did not move away from the song that is liked"
    assert owned(db) == before
    assert worklist(db) == {SELF}, "the song is held: it is not released with no file"
    assert report.rehome is not None and report.rehome.moved == 0 and report.rehome.stayed_last_file == 1
    assert report.rehome.released == 0 and report.rehome.held_back == 1
    assert copies(db) == [], "nothing moved, so no copy"
    assert any("last file" in r.getMessage() for r in caplog.records if r.name == LOG)


def test_probe6_back_case_a_file_the_music_server_lists_again_is_a_file_the_song_keeps_so_the_other_one_moves(
    db: Database,
) -> None:
    """The same world with nd-2 LISTED: the song keeps a file whatever happens to nd-1, so nd-1 moves to the song its tags name, the like stays, the song is released."""
    wrong, unlisted = probe6_world(db)
    before = owned(db)

    report = link_library(db, Music([wrong, unlisted]))

    assert files(db) == {"nd-1": (OTHER,), "nd-2": (SELF,)}
    assert owned(db) == before and worklist(db) == set()
    assert report.rehome is not None and report.rehome.moved == 1 and report.rehome.released == 1


def test_probe6_in_a_pass_that_only_adds_the_file_the_listing_lacks_is_no_file_either(db: Database) -> None:
    """With the prune OFF (the pass after a scan) the row of nd-2 is still there, but the pass has seen that the music server does not list it: the next pass that prunes will
    remove it. It does not count as a file the song keeps. Counting it moved nd-1 away now and left the like on a song whose only row the next hourly pass removed."""
    wrong, _unlisted = probe6_world(db)

    report = link_library(db, Music([wrong]), prune=False)

    assert files(db) == {"nd-1": (SELF,), "nd-2": (SELF,)}, "a pass that only adds removes nothing and moves nothing"
    assert worklist(db) == {SELF}
    assert report.rehome is not None and report.rehome.moved == 0 and report.rehome.stayed_last_file == 1

    link_library(db, Music([wrong]))  # the hourly pass that prunes: the like still has its file

    assert files(db) == {"nd-1": (SELF,)} and worklist(db) == {SELF}


def test_the_preferred_file_is_never_one_the_listing_lacks_in_a_pass_that_only_adds(db: Database) -> None:
    """The preference is a decision of the pass too: the song plays the file it prefers, so after a move it must not be one the music server does not list (its row is
    removed by the next pass that prunes). R holds the newest row nd-3 (not listed), a kept nd-1 and the file nd-2 that moves."""
    kept = song("nd-1", *K1)
    moves = song("nd-2", *K2)
    unlisted = song("nd-3", *K1)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", added_at=100, song=kept)
        add_file(c, SELF, "nd-2", added_at=200, song=moves)
        add_file(c, SELF, "nd-3", added_at=300, preferred=1, song=unlisted)
        add_ref(c, OTHER, K2[0], [K2[1]], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, SELF)

    link_library(db, Music([kept, moves]), prune=False)

    with db.read() as conn:
        preferred = [
            r["navidrome_song_id"]
            for r in conn.execute("SELECT navidrome_song_id FROM song_file WHERE ref = ? AND preferred = 1", (SELF,))
        ]
    assert preferred == ["nd-1"], "the file the song plays is one the music server lists"


def test_a_pass_that_finishes_what_a_killed_one_began_never_prefers_a_keepers_row_the_listing_lacks(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_prefer_a_decided_file` runs for a song that lost a file to an EARLIER pass (`ref_recheck.moved`). A keeper's row is 'decided' by its source, so only the listing can say
    that this one (not listed, in a pass that only adds: the row is still there) is gone: the song must not play it."""
    third = rid("sr", 4)
    kept = song("nd-1", *K1)
    nameless = song("nd-2", K1[0], "[Unknown Artist]")
    keeper_row = song("nd-3", *K1)
    moving = song("nd-4", *K2)
    second_move = song("nd-5", *K4)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", added_at=100, song=kept)
        add_file(c, SELF, "nd-2", added_at=200, song=nameless)
        add_file(c, SELF, "nd-3", source="youtube", added_at=300, song=keeper_row)
        add_file(c, SELF, "nd-4", added_at=400, preferred=1, song=moving)
        add_ref(c, OTHER, K2[0], [K2[1]], old=False, duration_ms=200_000)
        add_ref(c, third, K3[0], [K3[1]], old=False, duration_ms=200_000)
        add_file(c, third, "nd-5", added_at=500, song=second_move)
        add_ref(c, rid("sr", 5), K4[0], [K4[1]], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, SELF, third)
    songs = [kept, nameless, moving, second_move]  # the keeper's row nd-3 is not listed
    monkeypatch.setattr(rehome, "CHUNK", 1)
    real = rehome.Rehome._move  # noqa: SLF001
    calls: list[str] = []

    def dying(self: rehome.Rehome, conn: sqlite3.Connection, file_id: str, ref: str, described_: dict[str, Any] | None) -> Any:
        calls.append(file_id)
        if len(calls) == 2:
            raise RuntimeError("the process was killed here")
        return real(self, conn, file_id, ref, described_)

    monkeypatch.setattr(rehome.Rehome, "_move", dying)
    link_library(db, Music(songs), prune=False)
    monkeypatch.undo()
    assert files(db)["nd-4"] == (OTHER,) and files(db)["nd-5"] == (third,)

    link_library(db, Music(songs), prune=False)

    with db.read() as conn:
        preferred = [
            r["navidrome_song_id"]
            for r in conn.execute("SELECT navidrome_song_id FROM song_file WHERE ref = ? AND preferred = 1", (SELF,))
        ]
    assert preferred == ["nd-1"]


def test_the_target_of_a_move_prefers_a_file_the_listing_has_in_a_pass_that_only_adds(db: Database) -> None:
    """The same rule for the song a file ARRIVES on: it holds the row u (newest, not listed, prefers nothing yet) and the file that moves onto it is older. The rule of
    `ensure_one_preferred` (the newest when none is preferred) chose u, a row the next pass that prunes removes: the song would have played a file that is not there."""
    moving = song("nd-1", *K1)
    unlisted = song("nd-3", *K1)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-3", added_at=900, preferred=0, song=unlisted)
        add_ref(c, OTHER, K2[0], [K2[1]], old=False, duration_ms=200_000)
        add_file(c, OTHER, "nd-1", added_at=100, song=moving)

    make_world(db, build)
    listed(db, OTHER)

    link_library(db, Music([moving]), prune=False)

    assert files(db)["nd-1"] == (SELF,)
    with db.read() as conn:
        preferred = [
            r["navidrome_song_id"]
            for r in conn.execute("SELECT navidrome_song_id FROM song_file WHERE ref = ? AND preferred = 1", (SELF,))
        ]
    assert preferred == ["nd-1"]


@pytest.mark.parametrize("other_file", ["no music server id", "attached after the pass began"])
def test_a_file_with_no_music_server_id_or_attached_since_the_pass_began_is_a_file_the_song_keeps(
    db: Database, other_file: str
) -> None:
    """The prune leaves these rows alone, so the song keeps them: nd-1 is NOT its last file and moves. (Counting only the ids the listing holds would call them gone.)"""
    wrong = song("nd-1", *K2)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", added_at=100, song=wrong)
        add_ref(c, OTHER, K2[0], [K2[1]], old=False, duration_ms=200_000)
        own(c, "like", SELF)
        c.execute(
            "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, bitrate_kbps, source, preferred, added_at, meta) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
            (
                "sf_keeper",
                SELF,
                None if other_file == "no music server id" else "nd-9",
                "Encore/keeper.opus",
                "opus",
                128,
                "youtube",
                0,
                100 if other_file == "no music server id" else now_ms() + 3_600_000,
            ),
        )

    make_world(db, build)
    listed(db, SELF)

    report = link_library(db, Music([wrong]))

    assert files(db)["nd-1"] == (OTHER,), "the song keeps the keeper's file, so the wrong one may go"
    assert report.rehome is not None and report.rehome.moved == 1 and report.rehome.stayed_last_file == 0


def test_a_listing_says_which_rows_are_alive() -> None:
    """The one definition (`link_listing.Listing.alive`): the music server lists the id, or the row was attached after the pass began, or it has no music server id."""
    listing_ = Listing.of([{"id": "nd-1"}, {"id": ""}, {"title": "no id"}], began=1000)
    assert listing_.complete and listing_.seen == {"nd-1"}
    assert listing_.alive("nd-1", 5) is True, "listed"
    assert listing_.alive("nd-2", 5) is False, "not listed, and older than the pass: gone"
    assert listing_.alive("nd-2", 1000) is True and listing_.alive("nd-2", 5000) is True, (
        "attached since the pass began: the prune leaves it alone"
    )
    assert listing_.alive(None, 5) is True, "no music server id: the prune cannot remove it"


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# SEED 7073: the rehome never writes what the next decision reads (a ref's length and ids)


def length_world(db: Database) -> dict[str, dict[str, Any]]:
    """T (SELF, NO length) holds f2 (260 s of K1); R (OTHER) holds f1 (200 s of K1: a move onto T, which has no length to disagree) and z holds f3 (a move to X4)."""
    tags = {
        "f1": song("nd-1", *K1, 200.0),
        "f2": song("nd-2", *K1, 260.0),
        "f3": song("nd-3", *K4, 200.0),
    }
    z, x4 = rid("sr", 4), rid("sr", 5)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=None)
        add_file(c, SELF, "nd-2", added_at=300, song=tags["f2"])
        add_ref(c, OTHER, K2[0], [K2[1]], old=False, duration_ms=200_000)
        add_file(c, OTHER, "nd-1", added_at=100, song=tags["f1"])
        add_ref(c, z, K3[0], [K3[1]], old=False, duration_ms=200_000)
        add_file(c, z, "nd-3", added_at=200, song=tags["f3"])
        add_ref(c, x4, K4[0], [K4[1]], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, SELF, OTHER, z)
    return tags


def test_a_pass_cut_by_the_music_server_then_resumed_ends_where_the_uncut_pass_ends_a_length_the_rehome_wrote_decides_nothing(
    db: Database, tmp_path: Any
) -> None:
    """THE seed-7073 shape. Uncut: f2 (260 s) fits T while T has no length, f1 moves onto T, T is released. Cut after the page with f1 and resumed: the first build had moved
    f1 already and FILLED T's length (200 s), so f2 no longer fitted T at the next pass and T was held for good by a hold only the rehome's own write made. Now a pass that did
    not see the whole listing decides and writes nothing."""
    tags = length_world(db)
    uncut = Database(tmp_path / "uncut" / "encore.db")
    uncut.migrate()
    length_world(uncut)
    link_library(uncut, Music([tags["f1"], tags["f3"], tags["f2"]]), page=1)

    cut = link_library(db, Music([tags["f1"], tags["f3"], tags["f2"]], down_at=2), page=1)
    assert cut.complete is False and cut.rehome is None
    assert files(db)["nd-1"] == (OTHER,), "an incomplete pass moves nothing"
    link_library(db, Music([tags["f1"], tags["f3"], tags["f2"]]), page=1)

    assert worklist(db) == worklist(uncut) == set()
    assert files(db) == files(uncut)
    assert files(db)["nd-1"] == (SELF,) and files(db)["nd-2"] == (SELF,), "both files of the song are on it, and it is released"


def test_a_pass_killed_between_two_chunks_of_moves_then_resumed_ends_where_the_uncut_pass_ends(
    db: Database, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The same hold, by the other road: the process dies after the first chunk of moves was committed. A move onto a ref must not change what the next file is judged by
    (the length and the ids of the ref), or the resumed pass finds a world the uncut pass never saw."""
    tags = length_world(db)
    listing_ = [tags["f1"], tags["f3"], tags["f2"]]
    uncut = Database(tmp_path / "uncut" / "encore.db")
    uncut.migrate()
    length_world(uncut)
    link_library(uncut, Music(listing_))

    monkeypatch.setattr(rehome, "CHUNK", 1, raising=False)
    real = rehome.Rehome._move  # noqa: SLF001
    calls: list[str] = []

    def dying(self: rehome.Rehome, conn: sqlite3.Connection, file_id: str, ref: str, song_: dict[str, Any]) -> Any:
        calls.append(file_id)
        if len(calls) == 2:
            raise RuntimeError("the process was killed here")
        return real(self, conn, file_id, ref, song_)

    monkeypatch.setattr(rehome.Rehome, "_move", dying)
    killed = link_library(db, Music(listing_))
    monkeypatch.undo()

    assert killed.rehome is not None and killed.rehome.failed and killed.rehome.moved == 1, (
        "the report counts the chunk that committed"
    )
    assert worklist(db) == {SELF, OTHER, rid("sr", 4)}, "a pass that failed released nothing"
    link_library(db, Music(listing_))

    assert worklist(db) == worklist(uncut) == set(), "f2 still fits T: its length is the one it had"
    assert files(db) == files(uncut)


@pytest.mark.parametrize("column", ["duration_ms", "isrc"])
def test_a_move_onto_a_song_never_writes_its_length_or_its_ids_but_fills_what_is_only_description(
    db: Database, column: str
) -> None:
    """The facts `refs.candidates` matches by (the length, the three ids) are what the NEXT file is judged by, so the rehome never writes them on a song that exists. What a file's
    tags add as plain description (the album, the year, the track number) still fills a gap, as a scan would."""
    tags = {**song("nd-1", *K1, 200.0, isrc=["QZ1234567890"], album="Album of the file", year=2001, track=3)}

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=None)
        add_ref(c, OTHER, K2[0], [K2[1]], old=False, duration_ms=200_000)
        add_file(c, OTHER, "nd-1", song=tags)

    make_world(db, build)
    listed(db, OTHER)

    report = link_library(db, Music([tags]))

    assert files(db) == {"nd-1": (SELF,)} and report.rehome is not None and report.rehome.moved == 1
    with db.read() as conn:
        row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (SELF,)).fetchone()
    assert row[column] is None, f"{column} is the ref's own, the file's tags do not write it"
    assert row["album"] == "Album of the file" and row["year"] == 2001 and row["track_no"] == 3


def test_a_move_to_a_song_that_does_not_exist_makes_it_with_the_whole_description_of_the_file(db: Database) -> None:
    """The ref a move MAKES is described by its own file in full (a new ref cannot disagree with anything): the length and the id are what the next file is judged by."""
    tags = song("nd-1", *K2, 200.0, isrc=["QZ1234567890"])

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", song=tags)

    make_world(db, build)
    listed(db, SELF)

    link_library(db, Music([tags]))

    (made,) = files(db)["nd-1"]
    assert made != SELF
    with db.read() as conn:
        row = conn.execute("SELECT duration_ms, isrc FROM song_ref WHERE id = ?", (made,)).fetchone()
    assert (row["duration_ms"], row["isrc"]) == (200_000, "QZ1234567890")


def test_two_files_that_move_to_the_same_new_song_make_one_song_and_the_report_counts_one(db: Database) -> None:
    """Both files are judged before either moved (they name a song that does not exist yet); the first move makes it and the second finds it. The report said two new songs."""
    a, b = song("nd-1", *K2, 200.0), song("nd-2", *K2, 201.0)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", added_at=100, song=a)
        add_file(c, SELF, "nd-2", added_at=200, song=b)

    make_world(db, build)
    listed(db, SELF)

    report = link_library(db, Music([a, b]))

    assert report.rehome is not None and report.rehome.moved == 2 and report.rehome.new_refs == 1
    assert files(db)["nd-1"] == files(db)["nd-2"]


def test_which_of_two_wrong_files_of_an_owned_song_stays_does_not_depend_on_the_order_of_the_listing(tmp_path: Any) -> None:
    """Two wrong files on a liked song that holds nothing else: one of them goes, the other is then the LAST file and stays. It is always the same one (the OLDEST goes: the
    pass judges oldest first, whatever the order the music server lists them in)."""
    outcomes = []
    for n, order in enumerate((("nd-1", "nd-2"), ("nd-2", "nd-1"))):
        db = Database(tmp_path / f"o{n}" / "encore.db")
        db.migrate()
        first, second = song("nd-1", *K2), song("nd-2", *K4)
        z1, z2 = rid("sr", 4), rid("sr", 5)

        def build(
            c: sqlite3.Connection, first: dict[str, Any] = first, second: dict[str, Any] = second, z1: str = z1, z2: str = z2
        ) -> None:
            add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
            add_file(c, SELF, "nd-1", added_at=100, song=first)
            add_file(c, SELF, "nd-2", added_at=200, song=second)
            add_ref(c, z1, K2[0], [K2[1]], old=False, duration_ms=200_000)
            add_ref(c, z2, K4[0], [K4[1]], old=False, duration_ms=200_000)
            own(c, "like", SELF)

        make_world(db, build)
        listed(db, SELF)
        by_id = {"nd-1": first, "nd-2": second}
        link_library(db, Music([by_id[nd] for nd in order]))
        outcomes.append(files(db))
    assert outcomes[0] == outcomes[1] == {"nd-1": (rid("sr", 4),), "nd-2": (SELF,)}


def test_the_rehome_refuses_to_decide_on_a_listing_that_is_not_complete(db: Database) -> None:
    """The verdict of a file depends on the files the music server lists in the REST of the pass, so `finish` on a listing the pass did not finish reading is a mistake of the
    caller, not a pass: it raises and writes nothing."""
    tags = song("nd-1", *K2)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", song=tags)
        add_ref(c, OTHER, K2[0], [K2[1]], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, SELF)
    work = rehome.begin(db, described, Listing(began=now_ms()))
    assert work is not None
    work.page([tags])

    with pytest.raises(RuntimeError, match="not complete"):
        work.finish()

    assert files(db) == {"nd-1": (SELF,)} and worklist(db) == {SELF} and copies(db) == []


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the SECOND PASS writes nothing: what a move frees is decided in the same pass


def freed_world(db: Database) -> tuple[dict[str, Any], dict[str, Any]]:
    """T (SELF, a like) holds f2, which names X (OTHER) and is T's only file; R (DUP, unowned) holds f1, which names T. Judged together, f2 is T's LAST file and stays; once f1
    has moved onto T it is not, and the first build moved it only at the NEXT pass (a second copy of the database, a second write)."""
    f1, f2 = song("nd-1", *K1), song("nd-2", *K2)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-2", added_at=200, song=f2)
        add_ref(c, DUP, K3[0], [K3[1]], old=False, duration_ms=200_000)
        add_file(c, DUP, "nd-1", added_at=100, song=f1)
        add_ref(c, OTHER, K2[0], [K2[1]], old=False, duration_ms=200_000)
        own(c, "like", SELF)

    make_world(db, build)
    listed(db, SELF, DUP)
    return f1, f2


def test_a_file_that_moves_onto_an_owned_song_frees_its_other_wrong_file_in_the_same_pass_and_the_second_pass_writes_nothing(
    db: Database,
) -> None:
    f1, f2 = freed_world(db)
    before = owned(db)

    first = link_library(db, Music([f1, f2]))

    assert files(db) == {"nd-1": (SELF,), "nd-2": (OTHER,)}, "both files are where their tags say after ONE pass"
    assert worklist(db) == set() and owned(db) == before
    assert first.rehome is not None and first.rehome.moved == 2 and first.rehome.rounds == 2
    assert len(copies(db)) == 1
    state = digest(db)

    second = link_library(db, Music([f1, f2]))

    assert digest(db) == state, "a second pass over an unchanged catalogue writes nothing"
    assert len(copies(db)) == 1, "and takes no copy"
    assert second.rehome is None, "the worklist is empty"


def test_an_id_on_a_song_a_move_made_names_a_nameless_file_in_the_same_pass(db: Database) -> None:
    """f_n has the placeholder artist and an ISRC nobody holds: judged by ids only, it stays. f_m moves to a song that does not exist yet and MAKES it with that ISRC (its tags
    carry it too): the same recording by id, so f_n belongs there; the first build saw it only at the next pass."""
    nameless = song("nd-1", K3[0], "[Unknown Artist]", 200.0, isrc=["QZ1234567890"])
    named = song("nd-2", *K2, 200.0, isrc=["QZ1234567890"])
    z = rid("sr", 4)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", added_at=100, song=nameless)
        add_ref(c, z, K4[0], [K4[1]], old=False, duration_ms=200_000)
        add_file(c, z, "nd-2", added_at=200, song=named)

    make_world(db, build)
    listed(db, SELF, z)

    first = link_library(db, Music([nameless, named]))

    assert files(db)["nd-1"] == files(db)["nd-2"] and files(db)["nd-1"] not in ((SELF,), (z,))
    assert worklist(db) == set()
    assert first.rehome is not None and first.rehome.moved == 2
    state = digest(db)

    link_library(db, Music([nameless, named]))

    assert digest(db) == state and len(copies(db)) == 1


def chain_world(db: Database, *, links: int) -> list[dict[str, Any]]:
    """A chain of `links` files that each free the next one. Song n holds ONE file, nd-n, whose tags name song n+1 (the last one names a song that holds nothing). Song 0 is
    nobody's, so its file is free to move at once; songs 1.. are liked, so their file is the LAST one the song has until the file before it arrives. Judged against one state
    only nd-0 can move; every move frees the next one: `links` rounds."""
    names = [(f"song {n}", "فيروز") for n in range(links + 1)]
    tags = [song(f"nd-{n}", *names[n + 1]) for n in range(links)]

    def build(c: sqlite3.Connection) -> None:
        for n in range(links + 1):
            add_ref(c, rid("sr", n + 1), names[n][0], [names[n][1]], old=False, duration_ms=200_000)
        for n in range(links):
            add_file(c, rid("sr", n + 1), f"nd-{n}", added_at=100 + n, song=tags[n])
            if n >= 1:
                own(c, "like", rid("sr", n + 1))

    make_world(db, build)
    listed(db, *(rid("sr", n + 1) for n in range(links)))
    return tags


@pytest.mark.parametrize("links", [3, 5])
def test_a_chain_of_files_that_each_free_the_next_is_finished_in_one_pass_and_the_second_pass_writes_nothing(
    db: Database, links: int
) -> None:
    tags = chain_world(db, links=links)

    first = link_library(db, Music(list(reversed(tags))))  # the listing order is the worst one

    assert files(db) == {f"nd-{n}": (rid("sr", n + 2),) for n in range(links)}, "every file is on the song its tags name"
    assert worklist(db) == set()
    assert first.rehome is not None and first.rehome.rounds == links, "one round per link of the chain, and no more"
    state = digest(db)

    link_library(db, Music(tags))

    assert digest(db) == state and len(copies(db)) == 1


def test_a_chain_longer_than_the_cap_stops_with_a_line_and_the_next_pass_goes_on_so_the_cap_costs_a_pass_and_loses_nothing(
    db: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The rounds end by themselves (a file moves at most once in a pass, so there are at most as many rounds as files plus one); the cap is a second layer. When it is reached
    the pass says so, writes what it has, keeps the songs that are not decided on the worklist, and the next pass finishes."""
    tags = chain_world(db, links=5)
    monkeypatch.setattr(rehome, "MAX_ROUNDS", 2, raising=False)

    with caplog.at_level(logging.ERROR, logger=LOG):
        first = link_library(db, Music(tags))

    assert first.rehome is not None and first.rehome.rounds == 2
    assert any("rounds" in r.getMessage() for r in caplog.records if r.name == LOG)
    assert len(worklist(db)) >= 1 and files(db)["nd-4"] == (rid("sr", 5),), "what is not decided is held"
    monkeypatch.undo()

    link_library(db, Music(tags))
    link_library(db, Music(tags))

    assert files(db) == {f"nd-{n}": (rid("sr", n + 2),) for n in range(5)} and worklist(db) == set()


def test_the_outcome_of_one_pass_never_depends_on_the_size_of_a_page_or_the_order_of_the_listing(tmp_path: Any) -> None:
    """The verdicts are those of ONE state: the page size and the order of the listing decide nothing (the first build judged a page at a time, after the writes of the
    pages before it)."""
    outcomes = []
    for n, page in enumerate((1, 2, 500)):
        other = Database(tmp_path / f"p{n}" / "encore.db")
        other.migrate()
        f1, f2 = freed_world(other)
        link_library(other, Music([f2, f1]), page=page)
        outcomes.append((files(other), worklist(other)))
    assert outcomes[0] == outcomes[1] == outcomes[2]
    assert outcomes[0][0] == {"nd-1": (SELF,), "nd-2": (OTHER,)}


def test_the_rehome_does_not_use_a_ref_only_it_made_as_evidence_against_a_file_judged_before(db: Database) -> None:
    """The ref a move makes carries the id of its file: another file of the song named by the SAME name whose own ref fits it by name is KEPT (judged against the state before the
    move), not held for good because an id appeared meanwhile."""
    moving = song("nd-1", *K2, 200.0, isrc=["QZ1234567890"])
    sibling = song("nd-2", *K1, 200.0, isrc=["QZ1234567890"])

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-2", added_at=300, song=sibling)
        add_ref(c, DUP, K3[0], [K3[1]], old=False, duration_ms=200_000)
        add_file(c, DUP, "nd-1", added_at=100, song=moving)

    make_world(db, build)
    listed(db, SELF, DUP)

    link_library(
        db, Music([moving, sibling]), page=1
    )  # the file that makes the song is on the page BEFORE the file that is judged against it

    assert worklist(db) == set(), "SELF fits its file by name: kept, released"
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_file WHERE ref = ?", (SELF,)).fetchone()[0] == 1
        assert refs.ref_exists(conn, SELF)
