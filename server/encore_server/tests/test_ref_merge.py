"""N-11 part B: the start-up repair that merges the song refs which hold one file, and everything that keeps the merge honest afterwards.

The data here is SYNTHETIC (invented songs and people, fixed ids, fixed times), shaped like what the test server's database turned out to hold: the
keeper's ref (the import's description: the artists as a list, a cover, the album) and the scan's ref (the tags: the artists as ONE string, a length
seconds off, the album `[Unknown Album]`), both holding the same file of the music server. Rows are written with SQL on purpose: `refs.resolve` would
match the two descriptions to each other, which is exactly what the old scan failed to do.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server import library, playback, refmerge, refs
from encore_server.api import create_app
from encore_server.auth import sign_stream
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.scanner import link_library
from tests.conftest import FakeVerifier, creds
from tests.test_scanner import FakeLibrary

V1 = "/encore/api/v1"
COVER = "https://e-cdns-images.dzcdn.net/images/cover/synthetic/500x500.jpg"


def rid(prefix: str, n: int) -> str:
    """A well-formed id with a number in it: `sr_00000000000000000000000012`."""
    return f"{prefix}_{n:026d}"


# the songs (a number each), the people, the lists
S1, L1, S2, L2, S3, L3, S3B, L3B, T1, T2, T3, H1, H2, Q1, Q2, R1, R2 = (rid("sr", n) for n in range(1, 18))
P1, P2 = rid("pn", 1), rid("pn", 2)
PL_A, PL_B = rid("pl", 1), rid("pl", 2)


def add_person(conn: sqlite3.Connection, person: str, name: str) -> None:
    conn.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES (?,?,?,1)", (person, name, name))


def add_ref(conn: sqlite3.Connection, ref: str, title: str, artists: list[str], **fields: Any) -> None:
    n = int(ref[3:])
    row = {
        "album": None,
        "album_artist": None,
        "duration_ms": None,
        "isrc": None,
        "deezer_id": None,
        "ytm_video_id": None,
        "cover_url": None,
        "year": None,
        **fields,
    }
    conn.execute(
        "INSERT INTO song_ref (id, title, artists, album, album_artist, year, duration_ms, isrc, deezer_id, ytm_video_id, cover_url, norm_key, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ref,
            title,
            json.dumps(artists),
            row["album"],
            row["album_artist"],
            row["year"],
            row["duration_ms"],
            row["isrc"],
            row["deezer_id"],
            row["ytm_video_id"],
            row["cover_url"],
            refs.norm_key(artists[0], title),
            1000 + n,
        ),
    )


def add_file(
    conn: sqlite3.Connection,
    ref: str,
    nd: str,
    added_at: int,
    *,
    source: str,
    path: str,
    meta: dict[str, Any] | None = None,
    bitrate: int = 128,
) -> None:
    file_id = f"sf_{int(ref[3:]):013d}{int(nd.split('-')[1]):013d}"  # one id for each (song, file of the music server), the same on every run
    conn.execute(
        "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, bitrate_kbps, source, preferred, added_at, meta) VALUES (?,?,?,?,?,?,?,1,?,?)",
        (
            file_id,
            ref,
            nd,
            path,
            "opus",
            bitrate,
            source,
            added_at,
            json.dumps(meta, separators=(",", ":"), sort_keys=True) if meta else None,
        ),
    )
    conn.execute("INSERT INTO file_log (ref, at) VALUES (?, ?)", (ref, added_at))


def seed(db: Database) -> None:
    """Seventeen songs: six pairs that must merge, a group of three (one of them held), and two pairs that must be held."""
    with db.tx() as c:
        add_person(c, P1, "ana")
        add_person(c, P2, "ben")

        # 1: the artists as a list + a cover + the album, against the artists as ONE string and "[Unknown Album]"
        add_ref(c, S1, "Neon Harbor", ["Ana Vale", "Bo Lin", "Cy Mar"], album="Real Album", album_artist="Ana Vale", duration_ms=249000,
                ytm_video_id="VIDEOAAAAA1", cover_url=COVER)  # fmt: skip
        add_ref(c, L1, "Neon Harbor", ["Ana Vale, Bo Lin, Cy Mar"], album="[Unknown Album]", duration_ms=261000)
        add_file(
            c,
            S1,
            "nd-1",
            1000,
            source="youtube",
            path="Encore/Ana Vale/Singles/Neon Harbor.opus",
            meta={"coverArt": "al-1", "size": 111},
        )
        add_file(c, L1, "nd-1", 2000, source="library", path="Ana Vale, Bo Lin, Cy Mar/[Unknown Album]/Neon Harbor.opus",
                 meta={"albumId": "al-9", "size": 222}, bitrate=131)  # fmt: skip

        # 2: the lengths are 12 seconds apart; the later ref knows a cover and a year the first does not
        add_ref(c, S2, "Quiet Orbit", ["Dee Roy"], album="Orbit", duration_ms=200000)
        add_ref(
            c,
            L2,
            "Quiet Orbit",
            ["Dee Roy"],
            album="Orbit",
            album_artist="Dee Roy",
            duration_ms=212000,
            year=2001,
            cover_url=COVER,
        )
        add_file(c, S2, "nd-2", 1100, source="youtube", path="Encore/Dee Roy/Singles/Quiet Orbit.opus")
        add_file(c, L2, "nd-2", 2100, source="library", path="Dee Roy/Orbit/Quiet Orbit.opus")

        # 3: no album against "[Unknown Album]" (the survivor must not get the placeholder), and the placeholder against a real album
        add_ref(c, S3, "Paper Moon", ["Eli Ko"], album=None)
        add_ref(c, L3, "Paper Moon", ["Eli Ko"], album="[Unknown Album]")
        add_file(c, S3, "nd-3", 1200, source="youtube", path="Encore/Eli Ko/Singles/Paper Moon.opus")
        add_file(c, L3, "nd-3", 2200, source="library", path="Eli Ko/[Unknown Album]/Paper Moon.opus")
        add_ref(c, S3B, "Glass Tide", ["Fay Gu"], album="[Unknown Album]")
        add_ref(c, L3B, "Glass Tide", ["Fay Gu"], album="Moonlit")
        add_file(c, S3B, "nd-4", 1250, source="youtube", path="Encore/Fay Gu/Singles/Glass Tide.opus")
        add_file(c, L3B, "nd-4", 2250, source="library", path="Fay Gu/Moonlit/Glass Tide.opus")

        # 4: a group of THREE on one file: two youtube refs from two different videos, and the scan's ref
        add_ref(c, T1, "Triple Echo", ["Gus Ha"], ytm_video_id="TTTTTTTTTT1")
        add_ref(c, T2, "Triple Echo", ["Gus Ha"], ytm_video_id="TTTTTTTTTT2")
        add_ref(c, T3, "Triple Echo", ["Gus Ha"], album="[Unknown Album]")
        add_file(c, T1, "nd-5", 1300, source="youtube", path="Encore/Gus Ha/Singles/Triple Echo.opus")
        add_file(c, T2, "nd-5", 1400, source="youtube", path="Encore/Gus Ha/Singles/Triple Echo.opus")
        add_file(c, T3, "nd-5", 2300, source="library", path="Gus Ha/[Unknown Album]/Triple Echo.opus")

        # 5: two source items (two videos) on one file: held
        add_ref(c, H1, "Twin Signal", ["Ivy Jo"], ytm_video_id="HHHHHHHHHH1")
        add_ref(c, H2, "Twin Signal", ["Ivy Jo"], ytm_video_id="HHHHHHHHHH2")
        add_file(c, H1, "nd-6", 1500, source="youtube", path="Encore/Ivy Jo/Singles/Twin Signal.opus")
        add_file(c, H2, "nd-6", 2500, source="library", path="Ivy Jo/[Unknown Album]/Twin Signal.opus")

        # 6: one playlist holds both refs of a pair: held (merging would show the song twice there)
        add_ref(c, Q1, "Shared Shelf", ["Kai Lu"])
        add_ref(c, Q2, "Shared Shelf", ["Kai Lu"])
        add_file(c, Q1, "nd-7", 1600, source="youtube", path="Encore/Kai Lu/Singles/Shared Shelf.opus")
        add_file(c, Q2, "nd-7", 2600, source="library", path="Kai Lu/[Unknown Album]/Shared Shelf.opus")

        # 7: a pair whose second ref sits in a playlist only as a REMOVED entry: not held
        add_ref(c, R1, "Late Entry", ["Lia Mo"])
        add_ref(c, R2, "Late Entry", ["Lia Mo"])
        add_file(c, R1, "nd-8", 1700, source="youtube", path="Encore/Lia Mo/Singles/Late Entry.opus")
        add_file(c, R2, "nd-8", 2700, source="library", path="Lia Mo/[Unknown Album]/Late Entry.opus")

        # what the people have
        for pl, owner, name in ((PL_A, P1, "Road trip"), (PL_B, P2, "Evening")):
            c.execute("INSERT INTO playlist (id, owner, name, created_at, updated_at) VALUES (?,?,?,1,1)", (pl, owner, name))
        entries = [  # id, playlist, ref, deleted_at
            (rid("pe", 1), PL_A, L1, None),
            (rid("pe", 2), PL_A, L2, None),
            (rid("pe", 3), PL_A, Q1, None),
            (rid("pe", 4), PL_A, Q2, None),
            (rid("pe", 5), PL_A, L3, 9),
            (rid("pe", 6), PL_B, S1, None),
            (rid("pe", 7), PL_B, R1, None),
            (rid("pe", 8), PL_B, R2, 9),
        ]
        for index, (entry, playlist, ref, deleted) in enumerate(entries, start=1):
            owner = P1 if playlist == PL_A else P2
            c.execute(
                "INSERT INTO playlist_entry (id, playlist, position, ref, added_by, at, deleted_at) VALUES (?,?,?,?,?,5,?)",
                (entry, playlist, float(index), ref, owner, deleted),
            )
        for person, ref, at in ((P1, L1, 5000), (P2, L1, 3000), (P2, S1, 4000), (P1, H2, 6000)):
            c.execute("INSERT INTO library_item (person, kind, target, at) VALUES (?, 'like', ?, ?)", (person, ref, at))
            c.execute("INSERT INTO change_log (person, kind, target, at) VALUES (?, 'like', ?, ?)", (person, ref, at))
        for play, person, ref in (("play-1", P1, L2), ("play-2", P1, L2), ("play-3", P1, S2), ("play-4", P2, T3)):
            c.execute("INSERT INTO play_event (id, person, ref, at, ms_played) VALUES (?,?,?,7000,200000)", (play, person, ref))
        c.execute(
            "INSERT INTO playback_state (person, ref, position_ms, queue, idx, rev, updated_at) VALUES (?,?,1234,?,2,3,8000)",
            (P1, L2, json.dumps([S1, L1, L2, T3, S1, H2])),
        )
        for person, album, ref in ((P1, "alb-1", S1), (P1, "alb-1", L1), (P2, "alb-2", L3)):
            c.execute(
                "INSERT INTO library_item (person, kind, target, at) VALUES (?, 'saved_album', ?, 1) ON CONFLICT DO NOTHING",
                (person, album),
            )
            c.execute("INSERT INTO saved_album_ref (person, album, ref) VALUES (?,?,?)", (person, album, ref))
        c.execute(
            "INSERT INTO import (id, person, source, name, created_at, updated_at) VALUES (?,?,'youtube','A list',1,1)",
            (rid("im", 1), P1),
        )
        for position, ref in ((0, L2), (1, S1)):
            c.execute("INSERT INTO import_entry (import, position, ref) VALUES (?,?,?)", (rid("im", 1), position, ref))
        work = [  # id, kind, ref, state, who wants it
            (rid("wk", 1), "keep", L1, "queued", P1),
            (rid("wk", 2), "keep", S1, "queued", P2),
            (rid("wk", 3), "prepare", L2, "queued", P2),
            (rid("wk", 4), "keep", L3, "failed", P1),
            (rid("wk", 5), "keep", T3, "running", P2),
        ]
        for item, kind, ref, state, person in work:
            c.execute(
                "INSERT INTO work_item (id, kind, ref, priority, state, next_try_at, created_at, updated_at) VALUES (?,?,?,4,?,0,1,1)",
                (item, kind, ref, state),
            )
            c.execute("INSERT INTO work_item_person (item, person) VALUES (?,?)", (item, person))


MERGED = {L1: S1, L2: S2, L3: S3, L3B: S3B, T3: T1, R2: R1}
HELD = {frozenset({T1, T2}), frozenset({H1, H2}), frozenset({Q1, Q2})}


@pytest.fixture()
def seeded(db: Database) -> Database:
    seed(db)
    return db


def q(db: Database, sql: str, *args: Any) -> list[sqlite3.Row]:
    with db.read() as conn:
        return list(conn.execute(sql, args))


def one(db: Database, sql: str, *args: Any) -> Any:
    return q(db, sql, *args)[0][0]


def duplicates(db: Database) -> int:
    return int(
        one(
            db,
            "SELECT COUNT(*) FROM (SELECT navidrome_song_id FROM song_file WHERE navidrome_song_id IS NOT NULL"
            " GROUP BY 1 HAVING COUNT(DISTINCT ref) > 1)",
        )
    )


def dump(db: Database) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table, to prove that a rolled-back repair changed nothing."""
    with db.read() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {t: sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {t}")) for t in tables}  # noqa: S608 - names from sqlite_master


def refs_pointed_at(conn: sqlite3.Connection) -> set[str]:
    """Every song id any row names, in every column that can hold one."""
    named: set[str] = set()
    for table, column, where in (
        ("song_file", "ref", "1"),
        ("library_item", "target", "kind = 'like'"),
        ("playlist_entry", "ref", "1"),
        ("play_event", "ref", "1"),
        ("import_entry", "ref", "1"),
        ("work_item", "ref", "1"),
        ("saved_album_ref", "ref", "1"),
        ("playback_state", "ref", "ref IS NOT NULL"),
        ("file_log", "ref", "1"),
        ("change_log", "target", "kind = 'like'"),
    ):
        named.update(r[0] for r in conn.execute(f"SELECT {column} FROM {table} WHERE {where}"))  # noqa: S608 - fixed names
    for row in conn.execute("SELECT queue FROM playback_state"):
        named.update(json.loads(row[0]))
    return named


def live_refs(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT id FROM song_ref")}


def per_person(db: Database) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for person in (P1, P2):
        out[person] = {
            "live_entries": one(
                db,
                "SELECT COUNT(*) FROM playlist_entry e JOIN playlist p ON p.id = e.playlist WHERE p.owner = ? AND e.deleted_at IS NULL",
                person,
            ),
            "all_entries": one(
                db, "SELECT COUNT(*) FROM playlist_entry e JOIN playlist p ON p.id = e.playlist WHERE p.owner = ?", person
            ),
            "likes": one(db, "SELECT COUNT(*) FROM library_item WHERE person = ? AND kind = 'like'", person),
            "plays": one(db, "SELECT COUNT(*) FROM play_event WHERE person = ?", person),
        }
    return out


# ------------------------------------------------------------------------------------------------------------------ the migration


def test_every_column_that_holds_a_song_id_is_one_the_repair_knows(db: Database) -> None:
    """A new table that points at `song_ref` must be taught to the repair (`refmerge.REPOINTED`) in the same change, or a merge would cascade-delete
    its rows or leave them pointing at nothing. This fails the day somebody adds one."""
    with db.read() as conn:
        found = set()
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for fk in conn.execute(f"PRAGMA foreign_key_list({table})"):  # noqa: S608 - names from sqlite_master
                if fk["table"] == "song_ref":
                    found.add((table, fk["from"]))
    assert found == refmerge.FOREIGN_KEY_COLUMNS


def test_the_ref_merge_table_has_the_columns_the_design_names(db: Database) -> None:
    with db.read() as conn:
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(ref_merge)")]
    assert columns == ["seq", "old_id", "into_id", "at", "norm_key", "isrc", "deezer_id", "ytm_video_id", "duration_ms"]


@pytest.mark.parametrize(
    ("sql", "index"),
    [
        ("SELECT 1 FROM playlist_entry WHERE ref = 'x'", "playlist_entry_ref"),
        ("SELECT 1 FROM play_event WHERE ref = 'x'", "play_event_ref"),
        ("SELECT 1 FROM library_item WHERE kind = 'like' AND target = 'x'", "library_item_like_target"),
        ("SELECT 1 FROM change_log WHERE kind = 'like' AND target = 'x'", "change_log_like_target"),
        ("SELECT 1 FROM ref_merge WHERE old_id = 'x'", "sqlite_autoindex_ref_merge_1"),
        ("SELECT 1 FROM ref_merge WHERE norm_key = 'x'", "ref_merge_norm"),
    ],
)
def test_the_lookups_the_repair_and_find_make_are_answered_by_an_index_not_a_scan(db: Database, sql: str, index: str) -> None:
    """A big library has years of plays and a change log that only grows: a start-up repair that read them all for every merged song would take minutes."""
    with db.read() as conn:
        plan = " ".join(str(r["detail"]) for r in conn.execute("EXPLAIN QUERY PLAN " + sql))
    assert index in plan, plan


# ------------------------------------------------------------------------------------------------------------------ what is merged and what is held


def test_only_the_pairs_that_are_the_same_song_are_merged_and_the_rest_are_held(seeded: Database) -> None:
    assert duplicates(seeded) == 8

    report = refmerge.repair(seeded)

    assert report.failed is False
    assert {pair.loser: pair.survivor for pair in report.merged} == MERGED
    assert {frozenset({h.survivor, h.loser}) for h in report.held} == HELD
    assert {h.reason for h in report.held} == {"different_source_video", "same_playlist"}
    assert duplicates(seeded) == 3  # only the held ones remain
    with seeded.read() as conn:
        assert live_refs(conn) == {S1, S2, S3, S3B, T1, T2, H1, H2, Q1, Q2, R1}
    assert {r["old_id"]: r["into_id"] for r in q(seeded, "SELECT old_id, into_id FROM ref_merge")} == MERGED


def test_the_survivor_is_the_ref_whose_file_was_attached_first_not_the_older_ref(db: Database) -> None:
    """The ref made first is not the survivor when the other one's file came earlier: the file's own row says whose it is."""
    with db.tx() as c:
        add_ref(c, S1, "Older Ref", ["Ana Vale"])  # created first, its file attached SECOND
        add_ref(c, L1, "Older Ref", ["Ana Vale"])
        add_file(c, S1, "nd-1", 5000, source="library", path="a.opus")
        add_file(c, L1, "nd-1", 4000, source="youtube", path="b.opus")

    report = refmerge.repair(db)

    assert [(p.survivor, p.loser) for p in report.merged] == [(L1, S1)]


def test_two_refs_with_different_isrc_or_catalogue_ids_are_two_recordings_and_are_held(db: Database) -> None:
    with db.tx() as c:
        add_ref(c, S1, "Same File", ["Ana Vale"], isrc="GBAAA0000001")
        add_ref(c, L1, "Same File", ["Ana Vale"], isrc="GBAAA0000002")
        add_ref(c, S2, "Other File", ["Dee Roy"], deezer_id="11")
        add_ref(c, L2, "Other File", ["Dee Roy"], deezer_id="22")
        for ref, nd, at in ((S1, "nd-1", 1), (L1, "nd-1", 2), (S2, "nd-2", 1), (L2, "nd-2", 2)):
            add_file(c, ref, nd, at, source="library", path=f"{ref}.opus")

    report = refmerge.repair(db)

    assert report.merged == [] and {h.reason for h in report.held} == {"different_isrc", "different_deezer_id"}
    assert report.backup is None  # nothing to merge: nothing is backed up


def test_entries_and_plays_per_person_are_unchanged_and_the_likes_that_changed_are_explained(seeded: Database) -> None:
    before = per_person(seeded)

    refmerge.repair(seeded)

    after = per_person(seeded)
    assert after[P1] == before[P1]
    # ben liked both refs of the first pair: one like of the song is what is left (the earlier of the two dates)
    assert after[P2] == {**before[P2], "likes": before[P2]["likes"] - 1}
    assert (
        q(seeded, "SELECT target, at FROM library_item WHERE person = ? AND kind = 'like' ORDER BY target", P2)[0]["at"] == 3000
    )
    assert [
        (r["target"], r["at"]) for r in q(seeded, "SELECT target, at FROM library_item WHERE person = ? AND kind = 'like'", P1)
    ] == [
        (S1, 5000),
        (H2, 6000),
    ]


def test_no_row_anywhere_points_at_a_song_that_is_gone(seeded: Database) -> None:
    with seeded.read() as conn:
        assert refs_pointed_at(conn) >= set(MERGED)  # people's rows do point at the songs that are about to go

    refmerge.repair(seeded)

    with seeded.read() as conn:
        assert refs_pointed_at(conn) - live_refs(conn) == set()
        assert refs_pointed_at(conn).isdisjoint(MERGED)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_playlist_entries_follow_to_the_survivor_the_removed_one_too(seeded: Database) -> None:
    refmerge.repair(seeded)

    assert {r["id"]: r["ref"] for r in q(seeded, "SELECT id, ref FROM playlist_entry")} == {
        rid("pe", 1): S1,
        rid("pe", 2): S2,
        rid("pe", 3): Q1,
        rid("pe", 4): Q2,
        rid("pe", 5): S3,
        rid("pe", 6): S1,
        rid("pe", 7): R1,
        rid("pe", 8): R1,
    }


def test_plays_imports_and_the_servers_copy_of_the_saved_queue_follow(seeded: Database) -> None:
    refmerge.repair(seeded)

    assert {r["id"]: r["ref"] for r in q(seeded, "SELECT id, ref FROM play_event")} == {
        "play-1": S2,
        "play-2": S2,
        "play-3": S2,
        "play-4": T1,
    }
    assert [(r["position"], r["ref"]) for r in q(seeded, "SELECT position, ref FROM import_entry ORDER BY position")] == [
        (0, S2),
        (1, S1),
    ]
    state = q(seeded, "SELECT * FROM playback_state")[0]
    # the queue is rewritten in place: the same length, the same places (the index would shift if a song were dropped), a held ref left alone
    assert state["ref"] == S2 and json.loads(state["queue"]) == [S1, S1, S2, T1, S1, H2] and state["idx"] == 2
    assert (
        state["rev"] > 3
    )  # the state changed under the devices that hold the old one: their next write gets `conflict` and the new state


def test_a_saved_release_that_held_both_songs_holds_the_survivor_once(seeded: Database) -> None:
    refmerge.repair(seeded)

    assert [(r["person"], r["album"], r["ref"]) for r in q(seeded, "SELECT * FROM saved_album_ref ORDER BY person, album")] == [
        (P1, "alb-1", S1),
        (P2, "alb-2", S3),
    ]


def test_work_for_the_loser_moves_joins_the_survivors_or_is_dropped(seeded: Database) -> None:
    refmerge.repair(seeded)

    items = {r["id"]: (r["kind"], r["ref"], r["state"]) for r in q(seeded, "SELECT * FROM work_item")}
    # wk_1 (keep L1) joined wk_2 (keep S1): one item for the song, wanted by both people; wk_3 moved; wk_4 was history of the loser; wk_5 moved
    assert items == {
        rid("wk", 2): ("keep", S1, "queued"),
        rid("wk", 3): ("prepare", S2, "queued"),
        rid("wk", 5): ("keep", T1, "running"),
    }
    assert {r["person"] for r in q(seeded, "SELECT person FROM work_item_person WHERE item = ?", rid("wk", 2))} == {P1, P2}
    assert q(seeded, "SELECT 1 FROM work_item_person WHERE item IN (?, ?)", rid("wk", 1), rid("wk", 4)) == []


def test_an_unreadable_saved_queue_or_file_meta_does_not_stop_the_repair_of_everything_else(seeded: Database) -> None:
    broken_queue = f"not json {L2}"
    with seeded.tx() as c:
        c.execute("UPDATE playback_state SET queue = ?", (broken_queue,))
        c.execute("UPDATE song_file SET meta = '{broken' WHERE ref = ?", (S1,))

    report = refmerge.repair(seeded)

    assert report.failed is False and {m.loser: m.survivor for m in report.merged} == MERGED
    assert q(seeded, "SELECT queue, ref FROM playback_state")[0]["queue"] == broken_queue  # left as it was
    assert json.loads(q(seeded, "SELECT meta FROM song_file WHERE ref = ?", S1)[0]["meta"]) == {"albumId": "al-9", "size": 222}


def test_the_survivor_is_enriched_only_with_what_it_lacks_and_never_with_an_unknown_album(seeded: Database) -> None:
    refmerge.repair(seeded)

    with seeded.read() as conn:
        first, second, third, fourth = (refs.get_ref(conn, r) for r in (S1, S2, S3, S3B))
        triple = refs.get_ref(conn, T1)
    # the keeper's description is kept as it is (the list of artists, the real album, the cover): nothing of the scan's tags replaces it
    assert (first["artists"], first["album"], first["albumArtist"], first["coverUrl"], first["durationMs"], first["videoId"]) == (
        ["Ana Vale", "Bo Lin", "Cy Mar"],
        "Real Album",
        "Ana Vale",
        COVER,
        249000,
        "VIDEOAAAAA1",
    )
    # what the survivor lacked is taken from the other ref
    assert (second["coverUrl"], second["year"], second["albumArtist"], second["durationMs"], second["album"]) == (
        COVER,
        2001,
        "Dee Roy",
        200000,
        "Orbit",
    )
    # no album stays no album: "[Unknown Album]" is never copied; a placeholder is replaced by a real album
    assert third["album"] is None and fourth["album"] == "Moonlit"
    assert triple["album"] is None


def test_a_loser_with_an_id_the_survivor_lacks_hands_it_over(db: Database) -> None:
    with db.tx() as c:
        add_ref(c, S1, "Handover", ["Ana Vale"])
        add_ref(c, L1, "Handover", ["Ana Vale"], isrc="GBAAA0000009", deezer_id="99", ytm_video_id="VIDEOHAND01")
        add_file(c, S1, "nd-1", 1, source="youtube", path="a.opus")
        add_file(c, L1, "nd-1", 2, source="library", path="b.opus")

    refmerge.repair(db)

    with db.read() as conn:
        row = refs.get_ref(conn, S1)
    assert (row["isrc"], row["deezerId"], row["videoId"]) == ("GBAAA0000009", "99", "VIDEOHAND01")


def test_the_files_are_merged_key_by_key_and_the_survivor_keeps_its_path_and_its_only_cover_id(seeded: Database) -> None:
    refmerge.repair(seeded)

    rows = q(seeded, "SELECT * FROM song_file WHERE ref = ?", S1)
    assert len(rows) == 1  # the same file of the music server: one row, not two
    row = rows[0]
    assert (row["navidrome_song_id"], row["path"], row["source"], row["added_at"], row["preferred"]) == (
        "nd-1",
        "Encore/Ana Vale/Singles/Neon Harbor.opus",
        "youtube",
        1000,
        1,
    )
    # a replaced meta would have lost "coverArt" (only the survivor had it); the newer row's values win where both have one
    assert json.loads(row["meta"]) == {"coverArt": "al-1", "albumId": "al-9", "size": 222}
    assert row["bitrate_kbps"] == 131  # what the music server reported last
    with seeded.read() as conn:
        shown = refs.get_ref(conn, S1)
    assert shown["file"]["meta"]["coverArt"] == "al-1"


def test_a_file_the_survivor_does_not_have_moves_over_and_one_file_stays_preferred(db: Database) -> None:
    with db.tx() as c:
        add_ref(c, S1, "Two Files", ["Ana Vale"])
        add_ref(c, L1, "Two Files", ["Ana Vale"])
        add_file(c, S1, "nd-1", 1, source="youtube", path="a.opus")
        add_file(c, L1, "nd-1", 2, source="library", path="b.opus")
        add_file(c, L1, "nd-2", 3, source="library", path="c.flac")  # another file of the loser's: a better copy

    refmerge.repair(db)

    rows = q(db, "SELECT navidrome_song_id, preferred FROM song_file WHERE ref = ? ORDER BY added_at", S1)
    assert [r["navidrome_song_id"] for r in rows] == ["nd-1", "nd-2"] and sum(r["preferred"] for r in rows) == 1


def test_the_feeds_tell_every_phone_that_has_the_song(seeded: Database) -> None:
    with seeded.read() as conn:
        files_before = int(conn.execute("SELECT MAX(seq) FROM file_log").fetchone()[0])
        changes_before = {p: library.latest_cursor(conn, p) for p in (P1, P2)}

    refmerge.repair(seeded)

    with seeded.read() as conn:
        files = library.files_since(conn, files_before)
        assert S1 in {r["id"] for r in files["refs"]}  # the survivor's file changed: phones read it again
        for person in (P1, P2):
            page = library.changes(conn, person, changes_before[person])
            assert page["refs"], person
            assert not any(
                like["removed"] for like in page["likes"]
            )  # nobody is told to un-like the song, only that it is the survivor now
        assert [e["ref"] for e in library.changes(conn, P1, changes_before[P1])["entries"] if e["id"] == rid("pe", 1)] == [S1]
        assert S1 in {like["ref"] for like in library.changes(conn, P1, changes_before[P1])["likes"]}
        # the like rows of the feed that named the loser now name the survivor, so none names a song that is gone
        assert {r["target"] for r in conn.execute("SELECT target FROM change_log WHERE kind = 'like'")} == {S1, H2}
        # the file feed's rows for the loser name the survivor
        assert {r["ref"] for r in conn.execute("SELECT ref FROM file_log")} <= live_refs(conn)


# ------------------------------------------------------------------------------------------------------------------ safety


def test_the_second_run_is_a_no_op_and_takes_no_backup(seeded: Database, caplog: pytest.LogCaptureFixture) -> None:
    refmerge.repair(seeded)
    backups = sorted(seeded.backups.glob("*"))
    state = dump(seeded)

    with caplog.at_level(logging.INFO, logger="encore_server.refmerge"):
        again = refmerge.repair(seeded)

    assert again.merged == [] and again.failed is False and again.backup is None
    assert {frozenset({h.survivor, h.loser}) for h in again.held} == HELD  # still held, still said
    assert dump(seeded) == state
    assert sorted(seeded.backups.glob("*")) == backups


def test_it_takes_its_own_backup_first_keeps_it_and_says_where(seeded: Database, caplog: pytest.LogCaptureFixture) -> None:
    before = dump(seeded)

    with caplog.at_level(logging.INFO, logger="encore_server.refmerge"):
        report = refmerge.repair(seeded)

    assert report.backup is not None and report.backup.parent == seeded.backups and report.backup.is_file()
    assert "before-ref-merge" in report.backup.name
    assert str(report.backup) in caplog.text
    # the copy is the database as it was: open it and compare
    assert dump(Database(report.backup)) == before


def test_held_pairs_are_logged_at_info_on_every_start_and_are_not_a_failure(
    seeded: Database, caplog: pytest.LogCaptureFixture
) -> None:
    for _ in range(2):
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="encore_server.refmerge"):
            report = refmerge.repair(seeded)
        held = [r for r in caplog.records if "held" in r.getMessage() and r.levelno == logging.INFO]
        assert len(held) >= len(HELD)
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert report.failed is False
    text = caplog.text
    for pair in HELD:
        assert all(ref in text for ref in pair)  # ids, so the line can be looked up; no titles


def test_nothing_to_merge_takes_no_backup_and_writes_nothing(db: Database) -> None:
    with db.tx() as c:
        add_ref(c, S1, "Alone", ["Ana Vale"])
        add_file(c, S1, "nd-1", 1, source="library", path="a.opus")
    state = dump(db)

    report = refmerge.repair(db)

    assert report.merged == [] and report.held == [] and report.backup is None and dump(db) == state
    assert not db.backups.exists() or list(db.backups.glob("*")) == []


def test_a_failure_half_way_rolls_everything_back_and_does_not_raise(
    seeded: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    before = dump(seeded)
    real = refmerge._merge_pair
    calls: list[str] = []

    def failing(conn: sqlite3.Connection, survivor: str, loser: str) -> None:
        calls.append(loser)
        if len(calls) == 3:
            raise sqlite3.OperationalError("disk I/O error (injected)")
        real(conn, survivor, loser)

    monkeypatch.setattr(refmerge, "_merge_pair", failing)

    with caplog.at_level(logging.INFO, logger="encore_server.refmerge"):
        report = refmerge.repair(seeded)

    assert len(calls) == 3 and report.failed is True and report.merged == []
    assert dump(seeded) == before  # two merges had been made inside the transaction: none of it is left
    assert report.backup is not None and report.backup.is_file()  # the copy was taken before the attempt
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]  # the failure is logged, with its cause


def test_a_failed_backup_means_no_merge(seeded: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    before = dump(seeded)

    def no_room(label: str) -> Path:
        raise sqlite3.OperationalError("database or disk is full (injected)")

    monkeypatch.setattr(seeded, "backup", no_room)

    report = refmerge.repair(seeded)

    assert report.failed is True and report.merged == [] and dump(seeded) == before


def test_the_repair_runs_at_start_up_before_anything_else_and_a_failure_does_not_stop_the_server(
    tmp_path: Path, db: Database, verifier: FakeVerifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(db)
    settings = Settings(
        data_dir=db.path.parent, music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )

    app = create_app(settings, verifier=verifier, db=db)

    assert duplicates(db) == 3  # done by the time the app exists: before any thread of the lifespan starts
    with TestClient(app) as client:
        assert client.get(f"{V1}/info").status_code == 200

    broken = Database(tmp_path / "other" / "encore.db")
    broken.migrate()
    seed(broken)
    before = dump(broken)

    def explode(conn: sqlite3.Connection, survivor: str, loser: str) -> None:
        raise RuntimeError("injected")

    monkeypatch.setattr(refmerge, "_merge_pair", explode)
    other = Settings(
        data_dir=broken.path.parent, music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(other, verifier=verifier, db=broken)) as client:
        assert client.get(f"{V1}/info").status_code == 200  # the server starts, and says what happened in its log
    # nothing of the people's data changed (the server wrote its own key into `setting` when it started: that is not part of the repair)
    assert {t: rows for t, rows in dump(broken).items() if t != "setting"} == {
        t: rows for t, rows in before.items() if t != "setting"
    }


# ------------------------------------------------------------------------------------------------------------------ nothing comes back


def tagged(song_id: str, title: str, artist: str, **extra: Any) -> dict[str, Any]:
    """A file as the music server lists it, the way the old keeper's tags described it."""
    return {
        "id": song_id,
        "title": title,
        "artist": artist,
        "artists": [{"name": artist}],
        "album": "[Unknown Album]",
        "duration": 261,
        "path": f"{artist}/[Unknown Album]/{title}.opus",
        "suffix": "opus",
        "bitRate": 128,
        **extra,
    }


def test_a_scan_after_the_repair_creates_no_ref_and_keeps_one_song_one_ref(seeded: Database) -> None:
    refmerge.repair(seeded)
    with seeded.read() as conn:
        count = conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0]
    library_now = FakeLibrary(
        [
            tagged("nd-1", "Neon Harbor", "Ana Vale, Bo Lin, Cy Mar"),
            tagged("nd-2", "Quiet Orbit", "Dee Roy", duration=212),
            tagged("nd-3", "Paper Moon", "Eli Ko"),
            tagged("nd-4", "Glass Tide", "Fay Gu"),
            tagged("nd-5", "Triple Echo", "Gus Ha"),
            tagged("nd-6", "Twin Signal", "Ivy Jo"),
            tagged("nd-7", "Shared Shelf", "Kai Lu"),
            tagged("nd-8", "Late Entry", "Lia Mo"),
        ]
    )

    report = link_library(seeded, library_now)
    again = link_library(seeded, library_now)

    assert (report.new_refs, again.new_refs) == (0, 0)
    with seeded.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0] == count
        assert refs.get_ref(conn, S3)["album"] is None  # the scan did not give the survivor the placeholder back either
    assert duplicates(seeded) == 3


def test_a_loser_described_again_the_way_it_was_lands_on_the_survivor_and_makes_no_ref(seeded: Database) -> None:
    refmerge.repair(seeded)
    with seeded.read() as conn:
        count = conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0]
    again = [  # each loser as its own description said it (joined artists, its own length, the placeholder album)
        {"title": "Neon Harbor", "artists": ["Ana Vale, Bo Lin, Cy Mar"], "album": "[Unknown Album]", "durationMs": 261000},
        {"title": "Quiet Orbit", "artists": ["Dee Roy"], "durationMs": 212000, "album": "Orbit"},  # 12 s away from the survivor's
        {"title": "Paper Moon", "artists": ["Eli Ko"], "album": "[Unknown Album]"},
        {"title": "Triple Echo", "artists": ["Gus Ha"], "album": "[Unknown Album]"},
        {"title": "Late Entry", "artists": ["Lia Mo"]},
    ]

    with seeded.tx() as conn:
        found = [refs.resolve(conn, item) for item in again]

    assert [r["id"] for r in found] == [S1, S2, S3, T1, R1]
    with seeded.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0] == count
        assert refs.get_ref(conn, S3)["album"] is None  # `_enrich` does not hand the placeholder over either
        assert refs.get_ref(conn, S1)["album"] == "Real Album"


