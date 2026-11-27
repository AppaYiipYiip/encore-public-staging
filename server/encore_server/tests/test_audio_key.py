"""N-38: the audio-only key (`audio_key.py`): made, stored, served, carried over a tag rewrite, and made again only when the SOUND changes.

These tests need no ffmpeg: the hash is given (a hash of the bytes). The same promises on the real ffmpeg, with real tag rewrites in four containers, are in `tests/integration/test_audio_key.py`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

from encore_server import audio_key, refs
from encore_server.audio_key import AudioKeys, Unreadable, audio_key_of, carry, ffmpeg_command
from encore_server.db import Database
from encore_server.place import on_disk

HEX = "ab" * 32


def done(returncode: int = 0, stdout: str = f"SHA256={HEX}\n", stderr: str = "") -> Any:
    return lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout, stderr)


def of_bytes(path: Path) -> str:
    return "a1:" + hashlib.sha256(path.read_bytes()).hexdigest()[:32]


# ---------------------------------------------------------------------------------------------------------------------- the key


def test_the_command_copies_the_first_audio_stream_and_hashes_it_so_no_tag_can_be_in_it() -> None:
    path = Path("/music/Encore/A/B.opus")
    command = ffmpeg_command(path)
    assert "ffmpeg" in command
    joined = " ".join(command)
    assert "-map 0:a:0 -c copy -f hash -hash sha256 -" in joined, (
        "the audio stream only (a cover is a video stream), copied as it is, hashed"
    )
    assert f"-i {path} -map" in joined


def test_the_key_is_the_prefix_and_the_first_32_digits_of_the_sha256() -> None:
    assert audio_key_of(Path("x.opus"), runner=done()) == "a1:" + HEX[:32]


@pytest.mark.parametrize(
    "runner",
    [
        done(1, "", "Invalid data found when processing input"),
        done(0, "nothing useful"),
        done(0, f"sha256={HEX}"),
        done(0, "SHA256=abc"),
    ],
)
def test_a_file_ffmpeg_cannot_hash_is_unreadable_never_a_made_up_key(runner: Any) -> None:
    with pytest.raises(Unreadable):
        audio_key_of(Path("x.opus"), runner=runner)


def test_a_missing_ffmpeg_and_a_timeout_say_nothing_about_the_file_so_they_are_not_unreadable() -> None:
    def no_ffmpeg(*a: Any, **k: Any) -> Any:
        raise FileNotFoundError("ffmpeg")

    def too_slow(*a: Any, **k: Any) -> Any:
        raise subprocess.TimeoutExpired("ffmpeg", 1)

    with pytest.raises(FileNotFoundError):
        audio_key_of(Path("x.opus"), runner=no_ffmpeg)
    with pytest.raises(subprocess.TimeoutExpired):
        audio_key_of(Path("x.opus"), runner=too_slow)


def test_the_prefix_is_frozen() -> None:
    """Phones keep the key they were served for as long as a download lives. A new way of making keys is a new prefix and a migration on the phone, never an edit of this one."""
    assert audio_key.KEY_PREFIX == "a1:" and audio_key.KEY_DIGITS == 32


# ---------------------------------------------------------------------------------------------------------------------- serving and attaching


def one_ref(db: Database, title: str = "Weird Fishes") -> str:
    with db.tx() as conn:
        return str(refs.resolve(conn, {"title": title, "artists": ["Radiohead"]})["id"])


def file_of(db: Database, ref: str) -> dict[str, Any]:
    with db.read() as conn:
        return dict(refs.get_ref(conn, ref)["file"])


def feed(db: Database) -> int:
    with db.read() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM file_log").fetchone()[0])


def test_the_key_is_served_when_there_is_one_and_absent_when_there_is_none(db: Database) -> None:
    ref = one_ref(db)
    with db.tx() as conn:
        refs.attach_file(
            conn, ref, navidrome_song_id="nd1", path="Encore/R/W.opus", codec="opus", bitrate_kbps=128, meta={"size": 100}
        )
    assert "audioKey" not in file_of(db, ref), "nothing made yet: nothing served, and the phone does what it did"
    with db.tx() as conn:
        conn.execute("UPDATE song_file SET audio_key = '', audio_key_size = 100")
    assert "audioKey" not in file_of(db, ref), "unreadable is not served either"
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="Encore/R/W.opus",
            codec="opus",
            bitrate_kbps=128,
            meta={"size": 100},
            audio_key="a1:" + "c" * 32,
            audio_key_size=100,
        )
    assert file_of(db, ref)["audioKey"] == "a1:" + "c" * 32


def test_attach_file_stores_the_keepers_key_and_tells_the_phones_only_when_the_key_is_new_or_changed(db: Database) -> None:
    ref = one_ref(db)
    key = "a1:" + "d" * 32
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="Encore/R/W.opus",
            codec="opus",
            bitrate_kbps=1,
            meta={"size": 10},
            audio_key=key,
            audio_key_size=10,
        )
    assert file_of(db, ref)["audioKey"] == key
    before = feed(db)
    # the same key at another size: a tag rewrite. The file's meta changes (the feed says so for the new size), the key does not.
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="Encore/R/W.opus",
            codec="opus",
            bitrate_kbps=1,
            meta={"size": 12},
            audio_key=key,
            audio_key_size=12,
        )
    assert file_of(db, ref)["audioKey"] == key
    after_meta = feed(db)
    assert after_meta == before + 1, "the changed meta is one feed row, as before this change"
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="Encore/R/W.opus",
            codec="opus",
            bitrate_kbps=1,
            meta={"size": 12},
            audio_key=key,
            audio_key_size=12,
        )
    assert feed(db) == after_meta, "attaching what is attached writes nothing"
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="Encore/R/W.opus",
            codec="opus",
            bitrate_kbps=1,
            meta={"size": 12},
            audio_key="a1:" + "e" * 32,
            audio_key_size=12,
        )
    assert feed(db) == after_meta + 1 and file_of(db, ref)["audioKey"] == "a1:" + "e" * 32, "another key is told"


def test_a_scan_that_describes_the_file_again_never_loses_the_key(db: Database) -> None:
    ref = one_ref(db)
    key = "a1:" + "d" * 32
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="p.opus",
            codec="opus",
            bitrate_kbps=1,
            meta={"size": 10},
            audio_key=key,
            audio_key_size=10,
        )
        refs.attach_file(
            conn, ref, navidrome_song_id="nd1", path="p.opus", codec="opus", bitrate_kbps=1, meta={"size": 99, "suffix": "opus"}
        )
    assert file_of(db, ref)["audioKey"] == key and file_of(db, ref)["meta"]["size"] == 99


def test_carry_moves_only_the_size_a_key_is_recorded_at_and_only_when_there_is_a_key(db: Database) -> None:
    ref = one_ref(db)
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="p.opus",
            codec="opus",
            bitrate_kbps=1,
            meta={"size": 10},
            audio_key="a1:" + "d" * 32,
            audio_key_size=10,
        )
        sid = str(conn.execute("SELECT id FROM song_file").fetchone()["id"])
        carry(conn, sid, 14)
    with db.read() as conn:
        row = conn.execute("SELECT audio_key, audio_key_size, meta FROM song_file").fetchone()
    assert (row["audio_key"], row["audio_key_size"]) == ("a1:" + "d" * 32, 14)
    assert json.loads(row["meta"])["size"] == 14, (
        "the music server's number moves with it, in the format a scan writes (so a scan of the same size changes nothing)"
    )
    other = one_ref(db, "Other")
    with db.tx() as conn:
        refs.attach_file(conn, other, navidrome_song_id="nd2", path="q.opus", codec="opus", bitrate_kbps=1, meta={"size": 10})
        sid2 = str(conn.execute("SELECT id FROM song_file WHERE ref = ?", (other,)).fetchone()["id"])
        carry(conn, sid2, 14)
        assert (
            conn.execute("SELECT audio_key, audio_key_size FROM song_file WHERE id = ?", (sid2,)).fetchone()["audio_key_size"]
            is None
        )


# ---------------------------------------------------------------------------------------------------------------------- the hourly errand


class Bench:
    """A music folder and a database; files are put in, rows attached as the library link does (a path, the music server's own size in `meta`)."""

    def __init__(self, tmp: Path, db: Database) -> None:
        self.music = tmp / "music"
        self.music.mkdir()
        self.db = db
        self.n = 0
        self.hashed: list[str] = []
        self.now = 0.0

    def add(
        self, content: bytes = b"sound", *, name: str | None = None, preferred: bool = True, stored: str | None = None
    ) -> tuple[str, Path]:
        self.n += 1
        ref = one_ref(self.db, f"Song {self.n}")
        path = self.music / (name or f"Artist/Song {self.n}.opus")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        with self.db.tx() as conn:
            refs.attach_file(
                conn,
                ref,
                navidrome_song_id=f"nd{self.n}",
                path=stored or path.relative_to(self.music).as_posix(),
                codec="opus",
                bitrate_kbps=1,
                meta={"size": len(content)},
                path_real=True,  # a row whose path was checked (N-53): the errand takes no other
            )
            if not preferred:
                conn.execute("UPDATE song_file SET preferred = 0 WHERE ref = ?", (ref,))
        return ref, path

    def hash_(self, path: Path) -> str:
        self.hashed.append(path.name)
        return of_bytes(path)

    def keys(self, **more: Any) -> AudioKeys:
        return AudioKeys(self.db, self.music, hash_=more.pop("hash_", self.hash_), clock=lambda: self.now, **more)

    def row(self, ref: str) -> sqlite3.Row:
        with self.db.read() as conn:
            row: sqlite3.Row = conn.execute("SELECT audio_key, audio_key_size FROM song_file WHERE ref = ?", (ref,)).fetchone()
        return row

    def scan_says_size(self, ref: str, size: int) -> None:
        """The music server's next scan: the file has another size now."""
        with self.db.tx() as conn:
            conn.execute("UPDATE song_file SET meta = ? WHERE ref = ?", (json.dumps({"size": size}), ref))


@pytest.fixture()
def bench(tmp_path: Path, db: Database) -> Bench:
    return Bench(tmp_path, db)


def test_a_library_file_gets_its_key_once_and_the_phones_are_told(bench: Bench) -> None:
    ref, path = bench.add(b"one")
    before = feed(bench.db)

    first = bench.keys().run_once()

    assert (first.made, first.unreadable, first.left) == (1, 0, 0)
    assert bench.row(ref)["audio_key"] == of_bytes(path) and bench.row(ref)["audio_key_size"] == 3
    assert file_of(bench.db, ref)["audioKey"] == of_bytes(path)
    assert feed(bench.db) == before + 1, "a phone learns the key through the files feed"
    assert bench.keys().run_once() == (0, 0, 0) and bench.hashed == ["Song 1.opus"], "a second pass hashes nothing"


def test_a_tag_rewrite_by_somebody_else_is_one_hash_and_no_news_for_the_phones(bench: Bench) -> None:
    """The size changed (the music server says so), the sound did not: the pass hashes the file once, finds the same key and writes down the new size. It tells no phone."""
    ref, path = bench.add(b"sound-bytes")
    bench.keys().run_once()
    key = bench.row(ref)["audio_key"]
    news = feed(bench.db)
    path.write_bytes(
        b"sound-bytes" + b"+ a picture and longer tags"
    )  # a retag grew the file; the music server's next scan says so
    bench.scan_says_size(ref, path.stat().st_size)
    again = bench.keys(hash_=lambda p: key).run_once()  # ffmpeg's answer for the same sound
    assert again.made == 0 and bench.row(ref)["audio_key"] == key and bench.row(ref)["audio_key_size"] == path.stat().st_size
    assert feed(bench.db) == news, "same key: nothing to tell"
    assert bench.keys().run_once() == (0, 0, 0), "and the size is recorded, so it is not looked at again"


def test_a_replaced_file_gets_another_key_and_the_phones_are_told(bench: Bench) -> None:
    ref, path = bench.add(b"old sound")
    bench.keys().run_once()
    old = bench.row(ref)["audio_key"]
    path.write_bytes(b"a different recording altogether")
    bench.scan_says_size(ref, path.stat().st_size)
    news = feed(bench.db)

    assert bench.keys().run_once().made == 1

    assert bench.row(ref)["audio_key"] != old and feed(bench.db) == news + 1


def test_the_old_key_is_served_until_the_pass_has_made_the_new_one(bench: Bench) -> None:
    ref, path = bench.add(b"old sound")
    bench.keys().run_once()
    key = file_of(bench.db, ref)["audioKey"]
    bench.scan_says_size(ref, 4242)  # the scan saw a new size: until the pass runs the ref still answers with the key it has
    assert file_of(bench.db, ref)["audioKey"] == key


def test_a_file_ffmpeg_cannot_read_is_marked_at_its_size_and_not_asked_about_again_until_it_changes(bench: Bench) -> None:
    ref, path = bench.add(b"not audio")

    def broken(p: Path) -> str:
        raise Unreadable("Invalid data")

    assert bench.keys(hash_=broken).run_once() == (0, 1, 0), "nothing new to tell a phone: no key was made"
    assert bench.row(ref)["audio_key"] == "" and bench.row(ref)["audio_key_size"] == 9
    assert "audioKey" not in file_of(bench.db, ref)
    assert bench.keys().run_once() == (0, 0, 0) and bench.hashed == [], "not looked at again at the same size"
    path.write_bytes(b"now it is a song, a longer one")
    bench.scan_says_size(ref, path.stat().st_size)
    assert bench.keys().run_once().made == 1 and file_of(bench.db, ref)["audioKey"].startswith("a1:")


def test_what_is_not_on_the_disk_or_not_in_the_music_folder_is_left_and_never_remembered(bench: Bench, tmp_path: Path) -> None:
    gone, path = bench.add(b"here today")
    path.unlink()
    outside = tmp_path / "secret.opus"
    outside.write_bytes(b"outside")
    ref = one_ref(bench.db, "Sneaky")
    with bench.db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="ndx",
            path="../secret.opus",
            codec="opus",
            bitrate_kbps=1,
            meta={"size": 7},
            path_real=True,  # even a path marked checked is never read when it leaves the music folder
        )

    done_ = bench.keys().run_once()

    assert (done_.made, done_.left) == (0, 2) and bench.hashed == [], "a path that leaves the music folder is never read"
    with bench.db.read() as conn:
        marks = {r["ref"]: r["path_real"] for r in conn.execute("SELECT ref, path_real FROM song_file")}
    assert marks[gone] == 0 and marks[ref] == 0, (
        "a checked path that names no file (gone, or leaving the folder) is not trusted any more: the errand asks the music server again"
    )
    assert bench.row(gone)["audio_key"] is None and bench.row(ref)["audio_key"] is None


