"""P2-25 slice 3: the start-up rekey (`keyrepair.py`): the stored `norm_key` of every ref is rewritten from the ref's own text with the new fold, the refs the old
fold damaged go on the worklist (`ref_recheck`), and nothing a person has moves.

The data is SYNTHETIC and built the way the OLD server built it: the stored keys are `tests/legacy_fold.py`'s (the frozen old fold), so a test here can only pass
by doing what the repair is for. Rows are written with SQL on purpose (`refs.resolve` would now find the very matches the old fold failed to make).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from encore_server import db as db_module
from encore_server import keyrepair, library, refmerge, refs, textnorm
from encore_server.db import Database
from tests import legacy_fold as legacy

DEEZER_COVER = "https://e-cdns-images.dzcdn.net/images/cover/synthetic/500x500.jpg"
YT_COVER = "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg"


def rid(prefix: str, n: int) -> str:
    return f"{prefix}_{n:026d}"


ME, YOU = rid("pn", 1), rid("pn", 2)
# songs: the Latin control, the collapse of two Arabic songs on one ref, the Latin artist with Arabic title tails, the keeper-only Arabic song, Polish, the apostrophes
ABBA, FAIRUZ, HABIBI, KEPT_ONLY, LUKASZ, CURLY, STRAIGHT, AUDIO, MIXED_COVER, BJORK = (rid("sr", n) for n in range(1, 11))
PLAYLIST = rid("pl", 1)
# refs a test adds later: what an OLDER image (a rollback) wrote after the revision was stored, and the all-ASCII song whose old key had an empty title segment
ROLLED_BACK, ROLLED_BACK_LATIN, SLIPKNOT = (rid("sr", n) for n in (11, 12, 13))


def add_ref(conn: sqlite3.Connection, ref: str, title: str, artists: list[str], **fields: Any) -> None:
    """A ref as the OLD code stored it: its key is the old fold's."""
    row = {"cover_url": None, "cover_tried_at": None, "deezer_id": None, "duration_ms": 200_000, **fields}
    conn.execute(
        "INSERT INTO song_ref (id, title, artists, duration_ms, deezer_id, cover_url, cover_tried_at, norm_key, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            ref,
            title,
            json.dumps(artists, ensure_ascii=False),
            row["duration_ms"],
            row["deezer_id"],
            row["cover_url"],
            row["cover_tried_at"],
            legacy.norm_key(artists[0], title),
            1000 + int(ref[3:]),
        ),
    )


def add_file(conn: sqlite3.Connection, ref: str, nd: str, *, source: str = "library") -> str:
    file_id = f"sf_{int(ref[3:]):013d}{int(nd.split('-')[1]):013d}"
    conn.execute(
        "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, bitrate_kbps, source, preferred, added_at, meta) VALUES (?,?,?,?,?,?,?,1,?,?)",
        (file_id, ref, nd, f"music/{nd}.opus", "opus", 128, source, 5000 + int(nd.split("-")[1]), json.dumps({"size": 100})),
    )
    return file_id


def seed(db: Database) -> None:
    with db.tx() as c:
        for person, name in ((ME, "ana"), (YOU, "ben")):
            c.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES (?,?,?,1)", (person, name, name))
        add_ref(c, ABBA, "Dancing Queen", ["ABBA"], cover_url=DEEZER_COVER, cover_tried_at=10, deezer_id="777")
        # the collapse: two different Arabic songs of one artist were ONE ref (key `||`) holding both files; its cover is the one name-match of a pass
        add_ref(c, FAIRUZ, "سألوني الناس", ["فيروز"], cover_url=DEEZER_COVER, cover_tried_at=11)
        add_file(c, FAIRUZ, "nd-1")
        add_file(c, FAIRUZ, "nd-2")
        add_ref(
            c, HABIBI, "Habibi يا نور", ["Fairuz"], cover_url=YT_COVER, cover_tried_at=12
        )  # key `fairuz|habibi|`: not empty, still damaged
        add_file(c, HABIBI, "nd-3")
        # an Arabic song only the keeper has: suspect, but a keeper file is never re-judged, so it is not on the worklist; its cover is voided all the same
        add_ref(c, KEPT_ONLY, "أغنية", ["فيروز"], cover_url=DEEZER_COVER, cover_tried_at=13)
        add_file(c, KEPT_ONLY, "nd-4", source="youtube")
        add_ref(
            c, LUKASZ, "Łódź", ["Łukasz"], cover_url=DEEZER_COVER, cover_tried_at=14, deezer_id="888"
        )  # identified by the catalogue: its cover stays
        add_file(c, LUKASZ, "nd-5")
        add_ref(c, CURLY, "Don’t Stop", ["Artist"])  # old key `artist|dont stop|`
        add_ref(c, STRAIGHT, "Don't Stop", ["Artist"])  # old key `artist|don t stop|`: the same song, two refs (they stay two)
        add_ref(
            c, AUDIO, "Official Video", ["X"]
        )  # old key `x||`: all ASCII, but its stored key has an EMPTY segment, which is the second reason it is suspect
        add_ref(c, MIXED_COVER, "Hello", ["Adele"])
        add_ref(c, BJORK, "Hyperballad", ["Bjørk"], cover_url=DEEZER_COVER, cover_tried_at=15)  # old key `bjrk|hyperballad|`
        add_file(c, BJORK, "nd-6")
        # what people have
        for who in (ME, YOU):
            library.set_item(c, who, "like", FAIRUZ)
        library.set_item(c, ME, "like", ABBA)
        c.execute("INSERT INTO playlist (id, owner, name, created_at, updated_at) VALUES (?,?,?,1,1)", (PLAYLIST, ME, "mine"))
        for n, ref in enumerate((FAIRUZ, ABBA, HABIBI), start=1):
            c.execute(
                "INSERT INTO playlist_entry (id, playlist, position, ref, added_by, at) VALUES (?,?,?,?,?,1)",
                (rid("pe", n), PLAYLIST, n, ref, ME),
            )
        for n, ref in enumerate((FAIRUZ, FAIRUZ, ABBA), start=1):
            c.execute(
                "INSERT INTO play_event (id, person, ref, at, ms_played) VALUES (?,?,?,?,1000)", (rid("pv", n), ME, ref, 100 + n)
            )
        # tombstones of the old fold, and a retired ref
        for n, (old, key) in enumerate(
            [
                ("sr_gone1", "||"),
                ("sr_gone2", "fairuz||"),
                ("sr_gone3", "abba|waterloo|"),
                ("sr_gone4", "bjrk|hyperballad|"),
                ("sr_gone5", None),
                ("sr_gone6", "|habibi|"),
            ],
            start=1,
        ):
            c.execute("INSERT INTO ref_merge (old_id, into_id, at, norm_key) VALUES (?,?,?,?)", (old, ABBA, 50 + n, key))
        c.execute("INSERT INTO ref_gone (ref_id, at) VALUES ('sr_retired', 60)")