def test_a_merged_ref_is_found_by_the_ids_it_had(db: Database) -> None:
    with db.tx() as c:
        add_ref(c, S1, "By Ids", ["Ana Vale"])
        add_ref(c, L1, "By Ids", ["Ana Vale"], isrc="GBAAA0000005", deezer_id="55", ytm_video_id="VIDEOBYIDS1")
        add_ref(c, S2, "Another Song", ["Dee Roy"])  # a live ref that the loser's title could be mistaken for
        add_file(c, S1, "nd-1", 1, source="youtube", path="a.opus")
        add_file(c, L1, "nd-1", 2, source="library", path="b.opus")
    refmerge.repair(db)
    with db.tx() as c:  # the survivor took the ids over: take them away again to prove the TABLE answers, not the live row
        c.execute("UPDATE song_ref SET isrc = NULL, deezer_id = NULL, ytm_video_id = NULL WHERE id = ?", (S1,))
        by = [
            refs.find(c, refs.parse_item({"title": "Another Song", "artists": ["Dee Roy"], **ids}))
            for ids in ({"isrc": "GBAAA0000005"}, {"deezerId": "55"}, {"videoId": "VIDEOBYIDS1"})
        ]

    # an id of the deleted ref is stronger evidence than the name: the survivor, not the live ref the name matches
    assert [row["id"] for row in by if row is not None] == [S1, S1, S1]


