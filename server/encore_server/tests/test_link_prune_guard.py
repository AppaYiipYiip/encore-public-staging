"""P3-33 (audit B-40): an empty or partial answer from the music server never wipes the library link.

A disk or NAS that is not mounted at boot, a restart in the middle of a scan, a music server that answers with nothing: the pass used to take an empty listing for the truth and remove every file link in
one go (the probe printed `file rows left=0`). A phone that synced in between then saw every song with no server copy and dropped its downloads; and when the music came back the links were made again
as library files, the keeper's own rows with their `youtube` source lost. Keeping a row of a file that is really gone costs nothing: a kept song whose file is gone streams from YouTube again (CF-31).

The rule: a pass that sees at least half of what is linked is trusted and removes what is absent at once (a Host deleting some files, as before); a pass that sees LESS removes nothing the first time,
only remembers when it first missed each file (`song_file.missing_since`), and removes a file only when it has been absent for a day and the music server lists something; a pass that sees NOTHING while
files are linked never removes anything. A file that is listed again forgets that it was missed.
"""

from __future__ import annotations

import pytest

from encore_server.config import Settings
from encore_server.db import Database
from encore_server.ids import now_ms
from encore_server.scanner import CONFIRM_AFTER_MS, LinkReport, link_library
from tests.test_scanner import FakeLibrary, entry

DAY = 24 * 3600 * 1000


def linked(db: Database, count: int) -> None:
    """A library of [count] songs linked by an ordinary pass."""
    link_library(db, FakeLibrary([entry(n) for n in range(count)]), prune=True)


def rows(db: Database) -> int:
    with db.read() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM song_file").fetchone()[0])


def missed(db: Database) -> dict[str, int | None]:
    with db.read() as conn:
        return {
            r["navidrome_song_id"]: r["missing_since"]
            for r in conn.execute("SELECT navidrome_song_id, missing_since FROM song_file")
        }


def age_the_misses(db: Database, by_ms: int) -> None:
    """Pretend the first miss was [by_ms] ago."""
    with db.tx() as conn:
        conn.execute("UPDATE song_file SET missing_since = missing_since - ? WHERE missing_since IS NOT NULL", (by_ms,))


def test_an_empty_answer_removes_no_file_link_however_often_it_comes(db: Database) -> None:
    """The audit's own probe: 300 links, the music server answers with nothing."""
    linked(db, 300)

    for _ in range(3):
        report = link_library(db, FakeLibrary([]), prune=True)
        assert report.pruned == 0 and report.held_back == 300 and report.complete

    assert rows(db) == 300
    age_the_misses(db, 10 * DAY)
    link_library(db, FakeLibrary([]), prune=True)
    assert rows(db) == 300, "even after days of nothing: a pass that sees nothing never removes anything"


def test_a_pass_that_sees_at_least_half_removes_what_is_absent_at_once(db: Database) -> None:
    """A Host who deletes some files: the same as before the guard."""
    linked(db, 10)

    report = link_library(db, FakeLibrary([entry(n) for n in range(6)]), prune=True)  # 6 of 10 seen

    assert report.pruned == 4 and report.held_back == 0 and rows(db) == 6


def test_a_pass_that_sees_less_than_half_removes_nothing_the_first_time_and_remembers_the_miss(db: Database) -> None:
    linked(db, 10)

    report = link_library(db, FakeLibrary([entry(n) for n in range(3)]), prune=True)  # 3 of 10 seen: a share is not mounted

    assert report.pruned == 0 and report.held_back == 7 and rows(db) == 10
    marks = missed(db)
    assert all(marks[f"nd-{n}"] is None for n in range(3)), "what is listed was not missed"
    assert all(marks[f"nd-{n}"] is not None and marks[f"nd-{n}"] <= now_ms() for n in range(3, 10))


def test_what_stays_absent_for_a_day_while_the_music_server_lists_something_is_removed(db: Database) -> None:
    linked(db, 10)
    partial = FakeLibrary([entry(n) for n in range(3)])
    link_library(db, partial, prune=True)

    link_library(db, partial, prune=True)  # an hour later, in effect: the same pass again, nothing aged
    assert rows(db) == 10
    age_the_misses(db, CONFIRM_AFTER_MS + 1)
    report = link_library(db, partial, prune=True)

    assert report.pruned == 7 and report.held_back == 0 and rows(db) == 3


def test_a_file_that_comes_back_forgets_that_it_was_missed(db: Database) -> None:
    linked(db, 10)
    link_library(db, FakeLibrary([entry(n) for n in range(3)]), prune=True)
    age_the_misses(db, CONFIRM_AFTER_MS + 1)

    link_library(db, FakeLibrary([entry(n) for n in range(10)]), prune=True)  # the disk is back

    assert rows(db) == 10 and all(v is None for v in missed(db).values())
    link_library(
        db, FakeLibrary([entry(n) for n in range(3)]), prune=True
    )  # a second outage starts the clock again, it does not inherit the first
    assert rows(db) == 10


