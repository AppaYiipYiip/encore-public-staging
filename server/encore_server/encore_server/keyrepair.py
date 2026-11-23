"""Rewriting the stored song keys when the fold changes (P2-25 slice 3, audit B-37). The precedent is `refmerge.py`; the design is
`docs/tasks/P2-songs-as-references.md`, section P2-25, part 7.

**What went wrong.** `song_ref.norm_key` is how a song described again (a search, an import, the library scan) finds the ref it already has. Until P2-25 the key
was made with a fold that kept `a-z0-9` and DROPPED every other letter: two different Arabic, Russian, Korean or Japanese songs of one artist were the SAME key
(`||`), a Latin artist with two different Arabic titles that start alike were `fairuz|habibi|`, and `Bjork` with a stroked o was `bjrk`. The stored keys are the
old fold's; the code now makes keys with the new one (`textnorm.py`), so a song described again would not find its own ref and would make a duplicate.

**What this does, at every start, after the migrations and BEFORE `refmerge.repair` (so the tombstones that run writes carry new keys), before any thread.**
The PLAN (a read, `plan`) runs at EVERY start, and its cost is the cost of every start: 0.07 s for 3,394 refs, 3.4 s for 200,000 synthetic refs (the WHOLE repair, once, with
its copy and its writes, is another number: 0.28 s and 8.3 s). Only when it finds something is anything written, and only then is a copy
taken. What it finds depends on which start it is:

* **The first one** (`setting.textnorm_revision` lower than `textnorm.TEXTNORM_REVISION`; 0 until now: a database that never had the setting was made by the old
  fold): every key is rewritten, and every ref the old fold damaged is judged (worklist, picture).
* **Every later one** (the revision is current): the rewrite of a key that is NOT what the fold makes now, and ONLY for the refs it rewrites does it judge damage. That
  is the **rollback hole** closed: an older image (a rollback, or a Host who started the old tag by hand) keys new songs with the OLD fold after the revision was stored,
  and nothing used to repair them. A key that differs from the current fold is the evidence that an older image made it, and it is the reason a ref is judged
  again at all: a ref already repaired is never touched twice, so the worklist the rehome (slice 4) empties stays empty, and a catalogue picture the cover finder found
  later is never voided again. (A bump of the fold nobody wrote down in `TEXTNORM_REVISION` is found the same way: the plan is a second layer under the rule.)
* **A database of a NEWER fold** (a rollback the other way) is not even planned against: the plan would rewrite its keys DOWN.

The first and every later repair do the same, in ONE transaction after a copy of the database (`db.backup("before-key-rewrite")`, its path logged):

1. every `song_ref.norm_key` that is not what the fold makes now is rewritten from the ref's own artist and title. **A rewrite never merges** (two refs that now
   share a key stay two: a key is a lookup, and identity by name afterwards is what B-37 was);
2. a ref the old fold DAMAGED (its own text did not survive it, or its STORED key has an empty artist or title segment: `slipknot||sic`, all ASCII, one key for
   every song of the band that has a bracket in its name) that holds a library file goes on the worklist `ref_recheck`; a tombstone whose key had an empty artist or
   title segment is set to NULL (it can never be found again; its ids keep working); the Deezer picture of a damaged ref that the catalogue never identified is voided
   (one hit matched every Arabic song), so the cover finder asks again;
3. on the first start the revision (and the Unicode version it was made under) is written LAST; and the name of the copy this repair used is recorded (below).

It is idempotent (a start that finds nothing writes nothing), it rolls back whole when anything fails, it logs ids and counts only (a title is a person's data) and it
**never stops the server**: a failed repair is tried again at the next start, and logs ONE ERROR line per start. Until it has run, the cost is that a non-Latin song
described again may make a duplicate ref, which the by-file merge folds later; the ERROR line says so.

**The copy** (`Database.backup`, `Database.prune_backups`; the rules below are now written ONCE in `repair_copy.py`, which `rehome.py` shares, with its own label and settings). The invariant: **a repair never writes without a copy it can be undone from, as far as a check at start-up can tell** (the tombstone keys it
nulls and the pictures it voids come back from nothing else). It holds in two layers, and neither depends on the ORDER of the copies, because the order is not
trustworthy: a copy's name is the LOCAL time of the clock that made it, a clock goes back (the end of daylight saving time repeats an hour, a time sync steps it,
somebody sets it), and a file's modification time comes from the same clock. (The first version ordered the copies by their names: with three copies named in the future
the copy just taken was the OLDEST of four, the prune removed it, and the repair went on with a path that did not exist and logged it as kept.)

1. **By construction.** The prune is told which copies must stay and never takes them as candidates: the copy just taken and the one the last COMMITTED repair used.
   The copy an attempt takes is recorded by name (`setting.textnorm_backup_pending`) in its OWN committed write, right after it is taken, because the rewrite itself may
   roll back; the next start reuses exactly that copy, and only while it is still there and still looks like a database. A file that merely sorts newest is NOT an earlier
   attempt's copy (the first version reused it). The repair that commits records the copy it used (`setting.textnorm_backup_used`) and clears the pending record in the
   SAME transaction, so a copy a committed repair used is spent and a later real repair takes its own.
2. **At the point of writing.** Inside the write transaction and before the first write, the repair checks that the copy exists, is not empty and begins like a SQLite
   database (its first 16 bytes are the header `SQLite format 3` and a zero byte; `_is_a_copy`). **That is all: it is not an integrity check of the copy's contents**
   (nothing opens the copy or runs `PRAGMA integrity_check`; a copy cut short that still begins with the header passes; `Database.backup` is `VACUUM INTO`, a whole new file
   or an error). Otherwise it writes nothing (no key, no worklist row, no revision), logs ONE error line and the server goes on; the next start takes a new copy.

At most `KEEP_COPIES` copies of this label are kept: the two that must stay and the newest of the others by name (a rollback loop cannot fill the disk; the copies of other
repairs, a migration's and the merge's, are never touched). **The cost, stated:** when the clock has gone back, the name order can be wrong, and then a spare copy goes
before another one: an older spare is kept instead of a newer one. The copy a repair relies on is never what is lost. A reused copy can also be older than the start that
used it (a failing repair that is fixed a week later is backed by the copy of the first attempt), so restoring it loses what was written in between; the repair rewrites
keys and the worklist only, and every one of them is recomputed from the refs' own text, so a restore is never what undoes it.

**The Unicode version is a guard, not a hope.** A stored key is a function of the Unicode data of the Python that made it. The fold is pinned to `textnorm.UNICODE_VERSION`
(15.0.0: `python:3.12-slim`); the server REFUSES TO START on any other (`create_app`, the server command), so no key is ever written or rewritten under another, and
`repair` itself raises `textnorm.UnicodeVersionError` first (a second layer for any other caller; the one exception it does not swallow, because it is a refusal and not a
failure). `tests/test_unicode_pin.py` guards the image, the workflow, `requires-python`, the server and the interpreter that runs the tests.

**What is left to the rehome** (slice 4, `rehome.py`, in the hourly library link): the files the old fold glued onto the wrong song. This only lists the refs to
judge (`ref_recheck`). The rewrite never renames, moves, retags or deletes a file: it touches no file of the Host's music at all. (The only files it ever deletes are its
own surplus copies of the database, and it asks `Database` to do that.)

STOP-GAP(P2-25 one-shot-repair; remove after 0.1.0): `_lost_by_old_fold`, the worklist and the voided covers are a ONE-TIME repair of data the old fold made. They go when the
worklist is empty on every install the project knows and one release has passed (N-36; `tests/test_stopgap_expiry.py` fails when the release in the marker has passed, and
`python docs/evidence/scripts/audit_stack.py check rekey` reads whether the worklist is empty). The rewrite itself, the revision in `setting`, the plan at every start and the guard are
permanent: every later change of the fold is the same mechanism with a higher `TEXTNORM_REVISION`.
"""