def snapshot(db: Database, *, without_key: bool = True) -> dict[str, list[tuple[Any, ...]]]:
    """Every table a person's data lives in, whole (the rekey may change `song_ref.norm_key`, `ref_merge.norm_key` and the voided covers, nothing else)."""
    out: dict[str, list[tuple[Any, ...]]] = {}
    with db.read() as conn:
        for table in (
            "library_item",
            "playlist",
            "playlist_entry",
            "play_event",
            "ref_gone",
            "song_file",
            "playback_state",
            "work_item",
            "import_entry",
            "saved_album_ref",
        ):
            out[table] = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]  # noqa: S608 - fixed names
        columns = [
            r["name"]
            for r in conn.execute("PRAGMA table_info(song_ref)")
            if r["name"] not in ("norm_key", "cover_url", "cover_tried_at")
        ]
        out["song_ref"] = [tuple(r) for r in conn.execute(f"SELECT {', '.join(columns)} FROM song_ref ORDER BY id")]  # noqa: S608
        out["ref_merge"] = [
            tuple(r)
            for r in conn.execute(
                "SELECT seq, old_id, into_id, at, isrc, deezer_id, ytm_video_id, duration_ms FROM ref_merge ORDER BY seq"
            )
        ]
    return out


def key_of(db: Database, ref: str) -> str:
    with db.read() as conn:
        return str(conn.execute("SELECT norm_key FROM song_ref WHERE id = ?", (ref,)).fetchone()[0])


def worklist(db: Database) -> set[str]:
    with db.read() as conn:
        return {r["ref"] for r in conn.execute("SELECT ref FROM ref_recheck")}


def revision(db: Database) -> str | None:
    with db.read() as conn:
        row = conn.execute("SELECT value FROM setting WHERE key = 'textnorm_revision'").fetchone()
    return None if row is None else str(row["value"])


@pytest.fixture()
def old_world(db: Database) -> Database:
    seed(db)
    return db


# ---------------------------------------------------------------------------------------------------------------------------------------------------


def test_the_world_is_what_the_old_fold_made(old_world: Database) -> None:
    """The setup itself: the damage is really there (so the tests below can only pass by repairing it)."""
    assert key_of(old_world, FAIRUZ) == "||"
    assert key_of(old_world, HABIBI) == "fairuz|habibi|"
    assert key_of(old_world, LUKASZ) == "ukasz|odz|"
    assert key_of(old_world, AUDIO) == "x||"
    assert revision(old_world) is None


def test_every_key_is_rewritten_from_the_refs_own_text(old_world: Database) -> None:
    report = keyrepair.repair(old_world)
    assert report.failed is False and report.ran is True
    with old_world.read() as conn:
        for row in conn.execute("SELECT id, title, artists, norm_key FROM song_ref"):
            assert row["norm_key"] == refs.norm_key(refs.lead_artist(row["artists"]), row["title"]), row["id"]
    assert key_of(old_world, FAIRUZ) == "فيروز|سالوني الناس|"
    assert key_of(old_world, HABIBI) == "fairuz|habibi يا نور|"
    assert key_of(old_world, LUKASZ) == "lukasz|lodz|"
    assert key_of(old_world, BJORK) == "bjork|hyperballad|"
    assert key_of(old_world, AUDIO) == "x|official video|"
    assert key_of(old_world, ABBA) == "abba|dancing queen|", "a key made of ASCII is what it was"


def test_two_refs_that_now_share_a_key_stay_two(old_world: Database) -> None:
    """A rewrite NEVER merges (identity by name afterwards is what B-37 was): the apostrophe pair now has ONE key and two refs."""
    keyrepair.repair(old_world)
    assert key_of(old_world, CURLY) == key_of(old_world, STRAIGHT) == "artist|don t stop|"
    with old_world.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref WHERE id IN (?, ?)", (CURLY, STRAIGHT)).fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM ref_merge").fetchone()[0] == 6, "no tombstone is made by a rewrite"


def test_the_worklist_is_exactly_the_suspect_refs_that_have_a_library_file(old_world: Database) -> None:
    """Suspect, for either of two reasons: the ref's own artist or title did not survive the OLD fold (decided from the text: `fairuz|habibi|` is not empty and is
    still damaged), or its STORED key has an empty artist or title segment (`x||`: all ASCII, and still a key that matched every other song of the artist).
    On the worklist = and it holds a library file. The keeper's own file is never re-judged."""
    report = keyrepair.repair(old_world)
    assert worklist(old_world) == {FAIRUZ, HABIBI, LUKASZ, BJORK}
    assert report.suspect == 6, (
        "the four above, the keeper-only Arabic song and the all-ASCII `x||` (no file: not on the worklist)"
    )
    assert report.worklist == 4
    with old_world.read() as conn:
        assert conn.execute("SELECT moved FROM ref_recheck WHERE ref = ?", (FAIRUZ,)).fetchone()["moved"] == 0


def test_nothing_a_person_owns_or_a_tombstone_can_find_by_id_moves(old_world: Database) -> None:
    before = snapshot(old_world)
    keyrepair.repair(old_world)
    after = snapshot(old_world)
    assert after == before, (
        "likes, entries, plays, the files, ref_gone, every id of ref_merge and every other column of song_ref are what they were"
    )


def test_a_tombstone_with_an_empty_artist_or_title_segment_is_set_to_null_and_the_others_stay(old_world: Database) -> None:
    """Its key can never be found again (no new key has an empty segment); its ids keep working. The version segment is EMPTY in nearly every key
    (`abba|waterloo|`): it is never what makes a key degenerate."""
    report = keyrepair.repair(old_world)
    with old_world.read() as conn:
        keys = {r["old_id"]: r["norm_key"] for r in conn.execute("SELECT old_id, norm_key FROM ref_merge")}
        assert refs.canonical(conn, "sr_gone1") == ABBA
    assert keys == {
        "sr_gone1": None,
        "sr_gone2": None,
        "sr_gone3": "abba|waterloo|",
        "sr_gone4": "bjrk|hyperballad|",  # stale dead weight for a letter the old fold dropped: never a wrong answer
        "sr_gone5": None,
        "sr_gone6": None,
    }
    assert report.tombstones_nulled == 3


def test_the_deezer_cover_of_a_suspect_ref_with_no_catalogue_id_is_voided_and_the_finder_asks_again(old_world: Database) -> None:
    """Every suspect ref (not only the worklist): one Deezer hit matched every Arabic song, and a ref the catalogue identified keeps its picture."""
    report = keyrepair.repair(old_world)
    with old_world.read() as conn:
        rows = {r["id"]: r for r in conn.execute("SELECT id, cover_url, cover_tried_at FROM song_ref")}
    assert rows[FAIRUZ]["cover_url"] is None and rows[FAIRUZ]["cover_tried_at"] is None
    assert rows[KEPT_ONLY]["cover_url"] is None and rows[KEPT_ONLY]["cover_tried_at"] is None
    assert rows[BJORK]["cover_url"] is None, "extended Latin was damaged too (the cover finder compared `bjrk` with `bjrk`)"
    assert rows[LUKASZ]["cover_url"] == DEEZER_COVER, "a deezer_id: the catalogue identified it"
    assert rows[ABBA]["cover_url"] == DEEZER_COVER, "a Latin ref keeps its picture"
    assert rows[HABIBI]["cover_url"] == YT_COVER, "not a Deezer address: not the finder's"
    assert report.covers_voided == 3


