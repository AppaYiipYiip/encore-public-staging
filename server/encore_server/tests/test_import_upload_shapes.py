"""N-26 slice 4: the series label shape of the upload reader (docs/tasks/P2-songs-as-references.md, "N-26", slice 4).

`<Series> Opening | <Song> by <Artist>` (a PIPE after a label that ends in Opening or Ending, and exactly one "by") names the artist after "by": "DAN DA DAN
Opening | Otonoke by Creepy Nuts" is "Otonoke" by Creepy Nuts, not a song of the channel Crunchyroll. The rule is deliberately NARROW (its first, wider form,
any "by", "op", "ed" or "ost", broke good titles, and a DASH after the label filed "Happy Ending - Born by the River" under "the River": see
`test_import_upload_corpus.py`, whose rows no rule may change). Each case here is a title, who uploaded it and what must come out; the near misses are as
important as the hits.

No I/O, no network.
"""

from __future__ import annotations

import pytest

from encore_server.imports.readers import read_playlist
from encore_server.imports.uploads import read_upload

LINK = "https://music.youtube.com/playlist?list=OLAK5uy_m59x-hBFsC789l1_qWwFXwH3gjntwy_CA"


def upload(title: str, uploader: str) -> tuple[str, str, str]:
    reading = read_upload(title, uploader)
    return reading.artist, reading.title, reading.basis


# --------------------------------------------------------------------------- the shape


@pytest.mark.parametrize(
    ("title", "uploader", "expected"),
    [
        # the audit's third string (B-125), recorded: filed under Crunchyroll before
        ("DAN DA DAN Opening | Otonoke by Creepy Nuts", "Crunchyroll", ("Creepy Nuts", "Otonoke", "title")),
        # the same shape with Ending, recorded
        ("DAN DA DAN Ending | TAIDADA by ZUTOMAYO", "Crunchyroll", ("ZUTOMAYO", "TAIDADA", "title")),
        # a number after the word; the series may be any text
        ("Naruto Shippuden Ending 5 | Sign by FLOW", "Funimation", ("FLOW", "Sign", "title")),
        (
            "Spy x Family Opening 2 | Mixed Nuts by Official HIGE DANdism",
            "Crunchyroll",
            ("Official HIGE DANdism", "Mixed Nuts", "title"),
        ),
        # the label may be the word alone, in any case, and no space is needed around the pipe
        ("Opening | Song by Artist", "Some Channel", ("Artist", "Song", "title")),
        ("ENDING|Song by Artist", "Some Channel", ("Artist", "Song", "title")),
        # a song bracket stays (it says which recording this is); a noise bracket and a feat. tail go, as everywhere
        ("Series Opening | Otonoke (TV Size) by Creepy Nuts", "Crunchyroll", ("Creepy Nuts", "Otonoke (TV Size)", "title")),
        ("Series Opening | Otonoke by Creepy Nuts (Lyrics)", "Crunchyroll", ("Creepy Nuts", "Otonoke", "title")),
        ("Series Opening | Otonoke by Creepy Nuts ft. Somebody", "Crunchyroll", ("Creepy Nuts", "Otonoke", "title")),
        # any alphabet in the artist and the song
        ("ダンダダン Opening | オトノケ by Creepy Nuts", "Crunchyroll", ("Creepy Nuts", "オトノケ", "title")),
        ("Series Ending | Song by Кино", "Anime Channel", ("Кино", "Song", "title")),
    ],
)
def test_a_series_label_a_pipe_and_a_credit_name_the_artist(title: str, uploader: str, expected: tuple[str, str, str]) -> None:
    assert upload(title, uploader) == expected


def test_the_uploader_is_still_kept_as_a_fact() -> None:
    reading = read_upload("DAN DA DAN Opening | Otonoke by Creepy Nuts", "Crunchyroll")
    assert (reading.artists, reading.uploader) == (("Creepy Nuts",), "Crunchyroll")
    assert read_upload("DAN DA DAN Opening | Otonoke by Creepy Nuts", "").uploader is None


# --------------------------------------------------------------------------- near misses: the shape needs ALL of its parts


