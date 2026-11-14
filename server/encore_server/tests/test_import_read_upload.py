"""N-26: reading an upload's title (docs/tasks/P2-songs-as-references.md, "N-26", section 2). Pure logic, no I/O.

The titles marked "recorded" are real (tests/fixtures/ytm/n26, tests/test_import_upload_reading.py); the others are the shapes the rule must tell
apart, written as plain examples. The rule: the channel is the uploader, and the uploader is evidence, not the artist.
"""

from __future__ import annotations

import pytest

from encore_server.imports.readers import split_artist_title
from encore_server.imports.uploads import UNKNOWN_ARTIST, read_declared, read_official_video, read_upload
from encore_server.textnorm import ascii_fold


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
        ("Becky G - POR EL CONTRARIO (Performance Video) ft. Angela Aguilar", "Becky G", ("Becky G", "POR EL CONTRARIO", "title")),
        ("Arcangel - FN8 ( Video Lyric )", "Arcangel", ("Arcangel", "FN8", "title")),
        ("Opeth - Windowpane", "Some Uploader", ("Opeth", "Windowpane", "title")),
        # the left side lists the channel among several names: still `Artist - Song`, the whole left side stays the artist
        ("Artist A & Artist B - Song", "Artist A", ("Artist A & Artist B", "Song", "title")),
    ],
)
def test_the_channel_breaks_the_tie_only_when_it_is_a_whole_name(title: str, uploader: str, expected: tuple[str, str, str]) -> None:
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


@pytest.mark.parametrize("title", ["Jay-Z", "Jay–Z", "col·legi", "Song (feat. A - B)", "Song [Artist – Remix]"])
def test_a_separator_needs_spaces_around_it_and_a_bracket_protects_what_is_inside(title: str) -> None:
    assert upload(title, "Uploader") == ("Uploader", title, "channel")


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
def test_with_no_separator_the_uploader_is_the_artist_and_is_flagged(title: str, uploader: str, expected: tuple[str, str, str]) -> None:
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
    assert (reading.artists, reading.title, reading.basis) == (("Pure Noise Records",), 'Vomit Forth "Prophecy Of Defilement"', "declared")


def test_the_unknown_artist_is_the_name_the_keeper_already_files_under() -> None:
    assert UNKNOWN_ARTIST == "Unknown Artist"
