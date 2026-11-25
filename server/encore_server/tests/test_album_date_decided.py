"""N-34, the first live pass on a real server (25 Nov 2026): RULE 1, `date_decided`. The album pass stamped five doubtful PERMANENT albums on VM 108 (all undone): blink-182 `All The Small
Things` on the EP `I Won't Be Home For Christmas`, Limp Bizkit `Break Stuff` on the compilation `Greatest Hitz`, My Chemical Romance `Welcome to the Black Parade` on the compilation `May
Death Never Stop You`, Cassidy `Hotel` on an EP dated 1990-01-01 and Ja Rule `Always On Time` on the EP `Wonderful`.

**The cause, with proof** (the second live dry run, `tests/fixtures/deezer/n34_dryrun_25nov.json`): the catalogue's DATES of old releases are not the dates they came out. They are the dates of a
reissue (blink-182's `Enema Of The State` is dated 2018 and 2019, Limp Bizkit's `Significant Other` 2008) or a placeholder (`1990-01-01`, `2004-01-01`), so "the earliest release wins" picks an EP
or a compilation over the real album. The date cannot tell them apart, so a release that wins ONLY by its date, against a real competitor of its own tier, is a re-askable `none`:
`date_decided`. **The invariant** (stated in `album_finder.choose_release`, held by `tests/test_album_rules_property.py`): a `matched` verdict never has an eligible competitor of the same tier,
another release family and no compilation title, beaten only by the date order.

The answers are the REAL ones (`tests/album_world.py` says where they are and what their lengths are); the made catalogue states what each release IS and nothing else.
"""

from __future__ import annotations

import pytest

from encore_server import album_finder
from encore_server.album_finder import release_family
from tests.album_world import Rel, outcome, recorded_inputs, recorded_song, verdict_of

# ------------------------------------------------------------------------------------------------------------------ the five songs a real pass stamped, and the songs that stay


@pytest.mark.parametrize(
    ("artist", "title", "reason", "was_stamped_with"),
    [
        ("blink-182", "All The Small Things", "date_decided", "I Won't Be Home For Christmas"),
        ("Limp Bizkit", "Break Stuff", "date_decided", "Greatest Hitz"),
        ("Cassidy", "Hotel", "date_decided", "Hotel"),
        ("Ja Rule", "Always On Time", "date_decided", "Wonderful"),
        ("My Chemical Romance", "Welcome to the Black Parade", "sole_album", "May Death Never Stop You"),
    ],
)
def test_the_five_songs_a_real_pass_stamped_wrongly_are_re_askable_nones_with_the_reason(
    artist: str, title: str, reason: str, was_stamped_with: str
) -> None:
    verdict = recorded_song(artist, title)
    assert outcome(verdict) == ("none", reason)
    assert verdict.remember is True and verdict.match is None, "a re-askable fact about the catalogue, written by nobody"
    assert verdict.withheld is not None and verdict.withheld.album == was_stamped_with, (
        "the report still shows what the old rule would have stamped"
    )


@pytest.mark.parametrize(
    ("artist", "title", "album", "record_type"),
    [
        (
            "The Game",
            "Hate It Or Love It",
            "The Documentary",
            "album",
        ),  # its lead singles are other releases of the song: the album is no sole release
        ("System Of A Down", "Chop Suey!", "Toxicity", "album"),
        ("Pause", "Lyam", "Metamorphose", "ep"),  # a sole EP stays accepted (the artist's own EPs; a compilation EP is rare)
    ],
)
def test_the_songs_the_rules_must_not_delay_stay_matched_on_the_real_answers(
    artist: str, title: str, album: str, record_type: str
) -> None:
    verdict = recorded_song(artist, title)
    assert outcome(verdict) == ("matched", "matched")
    assert verdict.match is not None and (verdict.match.album, verdict.match.record_type) == (album, record_type)


