"""A repeatable, READ-ONLY check of the one-time repair of songs in other alphabets (P2-25 slice 4): are the stored keys what the fold makes now, is the worklist empty,
does the merge repair still hold a pair back for it? A lead runs it against a database copy or a running stack (`docs/evidence/scripts/audit_stack.py check rekey`); the
repair writes nothing and this reads only.

    python -m encore_server.rekey_audit --db copy-of-encore.db

**What it counts** (ids only, never a title: a title is a person's data), each with what is wanted after the server has started once and one library pass has run:

* the refs whose stored key is NOT what the fold makes now (the rewrite of `keyrepair.py` did not run, or an older image keyed a song after it): wanted 0;
* the refs whose stored key has an empty artist or title part, and the tombstones whose key has (the old fold's `||`): wanted 0 of the refs;
* the refs on the worklist `ref_recheck` and the library files they still hold (the rehome of `rehome.py` has not judged them, or could not judge or safely move them: wanted 0).
  **The files are named** (the row id, the music server's own id and the song's id, five of them: ids only, no path and no title), because this FAIL is the visible reminder of a
  ref that stays held. Why a ref stays held, and what lets each one go, is the table `rehome.HOLDS` (the line below prints it: it is the one place that says it, and
  `tests/test_rehome_held_text.py` checks it against what the pass does); the log of the pass says which reason each ref has;
* the pairs of refs that hold one file and are held back by the merge repair, by reason, and how many of them for the worklist (`recheck_pending`): wanted 0 for the
  worklist (the other reasons are not failures: a pair with different YouTube ids is two recordings);
* whether any pair can be merged right now and has not been (the merge runs at every start and after a pass that emptied the worklist).

**Exit code**: 0 `PASS` (nothing wanted is missing), 1 `FAIL` (the lines say what), 2 it did not look (this Python's Unicode is not the pin, so every non-Latin key would
look stale; the file is missing; the database is at an older schema than this code and was never started by it: let the server migrate it, or `Database.migrate` on a COPY).

The database is opened `mode=ro` and `query_only` (like `album_dryrun`), and the answer is the same on a database a server is running on. Reading a stored key needs the
fold, so this must run on the pinned Python (3.12): a stack runs it inside the image, a copy on the venv of `server/encore_server`.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import keyrepair, refmerge, refs, rehome, textnorm
from .db import Database

#: How many ids of each kind are written out; the rest are counted.
_EXAMPLES = 5


@dataclass
class Audit:
    schema: int = 0
    stored_revision: int = 0
    refs: int = 0
    stale: int = 0
    stale_ids: list[str] = field(default_factory=list)
    degenerate_refs: int = 0
    degenerate_tombstones: int = 0
    worklist: int = 0
    worklist_files: int = 0
    worklist_ids: list[str] = field(default_factory=list)
    #: `file row id (the music server's id) of the song`, for the first few library files the worklist refs hold.
    worklist_file_ids: list[str] = field(default_factory=list)
    held: Counter[str] = field(default_factory=Counter)
    held_for_worklist_ids: list[str] = field(default_factory=list)
    mergeable: bool = False

    @property
    def held_for_worklist(self) -> int:
        return self.held.get("recheck_pending", 0)

    def problems(self) -> list[str]:
        """What is not as wanted, in words; empty is PASS."""
        found: list[str] = []
        if self.stored_revision < textnorm.TEXTNORM_REVISION:
            found.append(
                f"the keys were made by fold revision {self.stored_revision} and this server makes {textnorm.TEXTNORM_REVISION}: the start-up rewrite has not run on this database"
            )
        if self.stale:
            found.append(f"{self.stale} refs hold a key that is not what the fold makes now")
        if self.degenerate_refs:
            found.append(f"{self.degenerate_refs} refs hold a key with an empty artist or title part")
        if self.worklist:
            found.append(
                f"{self.worklist} refs are still on the worklist, holding {self.worklist_files} library files the rehome has not judged or could not judge or safely move, so "
                f"the pairs held for them stay held. What lets each one go: {rehome.what_frees()}"
            )
        if self.held_for_worklist:
            found.append(
                f"{self.held_for_worklist} pairs of refs that hold one file are held back for the worklist (recheck_pending)"
            )
        if self.mergeable:
            found.append(
                "refs that hold one file can be merged now and have not been (the merge repair runs at every start and after a pass that emptied the worklist)"
            )
        return found


class Refused(RuntimeError):
    """It did not look: nothing is said about the database."""


def audit(conn: sqlite3.Connection) -> Audit:
    """Counts, from a connection that is not written to. Raises [textnorm.UnicodeVersionError] on a Python that is not the pin and [Refused] on an older schema."""
    textnorm.require_pinned_unicode()
    result = Audit()
    migrations = {number for number, _name, _sql in Database._migrations()}  # noqa: SLF001 - the numbers of the steps this code has
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    result.schema = max(done, default=0)
    if migrations - done:
        raise Refused(
            f"this database is at schema {result.schema} and this code is at {max(migrations)}: it was never started by this version, so there is nothing to audit yet "
            "(start the server of this version once, or run Database.migrate on a COPY)"
        )
    result.stored_revision = keyrepair.stored_revision(conn)
    look = keyrepair.plan(conn, one_shot=False)
    result.refs = look.refs_total
    result.stale = len(look.rekeys)
    result.stale_ids = [ref for ref, _old, _new in look.rekeys[:_EXAMPLES]]
    result.degenerate_tombstones = len(look.tombstones)
    result.degenerate_refs = sum(1 for row in conn.execute("SELECT norm_key FROM song_ref") if refs.key_is_degenerate(row[0]))
    listed = [row[0] for row in conn.execute("SELECT ref FROM ref_recheck ORDER BY ref")]
    result.worklist = len(listed)
    result.worklist_ids = listed[:_EXAMPLES]
    result.worklist_files = conn.execute(
        "SELECT COUNT(*) FROM song_file WHERE source = 'library' AND ref IN (SELECT ref FROM ref_recheck)"
    ).fetchone()[0]
    result.worklist_file_ids = [
        f"{row[0]} ({row[1]}) of {row[2]}"
        for row in conn.execute(
            "SELECT id, navidrome_song_id, ref FROM song_file WHERE source = 'library' AND ref IN (SELECT ref FROM ref_recheck) ORDER BY ref, id LIMIT ?",
            (_EXAMPLES,),
        )
    ]
    result.mergeable, held = refmerge.look(conn)
    result.held = Counter(pair.reason for pair in held)
    result.held_for_worklist_ids = [f"{pair.survivor}+{pair.loser}" for pair in held if pair.reason == "recheck_pending"][
        :_EXAMPLES
    ]
    return result


def render(path: str, result: Audit) -> str:
    """The report, plain text, ids only."""
    problems = result.problems()
    held = ", ".join(f"{reason} {count}" for reason, count in sorted(result.held.items())) or "none"

    def wanted(ok: bool) -> str:
        return "ok" if ok else "NOT AS WANTED"

    lines = [
        f"rekey audit of {path}",
        f"Python {sys.version.split()[0]}, Unicode {textnorm.running_unicode()} (the pin {textnorm.UNICODE_VERSION})",
        f"schema {result.schema}; the stored keys were made by fold revision {result.stored_revision}, this server makes {textnorm.TEXTNORM_REVISION}",
        f"refs: {result.refs}",
        f"keys that are not what the fold makes now: {result.stale} (wanted 0: {wanted(not result.stale)})"
        + (f"; e.g. {', '.join(result.stale_ids)}" if result.stale_ids else ""),
        f"refs whose key has an empty artist or title part: {result.degenerate_refs} (wanted 0: {wanted(not result.degenerate_refs)}); tombstones: {result.degenerate_tombstones} (nulled by the repair, not a failure)",
        f"refs on the worklist: {result.worklist}, holding {result.worklist_files} library files (wanted 0: {wanted(not result.worklist)})"
        + (f"; e.g. {', '.join(result.worklist_ids)}" if result.worklist_ids else ""),
        *([f"  the files still held: {'; '.join(result.worklist_file_ids)}"] if result.worklist_file_ids else []),
        f"pairs held back by the merge repair: {held}; for the worklist (recheck_pending): {result.held_for_worklist} (wanted 0: {wanted(not result.held_for_worklist)})"
        + (f"; e.g. {', '.join(result.held_for_worklist_ids)}" if result.held_for_worklist_ids else ""),
        f"pairs that can be merged now and are not: {'yes' if result.mergeable else 'no'} (wanted no: {wanted(not result.mergeable)})",
    ]
    lines += [f"  - {problem}" for problem in problems]
    lines.append("PASS" if not problems else "FAIL")
    return "\n".join(lines) + "\n"


def open_read_only(path: Path) -> sqlite3.Connection:
    """The database as it is, never written to: `mode=ro` (it cannot create the file or change it) and `query_only`."""
    if not path.is_file():
        raise Refused(f"no such database: {path}")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _stdout(text: str) -> None:
    """Ids and numbers only, but a console that is not UTF-8 must never end the run: what it cannot show is written as its escape."""
    encoding = sys.stdout.encoding or "ascii"
    sys.stdout.write(text.encode(encoding, "backslashreplace").decode(encoding))


def main(argv: Sequence[str] | None = None, *, out: Callable[[str], object] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m encore_server.rekey_audit",
        description="P2-25 slice 4: is the one-time repair of other alphabets done? (reads only)",
    )
    parser.add_argument("--db", required=True, type=Path, help="encore.db or a COPY of it (opened read-only)")
    args = parser.parse_args(argv)
    say = out or _stdout
    try:
        conn = open_read_only(args.db)
        try:
            result = audit(conn)
        finally:
            conn.close()
    except textnorm.UnicodeVersionError as refusal:
        say(f"rekey audit did not look: {refusal}\n")
        return 2
    except Refused as refusal:
        say(f"rekey audit did not look: {refusal}\n")
        return 2
    except sqlite3.DatabaseError as error:
        say(f"rekey audit did not look: {args.db} is not a database this version can read ({error})\n")
        return 2
    say(render(str(args.db), result))
    return 0 if not result.problems() else 1


if __name__ == "__main__":
    raise SystemExit(main())
