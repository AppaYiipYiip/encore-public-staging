"""N-53 and N-38 in the merge of two refs' files (`refmerge._merge_files`): when are two `song_file` rows ONE file, and what the survivor takes from the loser.

The music server builds a library song's path from its tags, so two files of one song (two folders, the same tags) report ONE path: a path is a way to match two rows only when it is a REAL place on
both sides (`path_real = 1`). The same file (one id of the music server, or one real place) is one row, and the loser's key of its audio is kept when the survivor has none.
"""

from __future__ import annotations

import json
from typing import Any

from encore_server import refmerge
from encore_server.db import Database

SURVIVOR, LOSER = "sr_" + "1" * 26, "sr_" + "2" * 26


def two_refs(db: Database) -> None:
    with db.tx() as conn:
        for ref in (SURVIVOR, LOSER):
            conn.execute(
                "INSERT INTO song_ref (id, title, artists, norm_key, created_at) VALUES (?, 'Heartbeat', '[\"Nneka\"]', ?, 1)",
                (ref, "k" + ref),
            )


def add(
    conn: Any, file_id: str, ref: str, nd: str | None, path: str, *, real: int = 0, key: str | None = None, added: int = 1
) -> None:
    conn.execute(
        "INSERT INTO song_file (id, ref, navidrome_song_id, path, path_real, codec, source, preferred, added_at, meta, audio_key, audio_key_size)"
        " VALUES (?, ?, ?, ?, ?, 'opus', 'library', 1, ?, ?, ?, ?)",
        (file_id, ref, nd, path, real, added, json.dumps({"size": 100}), key, 100 if key else None),
    )


def merge(db: Database) -> list[Any]:
    with db.tx() as conn:
        refmerge._merge_files(conn, SURVIVOR, LOSER)
        return conn.execute("SELECT id, ref, navidrome_song_id, audio_key, audio_key_size FROM song_file ORDER BY id").fetchall()


def test_two_files_that_share_the_tag_built_path_are_two_rows_after_the_merge(db: Database) -> None:
    two_refs(db)
    built = "Nneka/Soul/Heartbeat.opus"
    with db.tx() as conn:
        add(conn, "sf_a", SURVIVOR, "nd-1", built)
        add(conn, "sf_b", LOSER, "nd-2", built, added=2)

    rows = merge(db)

    assert [(r["id"], r["ref"], r["navidrome_song_id"]) for r in rows] == [
        ("sf_a", SURVIVOR, "nd-1"),
        ("sf_b", SURVIVOR, "nd-2"),
    ], "two files, both the survivor's now"


def test_two_rows_with_the_same_real_place_are_one_file(db: Database) -> None:
    two_refs(db)
    with db.tx() as conn:
        add(conn, "sf_a", SURVIVOR, "nd-1", "Encore/Nneka/Heartbeat.opus", real=1)
        add(conn, "sf_b", LOSER, None, "Encore/Nneka/Heartbeat.opus", real=1, added=2)

    rows = merge(db)

    assert [(r["id"], r["ref"]) for r in rows] == [("sf_a", SURVIVOR)], "the loser's row of the same file is gone"


def test_a_real_place_and_an_unchecked_path_that_look_alike_are_not_the_same_file(db: Database) -> None:
    two_refs(db)
    with db.tx() as conn:
        add(conn, "sf_a", SURVIVOR, "nd-1", "Encore/Nneka/Heartbeat.opus", real=1)
        add(
            conn, "sf_b", LOSER, "nd-2", "Encore/Nneka/Heartbeat.opus", real=0, added=2
        )  # a tag-built path of an artist called "Encore"

    assert len(merge(db)) == 2


def test_the_survivor_takes_the_losers_key_of_the_same_file_when_it_has_none(db: Database) -> None:
    two_refs(db)
    with db.tx() as conn:
        add(conn, "sf_a", SURVIVOR, "nd-1", "A/a.opus")
        add(conn, "sf_b", LOSER, "nd-1", "B/b.opus", key="a1:" + "c" * 32, added=2)

    rows = merge(db)

    assert [(r["id"], r["audio_key"], r["audio_key_size"]) for r in rows] == [("sf_a", "a1:" + "c" * 32, 100)]


def test_the_survivors_own_key_is_never_replaced(db: Database) -> None:
    two_refs(db)
    with db.tx() as conn:
        add(conn, "sf_a", SURVIVOR, "nd-1", "A/a.opus", key="a1:" + "a" * 32)
        add(conn, "sf_b", LOSER, "nd-1", "B/b.opus", key="a1:" + "b" * 32, added=2)

    assert [r["audio_key"] for r in merge(db)] == ["a1:" + "a" * 32]