from __future__ import annotations

import logging
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import library, refs, repair_copy, textnorm
from .db import Database
from .ids import now_ms

log = logging.getLogger("encore_server.keyrepair")

_BACKUP_LABEL = "before-key-rewrite"
REVISION_SETTING = "textnorm_revision"
UNICODE_SETTING = "textnorm_unicode"
#: The name of the copy the last repair that COMMITTED used: that repair is over, its copy is spent (and is one of the two the prune never removes).
BACKUP_USED_SETTING = "textnorm_backup_used"
#: The name of the copy an attempt took and has not yet committed with: written in its own committed write right after the copy is taken (the rewrite may roll back),
#: cleared by the repair that commits. It is the ONLY copy a later start reuses: the order of the names says nothing about which attempt a file belongs to.
BACKUP_PENDING_SETTING = "textnorm_backup_pending"
#: How many copies of the stored keys are kept (the rule, and why three, is in `repair_copy.py`, which `rehome.py` shares).
KEEP_COPIES = repair_copy.KEEP_COPIES
#: The picture hosts of the catalogue whose hit the broken fold matched to every song with the same (empty) name. The HOSTNAME decides, not a substring.
_DEEZER_HOSTS = ("dzcdn.net", "deezer.com")


def _lost_by_old_fold(text: str) -> bool:
    """Did [text] lose a letter or a digit in the OLD fold (NFKD, keep ASCII)? **Frozen on purpose**: this describes how the data already stored was made, not
    what the server does now (`textnorm.survives_fold_whole` is the live rule). True for every name that is not Latin, for the Latin letters that do not
    decompose (`ø ł ı ß đ þ æ`), for a name that mixes a Latin start with another script, and for a text with no letter or digit at all (`!!!`); false for `Björk`,
    `Beyoncé`, `BTS`, `Don’t Stop`. It is a property of the text, so it needs no copy of the old fold, and it is decided from the ref's own title and artist,
    not from its stored key (`fairuz|habibi|` is not empty and is still damaged). It guards against a WRONG attachment; a miss it cannot make. A ref whose text
    survived but whose stored key has an empty segment is the other reason a ref is suspect (`plan`).
    STOP-GAP(P2-25 one-shot-repair; remove after 0.1.0): removed with the worklist (N-36)."""
    seen = False
    for ch in unicodedata.normalize("NFKD", text or ""):
        if unicodedata.category(ch)[0] in "LN":
            if ch > "\x7f":
                return True
            seen = True
    return not seen


