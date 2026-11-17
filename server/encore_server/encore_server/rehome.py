"""Re-pointing the files the old text fold glued onto the wrong song (P2-25 slice 4, audit B-37). The design is `docs/tasks/P2-songs-as-references.md`, section P2-25,
part 7 (step 2) and part 8 (what a split does to the feeds); the worklist it works through is filled by `keyrepair.py` (slice 3).

**What went wrong.** Until P2-25 a name in Arabic, Russian, Korean or Japanese folded to nothing, so the library scan found every such file by the same key `||` and
`attach_file` obeyed: ONE ref held five files of five songs. The scan then kept each file on the ref that held it "whatever the tags say" (`scanner.link_library`:
the keeper attached it on purpose), so preventing the damage repairs nothing. `keyrepair` gives every ref its right key and lists the damaged ones (`ref_recheck`);
this judges their files by their tags and moves the ones that belong to another song.

**What it is: re-pointing `song_file` rows, and nothing else.** A file stays exactly where it is on the Host's disk: this module never renames, moves, retags, writes
or deletes a file of the Host's own music library (a stranger's existing music folder: the product works beside it), and it imports nothing that could.
(`tests/test_rehome.py` proves it two ways: every Python-level write or delete under a real folder raises during a whole pass, and the source's own imports are read; the
second cannot see through a module it IS allowed to import, which is why the first exists.) Only a keeper's file under `Encore/` may ever be moved, and then by the
`refile` of N-34, never by this. Likes, playlist entries, plays, saved releases and the saved queue are never touched either: they stay on the ref that holds them, which
keeps the title the person saw, so no id disappears and there is no tombstone, no `ref_merge` row and no new feed (design part 8: the phone learns from the files feed it
already reads, where `files_since` returns the CURRENT state of both refs).

**Where it runs.** In the hourly library link (`scanner.link_library`), page by page, after the page's own link transaction has committed (a page's holders are read at
the top of its link transaction and the scan re-attaches a file by the ref that holds it: judging first would let the scan add a second row for a file just moved).
It cannot be a start-up step: `song_file.meta` holds no title or artist, the scan reads the tags anyway, and a start-up that waits for the music server is a start-up
that does not start. A pass is **paced** (one write transaction per `CHUNK` songs, never one for the library), **resumable** (each chunk commits; the worklist is emptied
only at the end of a COMPLETE pass, so a pass that stops, because the music server stopped answering or the process was killed, is simply done again), **idempotent**
(a second pass finds every file where its tags say) and **never stops the server or the scan** (a failure is one ERROR line and the link goes on without it).

**What is judged.** Every library row of a worklist ref (not only the one the scan's holder rule finds, which is the oldest row): a keeper's file (source `youtube` or
`quality`) is never judged, because the keeper attached it on purpose for the ref's own description. The row is judged by the tags of the song the pass reads, in this
order:

1. **Is this ref one of the refs those tags name?** `refs.matches` is the answer of `refs.find` and the other refs of the SAME tier of evidence: ids first (an ISRC the ref
   holds means the file IS that recording; when an id names a ref, only that ref counts), then the key of the artist and title with a compatible length, then the
   tombstones. If yes, the file STAYS. This is stricter than "does `find` return this ref": two refs of one song (the N-11 duplicates) are both right, and moving the
   file off the younger one because the older answers first would leave the younger ref, and its likes, without a file; the merge by file folds such a pair, the rehome
   never decides between them. (A change from the first draft of the design, which said "find returns THIS ref".)
2. **Otherwise it MOVES**: to the ref the tags name (an existing song) or to a new one (`refs.resolve` makes it, exactly as a fresh scan would). The row moves with its id,
   `added_at`, `meta` and `source` (a delete and a re-attach would lose them and open a window in which the feed says `file: null` and a phone could drop a download);
   if the target already holds the same file (the keeper's row), the wrong holder's row is dropped and the target's stays; one preferred file per ref is restored on both;
   `refs.touch_file` and `library.touch_ref_holders` tell the phones of both.
3. **The placeholder artist** (`[Unknown Artist]`, the Host's untagged file) is judged by ids ONLY: `refs.find` returns nothing for that name on purpose, and nothing must
   never read as another song. When no id names another ref the file stays (an untagged Arabic file stays on its own ref).
4. **A file whose tags give no usable title and artist** is not judged and stays (counted in the log). It does not keep its ref on the worklist: it can never be judged by
   anything, and holding the ref back for it would hold its pairs back for ever.

**The worklist and the hold.** At the end of a COMPLETE pass, a worklist ref is released (its row deleted) when every library row it holds is judged or gone (a file the
listing does not have was pruned by the same pass). A pass that only adds (`prune=False`, the one after a scan) cannot say a file is gone: a ref with a file it could not see
stays on the worklist, with a line that says so, and the hourly pass that prunes finishes the job. When rows were released, `refmerge.repair` runs in the SAME link, so a
pair that held one file with a worklist ref (held for `recheck_pending`) is judged by the normal rules now and not at the next restart. **`refmerge.repair` was written for
the start-up, before any thread; it now also runs with live threads.** That is safe because it is one `BEGIN IMMEDIATE` transaction (every other writer waits for it) and
every route reads a song id through `refs.canonical`; the cost is that a keeper job that holds the id of a merged-away ref in memory finds it gone when it finishes and
fails that one keep, which is retried (the janitor retires refs under a running keeper the same way).

**The copy** (`repair_copy.py`, the discipline the slice 3 repair ended on). ONE copy of the database, labelled `before-rehome`, before the first re-point of a pass;
none when nothing moves. The copy an attempt that did not finish took is reused; the prune is told which copies stay (the one just taken and the one the last COMMITTED
pass used) and never chooses by the order of file names; the write transaction checks that the copy exists and begins like a SQLite database before its first write, else
nothing is written and ONE error line says so; at most `repair_copy.KEEP_COPIES` are kept. The copy is recorded as used only by the pass that completes.

**What the log says**: counts and a few ref ids, never a title (a title is a person's data): the first `_LOG_MOVES` moves with the ids of the file and of both songs, then
a count.

STOP-GAP(P2-25 one-shot-repair, until 0.2.0): the whole module is a ONE-TIME repair of data the old fold made. It goes with the worklist when the worklist is empty on every
install the project knows and one release has passed (N-36); the rekey, the revision and the plan at every start stay.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import library, refmerge, refs, repair_copy, textnorm
from .db import Database
from .errors import ApiError
from .ids import now_ms

log = logging.getLogger("encore_server.rehome")

_BACKUP_LABEL = "before-rehome"
#: The copy an attempt took and has not finished with, and the copy the last COMMITTED pass used (see `repair_copy.py`): this repair's OWN two settings, so it never
#: reuses or spends the copy of the key rewrite.
BACKUP_PENDING_SETTING = "rehome_backup_pending"
BACKUP_USED_SETTING = "rehome_backup_used"
#: How many songs one write transaction judges at most: a pass over a library that collapsed on thousands of refs holds the database for a short time, many times.
CHUNK = 100
#: How many moves are written out one by one; the rest are counted.
_LOG_MOVES = 20

_KEEP, _MOVE, _STAY_UNTAGGED, _STAY_NAMELESS = "keep", "move", "untagged", "nameless"


@dataclass
class Report:
    """What a pass did. `moved` counts the files that left the ref they were glued to (`dropped` of them as a row that the target already held: the target's stays)."""

    judged: int = 0
    kept: int = 0
    moved: int = 0
    new_refs: int = 0
    dropped: int = 0
    #: Tags with an artist that is the placeholder for "nobody": judged by ids only, and no id named another ref.
    stayed_nameless: int = 0
    #: Tags with no usable title or artist: not judged, they stay.
    stayed_untagged: int = 0
    #: A row that was not where the pass read it (another writer moved or removed it in between).
    changed: int = 0
    #: Worklist rows the pass deleted: refs whose every library file is judged or gone.
    released: int = 0
    #: Worklist refs with a library file the pass did not see (a pass that only adds): they stay on the worklist.
    held_back: int = 0
    #: Worklist rows of refs that no longer exist.
    gone: int = 0
    failed: bool = False
    #: The copy this pass relied on; `None` when nothing moved.
    backup: Path | None = None


@dataclass(frozen=True)
class _Verdict:
    kind: str
    item: dict[str, Any] | None = None
    #: The ids of the refs the tags name (the first tier of evidence): empty when the move is to a NEW song.
    answers: tuple[str, ...] = ()


Describe = Callable[[dict[str, Any]], dict[str, Any] | None]


def _copy_for_this_pass(db: Database) -> Path:
    """The copy of the database this pass is backed by (`repair_copy.copy_for_repair`). Kept under this name because the pass calls it and the tests replace it."""
    return repair_copy.copy_for_repair(
        db,
        label=_BACKUP_LABEL,
        pending_key=BACKUP_PENDING_SETTING,
        used_key=BACKUP_USED_SETTING,
        log=log,
        what="rehome",
        noun="re-pointing",
    )


def begin(db: Database, describe: Describe) -> Rehome | None:
    """The judge of one library pass, or `None` when the worklist is empty (every install after the repair and every new library: the pass costs one query).
    [describe] is `scanner.described` (given, not imported: the scanner imports this module)."""
    textnorm.require_pinned_unicode()
    with db.read() as conn:
        listed = [row["ref"] for row in conn.execute("SELECT ref FROM ref_recheck ORDER BY ref")]
        if not listed:
            return None
        rows = conn.execute(
            "SELECT id, ref, navidrome_song_id FROM song_file WHERE source = 'library' AND navidrome_song_id IS NOT NULL"
            " AND ref IN (SELECT ref FROM ref_recheck)"
        ).fetchall()
    log.info(
        "rehome: %d songs on the worklist, %d of their library files are judged by their tags in this pass",
        len(listed),
        len(rows),
    )
    return Rehome(db, describe, listed, rows, began=now_ms())


class Rehome:
    """One library pass's judge: [page] for every page of the music server's songs (after the page was linked), then [finish] at the end of a complete pass."""

    def __init__(self, db: Database, describe: Describe, listed: list[str], rows: Sequence[sqlite3.Row], *, began: int) -> None:
        self._db = db
        self._describe = describe
        self._listed = listed
        self._began = began
        #: The library rows of the worklist refs as they were when the pass began: `{music server id: [(file row id, ref)]}` (two refs may hold one file).
        self._by_nd: dict[str, list[tuple[str, str]]] = {}
        for row in rows:
            self._by_nd.setdefault(row["navidrome_song_id"], []).append((row["id"], row["ref"]))
        self._judged: set[str] = set()
        self._copy: Path | None = None
        self._logged = 0
        self.report = Report()

    # ------------------------------------------------------------------------------------------------------------------ a page

    def page(self, songs: Sequence[dict[str, Any]]) -> None:
        """Judges the worklist files among these songs. Never raises: a failure is one ERROR line, the rest of the pass is skipped and the worklist is kept."""
        if self.report.failed or not self._by_nd:
            return
        wanted: list[tuple[str, str, dict[str, Any]]] = []
        for song in songs:
            for file_id, ref in self._by_nd.get(str(song.get("id") or ""), ()):
                if file_id not in self._judged:
                    wanted.append((file_id, ref, song))
        for start in range(0, len(wanted), CHUNK):
            try:
                self._chunk(wanted[start : start + CHUNK])
            except repair_copy.CopyMissing as missing:  # nothing was written: the transaction rolled back before its first write
                self._fail(
                    "REFUSED and changed nothing: the copy of the database it was to rely on (%s) is not there, or is not a database, at the moment of writing, and a pass "
                    "that cannot be undone from a copy does not run (the worklist is kept, and the next pass takes a new copy)",
                    missing,
                )
                return
            except Exception:  # noqa: BLE001 - the library link must go on whatever happens here; the chunk rolled back, the copy is kept
                self._fail(
                    "FAILED; the chunk it was in changed nothing and the worklist is kept (it is tried again at the next pass)%s",
                    self._where(),
                    exc=True,
                )
                return

    def _where(self) -> str:
        return f"; the copy taken before it is {self._copy}" if self._copy else ""

    def _fail(self, message: str, *args: object, exc: bool = False) -> None:
        self.report.failed = True
        log.error("rehome " + message, *args, exc_info=exc)

    def _chunk(self, wanted: list[tuple[str, str, dict[str, Any]]]) -> None:
        with self._db.read() as conn:
            verdicts = [(file_id, ref, song, self._decide(conn, ref, song)) for file_id, ref, song in wanted]
        moves = [(file_id, ref, song) for file_id, ref, song, verdict in verdicts if verdict.kind == _MOVE]
        outcome = Report()
        moved: list[tuple[str, str, str]] = []
        if moves:
            copy = self._copy_taken()
            with self._db.tx() as conn:
                repair_copy.require_copy(
                    copy
                )  # the second layer: before the first write of this transaction, and so of every chunk
                for file_id, ref, song in moves:
                    result = self._move(conn, file_id, ref, song)
                    if result is None:
                        outcome.changed += 1
                        continue
                    kept, target, created, dropped = result
                    if kept:
                        outcome.kept += 1
                        continue
                    outcome.moved += 1
                    outcome.new_refs += int(created)
                    outcome.dropped += int(dropped)
                    moved.append((file_id, ref, target))
        # committed: now (and only now) the pass has done this much
        report = self.report
        for _file_id, _ref, _song, verdict in verdicts:
            report.kept += verdict.kind == _KEEP
            report.stayed_nameless += verdict.kind == _STAY_NAMELESS
            report.stayed_untagged += verdict.kind == _STAY_UNTAGGED
        report.judged += len(verdicts)
        report.kept += outcome.kept
        report.moved += outcome.moved
        report.new_refs += outcome.new_refs
        report.dropped += outcome.dropped
        report.changed += outcome.changed
        self._judged.update(file_id for file_id, *_ in verdicts)
        for file_id, ref, target in moved:
            if self._logged < _LOG_MOVES:
                log.info("rehome: file %s of song %s now belongs to song %s", file_id, ref, target)
            self._logged += 1

    def _copy_taken(self) -> Path:
        if self._copy is None:
            self._copy = _copy_for_this_pass(self._db)
            self.report.backup = self._copy
        return self._copy

    # ------------------------------------------------------------------------------------------------------------------ one file

    def _decide(self, conn: sqlite3.Connection, ref: str, song: dict[str, Any]) -> _Verdict:
        """Keep, move or leave this file of [ref], judged by the song's tags (see the module's text). A read."""
        described = self._describe(song)
        if described is None:
            return _Verdict(_STAY_UNTAGGED)
        try:
            item = refs.parse_item(described)
        except ApiError:
            return _Verdict(_STAY_UNTAGGED)
        answers = tuple(str(row["id"]) for row in refs.matches(conn, item))
        if ref in answers:
            return _Verdict(_KEEP)
        if not answers and textnorm.is_unknown_artist(item["artists"][0]):
            return _Verdict(_STAY_NAMELESS)  # no id named another song, and "no name" is not a name: it stays where it is
        return _Verdict(_MOVE, described, answers)

    def _move(
        self, conn: sqlite3.Connection, file_id: str, ref: str, song: dict[str, Any]
    ) -> tuple[bool, str, bool, bool] | None:
        """Re-points one row, judged again against the state this transaction sees. `None`: the row is not where the pass read it. Otherwise
        `(kept after all, the target, a new song was made, the row was dropped)`."""
        row = conn.execute("SELECT id, ref, source, navidrome_song_id, path FROM song_file WHERE id = ?", (file_id,)).fetchone()
        if row is None or row["ref"] != ref or row["source"] != "library":
            return None
        verdict = self._decide(conn, ref, song)
        if verdict.kind != _MOVE or verdict.item is None:
            return True, ref, False, False
        target = str(
            refs.resolve(conn, verdict.item)["id"]
        )  # the ref the tags name, or a new one: what a fresh scan would have done
        twin = conn.execute(
            "SELECT id FROM song_file WHERE ref = ? AND id <> ? AND ((navidrome_song_id IS NOT NULL AND navidrome_song_id = ?) OR (path IS NOT NULL AND path = ?))",
            (target, file_id, row["navidrome_song_id"], row["path"]),
        ).fetchone()
        if twin is not None:
            conn.execute("DELETE FROM song_file WHERE id = ?", (file_id,))
        else:
            conn.execute("UPDATE song_file SET ref = ?, preferred = 0 WHERE id = ?", (target, file_id))
        refs.ensure_one_preferred(conn, target)
        refs.ensure_one_preferred(conn, ref)
        refs.clear_missing(
            conn, target
        )  # the server has a file of that song now: whatever was remembered about its absence is void
        for touched in (ref, target):
            refs.touch_file(conn, touched)
            library.touch_ref_holders(conn, touched)
        conn.execute("UPDATE ref_recheck SET moved = moved + 1 WHERE ref = ?", (ref,))
        return False, target, not verdict.answers, twin is not None

    # ------------------------------------------------------------------------------------------------------------------ the end of a complete pass

    def finish(self, *, release: bool = True) -> Report:
        """The end of a COMPLETE pass: the worklist rows of the refs whose every library file is judged or gone are deleted, and (with [release]) the pairs `refmerge`
        held for them are judged by the normal rules now. A pass that failed deletes nothing."""
        report = self.report
        if report.failed:
            self._summary()
            return report
        with self._db.tx() as conn:
            kept_back: list[str] = []
            for ref in self._listed:
                if not refs.ref_exists(conn, ref):
                    conn.execute("DELETE FROM ref_recheck WHERE ref = ?", (ref,))
                    report.gone += 1
                    continue
                # A library file that is on the ref now, was there before the pass began, and was not judged: the listing did not have it, and a pass that prunes would
                # have removed its row by now. (A file attached since the pass began is the link's own, found by its tags.)
                unseen = [
                    r["id"]
                    for r in conn.execute(
                        "SELECT id FROM song_file WHERE ref = ? AND source = 'library' AND navidrome_song_id IS NOT NULL AND added_at < ?",
                        (ref, self._began),
                    )
                    if r["id"] not in self._judged
                ]
                if unseen:
                    kept_back.append(ref)
                    continue
                conn.execute("DELETE FROM ref_recheck WHERE ref = ?", (ref,))
                report.released += 1
            report.held_back = len(kept_back)
            if self._copy is not None:  # the pass completed: the copy it took is spent, and a later real pass takes its own
                repair_copy.mark_used(conn, pending_key=BACKUP_PENDING_SETTING, used_key=BACKUP_USED_SETTING, copy=self._copy)
        for ref in kept_back[:_LOG_MOVES]:
            log.info(
                "rehome: song %s stays on the worklist: a library file of it was not in the music server's listing of this pass",
                ref,
            )
        self._summary()
        if release and report.released:
            refmerge.repair(self._db)
        return report

    def _summary(self) -> None:
        r = self.report
        if self._logged > _LOG_MOVES:
            log.info("rehome: and %d more files re-pointed", self._logged - _LOG_MOVES)
        log.info(
            "rehome: %d files judged by their tags: %d kept, %d files re-pointed to other songs (%d new songs made, %d rows dropped because the song already held the file), "
            "%d stayed (no usable tags %d, no artist name and no id %d), %d changed hands meanwhile; %d songs released from the worklist, %d kept on it, %d no longer exist%s",
            r.judged,
            r.kept,
            r.moved,
            r.new_refs,
            r.dropped,
            r.stayed_nameless + r.stayed_untagged,
            r.stayed_untagged,
            r.stayed_nameless,
            r.changed,
            r.released,
            r.held_back,
            r.gone,
            "; the pass failed, so the worklist is kept as it was" if r.failed else "",
        )
