"""N-34 slice 2, the advisor's ruling after the live dry run of 24 Nov 2026 (the independent review of PR 125): SLICE 2 NEVER STAMPS A SINGLE.

40 of the 150 live stamps were `single` releases, and two of them are album tracks stamped as singles (`Fat Joe - What's Luv?`, `T-Pain - Buy U A Drank`). A stamp is permanent, and
the later rounds (the artist's discography, a better rule) only ask `none` and `held` again, so a single stamped here can never be corrected; and the eight hits of a search cannot
prove that no album carries the recording. So a song whose only same-recording release is a SINGLE is a re-askable `none` with the reason `single_only`, in the matcher AND again in
the pass's write transaction. EPs stay accepted. An album that wins over an earlier single is as it was. **The cost is a delay**: the song stays in "Songs without an album" until the
discography round finds an album that carries the recording (3 of the 32 such songs on 26 Nov 2026; for 27 more none does, and a stamp of the single itself is a later item, N-51).

The answers are the REAL ones of the live run (`tests/fixtures/deezer/n34_dryrun_24nov.json`).
"""

# ruff: noqa: F811
from __future__ import annotations

import copy
import dataclasses
import functools
from typing import Any

import httpx
import pytest

from encore_server import album_finder
from encore_server.album_dryrun import Entry, Report, Row
from encore_server.album_finder import Song, Verdict, choose_release
from encore_server.catalogue import Cache
from encore_server.catalogue import Catalogue as RealCatalogue
from encore_server.db import Database
from encore_server.deezer import DeezerClient, Gate
from tests.catalogue_fakes import RecordedDeezer, recorded_search
from tests.test_album_finder import ALBUM, SINGLE, albums, creature_hit, derive, single_hit, with_later_single
from tests.test_album_pass import DAY_MS, NOW, Catalogue, finder, make_ref, pdb, row_of  # noqa: F401 - `pdb` is a fixture

WHATS_LUV = "362957"  # `What's Luv? (feat. Ashanti)`, a single of 2002-02-05
BUY_U_A_DRANK = "72512"  # `Buy U A Drank (Shawty Snappin')`, a single of 2007-06-04
FAT_JOE = Song("Fat Joe", "What's Luv?", 231_000)
T_PAIN = Song("T-Pain", "Buy U A Drank (Shawty Snappin')", 229_000)
CREATURE = Song("LANDMVRKS", "Creature", 225_000)


@functools.cache
def _catalogue() -> RealCatalogue:
    return RealCatalogue(
        DeezerClient(Gate(rate=1000, burst=1000, background_gap_s=0.0), httpx.Client(transport=RecordedDeezer().transport())),
        Cache(None),
    )


def mapped_album(ident: str) -> dict[str, Any]:
    """What `Catalogue.album` answers for a recorded album: its raw answer and song list through the server's own mapping."""
    return copy.deepcopy(_catalogue().album(ident, priority="background", deadline_s=10.0))


def hits(query: str) -> list[dict[str, Any]]:
    return copy.deepcopy(recorded_search(query)["data"])


# ------------------------------------------------------------------------------------------------------------------ the two real songs


@pytest.mark.parametrize(
    ("song", "query", "album_id", "title"),
    [
        (FAT_JOE, "Fat Joe What's Luv?", WHATS_LUV, "What's Luv? (feat. Ashanti)"),
        (T_PAIN, "T-Pain Buy U A Drank (Shawty Snappin')", BUY_U_A_DRANK, "Buy U A Drank (Shawty Snappin')"),
    ],
)
def test_a_song_whose_only_release_is_a_single_is_a_re_askable_none_and_never_matched(
    song: Song, query: str, album_id: str, title: str
) -> None:
    verdict = choose_release(song, hits(query), {album_id: mapped_album(album_id)})
    assert (verdict.outcome, verdict.reason, verdict.remember, verdict.match) == ("none", "single_only", True, None)
    assert verdict.withheld is not None and (verdict.withheld.album, verdict.withheld.record_type) == (title, "single")
    assert [(r.album_id, r.reason) for r in verdict.releases] == [(album_id, "chosen")], (
        "the matcher chose it, and the rule refused the stamp"
    )


def test_the_recorded_creature_single_alone_is_the_same_none() -> None:
    """The step-0 recordings: the single of Creature (524195422) is the only release among the hits."""
    verdict = choose_release(CREATURE, [single_hit()], albums(SINGLE))
    assert (verdict.outcome, verdict.reason) == ("none", "single_only")


def test_an_ep_is_still_accepted_the_rule_is_about_singles() -> None:
    """DERIVED: the recorded single of Creature typed `ep` (a record of one song is no album, but the catalogue calls it an EP and nothing here says otherwise)."""
    verdict = choose_release(CREATURE, [single_hit()], {SINGLE: derive(albums(SINGLE)[SINGLE], recordType="ep")})
    assert (verdict.outcome, verdict.reason) == ("matched", "matched")
    assert verdict.match is not None and verdict.match.record_type == "ep"