def _on_deezer(url: object) -> bool:
    if not isinstance(url, str):
        return False
    host = (urlparse(url).hostname or "").lower()
    return any(host == known or host.endswith("." + known) for known in _DEEZER_HOSTS)


@dataclass
class Plan:
    """What a rewrite would do, from a look that changes nothing (the dry run of the tool prints it; `repair` applies it)."""

    #: `(ref, stored key, new key)` of every ref whose stored key is not what the fold makes now.
    rekeys: list[tuple[str, str, str]] = field(default_factory=list)
    #: The refs the old fold DAMAGED: their own artist or title did not survive it, or their stored key has an empty artist or title segment.
    suspect: set[str] = field(default_factory=set)
    #: The suspect refs that hold at least one library file: the rehome (slice 4) judges their files.
    worklist: set[str] = field(default_factory=set)
    #: The suspect refs whose catalogue picture (no catalogue id) is voided.
    covers: list[str] = field(default_factory=list)
    #: The `old_id` of the tombstones whose key had an empty artist or title segment.
    tombstones: list[str] = field(default_factory=list)
    refs_total: int = 0

    @property
    def changes(self) -> bool:
        return bool(self.rekeys or self.worklist or self.covers or self.tombstones)


def plan(conn: sqlite3.Connection, *, one_shot: bool = True) -> Plan:
    """The rewrite as a list, from the database as it is. Changes nothing, and is cheap enough to run at every start.

    A ref is **suspect** for either of two reasons, each enough on its own: its OWN text did not survive the old fold (`fairuz|habibi|` is a healthy-looking key of a
    damaged ref), or its STORED key has an empty artist or title segment (`slipknot||sic`: all ASCII, nothing in the text was lost, but the key matched every other
    song of the artist). A Latin ref whose stored key is healthy is not suspect.

    [one_shot] is the first start after the fold changed (the stored revision is lower): every suspect ref is judged. On any later start only a suspect ref whose key is
    being rewritten NOW is judged: a stale key is the evidence that an older image made the ref, and a ref repaired already (its key is current) must not be judged again
    (the rehome empties the worklist; the cover finder stores correct pictures)."""
    result = Plan()
    library_refs = {row["ref"] for row in conn.execute("SELECT DISTINCT ref FROM song_file WHERE source = 'library'")}
    for row in conn.execute("SELECT id, title, artists, norm_key, cover_url, deezer_id FROM song_ref"):
        result.refs_total += 1
        artist = refs.lead_artist(row["artists"])
        new_key = refs.norm_key(artist, row["title"])
        stale = new_key != row["norm_key"]
        if stale:
            result.rekeys.append((row["id"], row["norm_key"], new_key))
        damaged = _lost_by_old_fold(artist) or _lost_by_old_fold(row["title"]) or refs.key_is_degenerate(row["norm_key"])
        if damaged and (one_shot or stale):
            result.suspect.add(row["id"])
            if row["id"] in library_refs:
                result.worklist.add(row["id"])
            if row["deezer_id"] is None and _on_deezer(row["cover_url"]):
                result.covers.append(row["id"])
    for row in conn.execute("SELECT old_id, norm_key FROM ref_merge WHERE norm_key IS NOT NULL"):
        if refs.key_is_degenerate(row["norm_key"]):
            result.tombstones.append(row["old_id"])
    return result


