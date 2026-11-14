"""N-26 / audit B-125: who is the artist of an imported YouTube upload (docs/tasks/P2-songs-as-references.md, "N-26").

The titles, channels, video types and credited artists below are REAL: `tests/fixtures/ytm/n26/*.json` are YouTube Music's own search answers, recorded
on 2026-11-14 (`videoType` and `artists` exactly as the service gave them). A playlist entry is built from one of them the way `get_playlist` shapes an
entry (the shape of the first track of `tests/fixtures/ytm/playlist_album.json`, filled with the recorded `videoId`, `title`, `artists`, `videoType` and
length): the VALUES are recorded, the SHAPE around them is the recorded playlist's. No test asks the network.

A table row marked KNOWN LEFTOVER pins a result that is wrong or incomplete today on purpose, so that the slice that fixes it changes the row on purpose.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import pytest

from encore_server.imports.readers import Track, read_playlist

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "ytm"
N26 = FIXTURES / "n26"
LINK = "https://music.youtube.com/playlist?list=OLAK5uy_m59x-hBFsC789l1_qWwFXwH3gjntwy_CA"


def recorded_result(video_id: str) -> dict[str, Any]:
    for path in sorted(N26.glob("*.json")):
        for result in json.loads(path.read_text(encoding="utf-8"))["results"]:
            if result["videoId"] == video_id:
                return result  # type: ignore[no-any-return]
    raise AssertionError(f"no recorded answer has the video {video_id}")


def playlist_entry(video_id: str, **changes: Any) -> dict[str, Any]:
    """A `get_playlist` entry for a recorded search result (see the module text for what is recorded and what is shape)."""
    result = recorded_result(video_id)
    base = json.loads((FIXTURES / "playlist_album.json").read_text(encoding="utf-8"))["tracks"][0]
    entry = copy.deepcopy(base)
    entry.pop("creditsBrowseId", None)
    entry.update(
        videoId=video_id,
        title=result["title"],
        artists=copy.deepcopy(result.get("artists")),  # a recorded answer can have none at all (the OMV `Akudama`)
        album=copy.deepcopy(result.get("album")),
        videoType=result["videoType"],
        isAvailable=True,
        duration_seconds=result["duration_seconds"],
        duration=result["duration"],
    )
    entry.update(changes)
    return entry


def read_one(entry: dict[str, Any]) -> Track:
    playlist = read_playlist(LINK, ytmusic=lambda ident: {"title": "Recorded", "tracks": [entry]})
    return playlist.tracks[0]


def reading_of_entry(entry: dict[str, Any]) -> tuple[str, str, str]:
    track = read_one(entry)
    return track.artist, track.title, track.artist_basis


def reading_of(video_id: str, **changes: Any) -> tuple[str, str, str]:
    return reading_of_entry(playlist_entry(video_id, **changes))


# --------------------------------------------------------------------------- what the importer did wrong (B-125), now right


@pytest.mark.parametrize(
    ("video", "expected"),
    [
        # The audit's first row: KEXP's own upload. Filed under "KEXP" with the whole title before.
        ("kGJwMhVICg0", ("Tinariwen", "Full Performance (Live on KEXP)", "title")),
        # The same session re-uploaded by a person whose channel name is Cyrillic: a MIDDLE DOT is the separator.
        ("bUO6qINN5nY", ("Tinariwen", "Full Performance · Live on KEXP", "title")),
        ("nkCwGCDaaZ4", ("Etran de L'Aïr", "Full Performance (Live on KEXP)", "title")),
        # An EN DASH is a separator ("Bad Bunny – MONACO ..."), the uploader is a stranger's channel.
        ("XYlvVLvMmHc", ("Bad Bunny", "MONACO 🔥 Afro House Remix | INSANE Latin Energy 2026", "title")),
        # A label's upload typed UGC: the band is in the title.
        ("MSUGmeWqbCY", ("Loathe", "Two-Way Mirror", "title")),
        ("iT6vqeL-ysI", ("Metallica", "One", "title")),
    ],
)
def test_an_upload_is_filed_under_the_performer_its_title_names_not_under_its_channel(video: str, expected: tuple[str, str, str]) -> None:
    assert reading_of(video) == expected


def test_the_uploader_is_kept_as_a_fact_for_an_upload_and_not_for_a_song() -> None:
    assert read_one(playlist_entry("kGJwMhVICg0")).uploader == "KEXP"
    assert read_one(playlist_entry("phSYyQ1xGKw")).uploader is None  # the recorded catalogue song `Bismillah`


# --------------------------------------------------------------------------- the entries that are right today stay exactly as they are


def test_a_song_of_the_catalogue_keeps_the_artists_youtube_music_declares() -> None:
    track = read_one(playlist_entry("phSYyQ1xGKw"))
    assert (track.artist, track.title, track.artist_basis, track.uploader) == ("Tinariwen", "Bismillah", "declared", None)
    assert track.album == "The Radio Tisdas Sessions"


@pytest.mark.parametrize(
    ("video", "expected"),
    [
        # An official video is credited to the band, with no separator in its title.
        ("eel5yD9TKms", ("napalm death", "Down in the Zero", "declared")),
        ("_PJvpq8uOZM", ("Bad Bunny", "MONACO", "declared")),
        # ... and when the title repeats the credited artist before a colon or a dash it stays what YouTube Music says.
        ("WM8bTdBs-cw", ("Metallica", "Metallica: One", "declared")),
        ("tbFZO1V5hrE", ("Metallica", "Metallica - One (Live) [Metallica Through the Never]", "declared")),
    ],
)
def test_an_official_music_video_is_credited_to_the_artist_youtube_music_names(video: str, expected: tuple[str, str, str]) -> None:
    assert reading_of(video) == expected


def test_an_official_video_with_two_credited_artists_keeps_both() -> None:
    track = read_one(playlist_entry("4IZMGxXi80s"))
    assert (track.artists, track.artist_basis) == (("We Came As Romans", "Zero 9:36"), "declared")


def test_an_official_video_whose_title_names_a_different_performer_before_a_separator_reads_the_band_from_the_title() -> None:
    """The recorded label credit (Pure Noise Records) with a title that has the dash the recorded one lacks: the TITLE is constructed here, since the one
    recorded OMV credited to a label has no separator in its title."""
    track = read_one(playlist_entry("ZXGKsaK8hH0", title="Vomit Forth - Prophecy Of Defilement (Official Music Video)"))
    assert (track.artist, track.title, track.artist_basis) == ("Vomit Forth", "Prophecy Of Defilement", "title")


@pytest.mark.parametrize("title", ["Scum - Official Video", "Scum - Live in Moscow", "Scum - Official Audio"])
def test_an_official_video_is_not_read_when_the_other_side_of_the_dash_only_describes_the_upload_or_the_version(title: str) -> None:
    """Constructed titles on the recorded OMV credited to napalm death: "Song - Official Video" and "Song - Live ..." have a SONG before the dash, not a
    performer. The credit must survive."""
    track = read_one(playlist_entry("eel5yD9TKms", title=title))
    assert (track.artists, track.artist_basis) == (("napalm death",), "declared")


# --------------------------------------------------------------------------- what YouTube cannot tell us, pinned so that a later change is deliberate


def test_KNOWN_LEFTOVER_an_official_video_credited_to_a_label_with_no_separator_keeps_the_label() -> None:
    """The recorded `Vomit Forth "Prophecy Of Defilement" (Official Music Video)` is typed OMV and credited to the label Pure Noise Records. Nothing in the
    title or the credit says the band: unknowable from YouTube alone. Its fix is N-28 (the catalogue names the artist of a song by its title)."""
    assert reading_of("ZXGKsaK8hH0") == ("Pure Noise Records", 'Vomit Forth "Prophecy Of Defilement"', "declared")


def test_KNOWN_LEFTOVER_an_official_video_with_no_credited_artist_has_no_artist() -> None:
    """The recorded OMV `Akudama` has an EMPTY `artists` and a title with no separator. The reader says so: no artist, basis `unknown`; the import fills
    the placeholder (test_imports.py)."""
    track = read_one(playlist_entry("3ENMe1rlA0M"))
    assert (track.artist, track.artists, track.title, track.artist_basis) == ("", (), "Akudama", "unknown")


def test_KNOWN_LEFTOVER_an_upload_whose_title_names_nobody_is_filed_under_its_uploader_and_flagged() -> None:
    """Unknowable (U1): `Metallica One Music Video with Lyrics HQ` by the account "David C" looks the same whether the account is the band's or a fan's.
    The uploader stays the visible artist, as YouTube Music shows it, flagged `channel` so that slices 2 and 3 can keep it out of pictures and pages."""
    assert reading_of("c5qbpWOgGzw") == ("David C", "Metallica One Music Video with Lyrics HQ", "channel")


def test_KNOWN_LEFTOVER_a_title_that_names_the_song_first_is_read_artist_first_when_the_channel_does_not_say() -> None:
    """Unknowable (U2): `Lionel Messi ★ Monaco - Bad Bunny` by "JF10HD" is `Song - Artist`, and nothing but the catalogue knows it."""
    assert reading_of("C2mTh6DPM_s") == ("Lionel Messi ★ Monaco", "Bad Bunny", "title")


def test_KNOWN_LEFTOVER_the_audit_titles_that_need_the_shapes_of_slice_4_stay_under_their_channel() -> None:
    """ARTE Concert (an en dash, then the broadcaster's own name) and Crunchyroll (a pipe and a "by" form) need the context shapes of slice 4. Until then
    both are flagged `channel`: they are never taken for a performer by the picture and page guards."""
    assert reading_of("_IIdj4ZXvko") == ("ARTE Concert", "Sepultura, live at Hellfest Open Air 2026", "channel")
    assert reading_of("a4na2opArGY") == ("Crunchyroll", "DAN DA DAN Opening | Otonoke by Creepy Nuts", "channel")


# --------------------------------------------------------------------------- the trust rule: what YouTube Music declares, and what it does not


def test_an_unknown_kind_of_video_is_an_upload_and_never_promotes_its_uploader_to_a_performer() -> None:
    entry = playlist_entry("kGJwMhVICg0", videoType="MUSIC_VIDEO_TYPE_SOMETHING_NEW")
    assert reading_of_entry(entry) == ("Tinariwen", "Full Performance (Live on KEXP)", "title")
    no_dash = playlist_entry("c5qbpWOgGzw", videoType="MUSIC_VIDEO_TYPE_SOMETHING_NEW")
    assert reading_of_entry(no_dash) == ("David C", "Metallica One Music Video with Lyrics HQ", "channel")


def test_an_available_entry_with_no_video_type_and_no_album_is_an_upload() -> None:
    entry = playlist_entry("kGJwMhVICg0", videoType=None)
    assert reading_of_entry(entry) == ("Tinariwen", "Full Performance (Live on KEXP)", "title")


def test_a_removed_entry_of_the_catalogue_keeps_its_declared_artist() -> None:
    """The recorded playlist's two removed entries have no `videoType`, are not available, and have an album."""
    removed = json.loads((FIXTURES / "playlist_community.json").read_text(encoding="utf-8"))["tracks"]
    gone = next(t for t in removed if t["title"] == "We Fly High")
    track = read_one(gone)
    assert (track.artist, track.artist_basis, track.video_id) == ("Jim Jones", "declared", None)


def test_an_entry_with_no_video_type_but_an_album_is_still_declared() -> None:
    entry = playlist_entry("phSYyQ1xGKw", videoType=None)
    assert reading_of_entry(entry) == ("Tinariwen", "Bismillah", "declared")


# --------------------------------------------------------------------------- nothing that is right today changes


def test_every_entry_of_the_recorded_playlists_gives_the_artists_it_gave_before() -> None:
    """The invariance test of slice 1: 146 `ATV`, 1 `OMV`, 2 removed entries (recorded 2026-10-22) and the 10 songs of an album. Every one is declared and
    keeps the artists the entry lists (with the "- Topic" and "VEVO" endings stripped, as before)."""
    for name in ("playlist_community.json", "playlist_album.json"):
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        playlist = read_playlist(LINK, ytmusic=lambda ident, data=data: data)
        listed = [t for t in data["tracks"] if t.get("title")]
        assert len(playlist.tracks) == len(listed) == len(data["tracks"]), name
        for entry, track in zip(listed, playlist.tracks, strict=True):
            wanted = tuple(a["name"].removesuffix(" - Topic") for a in entry["artists"])
            assert track.artists == wanted, (name, entry["title"])
            assert track.artist_basis == "declared", (name, entry["title"])


def test_with_the_video_type_removed_every_entry_that_has_an_album_is_still_declared() -> None:
    data = json.loads((FIXTURES / "playlist_community.json").read_text(encoding="utf-8"))
    for entry in data["tracks"]:
        entry["videoType"] = None
    playlist = read_playlist(LINK, ytmusic=lambda ident: data)
    for entry, track in zip(data["tracks"], playlist.tracks, strict=True):
        if entry.get("album"):
            assert track.artist_basis == "declared", entry["title"]


# --------------------------------------------------------------------------- the fallback reader (yt-dlp's flat listing) says the same


@pytest.mark.parametrize(
    ("title", "channel", "expected"),
    [
        ("Tinariwen - Full Performance (Live on KEXP)", "KEXP", ("Tinariwen", "Full Performance (Live on KEXP)", "title")),
        ("Tinariwen · Full Performance · Live on KEXP", "Товарищ Lxss", ("Tinariwen", "Full Performance · Live on KEXP", "title")),
        ("Bad Bunny – MONACO", "Rhytma Afro House", ("Bad Bunny", "MONACO", "title")),
        ("Sepultura, live at Hellfest Open Air 2026 – ARTE Concert", "ARTE Concert", ("ARTE Concert", "Sepultura, live at Hellfest Open Air 2026", "channel")),
        ("DAN DA DAN Opening | Otonoke by Creepy Nuts", "Crunchyroll", ("Crunchyroll", "DAN DA DAN Opening | Otonoke by Creepy Nuts", "channel")),
        ("The Leper Affinity", "Opeth - Topic", ("Opeth", "The Leper Affinity", "declared")),
    ],
)
def test_the_flat_yt_dlp_listing_is_read_by_the_same_rule(title: str, channel: str, expected: tuple[str, str, str]) -> None:
    listing = {"title": "Flat", "entries": [{"id": "abcdefghijk", "title": title, "channel": channel}]}
    track = read_playlist(LINK, ytdlp=lambda url: listing).tracks[0]
    assert (track.artist, track.title, track.artist_basis) == expected
