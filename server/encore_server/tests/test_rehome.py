"""P2-25 slice 4 (audit B-37): the REHOME (`rehome.py`), the one-time repair of the files the old text fold glued onto the wrong song.

Until P2-25 a Host's library in Arabic, Russian, Korean or Japanese collapsed: every file whose name folded to nothing was found by the key `||`, `attach_file` obeyed,
and ONE ref held five files of five different songs. The start-up rekey (slice 3, `keyrepair.py`) gives every ref its right key and lists the damaged ones on the
worklist `ref_recheck`; this slice judges their library files by their tags in the hourly library link and RE-POINTS the ones that belong to another song.

The data is SYNTHETIC and built the way the OLD server built it (the stored keys are `tests/legacy_fold.py`'s), then repaired by the real `keyrepair`, so a test here can
only pass by doing what the rehome is for. The music server is a fake with the seven tagged files of `docs/evidence/scripts/audit_stack.py` (three Arabic songs of one
artist, two Russian of another, two Latin) and lengths within three seconds of the first, which is exactly why the old scan glued five of them onto one ref.

What the tests protect, in the owner's words: the five files hang on five songs, and NOTHING A PERSON OWNS MOVED (a like, a playlist entry, a play, the saved queue stay
on the ref that holds them); the Host's own music folder is never touched; one copy of the database before the first move; the worklist is emptied only by a complete
pass; a second pass moves nothing.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server import keyrepair, library, refmerge, refs, rehome, repair_copy, textnorm
from encore_server.db import Database
from encore_server.ids import now_ms
from encore_server.link_listing import Listing
from encore_server.navidrome import file_meta
from encore_server.ref_janitor import AGE_MS, RefJanitor
from encore_server.scanner import LinkReport, described, link_library
from tests import legacy_fold as legacy
from tests.conftest import creds
from tests.test_ref_merge import everything_listed

V1 = "/encore/api/v1"
LOG = "encore_server.rehome"


def rid(prefix: str, n: int) -> str:
    return f"{prefix}_{n:026d}"


ME, YOU = rid("pn", 1), rid("pn", 2)
PLAYLIST = rid("pl", 1)
# R is the ref the old scan made for the first Arabic file and then glued FOUR more files onto (key `||`); the Radiohead refs are Latin and were never damaged.
R, FISHES, RECKONER = rid("sr", 1), rid("sr", 2), rid("sr", 3)

# (the music server's id, title, artist, album, seconds): the library of `audit_stack.py`, five non-Latin files within three seconds of each other
TRACKS = [
    ("nd-1", "كيفك إنت", "فيروز", "كيفك إنت", 10.0),
    ("nd-2", "نسّم علينا الهوا", "فيروز", "كيفك إنت", 11.5),
    ("nd-3", "حبيتك بالصيف", "فيروز", "كيفك إنت", 11.0),
    ("nd-4", "Группа крови", "Кино", "Группа крови", 12.0),
    ("nd-5", "Кукушка", "Кино", "Группа крови", 12.5),
    ("nd-6", "Weird Fishes", "Radiohead", "In Rainbows", 14.0),
    ("nd-7", "Reckoner", "Radiohead", "In Rainbows", 18.0),
]


def listing(**extra: dict[str, Any]) -> list[dict[str, Any]]:
    """What the music server lists for the seven files; `extra` overrides fields of one id (`extra={"nd-2": {"isrc": [...]}}`)."""
    songs = []
    for n, (nd, title, artist, album, seconds) in enumerate(TRACKS, start=1):
        songs.append(
            {
                "id": nd,
                "title": title,
                "artist": artist,
                "album": album,
                "albumId": f"al-{album}",
                "duration": seconds,
                "path": f"Collection/{artist}/{album}/{n:02d}.opus",
                "suffix": "opus",
                "size": 1000 * n,
                "bitRate": 128,
                **extra.get(nd, {}),
            }
        )
    return songs


class Music:
    """The music server: pages of songs; `down_at` is the number of the call (from 1) that gets no answer, as when the music server restarts in the middle of a pass."""

    def __init__(self, songs: list[dict[str, Any]], *, down_at: int | None = None) -> None:
        self.songs_ = songs
        self.down_at = down_at
        self.calls = 0

    def songs(self, offset: int, size: int = 500) -> list[dict[str, Any]] | None:
        self.calls += 1
        if self.down_at is not None and self.calls == self.down_at:
            return None
        return self.songs_[offset : offset + size]


# ------------------------------------------------------------------------------------------------------------------------------ the old world


def add_ref(conn: sqlite3.Connection, ref: str, title: str, artists: list[str], *, old: bool = True, **fields: Any) -> None:
    """A ref as the code of the time stored it: with the OLD fold's key by default (`old=False`: the key the fold makes now)."""
    key = legacy.norm_key(artists[0], title) if old else refs.norm_key(artists[0], title)
    conn.execute(
        "INSERT INTO song_ref (id, title, artists, album, duration_ms, isrc, norm_key, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            ref,
            title,
            json.dumps(artists, ensure_ascii=False),
            fields.get("album"),
            fields.get("duration_ms"),
            fields.get("isrc"),
            key,
            fields.get("created_at", 1000 + int(ref[3:])),
        ),
    )


def add_file(
    conn: sqlite3.Connection,
    ref: str,
    nd: str,
    *,
    source: str = "library",
    added_at: int | None = None,
    preferred: int = 0,
    song: dict[str, Any] | None = None,
) -> str:
    """A `song_file` row as the scan wrote it: the music server's id, its path, and the facts of the listing as `meta`."""
    song = song or next(s for s in listing() if s["id"] == nd)
    file_id = f"sf_{int(ref[3:]):013d}{int(nd.split('-')[1]):013d}"
    conn.execute(
        "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, bitrate_kbps, source, preferred, added_at, meta) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            file_id,
            ref,
            nd,
            song["path"],
            "opus",
            128,
            source,
            preferred,
            added_at if added_at is not None else 5000 + int(nd.split("-")[1]),
            json.dumps(file_meta(song), separators=(",", ":"), sort_keys=True),
        ),
    )
    return file_id


def seed_old_world(db: Database) -> None:
    """The library as the old scan left it, plus what people did with it."""
    with db.tx() as c:
        for person, name in ((ME, "ana"), (YOU, "ben")):
            c.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES (?,?,?,1)", (person, name, name))
        add_ref(c, R, "كيفك إنت", ["فيروز"], album="كيفك إنت", duration_ms=10_000)
        for nd in ("nd-1", "nd-2", "nd-3", "nd-4"):
            add_file(c, R, nd)
        add_file(c, R, "nd-5", preferred=1)  # the newest is the preferred one: the file the phone plays, and the one that moves
        add_ref(c, FISHES, "Weird Fishes", ["Radiohead"], album="In Rainbows", duration_ms=14_000)
        add_file(c, FISHES, "nd-6", preferred=1)
        add_ref(c, RECKONER, "Reckoner", ["Radiohead"], album="In Rainbows", duration_ms=18_000)
        add_file(c, RECKONER, "nd-7", preferred=1)
        for ref in (
            R,
            FISHES,
            RECKONER,
        ):  # the old scan told the phones about each file it attached (the feed a phone that synced then holds)
            refs.touch_file(c, ref)
        # what people own: every one of these stays exactly where it is
        for who in (ME, YOU):
            library.set_item(c, who, "like", R)
        library.set_item(c, ME, "like", FISHES)
        c.execute("INSERT INTO playlist (id, owner, name, created_at, updated_at) VALUES (?,?,?,1,1)", (PLAYLIST, ME, "mine"))
        for n, ref in enumerate((R, FISHES), start=1):
            c.execute(
                "INSERT INTO playlist_entry (id, playlist, position, ref, added_by, at) VALUES (?,?,?,?,?,1)",
                (rid("pe", n), PLAYLIST, n, ref, ME),
            )
        for n, ref in enumerate((R, R, FISHES), start=1):
            c.execute(
                "INSERT INTO play_event (id, person, ref, at, ms_played) VALUES (?,?,?,?,1000)", (rid("pv", n), ME, ref, 100 + n)
            )
        c.execute(
            "INSERT INTO playback_state (person, ref, position_ms, queue, idx, updated_at) VALUES (?,?,?,?,?,1)",
            (ME, R, 4000, json.dumps([R, FISHES, R]), 2),
        )
        c.execute("INSERT INTO saved_album_ref (person, album, ref) VALUES (?, 'cat:1', ?)", (ME, R))


@pytest.fixture()
def old_world(db: Database) -> Database:
    """The old world, repaired by the REAL slice 3: new keys, and `R` on the worklist (it holds five library files of five songs)."""
    seed_old_world(db)
    assert keyrepair.repair(db).ran is True
    assert worklist(db) == {R}
    return db


def worklist(db: Database) -> set[str]:
    with db.read() as conn:
        return {r["ref"] for r in conn.execute("SELECT ref FROM ref_recheck")}


OWNED = (
    "library_item",
    "playlist",
    "playlist_entry",
    "play_event",
    "playback_state",
    "saved_album_ref",
    "import_entry",
    "work_item",
)