def test_a_survivor_that_is_merged_in_turn_takes_the_old_tombstones_with_it(seeded: Database) -> None:
    refmerge.repair(seeded)
    with (
        seeded.tx() as c
    ):  # a new ref whose file row for `nd-1` is older than the survivor's: it becomes the survivor of the survivor
        add_ref(c, rid("sr", 50), "Neon Harbor", ["Ana Vale, Bo Lin, Cy Mar"], duration_ms=249000)
        add_file(c, rid("sr", 50), "nd-1", 1, source="library", path="Elsewhere/Neon Harbor.opus")

    report = refmerge.repair(seeded)

    assert [(p.survivor, p.loser) for p in report.merged] == [(rid("sr", 50), S1)]
    assert {
        r["old_id"]: r["into_id"] for r in q(seeded, "SELECT old_id, into_id FROM ref_merge WHERE old_id IN (?, ?)", L1, S1)
    } == {
        L1: rid("sr", 50),
        S1: rid("sr", 50),
    }
    with seeded.read() as conn:
        assert refs.canonical(conn, L1) == rid("sr", 50) and refs.canonical(conn, S1) == rid("sr", 50)
        assert refs_pointed_at(conn) - live_refs(conn) == set()


def test_canonical_follows_a_chain_and_stops_at_a_loop(db: Database) -> None:
    with db.tx() as c:
        for n, (old, into) in enumerate(((S1, S2), (S2, S3), (S3, S1)), start=1):
            c.execute("INSERT INTO ref_merge (old_id, into_id, at) VALUES (?,?,?)", (old, into, n))
        c.execute("INSERT INTO ref_merge (old_id, into_id, at) VALUES (?,?,1)", (L1, L2))
    with db.read() as conn:
        assert refs.canonical(conn, L1) == L2
        assert refs.canonical(conn, "sr_" + "0" * 26) == "sr_" + "0" * 26  # never merged: answers itself
        assert refs.canonical(conn, S1) in {S1, S2, S3}  # a damaged table (a loop) still ends
        assert refs.canonical_many(conn, [L1, L2, S3]) == {L1: L2, L2: L2, S3: refs.canonical(conn, S3)}


