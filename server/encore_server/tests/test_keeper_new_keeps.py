"""N-34 slice 3: NEW KEEPS are filed and tagged under their album from the start, and a song that already has its file is never saved twice (audit B-110).

The permanence rules of the slice, each pinned below (a keep writes into the TAGS and the FOLDER of a file on the Host's disk, which is harder to undo than a row):

1. a new keep is filed under an album ONLY from a `matched` outcome of the matcher the pass uses; `none`, `held`, a single and "could not ask" keep the song where it is filed today;
2. a catalogue that cannot be asked (down, resting, off, slow, no length) never blocks or delays the keep, and nothing is remembered about the song for that reason;
3. the keep never rewrites an album the ref already has;
5. the keeper reads the downloaded FILE's own length, never the import's listing;
6. one file per ref: a keep reuses the file the ref already has, wherever it lies, never hands a file another ref holds to this one, and never touches the Host's own files.

Every catalogue answer is a RECORDED one (`tests/test_album_pass.py`'s fake over the recordings of `tests/fixtures/deezer/`); nothing here makes a request.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server import album_finder, album_pass, deezer, refs
from encore_server.album_pass import KeepAnswer, KeepAsker
from encore_server.album_pass import (
    search_the_catalogue_for_keep as the_real_search,
)  # bound before the autouse guard of conftest replaces it
from encore_server.api import create_app
from encore_server.catalogue import Cache
from encore_server.catalogue import Catalogue as RealCatalogue
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.deezer import DeezerClient, Gate
from encore_server.keeper.covers import write_folder_picture
from encore_server.keeper.placement import plan_for_ref
from encore_server.keeper.tagging import Tags, tags_of
from tests.catalogue_fakes import RecordedDeezer
from tests.conftest import FakeVerifier, creds, resolve
from tests.test_album_finder import ALBUM, SINGLE, albums, derive, single_hit
from tests.test_album_pass import Catalogue, landmvrks
from tests.test_keeper import AUDIO, FakeNavidrome, FakeSource, Rig, fake_ffmpeg

ALBUM_TITLE = "The Darkest Place I've Ever Been"
ALBUM_DIR = f"Encore/LANDMVRKS/{ALBUM_TITLE}"
FILE_LENGTH_MS = 225_000  # the recorded catalogue's length of Creature: the file's own, as `file_length_ms` would read it
LISTED_MS = 237_000  # what an import's listing said: 12 s off, which the matcher refuses (the tolerance is 3 s)
OTHER_LISTED_MS = 250_000  # a second ref of the same song: 13 s from the first, so `refs.resolve` makes it a ref of its own (the owner's Creature pair)
NOW = 1_800_000_000_000


class KeepRig(Rig):
    """The keeper rig with the album question switched on: the catalogue is the recorded fake, the file's length is what the test says, every question is written down."""

    def __init__(self, tmp: Path, db: Database, catalogue: Catalogue | None = None) -> None:
        super().__init__(tmp, db)
        self.catalogue = catalogue if catalogue is not None else landmvrks()
        self.file_length: int | None = FILE_LENGTH_MS
        self.waits: list[float] = []
        self.lengths_asked: list[int | None] = []
        self.clock_now = 0.0
        self.asker = KeepAsker(
            db,
            search=self._search,
            album=self._album,
            call_wait_s=10.0,
            budget_s=10.0,
            clock=lambda: self.clock_now,
            now=lambda: NOW,
        )
        self.keeper._identify = self._identify
        self.keeper._length_of = lambda path, listed: (self.file_length, "file") if self.file_length else (listed, "listing")  # type: ignore[assignment,return-value]

    def _identify(self, ref_id: str, length_ms: int | None) -> KeepAnswer:
        self.lengths_asked.append(length_ms)
        return self.asker(ref_id, length_ms)

    def _search(self, artist: str, title: str, wait_s: float) -> list[dict[str, Any]]:
        self.waits.append(wait_s)
        return self.catalogue.search(artist, title)

    def _album(self, ident: str, wait_s: float) -> dict[str, Any]:
        self.waits.append(wait_s)
        return self.catalogue.album(ident)

    def creature(self, *, duration: int = LISTED_MS, **extra: Any) -> str:
        """The owner's song as an import describes it: no album, a listed length that is 12 s off the file's."""
        extra.setdefault("album", None)
        return self.make_ref(title="Creature", artists=["LANDMVRKS"], durationMs=duration, **extra)

    def unknown(self, **extra: Any) -> str:
        extra.setdefault("album", None)
        return self.make_ref(title="A Song Nobody Recorded", artists=["Nobody At All"], durationMs=200_000, **extra)

    def row(self, ref: str) -> dict[str, Any]:
        with self.db.read() as conn:
            return dict(conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref,)).fetchone())

    def kept_paths(self) -> list[str]:
        return sorted(f.relative_to(self.music).as_posix() for f in (self.music / "Encore").rglob("*") if f.is_file())

    def audio_paths(self) -> list[str]:
        return [p for p in self.kept_paths() if p.endswith(".opus")]


