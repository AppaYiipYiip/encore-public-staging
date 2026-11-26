"""N-47 (audit B-138): two songs are merged only on a file the music server still lists, and the merge is decided where that can be shown.

A merge cannot be undone (a like on the merged-away ref moves to the survivor). `refmerge.repair` used to count every row of `song_file`, including a row the music server no longer lists and the very
next pass removes; the start-up repair, which has no listing at all, merged on such rows too. The rule now: a shared file counts only when `link_listing.Listing.alive` says the pass leaves it alive (the
ONE definition `scanner._prune` and the rehome already use), the decision is taken at the end of a COMPLETE pass, and a start-up or an incomplete pass decides nothing.

The first tests drive the real thing (the start-up of the app, then a real pass of the library link) so they stay true whatever the repair's internal shape is; the later ones pin the repair's own contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from encore_server import refmerge
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.ids import now_ms
from encore_server.link_listing import Listing
from encore_server.scanner import link_library
from tests.conftest import FakeVerifier
from tests.test_ref_merge import L1, S1, add_file, add_ref, one, q, rid
from tests.test_scanner import FakeLibrary, entry


def two_refs_one_file(db: Database) -> None:
    """The keeper's ref and a ref the scan made, both attached to the music server's file `nd-1` (the pair the repair exists for)."""
    with db.tx() as c:
        add_ref(c, S1, "Creature", ["LANDMVRKS"])
        add_ref(c, L1, "Creature", ["LANDMVRKS"])
        add_file(c, S1, "nd-1", 4000, source="youtube", path="a.opus")
        add_file(c, L1, "nd-1", 5000, source="library", path="a.opus")


def start(tmp_path: Path, db: Database, verifier: FakeVerifier) -> None:
    settings = Settings(
        data_dir=db.path.parent, music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    create_app(settings, verifier=verifier, db=db)  # the start-up: whatever the repair does at start, it has done by now


def merges(db: Database) -> int:
    return int(one(db, "SELECT COUNT(*) FROM ref_merge"))


def live_refs(db: Database) -> set[str]:
    return {row["id"] for row in q(db, "SELECT id FROM song_ref")}


def test_two_songs_that_share_only_a_file_the_music_server_no_longer_lists_are_never_merged(
    tmp_path: Path, db: Database, verifier: FakeVerifier
) -> None:
    two_refs_one_file(db)
    start(tmp_path, db, verifier)  # the start-up repair has no listing: it cannot say the file is still there

    # The tester's scenario (B-138): FIRST a pass that only adds (the one after a scan): the rows of nd-1 are still there, the music server does not list them, nothing has pruned them yet.
    # The repair must not take them for evidence. THEN the pass that prunes: the rows go, and the two songs share nothing any more.
    link_library(db, FakeLibrary([entry(2)]), prune=False)
    assert one(db, "SELECT COUNT(*) FROM song_file WHERE navidrome_song_id = 'nd-1'") == 2, "the add-only pass pruned nothing"
    assert merges(db) == 0, "merged on a file the music server does not list"
    link_library(db, FakeLibrary([entry(2)]))

    assert merges(db) == 0 and {S1, L1} <= live_refs(db), "two songs were merged on a file that is gone"


def test_two_songs_that_share_a_file_the_music_server_lists_are_merged_by_a_complete_pass(
    tmp_path: Path, db: Database, verifier: FakeVerifier
) -> None:
    """The control: the repair still does its work, where it can be shown that the file is there."""
    two_refs_one_file(db)
    start(tmp_path, db, verifier)

    link_library(db, FakeLibrary([entry(1)]))

    assert merges(db) == 1 and len({S1, L1} & live_refs(db)) == 1


def test_a_pass_the_music_server_cut_short_merges_nothing(tmp_path: Path, db: Database, verifier: FakeVerifier) -> None:
    two_refs_one_file(db)
    start(tmp_path, db, verifier)
    library = FakeLibrary([entry(1)])
    library.down = True  # the music server stopped answering: no complete listing

    link_library(db, library)

    assert merges(db) == 0 and {S1, L1} <= live_refs(db)


# ------------------------------------------------------------------------------------------------------------------ the repair's own contract


def listing_of(*ids: str, began: int | None = None, complete: bool = True) -> Listing:
    return Listing(began=now_ms() + 10_000 if began is None else began, seen=set(ids), complete=complete)


def test_the_repair_counts_a_shared_file_only_when_the_listing_leaves_it_alive(db: Database) -> None:
    two_refs_one_file(db)

    gone = refmerge.repair(db, listing_of("nd-9"))
    assert gone.merged == [] and merges(db) == 0, "nd-1 is not in the listing: not alive, not evidence"

    listed = refmerge.repair(db, listing_of("nd-1"))
    assert [(m.survivor, m.loser) for m in listed.merged] == [(L1, S1)] or [(m.survivor, m.loser) for m in listed.merged] == [
        (S1, L1)
    ]


def test_a_row_attached_after_the_pass_began_is_alive_whatever_the_listing_says(db: Database) -> None:
    """`Listing.alive`'s own rule (the keeper attaches mid-pass): the repair does not second-guess it."""
    two_refs_one_file(db)

    report = refmerge.repair(
        db, listing_of("nd-9", began=1_000)
    )  # both rows were added after the pass began (added_at 4000 and 5000)

    assert len(report.merged) == 1


