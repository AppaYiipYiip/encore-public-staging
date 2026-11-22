"""P2-25 slice 4, second review round, item 4 (audit probe 5): the sentences that say why a song stays on the worklist and what lets it go are TRUE.

Three sentences of the first build said that tagging frees only the first reason (or only a file with no usable tags). The behaviour says otherwise: a file with the placeholder
artist and no id, once tagged, releases its song too, and so does a file with no tags (the probe's two worlds below). The fix is not three corrected sentences but ONE table
(`rehome.HOLDS`: the reason, what lets the song go, and whether tagging does) that the log line of the pass and the audit's FAIL line are made from, and these tests tie the
table to what the pass does and the sentences to the table, so a sentence cannot say what the pass does not.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from encore_server import rehome, rekey_audit
from encore_server.db import Database
from encore_server.scanner import link_library
from tests.test_rehome import DUP, LOG, OTHER, SELF, Music, add_file, add_ref, listed, make_world, own, song, worklist

K1 = ("كيفك إنت", "فيروز")
K2 = ("حبيتك بالصيف", "فيروز")
ISRC = "QZ1234567890"

#: One world per reason: SELF holds ONE library file whose verdict is that reason, and the listing of the same file after the Host TAGGED it (`None`: the file is already
#: tagged the way the Host can; tagging has nothing to add, so the listing is the same).
Scenario = Callable[[sqlite3.Connection], tuple[dict[str, Any], dict[str, Any] | None]]


def untagged(c: sqlite3.Connection) -> tuple[dict[str, Any], dict[str, Any] | None]:
    add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
    bare = song("nd-1", "", "")
    add_file(c, SELF, "nd-1", song=bare)
    return bare, song("nd-1", *K1)


def nameless(c: sqlite3.Connection) -> tuple[dict[str, Any], dict[str, Any] | None]:
    add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
    placeholder = song("nd-1", K1[0], "[Unknown Artist]")
    add_file(c, SELF, "nd-1", song=placeholder)
    return placeholder, song("nd-1", *K1)


def ambiguous(c: sqlite3.Connection) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """SELF fits the tags by name and a duplicate holds the id the tags carry: the review's case."""
    add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
    add_ref(c, DUP, K1[0], [K1[1]], old=False, duration_ms=200_000, isrc=ISRC)
    tags = song("nd-1", *K1, isrc=[ISRC])
    add_file(c, SELF, "nd-1", song=tags)
    return tags, None


def last_file(c: sqlite3.Connection) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The tags name another song and the file is the only one a liked song has."""
    add_ref(c, SELF, K1[0], [K1[1]], old=False, duration_ms=200_000)
    add_ref(c, OTHER, K2[0], [K2[1]], old=False, duration_ms=200_000)
    tags = song("nd-1", *K2)
    add_file(c, SELF, "nd-1", song=tags)
    own(c, "like", SELF)
    return tags, None


SCENARIOS: dict[str, Scenario] = {
    "untagged": untagged,
    "nameless": nameless,
    "ambiguous": ambiguous,
    "last_file": last_file,
}


def held_world(db: Database, kind: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    made: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    def build(c: sqlite3.Connection) -> None:
        made.append(SCENARIOS[kind](c))

    make_world(db, build)
    listed(db, SELF)
    return made[0]


def test_the_table_has_one_row_per_reason_a_ref_can_be_held_for() -> None:
    assert [hold.kind for hold in rehome.HOLDS] == list(SCENARIOS), (
        "a new reason to hold a ref needs a row, a scenario here and a sentence in docs/18"
    )
    assert {hold.kind for hold in rehome.HOLDS} == set(rehome._UNDECIDED)  # noqa: SLF001


@pytest.mark.parametrize("kind", list(SCENARIOS))
def test_the_table_says_what_the_pass_does_when_the_file_is_tagged(db: Database, kind: str) -> None:
    """PROBE 5: tagging a file with the placeholder artist, and a file with no tags, releases the ref (the old sentences said it frees only the first reason); for the two
    reasons where the tags are already right, tagging the file the way a Host can changes nothing, and the ref stays held."""
    before, after = held_world(db, kind)

    held = link_library(db, Music([before]))

    assert worklist(db) == {SELF} and held.rehome is not None and held.rehome.held_undecided == 1, f"{kind}: the ref is held"

    link_library(db, Music([after if after is not None else before]))

    (hold,) = [h for h in rehome.HOLDS if h.kind == kind]
    assert (worklist(db) == set()) is hold.tagging_frees, (
        f"{kind}: tagging {'frees' if hold.tagging_frees else 'does not free'} the ref according to the table, and the pass disagrees"
    )


def test_what_the_table_says_lets_each_ref_go_is_what_lets_it_go_for_the_two_reasons_tagging_does_not_free(db: Database) -> None:
    """The other half of the sentence: the remedy the table names for a song that fits as well as another (the id taken out of the tags, or the file removed) really frees it."""
    before, _after = held_world(db, "ambiguous")
    link_library(db, Music([before]))
    assert worklist(db) == {SELF}

    link_library(
        db, Music([song("nd-1", *K1)])
    )  # the id is taken out of its tags: the song and its duplicate both name the file; it is kept

    assert worklist(db) == set()


def test_the_table_agrees_with_itself_the_prose_of_each_row_says_what_its_flag_says() -> None:
    for hold in rehome.HOLDS:
        assert ("tagging cannot help" in hold.frees) is (not hold.tagging_frees), hold.kind
        assert hold.frees.startswith("the Host tags the file") is hold.tagging_frees, hold.kind


def test_the_log_line_of_the_pass_is_made_from_the_table(db: Database, caplog: pytest.LogCaptureFixture) -> None:
    before, _ = held_world(db, "nameless")

    with caplog.at_level(logging.INFO, logger=LOG):
        link_library(db, Music([before]))

    lines = [r.getMessage() for r in caplog.records if r.name == LOG and "could not be judged or safely moved" in r.getMessage()]
    assert len(lines) == 1 and SELF in lines[0] and lines[0].endswith(rehome.what_frees())
    for hold in rehome.HOLDS:
        assert hold.why in lines[0] and hold.frees in lines[0]


def test_the_audit_fail_line_is_made_from_the_table_and_the_probe5_world_is_what_it_describes(db: Database) -> None:
    """The audit prints the same sentence; and the world it reports (a nameless file, held) is released by tagging, as the sentence says."""
    before, after = held_world(db, "nameless")
    link_library(db, Music([before]))

    with db.read() as conn:
        problems = rekey_audit.audit(conn).problems()
    (line,) = [p for p in problems if "still on the worklist" in p]
    assert line.endswith(rehome.what_frees())

    assert after is not None
    link_library(db, Music([after]))
    with db.read() as conn:
        assert not [p for p in rekey_audit.audit(conn).problems() if "worklist" in p], (
            "tagged: the worklist is empty and the audit has nothing to say of it"
        )


def test_no_sentence_of_the_code_says_that_tagging_frees_only_the_first_reason() -> None:
    """The three false sentences of the first build, by their words (the log line, the module text and the FAIL line of the audit)."""
    for module in (rehome, rekey_audit):
        text = Path(module.__file__).read_text(encoding="utf-8")
        assert "tagging frees only" not in text, module.__name__
        assert "only for the first reason" not in text, module.__name__