@pytest.fixture()
def krig(tmp_path: Path, db: Database) -> KeepRig:
    return KeepRig(tmp_path, db)


# ------------------------------------------------------------------------------------------------------------------ rule 1: filed under an album only from a match


def test_a_matched_new_keep_is_filed_and_tagged_under_its_album_from_the_start(krig: KeepRig) -> None:
    ref = krig.creature()

    krig.keep(ref)

    assert krig.kept_paths() == [f"{ALBUM_DIR}/02 - Creature.opus", f"{ALBUM_DIR}/cover.jpg"]
    _, tags, cover = krig.tagged[0]
    assert (tags.album, tags.track, tags.disc, tags.year, tags.isrc, tags.album_artist) == (
        ALBUM_TITLE,
        2,
        1,
        2025,
        "DEYO62300153",
        "LANDMVRKS",
    )
    assert cover == b"cover-bytes", "the release's picture is embedded"
    row = krig.row(ref)
    assert (row["album"], row["deezer_id"], row["identity_outcome"], row["identity_reason"]) == (
        ALBUM_TITLE,
        "3116792061",
        "matched",
        "matched",
    )
    assert krig.ref(ref)["file"]["navidromeSongId"] == "nd-1"
    assert (krig.music / ALBUM_DIR / "cover.jpg").read_bytes() == b"cover-bytes", "and the folder's picture is written"
    assert krig.catalogue.searched == [("LANDMVRKS", "Creature")], "one search for one keep"


def test_the_album_is_asked_by_the_downloaded_files_own_length(krig: KeepRig) -> None:
    """Rule 5. The import's listing is 12 s off (N-11), outside the 3 s tolerance, so a keeper that asked with it would never place the song."""
    ref = krig.creature()
    krig.keep(ref)
    assert krig.lengths_asked == [FILE_LENGTH_MS]
    assert krig.row(ref)["identity_outcome"] == "matched"


def test_without_a_readable_file_the_listing_is_all_there_is_and_the_song_stays_in_singles(krig: KeepRig) -> None:
    krig.file_length = None  # the rig's `_length_of` then answers the listing's, as `file_or_listing_length` does
    ref = krig.creature()
    krig.keep(ref)
    assert krig.lengths_asked == [LISTED_MS]
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    assert (krig.row(ref)["identity_outcome"], krig.row(ref)["identity_reason"]) == ("none", "no_same_recording")


def test_a_song_with_no_length_at_all_is_not_asked_and_nothing_is_remembered(krig: KeepRig) -> None:
    krig.file_length = None
    ref = krig.creature(duration=0)
    krig.keep(ref)
    assert krig.catalogue.searched == []
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    assert krig.row(ref)["identity_outcome"] is None


def test_the_picture_lookup_is_given_the_files_own_length_too(krig: KeepRig) -> None:
    """The stop-gap of slice 2 ("the keeper passes the refs LISTED length to the picture lookup until slice 3 reads the file") is closed: one length, the file's."""
    krig.cover_found = "https://cdn.dzcdn.net/found.jpg"
    krig.keeper._identify = None
    ref = krig.make_ref(durationMs=215_000)
    krig.file_length = 218_222

    krig.keep(ref)

    assert krig.cover_lengths == [218_222]


def test_a_song_the_catalogue_cannot_place_is_kept_in_singles_with_no_album(krig: KeepRig) -> None:
    ref = krig.unknown()
    krig.keep(ref)
    assert krig.audio_paths() == ["Encore/Nobody At All/Singles/A Song Nobody Recorded.opus"]
    assert krig.tagged[0][1].album is None
    row = krig.row(ref)
    assert row["album"] is None and (row["identity_outcome"], row["identity_reason"]) == ("none", "no_same_recording")


def test_a_song_whose_only_release_is_a_single_stays_in_singles_and_is_asked_again_by_the_pass(krig: KeepRig) -> None:
    """Slice 2 never stamps a single (a stamp is permanent and eight hits cannot prove no album carries the song): a keep must not either."""
    krig.catalogue = Catalogue({("LANDMVRKS", "Creature"): [single_hit()]}, albums(SINGLE))
    ref = krig.creature()

    krig.keep(ref)

    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    row = krig.row(ref)
    assert row["album"] is None and row["deezer_id"] is None
    assert (row["identity_outcome"], row["identity_reason"]) == ("none", "single_only")