def test_a_correct_stamp_is_delayed_when_a_compilation_with_no_telling_title_is_a_competitor_and_that_is_the_price() -> None:
    """THE PRICE, said by a test (the stop-gap `STOP-GAP(N-34 date decided)`): `Stankonia` is the right album of `So Fresh, So Clean`, and `Big Boi & Dre Present...OutKast` (2001, an album
    by the artist, no compilation word in its title) is a later release the matcher cannot tell from an album. The song waits; the artist's discography (N-48) is what ends the wait. When it
    lands this test is replaced by one that expects the stamp."""
    song, hits, answers = recorded_inputs("Outkast", "So Fresh, So Clean")
    verdict = album_finder.choose_release(song, hits, answers)
    assert outcome(verdict) == ("none", "date_decided")
    assert verdict.withheld is not None and verdict.withheld.album == "Stankonia"
    # The same answers without that one competitor: `Stankonia`, `Stankonia (Deluxe Version)` and `Stankonia (25th Anniversary ...)` are ONE release family, so no rival is left and the album is
    # the sole one (rule 2). Were the editions two families, this would be `date_decided` again: that is what the fold is for.
    others = [h for h in hits if not str(h["album"]["title"]).startswith("Big Boi")]
    assert len(others) == len(hits) - 1
    after = album_finder.choose_release(
        song, others, {k: v for k, v in answers.items() if not str(v["album"]["title"]).startswith("Big Boi")}
    )
    assert outcome(after) == ("none", "sole_album")
    assert (
        len({release_family(a["album"]["title"]) for a in answers.values() if not str(a["album"]["title"]).startswith("Big Boi")})
        == 1
    )


# ------------------------------------------------------------------------------------------------------------------ the families: editions of one release are one release

SAME_RELEASE = [
    ("Hybrid Theory", "Hybrid Theory (Bonus Edition)"),
    ("Hybrid Theory", "Hybrid Theory (20th Anniversary Edition)"),
    ("Meteora", "Meteora 20th Anniversary Edition"),
    ("The Better Life", "The Better Life (20th Anniversary / Deluxe)"),
    ("Three Ringz (Thr33 Ringz)", "Three Ringz (Thr33 Ringz) [Edited Version]"),
    ("When The World Comes Down", "When The World Comes Down (International Version)"),
    ("Stankonia", "Stankonia (Deluxe Version)"),
    ("Stankonia", "Stankonia (25th Anniversary Deluxe Edition)"),
    ("No Need To Argue", "No Need To Argue (2025 Remastered)"),
    ("Most Known Unknown (Explicit)", "Most Known Unknown (Clean)"),
    ("Disclaimer", "Disclaimer (Deluxe Edition)"),
    ("Sempiternal", "Sempiternal (Expanded Edition)"),
    ("Let Go", "Let Go [Legacy Edition]"),
    ("O My Heart", "O My Heart (Extended Edition)"),
    ("The Black Parade", "The Black Parade (20th Anniversary Edition)"),
    ("Toxicity", "Toxicity (2001)"),
    ("Toxicity", "Toxicity (Super Deluxe Edition)"),
]

DIFFERENT_RELEASE = [
    ("Relapse", "Relapse: Refill"),
    ("Waking The Fallen", "Waking The Fallen: Resurrected"),
    ("Pain Is Love", "The Rules of Love: Pain is Love"),
    ("The Black Parade", "The Black Parade / Living with Ghosts (The 10th Anniversary Edition)"),
    ("In Rainbows", "In Rainbows (Live)"),  # a version mark never folds: another recording
    ("Songs", "Songs (Acoustic)"),
    ("1989", "1989 (Taylor's Version)"),
    ("Hybrid Theory", "Hybrid Theory (Remixed)"),
    ("Clean", "Squeaky Clean"),  # a bare label word that is the title's own
    ("Disclaimer", "Disclaimer II"),
    ("Ladies & Gentlemen", "Careless Whisper EP"),
]


@pytest.mark.parametrize(("plain", "edition"), SAME_RELEASE)
def test_an_edition_label_is_the_same_release_as_the_plain_title(plain: str, edition: str) -> None:
    assert release_family(edition) == release_family(plain) != ""


@pytest.mark.parametrize(("one", "other"), DIFFERENT_RELEASE)
def test_a_title_that_says_more_than_an_edition_is_another_release(one: str, other: str) -> None:
    assert release_family(one) != release_family(other)


@pytest.mark.parametrize("title", ["Edition", "Legacy Edition", "(2001)"])
def test_a_title_that_is_only_labels_keeps_its_own_family_and_never_folds_to_nothing(title: str) -> None:
    assert release_family(title) != ""


