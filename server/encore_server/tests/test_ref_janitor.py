"""N-27 slice 2a (B-131, B-126): the janitor that retires song refs nobody points at.

Slice 1 stopped browsing from making a song row. Rows that already exist, and the ones a real tap leaves behind (a tap on a song the server cannot find
makes its ref and nothing keeps it), stay for ever without this. The rule, in one sentence: a ref is retired when NOTHING points at it, it has no live
verdict (N-13), it never held a file, and it is itself older than 14 days. "Nothing points at it" means nobody among ALL the
people: another person's like, entry or play keeps the ref for everybody.

The data is SYNTHETIC (fixed ids, a fixed "now", invented songs): rows are written with SQL on purpose, so that each test builds exactly one reason to
keep a ref and the control next to it has none. Three kinds of test:

* the rule (each pointer keeps a ref; an unpointed old ref goes; the age, the verdict window, the batch);
* the guards that keep the rule honest later (every pointer is shown to be load-bearing by taking it away; the schema is compared with the list of
  pointers, so a table added by a later migration cannot be forgotten; no pointer table is read by scanning it);
* the wiring (the app runs the janitor as one of the errands of the hourly library link, and a failing pass changes nothing).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from encore_server import library, missing, ref_janitor, refs
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.ids import now_ms
from encore_server.missing import REASONS, WINDOW_MS, standing_of
from encore_server.navidrome import NavidromeClient
from encore_server.navidrome_admin import NavidromeAdmin
from encore_server.ref_janitor import AGE_MS, BATCH, POINTERS, RefJanitor
from encore_server.sources.youtube.scoring import MATCHER_REVISION

DAY = 24 * 3600 * 1000
HOUR = 3600 * 1000
NOW = 1_800_000_000_000  # the clock of every test: the janitor is given it, it never reads the wall clock
OLD = NOW - AGE_MS - DAY  # a ref made 15 days ago
FRESH = NOW - AGE_MS + HOUR  # a ref made 13 days and 23 hours ago

ME, YOU = "pn_00000000000000000000000001", "pn_00000000000000000000000002"
LIST = "pl_00000000000000000000000001"
IMPORT = "im_00000000000000000000000001"


def rid(n: int) -> str:
    """A well-formed song ref id with a number in it."""
    return f"sr_{n:026d}"


def add_ref(conn: sqlite3.Connection, n: int, created_at: int = OLD, **extra: Any) -> str:
    ref = rid(n)
    columns = {
        "id": ref,
        "title": f"Song {n}",
        "artists": json.dumps(["Nobody"]),
        "norm_key": f"nobody|song {n}",
        "created_at": created_at,
        **extra,
    }
    conn.execute(
        f"INSERT INTO song_ref ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", tuple(columns.values())
    )
    return ref


@pytest.fixture()
def world(db: Database) -> Database:
    """Two people, one playlist and one import for the rows below to hang from (the foreign keys are on)."""
    with db.tx() as conn:
        for person, name in ((ME, "me"), (YOU, "you")):
            conn.execute(
                "INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES (?,?,?,1)", (person, name, name)
            )
        conn.execute("INSERT INTO playlist (id, owner, name, created_at, updated_at) VALUES (?,?,?,1,1)", (LIST, ME, "mine"))
        conn.execute(
            "INSERT INTO import (id, person, source, name, created_at, updated_at) VALUES (?,?,?,?,1,1)",
            (IMPORT, ME, "file", "x"),
        )
    return db


def janitor(db: Database, **kwargs: Any) -> RefJanitor:
    return RefJanitor(db, clock=lambda: NOW, **kwargs)


def refs_left(db: Database) -> set[str]:
    with db.read() as conn:
        return {row["id"] for row in conn.execute("SELECT id FROM song_ref")}


# ------------------------------------------------------------------------------------------------ what points at a ref

Pointer = Callable[[sqlite3.Connection, str], None]


def _song_file(conn: sqlite3.Connection, ref: str) -> None:
    conn.execute("INSERT INTO song_file (id, ref, source, added_at) VALUES (?,?, 'library', 1)", (f"sf_{ref[3:]}", ref))


def _entry(conn: sqlite3.Connection, ref: str, *, removed: bool = False, person: str = ME) -> None:
    conn.execute(
        "INSERT INTO playlist_entry (id, playlist, position, ref, added_by, at, deleted_at) VALUES (?,?,1.0,?,?,1,?)",
        (f"pe_{ref[3:]}", LIST, ref, person, 5 if removed else None),
    )


def _like(conn: sqlite3.Connection, ref: str, *, person: str = ME) -> None:
    conn.execute("INSERT INTO library_item (person, kind, target, at) VALUES (?, 'like', ?, 1)", (person, ref))


def _play(conn: sqlite3.Connection, ref: str) -> None:
    conn.execute("INSERT INTO play_event (id, person, ref, at, ms_played) VALUES (?,?,?,1,1000)", (f"pv_{ref[3:]}", ME, ref))


def _import_entry(conn: sqlite3.Connection, ref: str) -> None:
    conn.execute("INSERT INTO import_entry (import, position, ref) VALUES (?, 1, ?)", (IMPORT, ref))


def _saved_album(conn: sqlite3.Connection, ref: str) -> None:
    conn.execute("INSERT INTO saved_album_ref (person, album, ref) VALUES (?, 'cat:1', ?)", (ME, ref))


def _work(conn: sqlite3.Connection, ref: str, state: str) -> None:
    conn.execute(
        "INSERT INTO work_item (id, kind, ref, priority, state, next_try_at, created_at, updated_at) VALUES (?, 'prepare', ?, 1, ?, 1, 1, 1)",
        (f"wk_{ref[3:]}", ref, state),
    )


def _playing(conn: sqlite3.Connection, ref: str) -> None:
    conn.execute("INSERT INTO playback_state (person, ref, queue, updated_at) VALUES (?,?, '[]', 1)", (ME, ref))


def _queued(conn: sqlite3.Connection, ref: str) -> None:
    queue = json.dumps([rid(900), ref, rid(901)])
    conn.execute("INSERT INTO playback_state (person, ref, queue, updated_at) VALUES (?, NULL, ?, 1)", (YOU, queue))


def _survivor(conn: sqlite3.Connection, ref: str) -> None:
    conn.execute("INSERT INTO ref_merge (old_id, into_id, at) VALUES (?,?,1)", (rid(800), ref))


def _file_once_changed(conn: sqlite3.Connection, ref: str) -> None:
    """The ref held a file once (every attach and every prune writes a row), however long ago: here 100 days."""
    conn.execute("INSERT INTO file_log (ref, at) VALUES (?,?)", (ref, NOW - 100 * DAY))


#: scenario -> (what is written, the key of the clause in `POINTERS` that keeps the ref). Every clause has at least one scenario.
SCENARIOS: dict[str, tuple[Pointer, str]] = {
    "a kept or found file": (_song_file, "song_file"),
    "a playlist entry": (_entry, "playlist_entry"),
    "a REMOVED playlist entry (the key has no cascade)": (lambda c, r: _entry(c, r, removed=True), "playlist_entry"),
    "another person's playlist entry": (lambda c, r: _entry(c, r, person=YOU), "playlist_entry"),
    "a like": (_like, "like"),
    "another person's like": (lambda c, r: _like(c, r, person=YOU), "like"),
    "a play": (_play, "play_event"),
    "an import entry": (_import_entry, "import_entry"),
    "a saved release's song": (_saved_album, "saved_album_ref"),
    "work that is queued": (lambda c, r: _work(c, r, "queued"), "active_work"),
    "work that is running": (lambda c, r: _work(c, r, "running"), "active_work"),
    "the song being played": (_playing, "playback_state"),
    "a song inside somebody's queue (a JSON text)": (_queued, "queue"),
    "a survivor that older ids resolve to": (_survivor, "merge_survivor"),
    "a ref that once held a file (and has none now)": (_file_once_changed, "file_history"),
}


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_a_ref_something_points_at_stays_and_the_control_next_to_it_goes(world: Database, scenario: str) -> None:
    write, _ = SCENARIOS[scenario]
    with world.tx() as conn:
        pointed = add_ref(conn, 1)
        control = add_ref(conn, 2)
        write(conn, pointed)

    retired = janitor(world).run_once()

    assert retired == 1
    assert refs_left(world) == {pointed}, f"{scenario}: the control ({control}) must go and the pointed ref must stay"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_clause_is_load_bearing_without_it_the_pointed_ref_would_be_retired(
    world: Database, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    """Without this a clause could be wrong (or deleted) and every test above would still pass because another clause happened to keep the ref. The
    foreign key is a second net under the tables that have no cascade: a pass that meets one of those rows is refused by it (and changes nothing, see
    below), which is also 'not kept by the clause'."""
    write, key = SCENARIOS[scenario]
    monkeypatch.setattr(ref_janitor, "POINTERS", {k: v for k, v in POINTERS.items() if k != key})
    with world.tx() as conn:
        pointed = add_ref(conn, 1)
        write(conn, pointed)

    try:
        janitor(world).run_once()
    except sqlite3.IntegrityError:
        return
    assert pointed not in refs_left(world), f"the clause {key!r} is not what keeps the ref in {scenario!r}"


def test_every_scenario_names_a_clause_and_every_clause_has_a_scenario() -> None:
    assert {key for _, key in SCENARIOS.values()} == set(POINTERS)


# ------------------------------------------------------------------------------------------------ the rule itself


def test_an_old_ref_nobody_points_at_goes_and_a_young_one_stays(world: Database) -> None:
    with world.tx() as conn:
        old = add_ref(conn, 1, OLD)
        fresh = add_ref(conn, 2, FRESH)

    assert janitor(world).run_once() == 1
    assert refs_left(world) == {fresh}
    assert old not in refs_left(world)


def test_the_age_is_exactly_fourteen_days_counted_from_the_ref_being_made(world: Database) -> None:
    assert AGE_MS == 14 * DAY
    with world.tx() as conn:
        on_the_line = add_ref(conn, 1, NOW - AGE_MS)
        one_older = add_ref(conn, 2, NOW - AGE_MS - 1)

    janitor(world).run_once()

    assert refs_left(world) == {on_the_line}, f"{one_older} is one millisecond past the line and goes; the line itself stays"


def test_a_second_pass_finds_nothing(world: Database) -> None:
    with world.tx() as conn:
        add_ref(conn, 1)
        add_ref(conn, 2)

    assert janitor(world).run_once() == 2
    assert janitor(world).run_once() == 0


def test_the_pass_is_one_errand_that_returns_how_many_it_retired_and_says_so_once(
    world: Database, caplog: pytest.LogCaptureFixture
) -> None:
    with world.tx() as conn:
        add_ref(conn, 1)
        add_ref(conn, 2)
    with caplog.at_level(logging.INFO, logger="encore_server.ref_janitor"):
        assert janitor(world).run_once() == 2
        assert janitor(world).run_once() == 0

    lines = [r.getMessage() for r in caplog.records if r.name == "encore_server.ref_janitor"]
    assert lines == ["ref janitor: retired 2 song refs nobody points at"], (
        "one line for a pass that did something, none for one that did not"
    )


def test_the_default_clock_is_the_wall_clock(world: Database) -> None:
    with world.tx() as conn:
        add_ref(conn, 1, created_at=now_ms() - 20 * DAY)
        young = add_ref(conn, 2, created_at=now_ms() - DAY)

    assert RefJanitor(world).run_once() == 1
    assert refs_left(world) == {young}


# ------------------------------------------------------------------------------------------------ what is lost, and what is not


def test_a_like_that_was_taken_back_lets_the_ref_go_and_the_phone_is_still_told_it_was_removed(world: Database) -> None:
    """`change_log` is a log of 'this was touched', not a pointer: the feed reads the state from the tables, so a phone that was away learns
    `removed` for the song although the ref is gone. The janitor must NOT delete that log row (the phone would never learn)."""
    with world.tx() as conn:
        ref = add_ref(conn, 1)
        _like(conn, ref)
        conn.execute("INSERT INTO change_log (person, kind, target, at) VALUES (?, 'like', ?, 1)", (ME, ref))
        conn.execute("DELETE FROM library_item WHERE person = ? AND target = ?", (ME, ref))
        conn.execute("INSERT INTO change_log (person, kind, target, at) VALUES (?, 'like', ?, 2)", (ME, ref))

    assert janitor(world).run_once() == 1

    with world.read() as conn:
        feed = library.changes(conn, ME, 0)
        assert conn.execute("SELECT COUNT(*) AS n FROM change_log WHERE target = ?", (ref,)).fetchone()["n"] == 2
    assert [(like["ref"], like["removed"]) for like in feed["likes"]] == [(ref, True)]


def test_only_a_like_keeps_a_ref_a_saved_album_or_a_followed_artist_that_happens_to_share_the_text_does_not(
    world: Database,
) -> None:
    with world.tx() as conn:
        ref = add_ref(conn, 1)
        conn.execute("INSERT INTO library_item (person, kind, target, at) VALUES (?, 'saved_album', ?, 1)", (ME, ref))
        conn.execute("INSERT INTO library_item (person, kind, target, at) VALUES (?, 'follow_artist', ?, 1)", (ME, ref))

    assert janitor(world).run_once() == 1
    assert ref not in refs_left(world)


def test_work_that_is_over_does_not_keep_a_ref_and_goes_with_it(world: Database) -> None:
    """Finished, failed and cancelled work stays in `work_item`: counting it as a pointer would make every ref that was ever prepared immortal."""
    with world.tx() as conn:
        refs = [add_ref(conn, n) for n in (1, 2, 3)]
        for state, ref in zip(("done", "failed", "cancelled"), refs, strict=True):
            _work(conn, ref, state)

    assert janitor(world).run_once() == 3
    with world.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM work_item").fetchone()["n"] == 0


def test_a_queue_that_holds_other_songs_does_not_keep_this_one(world: Database) -> None:
    with world.tx() as conn:
        mine = add_ref(conn, 1)
        theirs = add_ref(conn, 2)
        conn.execute(
            "INSERT INTO playback_state (person, ref, queue, updated_at) VALUES (?, ?, ?, 1)",
            (ME, theirs, json.dumps([theirs, rid(77)])),
        )

    assert janitor(world).run_once() == 1
    assert refs_left(world) == {theirs} and mine not in refs_left(world)


def test_a_ref_that_once_held_a_file_stays_and_so_does_its_log_while_one_that_never_did_goes(world: Database) -> None:
    """The cost of what the janitor will not do (see `ref_janitor`): a ref whose file was removed is the only thing that can tell a phone that was away
    "no file". The junk it is for (taps, typing) never had a file and so has no log rows."""
    with world.tx() as conn:
        junk = add_ref(conn, 1)
        ex_file = add_ref(conn, 2)
        conn.execute("INSERT INTO file_log (ref, at) VALUES (?,?)", (ex_file, NOW - 30 * DAY))

    assert janitor(world).run_once() == 1

    assert refs_left(world) == {ex_file}, f"{junk} never held a file and goes"
    with world.read() as conn:
        assert [row["ref"] for row in conn.execute("SELECT ref FROM file_log")] == [ex_file]


def test_a_phone_that_was_away_for_weeks_is_still_told_that_a_song_has_no_file_any_more(world: Database) -> None:
    """The scenario that decides the rule. The owner removes a song: the prune writes a log row. Phone A syncs and drops the song. Phone B is away; the
    janitor passes more than 14 days later; B comes back with its OLD cursor. The files feed lists the ref with `file: null` (that is how B hears), which
    needs the ref to still exist: `files_since` skips a ref that is gone."""
    with world.tx() as conn:
        ref = add_ref(conn, 1)
        junk = add_ref(conn, 2)
        conn.execute("INSERT INTO song_file (id, ref, source, added_at) VALUES ('sf_1', ?, 'library', 1)", (ref,))
        refs.touch_file(conn, ref)  # the song was linked
    with world.read() as conn:
        phone_b_cursor = int(library.files_since(conn, 0)["cursor"])  # phone B read the feed here, and went away
    with world.tx() as conn:
        conn.execute("DELETE FROM song_file WHERE id = 'sf_1'")  # the owner removed the song from the music server: the prune
        refs.touch_file(conn, ref)

    assert janitor(world).run_once() == 1  # more than 14 days on (the ref is 15 days old)

    assert refs_left(world) == {ref}, f"{junk} was junk and went; the ref that once held a file stays"
    with world.read() as conn:
        feed = library.files_since(conn, phone_b_cursor)
    assert [(r["id"], r["file"]) for r in feed["refs"]] == [(ref, None)]


# ------------------------------------------------------------------------------------------------ the memory of songs the server cannot get (N-13)


def verdict(tried_ago: int, *, reason: str | None = "not_found", rev: int | None = MATCHER_REVISION) -> dict[str, Any]:
    return {"missing_reason": reason, "missing_at": NOW - tried_ago, "missing_tried_at": NOW - tried_ago, "missing_rev": rev}


def test_a_live_verdict_keeps_the_ref_for_its_window_and_an_expired_one_does_not(world: Database) -> None:
    """The verdict lives on the ref and saves a look-up at YouTube for everybody: deleting it forgets what it knows. After the window it is worth nothing."""
    with world.tx() as conn:
        live = add_ref(conn, 1, **verdict(WINDOW_MS - DAY))  # tried 6 days ago: believed for one more day
        edge = add_ref(conn, 2, **verdict(WINDOW_MS - 1))  # one millisecond left
        over = add_ref(conn, 3, **verdict(WINDOW_MS))  # the window ends the moment it is a full 7 days old
        expired = add_ref(conn, 4, **verdict(WINDOW_MS + DAY))
        other_matcher = add_ref(conn, 5, **verdict(HOUR, rev=MATCHER_REVISION + 1))
        no_revision = add_ref(conn, 6, **verdict(HOUR, rev=None))
        no_reason = add_ref(conn, 7, **verdict(HOUR, reason=None))

    janitor(world).run_once()

    assert refs_left(world) == {live, edge}, (
        f"over={over}, expired={expired}, other_matcher={other_matcher}, no_revision={no_revision}, no_reason={no_reason} must all go"
    )


def test_the_sql_and_missing_standing_of_never_disagree_about_what_is_live(world: Database) -> None:
    """ONE definition of 'a live verdict': the SQL is built from `missing`'s own constants, and this walks the boundaries of every part of it against
    `missing.standing_of` itself, so a change in either one that the other does not follow fails here."""
    reasons: list[str | None] = [*REASONS, None, "something_else"]
    revisions: list[int | None] = [MATCHER_REVISION, MATCHER_REVISION + 1, MATCHER_REVISION - 1, None]
    ages = [0, HOUR, WINDOW_MS - DAY, WINDOW_MS - 1, WINDOW_MS, WINDOW_MS + 1, WINDOW_MS + 5 * DAY, None]
    with world.tx() as conn:
        n = 0
        for reason in reasons:
            for rev in revisions:
                for age in ages:
                    n += 1
                    tried = None if age is None else NOW - age
                    add_ref(conn, n, missing_reason=reason, missing_at=tried, missing_tried_at=tried, missing_rev=rev)
    with world.read() as conn:
        rows = list(conn.execute("SELECT * FROM song_ref"))
    expected_kept = {row["id"] for row in rows if (s := standing_of(row, NOW)) is not None and s.live}

    janitor(world, batch=len(rows) + 1).run_once()

    assert refs_left(world) == expected_kept
    assert expected_kept and len(expected_kept) < len(rows), "the walk must cover both outcomes"


# ------------------------------------------------------------------------------------------------ the batch


def test_the_batch_is_five_hundred_and_what_is_left_goes_on_the_next_pass(world: Database) -> None:
    assert BATCH == 500
    with world.tx() as conn:
        for n in range(1, 502):
            add_ref(conn, n)

    assert janitor(world).run_once() == 500
    assert len(refs_left(world)) == 1
    assert janitor(world).run_once() == 1
    assert janitor(world).run_once() == 0


def test_the_batch_counts_only_refs_that_may_go_so_kept_ones_at_the_front_cannot_block_it(world: Database) -> None:
    """600 old refs with a live verdict (made EARLIER, so they would lead any list sorted by age), 600 old refs a person liked, and one that may go:
    it goes on the first pass. A limit applied before the exclusions would have looked at 500 refs it could not retire and given up for an hour."""
    with world.tx() as conn:
        for n in range(1, 601):
            add_ref(conn, n, OLD - 2 * DAY - n, **verdict(HOUR))
        for n in range(601, 1201):
            _like(conn, add_ref(conn, n, OLD - DAY - n))
        free = add_ref(conn, 5000)

    assert janitor(world).run_once() == 1
    assert free not in refs_left(world)
    assert len(refs_left(world)) == 1200


# ------------------------------------------------------------------------------------------------ keeping the list of pointers honest


def _foreign_keys_to_song_ref(db: Database) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    with db.read() as conn:
        tables = [
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        ]
        for table in tables:
            for fk in conn.execute(f"PRAGMA foreign_key_list({table})"):
                if fk["table"] == "song_ref":
                    found.add((table, fk["from"]))
    return found


def _every_column(db: Database) -> set[tuple[str, str]]:
    with db.read() as conn:
        tables = [
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        ]
        return {(table, col["name"]) for table in tables for col in conn.execute(f"PRAGMA table_info({table})")}


def test_every_column_that_names_a_song_ref_through_a_foreign_key_is_a_pointer_the_janitor_knows(db: Database) -> None:
    """A table added by a later migration that points at `song_ref` and is not in `ref_janitor.FOREIGN_KEY_POINTERS` fails here, not in production:
    the janitor would only learn it through a refused delete (or, with a cascade, by silently deleting the rows)."""
    assert _foreign_keys_to_song_ref(db) == set(ref_janitor.FOREIGN_KEY_POINTERS)


#: Columns that hold a song ref as plain text (no foreign key, so the schema cannot list them) are listed in `ref_janitor`; every column of the whole
#: schema whose NAME says it may hold a ref is made to be classified there. A new one with such a name fails until somebody decides what it is.
_LOOKS_LIKE_A_REF = {"ref", "target", "queue", "into_id", "old_id", "song", "track"}


def _looks_like_a_ref(column: str) -> bool:
    """By WHOLE words (`preferred` is not `ref`): the column, or one of the words between its underscores, is one of the names above."""
    return bool(({column} | set(column.split("_"))) & _LOOKS_LIKE_A_REF)


def test_every_column_that_may_hold_a_ref_by_its_name_is_classified_as_a_pointer_or_as_not_one(db: Database) -> None:
    classified = set(ref_janitor.FOREIGN_KEY_POINTERS) | set(ref_janitor.TEXT_POINTERS) | set(ref_janitor.NOT_POINTERS)
    looks = {
        (table, column)
        for table, column in _every_column(db)
        if _looks_like_a_ref(column) and table not in ("schema_migrations", "song_ref")
    }
    unclassified = looks - classified
    assert not unclassified, (
        f"decide for each: does it keep a ref alive (add it to POINTERS and the lists) or not (say why in NOT_POINTERS)? {sorted(unclassified)}"
    )
    assert not (set(ref_janitor.FOREIGN_KEY_POINTERS) & set(ref_janitor.NOT_POINTERS))


def test_every_listed_pointer_is_read_by_a_clause_and_every_listed_non_pointer_has_a_reason() -> None:
    for table, column in (*ref_janitor.FOREIGN_KEY_POINTERS, *ref_janitor.TEXT_POINTERS):
        assert any(f"{table}.{column}" in clause for clause in POINTERS.values()), (
            f"{table}.{column} is listed as a pointer but no single clause reads it"
        )
    for column, reason in ref_janitor.NOT_POINTERS.items():
        assert len(reason) > 20, f"{column}: say why it is not a pointer"


def test_no_table_that_points_at_a_ref_is_read_by_scanning_it(world: Database) -> None:
    """The pass asks every pointer table about every old ref: a table that is scanned each time makes the pass quadratic the day it has a million rows.
    Only `song_ref` itself (the one pass over the old refs) and `playback_state` (one row per person) may be scanned."""
    plan = ref_janitor.query_plan(world)
    scanned = {line.split("SCAN ", 1)[1].split()[0] for line in plan if "SCAN " in line}
    assert "r" in scanned, "the plan was not read: the pass over the old refs must show"
    assert scanned <= {"r", "playback_state"}, f"scanned: {scanned}\n" + "\n".join(plan)
    for table in (
        "song_file",
        "playlist_entry",
        "library_item",
        "play_event",
        "import_entry",
        "saved_album_ref",
        "ref_merge",
        "file_log",
    ):
        assert any(f"SEARCH {table} USING" in line for line in plan), f"{table} must be searched by an index\n" + "\n".join(plan)


# ------------------------------------------------------------------------------------------------ a pass that fails changes nothing


def test_a_pass_that_fails_changes_nothing_not_even_what_an_earlier_statement_deleted(
    world: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deletes of a pass are one transaction, however many statements they take. Here the chunk is ONE id, so the free ref is deleted by a
    statement of its own, and then the foreign key refuses the next (a clause was taken away and a play points at that ref): the free ref must be back."""
    monkeypatch.setattr(ref_janitor, "POINTERS", {k: v for k, v in POINTERS.items() if k != "play_event"})
    monkeypatch.setattr(ref_janitor, "_DELETE_CHUNK", 1)
    with world.tx() as conn:
        free = add_ref(conn, 1, OLD - DAY)  # the older one: deleted first
        pointed = add_ref(conn, 2)
        _play(conn, pointed)

    with pytest.raises(sqlite3.IntegrityError):
        janitor(world).run_once()

    assert refs_left(world) == {free, pointed}


