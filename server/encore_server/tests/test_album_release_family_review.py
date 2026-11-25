"""N-34, the review of PR 130 (25 Nov 2026): the ways a stamp could still be wrong, and the contract that closes them (the advisor's rulings).

1. A family key is NEVER empty: a title of symbols or labels only ('÷', '+', 'Deluxe', '1989 Remastered') folded to nothing, so different releases became one family and a rival vanished.
2. TWO comparisons, each failing closed: the NARROW `release_family` (listed labels only; an unlisted label is a RIVAL, so `date_decided` holds the song) and the BROAD `broad_release_family`
   (also any trailing bracketed, dashed or edition group; two releases that might be one are ONE, so `sole_album` holds the song).
3. The YEAR is not part of a stamp (a reissue date or a year-only placeholder cannot be told from the real one: Contraband 1990-01-01, Weathered 2009); the date stays in `release_date`.
4. On a date tie the plain title is the release's name, not its edition (the album's name is permanent).
"""

from __future__ import annotations

import pytest

from encore_server.album_finder import broad_release_family, choose_release, release_family
from tests.album_world import Rel, world

NEVER_EMPTY = [
    "÷",
    "+",
    "=",
    "-",
    "!!!",
    "?",
    "Deluxe",
    "Explicit",
    "Remastered",
    "1989 Remastered",
    "2001 Remastered",
    "(Deluxe)",
    "Standard Edition",
    "The",
    "÷ (Deluxe)",
]


@pytest.mark.parametrize("title", NEVER_EMPTY)
def test_a_family_key_is_never_empty_narrow_or_broad(title: str) -> None:
    assert release_family(title) != ""
    assert broad_release_family(title) != ""


@pytest.mark.parametrize("family", [release_family, broad_release_family])
def test_two_different_symbol_or_label_titles_are_two_families(family) -> None:  # type: ignore[no-untyped-def]
    assert family("÷") != family("+")
    assert family("Deluxe") != family("Remastered")


@pytest.mark.parametrize("family", [release_family, broad_release_family])
def test_a_symbol_title_and_its_labelled_edition_are_one_family(family) -> None:  # type: ignore[no-untyped-def]
    assert family("÷ (Deluxe)") == family("÷")


def test_a_year_with_a_label_is_the_year_for_the_broad_comparison() -> None:
    assert (
        broad_release_family("2001 Remastered") == broad_release_family("2001 (Expanded Edition)") == broad_release_family("2001")
    )


@pytest.mark.parametrize(
    "label",
    [
        "Reissue",
        "Collector's Edition",
        "Platinum Edition",
        "Japan Edition",
        "Tour Edition",
        "Japanese Version",
        "Tour Edition 2009",
    ],
)
def test_an_edition_label_the_narrow_list_has_never_seen_is_the_same_release_for_the_broad_comparison(label: str) -> None:
    assert broad_release_family(f"Harbour ({label})") == broad_release_family("Harbour")
    assert broad_release_family(f"Harbour - {label}") == broad_release_family("Harbour")


def test_an_edition_label_the_narrow_list_has_never_seen_is_a_rival_for_the_narrow_comparison() -> None:
    """The narrow comparison only folds what it is sure of: the unknown label makes a second family, so the song is HELD (a delay), never stamped."""
    assert release_family("Harbour (Tour Edition)") != release_family("Harbour")
    song, hits, answers = world(
        Rel("1", "Harbour", "album", "2000-05-05"), Rel("2", "Harbour (Tour Edition)", "album", "2005-05-05")
    )
    verdict = choose_release(song, hits, answers)
    assert (verdict.outcome, verdict.reason) == ("none", "date_decided")


def test_symbol_titled_albums_are_different_releases_so_the_dates_alone_decide_nothing() -> None:
    song, hits, answers = world(
        Rel("1", "÷", "album", "2005-01-01"), Rel("2", "+", "album", "2010-02-02"), Rel("3", "Hit Single", "single", "2012-01-01")
    )
    verdict = choose_release(song, hits, answers)
    assert (verdict.outcome, verdict.reason) == ("none", "date_decided")


@pytest.mark.parametrize(
    ("album", "single"),
    [
        ("2001 Remastered", "2001 (Expanded Edition)"),
        ("+", "+ (Standard)"),
        ("Harbour", "Harbour (Tour Edition)"),
        ("Harbour", "Harbour (Collector's Edition)"),
    ],
)
def test_a_sole_album_and_its_own_edition_as_a_single_is_still_a_sole_album(album: str, single: str) -> None:
    song, hits, answers = world(Rel("1", album, "album", "2001-06-06"), Rel("2", single, "single", "2001-07-07"))
    verdict = choose_release(song, hits, answers)
    assert (verdict.outcome, verdict.reason) == ("none", "sole_album"), verdict


def test_the_year_is_never_written_by_a_stamp_and_a_placeholder_date_cannot_write_one() -> None:
    """Velvet Revolver: the catalogue dates 'Contraband' 1990-01-01 (a placeholder) and 2004-06-07: the stamp is the album and NO year (the date stays in `release_date`)."""
    song, hits, answers = world(
        Rel("1", "Contraband", "album", "1990-01-01"),
        Rel("2", "Contraband", "album", "2004-06-07"),
        Rel("3", "Fall Single", "single", "2004-03-03"),
    )
    verdict = choose_release(song, hits, answers)
    assert verdict.outcome == "matched" and verdict.match is not None
    assert verdict.match.album == "Contraband" and verdict.match.year is None


def test_the_plain_title_is_the_name_of_the_album_when_an_edition_ties_it() -> None:
    song, hits, answers = world(
        Rel("1", "By the Way (Deluxe Edition)", "album", "2002-07-09"),
        Rel("2", "By the Way", "album", "2002-07-09"),
        Rel("3", "By the Way Single", "single", "2002-08-01"),  # a LATER single: an earlier one would be single_before_album
    )
    verdict = choose_release(song, hits, answers)
    assert verdict.outcome == "matched" and verdict.match is not None and verdict.match.album == "By the Way"