def test_a_title_with_no_edition_label_has_the_catalogues_own_release_key_as_its_family() -> None:
    """The family only ADDS labels to `catalogue.release_key` (the one definition the twin rule, the fill rule and the cover finder share); it never changes a title without one."""
    from encore_server.catalogue import release_key

    for title in (
        "Weezer (Green Album)",
        "The Wall",
        "Rock & Roll",
        "حبيبي",
        "Relapse: Refill",
        "No Need To Argue (Remastered 2011)",
    ):
        assert release_family(title) == release_key(title), title


# ------------------------------------------------------------------------------------------------------------------ the rule, on made releases

#: A single of the song that came out AFTER every album below: no "earlier single", and a second release family that corroborates the album (the sole-album rule sees two).
LATER_SINGLE = Rel("9", "Harbour Lights", "single", "2030-01-01")
ALBUM = Rel("1", "Harbour", "album", "2000-05-05")


def test_a_second_album_of_another_release_family_that_lost_only_on_the_date_is_date_decided() -> None:
    verdict = verdict_of(ALBUM, Rel("2", "Moorings", "album", "2003-03-03"), LATER_SINGLE)
    assert outcome(verdict) == ("none", "date_decided")
    assert verdict.withheld is not None and verdict.withheld.album == "Harbour"
    assert [(r.album_id, r.reason) for r in verdict.releases][:2] == [("1", "chosen"), ("2", "outranked")]


def test_an_ep_is_a_competitor_of_an_album_and_an_album_of_an_ep_they_are_one_tier() -> None:
    assert outcome(verdict_of(ALBUM, Rel("2", "Moorings", "ep", "2003-03-03"), LATER_SINGLE)) == ("none", "date_decided")
    assert outcome(verdict_of(Rel("1", "Harbour", "ep"), Rel("2", "Moorings", "album", "2003-03-03"), LATER_SINGLE)) == (
        "none",
        "date_decided",
    )


def test_editions_of_the_chosen_release_are_no_competitor() -> None:
    verdict = verdict_of(
        ALBUM,
        Rel("2", "Harbour (Deluxe Edition)", "album", "2005-05-05"),
        Rel("3", "Harbour (20th Anniversary Edition)", "album", "2020-05-05"),
        LATER_SINGLE,
    )
    assert outcome(verdict) == ("matched", "matched") and verdict.match is not None and verdict.match.album == "Harbour"


@pytest.mark.parametrize(
    "title",
    [
        *album_finder.COMPILATION_MARKERS,
        "Greatest",
        "Best Of",
        "Hits",
        "Collection",
        "Essential",
        "Anthology",
        "Gold",
        "Ultimate",
        "Singles",
        "Vol. 1",
    ],
)
def test_a_competitor_whose_title_says_it_is_a_compilation_is_no_competitor(title: str) -> None:
    verdict = verdict_of(ALBUM, Rel("2", f"Harbour {title}", "album", "2013-03-03"), LATER_SINGLE)
    assert outcome(verdict) == ("matched", "matched"), title


def test_the_compilation_words_of_the_competitor_filter_are_a_separate_list_and_the_markers_stay_what_they_were() -> None:
    """A best-of called Gold is still accepted as the CHOSEN release (the advisor's ruling of 17 Nov); the plain words only exempt a COMPETITOR."""
    assert "gold" not in album_finder.COMPILATION_MARKERS and "singles" not in album_finder.COMPILATION_MARKERS
    assert {"greatest", "best of", "hits", "collection", "essential", "anthology", "gold", "ultimate", "singles", "vol"} <= set(
        album_finder.PLAIN_COMPILATION_WORDS
    )
    chosen_gold = verdict_of(Rel("1", "Gold", "album", "2000-05-05"), LATER_SINGLE)
    assert outcome(chosen_gold) == ("matched", "matched")


def test_a_competitor_dated_the_same_day_or_not_at_all_is_a_competitor_because_nothing_but_an_id_decided() -> None:
    assert outcome(verdict_of(ALBUM, Rel("2", "Moorings", "album", "2000-05-05"), LATER_SINGLE)) == ("none", "date_decided")
    assert outcome(verdict_of(ALBUM, Rel("2", "Moorings", "album", None), LATER_SINGLE)) == ("none", "date_decided")
    assert outcome(verdict_of(ALBUM, Rel("2", "Moorings", "album", "0000-00-00"), LATER_SINGLE)) == ("none", "date_decided")