def test_a_pass_that_adds_only_never_removes_and_never_marks(db: Database) -> None:
    """The pass after a scan (P3-35) only adds: it must neither prune nor start any clock."""
    linked(db, 10)

    link_library(db, FakeLibrary([entry(0)]), prune=False)

    assert rows(db) == 10 and all(v is None for v in missed(db).values())


def test_a_music_server_that_did_not_answer_changes_nothing(db: Database) -> None:
    linked(db, 10)
    down = FakeLibrary([])
    down.down = True

    report = link_library(db, down, prune=True)

    assert not report.complete and rows(db) == 10 and all(v is None for v in missed(db).values())


def test_a_file_the_keeper_attached_during_the_pass_is_not_judged(db: Database) -> None:
    """Unchanged by the guard: a row attached after the pass began is never pruned or marked."""
    linked(db, 4)
    with db.tx() as conn:
        conn.execute("UPDATE song_file SET added_at = ? WHERE navidrome_song_id = 'nd-3'", (now_ms() + 60_000,))

    link_library(db, FakeLibrary([entry(0)]), prune=True)  # 1 of 3 judged rows seen: not trusted

    assert missed(db)["nd-3"] is None


def test_the_report_says_how_many_files_were_held_back(db: Database) -> None:
    linked(db, 10)

    report: LinkReport = link_library(db, FakeLibrary([entry(0), entry(1)]), prune=True)

    assert (report.seen, report.pruned, report.held_back) == (2, 0, 8)


def test_a_library_reorganised_under_new_ids_is_a_library_not_an_outage(db: Database) -> None:
    """The music server lists a FULL library whose ids are all new (the Host moved the folders): the pass is trusted by what the music server listed, so the old rows go in THIS pass, and the next
    pass over the same listing writes nothing (the trust must not change from one pass to the next)."""
    linked(db, 10)
    reorganised = FakeLibrary([entry(n) for n in range(100, 110)])

    first = link_library(db, reorganised, prune=True)

    assert first.pruned == 10 and first.held_back == 0
    with db.read() as conn:
        ids = {r[0] for r in conn.execute("SELECT navidrome_song_id FROM song_file")}
        before = [tuple(r) for r in conn.execute("SELECT * FROM song_file ORDER BY id")]
    assert ids == {f"nd-{n}" for n in range(100, 110)}
    second = link_library(db, reorganised, prune=True)
    with db.read() as conn:
        after = [tuple(r) for r in conn.execute("SELECT * FROM song_file ORDER BY id")]
    assert second.pruned == 0 and second.held_back == 0 and after == before, "the same listing, trusted again, changes nothing"


# ---------------------------------------------------------------------------------------------------------------------- the review of #180: what Home and `encore status` say


def test_the_count_of_held_back_files_is_read_from_the_database_not_from_the_last_pass(db: Database) -> None:
    from encore_server.link_listing import held_back

    linked(db, 10)
    link_library(db, FakeLibrary([entry(n) for n in range(3)]), prune=True)  # an outage: 3 of 10 listed
    with db.read() as conn:
        assert held_back(conn) == (7, 10)

    link_library(
        db, FakeLibrary([entry(n) for n in range(3)]), prune=False
    )  # the add-only pass a rescan brings: it reports nothing held back itself

    with db.read() as conn:
        assert held_back(conn) == (7, 10), "the warning does not disappear between hourly passes while the disk is still missing"


def test_every_pass_forgets_the_misses_of_the_files_it_lists_also_the_pass_that_only_adds(db: Database) -> None:
    linked(db, 10)
    link_library(db, FakeLibrary([entry(n) for n in range(3)]), prune=True)

    link_library(
        db, FakeLibrary([entry(n) for n in range(10)]), prune=False
    )  # the disk is back; the pass after the rescan only adds

    assert all(v is None for v in missed(db).values()) and rows(db) == 10
    from encore_server.link_listing import held_back

    with db.read() as conn:
        assert held_back(conn) == (0, 10)


def test_a_pass_that_only_adds_never_removes_what_it_forgets_to_miss(db: Database) -> None:
    linked(db, 10)
    link_library(db, FakeLibrary([entry(n) for n in range(3)]), prune=True)
    age_the_misses(db, CONFIRM_AFTER_MS + 1)

    link_library(db, FakeLibrary([entry(n) for n in range(3)]), prune=False)

    assert rows(db) == 10, "only a pass that prunes removes, and only a day after the first miss"


def test_the_op_says_so_in_words_when_files_are_held_back_and_nothing_otherwise(
    db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    from encore_server.ops.cli import command

    settings = Settings(data_dir=db.path.parent)
    quiet = io.StringIO()
    assert command(["library", "--check"], settings=settings, out=quiet) == 0 and quiet.getvalue() == ""

    linked(db, 10)
    link_library(db, FakeLibrary([entry(0)]), prune=True)
    said = io.StringIO()
    assert command(["library", "--check"], settings=settings, out=said) == 0
    assert (
        "lists 1 of the 10 songs" in said.getvalue() and "Nothing was removed" in said.getvalue() and "mounted" in said.getvalue()
    )