# ------------------------------------------------------------------------------------------------------------------ old ids on the server


@pytest.fixture()
def merged_pair(client: TestClient) -> tuple[str, str, str]:
    """A song merged away, on a running server: (survivor, loser, the person)."""
    me = client.get(f"{V1}/me", params=creds("marwa"))
    assert me.status_code == 200, me.text
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    person = one(db, "SELECT id FROM person WHERE navidrome_user = 'marwa'")
    with db.tx() as c:
        add_ref(c, S1, "Old Id", ["Ana Vale"], album="Real")
        add_ref(c, L1, "Old Id", ["Ana Vale"], album="[Unknown Album]")
        add_file(c, S1, "nd-1", 1, source="youtube", path="a.opus")
        add_file(c, L1, "nd-1", 2, source="library", path="b.opus")
    assert refmerge.repair(db).merged
    return S1, L1, str(person)


def api(client: TestClient, method: str, path: str, **kw: Any) -> Any:
    return client.request(method, f"{V1}{path}", params={**creds("marwa"), **kw.pop("params", {})}, **kw)


def test_asking_for_a_merged_song_answers_with_the_survivor(client: TestClient, merged_pair: tuple[str, str, str]) -> None:
    survivor, loser, _ = merged_pair

    body = api(client, "GET", f"/refs/{loser}").json()

    assert body["id"] == survivor and body["title"] == "Old Id"