@dataclass
class Report:
    #: Something was written (the keys, the worklist, the pictures or the revision) and committed.
    ran: bool = False
    failed: bool = False
    #: The copy this repair used (taken now, or an earlier attempt's that rolled back); `None` when nothing needed changing.
    backup: Path | None = None
    rekeyed: int = 0
    suspect: int = 0
    worklist: int = 0
    tombstones_nulled: int = 0
    covers_voided: int = 0


def stored_revision(conn: sqlite3.Connection) -> int:
    """Which fold made the stored keys: the number in `setting`, 0 when there is none (the old ASCII fold) or it is not a number."""
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (REVISION_SETTING,)).fetchone()
    try:
        return int(row["value"]) if row is not None else 0
    except (TypeError, ValueError):
        return 0


def _write_revision(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)", (UNICODE_SETTING, textnorm.running_unicode()))
    conn.execute("INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)", (REVISION_SETTING, str(textnorm.TEXTNORM_REVISION)))


CopyMissing = repair_copy.CopyMissing
_is_a_copy = repair_copy.is_a_copy


def _copy_for_this_repair(db: Database) -> Path:
    """The copy of the database this repair is backed by (`repair_copy.copy_for_repair`: the copy an earlier attempt recorded, else a new one with the pile pruned and
    the two copies that must stay named). The order of the names is never what chooses. Kept under this name because `repair` calls it and the tests replace it."""
    return repair_copy.copy_for_repair(
        db,
        label=_BACKUP_LABEL,
        pending_key=BACKUP_PENDING_SETTING,
        used_key=BACKUP_USED_SETTING,
        log=log,
        what="key rewrite",
        noun="rewrite",
        keep=KEEP_COPIES,
    )


