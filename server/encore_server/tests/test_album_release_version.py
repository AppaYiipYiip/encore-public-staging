"""N-34 slice 2, what the live dry run of 24 Nov 2026 found (PR 125): a studio song was stamped with a LIVE album.

`Ja Rule - Always On Time` was matched to `Ja Rule: 2005 (Live)` (an album of 2006) because the matcher refused a HIT whose own title is marked live, a remix or another
version when the song's is not, but never looked at the same marks in the RELEASE's title, and the live album was the earliest of the two releases the studio song is on.
A stamp is permanent (slice 5 files the song by it), so the same marks now refuse a release as the song's release (`release_version`): the other release is chosen, or the song
is a re-askable `none` (`release_version_mismatch`), never `matched`. The labels that are ignored for a hit stay ignored (Remastered, Deluxe, Explicit, Clean, Radio Edit).

The answers are the REAL ones of that run (`tests/fixtures/deezer/n34_dryrun_24nov.json` lists the 8 files copied byte for byte); a derived case changes exactly the named fields.
"""

from __future__ import annotations

import copy
import functools
import json
from typing import Any

import httpx
import pytest

from encore_server import album_finder
from encore_server.album_dryrun import Entry, Report, Row
from encore_server.album_finder import Song, choose_release, release_markers, wanted_albums
from encore_server.catalogue import Cache, Catalogue
from encore_server.db import Database
from encore_server.deezer import DeezerClient, Gate
from encore_server.fixture_names import fixture_name
from tests.catalogue_fakes import RECORDED, RecordedDeezer, recorded_search
from tests.test_album_pass import Catalogue as FakeCatalogue
from tests.test_album_pass import finder, make_ref, pdb, row_of  # noqa: F401 - `pdb` is a fixture

PAIN_IS_LOVE, JA_RULE_LIVE, OPETH_REMIXED = "85606442", "11552538", "11539892"
ALWAYS_ON_TIME = Song("Ja Rule", "Always On Time", 244_000)  # the file was 244 s: the catalogue's two entries are 243 s and 245 s


@functools.cache
def _answers() -> dict[str, dict[str, Any]]:
    catalogue = Catalogue(
        DeezerClient(Gate(rate=1000, burst=1000, background_gap_s=0.0), httpx.Client(transport=RecordedDeezer().transport())),
        Cache(None),
    )
    return {
        ident: catalogue.album(ident, priority="background", deadline_s=10.0)
        for ident in (PAIN_IS_LOVE, JA_RULE_LIVE, OPETH_REMIXED)
    }


def albums(*ids: str) -> dict[str, dict[str, Any]]:
    return {ident: copy.deepcopy(_answers()[ident]) for ident in ids}


def ja_rule_hits() -> list[dict[str, Any]]:
    return copy.deepcopy(recorded_search("Ja Rule Always On Time")["data"])


def hit_on(album_id: str) -> dict[str, Any]:
    return next(row for row in ja_rule_hits() if str(row["album"]["id"]) == album_id)


# ------------------------------------------------------------------------------------------------------------------ the marks of a release's title


@pytest.mark.parametrize(
    ("title", "marks"),
    [
        ("Ja Rule: 2005 (Live)", {"live"}),
        ("Live at Hellfest", {"live"}),
        ("Deliverance & Damnation Remixed", {"remix"}),
        ("The Remixes", {"remix"}),
        ("Songs (Acoustic)", {"acoustic"}),
        ("Early Demos", {"demo"}),
        ("Back Porch Jam (Instrumentals)", {"instrumental"}),
        ("Karaoke Hits", {"karaoke"}),
        ("Slowed and Reverb", {"slowed", "reverb"}),
        # ignored, as they are for a hit: the labels that say which PRINTING it is, not which recording
        ("Pain Is Love", set()),
        ("Hybrid Theory (Bonus Edition)", set()),
        ("The Blueprint (Explicit Version)", set()),
        ("No Need To Argue (2025 Remastered)", set()),
        ("By the Way (Deluxe Edition)", set()),
        ("Black Betty (Radio Edit)", set()),
        ("Most Known Unknown (Explicit)", set()),
        ("Weezer (Green Album)", set()),
        ("Three Ringz (Thr33 Ringz)", set()),
        # whole words only
        ("Lives in the Balance", set()),
        ("Alive", set()),
        ("Delivery", set()),
        ("Democracy", set()),
        ("", set()),
    ],
)
def test_the_marks_of_a_release_title_are_the_servers_version_words_and_nothing_else(title: str, marks: set[str]) -> None:
    assert release_markers(title) == frozenset(marks)