def test_an_album_that_wins_over_an_earlier_single_is_as_it_was_inside_the_window() -> None:
    verdict = choose_release(
        CREATURE,
        [single_hit(), creature_hit()],
        {ALBUM: albums(ALBUM)[ALBUM], SINGLE: albums(SINGLE)[SINGLE]},
        single_window_days=500,
    )
    assert (verdict.outcome, verdict.reason) == ("matched", "matched")
    assert verdict.match is not None and verdict.match.album_id == ALBUM


def test_a_single_is_still_the_choice_of_nobody_when_an_album_was_refused_for_another_reason() -> None:
    """DERIVED: the album of Creature credited to somebody else (refused) and the single: the single is all that is left, so the song waits: it is the ruling's own case, the
    album the catalogue may carry elsewhere is what the later round looks for."""
    answers = {
        ALBUM: derive(albums(ALBUM)[ALBUM], artists=[{"id": "1", "name": "Various Artists"}]),
        SINGLE: albums(SINGLE)[SINGLE],
    }
    verdict = choose_release(CREATURE, [single_hit(), creature_hit()], answers)
    assert (verdict.outcome, verdict.reason) == ("none", "single_only")


# ------------------------------------------------------------------------------------------------------------------ the pass and the report


def test_the_pass_stamps_nothing_for_a_song_whose_only_release_is_a_single(pdb: Database) -> None:
    ref = make_ref(pdb, "What's Luv?", "Fat Joe", 231_000)
    catalogue = Catalogue({("Fat Joe", "What's Luv?"): hits("Fat Joe What's Luv?")}, {WHATS_LUV: mapped_album(WHATS_LUV)})
    finder(pdb, catalogue).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["identity_reason"], after["deezer_id"], after["album"], after["track_no"]) == (
        "none",
        "single_only",
        None,
        None,
        None,
    )


def test_the_write_transaction_refuses_a_single_even_when_the_verdict_says_matched(
    pdb: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second layer: a matched verdict whose release is a single (a hand-made verdict, a future matcher) writes no album and no id."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    real = album_finder.decide

    def a_matched_verdict_for_a_single(song: Song, *args: Any, **kwargs: Any) -> Verdict:
        good = real(song, *args, **kwargs)
        assert good.match is not None
        return Verdict("matched", "matched", match=dataclasses.replace(good.match, record_type="single"))

    monkeypatch.setattr(album_finder, "decide", a_matched_verdict_for_a_single)
    found, both = with_later_single([creature_hit()], albums(ALBUM))  # a single beside the album: no sole release (25 Nov 2026)
    finder(pdb, Catalogue({("LANDMVRKS", "Creature"): found}, both)).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["identity_reason"], after["deezer_id"]) == ("none", "single_only", None)


def test_a_single_only_song_is_asked_again_after_seven_days_and_when_the_rule_gets_better(
    pdb: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_ref(pdb, "What's Luv?", "Fat Joe", 231_000)
    catalogue = Catalogue({("Fat Joe", "What's Luv?"): hits("Fat Joe What's Luv?")}, {WHATS_LUV: mapped_album(WHATS_LUV)})
    finder(pdb, catalogue, now=NOW).run_once()
    finder(pdb, catalogue, now=NOW + 7 * DAY_MS - 1).run_once()
    assert len(catalogue.searched) == 1
    finder(pdb, catalogue, now=NOW + 7 * DAY_MS).run_once()
    assert len(catalogue.searched) == 2
    monkeypatch.setattr(album_finder, "IDENTITY_REVISION", album_finder.IDENTITY_REVISION + 1)
    finder(pdb, catalogue, now=NOW + 7 * DAY_MS).run_once()
    assert len(catalogue.searched) == 3


def test_the_report_counts_the_single_only_songs_apart_and_says_why() -> None:
    verdict = choose_release(FAT_JOE, hits("Fat Joe What's Luv?"), {WHATS_LUV: mapped_album(WHATS_LUV)})
    text = Report([Row(Entry("sr_a", FAT_JOE, "file"), verdict)], 3000).render()
    lines = [line for line in text.splitlines() if "single_only" in line]
    assert any(line.split()[0] == "1" and "single" in line.lower() and "discography" in line.lower() for line in lines), lines


def test_the_revision_was_raised_for_the_single_rule() -> None:
    assert album_finder.IDENTITY_REVISION == 5, (
        "the latest revision: 5 is the first with `date_decided` and `sole_album` (25 Nov 2026); the data it pins is in test_album_withheld.py"
    )


def test_the_write_transaction_still_stamps_a_matched_ep(pdb: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other side of the second layer (the independent review of PR 125): an EP is accepted, so a matched verdict whose release is an EP is written, and the write
    transaction does not treat it like a single."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    real = album_finder.decide

    def a_matched_verdict_for_an_ep(song: Song, *args: Any, **kwargs: Any) -> Verdict:
        good = real(song, *args, **kwargs)
        assert good.match is not None
        return Verdict("matched", "matched", match=dataclasses.replace(good.match, record_type="ep"))

    monkeypatch.setattr(album_finder, "decide", a_matched_verdict_for_an_ep)
    found, both = with_later_single([creature_hit()], albums(ALBUM))
    finder(pdb, Catalogue({("LANDMVRKS", "Creature"): found}, both)).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["identity_reason"]) == ("matched", "matched")
    assert after["album"] is not None and after["deezer_id"] is not None
