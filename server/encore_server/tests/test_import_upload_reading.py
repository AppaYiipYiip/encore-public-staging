"""N-26 / audit B-125: who is the artist of an imported YouTube upload (docs/tasks/P2-songs-as-references.md, "N-26"). One file for the unit:

* **Part 1, the rule** (`imports/uploads.py`): a table of titles and channels, pure logic, no I/O. The titles marked "recorded" are real; the others are
  the shapes the rule must tell apart, written as plain examples. The rule: the channel is the uploader, and the uploader is evidence, not the artist.
* **Part 2, the readers**: the titles, channels, video types and credited artists are REAL: `tests/fixtures/ytm/n26/*.json` are YouTube Music's own search
  answers, recorded on 2026-11-14 (`videoType` and `artists` exactly as the service gave them). A playlist entry is built from one of them the way
  `get_playlist` shapes an entry (the shape of the first track of `tests/fixtures/ytm/playlist_album.json`, filled with the recorded `videoId`, `title`,
  `artists`, `videoType` and length): the VALUES are recorded, the SHAPE around them is the recorded playlist's, because no `get_playlist` answer of a
  person's upload has been recorded yet. No test asks the network.

A test named KNOWN_LEFTOVER pins a result that is wrong or incomplete today on purpose, so that the slice that fixes it changes the row on purpose.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import pytest

from encore_server.imports.readers import Track, read_playlist, split_artist_title
from encore_server.imports.uploads import UNKNOWN_ARTIST, read_declared, read_official_video, read_upload
from encore_server.textnorm import ascii_fold

# =========================================================================== part 1: the rule, pure


def upload(title: str, uploader: str) -> tuple[str, str, str]:
    reading = read_upload(title, uploader)
    return reading.artist, reading.title, reading.basis


# --------------------------------------------------------------------------- the channel is a WHOLE NAME of a side, never a substring


@pytest.mark.parametrize(
    ("title", "uploader", "expected"),
    [
        # recorded: "kexp" is inside "(Live on KEXP)", which used to make the right side "the channel" and swap the sides
        ("Tinariwen - Full Performance (Live on KEXP)", "KEXP", ("Tinariwen", "Full Performance (Live on KEXP)", "title")),
        # the same words on the band's own channel
        ("Tinariwen - Full Performance (Live on KEXP)", "Tinariwen", ("Tinariwen", "Full Performance (Live on KEXP)", "title")),
        # the channel's own decoration is not part of its name ("Official", "VEVO", "- Topic")
        ("Opeth - Windowpane", "Opeth Official", ("Opeth", "Windowpane", "title")),
        ("Opeth - Windowpane", "OpethVEVO", ("Opeth", "Windowpane", "title")),
        # the channel names one artist of a credit list on the right: `Song - Artists`
        ("BELLAKEO (Video Oficial) - Peso Pluma, Anitta", "Peso Pluma", ("Peso Pluma", "BELLAKEO", "title")),
        (
            "Becky G - POR EL CONTRARIO (Performance Video) ft. Angela Aguilar",
            "Becky G",
            ("Becky G", "POR EL CONTRARIO", "title"),
        ),
        ("Arcangel - FN8 ( Video Lyric )", "Arcangel", ("Arcangel", "FN8", "title")),
        ("Opeth - Windowpane", "Some Uploader", ("Opeth", "Windowpane", "title")),
        # the left side lists the channel among several names: still `Artist - Song`, the whole left side stays the artist
        ("Artist A & Artist B - Song", "Artist A", ("Artist A & Artist B", "Song", "title")),
    ],
)
def test_the_channel_breaks_the_tie_only_when_it_is_a_whole_name(
    title: str, uploader: str, expected: tuple[str, str, str]
) -> None:
    assert upload(title, uploader) == expected


def test_a_side_equal_to_the_uploader_alone_is_weak_because_a_broadcaster_and_a_performer_look_the_same() -> None:
    """`Song - ARTE Concert` on ARTE Concert is the broadcaster's credit; `Song - Queen` on Queen is the band. Nothing in the string tells them apart, so
    the artist reached only through the uploader's own name is flagged `channel` (the picture and page guards of slices 2 and 3 key on it). The cost, written
    in the design: a performer's own `Song - Artist` upload is weak too, until one of the artist's songs is `declared` or `title`."""
    assert upload("Song – ARTE Concert", "ARTE Concert") == ("ARTE Concert", "Song", "channel")
    assert upload("Bohemian Rhapsody - Queen", "Queen Official") == ("Queen", "Bohemian Rhapsody", "channel")
    # ... against a credit list that names somebody else too, which is a performer's credit
    assert upload("BELLAKEO - Peso Pluma, Anitta", "Peso Pluma")[2] == "title"
    # ... and the LEFT side being the channel is the strongest case
    assert upload("Queen - Bohemian Rhapsody", "Queen Official") == ("Queen", "Bohemian Rhapsody", "title")


# --------------------------------------------------------------------------- separators


@pytest.mark.parametrize(
    "separator",
    [" - ", " ‐ ", " – ", " — ", " − ", " · ", " • "],
    ids=["hyphen-minus", "hyphen", "en dash", "em dash", "minus", "middle dot", "bullet"],
)
def test_every_kind_of_dash_and_the_middle_dot_separates_an_artist_from_a_song(separator: str) -> None:
    assert upload(f"Bad Bunny{separator}MONACO", "Some Channel") == ("Bad Bunny", "MONACO", "title")


@pytest.mark.parametrize(
    ("title", "song"),
    [
        ("Jay-Z", "Jay-Z"),
        ("Jay–Z", "Jay–Z"),
        ("col·legi", "col·legi"),
        # a bracket protects the dash inside it (`clean_title` then drops the feat. group from the song, as it always did)
        ("Song (feat. A - B)", "Song"),
        ("Song [Artist – Remix]", "Song [Artist – Remix]"),
    ],
)
def test_a_separator_needs_spaces_around_it_and_a_bracket_protects_what_is_inside(title: str, song: str) -> None:
    assert upload(title, "Uploader") == ("Uploader", song, "channel")


def test_everything_after_the_first_separator_is_the_song() -> None:
    assert upload("Tinariwen · Full Performance · Live on KEXP", "Товарищ Lxss") == (
        "Tinariwen",
        "Full Performance · Live on KEXP",
        "title",
    )
    assert upload("Artist - Song - 2011 Remaster", "Whoever") == ("Artist", "Song - 2011 Remaster", "title")


def test_a_side_that_only_describes_the_upload_is_not_a_name() -> None:
    """`Shape of You - Official Video` has a song before the dash and a description after it: nobody is named. The description is dropped and the
    uploader stays the artist (flagged), instead of the song being filed as an artist called "Shape of You"."""
    assert upload("Shape of You - Official Video", "Ed Sheeran") == ("Ed Sheeran", "Shape of You", "channel")
    assert upload("Shape of You - Official Audio", "Some Fan") == ("Some Fan", "Shape of You", "channel")
    assert upload("Shape of You – Lyrics", "Some Fan") == ("Some Fan", "Shape of You", "channel")


# --------------------------------------------------------------------------- no evidence: the uploader, flagged (the one named stop-gap)


@pytest.mark.parametrize(
    ("title", "uploader", "expected"),
    [
        ("Windowpane (Official Video)", "OpethVEVO", ("Opeth", "Windowpane", "channel")),
        ("Windowpane (Official Video)", "Opeth", ("Opeth", "Windowpane", "channel")),
        ("We Live in Fear", "Some Band", ("Some Band", "We Live in Fear", "channel")),
        ("Stand By Me", "SomeUser", ("SomeUser", "Stand By Me", "channel")),
    ],
)
def test_with_no_separator_the_uploader_is_the_artist_and_is_flagged(
    title: str, uploader: str, expected: tuple[str, str, str]
) -> None:
    assert upload(title, uploader) == expected


def test_no_separator_and_no_uploader_is_no_artist_at_all() -> None:
    reading = read_upload("Akudama", "")
    assert (reading.artist, reading.artists, reading.title, reading.basis) == ("", (), "Akudama", "unknown")


def test_a_topic_channel_is_the_artist_and_the_title_is_already_clean() -> None:
    reading = read_upload("The Leper Affinity", "Opeth - Topic")
    assert (reading.artist, reading.title, reading.basis, reading.uploader) == ("Opeth", "The Leper Affinity", "declared", None)


def test_the_uploader_is_recorded_for_an_upload() -> None:
    assert read_upload("Opeth - Windowpane", "Some Uploader").uploader == "Some Uploader"


# --------------------------------------------------------------------------- titles that are right today stay so (the negative corpus of the design)


@pytest.mark.parametrize(
    ("title", "uploader", "expected"),
    [
        ("Ed Sheeran - Stand By Me", "SomeUser", ("Ed Sheeran", "Stand By Me")),
        ("Ed Sheeran - Shape of You | Official Video", "Ed Sheeran", ("Ed Sheeran", "Shape of You")),
        ("Chopin - Nocturne Op. 9 No. 2 | Piano", "Rubinstein Fan", ("Chopin", "Nocturne Op. 9 No. 2 | Piano")),
        ("The Who - Live at Leeds", "The Who", ("The Who", "Live at Leeds")),
        ("Nine Inch Nails - Closer (Live in Paris)", "Nine Inch Nails", ("Nine Inch Nails", "Closer (Live in Paris)")),
        ("Fontaines D.C. - Starburster | A COLORS SHOW", "COLORSxSTUDIOS", ("Fontaines D.C.", "Starburster | A COLORS SHOW")),
        ("Queen - Live Killers Session", "Queen Official", ("Queen", "Live Killers Session")),
    ],
)
def test_titles_that_are_read_right_today_are_read_the_same(title: str, uploader: str, expected: tuple[str, str]) -> None:
    reading = read_upload(title, uploader)
    assert (reading.artist, reading.title) == expected


def test_split_artist_title_still_answers_the_artist_and_the_song() -> None:
    """The name the older tests and callers know."""
    assert split_artist_title("Arcangel - FN8 ( Video Lyric )", "Arcangel") == ("Arcangel", "FN8")
    assert split_artist_title("Windowpane (Official Video)", "OpethVEVO") == ("Opeth", "Windowpane")


# --------------------------------------------------------------------------- other alphabets (B-37)


@pytest.mark.parametrize(
    ("title", "uploader", "expected"),
    [
        ("فيروز - كيفك إنت", "فيروز", ("فيروز", "كيفك إنت", "title")),
        # `Song - Artist` on the artist's own Arabic channel: the channel IS a whole name of the right side (flagged, as any side equal to the channel alone)
        ("كيفك إنت - فيروز", "فيروز", ("فيروز", "كيفك إنت", "channel")),
        # an Arabic channel that equals nothing: `Artist - Song`
        ("فيروز - كيفك إنت", "Some Uploader", ("فيروز", "كيفك إنت", "title")),
        ("Кино - Группа крови", "Кино", ("Кино", "Группа крови", "title")),
        ("Группа крови - Кино", "Кино", ("Кино", "Группа крови", "channel")),
    ],
)
def test_a_name_in_any_alphabet_is_compared_as_a_name(title: str, uploader: str, expected: tuple[str, str, str]) -> None:
    """The old comparison folded to a-z0-9, so every Arabic or Cyrillic name was the empty string and a non-Latin channel could never be recognised."""
    assert upload(title, uploader) == expected


def test_B37_the_servers_ascii_fold_still_turns_a_name_in_another_alphabet_into_nothing() -> None:
    """PIN (audit B-37, P2-25): `textnorm.ascii_fold` is the matcher's fold and it still keeps only a-z0-9, so an Arabic name folds to "". The reading
    of an upload does NOT rely on it (the test above compares names by their letters in any alphabet); this pin exists so that the day P2-25 replaces the
    fold, `uploads._name_key` is replaced by the same function in the same change, and this test is deleted with it."""
    assert ascii_fold("فيروز") == ""
    assert ascii_fold("Кино") == ""


# --------------------------------------------------------------------------- the other two kinds


def test_a_declared_song_strips_the_topic_and_vevo_endings_and_keeps_every_artist() -> None:
    reading = read_declared("Song (Official Audio)", ["Opeth - Topic", "SomeoneVEVO", ""])
    assert (reading.artists, reading.title, reading.basis, reading.uploader) == (("Opeth", "Someone"), "Song", "declared", None)


def test_a_declared_song_with_no_artist_has_none() -> None:
    reading = read_declared("Song", [])
    assert (reading.artist, reading.artists, reading.basis) == ("", (), "unknown")


def test_an_official_video_keeps_its_credit_when_a_side_of_the_title_names_it() -> None:
    reading = read_official_video("Metallica: One (Official Music Video)", ["Metallica"])
    assert (reading.artists, reading.title, reading.basis) == (("Metallica",), "Metallica: One", "declared")
    # the credited artist on the RIGHT: `Song - Artist`
    reading = read_official_video("BELLAKEO (Video Oficial) - Peso Pluma, Anitta", ["Peso Pluma"])
    assert (reading.artists, reading.title, reading.basis) == (("Peso Pluma",), "BELLAKEO - Peso Pluma, Anitta", "declared")


def test_an_official_video_that_names_nobody_is_not_read() -> None:
    reading = read_official_video('Vomit Forth "Prophecy Of Defilement" (Official Music Video)', ["Pure Noise Records"])
    assert (reading.artists, reading.title, reading.basis) == (
        ("Pure Noise Records",),
        'Vomit Forth "Prophecy Of Defilement"',
        "declared",
    )


def test_the_unknown_artist_is_the_name_the_keeper_already_files_under() -> None:
    assert UNKNOWN_ARTIST == "Unknown Artist"


# =========================================================================== part 2: the readers, on recorded answers


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
def test_an_upload_is_filed_under_the_performer_its_title_names_not_under_its_channel(
    video: str, expected: tuple[str, str, str]
) -> None:
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
def test_an_official_music_video_is_credited_to_the_artist_youtube_music_names(
    video: str, expected: tuple[str, str, str]
) -> None:
    assert reading_of(video) == expected


def test_an_official_video_whose_title_repeats_the_credited_name_anywhere_keeps_the_credit() -> None:
    """Recorded: `DANDADAN Opening in ITALIANO - EXTENDED "Otonoke" Creepy Nuts | ItsKlyo` is typed OMV and credited to ItsKlyo (a fan's account). It has a
    separator, and neither side of it IS the credited name, but the title mentions the credit (after a pipe): it does not name a DIFFERENT performer. Read
    literally ("neither side names the credit"), the rule would have filed it under the artist "DANDADAN Opening in ITALIANO", with the basis `title`."""
    assert reading_of("w9h54mt15y0") == (
        "ItsKlyo",
        'DANDADAN Opening in ITALIANO - EXTENDED "Otonoke" Creepy Nuts | ItsKlyo',
        "declared",
    )


def test_every_recorded_official_video_with_a_credit_keeps_it() -> None:
    """The invariance test on the real answers: the 60 recorded `MUSIC_VIDEO_TYPE_OMV` entries that have a credit (napalm death, Metallica, Pure Noise Records, SharpTone
    Records, Creepy Nuts, Bad Bunny, a fan's account ...) are all credited to who YouTube Music says, with the basis `declared`: no recorded official video is moved to
    another artist by the title. (The one OMV with no credit is `Akudama`, tested apart.)"""
    seen = 0
    for path in sorted(N26.glob("*.json")):
        for result in json.loads(path.read_text(encoding="utf-8"))["results"]:
            if result.get("videoType") != "MUSIC_VIDEO_TYPE_OMV" or not result.get("artists") or not result.get("videoId"):
                continue
            track = read_one(playlist_entry(result["videoId"]))
            assert track.artists == tuple(a["name"] for a in result["artists"]), result["title"]
            assert track.artist_basis == "declared", result["title"]
            seen += 1
    assert seen >= 60  # a guard against a fixture folder that quietly stopped being read


def test_an_official_video_with_two_credited_artists_keeps_both() -> None:
    track = read_one(playlist_entry("4IZMGxXi80s"))
    assert (track.artists, track.artist_basis) == (("We Came As Romans", "Zero 9:36"), "declared")


def test_an_official_video_whose_title_names_a_different_performer_before_a_separator_reads_the_band_from_the_title() -> None:
    """The recorded label credit (Pure Noise Records) with a title that has the dash the recorded one lacks: the TITLE is constructed here, since the one
    recorded OMV credited to a label has no separator in its title."""
    track = read_one(playlist_entry("ZXGKsaK8hH0", title="Vomit Forth - Prophecy Of Defilement (Official Music Video)"))
    assert (track.artist, track.title, track.artist_basis) == ("Vomit Forth", "Prophecy Of Defilement", "title")


@pytest.mark.parametrize("title", ["Scum - Official Video", "Scum - Live in Moscow", "Scum - Official Audio"])
def test_an_official_video_is_not_read_when_the_other_side_of_the_dash_only_describes_the_upload_or_the_version(
    title: str,
) -> None:
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
        (
            "Tinariwen · Full Performance · Live on KEXP",
            "Товарищ Lxss",
            ("Tinariwen", "Full Performance · Live on KEXP", "title"),
        ),
        ("Bad Bunny – MONACO", "Rhytma Afro House", ("Bad Bunny", "MONACO", "title")),
        (
            "Sepultura, live at Hellfest Open Air 2026 – ARTE Concert",
            "ARTE Concert",
            ("ARTE Concert", "Sepultura, live at Hellfest Open Air 2026", "channel"),
        ),
        (
            "DAN DA DAN Opening | Otonoke by Creepy Nuts",
            "Crunchyroll",
            ("Crunchyroll", "DAN DA DAN Opening | Otonoke by Creepy Nuts", "channel"),
        ),
        ("The Leper Affinity", "Opeth - Topic", ("Opeth", "The Leper Affinity", "declared")),
    ],
)
def test_the_flat_yt_dlp_listing_is_read_by_the_same_rule(title: str, channel: str, expected: tuple[str, str, str]) -> None:
    listing = {"title": "Flat", "entries": [{"id": "abcdefghijk", "title": title, "channel": channel}]}
    track = read_playlist(LINK, ytdlp=lambda url: listing).tracks[0]
    assert (track.artist, track.title, track.artist_basis) == expected
