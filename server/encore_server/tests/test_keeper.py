"""The keeper: a saved song is fetched once, tagged, placed in the shared folder, found by the music server and attached to its ref."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import pytest

from encore_server import library, refs
from encore_server.db import Database
from encore_server.deezer import LookupUnavailable
from encore_server.keeper.keeper import Keeper, KeepSettings
from encore_server.keeper.process import RunResult
from encore_server.keeper.tagging import Tags
from encore_server.scheduler import GiveUp, Retry, WorkItem
from encore_server.sources.youtube.errors import DownloadError
from encore_server.sources.youtube.source import Wanted

AUDIO = b"OggS" + bytes(range(256)) * 40


class FakeSource:
    def __init__(self) -> None:
        self.asked: list[Wanted] = []
        self.failure: Exception | None = None
        self.resting = 0.0

    def resting_for(self) -> float:
        return self.resting

    def download(self, wanted: Wanted, stem: Path, *, max_bytes: int) -> Path:
        self.asked.append(wanted)
        if self.failure is not None:
            raise self.failure
        stem.parent.mkdir(parents=True, exist_ok=True)
        path = stem.with_name(stem.name + ".webm")
        path.write_bytes(AUDIO)
        return path


class FakeNavidrome:
    """Finds a file once it has been asked to scan (or never, to show the wait)."""

    def __init__(self, music: Path) -> None:
        self.music = music
        self.scans = 0
        self.finds_after_scan = True
        self.known: dict[str, str] = {}

    def start_scan(self, *, full: bool = False) -> bool:
        self.scans += 1
        return True

    def scanning(self) -> bool | None:
        return False

    def get_song(self, song_id: str) -> dict[str, object] | None:
        return {
            "id": song_id,
            "albumId": "al-1",
            "artistId": "ar-1",
            "coverArt": "al-1",
            "suffix": "opus",
            "size": 4096,
            "unwanted": "x",
        }

    def find_song(
        self, *, artist: str, title: str, album: str | None = None, relative_path: str | None = None, size: int | None = None
    ) -> str | None:
        if relative_path in self.known:
            return self.known[relative_path]
        if self.scans and self.finds_after_scan and relative_path and (self.music / relative_path).is_file():
            self.known[relative_path] = f"nd-{len(self.known) + 1}"
            return self.known[relative_path]
        return None


def fake_ffmpeg(argv: list[str], timeout: int) -> RunResult:
    """`ffmpeg -i in -c:a copy out`: copies the bytes."""
    shutil.copyfile(argv[argv.index("-i") + 1], argv[-1])
    return RunResult(0, "", "")


class Rig:
    def __init__(self, tmp: Path, db: Database) -> None:
        self.music = tmp / "music"
        self.music.mkdir()
        self.db = db
        self.source = FakeSource()
        self.navidrome = FakeNavidrome(self.music)
        self.tagged: list[tuple[str, Tags, bytes | None]] = []
        self.told: list[dict[str, int]] = []
        self.slept: list[float] = []
        self.now = 0.0
        self.cover_found: str | None = None
        self.cover_breaks = False
        self.cover_unavailable = False
        self.cover_asked: list[tuple[str, str, str | None]] = []

        def write_tags(path: Path, tags: Tags, cover: bytes | None = None) -> bool:
            self.tagged.append((path.suffix, tags, cover))
            return True

        def sleep(seconds: float) -> None:
            self.slept.append(seconds)
            self.now += seconds

        self.keeper = Keeper(
            db,
            self.source,
            self.navidrome,  # type: ignore[arg-type]
            KeepSettings(music_dir=self.music, min_free_gb=0.0, scan_wait_s=10.0, scan_poll_s=2.0),
            tmp / "work",
            runner=fake_ffmpeg,
            write_tags_=write_tags,
            fetch_cover_=lambda url: b"cover-bytes" if url else None,
            find_cover_=self.find_cover,
            on_changed=self.told.append,
            sleep=sleep,
            clock=lambda: self.now,
        )

    def find_cover(self, artist: str, title: str, album: str | None) -> str | None:
        self.cover_asked.append((artist, title, album))
        if self.cover_unavailable:
            raise LookupUnavailable("the catalogue is resting")
        if self.cover_breaks:
            raise RuntimeError("the catalogue is down")
        return self.cover_found

    def make_ref(self, **extra: Any) -> str:
        item = {
            "title": "Weird Fishes / Arpeggi",
            "artists": ["Radiohead"],
            "album": "In Rainbows",
            "durationMs": 318000,
            **extra,
        }
        with self.db.tx() as conn:
            return str(refs.resolve(conn, item)["id"])

    def keep(self, ref: str) -> None:
        self.keeper.handle(WorkItem("wk_test", "keep", ref, 4, 1, ()))

    def ref(self, ref: str) -> dict[str, Any]:
        with self.db.read() as conn:
            return refs.get_ref(conn, ref)


@pytest.fixture()
def rig(tmp_path: Path, db: Database) -> Rig:
    return Rig(tmp_path, db)


def test_a_kept_song_lands_in_the_shared_folder_tagged_found_and_attached(rig: Rig) -> None:
    ref = rig.make_ref(isrc="GBAYE0701234", trackNo=4, year=2007, coverUrl="https://e-cdns-images.dzcdn.net/cover.jpg")

    rig.keep(ref)

    kept = rig.ref(ref)["file"]
    assert kept["navidromeSongId"] == "nd-1" and kept["codec"] == "opus"
    files = list((rig.music / "Encore").rglob("*.opus"))
    assert [f.relative_to(rig.music).as_posix() for f in files] == [
        "Encore/Radiohead/In Rainbows/04 - Weird Fishes - Arpeggi.opus"
    ]
    assert files[0].read_bytes() == AUDIO
    suffix, tags, cover = rig.tagged[0]
    assert suffix == ".opus" and cover == b"cover-bytes"
    assert (tags.title, tags.artist, tags.album, tags.track, tags.year, tags.isrc) == (
        "Weird Fishes / Arpeggi",
        "Radiohead",
        "In Rainbows",
        4,
        2007,
        "GBAYE0701234",
    )


def test_a_song_by_several_artists_is_tagged_with_each_of_them_on_its_own(rig: Rig) -> None:
    ref = rig.make_ref(artists=["Post Malone", "Swae Lee"], title="Sunflower")

    rig.keep(ref)

    tags = rig.tagged[0][1]
    assert tags.artist == "Post Malone, Swae Lee", "what is shown stays the joined string"
    assert tags.artists == ("Post Malone", "Swae Lee")
    assert tags.album_artist == "Post Malone"


def test_a_song_that_came_without_a_picture_gets_the_catalogues_in_its_file_and_on_its_ref(rig: Rig) -> None:
    rig.cover_found = "https://cdn.dzcdn.net/found.jpg"
    ref = rig.make_ref()

    rig.keep(ref)

    assert rig.cover_asked == [("Radiohead", "Weird Fishes / Arpeggi", "In Rainbows")]
    assert rig.tagged[0][2] == b"cover-bytes"
    assert rig.ref(ref)["coverUrl"] == "https://cdn.dzcdn.net/found.jpg"


def test_a_song_that_has_a_picture_is_not_looked_up(rig: Rig) -> None:
    rig.keep(rig.make_ref(coverUrl="https://e-cdns-images.dzcdn.net/cover.jpg"))

    assert rig.cover_asked == []


@pytest.mark.parametrize("breaks", [False, True])
def test_no_picture_found_or_a_lookup_that_fails_never_stops_the_keep(rig: Rig, breaks: bool) -> None:
    rig.cover_breaks = breaks
    ref = rig.make_ref()

    rig.keep(ref)

    assert rig.ref(ref)["file"]["navidromeSongId"] == "nd-1"
    assert rig.tagged[0][2] is None
    assert rig.ref(ref)["coverUrl"] is None


def test_a_catalogue_that_cannot_be_asked_is_one_quiet_line_and_never_stops_the_keep(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """P2-12: with the gate resting or `ENCORE_CATALOGUE=0` EVERY song kept used to log a stack trace here."""
    rig.cover_unavailable = True
    ref = rig.make_ref()

    with caplog.at_level(logging.INFO, logger="encore_server.keeper"):
        rig.keep(ref)

    assert rig.ref(ref)["file"]["navidromeSongId"] == "nd-1" and rig.ref(ref)["coverUrl"] is None
    assert "could not be asked" in caplog.text and all(record.exc_info is None for record in caplog.records)


def test_the_work_folder_is_left_clean(rig: Rig, tmp_path: Path) -> None:
    rig.keep(rig.make_ref())

    assert list((tmp_path / "work").glob("keep-*")) == []


def test_a_song_that_is_already_kept_is_not_fetched_again(rig: Rig) -> None:
    ref = rig.make_ref()
    rig.keep(ref)

    rig.keep(ref)

    assert len(rig.source.asked) == 1


def test_a_file_placed_by_a_run_that_died_is_linked_not_downloaded_again(rig: Rig) -> None:
    ref = rig.make_ref(trackNo=4)
    folder = rig.music / "Encore" / "Radiohead" / "In Rainbows"
    folder.mkdir(parents=True)
    (folder / "04 - Weird Fishes - Arpeggi.opus").write_bytes(AUDIO)

    rig.keep(ref)

    assert rig.source.asked == []
    assert rig.ref(ref)["file"]["navidromeSongId"] == "nd-1"


def test_when_the_music_server_has_not_seen_the_file_yet_it_is_attached_without_an_id_and_linked_on_the_next_try(
    rig: Rig,
) -> None:
    ref = rig.make_ref()
    rig.navidrome.finds_after_scan = False

    with pytest.raises(Retry):
        rig.keep(ref)

    attached = rig.ref(ref)["file"]
    assert attached is not None and attached["navidromeSongId"] is None
    assert rig.slept, "it waited, polling, before giving the scanner more time"

    rig.navidrome.finds_after_scan = True
    rig.keep(ref)

    linked = rig.ref(ref)["file"]
    assert linked["navidromeSongId"] == "nd-1" and linked["id"] == attached["id"]
    assert len(rig.source.asked) == 1, "the file was not downloaded a second time"


def test_a_file_the_music_server_never_finds_is_not_retried_every_thirty_seconds_for_ever(rig: Rig) -> None:
    """B7 (QA-BACKEND): the link step asked for a retry after a fixed 30 s, which the scheduler never counts towards giving up, so a music
    server that does not have the music folder as a library (or cannot read the file) kept the keep queued for ever and it never said failed.
    A retry with no pause given is the scheduler's own bounded one: 30 s, 2 minutes, 10 minutes, an hour, then failed with the reason."""
    ref = rig.make_ref()
    rig.navidrome.finds_after_scan = False

    with pytest.raises(Retry) as caught:
        rig.keep(ref)

    assert caught.value.after_s is None, "no pause of its own: the scheduler's backoff and its last try decide"
    assert "music server" in caught.value.reason and "library" in caught.value.reason, "the reason names what to check"