def test_liking_and_unliking_by_the_old_id_acts_on_the_survivor(client: TestClient, merged_pair: tuple[str, str, str]) -> None:
    survivor, loser, person = merged_pair
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]

    assert api(client, "PUT", f"/likes/{loser}").json()["changed"] is True
    assert [r["target"] for r in q(db, "SELECT target FROM library_item WHERE person = ? AND kind = 'like'", person)] == [
        survivor
    ]
    assert [r["target"] for r in q(db, "SELECT target FROM change_log WHERE person = ? AND kind = 'like'", person)] == [survivor]
    assert api(client, "PUT", f"/likes/{loser}").json()["changed"] is False  # again: nothing more
    assert api(client, "DELETE", f"/likes/{loser}").json()["changed"] is True  # not a silent no-op
    assert q(db, "SELECT 1 FROM library_item WHERE person = ? AND kind = 'like'", person) == []


def test_a_queued_edit_that_adds_the_old_id_to_a_playlist_adds_the_survivor(
    client: TestClient, merged_pair: tuple[str, str, str]
) -> None:
    survivor, loser, _ = merged_pair
    playlist = rid("pl", 77)
    assert api(client, "POST", "/playlists", json={"id": playlist, "name": "Mine"}).status_code == 201

    added = api(client, "POST", f"/playlists/{playlist}/entries", json={"songs": [{"ref": loser}, {"ref": survivor}]})

    assert added.status_code == 201
    assert [e["ref"] for e in api(client, "GET", f"/playlists/{playlist}").json()["entries"]] == [survivor, survivor]