def owned(db: Database) -> dict[str, list[tuple[Any, ...]]]:
    """Everything a person owns, whole: it must be the same after the rehome, to the last column."""
    with db.read() as conn:
        return {table: [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")] for table in OWNED}  # noqa: S608 - fixed names


def files(db: Database) -> dict[str, tuple[str, ...]]:
    """`{music server id: the refs that hold it}`."""
    with db.read() as conn:
        found: dict[str, list[str]] = {}
        for row in conn.execute("SELECT navidrome_song_id AS nd, ref FROM song_file ORDER BY nd, ref"):
            found.setdefault(row["nd"], []).append(row["ref"])
    return {nd: tuple(held) for nd, held in found.items()}


def ref_of(db: Database, nd: str) -> str:
    (ref,) = files(db)[nd]
    return ref


def one_pass(db: Database, songs: list[dict[str, Any]] | None = None, **kwargs: Any) -> LinkReport:
    return link_library(db, Music(songs if songs is not None else listing()), **kwargs)


def judge(db: Database, songs: list[dict[str, Any]], *, release: bool = False) -> rehome.Report:
    """What a pass does with this COMPLETE listing in hand: begin, note the page, finish (the rehome decides only at the end of a complete listing, `rehome.py`)."""
    work = rehome.begin(db, described, Listing.of(songs, began=now_ms()))
    assert work is not None
    work.page(songs)
    return work.finish(release=release)


def copies(db: Database) -> list[Path]:
    return db.copies("before-rehome")


def setting(db: Database, key: str) -> str | None:
    with db.read() as conn:
        return repair_copy.setting(conn, key)


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the acceptance: five files, five songs


def test_the_world_is_what_the_old_fold_made(old_world: Database) -> None:
    """The setup itself: the damage is really there and the slice 3 repair has listed it (so the tests below can only pass by repairing it)."""
    assert len({ref for ref in files(old_world).values()}) == 3, "seven files hang on three songs: five on one"
    assert files(old_world)["nd-4"] == (R,)
    with old_world.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_file WHERE ref = ?", (R,)).fetchone()[0] == 5
        assert conn.execute("SELECT moved FROM ref_recheck WHERE ref = ?", (R,)).fetchone()["moved"] == 0
    assert setting(old_world, "textnorm_revision") is not None


def test_five_files_that_hung_on_one_song_hang_on_five_songs_after_one_link(old_world: Database) -> None:
    """THE acceptance of the slice (design part 11, row 4): after one pass of the library link the five Arabic and Russian files hang on five songs, and every song of
    the library is its own ref: `refs.find` on each file's tags names the ref that holds it."""
    report = one_pass(old_world)

    assert report.complete is True and report.rehome is not None
    holders = files(old_world)
    assert all(len(held) == 1 for held in holders.values()), "one row per file of the music server, none twice"
    assert len({held[0] for nd, held in holders.items() if nd in ("nd-1", "nd-2", "nd-3", "nd-4", "nd-5")}) == 5, (
        "five files, five songs"
    )
    assert len({held[0] for held in holders.values()}) == 7
    assert holders["nd-1"] == (R,), "the first file, the one the ref was made for, stays"
    assert holders["nd-6"] == (FISHES,) and holders["nd-7"] == (RECKONER,), "a Latin library is not touched"
    with old_world.read() as conn:
        for song in listing():
            found = refs.find(conn, refs.parse_item(described(song)))
            assert found is not None and (found["id"],) == holders[song["id"]], song["id"]
    assert report.rehome.moved == 4 and report.rehome.new_refs == 4


# Every shape of the damage the old fold made, each as ONE ref that holds several files of different songs (the premise is asserted from the frozen old fold, not assumed):
# fully non-Latin in four alphabets; a Latin artist with Latin start and different Arabic tails; two artists whose names differ only by a letter the old fold dropped.
SHAPES: dict[str, list[tuple[str, str]]] = {
    "fully non-Latin (Arabic, Cyrillic, Korean, Japanese)": [
        ("فيروز", "كيفك إنت"),
        ("فيروز", "نسّم علينا الهوا"),
        ("فيروز", "حبيتك بالصيف"),
        ("Кино", "Группа крови"),
        ("Кино", "Звезда по имени Солнце"),
        ("방탄소년단", "봄날"),
        ("방탄소년단", "피 땀 눈물"),
        ("宇多田ヒカル", "初恋"),
        ("宇多田ヒカル", "夜に駆ける"),
    ],
    "a Latin artist, a Latin start and two different Arabic tails": [("Fairuz", "Habibi يا نور"), ("Fairuz", "Habibi يا قلبي")],
    "two artists that differ only by a letter the old fold dropped": [("Łukasz", "Łódź"), ("Ukasz", "Odz")],
}


@pytest.mark.parametrize("shape", list(SHAPES))
def test_every_shape_of_the_damage_is_split_into_one_ref_per_file_and_find_names_each_holder(db: Database, shape: str) -> None:
    """The acceptance in four alphabets and two more shapes: several songs that shared ONE ref under the old fold, each with its own library file, hang on one ref each
    after the repair, and `refs.find` on each file's tags names the ref that holds it (so a phone, the scan and the next pass agree)."""
    songs = SHAPES[shape]
    assert len({legacy.norm_key(artist, title) for artist, title in songs}) == 1, (
        "the premise: the OLD fold made ONE key of them all"
    )
    glued = rid("sr", 1)
    tags = [song(f"nd-{n}", title, artist, 200.0 + n) for n, (artist, title) in enumerate(songs, start=1)]
    with db.tx() as c:
        c.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES (?,?,?,1)", (ME, "ana", "ana"))
        add_ref(c, glued, songs[0][1], [songs[0][0]], duration_ms=200_000)
        for n, tag in enumerate(tags, start=1):
            add_file(c, glued, tag["id"], added_at=5000 + n, preferred=int(n == len(tags)), song=tag)
        library.set_item(c, ME, "like", glued)
    assert keyrepair.repair(db).ran is True and worklist(db) == {glued}
    before = owned(db)

    report = link_library(db, Music(tags))

    assert report.rehome is not None and report.rehome.moved == len(songs) - 1 and report.rehome.failed is False
    holders = files(db)
    assert all(len(held) == 1 for held in holders.values())
    assert len({held[0] for held in holders.values()}) == len(songs), "one song per file"
    assert holders["nd-1"] == (glued,), "the song the ref was made for keeps its file"
    with db.read() as conn:
        for tag in tags:
            found = refs.find(conn, refs.parse_item(described(tag)))
            assert found is not None and (found["id"],) == holders[tag["id"]], tag["id"]
    assert owned(db) == before, "the like stays on the ref that held it"
    assert worklist(db) == set()


def test_the_worklist_is_empty_and_a_second_pass_moves_nothing_and_leaves_one_row_per_file(old_world: Database) -> None:
    """Idempotent, and the scan does not put the file back: it attaches by the ref that holds the row now, so there is exactly ONE row per file of the music server."""
    one_pass(old_world)
    assert worklist(old_world) == set()
    after_one = (files(old_world), owned(old_world))
    with old_world.read() as conn:
        rows = [tuple(r) for r in conn.execute("SELECT * FROM song_file ORDER BY id")]
        refs_before = conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0]

    again = one_pass(old_world)

    assert again.rehome is None, "an empty worklist costs the pass nothing: there is no rehome to run"
    with old_world.read() as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM song_file ORDER BY id")] == rows
        assert conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0] == refs_before
    assert (files(old_world), owned(old_world)) == after_one
    assert all(len(held) == 1 for held in files(old_world).values())


def test_a_file_keeps_its_row_id_when_it_moves_and_so_its_added_at_meta_and_source(old_world: Database) -> None:
    """A delete and a re-attach would lose them and open a window in which the files feed says `file: null` and a phone could drop a download."""
    with old_world.read() as conn:
        before = {r["navidrome_song_id"]: tuple(r) for r in conn.execute("SELECT * FROM song_file")}

    one_pass(old_world)

    with old_world.read() as conn:
        after = {r["navidrome_song_id"]: r for r in conn.execute("SELECT * FROM song_file")}
    assert set(after) == set(before)
    for nd, row in after.items():
        old = before[nd]
        keep = [i for i, column in enumerate(row.keys()) if column not in ("ref", "preferred")]
        assert [tuple(row)[i] for i in keep] == [old[i] for i in keep], (
            f"{nd}: only the ref (and which file is preferred) may differ"
        )
    assert after["nd-5"]["ref"] != R, "the file the phone plays on R is the one that moved"


def test_every_ref_has_exactly_one_preferred_file_after_the_move(old_world: Database) -> None:
    one_pass(old_world)
    with old_world.read() as conn:
        for row in conn.execute("SELECT ref, SUM(preferred) AS preferred FROM song_file GROUP BY ref"):
            assert row["preferred"] == 1, row["ref"]
        assert conn.execute("SELECT preferred FROM song_file WHERE ref = ?", (R,)).fetchone()["preferred"] == 1, (
            "R lost its preferred file and has the one it kept now"
        )


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# nothing a person owns moved


def test_nothing_a_person_owns_moves_and_the_old_ref_keeps_its_id_and_its_first_title(old_world: Database) -> None:
    """The rule of the whole design: a split never moves a like, a playlist entry, a play, a saved release or the saved queue. They stay on R, which keeps the title the
    person saw. Taken on the REHOME ALONE (`finish(release=False)`): the merge that follows in the library link is a different step with a test of its own."""
    before = owned(old_world)
    with old_world.read() as conn:
        title = conn.execute("SELECT title FROM song_ref WHERE id = ?", (R,)).fetchone()["title"]

    judge(old_world, listing())

    assert owned(old_world) == before
    assert len({ref for ref in files(old_world).values()}) == 7, "and the split did happen"
    with old_world.read() as conn:
        assert conn.execute("SELECT title FROM song_ref WHERE id = ?", (R,)).fetchone()["title"] == title
        assert conn.execute("SELECT COUNT(*) FROM ref_merge").fetchone()[0] == 0, "no merge, no tombstone"
        assert conn.execute("SELECT COUNT(*) FROM ref_gone").fetchone()[0] == 0, "no id disappeared"


def test_the_people_who_hold_the_song_are_told_it_changed_through_the_feed_they_already_read(old_world: Database) -> None:
    """The holders of R are touched (their `library/changes` names R again, so a phone re-reads its file); nobody is told of a new row they do not own."""
    with old_world.read() as conn:
        cursors = {who: library.latest_cursor(conn, who) for who in (ME, YOU)}

    one_pass(old_world)

    with old_world.read() as conn:
        assert all(library.latest_cursor(conn, who) > cursors[who] for who in (ME, YOU))
        touched = {r["target"] for r in conn.execute("SELECT target FROM change_log WHERE seq > 0 AND kind = 'like'")}
    assert R in touched


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# what is judged, and how


def make_world(db: Database, build: Callable[[sqlite3.Connection], None]) -> None:
    """A small world with the KEYS THE FOLD MAKES NOW (the old-fold damage is in the acceptance tests above) and the refs it names put on the worklist by hand."""
    with db.tx() as c:
        c.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES (?,?,?,1)", (ME, "ana", "ana"))
        build(c)


def listed(db: Database, *refs_: str) -> None:
    with db.tx() as c:
        for ref in refs_:
            c.execute("INSERT INTO ref_recheck (ref, at) VALUES (?, 1)", (ref,))


def song(nd: str, title: str, artist: str, seconds: float = 200.0, **extra: Any) -> dict[str, Any]:
    return {
        "id": nd,
        "title": title,
        "artist": artist,
        "album": "A",
        "duration": seconds,
        "path": f"x/{nd}.opus",
        "suffix": "opus",
        "bitRate": 128,
        **extra,
    }


def test_a_ref_that_matches_the_tags_keeps_the_file_even_when_an_older_ref_matches_too(db: Database) -> None:
    """Two refs of ONE song (the N-11 duplicates): the file stays where it is, whichever is the oldest answer of `find`. The merge by file is what folds them, never a move
    that would leave the younger ref (and its likes) without a file."""
    older, younger = rid("sr", 1), rid("sr", 2)
    tags = song("nd-1", "كيفك إنت", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, older, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_ref(c, younger, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, younger, "nd-1", song=tags)

    make_world(db, build)
    listed(db, younger)
    with db.read() as conn:
        assert refs.find(conn, refs.parse_item(described(tags)))["id"] == older, "find answers the older ref"  # type: ignore[index]

    judge(db, [tags])

    assert files(db) == {"nd-1": (younger,)}
    assert worklist(db) == set()


def test_an_isrc_the_ref_holds_keeps_the_file_whatever_the_tags_say_of_the_title(db: Database) -> None:
    """Ids first: the ISRC the ref holds means the file IS that recording, even when the tags are poorer than the description the ref was made from."""
    ref = rid("sr", 1)
    tags = song("nd-1", "Habibi", "Fairuz", isrc=["QZ1234567890"])

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, ref, "حبيبي يا نور العين", ["فيروز"], old=False, isrc="QZ1234567890")
        add_file(c, ref, "nd-1", song=tags)

    make_world(db, build)
    listed(db, ref)

    report = judge(db, [tags])

    assert files(db) == {"nd-1": (ref,)} and report.moved == 0 and report.kept == 1


