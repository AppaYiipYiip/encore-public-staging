"""The expiry guard of the P2-25 stop-gaps (slice 4): a marked piece of code that has outlived its removal trigger FAILS the suite, so the reminder cannot be ignored.

**The stop-gap.** One kind is left, written by P2-25 and meant to go one release after the release that carries it (the owner's standing rule: a stop-gap says what it
costs, has a removal trigger, a task and a visible reminder). (The second kind, `skip-rule`, the guards of N-34's `album_finder.py`, was removed on 17 Nov 2026 in the
clean-up after slices 2 and 3, #115: nothing carries that marker now, and the inventory below fails if one comes back unlisted.)

* `STOP-GAP(P2-25 one-shot-repair; ...)`: the worklist table, `rehome.py`, `keyrepair._lost_by_old_fold`, the `recheck_pending` hold of `refmerge`, the voided covers and
  `tests/legacy_fold.py`: a one-time repair of data the old text fold made. Trigger: the worklist is empty on every install the project knows (read with
  `audit_stack.py check rekey`, never assumed) and one release has passed. Task: board item N-36.

**What "a release has passed" means here, and its limit (said plainly).** The repository has no release yet (P5-06: `CHANGELOG.md` says "Unreleased", the version is 0.1.0, the
image is tagged `v*` only for a release). The one machine-readable thing that moves at a release is the server's own version, `encore_server.__version__` (the `serverVersion` of
`/info`). So every marker names `remove after X.Y.Z`, the version of the release that CARRIES the piece, and this test fails when the version is PAST it. **The assumption**:
the first release is cut as 0.1.0 and a later release raises `__version__`. If the first release is cut under another number, this test fails in that very commit: the person who
cuts it sets every marker to that number (the failure message says how) and the clock starts there. What no test can do is know that a release was cut without the version being
raised: that is a convention, and it is written in `docs/30` section 5 and `docs/tasks/RELEASE-CANDIDATE.md` 4b.

**Not a way to silence it.** The inventory below pins which files carry which marker AND the piece each marker stands for, so deleting only the comment leaves the piece
without its marker and fails here; deleting the piece and its marker is the removal itself, and it edits the inventory in the same change.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from encore_server import __version__

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parents[1]
SCANNED = [SERVER / "encore_server", SERVER / "tests"]
#: `STOP-GAP(P2-25 <name>; remove after X.Y.Z)`: the name is lower case and dashed; the release is the one that CARRIES the piece.
MARKER = re.compile(r"STOP-GAP\(P2-25 (?P<name>[a-z][a-z-]*)(?P<rest>[^)]*)\)")
RELEASE = re.compile(r"^; remove after (?P<release>\d+\.\d+\.\d+)$")


@dataclass(frozen=True)
class Marker:
    file: str
    line: int
    name: str
    release: str | None


def found(roots: list[Path] = SCANNED) -> list[Marker]:
    """Every marker in the server's source and its tests. This file is not scanned: it names the marker to explain it. (A migration is never edited once it has run, so the
    comment of `0018_ref_recheck.sql` carries no release; the table it creates is dropped by a NEW migration, which is N-36, and `ref_janitor.py` / `keyrepair.py` carry the markers.)"""
    markers: list[Marker] = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.suffix != ".py" or "__pycache__" in path.parts or path.name == Path(__file__).name:
                continue
            for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                for match in MARKER.finditer(text):
                    named = RELEASE.match(match["rest"])
                    shown = path.relative_to(SERVER) if path.is_relative_to(SERVER) else path
                    markers.append(Marker(shown.as_posix(), number, match["name"], named["release"] if named else None))
    return markers


def version_of(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def expired(markers: list[Marker], current: str) -> list[Marker]:
    """The markers whose release is BEHIND [current]. A marker with no release it can read counts as expired: a reminder that cannot ring is the thing to avoid."""
    now = version_of(current)
    return [m for m in markers if m.release is None or version_of(m.release) < now]


def message(late: list[Marker], current: str) -> str:
    where = "\n".join(f"  {m.file}:{m.line}  STOP-GAP(P2-25 {m.name}), remove after {m.release}" for m in late)
    return (
        f"The server is at version {current} and these stop-gaps of P2-25 were to be gone after the release that carries them:\n{where}\n"
        "Delete them: board item N-36 lists every piece (the worklist table with a migration that drops it, rehome.py, keyrepair._lost_by_old_fold, the recheck_pending hold, "
        "tests/legacy_fold.py) and their tests, and this inventory. Do it only when `python docs/evidence/scripts/audit_stack.py check rekey` "
        "says the worklist is empty on every install the project knows. If instead this is the FIRST release (the version was raised to the number it ships under), set "
        "`remove after` of every marker to that number. If the trigger has really not been met, move the release on AND write why in a board note on N-36. "
        "Never delete only the comment: the inventory in tests/test_stopgap_expiry.py fails then."
    )


# ---------------------------------------------------------------------------------------------------------------------------------------------------


def test_every_p2_25_stop_gap_names_the_release_after_which_it_must_be_gone() -> None:
    markers = found()
    assert markers, "the scan sees no marker: a silent no-op is the failure to avoid"
    unreadable = [m for m in markers if m.release is None]
    assert not unreadable, "a marker without `; remove after X.Y.Z`: " + ", ".join(f"{m.file}:{m.line}" for m in unreadable)


def written_in_pyproject() -> str:
    text = (SERVER / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', text, re.MULTILINE)
    assert match, 'pyproject.toml has no version = "X.Y.Z"'
    return match.group(1)


def the_servers_version() -> str:
    """The later of the two places the version is written, so a release that raises only one of them still rings the alarm (and the test below says they must agree)."""
    return max(__version__, written_in_pyproject(), key=version_of)


def test_the_two_places_the_servers_version_is_written_agree() -> None:
    """`encore_server.__version__` (the `serverVersion` of `/info`) and `pyproject.toml` (the image's package): a release raises both, and the clock above reads the later one."""
    assert __version__ == written_in_pyproject(), "raise the version in encore_server/__init__.py and in pyproject.toml together"


def test_no_marked_piece_outlives_the_release_it_names() -> None:
    now = the_servers_version()
    late = expired(found(), now)
    assert not late, message(late, now)


def test_the_alarm_can_ring_a_version_past_the_release_fails_every_marker_and_the_release_itself_does_not() -> None:
    """The control of the test above (an alarm that cannot ring is no alarm): on a pretend current version past the release the same markers fail, with the message that says what to do."""
    markers = found()
    assert expired(markers, "0.1.0") == [], "the release that CARRIES the pieces is allowed to carry them"
    assert expired(markers, "0.1.1") == markers and expired(markers, "0.2.0") == markers and expired(markers, "1.0.0") == markers
    assert expired(markers, "0.0.9") == [], "a version before the release is not past it"
    ten = [Marker("x.py", 1, "one-shot-repair", "0.9.0")]
    assert expired(ten, "0.10.0") == ten, "compared as numbers, not as text ('0.10.0' sorts before '0.9.0' as text)"
    text = message(markers, "0.2.0")
    assert "N-36" in text and "audit_stack.py check rekey" in text and "Never delete only the comment" in text and "0.2.0" in text


def test_a_marker_that_names_no_release_counts_as_late_so_a_reminder_cannot_be_written_that_never_rings() -> None:
    bare = [Marker("x.py", 1, "one-shot-repair", None)]
    assert expired(bare, "0.0.1") == bare


@pytest.mark.parametrize(
    ("text", "release"),
    [
        ("# STOP-GAP(P2-25 one-shot-repair; remove after 0.1.0): x", "0.1.0"),
        ("STOP-GAP(P2-25 one-shot-repair): goes with the worklist (N-36).", None),
        ("STOP-GAP(P2-25 one-shot-repair; remove after soon)", None),
        ("STOP-GAP(P2-25 one-shot-repair; remove after 0.1)", None),
    ],
)
def test_the_scanner_reads_the_marker_and_refuses_a_release_it_cannot_parse(
    text: str, release: str | None, tmp_path: Path
) -> None:
    (tmp_path / "a.py").write_text(text + "\n", encoding="utf-8")
    (marker,) = found([tmp_path])
    assert marker.release == release


# ----------------------------------------------------------------------------------------------------------------------------------- the inventory

#: marker name -> {file (from the server folder): a piece of text that file holds because of the stop-gap}. A piece that is still there without its marker, or a marker
#: whose piece is gone, fails: the removal (N-36) edits this table in the same change as the code.
INVENTORY: dict[str, dict[str, str]] = {
    "one-shot-repair": {
        "encore_server/keyrepair.py": "def _lost_by_old_fold(",
        "encore_server/rehome.py": "class Rehome:",
        "encore_server/refs.py": "def recheck_pending(",
        "encore_server/refmerge.py": '"recheck_pending"',
        "encore_server/ref_janitor.py": "DELETE FROM ref_recheck",
        "tests/legacy_fold.py": "def norm_key(",
    },
}


def test_the_inventory_of_marked_pieces_is_the_scan_of_the_markers() -> None:
    markers = found()
    actual: dict[str, set[str]] = {}
    for m in markers:
        actual.setdefault(m.name, set()).add(m.file)
    assert actual == {name: set(files) for name, files in INVENTORY.items()}, (
        "a marker was added or removed: a new stop-gap needs a line in INVENTORY (and a task and a trigger); a removed one is N-36 and edits INVENTORY with it"
    )
    assert not [m for m in markers if m.name == "skip-rule"], (
        "the guards of album_finder.py were removed with #115: a skip-rule marker is a guard that came back"
    )


@pytest.mark.parametrize(("name", "file", "piece"), [(n, f, p) for n, files in INVENTORY.items() for f, p in files.items()])
def test_the_piece_a_marker_stands_for_is_still_there_next_to_its_marker(name: str, file: str, piece: str) -> None:
    """Deleting only the comment leaves the piece with no reminder: that fails here. (Deleting the piece too is the removal; its marker and this row go with it.)"""
    text = (SERVER / file).read_text(encoding="utf-8")
    assert piece in text, (
        f"{file} no longer holds {piece!r}: if the piece was removed on purpose (N-36), remove its marker's row from INVENTORY"
    )
    assert f"STOP-GAP(P2-25 {name};" in text, (
        f"{file} still holds {piece!r} but its STOP-GAP(P2-25 {name}) marker is gone: the reminder must stay while the piece does"
    )


def test_the_task_stays_on_the_board() -> None:
    """The removal trigger has a task, N-36 (its scope is in its board notes, which may be reworded freely), so `roadmap.py brief` and the board show it."""
    items = json.loads((REPO / "docs" / "roadmap" / "items.json").read_text(encoding="utf-8"))
    assert "N-36" in items and items["N-36"]["needs"] == [{"id": "P2-25", "mark": "d"}]