# ------------------------------------------------------------------------------------------------------------------ the case itself, on the real answers


def test_the_studio_song_is_on_the_studio_album_and_not_on_the_live_one_the_earlier_date_chose() -> None:
    """THE LIVE DRY RUN'S FINDING. Both releases carry the song at its length; the live album is the earliest (2006 against 2019), so the old rule took it."""
    found = ja_rule_hits()
    assert sorted(wanted_albums(ALWAYS_ON_TIME, found)) == sorted([PAIN_IS_LOVE, JA_RULE_LIVE]), (
        "the premise: both releases are asked"
    )
    verdict = choose_release(ALWAYS_ON_TIME, found, albums(PAIN_IS_LOVE, JA_RULE_LIVE))
    assert (verdict.outcome, verdict.reason) == ("matched", "matched")
    assert verdict.match is not None and (verdict.match.album, verdict.match.deezer_id) == ("Pain Is Love", "623714342")
    assert {r.album_id: r.reason for r in verdict.releases} == {PAIN_IS_LOVE: "chosen", JA_RULE_LIVE: "release_version"}


def test_a_studio_song_whose_only_release_is_a_live_album_is_a_re_askable_none_and_never_matched() -> None:
    only_live = [hit_on(JA_RULE_LIVE)]
    verdict = choose_release(ALWAYS_ON_TIME, only_live, albums(JA_RULE_LIVE))
    assert (verdict.outcome, verdict.reason, verdict.remember, verdict.match) == ("none", "release_version_mismatch", True, None)
    assert [(r.album_id, r.reason) for r in verdict.releases] == [(JA_RULE_LIVE, "release_version")]


def test_the_pass_stamps_the_studio_album_and_not_the_live_one(pdb: Database) -> None:  # noqa: F811
    ref = make_ref(pdb, "Always On Time", "Ja Rule", 244_000)
    catalogue = FakeCatalogue({("Ja Rule", "Always On Time"): ja_rule_hits()}, albums(PAIN_IS_LOVE, JA_RULE_LIVE))
    finder(pdb, catalogue).run_once()
    after = row_of(pdb, ref)
    assert (after["album"], after["identity_outcome"], after["deezer_id"]) == ("Pain Is Love", "matched", "623714342")


def test_a_song_that_is_itself_a_remix_may_take_the_remix_release_the_control() -> None:
    """Opeth, `To Rid the Disease (Remixed)`, 381 s, on `Deliverance & Damnation Remixed`: the song's own title says remix, so a release that says it is no mismatch."""
    song = Song("Opeth", "To Rid the Disease (Remixed)", 381_000)
    found = copy.deepcopy(recorded_search("Opeth To Rid the Disease (Remixed)")["data"])
    verdict = choose_release(song, found, albums(OPETH_REMIXED))
    assert (verdict.outcome, verdict.reason) == ("matched", "matched")
    assert verdict.match is not None and verdict.match.album == "Deliverance & Damnation Remixed"


def test_a_remix_song_may_take_a_remix_release_and_not_a_live_one() -> None:
    """DERIVED: the song's own marks license ITS marks, not every mark: the Opeth remix on a release titled `(Live)` is a release of another recording."""
    answers = albums(OPETH_REMIXED)
    answers[OPETH_REMIXED]["album"]["title"] = "Deliverance & Damnation (Live)"
    found = copy.deepcopy(recorded_search("Opeth To Rid the Disease (Remixed)")["data"])
    verdict = choose_release(Song("Opeth", "To Rid the Disease (Remixed)", 381_000), found, answers)
    assert (verdict.outcome, verdict.reason) == ("none", "release_version_mismatch")