def test_a_voided_cover_is_announced_to_the_phones_that_hold_the_song(old_world: Database) -> None:
    with old_world.read() as conn:
        files_before = conn.execute("SELECT COUNT(*) FROM file_log WHERE ref = ?", (KEPT_ONLY,)).fetchone()[0]
        changes_before = conn.execute("SELECT COUNT(*) FROM change_log WHERE target = ?", (FAIRUZ,)).fetchone()[0]
    keyrepair.repair(old_world)
    with old_world.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM file_log WHERE ref = ?", (FAIRUZ,)).fetchone()[0] >= 1, (
            "it has files: the files feed says so"
        )
        assert conn.execute("SELECT COUNT(*) FROM file_log WHERE ref = ?", (KEPT_ONLY,)).fetchone()[0] == files_before + 1
        assert conn.execute("SELECT COUNT(*) FROM change_log WHERE target = ?", (FAIRUZ,)).fetchone()[0] > changes_before, (
            "its likes are told"
        )


def test_a_suspect_ref_with_no_file_is_not_announced_to_the_files_feed(db: Database) -> None:
    """`touch_file` only when the ref has a file (the cover finder's own rule): a ref nobody keeps is not the files feed's business."""
    with db.tx() as c:
        add_ref(c, FAIRUZ, "سألوني الناس", ["فيروز"], cover_url=DEEZER_COVER, cover_tried_at=11)
    keyrepair.repair(db)
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM file_log").fetchone()[0] == 0
        assert conn.execute("SELECT cover_url FROM song_ref WHERE id = ?", (FAIRUZ,)).fetchone()[0] is None


def test_the_hostname_decides_not_a_substring(db: Database) -> None:
    with db.tx() as c:
        add_ref(c, FAIRUZ, "سألوني الناس", ["فيروز"], cover_url="https://i.ytimg.com/vi/x/dzcdn.net.jpg", cover_tried_at=1)
        add_ref(c, HABIBI, "سألوني", ["فيروز"], cover_url="https://api.deezer.com/album/1/image", cover_tried_at=1)
    keyrepair.repair(db)
    with db.read() as conn:
        covers = {r["id"]: r["cover_url"] for r in conn.execute("SELECT id, cover_url FROM song_ref")}
    assert covers[FAIRUZ] is not None
    assert covers[HABIBI] is None


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# idempotent, resumable, backed up, never stops the server


def test_the_revision_is_written_and_a_second_run_does_nothing(old_world: Database) -> None:
    first = keyrepair.repair(old_world)
    assert revision(old_world) == str(textnorm.TEXTNORM_REVISION) and first.backup is not None
    before = snapshot(old_world)
    keys = {ref: key_of(old_world, ref) for ref in (FAIRUZ, ABBA, CURLY)}
    again = keyrepair.repair(old_world)
    assert again.ran is False and again.failed is False and again.backup is None
    assert snapshot(old_world) == before
    assert {ref: key_of(old_world, ref) for ref in keys} == keys
    assert len(list(old_world.backups.glob("encore-before-key-rewrite-*.db"))) == 1, "one copy, taken once"


def test_the_copy_taken_before_the_rewrite_holds_the_old_keys(old_world: Database) -> None:
    report = keyrepair.repair(old_world)
    assert report.backup is not None and report.backup.name.startswith("encore-before-key-rewrite-")
    copy = sqlite3.connect(report.backup)
    try:
        assert copy.execute("SELECT norm_key FROM song_ref WHERE id = ?", (FAIRUZ,)).fetchone()[0] == "||"
        assert copy.execute("SELECT COUNT(*) FROM setting WHERE key = 'textnorm_revision'").fetchone()[0] == 0
    finally:
        copy.close()


def test_a_database_with_no_refs_takes_no_copy_and_only_writes_the_revision(db: Database) -> None:
    """Every `create_app` of every test (and every fresh install) must not write a backup."""
    report = keyrepair.repair(db)
    assert report.backup is None and report.failed is False
    assert revision(db) == str(textnorm.TEXTNORM_REVISION)
    assert not db.backups.exists() or not list(db.backups.glob("*before-key-rewrite*"))


def test_a_database_whose_keys_are_already_right_takes_no_copy(db: Database) -> None:
    """A Latin library (every key is what the new fold makes): the revision is written, nothing is copied (a copy of a big library is a minute)."""
    with db.tx() as c:
        add_ref(c, ABBA, "Dancing Queen", ["ABBA"])
    report = keyrepair.repair(db)
    assert report.backup is None and report.ran is True and report.rekeyed == 0
    assert revision(db) == str(textnorm.TEXTNORM_REVISION)


