"""The scanner link: what the music server already has becomes refs and files, without creating anything twice."""

from __future__ import annotations

from typing import Any

import pytest

from encore_server import library, refs
from encore_server.db import Database
from encore_server.scanner import described, link_library


class FakeLibrary:
    def __init__(self, songs: list[dict[str, Any]]) -> None:
        self.songs_ = songs
        self.down = False
        self.asked: list[tuple[int, int]] = []

    def songs(self, offset: int, size: int = 500) -> list[dict[str, Any]] | None:
        self.asked.append((offset, size))
        return None if self.down else self.songs_[offset : offset + size]


def entry(n: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"nd-{n}",
        "title": f"Song {n}",
        "artist": "Artist",
        "album": "Album",
        "duration": 180 + n,
        "path": f"Collection/Artist/Album/{n:02d} - Song {n}.flac",
        "suffix": "flac",
        "bitRate": 900,
        **extra,
    }


def files(db: Database) -> list[tuple[str, str | None]]:
    with db.read() as conn:
        return [
            (r["ref"], r["navidrome_song_id"])
            for r in conn.execute("SELECT ref, navidrome_song_id FROM song_file ORDER BY navidrome_song_id")
        ]


def test_every_song_gets_a_ref_and_its_file(db: Database) -> None:
    report = link_library(db, FakeLibrary([entry(1), entry(2), entry(3)]))

    assert (report.seen, report.linked, report.new_refs, report.complete) == (3, 3, 3, True)
    assert [f[1] for f in files(db)] == ["nd-1", "nd-2", "nd-3"]


def test_running_it_again_creates_nothing_new(db: Database) -> None:
    lib = FakeLibrary([entry(1), entry(2)])
    link_library(db, lib)

    again = link_library(db, lib)

    assert (again.new_refs, again.pruned) == (0, 0)
    assert len(files(db)) == 2
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0] == 2


def test_pages_are_read_until_a_short_one(db: Database) -> None:
    lib = FakeLibrary([entry(n) for n in range(1, 8)])

    report = link_library(db, lib, page=3)

    assert report.linked == 7 and lib.asked == [(0, 3), (3, 3), (6, 3)]


def test_the_same_recording_in_two_folders_is_one_ref_with_two_files(db: Database) -> None:
    a = entry(1, isrc=["GBAYE0701234"], path="Collection/A/01.flac")
    b = entry(2, title="Song 1", duration=181, isrc=["GBAYE0701234"], path="Other/B/01.mp3", suffix="mp3")

    link_library(db, FakeLibrary([a, b]))

    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0] == 1
    assert len({f[0] for f in files(db)}) == 1 and len(files(db)) == 2


def test_a_song_a_person_already_liked_is_found_not_duplicated(db: Database) -> None:
    with db.tx() as conn:
        who = library.ensure_person(conn, "marwa")["id"]
        ref = refs.resolve(conn, {"title": "Song 1", "artists": ["Artist"], "durationMs": 181000})["id"]
        library.set_item(conn, who, "like", ref)

    link_library(db, FakeLibrary([entry(1)]))

    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0] == 1
        assert refs.get_ref(conn, ref)["file"]["navidromeSongId"] == "nd-1"


def test_a_file_that_is_gone_loses_its_row_and_nothing_a_person_has_changes(db: Database) -> None:
    lib = FakeLibrary([entry(1), entry(2)])
    link_library(db, lib)
    ref = files(db)[0][0]
    with db.tx() as conn:
        who = library.ensure_person(conn, "marwa")["id"]
        library.set_item(conn, who, "like", ref)
    with db.read() as conn:
        before = library.changes(conn, who, 0)["likes"]
    lib.songs_ = [entry(2)]

    report = link_library(db, lib)

    assert report.pruned == 1 and [f[1] for f in files(db)] == ["nd-2"]
    with db.read() as conn:
        after = library.changes(conn, who, 0)
    assert [x["ref"] for x in after["likes"]] == [x["ref"] for x in before] == [ref]
    assert after["refs"][0]["file"] is None


def test_an_unanswered_music_server_prunes_nothing(db: Database) -> None:
    lib = FakeLibrary([entry(1)])
    link_library(db, lib)
    lib.down = True

    report = link_library(db, lib)

    assert report.complete is False and report.pruned == 0 and len(files(db)) == 1


def test_a_file_the_keeper_attached_during_the_pass_is_not_pruned(db: Database) -> None:
    class Late(FakeLibrary):
        def songs(self, offset: int, size: int = 500) -> list[dict[str, Any]] | None:
            page = super().songs(offset, size)
            with db.tx() as conn:  # the keeper links a new file while the scan is reading
                ref = refs.resolve(conn, {"title": "Fresh", "artists": ["Artist"], "durationMs": 200000})["id"]
                refs.attach_file(
                    conn,
                    ref,
                    navidrome_song_id="nd-fresh",
                    path="Encore/Artist/Fresh.opus",
                    codec="opus",
                    bitrate_kbps=128,
                    source="youtube",
                )
            return page

    link_library(db, Late([entry(1)]))

    assert "nd-fresh" in [f[1] for f in files(db)]


@pytest.mark.parametrize(
    ("song", "expected"),
    [
        ({"title": "T", "artist": "A"}, {"title": "T", "artists": ["A"]}),
        (
            {"title": "T", "artists": [{"name": "A"}, {"name": "B"}], "albumArtists": [{"name": "Various"}]},
            {"artists": ["A", "B"], "albumArtist": "Various"},
        ),
        (
            {"title": "T", "artist": "A", "isrc": ["XX1", "XX2"], "musicBrainzId": "abc", "duration": 200},
            {"isrc": "XX1", "mbid": "abc", "durationMs": 200000},
        ),
    ],
)
def test_the_music_servers_description_of_a_song(song: dict[str, Any], expected: dict[str, Any]) -> None:
    item = described(song)
    assert item is not None and {k: item[k] for k in expected} == expected


def test_a_song_without_a_title_or_an_artist_is_skipped(db: Database) -> None:
    report = link_library(db, FakeLibrary([{"id": "nd-9", "title": "", "artist": "A"}, {"id": "nd-8", "title": "T"}, entry(1)]))

    assert (report.skipped, report.linked) == (2, 1)


def test_the_linker_runs_by_itself_soon_after_start_and_again_when_poked(db: Database) -> None:
    import time

    from encore_server.scanner import LibraryLinker

    lib = FakeLibrary([entry(1)])
    linker = LibraryLinker(db, lib, first_after_s=0.0, every_s=3600.0)
    linker.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and len(files(db)) < 1:
            time.sleep(0.02)
        assert len(files(db)) == 1

        lib.songs_ = [entry(1), entry(2)]
        linker.poke()
        deadline = time.time() + 5
        while time.time() < deadline and len(files(db)) < 2:
            time.sleep(0.02)
        assert len(files(db)) == 2
    finally:
        linker.stop()
