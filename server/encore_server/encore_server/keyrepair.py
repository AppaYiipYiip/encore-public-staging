"""Rewriting the stored song keys when the fold changes (P2-25 slice 3, audit B-37). The precedent is `refmerge.py`; the design is
`docs/tasks/P2-songs-as-references.md`, section P2-25, part 7.

**What went wrong.** `song_ref.norm_key` is how a song described again (a search, an import, the library scan) finds the ref it already has. Until P2-25 the key
was made with a fold that kept `a-z0-9` and DROPPED every other letter: two different Arabic, Russian, Korean or Japanese songs of one artist were the SAME key
(`||`), a Latin artist with two different Arabic titles that start alike were `fairuz|habibi|`, and `Bjork` with a stroked o was `bjrk`. The stored keys are the
old fold's; the code now makes keys with the new one (`textnorm.py`), so a song described again would not find its own ref and would make a duplicate.

**What this does, once, at start-up, after the migrations and BEFORE `refmerge.repair` (so the tombstones that run writes carry new keys), before any thread.**
When `setting.textnorm_revision` is lower than `textnorm.TEXTNORM_REVISION` (0 until now: a database that never had the setting was made by the old fold):

1. a copy of the database (`db.backup("before-key-rewrite")`, its path logged), only when something is going to change;
2. ONE transaction: every `song_ref.norm_key` is rewritten from the ref's own artist and title. **A rewrite never merges** (two refs that now share a key stay
   two: a key is a lookup, and identity by name afterwards is what B-37 was); a ref that the old fold DAMAGED (its own text did not survive it) and that holds a
   library file goes on the worklist `ref_recheck`; a tombstone whose key had an empty artist or title segment is set to NULL (it can never be found again; its ids
   keep working); the Deezer picture of a damaged ref that the catalogue never identified is voided (one hit matched every Arabic song), so the cover finder asks again;
3. the revision (and the Unicode version it was made under) is written LAST.

It is idempotent (a second run finds the revision and does nothing), it rolls back whole when anything fails, it logs ids and counts only (a title is a person's
data) and it **never stops the server**: a failed rewrite is tried again at the next start. Until it has run, the cost is that a non-Latin song described again may
make a duplicate ref, which the by-file merge folds later; the ERROR line says so.

**The Unicode version is a guard, not a hope.** A stored key is a function of the Unicode data of the Python that made it. The fold is pinned to `textnorm.UNICODE_VERSION`
(15.0.0: `python:3.12-slim`); on any other version this REFUSES, at ERROR level, on every start, and rewrites nothing (the next start under the right Python does it).
`tests/test_unicode_pin.py` guards the image, the workflow and the interpreter that runs the tests.

**What is left to the rehome** (slice 4, `rehome.py`, in the hourly library link): the files the old fold glued onto the wrong song. This only lists the refs to
judge (`ref_recheck`). The rewrite never renames, moves, retags or deletes a file: it touches no file at all.

STOP-GAP(P2-25 one-shot-repair): `_lost_by_old_fold`, the worklist and the voided covers are a ONE-TIME repair of data the old fold made. They go when the worklist is
empty on every install the project knows and one release has passed (N-36). The rewrite itself, the revision in `setting` and the guard are permanent: every later
change of the fold is the same mechanism with a higher `TEXTNORM_REVISION`.
"""

from __future__ import annotations

import logging
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import library, refs, textnorm
from .db import Database
from .ids import now_ms

log = logging.getLogger("encore_server.keyrepair")

_BACKUP_LABEL = "before-key-rewrite"
REVISION_SETTING = "textnorm_revision"
UNICODE_SETTING = "textnorm_unicode"
#: The picture hosts of the catalogue whose hit the broken fold matched to every song with the same (empty) name. The HOSTNAME decides, not a substring.
_DEEZER_HOSTS = ("dzcdn.net", "deezer.com")


def _lost_by_old_fold(text: str) -> bool:
    """Did [text] lose a letter or a digit in the OLD fold (NFKD, keep ASCII)? **Frozen on purpose**: this describes how the data already stored was made, not
    what the server does now (`textnorm.survives_fold_whole` is the live rule). True for every name that is not Latin, for the Latin letters that do not
    decompose (`ø ł ı ß đ þ æ`), for a name that mixes a Latin start with another script, and for a text with no letter or digit at all (`!!!`); false for `Björk`,
    `Beyoncé`, `BTS`, `Don’t Stop`. It is a property of the text, so it needs no copy of the old fold, and it is decided from the ref's own title and artist,
    not from its stored key (`fairuz|habibi|` is not empty and is still damaged). It guards against a WRONG attachment; a miss it cannot make.
    STOP-GAP(P2-25 one-shot-repair): removed with the worklist (N-36)."""
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
    #: The refs whose OWN artist or title did not survive the old fold.
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