def test_a_file_that_changes_while_it_is_read_is_left_for_the_next_pass(bench: Bench) -> None:
    ref, path = bench.add(b"live recording")

    def grows(p: Path) -> str:
        key = of_bytes(p)
        p.write_bytes(p.read_bytes() + b"more")
        return key

    assert bench.keys(hash_=grows).run_once() == (0, 0, 1) and bench.row(ref)["audio_key"] is None


def test_a_missing_program_or_a_stuck_disk_stops_the_pass_and_marks_nothing(bench: Bench) -> None:
    first, _ = bench.add(b"a")
    second, _ = bench.add(b"b")

    def no_ffmpeg(p: Path) -> str:
        raise FileNotFoundError("ffmpeg")

    result = bench.keys(hash_=no_ffmpeg).run_once()

    assert result == (0, 0, 2) and bench.row(first)["audio_key_size"] is None and bench.row(second)["audio_key_size"] is None


def test_the_pass_takes_at_most_a_batch_and_a_budget_and_the_preferred_file_first(bench: Bench) -> None:
    old, _ = bench.add(b"old copy", preferred=False)
    wanted, _ = bench.add(b"wanted copy")
    third, _ = bench.add(b"third")

    assert bench.keys(batch=2).run_once().made == 2
    assert bench.row(old)["audio_key"] is None, "the file a phone downloads is keyed before the old copy"
    assert bench.row(wanted)["audio_key"] and bench.row(third)["audio_key"]

    def slow(p: Path) -> str:
        bench.now += 30.0
        return of_bytes(p)

    bench.add(b"fourth")
    bench.add(b"fifth")
    result = bench.keys(
        hash_=slow, budget_s=40.0
    ).run_once()  # two files are keyed (30 s each); the third is over the 40 s budget
    assert result == (2, 0, 1), "the budget stops the pass; the rest waits for the next"
    assert bench.row(old)["audio_key"] is None, "the old copy is the one left"