def test_a_play_reported_with_the_old_id_is_the_survivors(client: TestClient, merged_pair: tuple[str, str, str]) -> None:
    survivor, loser, person = merged_pair
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]

    response = api(client, "POST", "/plays", json={"id": "p-1", "ref": loser, "msPlayed": 120000})

    assert response.status_code == 201
    assert [r["ref"] for r in q(db, "SELECT ref FROM play_event WHERE person = ?", person)] == [survivor]


def test_a_playback_state_written_with_the_old_id_is_stored_with_the_survivor(
    client: TestClient, merged_pair: tuple[str, str, str]
) -> None:
    survivor, loser, _ = merged_pair

    response = api(
        client, "PUT", "/playback", json={"rev": 0, "ref": loser, "queue": [loser, survivor, loser], "index": 1, "playing": False}
    )

    assert response.status_code == 200, response.text
    state = response.json()["state"]
    assert state["ref"] == survivor and state["queue"] == [survivor, survivor, survivor] and state["index"] == 1
    assert api(client, "GET", "/playback").json()["state"]["queue"] == [survivor] * 3


def test_a_saved_release_that_names_the_old_id_saves_the_survivor_once(
    client: TestClient, merged_pair: tuple[str, str, str]
) -> None:
    survivor, loser, person = merged_pair
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]

    response = api(client, "PUT", "/saved-albums/alb-9", json={"refs": [loser, survivor]})

    assert response.status_code == 200, response.text
    assert [r["ref"] for r in q(db, "SELECT ref FROM saved_album_ref WHERE person = ?", person)] == [survivor]
    assert list(response.json()["keep"]) == [survivor]