def test_an_isrc_that_another_ref_holds_moves_the_file_there_when_the_current_ref_does_not_match_the_tags_too(
    db: Database,
) -> None:
    """The glued-different-song case: the current ref is another song (its name is not the tags' name), the strongest evidence names a ref, so the file MOVES there. (Until
    the review round of 20 Nov 2026 this test had a current ref that matched by name too and expected a move: the ambiguous case, below, which now stays.)"""
    wrong, right = rid("sr", 1), rid("sr", 2)
    tags = song("nd-1", "Habibi", "Fairuz", isrc=["QZ1234567890"])

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, wrong, "كيفك إنت", ["فيروز"], old=False)  # another song, which the old fold glued this file onto
        add_ref(c, right, "Habibi (the other title the catalogue uses)", ["Fairuz"], old=False, isrc="QZ1234567890")
        add_file(c, wrong, "nd-1", song=tags)

    make_world(db, build)
    listed(db, wrong)

    judge(db, [tags])

    assert files(db) == {"nd-1": (right,)}


def test_an_untagged_arabic_file_stays_on_its_ref_unless_an_id_names_another(db: Database) -> None:
    """The placeholder artist: `refs.find` returns NOTHING for it on purpose, and nothing must never read as another song, or a correct untagged file would be moved off its
    own song and onto a new ref. It is judged by ids only."""
    stays, goes, other = rid("sr", 1), rid("sr", 2), rid("sr", 3)
    plain = song("nd-1", "أغنية بلا فنان", "[Unknown Artist]")
    named = song("nd-2", "أغنية أخرى", "[Unknown Artist]", isrc=["QZ0000000002"])

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, stays, "أغنية بلا فنان", ["[Unknown Artist]"], old=False)
        add_file(c, stays, "nd-1", song=plain)
        add_ref(c, goes, "أغنية أخرى", ["[Unknown Artist]"], old=False)
        add_file(c, goes, "nd-2", song=named)
        add_ref(c, other, "The song that ISRC names", ["Somebody"], old=False, isrc="QZ0000000002")

    make_world(db, build)
    listed(db, stays, goes)

    report = judge(db, [plain, named])

    assert files(db) == {"nd-1": (stays,), "nd-2": (other,)}
    assert report.stayed_nameless == 1 and report.moved == 1 and report.new_refs == 0
    assert worklist(db) == {stays}, (
        "the ref whose file nobody could judge STAYS on the worklist; the one whose file an id named is released"
    )
    assert report.held_back == 1 and report.held_undecided == 1 and report.released == 1
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0] == 3, "no ref was made for a nameless file"


def test_a_file_with_no_usable_tags_stays_and_so_does_its_ref_on_the_worklist(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    """It cannot be judged by anything, so the file stays where it is (what the code did before) and its ref STAYS on the worklist: the ref's files may belong to other songs and
    nobody could check, and merging identities on a file nobody could verify is what the `recheck_pending` hold exists to stop. The log says how many files and why."""
    ref = rid("sr", 1)
    bare = song("nd-1", "", "")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, ref, "أغنية", ["فيروز"], old=False)
        add_file(c, ref, "nd-1", song=bare)

    make_world(db, build)
    listed(db, ref)

    with caplog.at_level(logging.INFO, logger=LOG):
        report = judge(db, [bare])

    assert files(db) == {"nd-1": (ref,)} and worklist(db) == {ref}
    assert report.stayed_untagged == 1 and report.held_back == 1 and report.held_undecided == 1 and report.released == 0
    assert ref in caplog.text and "could not be judged" in caplog.text


def test_a_ref_held_for_a_file_that_could_not_be_judged_is_released_once_the_file_can_be_judged(db: Database) -> None:
    """The Host tags the file (or removes it): the next pass judges it, and the ref leaves the worklist."""
    ref = rid("sr", 1)
    untagged = song("nd-1", "أغنية", "[Unknown Artist]")
    tagged = song("nd-1", "أغنية", "فيروز", 200.0)

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, ref, "أغنية", ["[Unknown Artist]"], old=False)
        add_file(c, ref, "nd-1", song=untagged)

    make_world(db, build)
    listed(db, ref)
    judge(db, [untagged])
    assert worklist(db) == {ref}

    report = judge(db, [tagged])

    assert worklist(db) == set() and report.released == 1 and report.moved == 1, (
        "the properly tagged file belongs to the song its tags name"
    )
    assert files(db)["nd-1"][0] != ref


def test_the_pairs_held_for_a_ref_with_a_file_nobody_could_judge_stay_held(db: Database) -> None:
    """Releasing such a ref would let `refmerge` merge identities on a file nobody could verify."""
    keeper_ref, scan_ref = rid("sr", 1), rid("sr", 2)
    nameless = song("nd-1", "أغنية", "[Unknown Artist]")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, keeper_ref, "أغنية", ["[Unknown Artist]"], old=False)
        add_file(c, keeper_ref, "nd-1", source="youtube", added_at=10, song=nameless)
        add_ref(c, scan_ref, "أغنية", ["[Unknown Artist]"], old=False)
        add_file(c, scan_ref, "nd-1", added_at=20, song=nameless)

    make_world(db, build)
    listed(db, scan_ref)

    report = link_library(db, Music([nameless]))

    assert report.rehome is not None and report.rehome.held_undecided == 1 and worklist(db) == {scan_ref}
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ref_merge").fetchone()[0] == 0
        mergeable, held = refmerge.look(conn)
    assert not mergeable and [h.reason for h in held] == ["recheck_pending"]


def test_a_target_that_already_holds_the_same_file_keeps_one_row_and_the_wrong_holder_loses_its_row(db: Database) -> None:
    """The keeper's ref holds the file of the music server too (N-11): the moved row is dropped and the target's own stays, so a file is never on two rows of one ref."""
    wrong, right = rid("sr", 1), rid("sr", 2)
    tags = song("nd-1", "نسّم علينا الهوا", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, wrong, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, wrong, "nd-1", song=tags)
        add_ref(c, right, "نسّم علينا الهوا", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, right, "nd-1", source="youtube", song=tags)

    make_world(db, build)
    listed(db, wrong)

    report = judge(db, [tags])

    assert files(db) == {"nd-1": (right,)}
    with db.read() as conn:
        assert conn.execute("SELECT source FROM song_file").fetchone()["source"] == "youtube", "the target's own row stays"
    assert report.dropped == 1 and report.moved == 1


def test_a_keepers_file_is_never_judged_or_moved(db: Database) -> None:
    """The keeper attached it on purpose, for the ref's own description: whatever the music server's tags say of it, the row stays (source `youtube` or `quality`)."""
    ref = rid("sr", 1)
    library_tags = song("nd-1", "كيفك إنت", "فيروز")
    kept_tags = song("nd-2", "حبيتك بالصيف", "فيروز")  # the tags of the keeper's file name ANOTHER song

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, ref, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, ref, "nd-1", song=library_tags)
        add_file(c, ref, "nd-2", source="youtube", song=kept_tags)
        add_file(c, ref, "nd-3", source="quality", song=song("nd-3", "نسّم علينا الهوا", "فيروز"))

    make_world(db, build)
    listed(db, ref)

    judge(db, [library_tags, kept_tags, song("nd-3", "نسّم علينا الهوا", "فيروز")])

    assert files(db) == {"nd-1": (ref,), "nd-2": (ref,), "nd-3": (ref,)}


def test_a_row_that_changed_hands_after_the_pass_began_is_left_alone(db: Database) -> None:
    """Between the worklist being read and the verdict being applied another writer (the keeper, the merge) may have moved the row: the pass judged it where it READ it, and the
    write transaction looks again. The other writer put it on a THIRD song (not the one the tags name), so a pass that acted on what it read would take it from there."""
    first, second, third = rid("sr", 1), rid("sr", 2), rid("sr", 3)
    tags = song("nd-1", "نسّم علينا الهوا", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, first, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, first, "nd-1", song=tags)
        add_ref(c, second, "نسّم علينا الهوا", ["فيروز"], old=False, duration_ms=200_000)
        add_ref(c, third, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, first)
    work = rehome.begin(db, described, Listing.of([tags], began=now_ms()))
    assert work is not None
    with db.tx() as c:  # somebody else re-pointed the file in the meantime
        c.execute("UPDATE song_file SET ref = ? WHERE navidrome_song_id = 'nd-1'", (third,))

    work.page([tags])
    report = work.finish(release=False)

    assert files(db) == {"nd-1": (third,)}, "left where the other writer put it"
    assert report.changed == 1 and report.moved == 0


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the feed: what the phones are told


def test_the_files_feed_returns_both_refs_and_the_old_one_names_the_file_it_kept(old_world: Database) -> None:
    with old_world.read() as conn:
        since = conn.execute("SELECT MAX(seq) FROM file_log").fetchone()[0] or 0

    one_pass(old_world)

    with old_world.read() as conn:
        page = library.files_since(conn, since)
    by_id = {r["id"]: r for r in page["refs"]}
    assert R in by_id and len(by_id) == 5, "R and the four songs that were made for its other files"
    assert by_id[R]["file"]["navidromeSongId"] == "nd-1", (
        "R names the file it kept, so a phone's download of R is stale by the key it already has"
    )
    moved = {r["file"]["navidromeSongId"] for rid_, r in by_id.items() if rid_ != R}
    assert moved == {"nd-2", "nd-3", "nd-4", "nd-5"}
    assert page["merges"] == [] and page["gone"] == [], "no new feed: no tombstone, no merge, no gone row"


def test_a_ref_that_lost_its_only_file_says_file_null_and_the_janitor_retires_it_after_fourteen_days(db: Database) -> None:
    """Left with no file and nothing pointing at it, the ref is just a ref nobody uses: it is retired like any other, after 14 days from the change of its files, and
    leaves a `ref_gone` row (the phone's own tombstone, slice 2c of N-27)."""
    left, real = rid("sr", 1), rid("sr", 2)
    tags = song("nd-1", "نسّم علينا الهوا", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, left, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000, created_at=1)
        add_file(c, left, "nd-1", song=tags)
        add_ref(c, real, "نسّم علينا الهوا", ["فيروز"], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, left)

    judge(db, [tags])

    with db.read() as conn:
        page = library.files_since(conn, 0)
    assert {r["id"]: r["file"] for r in page["refs"]}[left] is None
    now = int(time.time() * 1000)
    assert RefJanitor(db, clock=lambda: now + AGE_MS - 3600_000).run_once() == 0, (
        "13 days after the change of its files it is still there"
    )
    assert RefJanitor(db, clock=lambda: now + AGE_MS + 3600_000).run_once() == 1
    with db.read() as conn:
        assert conn.execute("SELECT 1 FROM ref_gone WHERE ref_id = ?", (left,)).fetchone() is not None


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the complete pass, the worklist and the hold of refmerge


