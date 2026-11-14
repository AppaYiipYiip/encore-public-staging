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


# ---------------------------------------------------------------------------------------------------------------------------------------
# N-11 / CF-42: a file that already belongs to a ref never gets a second one. The keeper saves a file for the ref an import or the catalogue
# made (the proper artists list, the cover, the album); the scan then meets the same file in the music server and describes it from its TAGS.
# Whatever the tags say, the file's own row (its id in the music server) says whose it is. The PATH is not used: the music server lists a file
# at a path it builds from the tags, the keeper saved it at its own, and in 177 of the 178 doubled pairs on the bench the two differ.

ARTISTS = ["Corey Taylor", "Dave Grohl", "Rick Nielsen", "Scott Reeder"]
KEPT_PATH = "Encore/Corey Taylor/Singles/Rick the Bruiser.opus"  # where the keeper puts a song (`keeper/placement.py`)
LISTED_PATH = "Corey Taylor/[Unknown Album]/Rick the Bruiser.opus"  # how the music server lists that same file


def kept(db: Database, *, song_id: str | None = "nd-1", path: str = KEPT_PATH, **item: Any) -> str:
    """What the keeper leaves behind: a ref made from a proper description, and its file attached with source `youtube`."""
    described_by_the_import = {
        "title": "Rick the Bruiser",
        "artists": ARTISTS,
        "album": "Real Album",
        "durationMs": 249000,
        "coverUrl": "https://e-cdns-images.dzcdn.net/images/cover/x/500x500.jpg",
        **item,
    }
    with db.tx() as conn:
        ref = refs.resolve(conn, described_by_the_import)["id"]
        refs.attach_file(conn, ref, navidrome_song_id=song_id, path=path, codec="opus", bitrate_kbps=128, source="youtube")
    return str(ref)


def tagged(**extra: Any) -> dict[str, Any]:
    """The same file as the music server lists it: the artists as ONE string (the old keeper's tags) and the path built from the tags."""
    return {
        "id": "nd-1",
        "title": "Rick the Bruiser",
        "artist": ", ".join(ARTISTS),
        "artists": [{"name": ", ".join(ARTISTS)}],
        "album": "Real Album",
        "duration": 249,
        "path": LISTED_PATH,
        "suffix": "opus",
        "bitRate": 128,
        **extra,
    }


def ref_count(db: Database) -> int:
    with db.read() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0])


def file_rows(db: Database) -> list[tuple[str, str | None, str | None, str]]:
    with db.read() as conn:
        return [
            (r["ref"], r["navidrome_song_id"], r["path"], r["source"])
            for r in conn.execute("SELECT ref, navidrome_song_id, path, source FROM song_file ORDER BY added_at, rowid")
        ]


FIRST_ARTIST_ONLY = {
    "artist": "Corey Taylor",
    "artists": [{"name": "Corey Taylor"}],
}  # the artist that does match the ref's first one


@pytest.mark.parametrize(
    "the_scan_says",
    [
        # Each case differs from the ref in ONE way (the first is `tagged()` as it is: the joined artist string).
        pytest.param({}, id="the-artists-are-one-joined-string"),
        pytest.param({**FIRST_ARTIST_ONLY, "duration": 249 + 12}, id="the-length-is-12-seconds-off"),
        pytest.param({**FIRST_ARTIST_ONLY, "album": "[Unknown Album]"}, id="the-album-is-unknown-in-the-tags"),
        pytest.param({**FIRST_ARTIST_ONLY, "album": None}, id="the-tags-have-no-album"),
    ],
)
def test_a_file_the_keeper_saved_is_attached_to_its_own_ref_whatever_the_tags_say(
    db: Database, the_scan_says: dict[str, Any]
) -> None:
    """CF-42."""
    ref = kept(db)

    report = link_library(db, FakeLibrary([tagged(**the_scan_says)]))

    assert ref_count(db) == 1  # nothing was made
    assert (report.seen, report.linked, report.new_refs, report.complete) == (1, 1, 0, True)
    # still the keeper's row (its path, its source): not a second row, not renamed `library`
    assert file_rows(db) == [(ref, "nd-1", KEPT_PATH, "youtube")]
    with db.read() as conn:
        shown = refs.get_ref(conn, ref)
    assert (
        shown["artists"] == ARTISTS and shown["album"] == "Real Album" and shown["coverUrl"]
    )  # the import's description is not replaced


def test_the_real_rows_mismatch_all_at_once(db: Database) -> None:
    """The 176 songs of the bench had these together: one joined artist string, a different length and the album `[Unknown Album]`."""
    ref = kept(db, album=None, durationMs=249000)

    link_library(db, FakeLibrary([tagged(duration=261, album="[Unknown Album]")]))

    assert ref_count(db) == 1
    assert [f[0] for f in file_rows(db)] == [ref]