def test_keep_and_the_address_to_stream_by_the_old_id_are_the_survivors(
    client: TestClient, merged_pair: tuple[str, str, str]
) -> None:
    survivor, loser, _ = merged_pair

    assert api(client, "GET", f"/refs/{loser}/keep").json()["state"] == "kept"
    assert api(client, "POST", f"/refs/{loser}/keep").json()["state"] == "kept"
    address = api(client, "GET", f"/refs/{loser}/stream-url").json()["url"]
    assert address.startswith(f"/encore/stream/{survivor}?")  # signed for the survivor: the address a player uses


def test_a_stream_address_handed_out_for_the_loser_before_the_repair_still_plays(
    client: TestClient, merged_pair: tuple[str, str, str]
) -> None:
    """The signature is checked against the id in the address, as it was signed; only then is the id turned into the survivor's."""
    survivor, loser, person = merged_pair
    services = client.app.state.services  # type: ignore[attr-defined]
    import time

    expires = int(time.time()) + 600
    sig = sign_stream(services.stream_key, person, loser, expires)

    response = client.get(f"/encore/stream/{loser}", params={"p": person, "e": expires, "sig": sig})
    forged = client.get(f"/encore/stream/{loser}", params={"p": person, "e": expires, "sig": "0" * len(sig)})

    assert forged.status_code == 401
    # past the signature and the lookup of the song: this test server has neither YouTube nor a music server, which is the answer it gives
    assert response.status_code not in (401, 404), response.text


def test_the_player_asks_the_server_to_prepare_the_old_id_and_the_survivor_is_prepared(
    client: TestClient, merged_pair: tuple[str, str, str]
) -> None:
    survivor, loser, _ = merged_pair
    asked: list[str] = []

    class Scheduler:
        def handles(self, kind: str) -> bool:
            return kind == "prepare"

        def submit(self, kind: str, ref: str, person: str, *, conn: Any = None) -> None:
            asked.append(ref)

    client.app.state.services.scheduler = Scheduler()  # type: ignore[attr-defined]

    answer = api(client, "POST", "/refs/prepare", json={"ids": [loser, survivor]}).json()

    assert asked == [survivor] and answer["accepted"] == 1


