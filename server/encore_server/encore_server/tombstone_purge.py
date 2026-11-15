"""Tombstones and old import lists are purged, so that the songs they named can be retired (N-31 = N-27 slice 2d; docs/18 "Song refs nobody points at").

The janitor (`ref_janitor.py`) keeps a song ref while ANY row names it, and two kinds of row named refs for ever: a REMOVED playlist entry (it stays as a
tombstone, because a phone that was away learns the removal from it, and the foreign key has no cascade) and an `import_entry` (there is no way to delete an
import). So the refs of a deleted playlist and of every import stayed for ever (VM 108, 14 Nov 2026: the 29 refs of a deleted test playlist). The janitor's
rule is not changed. What goes away is the reason to keep: after a time the rows themselves are purged, then the janitor retires the refs nothing else points
at, and `ref_gone` tells the phones.

**What is purged** (the two kinds are rules by name, so that a test shows each one is load-bearing):

* a playlist entry removed more than 90 days ago (`removed_entry`), and every entry of a playlist deleted more than 90 days ago
  (`entry_of_deleted_playlist`);
* the entries of an import that finished (done, stopped or failed) more than 60 days ago (`IMPORT_RULES`), after its counts were stored on the import row
  in the same transaction. An import that is still running is never touched: its songs are being matched.

**What is NEVER purged**: a `playlist` row. A deleted playlist's row is its tombstone: it holds no ref (about a hundred bytes), the phone still gets the whole
`{..., deleted: true}` row from it, a second "bring over my library" finds the source playlist by `playlist.source_id` there (without the row the playlist
the person deleted would come back), `import.playlist` has a foreign key to it with no cascade, and a create retried by a long-offline phone still answers
with the deleted row. The same precedent as `ref_gone` and `ref_merge`: a tiny tombstone is kept for ever; what is bounded is what keeps a ref alive.

**Why an away phone stays correct**: the `change_log` rows are never deleted. A phone that was away reads the rows after its cursor, and for an entry whose
row is gone the feed answers `{id, playlist, deleted: true}` (the playlist comes from `change_log.parent`, migration 0016): the 90 days are a margin of
support, not what keeps the phone correct. **If `change_log` is ever pruned this stops being true** (a phone whose cursor is older than the oldest row would
miss deletions) and that prune must come with a way for a phone to learn its cursor is too old. `library.changes` says so where it answers.

**How it runs**: one more errand of the hourly library link, BEFORE the janitor (so that the first hour after the 90 days retires the refs too), at most
`BATCH` entries and `IMPORT_BATCH` imports a pass, everything in ONE transaction (a pass that fails changes nothing). A second pass changes nothing.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from typing import Any, NamedTuple

from .db import Database
from .ids import now_ms
from .imports.service import counts_of

log = logging.getLogger("encore_server.tombstone_purge")

DAY_MS = 24 * 3600 * 1000
#: How long a removed entry, or the entries of a deleted playlist, are kept. A margin for support: correctness for an away phone does not depend on it.
ENTRY_AGE_MS = 90 * DAY_MS
#: How long after it finished an import keeps its songs (its counts are kept for ever).
IMPORT_AGE_MS = 60 * DAY_MS
#: How many entries one pass purges at most (the hourly pass catches up with a backlog in a few hours and never holds the database for long).
BATCH = 5000
#: How many imports one pass purges at most.
IMPORT_BATCH = 50
#: How many ids one DELETE names (SQLite refuses too many variables in one statement).
_DELETE_CHUNK = 500

#: The entries that go, by name: a query for their ids. `:cutoff` is the age line, `:batch` the limit. Each is read through a partial index of the tombstones
#: (migration 0016), never by scanning the playlists or their entries.
ENTRY_RULES: dict[str, str] = {
    "removed_entry": (
        "SELECT id FROM playlist_entry WHERE deleted_at IS NOT NULL AND deleted_at < :cutoff ORDER BY deleted_at, id LIMIT :batch"
    ),
    "entry_of_deleted_playlist": (
        "SELECT e.id AS id FROM playlist p JOIN playlist_entry e ON e.playlist = p.id"
        " WHERE p.deleted_at IS NOT NULL AND p.deleted_at < :cutoff ORDER BY p.deleted_at, e.id LIMIT :batch"
    ),
}

#: What an import must be for its songs to go, by name: every condition holds (`import i` is the import asked about).
IMPORT_RULES: dict[str, str] = {
    "finished": "i.state IN ('done', 'stopped', 'failed')",
    "sixty_days": "i.updated_at < :cutoff",
    # Without this a second pass would store the counts again, from entries that are no longer there: zeros over the real numbers.
    "not_yet_purged": "i.entries_purged_at IS NULL",
}


class Purged(NamedTuple):
    """What one pass removed: playlist entries, and imports whose songs were removed."""

    entries: int
    imports: int


def _chunks(items: Sequence[str]) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), _DELETE_CHUNK):
        yield items[start : start + _DELETE_CHUNK]


def _import_select() -> str:
    where = " AND ".join(IMPORT_RULES.values()) or "1"
    return f"SELECT i.id AS id FROM import i WHERE {where} ORDER BY i.updated_at, i.id LIMIT :batch"  # noqa: S608 - the rules are constants above


def query_plan(db: Database) -> list[str]:
    """What SQLite says it will do for each rule's query (for the test that refuses a scan of the playlists or their entries)."""
    params = {"cutoff": 0, "batch": BATCH}
    with db.read() as conn:
        return [
            f"{name}: {row['detail']}"
            for name, sql in ENTRY_RULES.items()
            for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params)
        ]


