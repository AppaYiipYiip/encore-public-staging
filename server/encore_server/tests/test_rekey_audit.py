"""`rekey_audit.py` and `audit_stack.py check rekey` (P2-25 slice 4): the repeatable, READ-ONLY check a lead runs against a stack or a database copy to see whether the
one-time repair of songs in other alphabets is done: the keys are what the fold makes now, the worklist is empty, the merge repair holds nothing back for it.

The data is the same synthetic old world as `test_rehome.py` (an Arabic song that five files hang on, built with the frozen old fold), taken through the three states a real
database goes through: made by the old code, started once by the new code (rekeyed, worklist filled), and after one library pass (rehomed, worklist empty).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from encore_server import keyrepair, rekey_audit, textnorm
from encore_server.db import Database
from encore_server.scanner import link_library
from tests.test_rehome import Music, R, listing, rid, seed_old_world

REPO = Path(__file__).resolve().parents[3]
AUDIT_STACK = REPO / "docs" / "evidence" / "scripts" / "audit_stack.py"
SERVER = REPO / "server" / "encore_server"


def look(db: Database) -> rekey_audit.Audit:
    with db.read() as conn:
        return rekey_audit.audit(conn)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_of(db: Database) -> Path:
    return db.backup("audit-copy")


def test_an_empty_database_passes(db: Database) -> None:
    keyrepair.repair(db)
    result = look(db)
    assert result.problems() == [] and result.refs == 0


def test_a_database_the_old_code_made_fails_and_names_what_is_wrong(db: Database) -> None:
    seed_old_world(db)

    result = look(db)

    assert result.stored_revision == 0 and result.stale == 1 and result.stale_ids == [R], (
        "the one Arabic ref (Latin keys are what they were)"
    )
    assert result.degenerate_refs == 1, "its key is `||`"
    problems = " ".join(result.problems())
    assert "fold revision 0" in problems and "1 refs hold a key that is not what the fold makes now" in problems
    assert "empty artist or title part" in problems


def test_after_the_start_up_repair_the_keys_are_right_and_the_worklist_is_what_fails(db: Database) -> None:
    seed_old_world(db)
    keyrepair.repair(db)

    result = look(db)

    assert result.stale == 0 and result.degenerate_refs == 0 and result.stored_revision == textnorm.TEXTNORM_REVISION
    assert result.worklist == 1 and result.worklist_files == 5 and result.worklist_ids == [R]
    assert [p for p in result.problems() if "worklist" in p], result.problems()


def test_the_files_the_worklist_still_holds_are_named_by_ids_so_the_host_can_find_them(db: Database) -> None:
    """The cost of a file nobody could judge is a ref that stays held; the visible reminder is this FAIL, so it must name the FILE (row id, the music server's id and the
    song), not only count it, and never print a path or a title."""
    seed_old_world(db)
    keyrepair.repair(db)

    result = look(db)
    said: list[str] = []
    rekey_audit.main(["--db", str(copy_of(db))], out=said.append)

    assert len(result.worklist_file_ids) == 5
    assert all(R in one and "nd-" in one for one in result.worklist_file_ids)
    assert "the files still held:" in said[0] and result.worklist_file_ids[0] in said[0]
    assert "FAIL" in said[0]
    for leak in ("Collection/", ".opus", "كيفك", "فيروز"):
        assert leak not in said[0]


def test_a_pair_the_worklist_holds_back_is_counted_by_reason_and_named_by_its_two_ids(db: Database) -> None:
    seed_old_world(db)
    other = rid("sr", 9)
    with db.tx() as c:  # a second ref of the same song that holds the file nd-1, as the scan before N-11 made
        c.execute(
            "INSERT INTO song_ref (id, title, artists, duration_ms, norm_key, created_at) VALUES (?,?,?,?,?,?)",
            (other, "x", '["y"]', 1, "y|x|", 5),
        )
        c.execute(
            "INSERT INTO song_file (id, ref, navidrome_song_id, source, preferred, added_at) VALUES (?,?,?,?,?,?)",
            (rid("sf", 9), other, "nd-1", "library", 1, 1),
        )
    keyrepair.repair(db)

    result = look(db)

    assert result.held == {"recheck_pending": 1} and result.held_for_worklist == 1
    assert result.held_for_worklist_ids and R in result.held_for_worklist_ids[0] and other in result.held_for_worklist_ids[0]
    assert not result.mergeable, "held, so nothing can be merged now"
    assert [p for p in result.problems() if "recheck_pending" in p]


def test_after_one_library_pass_it_passes(db: Database) -> None:
    seed_old_world(db)
    keyrepair.repair(db)
    link_library(db, Music(listing()))

    result = look(db)

    assert result.problems() == [], result.problems()
    assert result.worklist == 0 and result.stale == 0


def test_the_report_says_pass_or_fail_in_the_last_line_and_never_prints_a_title() -> None:
    result = rekey_audit.Audit(refs=3, stored_revision=textnorm.TEXTNORM_REVISION, schema=18)
    text = rekey_audit.render("x.db", result)
    assert text.splitlines()[-1] == "PASS"
    bad = rekey_audit.Audit(refs=3, stale=2, stale_ids=[R], stored_revision=0, schema=18)
    assert rekey_audit.render("x.db", bad).splitlines()[-1] == "FAIL"


def test_it_reads_only_a_copy_is_byte_for_byte_the_same_after_and_a_missing_file_is_not_created(
    db: Database, tmp_path: Path
) -> None:
    seed_old_world(db)
    keyrepair.repair(db)
    copy = copy_of(db)
    before = sha(copy)
    said: list[str] = []

    code = rekey_audit.main(["--db", str(copy)], out=said.append)

    assert code == 1 and "FAIL" in said[0] and sha(copy) == before, "a read-only look changes not one byte"
    missing = tmp_path / "nothing.db"
    assert rekey_audit.main(["--db", str(missing)], out=said.append) == 2 and not missing.exists()


def test_a_database_that_is_open_for_writing_elsewhere_is_read_without_a_write(db: Database) -> None:
    """The live file of a running stack (WAL, a held connection): the audit opens it `mode=ro` and `query_only` and never writes."""
    seed_old_world(db)
    keyrepair.repair(db)
    db.hold_open()
    try:
        conn = rekey_audit.open_read_only(db.path)
        try:
            with pytest.raises(Exception, match="readonly|read-only|attempt to write"):
                conn.execute("UPDATE song_ref SET title = 'x'")
            assert rekey_audit.audit(conn).worklist == 1
        finally:
            conn.close()
    finally:
        db.release()


def test_it_refuses_to_look_on_a_python_that_is_not_the_pin(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    """On another Unicode every non-Latin key would look stale: a wrong FAIL is worse than no answer."""
    seed_old_world(db)
    copy = copy_of(db)
    monkeypatch.setattr(textnorm.unicodedata, "unidata_version", "15.1.0")
    said: list[str] = []

    code = rekey_audit.main(["--db", str(copy)], out=said.append)

    assert code == 2 and "did not look" in said[0] and "Python 3.12" in said[0]


def test_it_refuses_a_database_that_this_version_never_started(tmp_path: Path) -> None:
    old = Database(tmp_path / "old" / "encore.db")
    steps = Database._migrations()  # noqa: SLF001
    old.migrate(migrations=[step for step in steps if step[0] <= 15])
    said: list[str] = []

    code = rekey_audit.main(["--db", str(old.path)], out=said.append)

    assert code == 2 and "schema 15" in said[0] and "never started by this version" in said[0]


def test_it_refuses_a_file_that_is_not_a_database(tmp_path: Path) -> None:
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not a database" * 50)
    said: list[str] = []

    assert rekey_audit.main(["--db", str(junk)], out=said.append) == 2 and "not a database" in said[0]


def test_the_report_carries_ids_and_counts_and_no_title(db: Database) -> None:
    seed_old_world(db)
    keyrepair.repair(db)
    said: list[str] = []

    rekey_audit.main(["--db", str(copy_of(db))], out=said.append)

    text = said[0]
    for name in ("كيفك", "فيروز", "Группа", "Radiohead", "Weird Fishes"):
        assert name not in text
    assert R in text


# ----------------------------------------------------------------------------------------------------- the command a lead runs (audit_stack.py)


def run_check(db_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(AUDIT_STACK), "check", "rekey", "--db", str(db_file), "--python", sys.executable],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONPATH": str(SERVER)},
        timeout=120,
    )


def test_audit_stack_check_rekey_prints_fail_on_a_copy_made_by_the_old_code_and_pass_on_the_repaired_one(db: Database) -> None:
    seed_old_world(db)
    old_copy = copy_of(db)
    keyrepair.repair(db)
    link_library(db, Music(listing()))
    repaired = db.backup("audit-copy-repaired")

    before = run_check(old_copy)
    after = run_check(repaired)

    assert "FAIL" in before.stdout and before.returncode == 0, (
        before.stdout + before.stderr
    )  # the tool reports; its own exit code is for the tool
    assert "wanted: the repair is done" in before.stdout and "-> FAIL" in before.stdout
    assert "-> PASS" in after.stdout, after.stdout + after.stderr


def test_audit_stack_lists_rekey_in_its_usage_and_its_choices() -> None:
    text = AUDIT_STACK.read_text(encoding="utf-8")
    assert "check rekey" in text.split('"""')[1], "the docstring is the usage"
    assert '"rekey"' in text


def test_audit_stack_never_writes_to_the_database_it_is_given(db: Database) -> None:
    seed_old_world(db)
    keyrepair.repair(db)
    copy = copy_of(db)
    before = sha(copy)

    result = run_check(copy)

    assert result.returncode == 0 and sha(copy) == before


def test_the_check_is_one_function_of_the_module_not_a_second_copy_of_the_counting(db: Database) -> None:
    """audit_stack.py only runs the module (in the image of a stack, or on a database copy) and prints its verdict: the counting lives once, here, and is tested here."""
    text = AUDIT_STACK.read_text(encoding="utf-8")
    assert "encore_server.rekey_audit" in text and "ref_recheck" not in text and "norm_key" not in text