def test_an_incomplete_pass_decides_and_writes_nothing_and_the_next_complete_one_does_the_whole_job_with_one_copy(
    old_world: Database,
) -> None:
    """The music server stops answering in the middle of the pass: the verdict of a file depends on the files the music server lists in the REST of the pass, so nothing was
    decided: no file moved, no copy taken, no record of an attempt, the worklist kept. The NEXT complete pass does the whole job with ONE copy (the second review round:
    the first build moved the files of the pages it had read, and the next pass found a world it had changed itself)."""
    first = link_library(old_world, Music(listing(), down_at=2), page=3)

    assert first.complete is False and first.rehome is None
    assert worklist(old_world) == {R}, "an incomplete pass empties nothing"
    assert copies(old_world) == [] and setting(old_world, rehome.BACKUP_PENDING_SETTING) is None
    assert {r for nd, (r,) in files(old_world).items() if nd in ("nd-1", "nd-2", "nd-3", "nd-4", "nd-5")} == {R}, (
        "and moves nothing"
    )

    second = link_library(old_world, Music(listing()), page=3)

    assert second.complete is True and worklist(old_world) == set()
    assert len(copies(old_world)) == 1
    assert setting(old_world, rehome.BACKUP_USED_SETTING) == copies(old_world)[0].name
    assert setting(old_world, rehome.BACKUP_PENDING_SETTING) is None
    assert len({r for nd, (r,) in files(old_world).items() if nd != "nd-6" and nd != "nd-7"}) == 5


def test_a_file_the_pass_could_not_see_keeps_its_ref_on_the_worklist_until_a_pass_that_does(old_world: Database) -> None:
    """A pass that only adds (the one after a scan, `prune=False`) cannot say a file is gone: a file of the ref that was not in the listing is not judged, so the ref stays
    on the worklist, with a line that says why, and the hourly pass (which prunes) finds it gone and empties the worklist."""
    without_last = [s for s in listing() if s["id"] != "nd-4"]

    report = one_pass(old_world, without_last, prune=False)

    assert report.complete is True
    assert worklist(old_world) == {R}, "nd-4 was not seen: its ref is not released"
    assert report.rehome is not None and report.rehome.held_back == 1 and report.rehome.released == 0
    assert files(old_world)["nd-4"] == (R,), "and it was not touched"

    one_pass(old_world, without_last)  # prune=True: the file is not in the listing, so its row goes

    assert worklist(old_world) == set()
    assert "nd-4" not in files(old_world)


def test_the_worklist_row_of_a_ref_that_is_gone_is_dropped_by_the_pass(db: Database) -> None:
    ref = rid("sr", 1)
    tags = song("nd-1", "كيفك إنت", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, ref, "كيفك إنت", ["فيروز"], old=False)
        add_file(c, ref, "nd-1", song=tags)

    make_world(db, build)
    listed(db, ref, rid("sr", 99))

    judge(db, [tags])

    assert worklist(db) == set()


