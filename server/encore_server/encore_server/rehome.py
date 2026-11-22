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
that does not start. A pass is **paced** (one write transaction per `CHUNK` songs judged and per `RELEASE_CHUNK` worklist rows released, never one for the library), **resumable** (each chunk
commits; the worklist is emptied only by a COMPLETE pass, so a pass that stops, because the music server stopped answering or the process was killed, is simply done again,
and one cut in the middle of the release is resumed by the next), **idempotent** (a second pass finds every file where its tags say) and **never stops the server or the scan**
(a failure is one ERROR line and the link goes on without it).

**What is judged.** Every library row of a worklist ref (not only the one the scan's holder rule finds, which is the oldest row): a keeper's file (source `youtube` or
`quality`) is never judged, because the keeper attached it on purpose for the ref's own description. The row is judged by the tags of the song the pass reads, in this
order:

**A wrong move is worse than none** (the lead's ruling of 17 Nov 2026, the same as N-34's best-of rule): a file is re-pointed ONLY when its current ref does NOT also fit it. In order:

1. **Is this ref one of the refs those tags name first?** `refs.matches` is the answer of `refs.find` and the other refs of the SAME tier of evidence: ids first (an ISRC the ref
   holds means the file IS that recording), then the key of the artist and title with a compatible length, then the tombstones. If yes, the file STAYS and is KEPT: two refs
   of one song (the N-11 duplicates) are both right, and moving the file off the younger one because the older answers first would leave the younger ref, and its likes, without
   a file; the merge by file folds such a pair, the rehome never decides between them.
2. **Does this ref fit the tags anyway?** (`refs.names_ref`.) When the tags name ANOTHER ref by stronger evidence (an ISRC) but this ref is also a plausible answer of any tier
   of `refs.candidates` (the same name; it absorbed a duplicate under that name), or its own key is the tags' key whatever its length says, the file STAYS, **its ref stays on the
   worklist** and ONE line (ids only) says why. The review's case: R (a like) holds the file, a duplicate X holds the ISRC the tags carry; the file used to be re-pointed R to X, R
   kept its like and had no file, and R and X share no file, so `refmerge` never folds them: permanent for the person who liked R. The length is left out of the second test on
   purpose (a length filled in later must not decide): the cost is that a longer cut of one song on one ref cannot be told apart and stays too.
3. **Is it the LAST file of a song a person owns?** (`ref_janitor.owned_by_people`: the janitor's own `POINTERS` without the files.) A like, an entry or a play on a song with no file
   is worse than one on a song with the wrong file, and nothing would ever put it right, so it STAYS, its ref stays on the worklist, one line says why. Asked inside the write
   transaction, after the earlier moves of the same chunk (the second of two moves stays). A song nobody owns moves its last file (the janitor retires it later).
4. **Otherwise it MOVES** (the tags name another song and this ref does not fit them): to the ref the tags name (an existing song) or to a new one (`refs.resolve` makes it, exactly
   as a fresh scan would). The row moves with its id, `added_at`, `meta` and `source` (a delete and a re-attach would lose them and open a window in which the feed says
   `file: null` and a phone could drop a download); if the target already holds the same file (the keeper's row), the wrong holder's row is dropped and the target's stays; one
   preferred file per ref is restored on both (`refs.ensure_one_preferred`, the newest row when there is none or several; **at the end of the pass the old song prefers a file
   judged KEPT or a keeper's, never one that stayed only because nobody could judge it**: read from `ref_recheck.moved`, committed with each move); `refs.touch_file` and
   `library.touch_ref_holders` tell the phones of both.
5. **The placeholder artist** (`[Unknown Artist]`, the Host's untagged file) is judged by ids ONLY: `refs.find` returns nothing for that name on purpose, and nothing must
   never read as another song. When no id names another ref the file stays (an untagged Arabic file stays on its own ref).
6. **A file whose tags give no usable title and artist** is not judged and stays (counted in the log). The music server LISTS it, so it is not gone: the prune keeps its row
   (`scanner._prune` removes the rows of files the listing lacks), also on the real hourly pass.

**A file that could not be judged, or safely moved, keeps its ref ON the worklist** (points 2, 3, 5 and 6, and the unseen file below): the ref's files may belong to other songs and
nobody could check, and merging identities on a file nobody could verify is exactly what the `recheck_pending` hold of `refmerge` exists to stop. The cost, stated: such a ref stays on
the worklist and every pair held for it stays held, so `rekey_audit` says FAIL for it, NAMING THE FILES (the visible reminder). What lets it go depends on why: a file with no usable
tags, or the placeholder artist with no id: the Host tags it or removes it; a song that fits the tags as well as another (R has no ISRC, X holds the one the tags carry): the file is
removed or the ISRC taken out of its tags (tagging cannot help, the tags are already right, and R and X share no file, so `refmerge` never folds them: the ref can stay for good); the
same name with another length: the song's stored length is corrected or the file is removed; the last file of a song a person owns: the song gains another file (the next pass then
moves the wrong one) or nobody owns it any more. On a Host where that never happens N-36's trigger (the worklist empty on every install) never fires there; the log says how many
files and why.

**The worklist and the hold.** At the end of a COMPLETE pass, a worklist ref is released (its row deleted) when every library row it holds was DECIDED (kept, or
re-pointed elsewhere) or is gone (a file the listing does not have was pruned by the same pass). A pass that only adds (`prune=False`, the one after a scan) cannot say a file is
gone: a ref with a file it could not see stays on the worklist, with a line that says so, and the hourly pass that prunes finishes the job; a ref with a file it could not judge
stays too. **The release is paced**: `RELEASE_CHUNK` rows per write transaction (200,000 refs in ONE held the write lock for 1.1 s, measured on a quiet machine, 3.0 s on a busy one; now at most
6 ms, 400 times; the price: the whole release takes 6.7 s instead of 1.2 s, because every transaction opens its own connection), each read inside its transaction. **The merge it owes is a durable debt** (`MERGE_PENDING_SETTING`), written in the SAME transaction as the first release, cleared only when
`refmerge.repair` ran and did not fail: the pairs it held for `recheck_pending` are judged by the normal rules at the end of the pass, and when it failed, or the process died, or the
worklist was already empty, the NEXT pass of the library link pays it (`pay_merge_debt`, from `idle` when there is no worklist), not only the next restart. **`refmerge.repair` was
written for the start-up, before any thread; it now also runs with live threads.** That is safe because it is one `BEGIN IMMEDIATE` transaction (every other writer waits for it) and
every route reads a song id through `refs.canonical`; the cost is that a keeper job that holds the id of a merged-away ref in memory finds it gone when it finishes and
fails that one keep, which is retried (the janitor retires refs under a running keeper the same way). **A pass that failed releases nothing, spends nothing and merges nothing.**

**The copy** (`repair_copy.py`, the discipline the slice 3 repair ended on). ONE copy of the database, labelled `before-rehome`, before the first re-point of a pass;
none when nothing moves. The copy an attempt that did not finish took is reused; the prune is told which copies stay (the one just taken and the one the last COMMITTED
pass used) and never chooses by the order of file names; the write transaction checks that the copy exists and begins like a SQLite database before its first write, else
nothing is written and ONE error line says so; at most `repair_copy.KEEP_COPIES` are kept. The copy is recorded as used only by the pass that completes (`repair_copy.settle`),
which also spends the record of an earlier attempt that did not finish when it itself took no copy (it found nothing to move), and `idle` does the same when the worklist
is empty (the pass that emptied it, or the janitor retiring the last ref on it, ended the attempt): left standing, the next change of the fold would reuse a copy taken before the
state of that day.

**What the log says**: counts and a few ref ids, never a title (a title is a person's data): the first `_LOG_MOVES` moves with the ids of the file and of both songs, then
a count.

STOP-GAP(P2-25 one-shot-repair; remove after 0.1.0): the whole module is a ONE-TIME repair of data the old fold made. It goes with the worklist when the worklist is empty on every
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
from .link_listing import Listing
from .ref_janitor import owned_by_people

log = logging.getLogger("encore_server.rehome")

_BACKUP_LABEL = "before-rehome"
#: The copy an attempt took and has not finished with, and the copy the last COMMITTED pass used (see `repair_copy.py`): this repair's OWN two settings, so it never
#: reuses or spends the copy of the key rewrite.
BACKUP_PENDING_SETTING = "rehome_backup_pending"
BACKUP_USED_SETTING = "rehome_backup_used"
#: The merge repair this repair OWES: written in the same transaction as the first release of a worklist ref (the pairs `refmerge` held for it have not been judged by the
#: normal rules yet), cleared only when `refmerge.repair` ran and did not fail. It is what lets the retry survive a restart, an unfinished pass and a failed repair.
MERGE_PENDING_SETTING = "rehome_merge_owed"
#: How many moves one write transaction applies at most: a pass over a library that collapsed on thousands of refs holds the database for a short time, many times.
CHUNK = 100
#: How many worklist rows one write transaction releases at most (each is read inside the transaction): a pass over 200,000 refs holds the write lock for the time of one
#: chunk, 500 rows, and not for the whole release at once (`docs/18`, "the rehome", has the measured figures).
RELEASE_CHUNK = 500
#: The rounds of one pass (see `Rehome._decide_and_apply`) end by themselves: a file moves at most once in a pass, so there are at most as many rounds as files plus one, and in
#: practice two or three. This is the second layer: a pass that reaches it says so, writes what it has, and the next pass goes on.
MAX_ROUNDS = 25
#: How many moves, and how many stays, are written out one by one (each kind has its own budget); the rest are counted.
_LOG_MOVES = 20

_KEEP, _MOVE, _STAY_UNTAGGED, _STAY_NAMELESS = "keep", "move", "untagged", "nameless"
#: The two stays of the review round (20 Nov 2026): the file's own ref fits its tags as well, or the ref is a person's and this is its last file.
_STAY_AMBIGUOUS, _STAY_LAST_FILE = "ambiguous", "last_file"
#: The row was not where the pass read it (another writer moved or removed it in between).
_CHANGED = "changed"
#: Every verdict that leaves the file where it is because nobody could decide: the ref STAYS on the worklist for each of them.
_UNDECIDED = (_STAY_UNTAGGED, _STAY_NAMELESS, _STAY_AMBIGUOUS, _STAY_LAST_FILE)
#: The two stays that a move of the same pass can lift (a file arrives on the song; a song that did not exist is made and carries the id): they are judged again in the next
#: round. Every other verdict is final: a move cannot make a file that fits its song stop fitting it, nor give a file with no tags any.
_JUDGED_AGAIN = (_STAY_NAMELESS, _STAY_LAST_FILE)


@dataclass(frozen=True)
class Hold:
    """Why a song stays on the worklist although its files were all judged, and what lets it go. **The ONE table**: the log line of the pass, the audit's FAIL line
    (`rekey_audit`) and the tests that pin them read it, so no sentence can say what the table does not; `docs/18` and the text of this module give the same table in
    prose."""

    kind: str
    why: str
    frees: str
    #: Does tagging the file (giving it a title and an artist, or an id) free the song? (Checked against the behaviour by `tests/test_rehome_held_text.py`.)
    tagging_frees: bool


HOLDS: tuple[Hold, ...] = (
    Hold(_STAY_UNTAGGED, "a file with no usable tags", "the Host tags the file or removes it", True),
    Hold(
        _STAY_NAMELESS,
        "a file with the placeholder artist and no id",
        "the Host tags the file (an artist name, or an id) or removes it",
        True,
    ),
    Hold(
        _STAY_AMBIGUOUS,
        "a song that fits the file's tags as well as another song (or has the same name with another length)",
        "the file is removed, or the id is taken out of its tags, or the song's stored length is corrected; the tags are already right, so tagging cannot help",
        False,
    ),
    Hold(
        _STAY_LAST_FILE,
        "the last file of a song a person owns",
        "the song gains another file (the next pass then moves the wrong one) or nobody owns it any more; tagging cannot help",
        False,
    ),
)


def what_frees() -> str:
    """The sentence the log of the pass and the audit say of a song that stays held, built from [HOLDS]: for each reason, what lets the song go."""
    return "; ".join(f"{hold.why}: {hold.frees}" for hold in HOLDS)


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
    #: The tags name another song, and the file's own ref fits them too (by an id, by its name, or by its name with another length): a wrong move is worse than none.
    stayed_ambiguous: int = 0
    #: The tags name another song and this is the last file of a song a person owns: a move would leave their like, entry or play on a song with no file.
    stayed_last_file: int = 0
    #: A row that was not where the pass read it (another writer moved or removed it in between).
    changed: int = 0
    #: Worklist rows the pass deleted: refs whose every library file is judged or gone.
    released: int = 0
    #: Worklist refs that stay on it: they hold a library file the pass did not see (a pass that only adds) or could not judge (`held_undecided` of them).
    held_back: int = 0
    held_undecided: int = 0
    #: Worklist rows of refs that no longer exist.
    gone: int = 0
    #: How many times the pass read the verdicts of the files a move can lift a stay of (at least one: every file is judged once).
    rounds: int = 0
    failed: bool = False
    #: The copy this pass relied on; `None` when nothing moved.
    backup: Path | None = None


@dataclass(frozen=True)
class _Verdict:
    kind: str
    item: dict[str, Any] | None = None
    #: The ids of the refs the tags name (the first tier of evidence): empty when the move is to a NEW song.
    answers: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Moved:
    """What became of one file: `kind` is a verdict kind (`_MOVE`, or the one that kept the file; `_CHANGED` for a row that was not where the pass read it). For a move the
    song it went to, whether that song was made by it, and whether the row was dropped because the song already held the file."""

    kind: str
    target: str = ""
    created: bool = False
    dropped: bool = False
    answers: tuple[str, ...] = ()
    #: The song the file was on when it was judged (for the log).
    origin: str = ""


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


def begin(db: Database, describe: Describe, listing: Listing) -> Rehome | None:
    """The judge of one library pass, or `None` when the worklist is empty (every install after the repair and every new library: the pass costs one query).
    [describe] is `scanner.described` (given, not imported: the scanner imports this module). [listing] is what the pass reads (`link_listing.Listing`): it is REQUIRED, because
    what counts as a file the song keeps is the listing's call and a default that counted every row would bring back the stranded like of audit probe 6."""
    textnorm.require_pinned_unicode()
    with db.read() as conn:
        listed = [row["ref"] for row in conn.execute("SELECT ref FROM ref_recheck ORDER BY ref")]
        if not listed:
            return None
        rows = conn.execute(
            "SELECT id, ref, navidrome_song_id, added_at FROM song_file WHERE source = 'library' AND navidrome_song_id IS NOT NULL"
            " AND ref IN (SELECT ref FROM ref_recheck)"
        ).fetchall()
    log.info(
        "rehome: %d songs on the worklist, %d of their library files are judged by their tags in this pass",
        len(listed),
        len(rows),
    )
    return Rehome(db, describe, listed, rows, listing)


class Rehome:
    """One library pass's judge: [page] for every page of the music server's songs (it only notes what the listing says), then [finish] at the end of a COMPLETE pass (it
    decides, moves and releases)."""

    def __init__(
        self, db: Database, describe: Describe, listed: list[str], rows: Sequence[sqlite3.Row], listing: Listing
    ) -> None:
        self._db = db
        self._describe = describe
        self._listed = listed
        self._listing = listing
        self._began = listing.began
        #: The library rows of the worklist refs as they were when the pass began: `{music server id: [(file row id, ref)]}` (two refs may hold one file).
        self._by_nd: dict[str, list[tuple[str, str]]] = {}
        #: When each of those rows was added: the order the pass judges them in (the oldest first), which is the same whatever the order of the listing.
        self._added: dict[str, int] = {}
        for row in rows:
            self._by_nd.setdefault(row["navidrome_song_id"], []).append((row["id"], row["ref"]))
            self._added[row["id"]] = row["added_at"]
        #: What the listing said of each worklist file, in the scan's words (`described`, `None` for tags nobody can use): `{file row id: (the ref it is on, its tags)}`. Held in
        #: memory until the listing is complete (about the size of one song's tags per worklist file, measured in docs/18).
        self._tags: dict[str, tuple[str, dict[str, Any] | None]] = {}
        #: What became of each worklist file the pass judged.
        self._outcome: dict[str, _Moved] = {}
        self._judged: set[str] = set()
        #: The files whose tags could not decide anything (no usable tags, no artist name and no id, a song that fits as well, the last file of a song somebody owns): they
        #: stay where they are and their ref stays on the worklist.
        self._undecided: set[str] = set()
        self._copy: Path | None = None
        self._logged = 0
        self._stays_logged = 0
        self.report = Report()

    # ------------------------------------------------------------------------------------------------------------------ a page

    def page(self, songs: Sequence[dict[str, Any]]) -> None:
        """Notes what the music server says of the worklist files among these songs. **It decides nothing and writes nothing**: the verdict of a file depends on the files the
        music server lists in the REST of the pass (the last-file guard counts only the files the listing has) and on the state the scan leaves, so it waits for the whole
        listing (`finish`). A pass that stops early therefore decides nothing and writes nothing."""
        if not self._by_nd:
            return
        for song in songs:
            for file_id, ref in self._by_nd.get(str(song.get("id") or ""), ()):
                if file_id not in self._tags:
                    self._tags[file_id] = (ref, self._describe(song))

    def _where(self) -> str:
        return f"; the copy taken before it is {self._copy}" if self._copy else ""

    def _fail(self, message: str, *args: object, exc: bool = False) -> None:
        self.report.failed = True
        log.error("rehome " + message, *args, exc_info=exc)

    # ------------------------------------------------------------------------------------------------------------------ the decisions

    def _decide_and_apply(self) -> None:
        """Judges every worklist file the listing showed against ONE state, applies the moves, and judges again the stays a move may have lifted, until a round moves nothing.

        **Round by round**: the verdicts of a round are all read from the same state (the database after the scan of this pass and its prune, plus the moves of the rounds
        before); the moves of the round are then applied in chunks, each move judged again inside its write transaction against the rows it sees (the second of two wrong
        files of a song somebody owns stays). What a move changes is decided in the SAME pass: a file that arrives on a liked song frees that song's other wrong file; a song
        a move makes carries the id of its file and names a nameless file of the same recording. The only stays that are judged again are those two kinds (`_JUDGED_AGAIN`):
        a move cannot make a file that fits its song stop fitting it (the length and the ids of a song that exists are never written by a move, `refs.resolve_keeping_identity`), nor give a file with no tags any. A file moves at most once, so the rounds end; `MAX_ROUNDS` is the second layer."""
        todo = sorted(self._tags, key=lambda file_id: (self._added[file_id], file_id))
        rounds = 0
        while todo:
            if rounds >= MAX_ROUNDS:
                log.error(
                    "rehome: stopped after %d rounds (rehome.MAX_ROUNDS); what is not decided stays where it is, its songs stay on the worklist and the next pass goes on",
                    rounds,
                )
                break
            rounds += 1
            moved = self._round(todo)
            todo = [file_id for file_id in todo if self._outcome[file_id].kind in _JUDGED_AGAIN] if moved else []
        self.report.rounds = rounds

    def _round(self, todo: list[str]) -> int:
        """One round over these files, oldest first: the number of files moved."""
        with self._db.read() as conn:
            verdicts = {file_id: self._decide(conn, file_id, *self._tags[file_id]) for file_id in todo}
        for file_id, verdict in verdicts.items():
            if verdict.kind != _MOVE:
                self._outcome[file_id] = _Moved(verdict.kind, answers=verdict.answers, origin=self._tags[file_id][0])
        moves = [file_id for file_id in todo if verdicts[file_id].kind == _MOVE]
        moved = 0
        for start in range(0, len(moves), CHUNK):
            copy = self._copy_taken()
            results: dict[str, _Moved] = {}
            with self._db.tx() as conn:
                # The second layer: before the first write of this transaction, and so of every chunk.
                repair_copy.require_copy(copy)
                for file_id in moves[start : start + CHUNK]:
                    ref, described = self._tags[file_id]
                    results[file_id] = self._move(conn, file_id, ref, described)
            # committed: now (and only now) the pass has done this much
            self._outcome.update(results)
            for file_id, result in results.items():
                if result.kind == _MOVE:
                    moved += 1
                    if self._logged < _LOG_MOVES:
                        log.info("rehome: file %s of song %s now belongs to song %s", file_id, result.origin, result.target)
                    self._logged += 1
        return moved

    def _decide(self, conn: sqlite3.Connection, file_id: str, ref: str, described: dict[str, Any] | None) -> _Verdict:
        """Keep, move or leave this file of [ref], judged by the song's tags (see the module's text). A read; `_move` asks it again inside its write transaction."""
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
        if refs.names_ref(conn, ref, item):
            return _Verdict(
                _STAY_AMBIGUOUS, answers=answers
            )  # the ref fits the tags too: the tags do not prove the file is in the wrong place
        # A song a person owns never loses its LAST file to a move: their like, entry or play would stay on a song with no file, and two songs that share no file are never
        # merged, so nothing would ever put it right. "Another file" is a file this pass keeps (`Listing.alive`: a row the prune of this pass removes is not one), asked
        # again inside the write transaction, after the earlier moves of the same chunk (the second of two wrong files stays).
        if not self._keeps_another_file(conn, ref, file_id) and owned_by_people(conn, ref):
            return _Verdict(_STAY_LAST_FILE)
        return _Verdict(_MOVE, described, answers)

    def _keeps_another_file(self, conn: sqlite3.Connection, ref: str, file_id: str) -> bool:
        """Does [ref] hold a file other than [file_id] that this pass leaves alive?"""
        return any(
            self._listing.alive(row["navidrome_song_id"], row["added_at"])
            for row in conn.execute("SELECT navidrome_song_id, added_at FROM song_file WHERE ref = ? AND id <> ?", (ref, file_id))
        )

    def _move(self, conn: sqlite3.Connection, file_id: str, ref: str, described: dict[str, Any] | None) -> _Moved:
        """Re-points one row, judged again against the state this transaction sees. `_CHANGED`: the row is not where the pass read it."""
        row = conn.execute("SELECT id, ref, source, navidrome_song_id, path FROM song_file WHERE id = ?", (file_id,)).fetchone()
        if row is None or row["ref"] != ref or row["source"] != "library":
            return _Moved(_CHANGED, origin=ref)
        verdict = self._decide(conn, file_id, ref, described)
        if verdict.kind != _MOVE or verdict.item is None:
            return _Moved(verdict.kind, answers=verdict.answers, origin=ref)
        # The ref the tags name, or a new one: what a fresh scan would have done, except that a ref that exists keeps its length and its ids (what the next file is judged by).
        target = str(refs.resolve_keeping_identity(conn, verdict.item)["id"])
        twin = conn.execute(
            "SELECT id FROM song_file WHERE ref = ? AND id <> ? AND ((navidrome_song_id IS NOT NULL AND navidrome_song_id = ?) OR (path IS NOT NULL AND path = ?))",
            (target, file_id, row["navidrome_song_id"], row["path"]),
        ).fetchone()
        if twin is not None:
            conn.execute("DELETE FROM song_file WHERE id = ?", (file_id,))
        else:
            conn.execute("UPDATE song_file SET ref = ?, preferred = 0 WHERE id = ?", (target, file_id))
        refs.ensure_one_preferred(conn, target, alive=self._listing.alive)
        # provisional for the old song: the end of the pass prefers a file judged kept (`_prefer_a_decided_file`)
        refs.ensure_one_preferred(conn, ref, alive=self._listing.alive)
        # The server has a file of that song now: whatever was remembered about its absence is void.
        refs.clear_missing(conn, target)
        for touched in (ref, target):
            refs.touch_file(conn, touched)
            library.touch_ref_holders(conn, touched)
        conn.execute("UPDATE ref_recheck SET moved = moved + 1 WHERE ref = ?", (ref,))
        return _Moved(_MOVE, target=target, created=not verdict.answers, dropped=twin is not None, origin=ref)

    def _account(self) -> None:
        """What the pass came to, counted once per file from the final outcome of each (a stay of the first round that a later round moved is a move)."""
        report = self.report
        stays = 0
        for file_id, result in self._outcome.items():
            report.judged += 1
            if result.kind == _MOVE:
                report.moved += 1
                report.new_refs += int(result.created)
                report.dropped += int(result.dropped)
                continue
            report.kept += result.kind == _KEEP
            report.stayed_nameless += result.kind == _STAY_NAMELESS
            report.stayed_untagged += result.kind == _STAY_UNTAGGED
            report.stayed_ambiguous += result.kind == _STAY_AMBIGUOUS
            report.stayed_last_file += result.kind == _STAY_LAST_FILE
            report.changed += result.kind == _CHANGED
            if result.kind in (_STAY_AMBIGUOUS, _STAY_LAST_FILE):
                self._say_why_it_stays(file_id, stays, result)
                stays += 1
            if result.kind in _UNDECIDED:
                self._undecided.add(file_id)
        self._judged = set(self._outcome)
        self._stays_logged = stays

    def _say_why_it_stays(self, file_id: str, number: int, result: _Moved) -> None:
        """ONE line for a file the pass leaves where it is for a reason a Host can act on (ids only: a title is a person's data); the first `_LOG_MOVES`, then a count."""
        if number >= _LOG_MOVES:
            return
        ref = result.origin
        if result.kind == _STAY_LAST_FILE:
            log.info(
                "rehome: file %s stays on song %s although the tags name another song: it is the last file of a song a person owns (a like, an entry, a play, a saved release "
                "or the queue), and a song with no file is worse than a song with the wrong one; the song stays on the worklist",
                file_id,
                ref,
            )
        elif result.answers:
            log.info(
                "rehome: file %s stays on song %s: the tags name song %s, but song %s names it as well (its own id or name), and a wrong move is worse than none; the song "
                "stays on the worklist",
                file_id,
                ref,
                ", ".join(result.answers),
                ref,
            )
        else:
            log.info(
                "rehome: file %s stays on song %s: its artist and title are the tags' and only its length differs (another recording of the song, or a length filled in "
                "later), and a wrong move is worse than none; the song stays on the worklist",
                file_id,
                ref,
            )

    def _copy_taken(self) -> Path:
        if self._copy is None:
            self._copy = _copy_for_this_pass(self._db)
            self.report.backup = self._copy
        return self._copy

    # ------------------------------------------------------------------------------------------------------------------ the end of a complete pass

    def finish(self, *, release: bool = True) -> Report:
        """The end of a COMPLETE pass: **everything is decided here**, against the state the listing and the scan of this pass leave, then the worklist rows of the refs whose
        every library file is judged or gone are deleted, `RELEASE_CHUNK` at a time (one write transaction each, so the write lock is never held for the whole worklist; a
        pass cut between two chunks is resumed by the next one), and (with [release]) the pairs `refmerge` held for them are judged by the normal rules now. **A pass that failed
        deletes nothing, spends nothing and merges nothing**: the worklist is emptied only by a complete pass."""
        if not self._listing.complete:
            raise RuntimeError(
                "the rehome decides only after the whole listing of the music server has been read; this pass is not complete"
            )
        report = self.report
        try:
            self._decide_and_apply()
        except repair_copy.CopyMissing as missing:  # nothing was written: the transaction rolled back before its first write
            self._fail(
                "REFUSED and changed nothing in that chunk: the copy of the database it was to rely on (%s) is not there, or is not a database, at the moment of writing, "
                "and a pass that cannot be undone from a copy does not run (the worklist is kept, and the next pass takes a new copy)",
                missing,
            )
        except Exception:  # noqa: BLE001 - the library link must go on whatever happens here; the chunk rolled back, the copy is kept
            self._fail(
                "FAILED; the chunk it was in changed nothing and the worklist is kept (it is tried again at the next pass)%s",
                self._where(),
                exc=True,
            )
        if report.failed:
            self._summary()
            return report
        self._account()
        kept_back: list[tuple[str, int, int]] = []
        for start in range(0, len(self._listed), RELEASE_CHUNK):
            part = self._listed[start : start + RELEASE_CHUNK]
            with self._db.tx() as conn:
                gone, released = self._release(conn, part, kept_back)
                if released:
                    # In the SAME transaction as the release: a process killed right after it still owes the merge repair (the pairs held for these refs are judged by the
                    # normal rules only now), and a failed repair, or a restart, is retried (`pay_merge_debt`).
                    conn.execute(
                        "INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)", (MERGE_PENDING_SETTING, str(now_ms()))
                    )
            report.gone += gone
            report.released += released
        report.held_back = len(kept_back)
        report.held_undecided = sum(1 for _ref, _unseen, n_undecided in kept_back if n_undecided)
        # the pass completed: the copy it took (or the unfinished attempt's it finished) is spent, and a later real pass takes its own
        with self._db.tx() as conn:
            repair_copy.settle(conn, pending_key=BACKUP_PENDING_SETTING, used_key=BACKUP_USED_SETTING, copy=self._copy)
        for ref, n_unseen, n_undecided in kept_back[:_LOG_MOVES]:
            if n_unseen:
                log.info(
                    "rehome: song %s stays on the worklist: %d of its library files were not in the music server's listing of this pass",
                    ref,
                    n_unseen,
                )
            if n_undecided:
                log.info(
                    "rehome: song %s stays on the worklist: %d of its library files could not be judged or safely moved, so the pairs held for it stay held. What lets it go: %s",
                    ref,
                    n_undecided,
                    what_frees(),
                )
        self._summary()
        if release:
            pay_merge_debt(self._db)
        return report

    def _release(self, conn: sqlite3.Connection, part: Sequence[str], kept_back: list[tuple[str, int, int]]) -> tuple[int, int]:
        """One chunk of the end of the pass, inside its write transaction: `(worklist rows of refs that no longer exist, rows released)`; a ref that stays is added to
        [kept_back] with how many of its files were not seen and how many could not be judged."""
        gone = released = 0
        for ref in part:
            if not refs.ref_exists(conn, ref):
                conn.execute("DELETE FROM ref_recheck WHERE ref = ?", (ref,))
                gone += 1
                continue
            # The library files that are on the ref now and were there before the pass began (a file attached since is the link's own, found by its tags). Two reasons to
            # keep the ref: one the listing did not have (not judged: a pass that prunes would have removed its row by now), and one the tags could not decide.
            rows = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM song_file WHERE ref = ? AND source = 'library' AND navidrome_song_id IS NOT NULL AND added_at < ?",
                    (ref, self._began),
                )
            ]
            listed = conn.execute(
                "SELECT moved FROM ref_recheck WHERE ref = ?", (ref,)
            ).fetchone()  # (None: the janitor retired it meanwhile; the delete below is then a no-op)
            if listed is not None and listed["moved"]:
                self._prefer_a_decided_file(conn, ref)
            unseen = [file_id for file_id in rows if file_id not in self._judged]
            undecided = [file_id for file_id in rows if file_id in self._undecided]
            if unseen or undecided:
                kept_back.append((ref, len(unseen), len(undecided)))
                continue
            conn.execute("DELETE FROM ref_recheck WHERE ref = ?", (ref,))
            released += 1
        return gone, released

    def _prefer_a_decided_file(self, conn: sqlite3.Connection, ref: str) -> None:
        """A song that lost a file to a move prefers a file that was JUDGED KEPT (or a keeper's), never one that stayed only because nobody could judge it, and never one the
        listing of this pass lacks: the move leaves the preference on the newest row left (`refs.ensure_one_preferred`, the merge's rule too, unchanged), which can be a file
        with no usable tags or the placeholder artist, and that is the file the phone would play. Read from `ref_recheck.moved`, which is committed with each move, so a pass
        that failed after a move is made right by the next complete one. The phones are told when the preferred file changes (the files feed answers with it)."""
        rows = conn.execute(
            "SELECT id, source, navidrome_song_id, added_at, preferred FROM song_file WHERE ref = ? ORDER BY preferred DESC, added_at DESC, rowid DESC",
            (ref,),
        ).fetchall()
        decided = [
            row
            for row in rows
            if self._listing.alive(row["navidrome_song_id"], row["added_at"]) and not self._nobody_could_judge(row)
        ]
        if not decided:
            return  # no file to prefer on that ground: the rule of `ensure_one_preferred` stands
        chosen = decided[0]["id"]  # the one it has when that is decided, else the newest decided
        if [row["id"] for row in rows if row["preferred"]] == [chosen]:
            return
        conn.execute("UPDATE song_file SET preferred = (id = ?) WHERE ref = ?", (chosen, ref))
        refs.touch_file(conn, ref)
        library.touch_ref_holders(conn, ref)

    def _nobody_could_judge(self, row: sqlite3.Row) -> bool:
        """A library file this pass read at its start that the tags could not decide, or that it never saw (a keeper's file and a file attached since are not)."""
        if row["source"] != "library" or row["navidrome_song_id"] is None or row["added_at"] >= self._began:
            return False
        return bool(row["id"] in self._undecided or row["id"] not in self._judged)

    def _summary(self) -> None:
        r = self.report
        if self._logged > _LOG_MOVES:
            log.info("rehome: and %d more files re-pointed", self._logged - _LOG_MOVES)
        if self._stays_logged > _LOG_MOVES:
            log.info("rehome: and %d more files stay where they are for a reason given above", self._stays_logged - _LOG_MOVES)
        log.info(
            "rehome: %d files judged by their tags in %d rounds: %d kept, %d files re-pointed to other songs (%d new songs made, %d rows dropped because the song already held the file), "
            "%d stayed (no usable tags %d, no artist name and no id %d, the song fits the tags as well as another %d, the last file of a song a person owns %d), "
            "%d changed hands meanwhile; %d songs released from the worklist, %d kept on it (%d for a file that could not be judged), %d no longer exist%s",
            r.judged,
            r.rounds,
            r.kept,
            r.moved,
            r.new_refs,
            r.dropped,
            r.stayed_nameless + r.stayed_untagged + r.stayed_ambiguous + r.stayed_last_file,
            r.stayed_untagged,
            r.stayed_nameless,
            r.stayed_ambiguous,
            r.stayed_last_file,
            r.changed,
            r.released,
            r.held_back,
            r.held_undecided,
            r.gone,
            "; the pass failed, so the worklist is kept as it was" if r.failed else "",
        )


# ---------------------------------------------------------------------------------------------------------------------------------- what a pass owes after it


def pay_merge_debt(db: Database) -> bool:
    """Runs the merge repair when the rehome owes it (`MERGE_PENDING_SETTING`: a worklist ref was released and the pairs held for it were not judged yet) and clears the
    debt ONLY when the repair ran and did not fail. `refmerge.repair` answers `failed` instead of raising; a raise is covered too. A failure is a log line and the debt stays,
    so the next pass of the library link (not only the next restart) tries again. Returns whether the debt is paid (or there was none)."""
    with db.read() as conn:
        if repair_copy.setting(conn, MERGE_PENDING_SETTING) is None:
            return True
    try:
        outcome = refmerge.repair(db)
    except Exception:  # noqa: BLE001 - the repair never raises by its own contract; a pass must still end whatever it does
        log.exception("rehome: the merge repair raised; it is still owed and the next pass of the library link tries again")
        return False
    if outcome.failed:
        log.error(
            "rehome: the merge repair failed (its own log line says why); it is still owed and the next pass of the library link tries again"
        )
        return False
    with db.tx() as conn:
        conn.execute("DELETE FROM setting WHERE key = ?", (MERGE_PENDING_SETTING,))
    return True


def idle(db: Database) -> None:
    """What a library pass with NO worklist still owes (the end of every pass that has no rehome to run): the record of an attempt that did not finish is spent (the pass that
    emptied the worklist, or the janitor retiring the last ref on it, is what ended it; left standing, the next change of the fold would reuse a copy taken before the state of
    that day), and the merge the last pass owed is run. A worklist that is not empty is none of its business (a rehome that could not start)."""
    with db.read() as conn:
        if conn.execute("SELECT 1 FROM ref_recheck LIMIT 1").fetchone() is not None:
            return
        pending = repair_copy.setting(conn, BACKUP_PENDING_SETTING)
    if pending is not None:
        with db.tx() as conn:
            repair_copy.settle(conn, pending_key=BACKUP_PENDING_SETTING, used_key=BACKUP_USED_SETTING, copy=None)
    pay_merge_debt(db)
