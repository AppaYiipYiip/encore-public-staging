"""Song refs nobody points at are retired (N-27 slice 2a, audit B-131 and B-126; docs/18 "song_ref").

A tap on a song the server cannot find leaves its ref behind (the tap made it, nothing keeps it), and so did every pause between two letters in Search
before slice 1 (`EncoreInstantBackend.prepare` no longer makes a row). Nothing ever removed them. This is the permanent hygiene of the table: it clears
what exists and what real taps leave behind; the SOURCE of junk was removed in slice 1, so there is no removal trigger.

**The rule** (one sentence): a ref is retired when NOTHING points at it, it has no live verdict (N-13), nothing touched its files in the last 14 days, and
it is itself older than 14 days. "Nothing points at it" means nobody among ALL the people: another person's like, entry or play keeps the ref for
everybody. The age keeps a ref a tap has just made safe (resolve, then play within seconds), and a person who searched yesterday and taps today still
finds the ref.

**What points at a ref** is `POINTERS`, one named clause per reason, each an `EXISTS` question about one table. The list is compared with the schema by
`tests/test_ref_janitor.py` (every foreign key to `song_ref`, and every column whose NAME says it may hold a ref, must be classified here), and each
clause is shown to be load-bearing by taking it away. A missed pointer deletes a ref somebody still uses, so adding a table that names a ref means
adding its clause here: the test fails until you do.

**The verdict** (`missing.py`) is read with the very constants `missing.standing_of` uses (the reasons, the matcher's revision, the window), and a test
walks every boundary against `standing_of` itself, so there is ONE definition of "live". A ref with a live verdict stays for the length of its window,
because deleting it would forget what saves a look-up at YouTube for everybody.

**How it runs**: one more errand of the hourly library link (`api.create_app`, after the finders), at most `BATCH` refs a pass, the candidates chosen and
deleted in ONE transaction (so a like that arrives between the two cannot be lost), the `file_log` rows of the retired refs deleted in the same
transaction (that table has no foreign key, so nothing else would). The batch limit is applied AFTER every exclusion: refs that may not go never use it up.
It adds no column and no table: it only removes rows.

The foreign keys are a second net: a table that is not yet in `POINTERS` and has no cascade makes the delete fail, the whole pass rolls back and the
errand logs it (the library link carries on, see `LibraryLinker.run_once`); a table WITH a cascade would lose its rows silently, which is why the schema
comparison is a test and not a hope.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from .db import Database
from .ids import now_ms
from .missing import MATCHER_REVISION, REASONS, WINDOW_MS
from .refmerge import FOREIGN_KEY_COLUMNS

log = logging.getLogger("encore_server.ref_janitor")

#: How old a ref must be before it may go, and how long after the last change of its files.
AGE_MS = 14 * 24 * 3600 * 1000
#: How many refs one pass retires at most (the hourly pass catches up with a long backlog in a few hours and never holds the database for long).
BATCH = 500

#: Every reason to keep a ref, by name: an `EXISTS` question about one table, `song_ref r` being the ref asked about. `:cutoff` is "now minus the age".
#: Tables are not aliased on purpose, so that the query plan names them (a test refuses a scan of any pointer table).
POINTERS: dict[str, str] = {
    "song_file": "SELECT 1 FROM song_file WHERE song_file.ref = r.id",
    "playlist_entry": "SELECT 1 FROM playlist_entry WHERE playlist_entry.ref = r.id",  # removed entries too: the key has no cascade
    "like": "SELECT 1 FROM library_item WHERE library_item.kind = 'like' AND library_item.target = r.id",
    "play_event": "SELECT 1 FROM play_event WHERE play_event.ref = r.id",
    "import_entry": "SELECT 1 FROM import_entry WHERE import_entry.ref = r.id",
    "saved_album_ref": "SELECT 1 FROM saved_album_ref WHERE saved_album_ref.ref = r.id",
    # Only work that is still to do or being done: finished, failed and cancelled items stay in the table, and counting them would make every ref that
    # was ever prepared immortal.
    "active_work": "SELECT 1 FROM work_item WHERE work_item.ref = r.id AND work_item.state IN ('queued', 'running')",
    "playback_state": "SELECT 1 FROM playback_state WHERE playback_state.ref = r.id",
    # The queue is a JSON array of ids in one text column. `instr` is an exact substring test (LIKE would read the `_` of an id as a wildcard); a
    # false "pointed at" can only keep a row longer.
    "queue": "SELECT 1 FROM playback_state WHERE instr(playback_state.queue, r.id) > 0",
    # A survivor of a merge: clients carry the old ids and resolve them through `ref_merge` to this one.
    "merge_survivor": "SELECT 1 FROM ref_merge WHERE ref_merge.into_id = r.id",
    # The age counts from the last change of the files too: a library file the music server lost an hour ago is not a song nobody wanted.
    "recent_file_change": "SELECT 1 FROM file_log WHERE file_log.ref = r.id AND file_log.at >= :cutoff",
}

#: The columns that name a ref through a foreign key (one list with the merge's: `refmerge` re-points exactly these, the janitor reads exactly these).
FOREIGN_KEY_POINTERS = FOREIGN_KEY_COLUMNS
#: The columns that name a ref as plain text, with no foreign key.
TEXT_POINTERS: frozenset[tuple[str, str]] = frozenset(
    {
        ("library_item", "target"),  # of kind 'like' (the other kinds hold a catalogue id)
        ("playback_state", "ref"),
        ("playback_state", "queue"),
        ("ref_merge", "into_id"),
    }
)
#: Columns a name says might hold a ref and that do NOT keep one alive, each with its reason.
NOT_POINTERS: dict[tuple[str, str], str] = {
    (
        "file_log",
        "ref",
    ): "A log of file changes, not a pointer: its rows are deleted with the ref; only a change in the last 14 days keeps it (recent_file_change).",
    (
        "change_log",
        "target",
    ): "A log of 'this was touched': the feed reads the state from the tables, so a retired ref is answered as removed; the rows stay so that a phone that was away still learns it.",
    (
        "ref_merge",
        "old_id",
    ): "The id of a ref that no longer exists: the tombstone clients fold the old id through; never deleted by the janitor.",
    ("song_file", "navidrome_song_id"): "The music server's own song id for the file, not a song ref.",
}


def _live_verdict() -> tuple[str, dict[str, Any]]:
    """`missing.standing_of(row, now).live` as SQL, built from the constants it uses. A NULL anywhere makes it NULL, which is read as 'not live'."""
    reasons = {f"reason{i}": reason for i, reason in enumerate(REASONS)}
    sql = (
        f"(r.missing_reason IN ({', '.join(':' + name for name in reasons)}) AND r.missing_rev = :rev"
        " AND :now < COALESCE(r.missing_tried_at, 0) + :window)"
    )
    return sql, {**reasons, "rev": MATCHER_REVISION, "window": WINDOW_MS}


def _select() -> tuple[str, dict[str, Any]]:
    """The candidates: old, nobody points at them, no live verdict; the limit comes after all of that."""
    verdict_sql, params = _live_verdict()
    keep = " AND ".join(f"NOT EXISTS ({sql})" for sql in POINTERS.values())
    sql = (
        "SELECT r.id FROM song_ref r WHERE r.created_at < :cutoff"
        f" AND NOT COALESCE({verdict_sql}, 0)" + (f" AND {keep}" if keep else "") + " ORDER BY r.created_at, r.id LIMIT :batch"
    )
    return sql, params


def query_plan(db: Database) -> list[str]:
    """What SQLite says it will do for the candidate query (for the test that refuses a scan of a pointer table)."""
    sql, params = _select()
    with db.read() as conn:
        rows = conn.execute("EXPLAIN QUERY PLAN " + sql, {**params, "cutoff": 0, "now": 0, "batch": BATCH})
        return [str(row["detail"]) for row in rows]


def _chunks(items: Sequence[str], size: int = 500) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class RefJanitor:
    """Retires the song refs nobody points at (see the module's text). [run_once] is the errand; the clock is given so that a test says what time it is."""

    def __init__(
        self,
        db: Database,
        *,
        clock: Callable[[], int] = now_ms,
        age_ms: int = AGE_MS,
        batch: int = BATCH,
    ) -> None:
        self._db = db
        self._clock = clock
        self._age = age_ms
        self._batch = batch

    def run_once(self) -> int:
        """One pass: returns how many refs were retired (0 when there was nothing to do, and then nothing is written)."""
        now = self._clock()
        sql, params = _select()
        params = {**params, "now": now, "cutoff": now - self._age, "batch": self._batch}
        with self._db.tx() as conn:
            ids = [row["id"] for row in conn.execute(sql, params)]
            for chunk in _chunks(ids):
                marks = ", ".join("?" for _ in chunk)
                conn.execute(f"DELETE FROM file_log WHERE ref IN ({marks})", tuple(chunk))
                # work_item (and work_item_person) go by their cascade: the rows left are over, the pointer clause counted only the active ones.
                conn.execute(f"DELETE FROM song_ref WHERE id IN ({marks})", tuple(chunk))
        if ids:
            log.info("ref janitor: retired %d song refs nobody points at", len(ids))
        return len(ids)