def test_everyone_who_has_the_song_is_told_the_file_is_there(rig: Rig, db: Database) -> None:
    ref = rig.make_ref()
    with db.tx() as conn:
        marwa = library.ensure_person(conn, "marwa")["id"]
        nina = library.ensure_person(conn, "nina")["id"]
        library.set_item(conn, marwa, "like", ref)
        library.create_playlist(conn, nina, "pl_" + "0" * 26, "Road trip")
        library.add_entries(conn, nina, "pl_" + "0" * 26, [{"ref": ref}])
        before = {marwa: library.latest_cursor(conn, marwa), nina: library.latest_cursor(conn, nina)}

    rig.keep(ref)

    assert set(rig.told[0]) == {marwa, nina}
    assert all(rig.told[0][p] > before[p] for p in (marwa, nina))
    with db.read() as conn:
        like = library.changes(conn, marwa, before[marwa])
    assert like["refs"][0]["file"]["navidromeSongId"] == "nd-1"


@pytest.mark.parametrize(
    ("code", "outcome"),
    [
        ("unavailable", GiveUp),
        ("age_restricted", GiveUp),
        ("not_found", GiveUp),
        ("too_big", GiveUp),
        ("blocked", Retry),
        ("timeout", Retry),
        ("search_failed", Retry),  # B-122: a search that could not be made is not "no copy of the song"
    ],
)
def test_what_goes_wrong_fetching_is_a_retry_or_a_giving_up(rig: Rig, code: str, outcome: type[Exception]) -> None:
    ref = rig.make_ref()
    rig.source.failure = DownloadError(code)

    with pytest.raises(outcome):
        rig.keep(ref)

    assert rig.ref(ref)["file"] is None
    assert list((rig.music / "Encore").rglob("*.*")) == []