# ---------------------------------------------------------------------------------------------------------------------- review of #164: the queue, the race, carry, the paths


def test_a_file_that_cannot_be_found_never_keeps_the_others_from_their_turn(bench: Bench) -> None:
    """Review of #164: rows the pass cannot resolve used to be taken first at every pass (preferred, newest), so enough of them filled every batch for ever."""
    good, _ = bench.add(b"the one that can be keyed")
    bad = []
    for n in range(4):
        ref = one_ref(bench.db, f"Unfindable {n}")
        with bench.db.tx() as conn:
            refs.attach_file(
                conn,
                ref,
                navidrome_song_id=f"ndx{n}",
                path=f"Nowhere/{n}.opus",
                codec="opus",
                bitrate_kbps=1,
                meta={"size": 10},
                path_real=True,
            )
        bad.append(ref)

    first = bench.keys(batch=3).run_once()
    assert (first.made, first.left) == (0, 3), "the three newest are looked at, found nowhere and sent to the back"
    second = bench.keys(batch=3).run_once()

    assert second.made == 1 and bench.row(good)["audio_key"] is not None, "the next pass reaches the file that can be keyed"
    assert [bench.row(ref)["audio_key"] for ref in bad] == [None] * 4


def test_a_file_that_always_times_out_does_not_stop_every_pass_at_its_first_row(bench: Bench) -> None:
    fine, _ = bench.add(b"fine song", name="Artist/Fine.opus")
    stuck, _ = bench.add(b"stuck on a bad disk sector", name="Artist/Stuck.opus")

    def stuck_on_one(path: Path) -> str:
        if path.name == "Stuck.opus":
            raise subprocess.TimeoutExpired("ffmpeg", 120)
        return of_bytes(path)

    first = bench.keys(hash_=stuck_on_one).run_once()
    assert first.made == 0 and bench.row(fine)["audio_key"] is None, "the newest row stopped the first pass"
    second = bench.keys(hash_=stuck_on_one).run_once()
    assert second.made == 1 and bench.row(fine)["audio_key"] is not None and bench.row(stuck)["audio_key"] is None