def plan(conn: sqlite3.Connection) -> Plan:
    """The rewrite as a list, from the database as it is. Changes nothing."""
    result = Plan()
    library_refs = {row["ref"] for row in conn.execute("SELECT DISTINCT ref FROM song_file WHERE source = 'library'")}
    for row in conn.execute("SELECT id, title, artists, norm_key, cover_url, deezer_id FROM song_ref"):
        result.refs_total += 1
        artist = refs.lead_artist(row["artists"])
        new_key = refs.norm_key(artist, row["title"])
        if new_key != row["norm_key"]:
            result.rekeys.append((row["id"], row["norm_key"], new_key))
        if _lost_by_old_fold(artist) or _lost_by_old_fold(row["title"]):
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
    #: The rewrite ran to its end (also when there was nothing to change but the revision).
    ran: bool = False
    failed: bool = False
    #: The Python's Unicode is not the pin: nothing was changed (ERROR in the log).
    refused: bool = False
    #: The copy taken before anything was changed; `None` when nothing needed changing.
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


def repair(db: Database) -> Report:
    """Rewrites the stored keys when the fold is newer than what made them; always returns, never raises (a server that cannot repair itself still has to
    start). See the module's docstring."""
    report = Report()
    try:
        running = textnorm.running_unicode()
        if textnorm.unicode_pin_status(running) != "pinned":
            report.refused = True
            log.error(
                "key rewrite REFUSED: this Python has Unicode %s and the fold is pinned to Unicode %s (the Python of the server image). A stored key must not depend "
                "on the Python that made it, so no key is written or rewritten here; run the image the project ships. Until then a song in a script the old fold "
                "dropped may be described again as a duplicate ref, which the by-file merge folds later.",
                running,
                textnorm.UNICODE_VERSION,
            )
            return report
        with db.read() as conn:
            if stored_revision(conn) >= textnorm.TEXTNORM_REVISION:
                return report
            look = plan(conn)
        if look.changes:
            report.backup = db.backup(_BACKUP_LABEL)
            log.info("key rewrite: a copy of the database before the rewrite is kept at %s", report.backup)
        with db.tx() as conn:
            _apply(conn, plan(conn) if look.changes else look, report)
            conn.execute("INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)", (UNICODE_SETTING, running))
            conn.execute(
                "INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)", (REVISION_SETTING, str(textnorm.TEXTNORM_REVISION))
            )
        report.ran = True
        log.info(
            "key rewrite: revision %d, %d of %d keys rewritten, %d refs the old fold damaged, %d refs on the worklist for the library link, %d tombstone keys "
            "voided, %d catalogue pictures voided",
            textnorm.TEXTNORM_REVISION,
            report.rekeyed,
            look.refs_total,
            report.suspect,
            report.worklist,
            report.tombstones_nulled,
            report.covers_voided,
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
    for ref in sorted(work.worklist):  # STOP-GAP(P2-25 one-shot-repair): the worklist, until N-36
        conn.execute("INSERT OR IGNORE INTO ref_recheck (ref, at) VALUES (?, ?)", (ref, at))
    report.worklist = len(work.worklist)
    # A tombstone's key cannot be recomputed (it stores no title or artist): one with an empty segment can never be found again, the others stay (dead weight).
    conn.executemany("UPDATE ref_merge SET norm_key = NULL WHERE old_id = ?", [(old,) for old in work.tombstones])
    report.tombstones_nulled = len(work.tombstones)
    for ref in work.covers:  # STOP-GAP(P2-25 one-shot-repair): the pictures the broken fold matched, until N-36
        conn.execute("UPDATE song_ref SET cover_url = NULL, cover_tried_at = NULL WHERE id = ?", (ref,))
        library.touch_ref_holders(conn, ref)
        if conn.execute("SELECT 1 FROM song_file WHERE ref = ?", (ref,)).fetchone() is not None:
            refs.touch_file(conn, ref)
    report.covers_voided = len(work.covers)