def repair(db: Database) -> Report:
    """Rewrites the stored keys that are not what the fold makes now, at every start; returns, never raises (a server that cannot repair itself still has to start),
    except for [textnorm.UnicodeVersionError]: a Python whose Unicode is not the pin must not write a key at all. See the module's docstring."""
    textnorm.require_pinned_unicode()
    report = Report()
    try:
        with db.read() as conn:
            stored = stored_revision(conn)
            if stored > textnorm.TEXTNORM_REVISION:
                return report  # a newer fold made these keys (a rollback the other way): rewriting them DOWN would be the damage
            first = stored < textnorm.TEXTNORM_REVISION
            look = plan(conn, one_shot=first)
        if not look.changes:
            if first:  # an empty database, a Latin library: the number is all there is to write, and no copy
                with db.tx() as conn:
                    _write_revision(conn)
                report.ran = True
                log.info("key rewrite: revision %d, nothing to rewrite in %d refs", textnorm.TEXTNORM_REVISION, look.refs_total)
            return report
        report.backup = _copy_for_this_repair(db)
        with db.tx() as conn:
            # The second layer, at the narrowest point: the first thing inside the write transaction, before any write. Whatever happened to the copy since it was
            # taken (a prune that went wrong, a cleaned folder, a full disk), a repair that cannot be undone from it does not run.
            if not _is_a_copy(report.backup):
                raise CopyMissing(str(report.backup))
            _apply(conn, plan(conn, one_shot=first), report)
            if first:
                _write_revision(conn)
            repair_copy.mark_used(conn, pending_key=BACKUP_PENDING_SETTING, used_key=BACKUP_USED_SETTING, copy=report.backup)
        report.ran = True
        log.info(
            "key rewrite (%s): revision %d, %d of %d keys rewritten, %d refs the old fold damaged, %d refs on the worklist for the library link, %d tombstone keys "
            "voided, %d catalogue pictures voided",
            "first start of this revision" if first else "a later start: keys an older image made",
            textnorm.TEXTNORM_REVISION,
            report.rekeyed,
            look.refs_total,
            report.suspect,
            report.worklist,
            report.tombstones_nulled,
            report.covers_voided,
        )
    except CopyMissing as missing:  # nothing was written: the transaction rolled back before its first write
        report = Report(failed=True)
        log.error(
            "key rewrite REFUSED and changed nothing: the copy of the database it was to rely on (%s) is not there, or is not a database, at the moment of writing, and "
            "a repair that cannot be undone from a copy does not run (it is tried again at the next start with a new copy, and until then a song in another alphabet "
            "described again may make a duplicate ref)",
            missing,
        )
    except Exception:  # noqa: BLE001 - the server must start whatever happens here; the transaction rolled back, the copy is kept
        report = Report(failed=True, backup=report.backup)
        log.exception(
            "key rewrite FAILED and changed nothing (the stored keys stay as they are; the rewrite is tried again at the next start, and until then a song in "
            "another alphabet described again may make a duplicate ref)%s",
            f"; the copy taken before it is {report.backup}" if report.backup else "",
        )
    return report


def _apply(conn: sqlite3.Connection, work: Plan, report: Report) -> None:
    at = now_ms()
    conn.executemany("UPDATE song_ref SET norm_key = ? WHERE id = ?", [(new, ref) for ref, _old, new in work.rekeys])
    report.rekeyed = len(work.rekeys)
    report.suspect = len(work.suspect)
    for ref in sorted(work.worklist):  # STOP-GAP(P2-25 one-shot-repair; remove after 0.1.0): the worklist, until N-36
        conn.execute("INSERT OR IGNORE INTO ref_recheck (ref, at) VALUES (?, ?)", (ref, at))
    report.worklist = len(work.worklist)
    # A tombstone's key cannot be recomputed (it stores no title or artist): one with an empty segment can never be found again, the others stay (dead weight).
    conn.executemany("UPDATE ref_merge SET norm_key = NULL WHERE old_id = ?", [(old,) for old in work.tombstones])
    report.tombstones_nulled = len(work.tombstones)
    # STOP-GAP(P2-25 one-shot-repair; remove after 0.1.0): the pictures the broken fold matched, until N-36
    for ref in work.covers:
        conn.execute("UPDATE song_ref SET cover_url = NULL, cover_tried_at = NULL WHERE id = ?", (ref,))
        library.touch_ref_holders(conn, ref)
        if conn.execute("SELECT 1 FROM song_file WHERE ref = ?", (ref,)).fetchone() is not None:
            refs.touch_file(conn, ref)
    report.covers_voided = len(work.covers)