def test_a_rehome_that_cannot_finish_never_stops_the_library_link_and_the_next_pass_finishes_it(
    old_world: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The scan did its work and committed it; a failure at the end of the rehome is one ERROR line, the worklist is kept, and the next pass finishes the job."""
    real = rehome.Rehome.finish

    def broken(self: rehome.Rehome, *, release: bool = True) -> rehome.Report:
        raise RuntimeError("the database is busy")

    monkeypatch.setattr(rehome.Rehome, "finish", broken)
    with caplog.at_level(logging.ERROR, logger="encore_server.scanner"):
        report = one_pass(old_world)

    assert report.complete is True and report.linked == 7 and report.rehome is None
    assert "could not finish its pass" in caplog.text and worklist(old_world) == {R}
    monkeypatch.setattr(rehome.Rehome, "finish", real)

    again = one_pass(old_world)

    assert again.rehome is not None and again.rehome.released == 1 and worklist(old_world) == set()
    assert len({held[0] for held in files(old_world).values()}) == 7


def test_a_rehome_that_cannot_start_never_stops_the_library_link(
    old_world: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(db: Database, describe: Any) -> None:
        raise RuntimeError("no worklist today")

    monkeypatch.setattr(rehome, "begin", broken)
    before = files(old_world)
    with caplog.at_level(logging.ERROR, logger="encore_server.scanner"):
        report = one_pass(old_world)

    assert report.complete is True and report.linked == 7 and report.rehome is None
    assert "could not start" in caplog.text and worklist(old_world) == {R} and files(old_world) == before


def test_a_python_whose_unicode_is_not_the_pin_is_a_refusal_the_rehome_does_not_swallow(
    old_world: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not a failure to log and go on from: this Python must not write a key at all (the server does not start on it either)."""
    monkeypatch.setattr(textnorm.unicodedata, "unidata_version", "15.1.0")

    with pytest.raises(textnorm.UnicodeVersionError):
        one_pass(old_world)


def test_the_hold_of_refmerge_is_released_in_the_same_link_and_the_pair_merges_by_the_normal_rules(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    """A pair that holds one file, with a worklist ref, is HELD (`recheck_pending`) until the rehome has judged that ref's files; the same link then judges it by the normal rules.
    Here the file belongs to the worklist ref (its tags match), the other ref is the keeper's duplicate: they merge, and the person's like follows the survivor."""
    keeper_ref, scan_ref = rid("sr", 1), rid("sr", 2)
    tags = song("nd-1", "كيفك إنت", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, keeper_ref, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, keeper_ref, "nd-1", source="youtube", added_at=10, song=tags)
        add_ref(c, scan_ref, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, scan_ref, "nd-1", added_at=20, song=tags)
        library.set_item(c, ME, "like", scan_ref)

    make_world(db, build)
    listed(db, scan_ref)
    with caplog.at_level(logging.INFO, logger="encore_server.refmerge"):
        before = refmerge.repair(db, everything_listed(db))
    assert before.merged == [] and [h.reason for h in before.held] == ["recheck_pending"]

    report = link_library(db, Music([tags]))

    assert report.rehome is not None and report.rehome.released == 1
    with db.read() as conn:
        merged = conn.execute("SELECT old_id, into_id FROM ref_merge").fetchall()
        assert [(m["old_id"], m["into_id"]) for m in merged] == [(scan_ref, keeper_ref)], (
            "the keeper's ref (attached first) survives, by the normal rule"
        )
        assert conn.execute("SELECT target FROM library_item WHERE kind = 'like'").fetchone()["target"] == keeper_ref, (
            "and the like follows the song"
        )
    assert worklist(db) == set()


def test_refmerge_is_not_run_when_the_pass_released_nothing(old_world: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pass that did not empty a worklist row has nothing to release: the merge repair (which logs every held pair) must not run every hour."""
    calls: list[int] = []
    # The pass-end merge of `scanner._merge_repair` (N-47) is its own call of the repair (and looks first); this test counts the DEBT's calls only, as it always did.
    monkeypatch.setattr("encore_server.scanner._merge_repair", lambda database, listing: None)
    monkeypatch.setattr(refmerge, "repair", lambda database, listing=None: calls.append(1) or refmerge.RepairReport())
    without_last = [s for s in listing() if s["id"] != "nd-4"]

    one_pass(old_world, without_last, prune=False)

    assert calls == [], "a worklist ref was kept on the list: nothing is released"
    one_pass(old_world, without_last)  # the pass that releases it
    assert calls == [1]
    one_pass(old_world, without_last)  # nothing on the worklist any more
    assert calls == [1]


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the copy


def test_exactly_one_copy_is_taken_before_the_first_move_and_it_holds_the_state_before_it(old_world: Database) -> None:
    assert copies(old_world) == []

    one_pass(old_world)

    (copy,) = copies(old_world)
    assert repair_copy.is_a_copy(copy)
    old = sqlite3.connect(copy)
    try:
        assert old.execute("SELECT COUNT(*) FROM song_file WHERE ref = ?", (R,)).fetchone()[0] == 5, (
            "the copy was taken BEFORE the first move"
        )
    finally:
        old.close()
    assert (
        setting(old_world, rehome.BACKUP_USED_SETTING) == copy.name and setting(old_world, rehome.BACKUP_PENDING_SETTING) is None
    )


def test_no_copy_is_taken_when_nothing_moves_and_none_when_the_worklist_is_empty(db: Database) -> None:
    ref = rid("sr", 1)
    tags = song("nd-1", "كيفك إنت", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, ref, "كيفك إنت", ["فيروز"], old=False)
        add_file(c, ref, "nd-1", song=tags)

    make_world(db, build)
    link_library(db, Music([tags]))
    assert copies(db) == [], "an empty worklist: nothing is read, nothing is copied"
    listed(db, ref)

    link_library(db, Music([tags]))

    assert copies(db) == [] and worklist(db) == set(), (
        "every file was kept: the worklist is emptied with no copy, because nothing was written but the list itself"
    )


def test_a_copy_a_committed_pass_spent_is_never_used_again(old_world: Database) -> None:
    one_pass(old_world)
    (first,) = copies(old_world)
    # the old fold's damage comes back (an older image ran and keyed songs its way): a new worklist, a new pass
    with old_world.tx() as c:
        c.execute("UPDATE song_file SET ref = ? WHERE navidrome_song_id = 'nd-3'", (R,))
        c.execute("INSERT INTO ref_recheck (ref, at) VALUES (?, 1)", (R,))

    one_pass(old_world)

    assert len(copies(old_world)) == 2 and first in copies(old_world), "the spent copy is not reused: a real pass takes its own"


def test_the_prune_never_removes_the_copy_just_taken_even_when_the_clock_names_older_copies_in_the_future(
    old_world: Database,
) -> None:
    """Three copies named in the future (a clock set back, the end of daylight saving time): the copy just taken sorts OLDEST of four. Ordering by names would remove it
    and the pass would go on with a path that does not exist (the slice 3 reproduction). The prune is told which copies stay."""
    old_world.backups.mkdir(parents=True, exist_ok=True)
    for stamp in ("20991231-235957", "20991231-235958", "20991231-235959"):
        (old_world.backups / f"encore-before-rehome-{stamp}.db").write_bytes(repair_copy.SQLITE_MAGIC + b"spare")

    one_pass(old_world)

    used = setting(old_world, rehome.BACKUP_USED_SETTING)
    assert used is not None and (old_world.backups / used).is_file(), "the copy the pass relied on is still there"
    assert repair_copy.is_a_copy(old_world.backups / used)
    assert len(copies(old_world)) <= repair_copy.KEEP_COPIES


@pytest.mark.parametrize("how", ["vanishes", "is emptied", "is not a database"])
def test_the_pass_writes_nothing_when_its_copy_is_not_there_at_the_moment_of_writing(
    old_world: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, how: str
) -> None:
    """The second layer, the only one that can stand alone: whatever happened to the copy between the moment it was taken and the moment of the write, nothing is
    re-pointed, ONE error line says so, the worklist is kept and the library link itself (the files it adds) carries on."""
    real = rehome._copy_for_this_pass

    def spoiled(db: Database) -> Path:
        copy = real(db)
        if how == "vanishes":
            copy.unlink()
        elif how == "is emptied":
            copy.write_bytes(b"")
        else:
            copy.write_bytes(b"this is not a database" * 50)
        return copy

    monkeypatch.setattr(rehome, "_copy_for_this_pass", spoiled)
    before = (files(old_world), owned(old_world))
    new_file = song("nd-8", "A new song", "Nobody New", 99.0)

    with caplog.at_level(logging.INFO, logger=LOG):
        report = link_library(old_world, Music([*listing(), new_file]))

    assert report.complete is True and report.linked == 8, "the library link went on"
    assert {nd: held for nd, held in files(old_world).items() if nd != "nd-8"} == before[0]
    assert owned(old_world) == before[1]
    assert worklist(old_world) == {R}
    assert [r.levelno for r in caplog.records if r.name == LOG and r.levelno >= logging.ERROR] == [logging.ERROR], (
        "ONE line, not one per page"
    )
    assert report.rehome is not None and report.rehome.failed is True


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# a pass that failed (review round of 20 Nov 2026)

A_REF, B_REF, Y_REF = rid("sr", 1), rid("sr", 2), rid("sr", 3)


def a_kept_and_a_moving_song(db: Database) -> list[dict[str, Any]]:
    """Two worklist songs on two pages: A's file is kept (page 1), B's file is Y's song (page 2: it moves). Returns the music server's listing."""
    tags_a = song("nd-1", "كيفك إنت", "فيروز")
    tags_b = song("nd-2", "حبيتك بالصيف", "فيروز")  # the tags of B's file name Y's song

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, A_REF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, A_REF, "nd-1", song=tags_a)
        add_ref(c, B_REF, "نسّم علينا الهوا", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, B_REF, "nd-2", song=tags_b)
        add_ref(c, Y_REF, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, A_REF, B_REF)
    return [tags_a, tags_b]


def test_a_pass_that_failed_after_the_copy_releases_nothing_spends_no_copy_and_runs_no_merge_and_the_next_pass_finishes(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard in `finish`: page 1 judged A's file (kept: A is DONE), page 2's chunk fails AFTER the copy was taken. A pass that failed must not release A (the worklist
    is emptied only by a complete pass), must not spend the copy it relies on (the next pass reuses it) and must not run the merge repair; the next pass finishes the job."""
    listing_ = a_kept_and_a_moving_song(db)
    calls: list[int] = []
    monkeypatch.setattr(refmerge, "repair", lambda database, listing=None: calls.append(1) or refmerge.RepairReport())
    real = library.touch_ref_holders

    def disk_full(conn: sqlite3.Connection, ref: str) -> None:
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(library, "touch_ref_holders", disk_full)

    report = link_library(db, Music(listing_), page=1)

    assert report.complete is True and report.rehome is not None and report.rehome.failed is True
    assert worklist(db) == {A_REF, B_REF}, "A was fully judged, and still stays: the pass did not complete"
    (copy,) = copies(db)
    assert setting(db, rehome.BACKUP_PENDING_SETTING) == copy.name, (
        "the copy of the attempt that did not finish is still the pending one"
    )
    assert setting(db, rehome.BACKUP_USED_SETTING) is None, "and is not spent"
    assert calls == [], "no merge repair after a failed pass"
    assert files(db) == {"nd-1": (A_REF,), "nd-2": (B_REF,)}, "the chunk that failed changed nothing"

    monkeypatch.setattr(library, "touch_ref_holders", real)
    again = link_library(db, Music(listing_), page=1)

    assert again.rehome is not None and again.rehome.failed is False and worklist(db) == set()
    assert files(db) == {"nd-1": (A_REF,), "nd-2": (Y_REF,)}
    assert copies(db) == [copy], "the same copy was used again"
    assert setting(db, rehome.BACKUP_USED_SETTING) == copy.name and setting(db, rehome.BACKUP_PENDING_SETTING) is None
    assert calls == [1], "the merge repair ran once, after the pass that finished"


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# a wrong move is worse than none (review round of 20 Nov 2026, item 1)

SELF, DUP, OTHER = rid("sr", 1), rid("sr", 2), rid("sr", 3)


def own(c: sqlite3.Connection, how: str | None, ref: str) -> None:
    """What a person did with a ref: a like, an entry of a playlist, a play (the three the people see)."""
    if how == "like":
        library.set_item(c, ME, "like", ref)
    elif how == "entry":
        c.execute("INSERT INTO playlist (id, owner, name, created_at, updated_at) VALUES (?,?,?,1,1)", (PLAYLIST, ME, "mine"))
        c.execute(
            "INSERT INTO playlist_entry (id, playlist, position, ref, added_by, at) VALUES (?,?,1,?,?,1)",
            (rid("pe", 1), PLAYLIST, ref, ME),
        )
    elif how == "play":
        c.execute("INSERT INTO play_event (id, person, ref, at, ms_played) VALUES (?,?,?,5,1000)", (rid("pv", 1), ME, ref))


@pytest.mark.parametrize("how", [None, "like"])
def test_a_file_stays_when_its_ref_matches_it_by_name_and_a_duplicate_by_its_isrc_and_the_ref_stays_on_the_worklist(
    db: Database, caplog: pytest.LogCaptureFixture, how: str | None
) -> None:
    """THE REVIEW'S CASE. R (a like) holds the file; a duplicate X of the same song holds the ISRC the file's tags carry. The ids tier names only X, so the file used to be
    re-pointed R -> X: R kept its like and had no file, and R and X share no file, so the merge by file never folds them: permanent for the person who liked R. A wrong
    move is worse than none: the current ref ALSO matches (by name), so nothing moves, R stays on the worklist, and ONE line says why (ids only). [how] None: nobody owns R,
    so ONLY the rule of this test can keep the file (the last-file rule of the tests below does not apply)."""
    tags = song("nd-1", "كيفك إنت", "فيروز", isrc=["QZ1234567890"])

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", song=tags)
        add_ref(c, DUP, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000, isrc="QZ1234567890")
        own(c, how, SELF)

    make_world(db, build)
    listed(db, SELF)
    before = owned(db)

    with caplog.at_level(logging.INFO, logger=LOG):
        report = link_library(db, Music([tags]))  # the real path: the hourly pass, with the prune

    assert files(db) == {"nd-1": (SELF,)} and owned(db) == before, "nothing moved, nothing a person owns changed"
    assert worklist(db) == {SELF}, "the ref is held"
    assert report.rehome is not None and report.rehome.stayed_ambiguous == 1 and report.rehome.moved == 0
    assert report.rehome.held_back == 1 and report.rehome.held_undecided == 1 and report.rehome.released == 0
    assert copies(db) == [], "nothing was written, so no copy"
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.name == LOG and r.getMessage().startswith("rehome: file") and "names it as well" in r.getMessage()
    ]
    assert len(lines) == 1 and SELF in lines[0] and DUP in lines[0], "ONE line, with both ref ids"
    for title in ("كيفك", "فيروز"):
        assert title not in caplog.text

    again = link_library(db, Music([tags]))  # idempotent: the same answer, still nothing written

    assert files(db) == {"nd-1": (SELF,)} and worklist(db) == {SELF} and copies(db) == []
    assert again.rehome is not None and again.rehome.stayed_ambiguous == 1


def test_a_file_whose_ref_matches_it_by_name_while_a_merged_ref_s_id_names_another_ref_also_stays(db: Database) -> None:
    """`candidates` has four tiers; the rule is about every one of them: a ref that is a plausible answer in ANY tier is one the file may belong to."""
    tags = song("nd-1", "كيفك إنت", "فيروز", isrc=["QZ1234567890"])

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", song=tags)
        add_ref(c, DUP, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)  # another song
        # the ISRC of the file belonged to a ref that was merged into DUP: the tags name DUP by a merged id (tier 2), SELF by name (tier 3)
        c.execute(
            "INSERT INTO ref_merge (old_id, into_id, at, isrc, norm_key, duration_ms) VALUES (?,?,1,?,?,?)",
            (rid("sr", 50), DUP, "QZ1234567890", "gone||gone", 200_000),
        )

    make_world(db, build)
    listed(db, SELF)

    report = link_library(db, Music([tags]))

    assert files(db) == {"nd-1": (SELF,)} and worklist(db) == {SELF}
    assert report.rehome is not None and report.rehome.stayed_ambiguous == 1


def test_a_ref_that_absorbed_a_duplicate_under_the_tags_name_is_a_plausible_answer_too_so_the_file_stays(db: Database) -> None:
    """The fourth tier of `candidates` on its own (the ref's OWN name is not the tags' name, only a tombstone's is): SELF is the survivor of a merged ref that had the tags'
    name, so the description may be SELF's song, and an ISRC names another ref at the same time. Nobody owns SELF: only the rule of this test keeps the file."""
    tags = song("nd-1", "كيفك إنت", "فيروز", isrc=["QZ1234567890"])

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)  # the title SELF carries now is another one
        add_file(c, SELF, "nd-1", song=tags)
        add_ref(c, DUP, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000, isrc="QZ1234567890")
        c.execute(
            "INSERT INTO ref_merge (old_id, into_id, at, norm_key, duration_ms) VALUES (?,?,1,?,?)",
            (rid("sr", 50), SELF, refs.norm_key("فيروز", "كيفك إنت"), 200_000),
        )

    make_world(db, build)
    listed(db, SELF)

    report = link_library(db, Music([tags]))

    assert files(db) == {"nd-1": (SELF,)} and worklist(db) == {SELF}
    assert report.rehome is not None and report.rehome.stayed_ambiguous == 1


@pytest.mark.parametrize("other", ["a duplicate holds the ISRC", "nobody else"])
def test_a_ref_whose_length_is_not_the_files_still_matches_it_by_name_so_the_file_stays(db: Database, other: str) -> None:
    """The name tier of `candidates` compares the LENGTH (three seconds), and a ref whose length was filled in after its file was attached (the builder's limit (c)) is then
    not an answer to the tags that name it: it was not in the plausible set, and the file moved off it. A ref whose own name is the tags' name is a ref the file may belong
    to, whatever its length says: doubt keeps the file. Nobody owns the ref, so only this rule can keep it."""
    tags = song("nd-1", "كيفك إنت", "فيروز", 260.0, isrc=["QZ1234567890"])

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)  # 60 s off the file
        add_file(c, SELF, "nd-1", song=tags)
        if other == "a duplicate holds the ISRC":
            add_ref(c, DUP, "كيفك إنت", ["فيروز"], old=False, duration_ms=260_000, isrc="QZ1234567890")

    make_world(db, build)
    listed(db, SELF)

    report = link_library(db, Music([tags]))

    assert files(db) == {"nd-1": (SELF,)} and worklist(db) == {SELF}
    assert report.rehome is not None and report.rehome.moved == 0 and report.rehome.stayed_ambiguous == 1