def test_a_twin_of_a_song_that_is_already_on_the_album_is_a_held_pair_and_stays_in_singles(
    krig: KeepRig, caplog: pytest.LogCaptureFixture
) -> None:
    """The owner's Creature: another ref of the same song already has the album: held, nothing written, never merged here (slice 6)."""
    krig.creature(duration=OTHER_LISTED_MS, album=ALBUM_TITLE)
    ref = krig.creature()
    with caplog.at_level(logging.INFO, logger="encore_server.album_pass"):
        krig.keep(ref)
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    row = krig.row(ref)
    assert row["album"] is None and row["deezer_id"] is None
    assert (row["identity_outcome"], row["identity_reason"]) == ("held", "twin_held")
    assert any("held pair" in r.getMessage() for r in caplog.records)


def test_an_id_another_song_took_while_the_catalogue_was_asked_is_a_held_pair_and_not_a_stamp(krig: KeepRig) -> None:
    """The second layer of the write rule is the pass's own: a keep cannot stamp what the pass would refuse."""
    ref = krig.creature()
    taken = krig.catalogue.search

    def search_then_another_song_takes_the_id(artist: str, title: str) -> list[dict[str, Any]]:
        found = taken(artist, title)
        with krig.db.tx() as conn:
            other = refs.resolve(conn, {"title": "Some Other Song", "artists": ["Someone Else"], "durationMs": 100_000})["id"]
            conn.execute("UPDATE song_ref SET deezer_id = '3116792061' WHERE id = ?", (other,))
        return found

    krig.catalogue.search = search_then_another_song_takes_the_id  # type: ignore[method-assign]
    krig.keep(ref)
    row = krig.row(ref)
    assert row["album"] is None and row["deezer_id"] is None and row["identity_outcome"] == "held"
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]


def test_the_placeholder_literal_is_forgotten_and_never_reaches_the_tags_or_the_folder_of_a_song_the_catalogue_cannot_place(
    krig: KeepRig,
) -> None:
    ref = krig.unknown(album="[Unknown Album]")
    krig.keep(ref)
    assert krig.row(ref)["album"] is None
    assert krig.tagged[0][1].album is None
    assert not any("Unknown Album" in p for p in krig.kept_paths())


def test_the_placeholder_is_never_written_into_a_files_tags_or_folder_even_when_the_catalogue_cannot_be_asked(
    krig: KeepRig,
) -> None:
    """Audit B-110's own example saved a song once in `Singles` and once in `[Unknown Album]`: the placeholder says "no album", so it is no folder and no tag (one definition,
    `textnorm.is_placeholder_album`, in the planner and in the tag builder). The ref itself is untouched: nothing was asked, so nothing is forgotten."""
    krig.catalogue = Catalogue(down=True)
    ref = krig.creature(album="[Unknown Album]")
    before = krig.row(ref)

    krig.keep(ref)

    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    assert krig.tagged[0][1].album is None
    assert krig.row(ref) == before and before["album"] == "[Unknown Album]"


# ------------------------------------------------------------------------------------------------------------------ rule 2: a catalogue that cannot be asked never blocks a keep


def test_a_catalogue_that_cannot_be_asked_does_not_stop_the_keep_and_nothing_at_all_is_written_for_the_song(
    krig: KeepRig,
) -> None:
    krig.catalogue = Catalogue(down=True)
    ref = krig.creature(album="[Unknown Album]")
    before = krig.row(ref)

    krig.keep(ref)

    assert krig.row(ref) == before, "not one column of the song changed: no answer, no stamp, not even the placeholder"
    assert len(krig.audio_paths()) == 1 and krig.ref(ref)["file"]["navidromeSongId"] == "nd-1"


def test_a_catalogue_that_cannot_be_asked_keeps_exactly_as_before(krig: KeepRig) -> None:
    krig.catalogue = Catalogue(down=True)
    ref = krig.creature()
    krig.keep(ref)
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    assert krig.row(ref)["identity_outcome"] is None


def test_a_catalogue_that_rests_is_not_asked_at_all(krig: KeepRig) -> None:
    krig.asker = KeepAsker(
        krig.db,
        search=krig._search,
        album=krig._album,
        resting=lambda: "the catalogue asked this server to rest (30 s)",
        now=lambda: NOW,
    )
    ref = krig.creature()
    krig.keep(ref)
    assert krig.catalogue.searched == [] and krig.row(ref)["identity_outcome"] is None
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]


def test_an_album_answer_that_cannot_be_asked_does_not_stop_the_keep_either(krig: KeepRig) -> None:
    krig.catalogue = Catalogue({("LANDMVRKS", "Creature"): landmvrks().searches[("LANDMVRKS", "Creature")]}, {}, albums_down=True)
    ref = krig.creature()
    krig.keep(ref)
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    assert krig.row(ref)["identity_outcome"] is None


