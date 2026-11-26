"""N-34, the first live pass on a real server (25 Nov 2026): RULE 2, `sole_album`. My Chemical Romance `Welcome to the Black Parade` was stamped with the 2014 compilation `May Death Never
Stop You`: it was the SOLE release among the eight hits of the search, and the album the song is really on was not among them. A sole ALBUM among the hits proves nothing about the other albums
the catalogue may carry the song on (a compilation, a re-record such as Papa Roach's 2020 `20/20`), and a stamp is permanent. So a song whose only same-recording release is an ALBUM
(one release family among the eligible releases, editions folded) is a re-askable `none`, `sole_album`. **The price is a delay** (the song waits in "Songs without an album" until the artist's
discography (item N-48) shows that ONE release family carries the recording); a sole EP stays accepted (the artist's own EPs; a compilation EP is rare) and a sole single is `single_only` already.

The real answers are the second live dry run's (`tests/album_world.py`); the made catalogue states what each release is.
"""

from __future__ import annotations

import pytest

from encore_server.album_finder import choose_release
from tests.album_world import Rel, outcome, recorded_inputs, recorded_song, verdict_of

ALBUM = Rel("1", "Harbour", "album", "2000-05-05")


def test_the_compilation_that_was_the_sole_release_among_the_hits_is_a_re_askable_none() -> None:
    verdict = recorded_song("My Chemical Romance", "Welcome to the Black Parade")
    assert outcome(verdict) == ("none", "sole_album") and verdict.remember and verdict.match is None
    assert verdict.withheld is not None and verdict.withheld.album == "May Death Never Stop You"
    assert [r.reason for r in verdict.releases] == ["chosen"], "the premise: it was the only release"


def test_an_album_and_its_own_anniversary_deluxe_edition_are_one_family_on_the_real_answers() -> None:
    """3 Doors Down `Kryptonite`: `The Better Life` and `The Better Life (20th Anniversary / Deluxe)` are the only two releases of the hits that carry it (the catalogue's other entry is a
    live record, refused): one family, so the album is the sole release."""
    verdict = recorded_song("3 Doors Down", "Kryptonite")
    assert outcome(verdict) == ("none", "sole_album")
    assert verdict.withheld is not None and verdict.withheld.album == "The Better Life"


def test_a_sole_album_is_none_whatever_its_title_or_date() -> None:
    for rel in (
        ALBUM,
        Rel("1", "Gold", "album", "1999-01-01"),
        Rel("1", "Harbour", "album", None),
        Rel("1", "Moorings (Deluxe Edition)", "album", "2019-07-08"),
    ):
        assert outcome(verdict_of(rel)) == ("none", "sole_album"), rel


def test_two_editions_of_one_album_are_one_family_so_the_album_is_still_sole() -> None:
    verdict = verdict_of(
        ALBUM,
        Rel("2", "Harbour (Deluxe Edition)", "album", "2005-05-05"),
        Rel("3", "Harbour (20th Anniversary Edition)", "album", "2020-05-05"),
    )
    assert outcome(verdict) == ("none", "sole_album")


def test_a_sole_ep_stays_matched() -> None:
    verdict = verdict_of(Rel("1", "Metamorphose", "ep", "2023-02-19"))
    assert outcome(verdict) == ("matched", "matched") and verdict.match is not None and verdict.match.record_type == "ep"
    assert outcome(recorded_song("Pause", "Lyam")) == ("matched", "matched")


def test_a_sole_single_is_single_only_not_sole_album() -> None:
    assert outcome(verdict_of(Rel("1", "Harbour Lights", "single", "2000-05-05"))) == ("none", "single_only")


def test_an_album_with_a_single_of_the_song_beside_it_is_matched_the_single_is_a_second_release_family() -> None:
    """The single is the song's own lead release: a second family among the eligible releases, as the album's `Chop Suey!` and `Hate It Or Love It` are on the real answers."""
    verdict = verdict_of(ALBUM, Rel("9", "Harbour Lights", "single", "2000-07-07"))
    assert outcome(verdict) == ("matched", "matched") and verdict.match is not None and verdict.match.album_id == "1"
    assert outcome(recorded_song("System Of A Down", "Chop Suey!")) == ("matched", "matched")


@pytest.mark.parametrize(
    "refused",
    [
        Rel(
            "2", "Moorings", "album", "2003-03-03", artist="Various Artists"
        ),  # somebody else's compilation is no second release of THIS artist's song
        Rel("2", "Harbour Lights (Live)", "album", "2003-03-03"),  # a live record is another recording
        Rel("2", "Unknown Album", "album", "2003-03-03"),
        Rel("2", "Moorings", "compile", "2003-03-03"),
    ],
)
def test_a_release_that_could_never_be_chosen_is_no_second_family_so_the_album_is_still_sole(refused: Rel) -> None:
    assert outcome(verdict_of(ALBUM, refused)) == ("none", "sole_album"), refused


def test_a_sole_album_that_is_also_a_compilation_by_its_title_keeps_the_older_reason() -> None:
    """Both reasons are re-askable and say the same in the end; the title's reason is the more specific, and it was already there."""
    assert outcome(verdict_of(Rel("1", "Greatest Hits", "album", "2000-05-05"))) == ("none", "compilation_title")


def test_the_recorded_answers_of_the_stamped_song_still_say_the_real_album_was_not_asked_for() -> None:
    """The cause, in the answers: no hit of `Welcome to the Black Parade` is on `The Black Parade`."""
    song, hits, answers = recorded_inputs("My Chemical Romance", "Welcome to the Black Parade")
    titles = {a["album"]["title"] for a in answers.values()}
    assert titles == {"May Death Never Stop You"}
    assert outcome(choose_release(song, hits, answers)) == ("none", "sole_album")