@pytest.mark.parametrize("how", ["like", "entry", "play"])
def test_the_last_file_of_a_song_a_person_owns_never_moves_and_its_ref_stays_on_the_worklist(
    db: Database, caplog: pytest.LogCaptureFixture, how: str
) -> None:
    """The tags name ANOTHER song and the file is the only one the person's song has: a move would leave a like, an entry or a play on a song with no file (the review's
    stranded person). It stays, the song stays on the worklist, one line says why."""
    tags = song("nd-1", "حبيتك بالصيف", "فيروز")  # the tags name OTHER's song

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", song=tags)
        add_ref(c, OTHER, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)
        own(c, how, SELF)

    make_world(db, build)
    listed(db, SELF)
    before = owned(db)

    with caplog.at_level(logging.INFO, logger=LOG):
        report = link_library(db, Music([tags]))

    assert files(db) == {"nd-1": (SELF,)} and owned(db) == before
    assert worklist(db) == {SELF} and copies(db) == []
    assert report.rehome is not None and report.rehome.stayed_last_file == 1 and report.rehome.moved == 0
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.name == LOG and r.getMessage().startswith("rehome: file") and "last file" in r.getMessage()
    ]
    assert len(lines) == 1 and SELF in lines[0] and "كيفك" not in lines[0]


def test_the_same_file_of_a_song_nobody_owns_moves_and_so_does_the_file_of_a_song_that_keeps_another_one(db: Database) -> None:
    """The two controls of the test above: nobody owns the song (the janitor retires it later: the existing behaviour), or the song keeps a keeper's file after the move."""
    free, owned_ref, target = rid("sr", 1), rid("sr", 2), rid("sr", 3)
    tags_free = song("nd-1", "حبيتك بالصيف", "فيروز")
    tags_owned = song("nd-2", "حبيتك بالصيف", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, free, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, free, "nd-1", song=tags_free)
        add_ref(c, owned_ref, "نسّم علينا الهوا", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, owned_ref, "nd-2", song=tags_owned)
        add_file(c, owned_ref, "nd-9", source="youtube", added_at=10, song=song("nd-9", "نسّم علينا الهوا", "فيروز"))
        own(c, "like", owned_ref)
        add_ref(c, target, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, free, owned_ref)

    report = link_library(
        db, Music([tags_free, tags_owned, song("nd-9", "نسّم علينا الهوا", "فيروز")])
    )  # the keeper's file is listed too, or the prune takes it

    assert files(db)["nd-1"] == (target,) and files(db)["nd-2"] == (target,) and files(db)["nd-9"] == (owned_ref,)
    assert report.rehome is not None and report.rehome.moved == 2 and report.rehome.stayed_last_file == 0