def test_a_keep_asks_with_a_short_wait_and_a_spent_budget_is_could_not_ask(krig: KeepRig) -> None:
    """The design: a short wait (10 s, not a pass's 120 s) for the whole question, the search and the albums together; a slow catalogue is an outage, never a `none`."""
    hits = landmvrks().searches[("LANDMVRKS", "Creature")]

    def slow_search(artist: str, title: str) -> list[dict[str, Any]]:
        krig.clock_now += 11.0  # it answered, but the keep's time is spent
        return hits

    krig.catalogue.search = slow_search  # type: ignore[method-assign]
    ref = krig.creature()

    krig.keep(ref)

    assert krig.waits == [10.0], "the search waits for its turn for 10 s at most, and no album is asked after the time is spent"
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    assert krig.row(ref)["identity_outcome"] is None, "a spent budget is 'could not ask': nothing is remembered"
    assert krig.catalogue.albumed == []


def test_the_waits_shrink_with_the_budget(krig: KeepRig) -> None:
    hits = landmvrks().searches[("LANDMVRKS", "Creature")]

    def search(artist: str, title: str) -> list[dict[str, Any]]:
        krig.clock_now += 6.0
        return hits

    krig.catalogue.search = search  # type: ignore[method-assign]
    krig.keep(krig.creature())
    assert krig.waits == [10.0, 4.0], "after 6 s only 4 of the 10 s are left for the album answer"