@pytest.mark.parametrize("listing", [None, listing_of("nd-1", complete=False)])
def test_without_a_complete_listing_the_repair_decides_nothing_and_writes_nothing(db: Database, listing: Listing | None) -> None:
    two_refs_one_file(db)

    report = refmerge.repair(db, listing)

    assert report.merged == [] and report.backup is None and report.failed is False and merges(db) == 0


def test_a_merge_still_needs_every_old_hold_to_pass_the_alive_test_changes_none_of_them(db: Database) -> None:
    """The holds (different source video, ISRC, Deezer id, same playlist, recheck pending) are judged exactly as before on the pairs that are alive."""
    with db.tx() as c:
        add_ref(c, S1, "Creature", ["LANDMVRKS"], ytm_video_id="aaaaaaaaaaa")
        add_ref(c, L1, "Creature", ["LANDMVRKS"], ytm_video_id="bbbbbbbbbbb")
        add_file(c, S1, "nd-1", 4000, source="youtube", path="a.opus")
        add_file(c, L1, "nd-1", 5000, source="library", path="a.opus")

    report = refmerge.repair(db, listing_of("nd-1"))

    assert report.merged == [] and [h.reason for h in report.held] == ["different_source_video"]


def test_a_pass_with_nothing_to_merge_never_runs_the_repair_so_held_pairs_are_not_logged_every_hour(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repair logs every held pair each time it runs (once per start before N-47). The pass-end merge looks first and runs it only when a pair can be merged."""
    with db.tx() as c:
        add_ref(c, S1, "Creature", ["LANDMVRKS"], ytm_video_id="aaaaaaaaaaa")  # two recordings: held, never merged
        add_ref(c, L1, "Creature", ["LANDMVRKS"], ytm_video_id="bbbbbbbbbbb")
        add_file(c, S1, "nd-1", 4000, source="youtube", path="a.opus")
        add_file(c, L1, "nd-1", 5000, source="library", path="a.opus")
    calls: list[int] = []
    monkeypatch.setattr(refmerge, "repair", lambda database, listing: calls.append(1) or refmerge.RepairReport())

    for _ in range(3):
        link_library(db, FakeLibrary([entry(1)]))

    assert calls == [], "a held pair is not a reason to run (and log) the repair every hour"


def test_a_worklist_that_never_empties_does_not_stop_the_other_pairs_from_merging(db: Database) -> None:
    """The key repair's worklist (`ref_recheck`) holds ITS refs' pairs (`recheck_pending`); the other pairs merge in every complete pass, worklist or not (the pass-end merge is not tied to an empty worklist)."""
    other_a, other_b = rid("sr", 5), rid("sr", 6)
    two_refs_one_file(db)
    with db.tx() as c:
        add_ref(c, other_a, "Requiem", ["LANDMVRKS"])
        add_ref(c, other_b, "Requiem", ["LANDMVRKS"])
        add_file(c, other_a, "nd-2", 4000, source="youtube", path="b.opus")
        add_file(c, other_b, "nd-2", 5000, source="library", path="b.opus")
        c.execute("INSERT INTO ref_recheck (ref, at, moved) VALUES (?, 1, 0)", (other_a,))

    link_library(db, FakeLibrary([entry(1), entry(2)]))

    merged = {row["old_id"] for row in q(db, "SELECT old_id FROM ref_merge")}
    assert merged & {S1, L1}, "the pair of refs that are not on the worklist was merged"