def test_a_failure_nobody_foresaw_is_left_for_the_scheduler_to_retry(rig: Rig) -> None:
    ref = rig.make_ref()
    rig.source.failure = DownloadError("download_failed", "HTTP 500")

    with pytest.raises(DownloadError):
        rig.keep(ref)


def test_a_full_disk_stops_keeping_and_fetches_nothing(rig: Rig) -> None:
    ref = rig.make_ref()
    rig.keeper._settings = KeepSettings(music_dir=rig.music, min_free_gb=10**9)

    with pytest.raises(Retry) as caught:
        rig.keep(ref)

    assert "free" in caught.value.reason and caught.value.after_s == 1800
    assert rig.source.asked == []


def test_a_recording_over_two_and_a_half_hours_is_played_but_not_kept(rig: Rig) -> None:
    """The limit is 150 minutes (owner, 7 Nov 2026; it was 45): above it a song is played from YouTube and never saved."""
    ref = rig.make_ref(title="A whole audiobook", artists=["Reader"], durationMs=181 * 60 * 1000)

    with pytest.raises(GiveUp) as caught:
        rig.keep(ref)

    assert "played but not kept" in caught.value.reason and "150" in caught.value.reason and rig.source.asked == []


def test_a_two_hour_recitation_is_kept(rig: Rig) -> None:
    """The owner's first song, a 2-hour recitation of Surat Al-Baqarah, could not be saved at the old limit of 45 minutes."""
    ref = rig.make_ref(title="Surat Al-Baqarah", artists=["Reciter"], durationMs=120 * 60 * 1000)

    rig.keep(ref)

    assert rig.source.asked, "the song was fetched, not refused for its length"