def test_a_key_the_keeper_linked_while_the_pass_was_hashing_is_not_overwritten(bench: Bench) -> None:
    ref, path = bench.add(b"being kept right now")
    keepers = "a1:" + "9" * 32

    def keeper_links_meanwhile(p: Path) -> str:
        with bench.db.tx() as conn:
            refs.attach_file(
                conn,
                ref,
                navidrome_song_id="nd1",
                path=path.relative_to(bench.music).as_posix(),
                codec="opus",
                bitrate_kbps=1,
                meta={"size": path.stat().st_size},
                audio_key=keepers,
                audio_key_size=path.stat().st_size,
            )
        return "a1:" + "0" * 32  # the pass's older answer

    assert bench.keys(hash_=keeper_links_meanwhile).run_once().made == 0
    assert bench.row(ref)["audio_key"] == keepers


def test_a_server_tag_rewrite_that_carried_its_key_is_not_hashed_again_before_the_next_scan(bench: Bench) -> None:
    """Review of #164: after `carry` the music server's `meta.size` still said the old size, so the errand took the file for one that changed behind the server's back and hashed it again; with a newer
    ffmpeg (the image is rebuilt weekly) that could have moved a key phones hold."""
    ref, path = bench.add(b"kept song")
    bench.keys().run_once()
    key = bench.row(ref)["audio_key"]
    path.write_bytes(b"kept song" + b" + tags and a cover the repair wrote")  # the repair rewrote the file...
    with bench.db.tx() as conn:  # ...and recorded it in the same step
        carry(conn, str(conn.execute("SELECT id FROM song_file WHERE ref = ?", (ref,)).fetchone()["id"]), path.stat().st_size)
    bench.hashed.clear()

    assert bench.keys().run_once() == (0, 0, 0) and bench.hashed == [], "nothing is hashed before the scan has said anything"
    assert bench.row(ref)["audio_key"] == key and file_of(bench.db, ref)["audioKey"] == key


