"""N-34 slice 2, review fix 1 (the lead's read of PR 125): an ISRC the song already holds is COUNTER-EVIDENCE.

A recording has one ISRC (a remaster or a re-recording has another). A song that holds ISRC X and meets a same-title, same-length catalogue entry that carries ISRC Y is not
that recording, and a `matched` stamp is permanent (`refs.find` matches the ids first; slice 5 files the song by its album). So the matcher refuses it as the same recording
(`isrc_differs`: a re-askable `none`, with `withheld` for the report), at the hit when the search row carries an ISRC and at the chosen release's song list, which is where the
catalogue gives one; the pass checks it AGAIN inside its write transaction (the row may have gained an ISRC since it was read). An equal ISRC, a song that holds none and a
catalogue entry that gives none stay as they were.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from encore_server import album_dryrun
from encore_server.album_finder import Song, choose_release, judge_hits
from encore_server.db import Database
from tests.test_album_finder import ALBUM, albums, creature_hit
from tests.test_album_pass import Catalogue, finder, landmvrks, make_ref, pdb, row_of  # noqa: F401 - `pdb` is a fixture

THE_RECORDING = "DEYO62300153"  # the recorded ISRC of "Creature" on the album (and on the single)
ANOTHER = "GBAYE0000001"


def creature(isrc: str | None) -> Song:
    return Song("LANDMVRKS", "Creature", 225_000, isrc)


def hit_with(isrc: str | None) -> dict[str, Any]:
    row = creature_hit()
    if isrc is not None:
        row["isrc"] = isrc
    return row


# ------------------------------------------------------------------------------------------------------------------ the hit


def test_a_hit_whose_isrc_is_another_recordings_is_refused_with_its_own_reason() -> None:
    (verdict,) = judge_hits(creature(THE_RECORDING), [hit_with(ANOTHER)])
    assert (verdict.reason, verdict.accepted, verdict.name_fits) == ("isrc_differs", False, True)


@pytest.mark.parametrize(
    ("song_isrc", "hit_isrc"),
    [
        (THE_RECORDING, THE_RECORDING),
        ("DE-YO6-23-00153", THE_RECORDING),
        (THE_RECORDING.lower(), THE_RECORDING),
        (None, ANOTHER),
        (THE_RECORDING, None),
    ],
)
def test_an_equal_isrc_a_song_without_one_and_a_hit_without_one_are_as_they_were(
    song_isrc: str | None, hit_isrc: str | None
) -> None:
    (verdict,) = judge_hits(creature(song_isrc), [hit_with(hit_isrc)])
    assert verdict.reason == "same_recording"


# ------------------------------------------------------------------------------------------------------------------ the chosen release's song list


def test_a_song_whose_isrc_differs_from_the_one_on_the_chosen_release_is_a_re_askable_none_and_never_matched() -> None:
    """The catalogue gives an ISRC in the album's song list even when the search row carries none: the second place the rule is asked (the row has its ISRC taken away here)."""
    row = creature_hit()
    row.pop("isrc", None)
    verdict = choose_release(creature(ANOTHER), [row], albums(ALBUM))
    assert (verdict.outcome, verdict.reason, verdict.remember, verdict.match) == ("none", "isrc_differs", True, None)
    assert verdict.withheld is not None and verdict.withheld.isrc == THE_RECORDING and ANOTHER in verdict.detail


def test_a_search_row_that_carries_the_other_isrc_is_refused_at_the_hit_and_the_song_is_the_same_re_askable_none() -> None:
    verdict = choose_release(creature(ANOTHER), [hit_with(THE_RECORDING)], albums(ALBUM))
    assert (verdict.outcome, verdict.reason, verdict.remember, verdict.match) == ("none", "isrc_differs", True, None)


def test_the_same_isrc_still_matches() -> None:
    verdict = choose_release(creature(THE_RECORDING), [creature_hit()], albums(ALBUM))
    assert (verdict.outcome, verdict.match is not None and verdict.match.isrc) == ("matched", THE_RECORDING)
    assert choose_release(creature(None), [creature_hit()], albums(ALBUM)).outcome == "matched"


# ------------------------------------------------------------------------------------------------------------------ the pass


def test_the_pass_never_stamps_a_song_that_holds_another_recordings_isrc(pdb: Database) -> None:  # noqa: F811
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, isrc=ANOTHER)
    report = finder(pdb, landmvrks()).run_once()
    after = row_of(pdb, ref)
    assert (report.matched, report.none) == (0, 1)
    assert (after["identity_outcome"], after["identity_reason"], after["album"], after["deezer_id"], after["isrc"]) == (
        "none",
        "isrc_differs",
        None,
        None,
        ANOTHER,
    )


def test_the_pass_stamps_a_song_that_holds_the_same_isrc(pdb: Database) -> None:  # noqa: F811
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, isrc=THE_RECORDING)
    assert finder(pdb, landmvrks()).run_once().matched == 1
    assert row_of(pdb, ref)["identity_outcome"] == "matched"


def test_a_song_that_gained_an_isrc_while_the_catalogue_was_asked_is_checked_again_in_the_write(pdb: Database) -> None:  # noqa: F811
    """The row is read again inside the write transaction: an ISRC that arrived since (a phone described the song, the library scan read its tags) counts."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)

    def somebody_describes_it() -> None:
        with pdb.tx() as conn:
            conn.execute("UPDATE song_ref SET isrc = ? WHERE id = ?", (ANOTHER, ref))

    base = landmvrks()
    report = finder(pdb, Catalogue(base.searches, base.known_albums, on_search=somebody_describes_it)).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["identity_reason"], after["album"], after["deezer_id"]) == (
        "none",
        "isrc_differs",
        None,
        None,
    )
    assert report.matched == 0


# ------------------------------------------------------------------------------------------------------------------ the dry run


def test_the_dry_run_carries_the_songs_isrc_and_so_reports_isrc_differs(pdb: Database) -> None:  # noqa: F811
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, isrc=ANOTHER)
    conn = sqlite3.connect(f"{pdb.path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        items = album_dryrun.entries(conn)
        rows = album_dryrun.run(conn, items, lambda artist, title: [creature_hit()], lambda ident: albums(ALBUM)[ident])
    finally:
        conn.close()
    assert [(e.ref_id, e.song.isrc) for e in items] == [(ref, ANOTHER)]
    assert [(r.verdict.outcome, r.verdict.reason) for r in rows] == [("none", "isrc_differs")]


def test_a_song_that_holds_an_isrc_is_not_matched_with_the_catalogue_entry_of_another_recording_when_the_right_one_is_among_the_hits(
    pdb: Database,  # noqa: F811
) -> None:
    """Two entries of the same name on the same album, the lower id carrying another recording's ISRC: without the song's own ISRC the matcher takes the lower id, whose song the
    album's list does not hold (a miss); with it, that entry is refused at the hit and the right one is stamped."""
    other = creature_hit()
    other.update(id=3116792060, isrc=ANOTHER)
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, isrc=THE_RECORDING)
    catalogue = Catalogue({("LANDMVRKS", "Creature"): [other, creature_hit()]}, albums(ALBUM))
    finder(pdb, catalogue).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["deezer_id"], after["isrc"]) == ("matched", "3116792061", THE_RECORDING)