def test_two_songs_of_one_album_share_its_folder(rig: Rig) -> None:
    first = rig.make_ref(title="15 Step", trackNo=1)
    second = rig.make_ref(title="Bodysnatchers", trackNo=2, durationMs=242000)

    rig.keep(first)
    rig.keep(second)

    folders = {p.parent for p in (rig.music / "Encore").rglob("*.opus")}
    assert len(folders) == 1


def test_replacing_the_file_changes_nothing_a_person_has(rig: Rig, db: Database) -> None:
    ref = rig.make_ref()
    with db.tx() as conn:
        marwa = library.ensure_person(conn, "marwa")["id"]
        library.set_item(conn, marwa, "like", ref)
        library.create_playlist(conn, marwa, "pl_" + "1" * 26, "Mine")
        library.add_entries(conn, marwa, "pl_" + "1" * 26, [{"ref": ref}])
    rig.keep(ref)
    with db.read() as conn:
        before = library.changes(conn, marwa, 0)

    # A better copy arrives later (the quality tier), and the old file is renamed on disk: only the file row changes.
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd-77",
            path="Encore/Radiohead/In Rainbows/renamed.flac",
            codec="flac",
            bitrate_kbps=900,
            source="quality",
        )
        library.touch_ref_holders(conn, ref)
    with db.read() as conn:
        after = library.changes(conn, marwa, 0)

    assert after["refs"][0]["file"]["navidromeSongId"] == "nd-77"
    assert [like["ref"] for like in after["likes"]] == [like["ref"] for like in before["likes"]] == [ref]
    assert [e["ref"] for e in after["entries"]] == [e["ref"] for e in before["entries"]] == [ref]
    assert [e["id"] for e in after["entries"]] == [e["id"] for e in before["entries"]]


def test_the_apps_view_of_a_kept_file_carries_what_the_music_server_knows(rig: Rig) -> None:
    ref = rig.make_ref()

    rig.keep(ref)

    meta = rig.ref(ref)["file"]["meta"]
    assert meta == {"albumId": "al-1", "artistId": "ar-1", "coverArt": "al-1", "suffix": "opus", "size": 4096}