def test_a_failed_rewrite_changes_nothing_and_is_tried_again_at_the_next_start(
    old_world: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    before = snapshot(old_world)
    keys = {ref: key_of(old_world, ref) for ref in (FAIRUZ, ABBA, LUKASZ)}
    real = refs.norm_key
    calls = {"n": 0}

    def breaks_half_way(artist: str, title: str) -> str:
        calls["n"] += 1
        if calls["n"] > 6:
            raise RuntimeError("a bug in the middle of the pass")
        return real(artist, title)

    monkeypatch.setattr(refs, "norm_key", breaks_half_way)
    with caplog.at_level(logging.ERROR, logger="encore_server.keyrepair"):
        report = keyrepair.repair(old_world)  # never raises: the server must start
    assert report.failed is True and report.ran is False
    assert "FAILED" in caplog.text and "changed nothing" in caplog.text
    assert revision(old_world) is None and worklist(old_world) == set()
    assert {ref: key_of(old_world, ref) for ref in keys} == keys
    assert snapshot(old_world) == before

    monkeypatch.setattr(refs, "norm_key", real)  # the next start: the bug is fixed
    retry = keyrepair.repair(old_world)
    assert retry.ran is True and retry.failed is False
    assert key_of(old_world, FAIRUZ) == "فيروز|سالوني الناس|"
    assert revision(old_world) == str(textnorm.TEXTNORM_REVISION)


def test_a_failure_in_the_middle_of_the_transaction_rolls_back_what_was_already_written(
    old_world: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The keys, the worklist and the tombstones are written BEFORE the covers are voided: a failure there must undo them all (one transaction), and the next
    start must be able to do the whole thing (resumable by being repeatable)."""

    def boom(conn: sqlite3.Connection, ref_id: str) -> dict[str, int]:
        raise RuntimeError("the cover announcement broke after the keys were written")

    before = snapshot(old_world)
    keys = {ref: key_of(old_world, ref) for ref in (FAIRUZ, ABBA, LUKASZ, CURLY)}
    with old_world.read() as conn:
        tombstones = [tuple(r) for r in conn.execute("SELECT old_id, norm_key FROM ref_merge ORDER BY seq")]
        covers = [tuple(r) for r in conn.execute("SELECT id, cover_url, cover_tried_at FROM song_ref ORDER BY id")]
    real = library.touch_ref_holders
    monkeypatch.setattr(library, "touch_ref_holders", boom)
    with caplog.at_level(logging.ERROR, logger="encore_server.keyrepair"):
        report = keyrepair.repair(old_world)
    assert report.failed is True and report.ran is False and "changed nothing" in caplog.text
    assert report.backup is not None, "the copy was taken before the transaction and is kept (its path is in the log)"
    assert {ref: key_of(old_world, ref) for ref in keys} == keys
    assert revision(old_world) is None and worklist(old_world) == set()
    with old_world.read() as conn:
        assert [tuple(r) for r in conn.execute("SELECT old_id, norm_key FROM ref_merge ORDER BY seq")] == tombstones
        assert [tuple(r) for r in conn.execute("SELECT id, cover_url, cover_tried_at FROM song_ref ORDER BY id")] == covers
    assert snapshot(old_world) == before

    monkeypatch.setattr(library, "touch_ref_holders", real)  # the next start
    retry = keyrepair.repair(old_world)
    assert retry.ran is True and retry.failed is False and worklist(old_world) == {FAIRUZ, HABIBI, LUKASZ, BJORK}


def test_a_database_made_by_a_newer_fold_is_left_alone(old_world: Database) -> None:
    """An older server started on a newer database (a rollback): it must not rewrite keys DOWN."""
    with old_world.tx() as c:
        c.execute("INSERT INTO setting (key, value) VALUES ('textnorm_revision', ?)", (str(textnorm.TEXTNORM_REVISION + 1),))
    before = key_of(old_world, FAIRUZ)
    report = keyrepair.repair(old_world)
    assert report.ran is False and report.failed is False
    assert key_of(old_world, FAIRUZ) == before


def test_the_report_says_how_many_and_the_log_carries_ids_only(old_world: Database, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="encore_server.keyrepair"):
        keyrepair.repair(old_world)
    assert "4 refs on the worklist" in caplog.text
    assert "فيروز" not in caplog.text and "Łukasz" not in caplog.text and "Fairuz" not in caplog.text, (
        "ids and counts only: a title is a person's data"
    )


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the second reason a ref is suspect: its STORED key has an empty segment (an all-ASCII song the old fold made `slipknot||sic`)


def test_an_all_ascii_song_whose_old_key_had_an_empty_segment_is_suspect_and_goes_on_the_worklist(db: Database) -> None:
    """`(sic)` is a bracket: the old fold dropped it as a noise group and kept it only as a VERSION, so Slipknot's `(sic)` and every other Slipknot song of that kind were one
    key, `slipknot||sic`, and the library link attached a file to whichever ref came first. Nothing in the TEXT was lost (it is all ASCII), so only the stored key can say so."""
    key = legacy.norm_key("Slipknot", "(sic)")
    assert key == "slipknot||sic" and refs.key_is_degenerate(key), "the old key really is empty in the title segment"
    assert not keyrepair._lost_by_old_fold("(sic)") and not keyrepair._lost_by_old_fold("Slipknot"), (
        "and the text alone would not have said so"
    )
    with db.tx() as c:
        add_ref(c, SLIPKNOT, "(sic)", ["Slipknot"], cover_url=DEEZER_COVER, cover_tried_at=3)
        add_file(c, SLIPKNOT, "nd-1")
    report = keyrepair.repair(db)
    assert worklist(db) == {SLIPKNOT} and report.suspect == 1 and report.worklist == 1
    assert key_of(db, SLIPKNOT) == "slipknot|sic|sic"
    with db.read() as conn:
        assert conn.execute("SELECT cover_url FROM song_ref WHERE id = ?", (SLIPKNOT,)).fetchone()[0] is None, (
            "the Deezer picture it was matched to by an empty title is voided like the others"
        )


def test_a_latin_ref_whose_stored_key_is_healthy_is_not_suspect(db: Database) -> None:
    """The control of the second reason: an ordinary song, all ASCII, with a healthy old key, a library file and a catalogue picture, is left entirely alone. The rewrite
    is a no-op for it (its key is what it was)."""
    assert not refs.key_is_degenerate(legacy.norm_key("ABBA", "Dancing Queen"))
    with db.tx() as c:
        add_ref(
            c, ABBA, "Dancing Queen", ["ABBA"], cover_url=DEEZER_COVER, cover_tried_at=10
        )  # no catalogue id: the cover rule would void it if it were suspect
        add_file(c, ABBA, "nd-1")
    report = keyrepair.repair(db)
    assert (
        report.suspect == 0
        and report.worklist == 0
        and report.covers_voided == 0
        and report.rekeyed == 0
        and report.backup is None
    )
    assert worklist(db) == set()
    with db.read() as conn:
        assert conn.execute("SELECT cover_url FROM song_ref WHERE id = ?", (ABBA,)).fetchone()[0] == DEEZER_COVER


def test_each_reason_is_enough_on_its_own(db: Database) -> None:
    """The text alone (`fairuz|habibi|`: the key is NOT empty) and the key alone (`slipknot||sic`: the text is ASCII) each put a ref on the worklist."""
    assert not refs.key_is_degenerate(legacy.norm_key("Fairuz", "Habibi يا نور"))
    with db.tx() as c:
        add_ref(c, HABIBI, "Habibi يا نور", ["Fairuz"])
        add_file(c, HABIBI, "nd-1")
        add_ref(c, SLIPKNOT, "(sic)", ["Slipknot"])
        add_file(c, SLIPKNOT, "nd-2")
    keyrepair.repair(db)
    assert worklist(db) == {HABIBI, SLIPKNOT}


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the plan runs at EVERY start (the rollback hole), writes only when it finds something, and never judges again what it has already judged


def _copies(db: Database) -> list[Path]:
    return db.copies("before-key-rewrite")


def _refuse_every_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """A start that must not write: opening a transaction or taking a copy fails the test (the repair catches every error, so it would show as `failed`)."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a start with nothing to repair must write nothing and take no copy")

    monkeypatch.setattr(Database, "tx", refuse)
    monkeypatch.setattr(Database, "backup", refuse)


def test_a_start_after_a_finished_repair_writes_nothing_and_takes_no_copy(
    old_world: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyrepair.repair(old_world)
    before = snapshot(old_world)
    keys = {ref: key_of(old_world, ref) for ref in (FAIRUZ, ABBA, CURLY, AUDIO)}
    _refuse_every_write(monkeypatch)
    again = keyrepair.repair(old_world)
    assert again.failed is False and again.ran is False and again.backup is None and again.rekeyed == 0
    assert snapshot(old_world) == before and {ref: key_of(old_world, ref) for ref in keys} == keys


def test_an_older_image_that_wrote_old_fold_keys_after_the_revision_was_stored_is_repaired_at_the_next_start(
    old_world: Database,
) -> None:
    """The rollback hole: the revision says the keys are right, an older image (a rollback) then makes new refs with the OLD fold, and the newer image starts again.
    Everything the first repair did for the refs it found, it does for these: the keys, the worklist, the picture. The refs it already repaired are not touched."""
    first = keyrepair.repair(old_world)
    assert first.backup is not None
    settled = snapshot(old_world)
    with old_world.tx() as c:
        add_ref(c, ROLLED_BACK, "يا مصطفى", ["أحمد"], cover_url=DEEZER_COVER, cover_tried_at=40)
        add_file(c, ROLLED_BACK, "nd-9")
        add_ref(c, ROLLED_BACK_LATIN, "Hyperballad", ["Bjørk"])  # an old key, `bjrk|hyperballad|`, and no library file
    assert key_of(old_world, ROLLED_BACK) == "||" and key_of(old_world, ROLLED_BACK_LATIN) == "bjrk|hyperballad|"

    again = keyrepair.repair(old_world)

    assert again.ran is True and again.failed is False and again.rekeyed == 2
    assert key_of(old_world, ROLLED_BACK) == "احمد|يا مصطفي|", "the hamza seat and the alef maksura fold (U+0649 to yeh)"
    assert key_of(old_world, ROLLED_BACK_LATIN) == "bjork|hyperballad|"
    assert worklist(old_world) == {FAIRUZ, HABIBI, LUKASZ, BJORK, ROLLED_BACK}, (
        "the new damaged ref joins the worklist; the Latin one with no file does not"
    )
    with old_world.read() as conn:
        assert conn.execute("SELECT cover_url FROM song_ref WHERE id = ?", (ROLLED_BACK,)).fetchone()[0] is None
    assert again.backup is not None and again.backup != first.backup, "a real repair takes its own copy"
    after = snapshot(old_world)
    for table, rows in settled.items():
        if table not in ("song_ref", "song_file"):
            assert after[table] == rows, table
    assert revision(old_world) == str(textnorm.TEXTNORM_REVISION), "the revision stays what it was"


def test_a_picture_found_after_the_repair_is_not_voided_again_at_the_next_start(
    old_world: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cover finder stores a correct catalogue picture on an Arabic ref (no catalogue id); the repair must not undo it at every start."""
    keyrepair.repair(old_world)
    with old_world.tx() as c:
        c.execute("UPDATE song_ref SET cover_url = ?, cover_tried_at = 99 WHERE id = ?", (DEEZER_COVER, FAIRUZ))
    _refuse_every_write(monkeypatch)
    report = keyrepair.repair(old_world)
    assert report.failed is False and report.ran is False and report.covers_voided == 0
    with old_world.read() as conn:
        assert conn.execute("SELECT cover_url FROM song_ref WHERE id = ?", (FAIRUZ,)).fetchone()[0] == DEEZER_COVER


def test_a_ref_the_rehome_took_off_the_worklist_does_not_come_back(old_world: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    """Slice 4 judges a ref and deletes its worklist row. Its key is right by then, so the plan has nothing to say about it, however suspect its text is."""
    keyrepair.repair(old_world)
    with old_world.tx() as c:
        c.execute("DELETE FROM ref_recheck WHERE ref = ?", (FAIRUZ,))
    _refuse_every_write(monkeypatch)
    report = keyrepair.repair(old_world)
    assert report.failed is False and report.ran is False and report.worklist == 0
    assert worklist(old_world) == {HABIBI, LUKASZ, BJORK}


def test_a_database_made_by_a_newer_fold_is_not_even_looked_at(old_world: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    """An older server on a newer database (a rollback the other way round): the plan would rewrite the keys DOWN to this fold, so it does not run at all."""
    with old_world.tx() as c:
        c.execute("INSERT INTO setting (key, value) VALUES ('textnorm_revision', ?)", (str(textnorm.TEXTNORM_REVISION + 1),))

    def not_looked_at(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a database of a newer fold must not be planned against")

    monkeypatch.setattr(keyrepair, "plan", not_looked_at)
    report = keyrepair.repair(old_world)
    assert report.failed is False and report.ran is False


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the copy: reused while the repair has not succeeded, fresh for a later real repair, and never more than KEEP_COPIES of them


def test_a_failing_repair_at_every_start_keeps_one_copy_and_logs_once_per_start(
    old_world: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(conn: sqlite3.Connection, ref_id: str) -> dict[str, int]:
        raise RuntimeError("a bug that stays")

    real = library.touch_ref_holders
    monkeypatch.setattr(library, "touch_ref_holders", boom)
    reports = []
    with caplog.at_level(logging.INFO, logger="encore_server.keyrepair"):
        for _ in range(5):
            caplog.clear()
            reports.append(keyrepair.repair(old_world))  # never raises
            assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 1, (
                "one ERROR line per start, not one per row or per retry"
            )
    assert all(r.failed for r in reports) and len(_copies(old_world)) == 1, "five starts, one copy"
    assert {r.backup for r in reports} == {_copies(old_world)[0]}, "every start names the same copy"
    assert revision(old_world) is None and worklist(old_world) == set()

    monkeypatch.setattr(library, "touch_ref_holders", real)  # the bug is fixed in the next image
    repaired = keyrepair.repair(old_world)
    assert repaired.ran is True and repaired.backup == reports[0].backup and len(_copies(old_world)) == 1, (
        "the repair that finally runs used the same copy"
    )
    assert repaired.backup is not None
    copy = sqlite3.connect(repaired.backup)
    try:
        assert copy.execute("SELECT norm_key FROM song_ref WHERE id = ?", (FAIRUZ,)).fetchone()[0] == "||", (
            "and it still holds the keys from before"
        )
    finally:
        copy.close()


def test_a_second_real_repair_after_a_rollback_is_not_blocked_by_an_old_copy_and_the_copies_are_capped(
    old_world: Database,
) -> None:
    """The copy of a repair that SUCCEEDED is spent (it was taken for that repair). A rollback and a new repair take a new one, and the pile never grows past
    `KEEP_COPIES`, so a rollback loop cannot fill the disk. Copies of other repairs (a migration's, the merge's) are never pruned."""
    old_world.backups.mkdir(parents=True, exist_ok=True)
    others = [
        old_world.backups / "encore-before-ref-merge-20200101-000000.db",
        old_world.backups / "encore-9.9-20200101-000000.db",
    ]
    for other in others:
        other.write_bytes(b"not a key copy")
    first = keyrepair.repair(old_world).backup
    assert first is not None
    taken = [first]
    for n in range(2, 8):  # rollback rounds: an older image keys a new Arabic song the old way, the newer image starts again
        with old_world.tx() as c:
            add_ref(c, rid("sr", 100 + n), f"أغنية {n}", ["فيروز"])
        report = keyrepair.repair(old_world)
        assert report.ran is True and report.failed is False and report.rekeyed == 1, n
        assert report.backup is not None and report.backup not in taken, "the spent copy of the earlier repair is not reused"
        taken.append(report.backup)
        assert len(_copies(old_world)) <= keyrepair.KEEP_COPIES
    assert _copies(old_world) == taken[-keyrepair.KEEP_COPIES :], "the newest copies are the ones kept"
    assert all(other.exists() for other in others)
    copy = sqlite3.connect(taken[-1])
    try:
        assert copy.execute("SELECT norm_key FROM song_ref WHERE id = ?", (rid("sr", 107),)).fetchone()[0] == legacy.norm_key(
            "فيروز", "أغنية 7"
        ), "the newest copy is from before THAT repair"
    finally:
        copy.close()


def test_a_repair_that_never_settles_cannot_pile_up_copies(old_world: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever the cause (a fold that depends on something it should not), a repair that finds something to do at EVERY start and succeeds every time takes a copy every
    time: the cap, not the logic, is what keeps the disk safe."""
    real_plan = keyrepair.plan

    def never_settles(conn: sqlite3.Connection, **kwargs: Any) -> keyrepair.Plan:
        result = real_plan(conn, **kwargs)
        result.worklist.add(ABBA)  # something to write at every start
        return result

    monkeypatch.setattr(keyrepair, "plan", never_settles)
    for _ in range(9):
        report = keyrepair.repair(old_world)
        assert report.failed is False and report.backup is not None
    assert len(_copies(old_world)) == keyrepair.KEEP_COPIES


def test_the_copy_a_finished_repair_used_is_recorded_with_it_in_one_transaction(old_world: Database) -> None:
    report = keyrepair.repair(old_world)
    assert report.backup is not None
    with old_world.read() as conn:
        used = conn.execute("SELECT value FROM setting WHERE key = 'textnorm_backup_used'").fetchone()
    assert used is not None and used["value"] == report.backup.name


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# THE BACKUP IS NEVER PRUNED AWAY, and the repair never writes without it (the last round of PR #110: a reviewer reproduced a repair that ran with NO backup).
# A copy's name carries the LOCAL time of the clock that made it, and a clock goes back; ordering the copies by their names then pruned the copy just taken.


class _StampsOf:
    """Stands in for the `time` module INSIDE `encore_server.db` only: the stamp of the next copy is the one given, everything else is the real clock."""

    def __init__(self, stamp: str) -> None:
        self._stamp = stamp

    def strftime(self, *_args: object) -> str:
        return self._stamp

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


@contextmanager
def _clock_says(stamp: str | None) -> Iterator[None]:
    """The copies made inside the block are named for `stamp` (None: the real clock)."""
    if stamp is None:
        yield
        return
    real = db_module.time
    db_module.time = _StampsOf(stamp)  # type: ignore[assignment]
    try:
        yield
    finally:
        db_module.time = real


def _a_repair_at(db: Database, n: int, stamp: str | None, *, mtime: float | None = None) -> keyrepair.Report:
    """One REAL repair round: an older image keyed one more Arabic song the old way (so there is something to repair), the newer image starts, the clock says `stamp`."""
    if n > 1:
        with db.tx() as c:
            add_ref(c, rid("sr", 100 + n), f"أغنية {n}", ["فيروز"])
    with _clock_says(stamp):
        report = keyrepair.repair(db)
    assert report.ran is True and report.failed is False and report.backup is not None, (n, stamp)
    if mtime is not None:  # what the operating system stamps from the same wall clock
        os.utime(report.backup, (mtime, mtime))
    return report


def _used(db: Database) -> str | None:
    with db.read() as conn:
        row = conn.execute("SELECT value FROM setting WHERE key = ?", (keyrepair.BACKUP_USED_SETTING,)).fetchone()
    return None if row is None else str(row["value"])


def _pending(db: Database) -> str | None:
    with db.read() as conn:
        row = conn.execute("SELECT value FROM setting WHERE key = ?", ("textnorm_backup_pending",)).fetchone()
    return None if row is None else str(row["value"])


_ONE_DAY = 24 * 3600
CLOCK_STEPS = [
    pytest.param(
        ["20991231-120000", "20991231-120001", "20991231-120002"],
        None,
        _ONE_DAY,
        id="the clock was a day ahead and was set back (the reviewers case)",
    ),
    pytest.param(
        ["20261101-015000", "20261101-015500", "20261101-015800"],
        "20261101-010200",
        0,
        id="the end of daylight saving time: the hour repeats",
    ),
    pytest.param(
        ["20261117-120010", "20261117-120011", "20261117-120012"],
        "20261117-120005",
        0,
        id="a time sync steps the clock back a few seconds",
    ),
    pytest.param(
        ["20261101-015000", "20261101-015500", "20261101-010500"],
        "20261101-011000",
        0,
        id="the clock went back between two repairs: the last committed repairs copy has the OLDEST name",
    ),
]


@pytest.mark.parametrize(("earlier", "now", "ahead"), CLOCK_STEPS)
def test_the_copy_just_taken_is_never_pruned_when_the_clock_has_gone_back(
    old_world: Database, earlier: list[str], now: str | None, ahead: int
) -> None:
    """Three repairs ran while the clock said `earlier`; the clock went back; a fourth repair takes its copy. Ordered by their names the fresh copy was the OLDEST of
    four, the prune removed it, and the repair went on with a path that did not exist and logged it as kept: no backup, while docs/18 says it never runs without one.
    The files' own modification times are put in the future too (the operating system stamps them from the same clock), so a fix that ordered by mtime would fail here.
    Asserting `ran` and an existing copy (not only 'nothing was written') means the second layer cannot hide the absence of the first."""
    future = time.time() + ahead
    taken = [_a_repair_at(old_world, n, stamp, mtime=future + n if ahead else None) for n, stamp in enumerate(earlier, start=1)]
    assert all(r.backup is not None and r.backup.exists() for r in taken)

    fresh = _a_repair_at(old_world, 4, now)

    assert fresh.backup is not None and fresh.backup.is_file() and fresh.backup.stat().st_size > 0, (
        "the copy the repair relies on exists"
    )
    assert fresh.backup not in [r.backup for r in taken]
    copy = sqlite3.connect(fresh.backup)
    try:
        key = copy.execute("SELECT norm_key FROM song_ref WHERE id = ?", (rid("sr", 104),)).fetchone()[0]
        assert key == legacy.norm_key("فيروز", "أغنية 4"), "and it is from before THAT repair (the old key)"
    finally:
        copy.close()
    assert _used(old_world) == fresh.backup.name
    kept = set(_copies(old_world))
    assert len(kept) == keyrepair.KEEP_COPIES
    assert {taken[1].backup, taken[2].backup, fresh.backup} == kept, (
        "the three most recent copies in the order they were TAKEN, whatever the names say"
    )


@pytest.mark.parametrize(
    "content",
    [b"SQLite format 3\x00" + b"\x00" * 200, b"not a database at all", b""],
    ids=["a file that looks like one", "junk", "empty"],
)
def test_a_file_that_merely_sorts_newest_is_not_an_earlier_attempts_copy(old_world: Database, content: bytes) -> None:
    """The reuse used to pick the NEWEST NAME that was not the spent copy. A file named in the future (a clock that was ahead, or anything dropped in the folder) was
    then 'the copy of an attempt that did not finish', and the repair went on backed by it. Only the copy an attempt RECORDED (in its own committed write, right after
    taking it) is reused."""
    old_world.backups.mkdir(parents=True, exist_ok=True)
    stray = old_world.backups / "encore-before-key-rewrite-20991231-120002.db"
    stray.write_bytes(content)

    report = keyrepair.repair(old_world)

    assert report.ran is True and report.backup is not None and report.backup != stray
    assert report.backup.stat().st_size > 1000 and report.backup.read_bytes()[:16] == b"SQLite format 3\x00", (
        "a real copy of the database"
    )


def _a_repair_that_fails(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Makes every repair fail (a bug that stays) and returns what puts the real code back."""

    def boom(conn: sqlite3.Connection, ref_id: str) -> dict[str, int]:
        raise RuntimeError("a bug that stays")

    real = library.touch_ref_holders
    monkeypatch.setattr(library, "touch_ref_holders", boom)
    return lambda: monkeypatch.setattr(library, "touch_ref_holders", real)


def test_the_copy_an_attempt_takes_is_recorded_in_its_own_committed_write_and_cleared_by_the_repair_that_uses_it(
    old_world: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = _a_repair_that_fails(monkeypatch)
    failed = keyrepair.repair(old_world)
    assert failed.failed is True and failed.backup is not None
    assert _pending(old_world) == failed.backup.name, "the rewrite rolled back, the record of its copy did not"
    assert _used(old_world) is None and revision(old_world) is None

    fixed()
    done = keyrepair.repair(old_world)
    assert done.ran is True and done.backup == failed.backup
    assert _used(old_world) == failed.backup.name
    assert _pending(old_world) is None, "cleared in the same transaction that spent the copy"


def test_an_earlier_attempts_copy_is_reused_even_when_the_clock_has_gone_back_since(
    old_world: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = _a_repair_that_fails(monkeypatch)
    with _clock_says("20991231-120000"):
        first = keyrepair.repair(old_world)
    fixed()
    old_world.backups.mkdir(parents=True, exist_ok=True)
    (old_world.backups / "encore-before-key-rewrite-20991231-120009.db").write_bytes(b"newer by its name only")
    done = keyrepair.repair(old_world)  # the real clock: the attempt's copy is named 2099
    assert first.backup is not None and done.backup == first.backup and done.ran is True


def test_a_recorded_copy_that_is_gone_is_replaced_by_a_new_one(old_world: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = _a_repair_that_fails(monkeypatch)
    failed = keyrepair.repair(old_world)
    assert failed.backup is not None
    failed.backup.unlink()  # a Host cleaned the backups folder
    fixed()
    with _clock_says(
        "20261117-130000"
    ):  # a name of its own: a free name of a copy that was deleted could be taken again within the second
        done = keyrepair.repair(old_world)
    assert done.ran is True and done.backup is not None and done.backup.is_file() and done.backup != failed.backup
    assert _pending(old_world) is None and _used(old_world) == done.backup.name


def _spoil_the_copy(how: str) -> Any:
    """The real `_copy_for_this_repair`, then the copy goes wrong BEFORE the write: it vanishes, is emptied, or is overwritten by something that is not a database."""
    real = keyrepair._copy_for_this_repair

    def spoiled(db: Database) -> Path:
        copy = real(db)
        if how == "vanishes":
            copy.unlink()
        elif how == "is emptied":
            copy.write_bytes(b"")
        else:
            copy.write_bytes(b"this is not a database" * 50)
        return copy

    return spoiled


@pytest.mark.parametrize("how", ["vanishes", "is emptied", "is not a database"])
def test_the_repair_refuses_to_write_when_the_copy_it_was_to_rely_on_is_not_there_when_it_comes_to_write(
    old_world: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, how: str
) -> None:
    """The second layer, and the only one that can stand alone: whatever happened to the copy between the moment it was taken and the moment of the write (a prune, an
    antivirus, a Host who cleared the folder, a full disk), the repair that cannot be undone from a copy does not run. It logs ONCE, writes nothing (not the keys, not
    the worklist, not the revision), and the server goes on (it never raises)."""
    before = snapshot(old_world)
    keys = {ref: key_of(old_world, ref) for ref in (FAIRUZ, ABBA, HABIBI, AUDIO)}
    with monkeypatch.context() as patched:
        patched.setattr(keyrepair, "_copy_for_this_repair", _spoil_the_copy(how))
        with caplog.at_level(logging.INFO, logger="encore_server.keyrepair"):
            report = keyrepair.repair(old_world)  # must not raise

    assert report.failed is True and report.ran is False and report.rekeyed == 0
    assert [r.levelno for r in caplog.records if r.levelno >= logging.ERROR] == [logging.ERROR], "ONE line, not two"
    assert "copy" in "".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert {ref: key_of(old_world, ref) for ref in keys} == keys, "no key was rewritten"
    assert revision(old_world) is None and worklist(old_world) == set() and _used(old_world) is None
    assert snapshot(old_world) == before
    with old_world.read() as conn:
        assert conn.execute("SELECT cover_url FROM song_ref WHERE id = ?", (FAIRUZ,)).fetchone()[0] == DEEZER_COVER, (
            "no picture was voided"
        )
        assert conn.execute("SELECT COUNT(*) FROM ref_merge WHERE norm_key IS NULL").fetchone()[0] == 1, (
            "no tombstone key was nulled (one was NULL already)"
        )

    again = keyrepair.repair(old_world)  # the next start finds nothing it can rely on and takes a new copy
    assert again.ran is True and again.backup is not None and again.backup.is_file() and again.backup.stat().st_size > 0


def test_a_ref_the_server_makes_itself_is_never_stale_so_a_start_never_rewrites_it(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plan runs at EVERY start, so the key `refs.resolve` stores must be exactly what the plan recomputes (`refs.norm_key` of the first artist and the title as stored):
    if the two ever differed for one kind of song, every start would rewrite that ref and take a copy, for ever. Songs of every kind, made by the real code after the
    revision was written, with a library file and a catalogue picture on the Arabic one (the things a suspect ref would lose)."""
    keyrepair.repair(db)  # a fresh install writes the revision at its first start
    songs = [
        {"title": "Dancing Queen", "artists": ["ABBA"]},
        {"title": "سألوني الناس", "artists": ["فيروز"]},
        {"title": "Don’t Stop (Live)", "artists": ["Artist feat. Someone", "Someone"]},
        {"title": "愛", "artists": ["嵐"]},
        {"title": "Песнь о земле родной", "artists": ["Грай"]},
        {"title": "???", "artists": ["!!!"]},
        {"title": "(sic)", "artists": ["Slipknot"]},
        {"title": "Official Video", "artists": ["X"]},
        {"title": "   Łódź   ", "artists": ["  Łukasz "]},
        {"title": "Hyperballad - Remastered 2011", "artists": ["Björk", "Guðmundur"]},
        {"title": "x" * 400, "artists": ["y" * 400]},
    ]
    with db.tx() as c:
        made = [refs.resolve(c, {**song, "durationMs": 200_000})["id"] for song in songs]
        c.execute("UPDATE song_ref SET cover_url = ?, cover_tried_at = 5 WHERE id = ?", (DEEZER_COVER, made[1]))
        c.execute(
            "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, bitrate_kbps, source, preferred, added_at, meta) VALUES (?,?,?,?,?,?,'library',1,?,?)",
            ("sf_never_stale_1", made[1], "nd-1", "music/nd-1.opus", "opus", 128, 5000, json.dumps({"size": 100})),
        )
    _refuse_every_write(monkeypatch)
    report = keyrepair.repair(db)
    assert report.failed is False and report.ran is False and report.rekeyed == 0 and report.backup is None
    with db.read() as conn:
        assert conn.execute("SELECT cover_url FROM song_ref WHERE id = ?", (made[1],)).fetchone()[0] == DEEZER_COVER
        assert conn.execute("SELECT COUNT(*) FROM ref_recheck").fetchone()[0] == 0


def test_a_start_that_only_has_to_write_the_revision_takes_no_copy(db: Database) -> None:
    """Nothing to change but the number (an empty database, a Latin library): the revision is written and no copy is taken (a copy of a big library is a minute)."""
    report = keyrepair.repair(db)
    assert report.ran is True and report.backup is None and _copies(db) == []
    with db.read() as conn:
        assert conn.execute("SELECT 1 FROM setting WHERE key = 'textnorm_backup_used'").fetchone() is None


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the hold in the merge repair, and what a merge leaves behind


def _share_a_file(conn: sqlite3.Connection, a: str, b: str, nd: str) -> None:
    add_file(conn, a, nd)
    add_file(conn, b, nd)


def test_refmerge_holds_a_pair_when_either_ref_is_on_the_worklist(db: Database) -> None:
    """A file two refs hold may be on the WRONG one of them: merging identities on its strength would put one song's likes on another."""
    with db.tx() as c:
        add_ref(c, FAIRUZ, "سألوني الناس", ["فيروز"])
        add_ref(c, HABIBI, "Habibi يا نور", ["Fairuz"])
        add_ref(c, ABBA, "Dancing Queen", ["ABBA"])
        add_ref(c, LUKASZ, "Dancing Queen", ["ABBA "], duration_ms=201_000)
        _share_a_file(c, FAIRUZ, HABIBI, "nd-1")
        _share_a_file(c, ABBA, LUKASZ, "nd-2")
    keyrepair.repair(db)
    assert worklist(db) == {FAIRUZ, HABIBI}
    report = refmerge.repair(db)
    held = {(h.survivor, h.loser): h.reason for h in report.held}
    assert held.get((FAIRUZ, HABIBI)) == "recheck_pending"
    assert [(m.survivor, m.loser) for m in report.merged] == [(ABBA, LUKASZ)], "a pair no worklist ref is in merges as before"


@pytest.mark.parametrize("worklist_ref_is", ["the survivor", "the loser"])
@pytest.mark.parametrize("reason", ["its text was lost by the old fold", "its stored key had an empty segment"])
def test_refmerge_holds_a_pair_when_only_one_of_the_two_refs_is_on_the_worklist(
    db: Database, worklist_ref_is: str, reason: str
) -> None:
    """Each half of the guard on its own, for each of the two reasons a ref is suspect: the suspect ref (on the worklist) and a Latin ref (never suspect) hold one
    library file, and the pair is held WHICHEVER of the two the merge would keep. A guard that looks at one side only would pass the test above (both refs are on
    the worklist there), and a merge of identities is never undone."""
    latin = ABBA
    suspect, title, artists = (
        (FAIRUZ, "سألوني الناس", ["فيروز"]) if reason.startswith("its text") else (SLIPKNOT, "(sic)", ["Slipknot"])
    )
    first, second = (suspect, latin) if worklist_ref_is == "the survivor" else (latin, suspect)
    with db.tx() as c:
        add_ref(c, latin, "Dancing Queen", ["ABBA"])
        add_ref(c, suspect, title, artists, duration_ms=201_000)
        _share_a_file(c, first, second, "nd-1")  # the ref that attached the shared file first is the one the merge keeps
        c.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES (?,?,?,1)", (ME, "ana", "ana"))
        library.set_item(c, ME, "like", suspect)  # the like the held pair keeps on its own song (snapshot below)
    keyrepair.repair(db)
    assert worklist(db) == {suspect}, (
        "exactly one of the two is on the worklist (the Latin ref lost nothing in the old fold and its key is healthy)"
    )
    before = snapshot(db)

    report = refmerge.repair(db)

    assert [(h.survivor, h.loser, h.reason) for h in report.held] == [(first, second, "recheck_pending")]
    assert report.merged == [] and report.backup is None, "nothing was merged, so no copy was taken either"
    assert snapshot(db) == before

    # the control: the worklist is the ONLY thing that held it (slice 4 empties it by re-judging the file); the same pair then merges, the survivor being the same one
    with db.tx() as c:
        c.execute("DELETE FROM ref_recheck")
    again = refmerge.repair(db)
    assert [(m.survivor, m.loser) for m in again.merged] == [(first, second)] and again.held == []


def test_a_merge_now_remembers_the_title_and_the_artist_of_the_ref_it_removes(db: Database) -> None:
    """So the NEXT fold revision can rewrite the tombstone's key (decision D10); a row from before stays NULL."""
    with db.tx() as c:
        add_ref(c, ABBA, "Dancing Queen", ["ABBA"])
        add_ref(c, LUKASZ, "Dancing Queen", ["ABBA, Someone"], duration_ms=201_000)
        _share_a_file(c, ABBA, LUKASZ, "nd-1")
    keyrepair.repair(db)
    refmerge.repair(db)
    with db.read() as conn:
        row = conn.execute("SELECT title, artist, norm_key FROM ref_merge WHERE old_id = ?", (LUKASZ,)).fetchone()
    assert row["title"] == "Dancing Queen" and row["artist"] == "ABBA, Someone"


def test_the_start_runs_the_rekey_before_the_merge_and_before_any_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from encore_server.api import create_app
    from encore_server.config import Settings

    order: list[str] = []
    real_rekey, real_merge = keyrepair.repair, refmerge.repair
    monkeypatch.setattr(keyrepair, "repair", lambda database: (order.append("rekey"), real_rekey(database))[1])
    monkeypatch.setattr(refmerge, "repair", lambda database: (order.append("merge"), real_merge(database))[1])
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        workers=False,
    )
    create_app(settings)
    assert order == ["rekey", "merge"]


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the migration: ONLY the worklist table and the two columns of the tombstone


def test_the_migration_only_adds_the_worklist_and_the_two_tombstone_columns(tmp_path: Path) -> None:
    before = Database(tmp_path / "old" / "encore.db")
    before.migrate(migrations=[m for m in Database._migrations() if m[0] <= 17])
    with before.tx() as c:
        c.execute("INSERT INTO ref_merge (old_id, into_id, at, norm_key) VALUES ('sr_a', 'sr_b', 1, 'abba|waterloo|')")
    with before.read() as conn:
        tables_before = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns_before = {t: [r["name"] for r in conn.execute(f"PRAGMA table_info({t})")] for t in tables_before}  # noqa: S608
    applied = before.migrate()
    assert applied == [18]
    with before.read() as conn:
        tables_after = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert tables_after - tables_before == {"ref_recheck"}
        for table, columns in columns_before.items():
            now = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]  # noqa: S608
            assert now[: len(columns)] == columns, f"{table}: no column moves or goes"
            assert (set(now) - set(columns)) == ({"title", "artist"} if table == "ref_merge" else set()), table
        row = conn.execute("SELECT old_id, into_id, norm_key, title, artist FROM ref_merge").fetchone()
        assert tuple(row) == ("sr_a", "sr_b", "abba|waterloo|", None, None)
        assert [r["name"] for r in conn.execute("PRAGMA table_info(ref_recheck)")] == ["ref", "at", "moved"]


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the Host's own music library is never touched


def test_the_rewrite_touches_no_file_of_the_hosts_music_library_it_cannot_even_name_one() -> None:
    """The product works beside a stranger's existing music folder: the rewrite re-keys database rows and NOTHING else. It takes no music folder, imports nothing that
    writes one (`keeper`, `shutil`) and has no call that renames, moves or deletes a file (the one copy it makes is the database's own, `Database.backup`)."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(keyrepair))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not {name for name in imported if name.split(".")[0] in {"shutil", "os", "keeper", "subprocess"}} and not any(
        "keeper" in name for name in imported
    )
    forbidden = {
        "rename",
        "replace",
        "unlink",
        "remove",
        "rmtree",
        "write_bytes",
        "write_text",
        "move",
        "copy",
        "copyfile",
        "mkdir",
        "touch",
    }
    called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not (called & forbidden), called & forbidden
    assert "music" not in inspect.signature(keyrepair.repair).parameters