def test_the_same_release_is_refused_for_a_studio_song_of_that_name() -> None:
    """DERIVED: the recorded Opeth hit with `(Remixed)` taken out of its title, so the song (a studio one) and the hit agree and only the RELEASE says remix."""
    found = copy.deepcopy(recorded_search("Opeth To Rid the Disease (Remixed)")["data"])
    found[0]["title"] = "To Rid the Disease"
    verdict = choose_release(Song("Opeth", "To Rid the Disease", 381_000), found, albums(OPETH_REMIXED))
    assert (verdict.outcome, verdict.reason) == ("none", "release_version_mismatch")


def test_a_live_song_may_take_the_live_album() -> None:
    """DERIVED: the song and the hit both say `(Live)`: the live album is its release."""
    hit = hit_on(JA_RULE_LIVE)
    hit["title"] = "Always On Time (Live)"
    verdict = choose_release(Song("Ja Rule", "Always On Time (Live)", 245_000), [hit], albums(JA_RULE_LIVE))
    assert (verdict.outcome, verdict.reason) == ("matched", "matched")


@pytest.mark.parametrize(
    "label",
    [
        "Deluxe Edition",
        "Remastered",
        "2019 Remaster",
        "Explicit Version",
        "Radio Edit",
        "Clean",
        "Bonus Edition",
        "Expanded Edition",
    ],
)
def test_the_labels_that_say_which_printing_it_is_do_not_refuse_a_release(label: str) -> None:
    """DERIVED: the studio album with each label added to its title."""
    answers = albums(PAIN_IS_LOVE)
    answers[PAIN_IS_LOVE]["album"]["title"] = f"Pain Is Love ({label})"
    verdict = choose_release(ALWAYS_ON_TIME, [hit_on(PAIN_IS_LOVE)], answers)
    assert (verdict.outcome, verdict.reason) == ("matched", "matched"), label


def test_a_release_the_version_rule_refused_does_not_hide_a_better_reason_for_another() -> None:
    """DERIVED: the live album AND a release by somebody else: nothing is eligible, and the reason names the version only when the version was what refused a release."""
    answers = albums(JA_RULE_LIVE, PAIN_IS_LOVE)
    answers[PAIN_IS_LOVE]["album"]["artists"] = [{"id": "1", "name": "Somebody Else"}]
    verdict = choose_release(ALWAYS_ON_TIME, ja_rule_hits(), answers)
    assert (verdict.outcome, verdict.reason) == ("none", "release_version_mismatch")
    assert {r.album_id: r.reason for r in verdict.releases} == {PAIN_IS_LOVE: "album_artist", JA_RULE_LIVE: "release_version"}


# ------------------------------------------------------------------------------------------------------------------ the report, the revision, the recordings


def test_the_report_names_the_new_cause_and_the_isrc_cause() -> None:
    verdict = choose_release(ALWAYS_ON_TIME, [hit_on(JA_RULE_LIVE)], albums(JA_RULE_LIVE))
    text = Report([Row(Entry("sr_a", ALWAYS_ON_TIME, "file"), verdict)], 3000).render()
    lines = [line for line in text.splitlines() if "release_version_mismatch" in line]
    assert any(line.split()[0] == "1" and "live" in line.lower() for line in lines), lines


def test_the_revision_was_raised_because_the_rule_changed() -> None:
    """Nothing was stamped anywhere with revision 1 (the live dry run writes nothing), so raising it costs nothing: the first pass on a real server asks every song under revision 2."""
    assert album_finder.IDENTITY_REVISION == 3


def test_every_answer_the_live_dry_run_ledger_names_is_here_and_is_the_answer_to_its_own_request() -> None:
    ledger = json.loads((RECORDED / "n34_dryrun_24nov.json").read_text(encoding="utf-8"))
    assert len(ledger["files"]) == 8 and len(set(ledger["files"])) == 8
    for name in ledger["files"]:
        body = json.loads((RECORDED / f"{name}.json").read_text(encoding="utf-8"))
        assert fixture_name(body["path"], body["params"]) == name, f"{name} is not named by the one rule for what it answers"