# ------------------------------------------------------------------------------------------------ the app runs it


def test_the_app_runs_the_janitor_as_one_of_the_errands_before_the_library_link(tmp_path: Path) -> None:
    """Without this a janitor that nothing calls would pass every test above."""

    def music_server(request: httpx.Request) -> httpx.Response:
        answers: dict[str, dict[str, Any]] = {
            "getScanStatus.view": {"scanStatus": {"scanning": False}},
            "getArtists.view": {"artists": {"index": []}},
            "search3.view": {"searchResult3": {}},
        }
        return httpx.Response(
            200, json={"subsonic-response": {"status": "ok", **answers.get(request.url.path.rsplit("/", 1)[-1], {})}}
        )

    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://music.invalid",
        navidrome_admin_user="admin",
        navidrome_admin_password="pw",
        youtube=False,
        workers=False,
    )
    client = NavidromeClient(
        "http://music.invalid", "admin", "pw", client=httpx.Client(transport=httpx.MockTransport(music_server))
    )
    app = create_app(settings, navidrome=client, navidrome_admin=NavidromeAdmin("http://music.invalid", "", ""))
    services = app.state.services
    with services.db.tx() as conn:
        old = add_ref(conn, 1, created_at=now_ms() - 20 * DAY)
        young = add_ref(conn, 2, created_at=now_ms() - DAY)

    assert services.linker is not None
    services.linker.run_once()

    assert refs_left(services.db) == {young}, f"{old} is older than 14 days and nobody points at it"


def test_missing_is_still_the_one_place_that_says_what_a_live_verdict_is() -> None:
    """The janitor imports the window, the reasons and the revision from `missing`; it must not carry numbers of its own."""
    source = Path(ref_janitor.__file__).read_text(encoding="utf-8")
    assert "from .missing import" in source or "missing." in source
    assert str(WINDOW_MS) not in source and "7 * 24" not in source
    assert missing.WINDOW_MS == WINDOW_MS
