"""`repair_copy.py`: the copy of the database a repair relies on, shared by the key rewrite (`keyrepair.py`) and the rehome (`rehome.py`), P2-25.

The invariant these tests keep: **a repair never writes without a copy it can be undone from**, and it never depends on the ORDER of the copies' names (a clock that
goes back makes it wrong). The two repairs have their own tests of the whole story (`test_keyrepair.py`, `test_rehome.py`); this file pins each rule of the helper on its
own, so a repair added later that uses it inherits them and a change to the helper cannot pass by luck.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from encore_server import repair_copy
from encore_server.db import Database

LABEL, PENDING, USED = "before-test-repair", "test_repair_pending", "test_repair_used"
LOG = logging.getLogger("test_repair_copy")


def take(db: Database, **kwargs: int) -> Path:
    return repair_copy.copy_for_repair(
        db, label=LABEL, pending_key=PENDING, used_key=USED, log=LOG, what="test repair", noun="repair", **kwargs
    )


def setting(db: Database, key: str) -> str | None:
    with db.read() as conn:
        return repair_copy.setting(conn, key)


def test_a_copy_is_taken_recorded_as_pending_and_is_a_database(db: Database) -> None:
    copy = take(db)

    assert repair_copy.is_a_copy(copy) and copy.parent == db.backups and db.copies(LABEL) == [copy]
    assert setting(db, PENDING) == copy.name and setting(db, USED) is None


def test_the_copy_of_an_attempt_that_did_not_finish_is_used_again_and_nothing_new_is_taken(db: Database) -> None:
    first = take(db)

    again = take(db)

    assert again == first and db.copies(LABEL) == [first]


def test_a_pending_copy_that_is_also_the_spent_one_is_never_used_again(db: Database) -> None:
    """The state cannot come from `mark_used` (it clears the pending record in the same transaction), so this is the second layer: if the two names ever agree, the copy
    is SPENT (a committed repair used it) and a later repair, which is about to write other things, takes its own."""
    spent = take(db)
    with db.tx() as conn:
        conn.execute("INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)", (USED, spent.name))

    new = take(db)

    assert new != spent and repair_copy.is_a_copy(new) and len(db.copies(LABEL)) == 2


@pytest.mark.parametrize("how", ["is gone", "is not a database"])
def test_a_pending_copy_that_is_gone_or_junk_is_replaced_by_a_new_one(
    db: Database, how: str, caplog: pytest.LogCaptureFixture
) -> None:
    first = take(db)
    if how == "is gone":
        first.unlink()
    else:
        first.write_bytes(b"not a database" * 40)

    with caplog.at_level(logging.WARNING, logger="test_repair_copy"):
        new = take(db)

    assert repair_copy.is_a_copy(new) and "gone or is not a database" in caplog.text
    if (
        how == "is not a database"
    ):  # the junk file is still there, so the new copy has a name of its own (a deleted one frees its name within the second)
        assert new != first


def test_a_name_in_the_settings_never_leads_out_of_the_backups_folder(db: Database, tmp_path: Path) -> None:
    """The pending record is a NAME; a value that is a path elsewhere is read as the last part of it, inside the folder (and there it is no copy)."""
    outside = tmp_path / "elsewhere.db"
    sqlite3.connect(outside).close()
    outside.write_bytes(repair_copy.SQLITE_MAGIC + b"x" * 100)
    with db.tx() as conn:
        conn.execute("INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)", (PENDING, str(outside)))

    new = take(db)

    assert new.parent == db.backups and new != outside


def test_the_prune_keeps_the_copy_just_taken_the_spent_one_and_at_most_keep_copies_whatever_the_names_say(db: Database) -> None:
    """Spare copies named in the FUTURE sort after the copy taken now: ordering by names would remove the copy just taken. It is told to stay."""
    db.backups.mkdir(parents=True, exist_ok=True)
    spent = db.backups / f"encore-{LABEL}-20000101-000000.db"
    spent.write_bytes(repair_copy.SQLITE_MAGIC + b"spent")
    with db.tx() as conn:
        conn.execute("INSERT OR REPLACE INTO setting (key, value) VALUES (?, ?)", (USED, spent.name))
    for stamp in ("20991231-235957", "20991231-235958", "20991231-235959"):
        (db.backups / f"encore-{LABEL}-{stamp}.db").write_bytes(repair_copy.SQLITE_MAGIC + b"future")

    copy = take(db, keep=3)

    left = db.copies(LABEL)
    assert copy in left and spent in left and len(left) == 3, "the two that must stay, and one spare"


def test_a_copy_of_another_label_is_never_touched(db: Database) -> None:
    db.backups.mkdir(parents=True, exist_ok=True)
    other = db.backups / "encore-before-ref-merge-20000101-000000.db"
    other.write_bytes(repair_copy.SQLITE_MAGIC + b"merge")
    for _ in range(5):
        take(db, keep=1)

    assert other.is_file()


def test_mark_used_spends_the_copy_and_clears_the_pending_record_in_one_transaction(db: Database) -> None:
    copy = take(db)
    with db.tx() as conn:
        repair_copy.mark_used(conn, pending_key=PENDING, used_key=USED, copy=copy)

    assert setting(db, USED) == copy.name and setting(db, PENDING) is None
    assert take(db) != copy, "the next repair takes its own"


def test_require_copy_refuses_a_missing_an_empty_and_a_junk_file_and_passes_a_real_copy(db: Database, tmp_path: Path) -> None:
    real = take(db)
    repair_copy.require_copy(real)
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a database" * 30)
    for bad in (tmp_path / "missing.db", empty, junk, tmp_path):
        with pytest.raises(repair_copy.CopyMissing):
            repair_copy.require_copy(bad)
