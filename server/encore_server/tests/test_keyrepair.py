"""P2-25 slice 3: the start-up rekey (`keyrepair.py`): the stored `norm_key` of every ref is rewritten from the ref's own text with the new fold, the refs the old
fold damaged go on the worklist (`ref_recheck`), and nothing a person has moves.

The data is SYNTHETIC and built the way the OLD server built it: the stored keys are `tests/legacy_fold.py`'s (the frozen old fold), so a test here can only pass
by doing what the repair is for. Rows are written with SQL on purpose (`refs.resolve` would now find the very matches the old fold failed to make).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

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
        add_ref(c, AUDIO, "Official Video", ["X"])  # old key `x||`: not suspect (it is all ASCII), its key is still rewritten
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
    """Suspect = the ref's own artist or title did not survive the OLD fold (decided from the text, not from the stored key: `fairuz|habibi|` is not empty).
    On the worklist = and it holds a library file. The keeper's own file is never re-judged; an all-ASCII ref is not suspect even when its key was empty."""
    report = keyrepair.repair(old_world)
    assert worklist(old_world) == {FAIRUZ, HABIBI, LUKASZ, BJORK}
    assert report.suspect == 5, "the four above and the keeper-only Arabic song"
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