def test_a_stored_path_is_taken_as_it_is_inside_the_music_folder_and_never_searched_for(tmp_path: Path) -> None:
    music = tmp_path / "music"
    song = music / "Artist" / "Album" / "01 - Song.opus"
    song.parent.mkdir(parents=True)
    song.write_bytes(b"x")
    assert on_disk(music, "Artist/Album/01 - Song.opus") == song
    assert on_disk(music, "Artist" + chr(92) + "Album" + chr(92) + "01 - Song.opus") == song, "a path written with backslashes"
    assert on_disk(music, str(song)) == song, "an absolute path that IS a location inside the music folder"
    assert on_disk(music, "Album/01 - Song.opus") is None, (
        "never found by its tail: another song's file by the same tail must never be taken"
    )
    assert on_disk(music, "/music/Artist/Album/01 - Song.opus") is None, "nor a root that is not this one's"
    assert on_disk(music, "Artist/Album/Missing.opus") is None and on_disk(music, "") is None
    outside = tmp_path / "secret.opus"
    outside.write_bytes(b"x")
    assert on_disk(music, "../secret.opus") is None and on_disk(music, str(outside)) is None


def test_a_file_whose_size_is_not_the_one_the_music_server_reports_for_that_row_is_never_hashed(bench: Bench) -> None:
    """Review of #164, measured on the real music server: a library row's path is built from the tags, so it can name ANOTHER song's file (two copies of an album share one built path) or a file that was
    retagged on the disk and not scanned yet. Only a file of exactly the reported size is the row's file."""
    ref, path = bench.add(b"the file that is really at this path")
    bench.scan_says_size(ref, 999)  # the music server means a file of another size

    first = bench.keys().run_once()

    assert (first.made, first.left) == (0, 1) and bench.hashed == [] and bench.row(ref)["audio_key"] is None
    bench.scan_says_size(ref, path.stat().st_size)  # a scan has seen the file as it is
    assert bench.keys().run_once().made == 1


def test_a_row_with_no_size_from_the_music_server_is_keyed_when_the_path_names_a_file(bench: Bench) -> None:
    ref, path = bench.add(b"a keeper row the music server never described")
    with bench.db.tx() as conn:
        conn.execute("UPDATE song_file SET meta = NULL WHERE ref = ?", (ref,))
    assert bench.keys().run_once().made == 1 and bench.row(ref)["audio_key"] == of_bytes(path)


def test_a_path_nobody_has_checked_is_never_looked_at(bench: Bench) -> None:
    """N-53: the scanner's path is the music server's tag-built one, not a location. A row is keyed only after `real_paths` (or the keeper) has said where its file really lies."""
    ref, path = bench.add(b"a library song")
    with bench.db.tx() as conn:
        conn.execute("UPDATE song_file SET path_real = 0 WHERE ref = ?", (ref,))

    assert bench.keys().run_once() == (0, 0, 0) and bench.hashed == [] and bench.row(ref)["audio_key"] is None
    with bench.db.tx() as conn:
        conn.execute("UPDATE song_file SET path_real = 1 WHERE ref = ?", (ref,))
    assert bench.keys().run_once().made == 1 and bench.row(ref)["audio_key"] == of_bytes(path)
