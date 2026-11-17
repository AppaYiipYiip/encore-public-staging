"""The copy of the database a repair relies on, written once for the repairs that need one (`keyrepair.py`, `rehome.py`; P2-25).

**The invariant: a repair never writes without a copy it can be undone from.** It holds in two layers, and neither depends on the ORDER of the copies, because the
order is not trustworthy: a copy's name is the LOCAL time of the clock that made it, a clock goes back (the end of daylight saving time repeats an hour, a time sync
steps it, somebody sets it), and a file's modification time comes from the same clock. (The first version of the key repair ordered the copies by their names: with
three copies named in the future the copy just taken was the OLDEST of four, the prune removed it, and the repair went on with a path that did not exist and logged it
as kept.)

1. **By construction** ([copy_for_repair]). The prune is told which copies must stay and never takes them as candidates: the copy just taken and the one the last
   COMMITTED repair used. The copy an attempt takes is recorded by name (a `setting`) in its OWN committed write, right after it is taken, because the repair itself may
   roll back; the next attempt reuses exactly that copy, and only while it is still there and still looks like a database. A file that merely sorts newest is NOT an
   earlier attempt's copy. The repair that commits records the copy it used and clears the pending record ([mark_used], in the SAME transaction), so a copy a committed
   repair used is spent and a later real repair takes its own.
2. **At the point of writing** ([require_copy]). Inside the write transaction and before the first write, the repair checks that the copy exists, is not empty and begins
   like a SQLite database. Otherwise it writes nothing, logs ONE error line and the server goes on; the next attempt takes a new copy.

Each repair has its OWN label and its own two settings: sharing them would reuse, or spend, another repair's copy.

At most [KEEP_COPIES] copies of a label are kept: the two that must stay and the newest of the others by name (a loop can never fill the disk; the copies of other
repairs, a migration's and the merge's, are never touched). **The cost, stated:** when the clock has gone back, the name order can be wrong, and then a spare copy goes
before another one: an older spare is kept instead of a newer one. The copy a repair relies on is never what is lost. A reused copy can also be older than the attempt
that used it, so restoring it loses what was written in between; the repairs here recompute everything they write from data that is still there.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from .db import Database

#: How a SQLite database file begins (what `VACUUM INTO` writes): a file that does not is not a copy to undo a repair from.
SQLITE_MAGIC = b"SQLite format 3\x00"
#: How many copies of one label are kept. Three: the one just taken and the one the last COMMITTED repair used (the prune never removes either, whatever their names
#: say), and one spare (the newest of the others by name, which a clock that went back can get wrong: then an older spare is kept). A loop can never cost more disk.
KEEP_COPIES = 3


class CopyMissing(RuntimeError):
    """The copy a repair was to rely on is not there, or is not a database, at the moment it comes to write: the repair does not run."""


def is_a_copy(path: Path) -> bool:
    """Is this something a repair can be undone from? It is there, it is not empty and it begins like a SQLite database (reading its first bytes covers all three: a
    missing file cannot be opened, an empty one has no first bytes, junk does not begin like a database). Never raises (a file that cannot be read is not one)."""
    try:
        with path.open("rb") as handle:
            return handle.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC
    except OSError:
        return False


def require_copy(path: Path) -> None:
    """The second layer: call it FIRST inside the write transaction. Raises [CopyMissing] when the copy is not there (nothing has been written yet)."""
    if not is_a_copy(path):
        raise CopyMissing(str(path))


def setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def copy_for_repair(
    db: Database,
    *,
    label: str,
    pending_key: str,
    used_key: str,
    log: logging.Logger,
    what: str,
    noun: str,
    keep: int = KEEP_COPIES,
) -> Path:
    """The copy of the database this repair is backed by: the one an earlier attempt of THIS repair recorded under [pending_key], while it is still there; else a new one
    (and the pile pruned, with this copy and the last committed repair's named as the ones that stay). The order of the names is never what chooses."""
    with db.read() as conn:
        pending = setting(conn, pending_key)
        spent = setting(conn, used_key)
    if pending and pending != spent:
        earlier = db.backups / Path(pending).name  # a name from the table, never a path out of the folder
        if is_a_copy(earlier):
            log.info(
                "%s: the copy an earlier attempt took, before the %s that did not finish, is used again: %s", what, noun, earlier
            )
            return earlier
        log.warning("%s: the copy an earlier attempt took is gone or is not a database, so a new one is taken", what)
    copy = db.backup(label)
    with db.tx() as conn:  # its own committed write: the repair below may roll back, the record of its copy must not
        conn.execute("INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)", (pending_key, copy.name))
    try:
        db.prune_backups(label, keep, protect=[copy, *([spent] if spent else [])])
    except OSError:
        log.warning("%s: the oldest copies could not be removed (the copy just taken is kept)", what, exc_info=True)
    log.info("%s: a copy of the database before the %s is kept at %s", what, noun, copy)
    return copy


def mark_used(conn: sqlite3.Connection, *, pending_key: str, used_key: str, copy: Path) -> None:
    """In the transaction that COMMITS the repair: this copy is spent (a later repair takes its own) and no attempt is pending."""
    conn.execute("INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)", (used_key, copy.name))
    conn.execute("DELETE FROM setting WHERE key = ?", (pending_key,))