def test_a_download_group_that_names_the_old_id_counts_the_survivor(
    merged_pair: tuple[str, str, str], client: TestClient
) -> None:
    from encore_server.keep_progress import Group, members

    survivor, loser, person = merged_pair
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    with db.tx() as c:
        c.execute("INSERT INTO library_item (person, kind, target, at) VALUES (?, 'saved_album', 'alb-old', 1)", (person,))

    with db.read() as conn:
        assert members(conn, person, Group("release", "alb-old", (loser, survivor))) == [survivor]


def test_a_made_up_id_still_fails_where_it_always_did(client: TestClient, merged_pair: tuple[str, str, str]) -> None:
    nobody = "sr_" + "Z" * 26

    assert api(client, "GET", f"/refs/{nobody}").status_code == 404
    assert api(client, "PUT", f"/likes/{nobody}").status_code == 404


def test_library_functions_resolve_the_old_id_too(seeded: Database) -> None:
    """The routes are not the only way in: the library functions themselves resolve (an import, a migration)."""
    refmerge.repair(seeded)
    with seeded.tx() as conn:
        assert library.set_item(conn, P2, "like", L2) is True  # ben never liked this song
        library.record_play(conn, P2, play_id="x", ref=L2, at=1, ms_played=5, device=None, context=None)
        state, _ = playback.put_state(conn, P2, {"rev": 0, "ref": L2, "queue": [L2]}, None)
    assert state["ref"] == S2 and state["queue"] == [S2]
    assert q(seeded, "SELECT ref FROM play_event WHERE id = 'x'")[0]["ref"] == S2
    with seeded.tx() as conn:
        # ana liked this song under the old id before the repair: taking the like away by that id takes away the one that is there now
        assert library.clear_item(conn, P1, "like", L1) is True
    assert q(seeded, "SELECT 1 FROM library_item WHERE person = ? AND kind = 'like' AND target = ?", P1, S1) == []


# ------------------------------------------------------------------------------------------------------------------ the files feed


def files(client: TestClient, **params: str) -> dict[str, Any]:
    response = api(client, "GET", "/library/files", params=params)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_the_files_feed_carries_the_merges_after_a_cursor_of_their_own(client: TestClient) -> None:
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    seed(db)
    refmerge.repair(db)
    pairs = {(r["old_id"], r["into_id"]): r["seq"] for r in q(db, "SELECT seq, old_id, into_id FROM ref_merge")}

    everything = files(client, mergesSince="0")

    assert {(m["from"], m["into"]): m["seq"] for m in everything["merges"]} == pairs
    assert everything["mergesCursor"] == str(max(pairs.values())) and everything["mergesMore"] is False
    # after the cursor of the third one only the later ones come, and the cursor stays at the end
    third = sorted(pairs.values())[2]
    later = files(client, mergesSince=str(third))
    assert [m["seq"] for m in later["merges"]] == [s for s in sorted(pairs.values()) if s > third]
    assert files(client, mergesSince=everything["mergesCursor"])["merges"] == []
    assert files(client, mergesSince=everything["mergesCursor"])["mergesCursor"] == everything["mergesCursor"]


def test_an_app_that_does_not_ask_for_merges_is_not_sent_them(client: TestClient) -> None:
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    seed(db)
    refmerge.repair(db)

    body = files(client)

    assert body["merges"] == [] and body["mergesCursor"] == "0" and body["mergesMore"] is False
    assert body["refs"]  # the rest of the answer is what it was


def test_the_merges_come_in_pages_like_the_songs_do(client: TestClient) -> None:
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    seed(db)
    refmerge.repair(db)

    first = files(client, mergesSince="0", limit="4")
    second = files(client, mergesSince=first["mergesCursor"], limit="4")

    assert len(first["merges"]) == 4 and first["mergesMore"] is True
    assert len(second["merges"]) == 2 and second["mergesMore"] is False
    assert {m["seq"] for m in first["merges"]}.isdisjoint(m["seq"] for m in second["merges"])


def test_a_bad_merges_cursor_is_refused_in_words(client: TestClient) -> None:
    response = api(client, "GET", "/library/files", params={"mergesSince": "soon"})

    assert response.status_code == 400


# ------------------------------------------------------------------------------------------------------------------ the saved real response

FIXTURE = Path(__file__).resolve().parents[3] / "app" / "test" / "fixtures" / "server" / "library-files-with-merges.json"


def test_the_files_response_with_merges_is_the_saved_fixture_the_phones_parser_reads(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-R41 T5 (one contract): the server's own test saves a REAL response, built by the real endpoint on synthetic data, and the app's parser
    reads it. When this response changes, this test fails until the file is written again (`ENCORE_WRITE_FIXTURES=1 pytest
    tests/test_ref_merge.py -k saved_fixture`) and the app's parser is changed to read it. Nothing in it is a person's data."""
    import os

    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    seed(db)
    refmerge.repair(db)
    body = files(client, mergesSince="0")
    body.pop("serverTime")  # the one value that is different every time
    text = json.dumps(body, indent=2, ensure_ascii=False) + "\n"

    if os.environ.get("ENCORE_WRITE_FIXTURES") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")

    assert FIXTURE.is_file(), "run with ENCORE_WRITE_FIXTURES=1 once to write it"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == body
    assert body["merges"] and all(set(m) == {"from", "into", "seq"} for m in body["merges"])


# ------------------------------------------------------------------------------------------------------------------ the placeholder


@pytest.mark.parametrize(
    ("album", "is_none"),
    [
        (None, True),
        ("", True),
        ("  ", True),
        ("[Unknown Album]", True),
        ("[unknown album]", True),
        ("Unknown Album", True),
        ("In Rainbows", False),
        ("[Unknown]", False),
    ],
)
def test_what_counts_as_no_album(album: str | None, is_none: bool) -> None:
    assert refs.is_placeholder_album(album) is is_none


def test_a_description_with_the_placeholder_album_does_not_fill_a_ref_that_has_none(db: Database) -> None:
    with db.tx() as conn:
        first = refs.resolve(conn, {"title": "No Album", "artists": ["Ana Vale"], "durationMs": 200000})
        again = refs.resolve(
            conn, {"title": "No Album", "artists": ["Ana Vale"], "durationMs": 200000, "album": "[Unknown Album]"}
        )
        real = refs.resolve(conn, {"title": "No Album", "artists": ["Ana Vale"], "durationMs": 200000, "album": "Real Album"})

    assert first["id"] == again["id"] == real["id"]
    assert again["album"] is None and real["album"] == "Real Album"