def test_an_exception_nobody_foresaw_in_the_album_question_never_stops_the_keep(
    krig: KeepRig, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(ref_id: str, length_ms: int | None) -> KeepAnswer:
        raise RuntimeError("something nobody expected")

    krig.keeper._identify = broken
    ref = krig.creature()
    with caplog.at_level(logging.INFO, logger="encore_server.keeper"):
        krig.keep(ref)
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    assert krig.ref(ref)["file"]["navidromeSongId"] == "nd-1"
    assert any("failed" in r.getMessage() for r in caplog.records)


def test_a_keeper_made_without_the_album_question_keeps_exactly_as_before(krig: KeepRig) -> None:
    krig.keeper._identify = None
    ref = krig.creature()
    krig.keep(ref)
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    assert krig.catalogue.searched == []


# ------------------------------------------------------------------------------------------------------------------ rule 3: an album the ref has is never rewritten


def test_a_song_that_has_its_album_is_not_asked_about_it_and_keeps_it(krig: KeepRig) -> None:
    ref = krig.creature(album="Hollow", trackNo=3)
    krig.keep(ref)
    assert krig.catalogue.searched == [], "no search for an album: the song has one (an import gave it)"
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Hollow/03 - Creature.opus"]
    assert krig.tagged[0][1].album == "Hollow"
    assert krig.row(ref)["album"] == "Hollow" and krig.row(ref)["identity_outcome"] is None


@pytest.mark.parametrize("basis", ["channel", "unknown"])
def test_a_song_whose_artist_is_a_channel_or_nobody_is_not_asked_by_a_keep(krig: KeepRig, basis: str) -> None:
    krig.keep(krig.creature(basis=basis))
    assert krig.catalogue.searched == []


def test_a_song_the_pass_answered_none_a_moment_ago_is_not_asked_again_by_a_keep(krig: KeepRig) -> None:
    ref = krig.creature()
    with krig.db.tx() as conn:
        conn.execute(
            "UPDATE song_ref SET identity_outcome = 'none', identity_reason = 'no_same_recording', identity_rev = ?, identity_tried_at = ? WHERE id = ?",
            (album_finder.IDENTITY_REVISION, NOW, ref),
        )
    krig.keep(ref)
    assert krig.catalogue.searched == [] and krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"]


def test_a_song_on_the_p2_25_worklist_is_not_asked_by_a_keep(krig: KeepRig) -> None:
    ref = krig.creature()
    with krig.db.tx() as conn:
        conn.execute("INSERT INTO ref_recheck (ref, at, moved) VALUES (?, 1, 0)", (ref,))
    krig.keep(ref)
    assert krig.catalogue.searched == []


# ------------------------------------------------------------------------------------------------------------------ the catalogue's picture and the folder's


def test_a_folder_that_has_a_picture_is_left_alone(krig: KeepRig) -> None:
    folder = krig.music / ALBUM_DIR
    folder.mkdir(parents=True)
    (folder / "folder.png").write_bytes(b"the Host's own picture")
    krig.keep(krig.creature())
    assert sorted(p.name for p in folder.iterdir()) == ["02 - Creature.opus", "folder.png"]


def test_no_folder_picture_is_written_into_singles(krig: KeepRig) -> None:
    """A Singles folder holds songs of no album: one picture there would be the picture of nothing."""
    krig.cover_found = "https://cdn.dzcdn.net/found.jpg"
    krig.keep(krig.unknown())
    assert krig.tagged[0][2] == b"cover-bytes"
    assert not any(p.endswith("cover.jpg") for p in krig.kept_paths())


def test_a_picture_found_by_name_for_a_song_that_has_its_album_is_the_folders_too(krig: KeepRig) -> None:
    krig.cover_found = "https://cdn.dzcdn.net/found.jpg"
    krig.keep(krig.make_ref())  # Radiohead, In Rainbows: no picture, an album
    assert krig.kept_paths() == [
        "Encore/Radiohead/In Rainbows/Weird Fishes - Arpeggi.opus",
        "Encore/Radiohead/In Rainbows/cover.jpg",
    ]


def test_a_picture_that_is_a_videos_thumbnail_is_embedded_but_never_becomes_the_folders_picture(krig: KeepRig) -> None:
    ref = krig.make_ref(videoId="abcdefghijk")
    krig.keep(ref)
    assert krig.tagged[0][2] == b"cover-bytes"
    assert not any(p.endswith("cover.jpg") for p in krig.kept_paths())


def test_write_folder_picture_never_writes_outside_the_servers_folder_or_over_a_picture(tmp_path: Path) -> None:
    root = tmp_path / "music" / "Encore"
    mine = root / "A" / "B"
    mine.mkdir(parents=True)
    hosts = tmp_path / "music" / "Albums" / "B"
    hosts.mkdir(parents=True)
    assert write_folder_picture(root, mine / "x.opus", b"jpg") is True
    assert [p.name for p in mine.iterdir()] == ["cover.jpg"], "no half-written file is left"
    assert write_folder_picture(root, mine / "x.opus", b"other") is False and (mine / "cover.jpg").read_bytes() == b"jpg"
    assert write_folder_picture(root, hosts / "x.opus", b"jpg") is False and list(hosts.iterdir()) == [], (
        "the Host's folder is never written into"
    )
    assert write_folder_picture(root, root / ".." / "Albums" / "B" / "x.opus", b"jpg") is False
    assert write_folder_picture(root, mine / "x.opus", None) is False
    (mine / "cover.jpg").unlink()
    (mine / "Folder.PNG").write_bytes(b"png")
    assert write_folder_picture(root, mine / "x.opus", b"jpg") is False, "a folder.* of any kind counts"


# ------------------------------------------------------------------------------------------------------------------ one builder of the tags, one planner of the place


def test_tags_of_a_ref_is_the_one_builder_of_a_files_tags() -> None:
    ref = {
        "title": "Creature",
        "artists": ["LANDMVRKS", "A Guest"],
        "album": "Hollow",
        "albumArtist": None,
        "trackNo": 3,
        "discNo": 1,
        "year": 2025,
        "isrc": "DEYO62300153",
        "mbid": None,
    }
    assert tags_of(ref) == Tags(
        title="Creature",
        artist="LANDMVRKS, A Guest",
        artists=("LANDMVRKS", "A Guest"),
        album="Hollow",
        album_artist="LANDMVRKS",
        track=3,
        disc=1,
        year=2025,
        isrc="DEYO62300153",
        mbid=None,
    )
    assert tags_of({"title": "T", "artists": ["A"]}).album is None


@pytest.mark.parametrize("placeholder", ["[Unknown Album]", "Unknown Album", " [unknown album] ", "", None])
def test_the_placeholder_album_is_no_album_in_the_tags_and_in_the_folder(tmp_path: Path, placeholder: str | None) -> None:
    ref = {"title": "Creature", "artists": ["LANDMVRKS"], "album": placeholder, "trackNo": None}
    assert tags_of(ref).album is None
    assert plan_for_ref(tmp_path, ref).path == tmp_path / "LANDMVRKS" / "Singles" / "Creature.opus"


def test_an_album_that_only_starts_like_the_placeholder_is_a_real_album(tmp_path: Path) -> None:
    ref = {"title": "Creature", "artists": ["LANDMVRKS"], "album": "Unknown Album Part Two", "trackNo": None}
    assert tags_of(ref).album == "Unknown Album Part Two"
    assert plan_for_ref(tmp_path, ref).path == tmp_path / "LANDMVRKS" / "Unknown Album Part Two" / "Creature.opus"


def test_plan_for_ref_is_the_one_planner_of_a_files_place(tmp_path: Path) -> None:
    ref = {"title": "Creature", "artists": ["LANDMVRKS"], "album": ALBUM_TITLE, "trackNo": 2}
    assert plan_for_ref(tmp_path, ref).path == tmp_path / "LANDMVRKS" / ALBUM_TITLE / "02 - Creature.opus"
    assert (
        plan_for_ref(tmp_path, {**ref, "album": None, "trackNo": None}).path
        == tmp_path / "LANDMVRKS" / "Singles" / "Creature.opus"
    )
    assert (
        plan_for_ref(tmp_path, {**ref, "albumArtist": "Various"}, ".m4a").path
        == tmp_path / "Various" / ALBUM_TITLE / "02 - Creature.m4a"
    )


# ------------------------------------------------------------------------------------------------------------------ rule 6 and audit B-110: one file per ref


def place(krig: KeepRig, relative: str, *, ref: str, source: str = "youtube", navidrome: str | None = None) -> Path:
    path = krig.music / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(AUDIO)
    with krig.db.tx() as conn:
        refs.attach_file(conn, ref, navidrome_song_id=navidrome, path=relative, codec="opus", bitrate_kbps=None, source=source)
    return path


def files_of(krig: KeepRig, ref: str) -> list[str]:
    with krig.db.read() as conn:
        return [r["path"] for r in conn.execute("SELECT path FROM song_file WHERE ref = ? ORDER BY added_at, path", (ref,))]


def test_b110_a_song_whose_album_became_known_after_its_file_was_placed_is_not_saved_again(krig: KeepRig) -> None:
    """The cause of audit B-110: the keeper looked for an existing file only where it would put the song NOW. The file is in Singles, the album became known (the pass
    stamped it), the keep is repeated (the music server had not found the file yet): it must find ITS file, not download the song again."""
    ref = krig.creature()
    first = place(krig, "Encore/LANDMVRKS/Singles/Creature.opus", ref=ref)
    with krig.db.tx() as conn:
        conn.execute("UPDATE song_ref SET album = ?, track_no = 2 WHERE id = ?", (ALBUM_TITLE, ref))

    krig.keep(ref)

    assert krig.source.asked == [], "no second download"
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"] and first.read_bytes() == AUDIO
    assert krig.ref(ref)["file"]["navidromeSongId"] == "nd-1"
    assert files_of(krig, ref) == ["Encore/LANDMVRKS/Singles/Creature.opus"], "one file row, the one it had"


def test_b110_the_other_direction_the_file_is_in_the_album_folder_and_the_album_is_not_known(krig: KeepRig) -> None:
    ref = krig.creature()
    place(krig, f"{ALBUM_DIR}/02 - Creature.opus", ref=ref)
    krig.keep(ref)
    assert krig.source.asked == [] and len(krig.audio_paths()) == 1


def test_b110_only_a_file_the_keeper_wrote_under_encore_is_taken_as_the_refs_own(krig: KeepRig) -> None:
    """A row of the Host's own library (`source = 'library'`), or a path outside the server's own folder, is never reused as a kept file: `_link` would attach it as
    `youtube` and a later repair would move it."""
    ref = krig.creature()
    place(krig, "Artists/LANDMVRKS/Creature.opus", ref=ref, source="library")
    place(krig, "Other/Creature.opus", ref=ref, source="youtube")
    krig.keep(ref)
    assert len(krig.source.asked) == 1, "neither is the keeper's: the song is fetched"
    with krig.db.read() as conn:
        rows = {r["path"]: r["source"] for r in conn.execute("SELECT path, source FROM song_file WHERE ref = ?", (ref,))}
    assert rows["Artists/LANDMVRKS/Creature.opus"] == "library", "the Host's file is still the Host's"
    assert (krig.music / "Artists/LANDMVRKS/Creature.opus").read_bytes() == AUDIO


def test_b110_a_path_that_leaves_the_server_folder_is_never_taken(krig: KeepRig) -> None:
    ref = krig.creature()
    (krig.music / "secret.opus").write_bytes(AUDIO)
    with krig.db.tx() as conn:
        conn.execute(
            "INSERT INTO song_file (id, ref, path, codec, source, preferred, added_at) VALUES ('sf_x', ?, 'Encore/../secret.opus', 'opus', 'youtube', 1, 1)",
            (ref,),
        )
    krig.keep(ref)
    assert len(krig.source.asked) == 1


def test_b110_a_row_whose_file_is_gone_is_not_a_file(krig: KeepRig) -> None:
    ref = krig.creature()
    with krig.db.tx() as conn:
        conn.execute(
            "INSERT INTO song_file (id, ref, path, codec, source, preferred, added_at) VALUES ('sf_gone', ?, 'Encore/LANDMVRKS/Singles/Creature.opus', 'opus', 'youtube', 1, 1)",
            (ref,),
        )
    krig.keep(ref)
    assert len(krig.source.asked) == 1


def test_a_file_at_the_planned_place_that_another_ref_holds_is_not_handed_to_this_ref(krig: KeepRig) -> None:
    """The shared file of N-11's notes (Creature's twin): two refs of one song, one file. `find_existing` gave it to whichever kept second."""
    krig.keeper._identify = None  # this test is about the FILE, not the album: both refs are filed as they were before slice 3
    first = krig.creature()
    second = krig.creature(duration=OTHER_LISTED_MS)
    assert first != second
    place(krig, "Encore/LANDMVRKS/Singles/Creature.opus", ref=first, navidrome="nd-first")

    krig.keep(second)

    assert len(krig.source.asked) == 1, "the second ref has no file of its own: it is fetched"
    assert files_of(krig, first) == ["Encore/LANDMVRKS/Singles/Creature.opus"]
    assert files_of(krig, second) == ["Encore/LANDMVRKS/Singles/Creature (2).opus"]


def test_a_holder_is_found_whatever_the_case_of_the_path(krig: KeepRig) -> None:
    krig.keeper._identify = None  # this test is about the FILE, not the album: both refs are filed as they were before slice 3
    first = krig.creature()
    second = krig.creature(duration=OTHER_LISTED_MS)
    place(krig, "Encore/LANDMVRKS/Singles/Creature.opus", ref=first, navidrome="nd-first")
    with krig.db.tx() as conn:
        conn.execute("UPDATE song_file SET path = 'ENCORE/landmvrks/SINGLES/creature.OPUS' WHERE ref = ?", (first,))
    krig.keep(second)
    assert len(krig.source.asked) == 1


def test_a_file_at_the_planned_place_that_nobody_holds_is_still_reused(krig: KeepRig) -> None:
    """A run that died after placing the file (before its row): the file is linked, not downloaded again (unchanged)."""
    ref = krig.creature()
    path = krig.music / "Encore/LANDMVRKS/Singles/Creature.opus"
    path.parent.mkdir(parents=True)
    path.write_bytes(AUDIO)
    krig.keep(ref)
    assert krig.source.asked == [] and krig.ref(ref)["file"]["navidromeSongId"] == "nd-1"


def test_a_file_another_keep_placed_while_this_song_was_fetched_is_not_taken_when_another_ref_holds_it(krig: KeepRig) -> None:
    """`_finish` looks once more at the target after the download: the same rule as `_existing`."""
    krig.keeper._identify = None  # this test is about the FILE, not the album: both refs are filed as they were before slice 3
    first = krig.creature()
    second = krig.creature(duration=OTHER_LISTED_MS)
    target = krig.music / "Encore/LANDMVRKS/Singles/Creature.opus"
    real_download = krig.source.download

    def download_while_another_keep_places_its_file(wanted: Any, stem: Path, *, max_bytes: int) -> Path:
        place(krig, "Encore/LANDMVRKS/Singles/Creature.opus", ref=first, navidrome="nd-first")
        return real_download(wanted, stem, max_bytes=max_bytes)

    krig.source.download = download_while_another_keep_places_its_file  # type: ignore[method-assign]
    krig.keep(second)
    assert target.exists() and files_of(krig, second) == ["Encore/LANDMVRKS/Singles/Creature (2).opus"]


# ------------------------------------------------------------------------------------------------------------------ no file of the Host's is ever touched


def test_a_keep_never_writes_or_deletes_anything_outside_the_servers_own_folder(krig: KeepRig) -> None:
    hosts = krig.music / "Albums" / "LANDMVRKS" / ALBUM_TITLE
    hosts.mkdir(parents=True)
    (hosts / "02 - Creature.flac").write_bytes(b"the Host's own file")
    (hosts / "cover.jpg").write_bytes(b"the Host's own picture")
    before = {p: p.read_bytes() for p in (krig.music / "Albums").rglob("*") if p.is_file()}

    krig.keep(krig.creature())

    assert {p: p.read_bytes() for p in (krig.music / "Albums").rglob("*") if p.is_file()} == before
    assert all(p.startswith("Encore/") for p in krig.kept_paths())


# ------------------------------------------------------------------------------------------------------------------ a song the catalogue just placed is not looked up by name for a picture


def test_a_song_the_catalogue_just_placed_whose_release_has_no_picture_is_not_looked_up_by_name_for_one(krig: KeepRig) -> None:
    """A search by name could only pick ANOTHER release's picture for it: the cover finder asks the very release by its id later (slice 2), never by name."""
    krig.cover_found = "https://cdn.dzcdn.net/another-release.jpg"
    krig.catalogue = Catalogue(landmvrks().searches, {ALBUM: derive(albums(ALBUM)[ALBUM], cover=None)})
    ref = krig.creature()

    krig.keep(ref)

    assert krig.row(ref)["identity_outcome"] == "matched" and krig.audio_paths() == [f"{ALBUM_DIR}/02 - Creature.opus"]
    assert krig.cover_asked == [], "no picture look-up by name for a song the catalogue placed"
    assert not any(p.endswith("cover.jpg") for p in krig.kept_paths())


# ------------------------------------------------------------------------------------------------------------------ the real calls: through the gate, and through the app


def test_a_keep_through_the_real_gate_files_the_song_under_its_album(
    tmp_path: Path, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`KeepAsker.on` over the real catalogue code and the RECORDED answers of the catalogue: the search is `deezer.search_tracks` as a background turn with the keep's short wait,
    the album is `Catalogue.album` as a background turn. (The conftest guard replaces the pass's search by one that cannot be asked; this test puts the real one back.)"""
    upstream = RecordedDeezer()
    client = DeezerClient(Gate(rate=1000, burst=1000, background_gap_s=0.0), httpx.Client(transport=upstream.transport()))
    deezer.install(client)
    monkeypatch.setattr(album_pass, "search_the_catalogue_for_keep", the_real_search)
    krig = KeepRig(tmp_path, db)
    krig.keeper._identify = KeepAsker.on(db, RealCatalogue(client, Cache(None)), now=lambda: NOW)
    ref = krig.creature()

    krig.keep(ref)

    assert krig.audio_paths() == [f"{ALBUM_DIR}/02 - Creature.opus"]
    assert krig.row(ref)["identity_outcome"] == "matched"
    assert upstream.paths()[0] == "/search" and any(path.startswith("/album/") for path in upstream.paths())


def test_a_server_whose_catalogue_is_switched_off_keeps_without_a_request_and_without_an_album(
    tmp_path: Path, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ENCORE_CATALOGUE=0` through the real gate (`Gate(enabled=False)`, which `api._default_catalogue` builds from the setting), not a fake that fails: no request goes out, the keep
    goes on exactly as before and nothing is remembered about the song."""
    upstream = RecordedDeezer()
    client = DeezerClient(Gate(enabled=False), httpx.Client(transport=upstream.transport()))
    deezer.install(client)
    monkeypatch.setattr(album_pass, "search_the_catalogue_for_keep", the_real_search)
    krig = KeepRig(tmp_path, db)
    krig.keeper._identify = KeepAsker.on(db, RealCatalogue(client, None), now=lambda: NOW)
    ref = krig.creature()
    before = krig.row(ref)

    krig.keep(ref)

    assert upstream.paths() == [], "no request is opened to the catalogue"
    assert krig.audio_paths() == ["Encore/LANDMVRKS/Singles/Creature.opus"] and krig.row(ref) == before


def test_the_app_asks_the_album_of_a_song_it_keeps(
    tmp_path: Path, verifier: FakeVerifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without this a keeper that nothing wires would pass every test above. A like keeps the song in the background; the app's own keeper asks the (recorded) catalogue and files
    it under its album."""

    class Configured(FakeNavidrome):
        configured = True

    music = tmp_path / "music"
    music.mkdir()
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=music,
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        workers=False,
        min_free_gb=0.0,
    )
    monkeypatch.setattr("encore_server.keeper.keeper.run_command", fake_ffmpeg)
    monkeypatch.setattr(
        "encore_server.keeper.keeper.fetch_cover", lambda url: b"cover-bytes"
    )  # the picture host is not reached from a test
    monkeypatch.setattr(album_pass, "search_the_catalogue_for_keep", the_real_search)
    upstream = RecordedDeezer()
    catalogue = RealCatalogue(
        DeezerClient(Gate(rate=1000, burst=1000, background_gap_s=0.0), httpx.Client(transport=upstream.transport())), Cache(None)
    )
    app = create_app(settings, verifier=verifier, youtube=FakeSource(), navidrome=Configured(music), catalogue=catalogue)  # type: ignore[arg-type]
    with TestClient(app) as client:
        service = client.app.state.services  # type: ignore[attr-defined]
        item = {"title": "Creature", "artists": ["LANDMVRKS"], "durationMs": FILE_LENGTH_MS}
        ref = str(resolve(client, "marwa", item)[0]["id"])
        assert client.put(f"/encore/api/v1/likes/{ref}", params=creds("marwa")).status_code == 200

        service.scheduler.drain()

    kept = sorted(p.relative_to(music).as_posix() for p in (music / "Encore").rglob("*.opus"))
    assert kept == [f"{ALBUM_DIR}/02 - Creature.opus"]
    assert upstream.paths()[0] == "/search"
