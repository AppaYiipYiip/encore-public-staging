"""Builds a tiny plan in a temporary folder, for the tests of the order check and of the local roadmap board (one helper, not two copies)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_plan as rp  # noqa: E402

BASE_TASKS = (
    "## P1-01 — A — Size S\n* **Order.** Needs: none.\n"
    "## P1-02 — B — Size M\n* **Order.** Needs: P1-01 [d].\n"
    "## P1-03 — C — Size L\n* **Order.** Needs: P1-02 [i]. Why: it says so.\n"
)
GOOD_ORDER = ["P1-01", "P1-02", "P1-03"]
ROAD = "# roadmap\n" + rp.BEGIN + "\n" + rp.END + "\n"        # the explanation, with the markers where the generated list goes
ITEMS = {"P1-01": {"title": "A", "kind": "feature"}, "P1-02": {"title": "B", "kind": "feature"}, "P1-03": {"title": "C", "kind": "feature"}}


def tree(tasks: str = BASE_TASKS, order: list | None = None, status: dict | None = None, items: dict | None = None, road: str | None = None, proposed: str | None = None) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "docs/tasks").mkdir(parents=True)
    (d / "docs/roadmap").mkdir(parents=True)
    (d / "docs/tasks/P1.md").write_text(tasks, encoding="utf-8")
    if proposed is not None:
        (d / "docs/tasks/PROPOSED.md").write_text(proposed, encoding="utf-8")
    (d / "docs/08-roadmap.md").write_text(road or ROAD, encoding="utf-8")
    (d / "docs/roadmap/items.json").write_text(json.dumps(items or ITEMS), encoding="utf-8")
    (d / "docs/roadmap/status.json").write_text(json.dumps(status or {}), encoding="utf-8")
    rp.write_order(d, order if order is not None else GOOD_ORDER)
    return d