@pytest.mark.parametrize(
    ("artist", "title", "kept_path", "listed_path"),
    [  # three of the real pairs of the test server's database: the same file, the same id, two different paths
        (
            "JAY-Z",
            "Empire State Of Mind",
            "Encore/JAY-Z/Singles/Empire State Of Mind.opus",
            "JAY-Z/[Unknown Album]/Empire State Of Mind.opus",
        ),
        (
            "T-Pain",
            "Buy U A Drank (Shawty Snappin')",
            "Encore/T-Pain/Singles/Buy U A Drank (Shawty Snappin').opus",
            "T-Pain/[Unknown Album]/Buy U A Drank (Shawty Snappin').opus",
        ),
        ("Eminem", "Lose Yourself", "Encore/Eminem/Singles/Lose Yourself.opus", "Eminem/[Unknown Album]/Lose Yourself.opus"),
    ],
)
def test_the_id_finds_the_ref_although_the_two_paths_of_the_file_never_match(
    db: Database, artist: str, title: str, kept_path: str, listed_path: str
) -> None:
    ref = kept(db, title=title, artists=[artist], durationMs=261000, path=kept_path)

    report = link_library(
        db, FakeLibrary([tagged(title=title, artist=artist, artists=[{"name": artist}], duration=249, path=listed_path)])
    )

    assert (ref_count(db), report.new_refs) == (1, 0)
    assert file_rows(db) == [(ref, "nd-1", kept_path, "youtube")]  # one row, the keeper's path kept


def test_the_scan_refreshes_the_columns_of_the_file_it_found(db: Database) -> None:
    ref = kept(db)

    link_library(db, FakeLibrary([tagged(suffix="opus", bitRate=131, size=4_000_000, albumId="al-9", coverArt="al-9")]))

    with db.read() as conn:
        row = conn.execute("SELECT * FROM song_file").fetchone()
        assert conn.execute("SELECT COUNT(*) FROM song_file").fetchone()[0] == 1
        file = refs.get_ref(conn, ref)["file"]
    assert (row["navidrome_song_id"], row["codec"], row["bitrate_kbps"], row["source"]) == ("nd-1", "opus", 131, "youtube")
    assert file is not None and file["meta"]["albumId"] == "al-9" and file["meta"]["size"] == 4_000_000


def test_a_file_that_one_ref_has_is_not_attached_to_another_ref_the_tags_happen_to_match(db: Database) -> None:
    """Ref A owns the file. Ref B (somebody liked the song) is exactly what the tags describe. The file is A's and B gets nothing."""
    a = kept(db)
    with db.tx() as conn:
        b = refs.resolve(conn, {"title": "Rick the Bruiser", "artists": [", ".join(ARTISTS)], "durationMs": 249000})["id"]
    assert a != b

    report = link_library(db, FakeLibrary([tagged()]))

    assert (report.new_refs, ref_count(db)) == (0, 2)
    assert file_rows(db) == [(a, "nd-1", KEPT_PATH, "youtube")]
    with db.read() as conn:
        assert refs.get_ref(conn, b)["file"] is None


def test_a_file_nobody_owns_gets_exactly_one_new_ref_and_a_second_scan_makes_nothing(db: Database) -> None:
    ref = kept(db)  # another song of the same artist is already there; it must not be taken for this one
    lib = FakeLibrary(
        [tagged(), tagged(id="nd-9", title="Hell Yeah", path="Collection/Hell Yeah.flac", suffix="flac", duration=200)]
    )

    first = link_library(db, lib)
    second = link_library(db, lib)

    assert (first.new_refs, first.linked) == (1, 2) and (second.new_refs, second.linked) == (0, 2)
    assert ref_count(db) == 2 and len(file_rows(db)) == 2
    assert file_rows(db)[0] == (ref, "nd-1", KEPT_PATH, "youtube")
    assert file_rows(db)[1][1:] == ("nd-9", "Collection/Hell Yeah.flac", "library") and file_rows(db)[1][0] != ref


def test_a_second_scan_after_the_fix_still_creates_nothing(db: Database) -> None:
    ref = kept(db)
    lib = FakeLibrary([tagged()])

    link_library(db, lib)
    again = link_library(db, lib)

    assert (again.new_refs, again.pruned, ref_count(db)) == (0, 0, 1)
    assert file_rows(db) == [(ref, "nd-1", KEPT_PATH, "youtube")]


def test_a_file_that_two_refs_already_have_is_refreshed_on_the_first_and_makes_nothing_new(db: Database) -> None:
    """The 178 pairs the old scan left behind: the pass neither crashes on them nor makes a third ref; it keeps to the first holder (the repair is separate)."""
    first = kept(db)
    with db.tx() as conn:
        second = refs.resolve(conn, {"title": "Rick the Bruiser", "artists": [", ".join(ARTISTS)], "durationMs": 261000})["id"]
        refs.attach_file(
            conn, second, navidrome_song_id="nd-1", path=LISTED_PATH, codec="opus", bitrate_kbps=128, source="library"
        )
    assert first != second and ref_count(db) == 2

    report = link_library(db, FakeLibrary([tagged(bitRate=140)]))

    assert (report.new_refs, ref_count(db), report.pruned) == (0, 2, 0)
    with db.read() as conn:
        rows = {r["ref"]: r["bitrate_kbps"] for r in conn.execute("SELECT ref, bitrate_kbps FROM song_file")}
    assert rows == {first: 140, second: 128}


@pytest.mark.xfail(
    strict=True,
    reason="N-11 part B / B-110, a known gap: a file the keeper saved but the music server had not listed yet has a path and no id, and the music "
    "server's path for it is built from the tags, so nothing exact links the two (2 rows of 3,389 on the bench). Remove this marker when it is closed.",
)
def test_a_file_the_keeper_saved_before_the_music_server_listed_it_is_not_given_a_second_ref(db: Database) -> None:
    kept(db, song_id=None)  # a row with the keeper's path and no id of the music server yet

    link_library(db, FakeLibrary([tagged(id="nd-7")]))

    assert ref_count(db) == 1


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