@pytest.mark.parametrize(
    ("title", "uploader", "expected"),
    [
        # no credit after the label: nobody is named, the uploader stays (flagged), as before
        (
            "DANDADAN Opening | Roblox Animation Collab",
            "OoferGuide",
            ("OoferGuide", "DANDADAN Opening | Roblox Animation Collab", "channel"),
        ),
        # a "by" with no label that ends in Opening or Ending: a bare "by" is not a shape ("Stand By Me", "Walk On By")
        ("Lullaby by Shawn Mendes (Lyrics)", "Lyrics Daily", ("Lyrics Daily", "Lullaby by Shawn Mendes", "channel")),
        ("Opening Ceremony - Heroes by David Bowie", "London 2012", ("Opening Ceremony", "Heroes by David Bowie", "title")),
        ("Ed Sheeran - Stand By Me", "SomeUser", ("Ed Sheeran", "Stand By Me", "title")),
        # the label word is not the LAST word of the label
        (
            "Alicia Keys - Opening Night (Live at the Apollo)",
            "Alicia Keys",
            ("Alicia Keys", "Opening Night (Live at the Apollo)", "title"),
        ),
        # the abbreviations OP and ED are not read: they are what broke "Chopin - Nocturne Op. 9" and "Ed Sheeran"
        (
            "Naruto OP 3 | Haruka Kanata by Asian Kung-Fu Generation",
            "Anime Fan",
            ("Anime Fan", "Naruto OP 3 | Haruka Kanata by Asian Kung-Fu Generation", "channel"),
        ),
        ("Big Ed | Song by Someone", "Some Channel", ("Some Channel", "Big Ed | Song by Someone", "channel")),
        # the label word sits inside another word
        ("Happy Pending | Song by Someone", "Some Channel", ("Some Channel", "Happy Pending | Song by Someone", "channel")),
        # a DASH after the label is not read (the lead's ruling): a band or a show whose name ends in Opening or Ending is an artist before a dash
        (
            "Attack on Titan Opening 1 - Guren no Yumiya by Linked Horizon",
            "Anime Fan",
            ("Attack on Titan Opening 1", "Guren no Yumiya by Linked Horizon", "title"),
        ),
        ("Happy Ending - Born by the River", "Some Uploader", ("Happy Ending", "Born by the River", "title")),
        ("Grand Opening - Nothing by Chance", "Some Uploader", ("Grand Opening", "Nothing by Chance", "title")),
        ("Hollow Ending - Standing By You", "Hollow Ending Official", ("Hollow Ending", "Standing By You", "title")),
        ("Gilmore Girls Opening - Stand By Me", "Some Uploader", ("Gilmore Girls Opening", "Stand By Me", "title")),
        ("Кино Ending - Born by the River", "Кино", ("Кино Ending", "Born by the River", "title")),
        # a label that IS the uploader's own name is a performer, not a series (a pipe, on the band's own channel)
        ("Happy Ending | Born by the River", "Happy Ending", ("Happy Ending", "Happy Ending | Born by the River", "channel")),
        (
            "Grand Opening | Nothing by Chance",
            "Grand Opening Official",
            ("Grand Opening Official", "Grand Opening | Nothing by Chance", "channel"),
        ),
        # a title with an ordinary artist-dash-song form keeps it, even with Opening in the song
        ("Mozart - Opening | Overture by Karajan", "Some Channel", ("Mozart", "Opening | Overture by Karajan", "title")),
    ],
)
def test_a_title_that_lacks_a_part_of_the_shape_is_read_as_it_was(
    title: str, uploader: str, expected: tuple[str, str, str]
) -> None:
    assert upload(title, uploader) == expected


@pytest.mark.parametrize(
    "title",
    [
        # the credit is not a clean name: a bracket or a pipe or a quote is left in it, so nobody is named (fail closed)
        "DAN DA DAN Opening | Otonoke by Creepy Nuts (TV Size)",
        "DAN DA DAN Opening | Otonoke by Creepy Nuts | Netflix Anime",
        'DAN DA DAN Opening | Otonoke by "Creepy Nuts"',
        "DAN DA DAN Opening | Otonoke by 「Creepy Nuts」",
        # nothing before the credit, or nothing after it
        "DAN DA DAN Opening | by Creepy Nuts",
        "DAN DA DAN Opening | Otonoke by ",
    ],
)
def test_a_credit_that_is_not_a_clean_name_names_nobody(title: str) -> None:
    """The shape names a performer only when it can say exactly who: a half-clean name would file a song under a wrong, TRUSTED artist (basis `title`),
    which is worse than the uploader flagged `channel`."""
    reading = read_upload(title, "Crunchyroll")
    assert (reading.artist, reading.basis) == ("Crunchyroll", "channel")


@pytest.mark.parametrize(
    "title",
    [
        "Series Opening | Song by Death by Stereo",
        "Anime Opening | Stand By Me by Ben E. King",
        "Series Ending | Born by the River by Someone",
    ],
)
def test_a_credit_with_more_than_one_by_is_ambiguous_so_nobody_is_named(title: str) -> None:
    """The lead's ruling. "Stand By Me by Ben E. King" needs the LAST " by " and "Song by Death by Stereo" needs the first, and the string cannot say which: the
    shape fails closed and the title reads as before (the uploader, flagged `channel`), exactly as for a bracket, a pipe or a quote left in the credit. The fix
    of both is the catalogue naming the artist by the title (N-28)."""
    reading = read_upload(title, "Crunchyroll")
    assert (reading.artist, reading.basis) == ("Crunchyroll", "channel")


def test_KNOWN_LEFTOVER_a_band_named_like_a_series_label_on_somebody_elses_channel_is_read_as_a_series() -> None:
    """`Happy Ending | Born by the River` on the band's own channel reads as before (the own-name guard). The same title on another channel cannot be told from a
    series: it is read as one. Unknowable from the string; N-28."""
    assert upload("Happy Ending | Born by the River", "Some Uploader") == ("the River", "Born", "title")


def test_a_topic_channel_still_wins_over_the_shape() -> None:
    reading = read_upload("Series Opening | Song by Artist", "Somebody - Topic")
    assert (reading.artist, reading.basis) == ("Somebody", "declared")


# --------------------------------------------------------------------------- the readers use it (YouTube Music's answer and yt-dlp's flat listing)


def test_the_flat_yt_dlp_listing_reads_the_audits_series_title() -> None:
    listing = {
        "title": "Flat",
        "entries": [{"id": "a4na2opArGY", "title": "DAN DA DAN Opening | Otonoke by Creepy Nuts", "channel": "Crunchyroll"}],
    }
    track = read_playlist(LINK, ytdlp=lambda url: listing).tracks[0]
    assert (track.artist, track.title, track.artist_basis, track.uploader) == ("Creepy Nuts", "Otonoke", "title", "Crunchyroll")