def test_the_order_of_the_hits_changes_nothing() -> None:
    verdict = verdict_of(Rel("3", "Moorings", "album", "2003-03-03"), ALBUM, LATER_SINGLE)
    assert outcome(verdict) == ("none", "date_decided") and verdict.withheld is not None and verdict.withheld.album == "Harbour"


@pytest.mark.parametrize(
    "other",
    [
        Rel("2", "Moorings", "single", "2003-03-03"),  # a single is another tier
        Rel("2", "Moorings", "album", "2003-03-03", artist="Various Artists"),  # not the song's artist: refused before the dates
        Rel("2", "Harbour Lights (Live)", "album", "2003-03-03"),  # a live record of the song is another recording
        Rel("2", "Moorings", "compile", "2003-03-03"),  # a type that never wins
        Rel("2", "Unknown Album", "album", "2003-03-03"),  # the music server's word for no album
    ],
)
def test_a_release_that_could_never_be_chosen_is_no_competitor(other: Rel) -> None:
    verdict = verdict_of(ALBUM, other, LATER_SINGLE)
    assert outcome(verdict) == ("matched", "matched"), other


def test_the_reason_is_asked_again_it_is_a_remembered_none_never_matched() -> None:
    verdict = verdict_of(ALBUM, Rel("2", "Moorings", "album", "2003-03-03"), LATER_SINGLE)
    assert verdict.outcome == "none" and verdict.remember and verdict.match is None and verdict.withheld is not None


# ------------------------------------------------------------------------------------------------------------------ a year-only date is never "earlier" than another date of its year


def test_a_year_only_placeholder_date_does_not_beat_a_real_date_of_the_same_year() -> None:
    """The edition dated 2002-01-01 (the catalogue's placeholder for "some day of 2002") is no earlier than the one dated 2002-06-25: the real date is chosen."""
    verdict = verdict_of(
        Rel("1", "Harbour", "album", "2002-01-01"), Rel("2", "Harbour (Deluxe Edition)", "album", "2002-06-25"), LATER_SINGLE
    )
    assert outcome(verdict) == ("matched", "matched") and verdict.match is not None and verdict.match.album_id == "2"


def test_a_year_only_date_is_still_earlier_than_any_date_of_a_later_year_and_a_placeholder_loses_to_nothing_else() -> None:
    verdict = verdict_of(
        Rel("1", "Harbour", "album", "2001-01-01"), Rel("2", "Harbour (Deluxe Edition)", "album", "2002-06-25"), LATER_SINGLE
    )
    assert verdict.match is not None and verdict.match.album_id == "1"
    two = verdict_of(
        Rel("5", "Harbour", "album", "2002-01-01"), Rel("4", "Harbour (Deluxe Edition)", "album", "2002-01-01"), LATER_SINGLE
    )
    assert two.match is not None and two.match.album_id == "5", (
        "two placeholders of one year: the plain title, then the lowest id"
    )


def test_a_release_with_no_date_is_still_last() -> None:
    verdict = verdict_of(
        Rel("1", "Harbour", "album", None), Rel("2", "Harbour (Deluxe Edition)", "album", "2002-06-25"), LATER_SINGLE
    )
    assert verdict.match is not None and verdict.match.album_id == "2"


def test_the_year_only_rule_does_not_loosen_the_single_before_album_rule() -> None:
    """`_single_before` is a WITHHOLD: a loosened one would make permanent stamps. A single dated 2000-01-01 before an album of the same year stays `single_before_album`."""
    verdict = verdict_of(Rel("1", "Harbour", "album", "2000-05-05"), Rel("9", "Harbour Lights", "single", "2000-01-01"))
    assert outcome(verdict) == ("none", "single_before_album")


def test_by_the_way_is_never_stamped_under_the_name_of_its_edition() -> None:
    """The two releases are one family and dated the same day: the stamp, when there is one, is the PLAIN title (the album's name is permanent); on the recorded answers the plain release's track list was not
    recorded, so the pass would ask again (`unavailable`), which is the safe side."""
    verdict = recorded_song("Red Hot Chili Peppers", "By the Way")
    if verdict.outcome == "matched":
        assert verdict.match is not None and verdict.match.album == "By the Way"
    else:
        assert verdict.outcome == "unavailable", verdict