class TombstonePurge:
    """Purges old tombstones and old import lists (see the module's text). [run_once] is the errand; the clock is given so that a test says what time it is."""

    def __init__(
        self,
        db: Database,
        *,
        clock: Callable[[], int] = now_ms,
        entry_age_ms: int = ENTRY_AGE_MS,
        import_age_ms: int = IMPORT_AGE_MS,
        batch: int = BATCH,
        import_batch: int = IMPORT_BATCH,
    ) -> None:
        self._db = db
        self._clock = clock
        self._entry_age = entry_age_ms
        self._import_age = import_age_ms
        self._batch = batch
        self._import_batch = import_batch

    def run_once(self) -> Purged:
        """One pass. Nothing is written when there is nothing to purge."""
        now = self._clock()
        with self._db.tx() as conn:
            entries = self._purge_entries(conn, now)
            imports = self._purge_imports(conn, now)
        if entries or imports:
            log.info("tombstone purge: removed %d playlist entries and the songs of %d imports", entries, imports)
        return Purged(entries, imports)

    def _purge_entries(self, conn: sqlite3.Connection, now: int) -> int:
        params: dict[str, Any] = {"cutoff": now - self._entry_age, "batch": self._batch}
        found: dict[str, None] = {}  # in order, once each: an entry both removed and in a deleted playlist is one
        for sql in ENTRY_RULES.values():
            for row in conn.execute(sql, params):
                found.setdefault(row["id"])
        ids = list(found)[: self._batch]
        for chunk in _chunks(ids):
            conn.execute(f"DELETE FROM playlist_entry WHERE id IN ({', '.join('?' for _ in chunk)})", tuple(chunk))  # noqa: S608 - only placeholders
        return len(ids)

    def _purge_imports(self, conn: sqlite3.Connection, now: int) -> int:
        params: dict[str, Any] = {"cutoff": now - self._import_age, "batch": self._import_batch}
        ids = [row["id"] for row in conn.execute(_import_select(), params)]
        for import_id in ids:
            counts = counts_of(conn, import_id)
            # The counts first, in the same transaction as the delete: an import is never left with neither its songs nor its numbers.
            conn.execute(
                "UPDATE import SET entries_purged_at = ?, final_total = ?, final_matched = ?, final_unmatched = ?, final_pending = ?, final_kept = ?"
                " WHERE id = ?",
                (now, counts["total"], counts["matched"], counts["unmatched"], counts["pending"], counts["kept"], import_id),
            )
            conn.execute("DELETE FROM import_entry WHERE import = ?", (import_id,))
        return len(ids)