def test_the_check_of_the_last_file_reads_the_rows_of_the_transaction_so_the_second_of_two_moves_stays(db: Database) -> None:
    """A song somebody owns holds two library files that both name other songs: the first may go (the song keeps the second), the second is then its LAST file and stays.
    The count is read inside the write transaction, after the first move of the same chunk, not from what the pass read before."""
    z1, z2 = rid("sr", 2), rid("sr", 3)
    first = song("nd-1", "حبيتك بالصيف", "فيروز")
    second = song("nd-2", "سألوني الناس", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", song=first)
        add_file(c, SELF, "nd-2", song=second)
        add_ref(c, z1, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)
        add_ref(c, z2, "سألوني الناس", ["فيروز"], old=False, duration_ms=200_000)
        own(c, "like", SELF)

    make_world(db, build)
    listed(db, SELF)

    report = link_library(db, Music([first, second]))

    assert files(db) == {"nd-1": (z1,), "nd-2": (SELF,)}
    assert report.rehome is not None and report.rehome.moved == 1 and report.rehome.stayed_last_file == 1
    assert worklist(db) == {SELF}


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the preferred file of a song that lost a file (review round, item 2)


@pytest.mark.parametrize("preferred_before", ["the file that moves", "the file that is kept"])
def test_after_a_move_the_old_song_prefers_a_file_judged_kept_never_the_newest_one_nobody_could_judge(
    db: Database, preferred_before: str
) -> None:
    """The review's repro: R holds nd-1 (kept), nd-2 (the placeholder artist: nobody could judge it) and nd-3 (moves). `ensure_one_preferred` leaves R preferring the NEWEST
    remaining row, nd-2. The kept file is on a LATER page than the move, so only the end of the pass knows it."""
    other = rid("sr", 2)
    kept = song("nd-1", "كيفك إنت", "فيروز")
    nameless = song("nd-2", "أغنية", "[Unknown Artist]")
    going = song("nd-3", "حبيتك بالصيف", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", added_at=100, preferred=int(preferred_before == "the file that is kept"), song=kept)
        add_file(c, SELF, "nd-2", added_at=200, song=nameless)
        add_file(c, SELF, "nd-3", added_at=300, preferred=int(preferred_before == "the file that moves"), song=going)
        add_ref(c, other, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)
        own(c, "like", SELF)

    make_world(db, build)
    listed(db, SELF)

    link_library(db, Music([going, nameless, kept]), page=2)  # the move is on page 1, the kept file on page 2

    assert files(db) == {"nd-1": (SELF,), "nd-2": (SELF,), "nd-3": (other,)}
    with db.read() as conn:
        preferred = [
            r["navidrome_song_id"]
            for r in conn.execute("SELECT navidrome_song_id FROM song_file WHERE ref = ? AND preferred = 1", (SELF,))
        ]
        assert [r["preferred"] for r in conn.execute("SELECT preferred FROM song_file WHERE ref = ?", (other,))] == [1]
    assert preferred == ["nd-1"], "the file judged kept, not the newest"


def test_after_a_move_the_old_song_prefers_the_keepers_file_over_a_file_nobody_could_judge(db: Database) -> None:
    """A keeper's file is attached on purpose for the song's own description (never judged, never wrong by the tags): it counts as decided."""
    other = rid("sr", 2)
    nameless = song("nd-2", "أغنية", "[Unknown Artist]")
    going = song("nd-3", "حبيتك بالصيف", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-4", source="youtube", added_at=100, song=song("nd-4", "كيفك إنت", "فيروز"))
        add_file(c, SELF, "nd-2", added_at=200, song=nameless)
        add_file(c, SELF, "nd-3", added_at=300, preferred=1, song=going)
        add_ref(c, other, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, SELF)

    link_library(
        db, Music([going, nameless, song("nd-4", "كيفك إنت", "فيروز")])
    )  # the keeper's file is listed too, or the prune takes it

    with db.read() as conn:
        (row,) = conn.execute("SELECT navidrome_song_id FROM song_file WHERE ref = ? AND preferred = 1", (SELF,)).fetchall()
    assert row["navidrome_song_id"] == "nd-4"


def test_the_preference_is_put_right_by_the_pass_that_completes_even_when_an_earlier_pass_made_the_move(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The move is committed by a pass that FAILS after its first chunk (the process dies, or a later chunk raises): the old song then prefers the newest row left, the one
    nobody could judge. `ref_recheck.moved` is committed with the move, so the NEXT complete pass, which re-judges the whole song, still puts the preference right."""
    other, third, fourth = rid("sr", 2), rid("sr", 3), rid("sr", 4)
    kept = song("nd-1", "كيفك إنت", "فيروز")
    nameless = song("nd-2", "أغنية", "[Unknown Artist]")
    going = song("nd-3", "حبيتك بالصيف", "فيروز")
    second_move = song("nd-4", "سألوني الناس", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", added_at=100, preferred=0, song=kept)
        add_file(c, SELF, "nd-2", added_at=200, song=nameless)
        add_file(c, SELF, "nd-3", added_at=300, preferred=1, song=going)
        add_ref(c, other, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)
        add_ref(c, third, "نسّم علينا الهوا", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, third, "nd-4", added_at=400, song=second_move)
        add_ref(c, fourth, "سألوني الناس", ["فيروز"], old=False, duration_ms=200_000)
        own(c, "like", SELF)

    make_world(db, build)
    listed(db, SELF, third)
    songs = [going, nameless, kept, second_move]
    monkeypatch.setattr(rehome, "CHUNK", 1)
    real = rehome.Rehome._move  # noqa: SLF001
    calls: list[str] = []

    def dying(self: rehome.Rehome, conn: sqlite3.Connection, file_id: str, ref: str, described_: dict[str, Any] | None) -> Any:
        calls.append(file_id)
        if len(calls) == 2:
            raise RuntimeError("the process was killed here")
        return real(self, conn, file_id, ref, described_)

    monkeypatch.setattr(rehome.Rehome, "_move", dying)

    killed = link_library(db, Music(songs))

    assert killed.rehome is not None and killed.rehome.failed
    assert files(db)["nd-3"] == (other,) and files(db)["nd-4"] == (third,), "the first chunk is committed, the second is not"
    assert worklist(db) == {SELF, third}
    monkeypatch.undo()

    link_library(db, Music(songs))

    with db.read() as conn:
        preferred = [
            r["navidrome_song_id"]
            for r in conn.execute("SELECT navidrome_song_id FROM song_file WHERE ref = ? AND preferred = 1", (SELF,))
        ]
    assert preferred == ["nd-1"]


def test_the_phones_are_told_when_the_preferred_file_of_a_song_changes_at_the_end_of_the_pass(db: Database) -> None:
    """The preferred file is what the files feed answers for the song: a change of it is a change the feed must carry."""
    other = rid("sr", 2)
    kept = song("nd-1", "كيفك إنت", "فيروز")
    nameless = song("nd-2", "أغنية", "[Unknown Artist]")
    going = song("nd-3", "حبيتك بالصيف", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", added_at=100, song=kept)
        add_file(c, SELF, "nd-2", added_at=200, song=nameless)
        add_file(c, SELF, "nd-3", added_at=300, preferred=1, song=going)
        add_ref(c, other, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, SELF)
    with db.read() as conn:
        top = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM file_log").fetchone()[0]

    link_library(db, Music([going, nameless, kept]), page=2)

    with db.read() as conn:
        touched = [r["ref"] for r in conn.execute("SELECT ref FROM file_log WHERE seq > ? ORDER BY seq", (top,))]
        preferred = [
            r["navidrome_song_id"]
            for r in conn.execute("SELECT navidrome_song_id FROM song_file WHERE ref = ? AND preferred = 1", (SELF,))
        ]
    assert preferred == ["nd-1"] and touched.count(SELF) >= 2, (
        "once for the file that left, once more for the preferred file that changed afterwards"
    )


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the file the music server lists and cannot describe, through the real hourly pass (review round, item 3)


def test_a_file_with_no_usable_tags_keeps_its_row_and_its_ref_stays_on_the_worklist_through_the_hourly_pass_that_prunes(
    db: Database,
) -> None:
    """The real path (`link_library`, prune on): the music server LISTS the file, so it is not gone, however poor its tags are. It used to be pruned as 'gone' (it was never
    in `seen_ids`) before the rehome looked at it, so its ref was released from the worklist: the opposite of what docs/18 says."""
    ref = rid("sr", 1)
    bare = song("nd-1", "", "")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, ref, "أغنية", ["فيروز"], old=False)
        add_file(c, ref, "nd-1", song=bare)

    make_world(db, build)
    listed(db, ref)

    report = link_library(db, Music([bare]))

    assert report.pruned == 0 and report.skipped == 1
    assert files(db) == {"nd-1": (ref,)}, "the file is still listed: its row stays"
    assert worklist(db) == {ref}
    assert report.rehome is not None and report.rehome.stayed_untagged == 1
    assert report.rehome.held_undecided == 1 and report.rehome.released == 0


def test_a_listed_file_the_scan_cannot_describe_keeps_its_row_whoever_holds_it_and_the_prune_still_removes_a_file_the_listing_lacks(
    db: Database,
) -> None:
    """The prune is for files the music server NO LONGER HAS. Not on the worklist at all: a file the music server still lists with no usable tags keeps its row (the song
    stays playable, and nobody is told it must be streamed again), and a file that is really gone still goes (the control that the change did not switch the prune off)."""
    ref, gone_ref = rid("sr", 1), rid("sr", 2)
    bare = song("nd-1", "", "")
    lost = song("nd-2", "حبيتك بالصيف", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, ref, "أغنية", ["فيروز"], old=False)
        add_file(c, ref, "nd-1", song=bare)
        add_ref(c, gone_ref, "حبيتك بالصيف", ["فيروز"], old=False)
        add_file(c, gone_ref, "nd-2", song=lost)

    make_world(db, build)

    report = link_library(db, Music([bare]))  # nd-2 is not listed any more

    assert files(db) == {"nd-1": (ref,)}, "the listed file stays, the unlisted one is gone"
    assert report.pruned == 1 and report.skipped == 1


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the pace of the release and the merge that is owed (review round, item 5)


def five_kept_songs(db: Database) -> list[dict[str, Any]]:
    words = ["كيفك", "حبيتك", "نسّم", "سألوني", "زهرة"]
    tags = [song(f"nd-{n}", word, "فيروز") for n, word in enumerate(words, start=1)]

    def build(c: sqlite3.Connection) -> None:
        for n, (word, one) in enumerate(zip(words, tags, strict=True), start=1):
            add_ref(c, rid("sr", n), word, ["فيروز"], old=False, duration_ms=200_000)
            add_file(c, rid("sr", n), f"nd-{n}", song=one)

    make_world(db, build)
    listed(db, *(rid("sr", n) for n in range(1, 6)))
    return tags


@contextmanager
def watching_transactions(monkeypatch: pytest.MonkeyPatch, *, cut_after: int | None = None) -> Iterator[list[int]]:
    """How many rows of the worklist each write transaction removed (the ones that removed none are not listed); `cut_after`: raise right after the commit of the n-th of
    them, as when the process dies between two chunks."""
    sizes: list[int] = []
    real = Database.tx

    @contextmanager
    def spy(self: Database) -> Iterator[sqlite3.Connection]:
        with real(self) as conn:
            before = conn.execute("SELECT COUNT(*) FROM ref_recheck").fetchone()[0]
            yield conn
            after = conn.execute("SELECT COUNT(*) FROM ref_recheck").fetchone()[0]
        if before != after:
            sizes.append(before - after)
            if cut_after is not None and len(sizes) == cut_after:
                raise RuntimeError("the process was killed here")

    monkeypatch.setattr(Database, "tx", spy)
    yield sizes


def test_the_worklist_is_released_in_chunks_one_transaction_each(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    """The write lock is held for one chunk at a time (200,000 refs in one transaction held it for 3 s, measured), whatever the size of the worklist."""
    tags = five_kept_songs(db)
    monkeypatch.setattr(
        rehome, "RELEASE_CHUNK", 2, raising=False
    )  # (raising off: on the old code the test must fail by what it does, not by a missing name)

    with watching_transactions(monkeypatch) as sizes:
        report = link_library(db, Music(tags))

    assert sizes == [2, 2, 1] and worklist(db) == set()
    assert report.rehome is not None and report.rehome.released == 5


def test_the_production_chunk_is_500_and_a_worklist_of_1001_refs_is_released_in_500_500_1_with_no_help_from_the_test(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pin of the PRODUCTION value. Every test above sets a small chunk by hand, so the mutant `RELEASE_CHUNK = 10**9` (one transaction for the whole worklist: 3 s of write
    lock measured at 200,000 refs, and the test of the round-1 pace stays green) survived them. Nothing is patched here: 1,001 refs, each with the one file that is its own."""
    assert rehome.RELEASE_CHUNK == 500
    songs: list[dict[str, Any]] = []

    def build(c: sqlite3.Connection) -> None:
        for n in range(1, 1002):
            tags = song(f"nd-{n}", f"song {n}", "فيروز")
            add_ref(c, rid("sr", n), f"song {n}", ["فيروز"], old=False, duration_ms=200_000)
            add_file(c, rid("sr", n), f"nd-{n}", song=tags)
            songs.append(tags)

    make_world(db, build)
    listed(db, *(rid("sr", n) for n in range(1, 1002)))

    with watching_transactions(monkeypatch) as sizes:
        report = link_library(db, Music(songs))

    assert sizes == [500, 500, 1], "the write lock is held for 500 rows at most, 1,001 rows take three transactions"
    assert report.rehome is not None and report.rehome.released == 1001 and worklist(db) == set()


def test_a_pass_cut_between_two_chunks_is_resumed_by_the_next_one_and_the_merge_it_owes_is_not_lost(
    db: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The process dies right after the FIRST chunk was committed: two refs are released, three are not. The flag that says 'the pairs held for released refs have not been
    judged yet' was written in the SAME transaction as that release, so it survives; the next pass finishes the worklist and then runs the merge repair (once)."""
    tags = five_kept_songs(db)
    calls: list[int] = []
    monkeypatch.setattr(refmerge, "repair", lambda database, listing=None: calls.append(1) or refmerge.RepairReport())
    monkeypatch.setattr(rehome, "RELEASE_CHUNK", 2, raising=False)

    with watching_transactions(monkeypatch, cut_after=1) as sizes, caplog.at_level(logging.ERROR, logger="encore_server.scanner"):
        report = link_library(db, Music(tags))

    assert sizes == [2] and report.rehome is None and "could not finish its pass" in caplog.text
    assert len(worklist(db)) == 3, "two refs are released, three are not"
    assert calls == [], "the merge repair waits for the end of the worklist"
    monkeypatch.undo()
    monkeypatch.setattr(refmerge, "repair", lambda database, listing=None: calls.append(1) or refmerge.RepairReport())

    again = link_library(db, Music(tags))

    assert again.rehome is not None and again.rehome.released == 3 and worklist(db) == set()
    assert calls == [1], "the merge repair ran once, after the pass that emptied the worklist"
    assert setting(db, rehome.MERGE_PENDING_SETTING) is None, "and the debt is paid"


def test_the_merge_owed_is_written_in_the_same_transaction_as_the_first_release(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the flag were written after the release, a process killed between the two would leave refs released and no memory that the pairs held for them were never judged."""
    tags = five_kept_songs(db)
    monkeypatch.setattr(refmerge, "repair", lambda database, listing=None: refmerge.RepairReport())
    monkeypatch.setattr(rehome, "RELEASE_CHUNK", 2, raising=False)

    with watching_transactions(monkeypatch, cut_after=1):
        link_library(db, Music(tags))

    assert len(worklist(db)) == 3
    assert setting(db, rehome.MERGE_PENDING_SETTING) is not None, (
        "the merge is owed: the flag is committed with the first release"
    )


@pytest.mark.parametrize("how", ["returns failed", "raises"])
def test_a_merge_repair_that_failed_after_the_worklist_was_emptied_is_retried_at_the_next_pass_and_then_not_again(
    db: Database, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """`refmerge.repair` answers `failed` (it never raises); a raise is covered as well. The worklist is already empty, so the next pass has no rehome to run: the retry is
    owed by a durable flag, and it clears only when the repair did not fail."""
    keeper_ref, scan_ref = rid("sr", 1), rid("sr", 2)
    tags = song("nd-1", "كيفك إنت", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, keeper_ref, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, keeper_ref, "nd-1", source="youtube", added_at=10, song=tags)
        add_ref(c, scan_ref, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, scan_ref, "nd-1", added_at=20, song=tags)
        library.set_item(c, ME, "like", scan_ref)

    make_world(db, build)
    listed(db, scan_ref)
    real = refmerge.repair
    calls: list[int] = []

    def flaky(database: Database, listing: Listing | None = None) -> refmerge.RepairReport:
        calls.append(1)
        if len(calls) == 1:
            if how == "raises":
                raise RuntimeError("the database is busy")
            return refmerge.RepairReport(failed=True)
        return real(database, listing)

    # The pass-end merge of `scanner._merge_repair` (N-47) is its own call of the repair; this test counts the DEBT's calls only, as it always did.
    monkeypatch.setattr("encore_server.scanner._merge_repair", lambda database, listing: None)
    monkeypatch.setattr(refmerge, "repair", flaky)

    first = link_library(db, Music([tags]))

    assert first.rehome is not None and first.rehome.released == 1 and worklist(db) == set()
    assert calls == [1]
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ref_merge").fetchone()[0] == 0, "the repair failed: nothing is merged yet"

    link_library(db, Music([tags]))  # the next pass: no worklist, no rehome, and still the retry

    assert calls == [1, 1]
    with db.read() as conn:
        assert [(m["old_id"], m["into_id"]) for m in conn.execute("SELECT old_id, into_id FROM ref_merge")] == [
            (scan_ref, keeper_ref)
        ]
    assert setting(db, rehome.MERGE_PENDING_SETTING) is None, "paid: the flag is clear"

    link_library(db, Music([tags]))

    assert calls == [1, 1], "and not again: the flag is clear"


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the record of a copy that nobody will use again (review round, item 6)


def test_a_pass_that_finishes_with_nothing_to_move_spends_the_copy_of_the_failed_attempt_it_finishes(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed pass A leaves its copy as the pending one (the next attempt reuses it). When the next pass B finds nothing to move (the file was removed, or put right some
    other way) it COMPLETES that attempt without taking or reusing a copy: the pending record must not stay, or a later fold change, which fills the worklist again, would reuse
    this copy, taken before the state of that day."""
    tags = song("nd-1", "حبيتك بالصيف", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", song=tags)
        add_ref(c, OTHER, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, SELF)
    real = library.touch_ref_holders

    def disk_full(conn: sqlite3.Connection, ref: str) -> None:
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(library, "touch_ref_holders", disk_full)
    failed = link_library(db, Music([tags]))
    monkeypatch.setattr(library, "touch_ref_holders", real)
    assert failed.rehome is not None and failed.rehome.failed is True
    (first,) = copies(db)
    assert setting(db, rehome.BACKUP_PENDING_SETTING) == first.name

    finished = link_library(db, Music([]))  # the music server no longer lists the file: nothing to move, the pass completes

    assert (
        finished.rehome is not None and finished.rehome.failed is False and finished.rehome.moved == 0 and worklist(db) == set()
    )
    assert setting(db, rehome.BACKUP_PENDING_SETTING) is None and setting(db, rehome.BACKUP_USED_SETTING) == first.name

    # a fold change fills the worklist again: a real pass takes its OWN copy
    with db.tx() as c:
        add_file(c, SELF, "nd-1", song=tags)
        c.execute("INSERT INTO ref_recheck (ref, at) VALUES (?, 1)", (SELF,))
    link_library(db, Music([tags]))

    assert len(copies(db)) == 2 and first in copies(db), "a new copy, not the old one again"
    assert files(db) == {"nd-1": (OTHER,)}


def test_the_record_of_a_failed_attempt_is_spent_when_the_worklist_was_emptied_by_another_hand(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The janitor (or anything else) can empty the worklist after a failure: then no pass runs and nothing would ever clear the record."""
    tags = song("nd-1", "حبيتك بالصيف", "فيروز")

    def build(c: sqlite3.Connection) -> None:
        add_ref(c, SELF, "كيفك إنت", ["فيروز"], old=False, duration_ms=200_000)
        add_file(c, SELF, "nd-1", song=tags)
        add_ref(c, OTHER, "حبيتك بالصيف", ["فيروز"], old=False, duration_ms=200_000)

    make_world(db, build)
    listed(db, SELF)
    monkeypatch.setattr(library, "touch_ref_holders", lambda conn, ref: (_ for _ in ()).throw(RuntimeError("the disk is full")))
    link_library(db, Music([tags]))
    (first,) = copies(db)
    assert setting(db, rehome.BACKUP_PENDING_SETTING) == first.name
    monkeypatch.undo()
    with db.tx() as c:
        c.execute("DELETE FROM ref_recheck")  # what the janitor does for a ref it retires

    link_library(db, Music([tags]))

    assert setting(db, rehome.BACKUP_PENDING_SETTING) is None and setting(db, rehome.BACKUP_USED_SETTING) == first.name


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the Host's own music is never touched


def tree(root: Path) -> dict[str, tuple[int, int, str]]:
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@contextmanager
def music_folder_is_read_only(root: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every Python-level way of changing a file or a folder under [root] raises: opening for writing, rename, replace, remove, unlink, rmdir, mkdir, truncate, utime,
    chmod, `shutil`. (SQLite's own writes are in C and are not covered: they go to the database and its copy, which are not under [root].)"""
    attempts: list[str] = []

    def under(value: object) -> bool:
        try:
            return Path(os.fspath(value)).resolve().is_relative_to(root.resolve())  # type: ignore[arg-type]
        except (TypeError, ValueError, OSError):
            return False

    def guard(name: str, real: Callable[..., Any], *, first_only: bool = False) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            for value in args[:1] if first_only else args:
                if under(value):
                    attempts.append(name)
                    raise AssertionError(f"{name} on the Host's music folder: {value}")
            return real(*args, **kwargs)

        return wrapped

    def guard_open(real: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if any(flag in str(mode) for flag in "wax+") and under(file):
                attempts.append("open for writing")
                raise AssertionError(f"open for writing on the Host's music folder: {file}")
            return real(file, mode, *args, **kwargs)

        return wrapped

    monkeypatch.setattr(builtins, "open", guard_open(builtins.open))
    monkeypatch.setattr(io, "open", guard_open(io.open))
    for name in (
        "remove",
        "unlink",
        "rename",
        "replace",
        "rmdir",
        "mkdir",
        "makedirs",
        "truncate",
        "utime",
        "chmod",
        "removedirs",
    ):
        monkeypatch.setattr(os, name, guard(f"os.{name}", getattr(os, name)))
    for name in ("move", "copy", "copy2", "copyfile", "copytree", "rmtree"):
        monkeypatch.setattr(shutil, name, guard(f"shutil.{name}", getattr(shutil, name)))
    yield attempts


def test_a_library_file_is_only_ever_re_pointed_the_disk_is_untouched(
    old_world: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Host's music folder is the Host's: the rehome changes rows of the database and nothing else. Real files stand where the listing says they do; every Python-level
    write, rename or delete under that folder raises during the pass, and the folder (names, sizes, modification times, bytes) is identical after it."""
    music = tmp_path / "hosts-music"
    for n, (nd, _title, artist, album, _seconds) in enumerate(TRACKS, start=1):
        path = music / "Collection" / artist / album / f"{n:02d}.opus"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"audio of {nd}".encode() * 100)
    before = tree(music)
    assert len(before) == 7

    # The listing names each file by its ABSOLUTE path here, so that a rehome that tried to do anything to "the file of the song" would reach the real file.
    songs = [{**s, "path": str(music / s["path"])} for s in listing()]
    with music_folder_is_read_only(music, monkeypatch) as attempts:
        report = one_pass(old_world, songs)

    assert report.rehome is not None and report.rehome.moved == 4, "the pass really ran under the guard"
    assert attempts == []
    assert tree(music) == before


def test_the_guard_of_the_test_above_would_see_a_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The control of the test above: the same guard stops a write, a rename and a delete (else a passing test would prove nothing)."""
    music = tmp_path / "m"
    music.mkdir()
    (music / "a.opus").write_bytes(b"x")
    with music_folder_is_read_only(music, monkeypatch) as attempts:
        for act in (
            lambda: (music / "b.opus").write_bytes(b"y"),
            lambda: (music / "a.opus").rename(music / "c.opus"),
            lambda: (music / "a.opus").unlink(),
            lambda: shutil.move(str(music / "a.opus"), str(tmp_path / "gone.opus")),
        ):
            with pytest.raises(AssertionError):
                act()
    assert len(attempts) >= 4 and (music / "a.opus").is_file()


def test_rehome_py_imports_nothing_that_writes_to_the_music_folder() -> None:
    """A source-level guard, with its limit stated: it reads the DIRECT imports of `rehome.py` and the names it calls. It cannot see a write that a module it is allowed to
    import (`refs` imports `keeper.covers`, which writes folder pictures) might make; that is what the runtime test above proves for the whole pass."""
    tree_ = ast.parse(Path(rehome.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree_):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(("." * node.level) + (node.module or ""))
            imported |= {("." * node.level) + (node.module or "") + "." + alias.name for alias in node.names}
    forbidden = {
        "shutil",
        "os",
        "tempfile",
        "glob",
        "subprocess",
        ".keeper",
        ".keeper.placement",
        ".keeper.tagging",
        ".keeper.keeper",
        ".keeper.covers",
    }
    assert not imported & forbidden, imported & forbidden
    calls = {node.attr for node in ast.walk(tree_) if isinstance(node, ast.Attribute)}
    assert not calls & {
        "unlink",
        "rename",
        "replace",
        "write_bytes",
        "write_text",
        "rmtree",
        "move",
        "remove",
        "mkdir",
        "touch",
    }, calls


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# what a log line says


def test_the_log_carries_ids_and_counts_and_never_a_title(old_world: Database, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOG):
        one_pass(old_world)

    text = caplog.text
    assert "rehome" in text and "4 files re-pointed" in text
    assert R in text, "a ref id, so a line can be looked up"
    for title in ("كيفك", "فيروز", "Группа", "Кино", "Radiohead", "Weird Fishes"):
        assert title not in text, title


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the saved real responses the phone's test reads (ADR-R41 T5): written by the real endpoint on this synthetic data

FIXTURES = Path(__file__).resolve().parents[3] / "app" / "test" / "fixtures" / "server"


def _answer(client: TestClient, since: str) -> dict[str, Any]:
    response = client.get(f"{V1}/library/files", params={**creds("marwa"), "since": since, "mergesSince": "0", "goneSince": "0"})
    assert response.status_code == 200
    body = response.json()
    body.pop("serverTime")  # the one value that is different every time
    return body  # type: ignore[no-any-return]


def _check_or_write(name: str, body: dict[str, Any]) -> None:
    text = json.dumps(body, indent=2, ensure_ascii=False) + "\n"
    path = FIXTURES / name
    if os.environ.get("ENCORE_WRITE_FIXTURES") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.is_file(), "run with ENCORE_WRITE_FIXTURES=1 once to write it"
    assert json.loads(path.read_text(encoding="utf-8")) == body


def test_the_files_responses_before_and_after_a_split_are_the_saved_fixtures_the_phone_reads(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One contract: the server's own test saves two REAL responses of the files feed, built by the real endpoint on synthetic data, and the app's test reads them: what a
    phone that synced BEFORE the split holds (R, whose preferred file is nd-5), and what the SAME feed answers after it, from the phone's cursor (R names nd-1; four new
    songs). When this changes, this test fails until the files are written again (`ENCORE_WRITE_FIXTURES=1 pytest tests/test_rehome.py -k saved_fixtures`)."""
    counter = iter(range(100, 200))
    monkeypatch.setattr(
        refs, "new_id", lambda prefix: f"{prefix}_{next(counter):026d}"
    )  # the new songs get fixed ids, so the saved answer is the same every run
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    seed_old_world(db)
    with db.tx() as c:  # the phone's own person is the one of the test client
        who = library.ensure_person(c, "marwa")["id"]
        library.set_item(c, who, "like", R)
    keyrepair.repair(db)
    before = _answer(client, "0")
    cursor = before["cursor"]

    link_library(db, Music(listing()))

    after = _answer(client, cursor)
    assert [r["id"] for r in before["refs"] if r["id"] == R] == [R] and next(r for r in before["refs"] if r["id"] == R)["file"][
        "navidromeSongId"
    ] == "nd-5"
    assert next(r for r in after["refs"] if r["id"] == R)["file"]["navidromeSongId"] == "nd-1"
    assert len(after["refs"]) == 5 and after["merges"] == [] and after["gone"] == []
    _check_or_write("library-files-before-split.json", before)
    _check_or_write("library-files-after-split.json", after)
