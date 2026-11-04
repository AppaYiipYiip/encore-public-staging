#!/usr/bin/env python3
"""The order of the plan, checked by a machine (docs/08). The rules live in tools/roadmap_plan.py; this is the command CI runs.

A task id (P2-12) names a TOPIC, never a time. Time is the sequence in docs/roadmap/order.json: ONE flat list, no phases and no groups (D-57).

Fails when:
  * a task has no `* **Order.** Needs: ...` line, no plain-words title, or is in no place of the plan (neither in order.json nor walked);
  * an item comes BEFORE something it hard-needs ([d] declared, [i] inferred), needs something unknown, or a walked item needs an unwalked one;
  * order.json has a duplicate, an unknown id, an entry that is not an id (an old milestone divider), a key besides "order", or lists something that is walked;
  * status.json names a bad state, or says walked without evidence;
  * the generated list in docs/08 is stale;
  * a note under docs/roadmap/notes is malformed, misnamed, points at nothing, or looks like a secret (a note about an item that left the plan only warns).
Policy needs `[p]` (a rule the project chose, such as "tablet only after the public release") only WARN: the owner may override them knowingly.

Usage:  python -I tools/check_order.py [--write] [--selftest]
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_plan as rp  # noqa: E402
import roadmap_notes as rn  # noqa: E402


def selftest() -> int:
    import roadmap_testkit as kit

    base, good = kit.BASE_TASKS, kit.GOOD_ORDER
    walked = {"P1-01": {"state": "walked", "evidence": "b01"}}

    def run(d: Path) -> tuple[list[str], list[str]]:
        return rp.validate(rp.load(d))

    e, w = run(kit.tree())
    assert not e and not w, (e, w)

    def expect(d: Path, word: str) -> None:
        e2, w2 = run(d)
        assert any(word in m for m in e2), (word, e2, w2)

    expect(kit.tree(order=["P1-02", "P1-01", "P1-03"]), "comes before P1-01")                              # a hard need after its user
    expect(kit.tree(order=["P1-01", "P1-02"]), "in no place of the plan")                                    # a task nowhere
    expect(kit.tree(order=["P1-01", "P1-02", "P1-02", "P1-03"]), "appears 2 times")
    expect(kit.tree(order=["P1-01", "P1-02", "P1-03", "P9-99"]), "not a task or a proposal")
    expect(kit.tree(order=[{"milestone": "M0"}, "P1-01", "P1-02", "P1-03"]), "is not an item id")             # the phases are gone (D-57)
    expect(kit.tree(tasks=base.replace("* **Order.** Needs: none.", "no line")), "no `* **Order.**")
    expect(kit.tree(tasks=base.replace(" Why: it says so.", "")), "no `Why:`")
    expect(kit.tree(status={"P1-01": {"state": "walked"}}), "names no evidence")
    expect(kit.tree(status=walked), "is walked, so it must leave the lists")
    expect(kit.tree(items={"P1-01": {"title": "A", "kind": "feature"}}), "no plain-words title")
    expect(kit.tree(proposed="| N-01 | x |\n"), "list different proposals")
    # a walked need satisfies a task that is no longer preceded by it in the list
    e3, _ = run(kit.tree(order=["P1-02", "P1-03"], status=walked))
    assert not e3, e3
    # a policy need only warns
    pol = base.replace("Needs: P1-01 [d].", "Needs: P1-01 [p]. Why: a rule of the plan.")
    e4, w4 = run(kit.tree(tasks=pol, order=["P1-02", "P1-01", "P1-03"]))
    assert not e4 and any("comes before P1-01" in m for m in w4), (e4, w4)
    # the board's save: a stale token, a hard violation, an entry that is not an id, a good move, a stale token again.
    # (P1-03 needs nothing here, so it may move freely; P1-02 still needs P1-01.)
    free = base.replace("Needs: P1-02 [i]. Why: it says so.", "Needs: none.")
    d = kit.tree(tasks=free)
    tok = rp.load(d).version
    assert rp.apply_order(d, {"version": "stale", "order": good})[0] == 409
    assert rp.apply_order(d, {"version": tok, "order": ["P1-02", "P1-01", "P1-03"]})[0] == 400
    assert rp.apply_order(d, {"version": tok, "order": [{"milestone": "M0"}, "P1-01", "P1-02", "P1-03"]})[0] == 400
    code, body = rp.apply_order(d, {"version": tok, "order": ["P1-03", "P1-01", "P1-02"]})
    assert code == 200 and body["version"] != tok, (code, body)
    assert rp.load(d).order == ["P1-03", "P1-01", "P1-02"]
    assert rp.apply_order(d, {"version": tok, "order": good})[0] == 409          # the token of the old file no longer fits
    # a problem that was already there (a missing plain title) must not block a drag the owner cannot fix on the board
    d4 = kit.tree(tasks=free, items={"P1-01": {"title": "A", "kind": "feature"}, "P1-02": {"title": "B", "kind": "feature"}})
    assert rp.validate(rp.load(d4))[0], "the plan was meant to have an old error"
    code4, _ = rp.apply_order(d4, {"version": rp.load(d4).version, "order": ["P1-03", "P1-01", "P1-02"]})
    assert code4 == 200, code4
    # estimates: a lone L cannot be split across agents (the floor), and a built item costs only a share
    d2 = kit.tree(order=["P1-03"], status={"P1-01": {"state": "walked", "evidence": "b"}, "P1-02": {"state": "walked", "evidence": "b"}})
    assert rp.estimates(rp.load(d2))["items"]["P1-03"]["lo"] >= 7
    d3 = kit.tree(status={"P1-01": {"state": "built"}})
    assert rp.remaining_days(rp.load(d3), "P1-01") == rp.BUILT_REMAINING * 1
    c = rp.estimates(rp.load(d3))["counts"]
    assert (c["done"], c["built"], c["left"], c["all"]) == (0, 1, 3, 3), c
    print("check_order selftest passed (one flat list, policy versus hard needs, walked items, the board's save and its conflicts, the estimate floor)")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    p = rp.load()
    errors, warnings = rp.validate(p)
    note_errors, note_warnings = rn.validate_files(rp.ROOT, set(p.tasks) | set(p.items))      # docs/roadmap/notes: well-formed, no secret, replies point somewhere
    errors += note_errors
    warnings += note_warnings
    ok, table = rp.refresh_roadmap(p)
    road = (rp.ROOT / rp.ROADMAP).read_text(encoding="utf-8").replace("\r\n", "\n")
    if not ok:
        errors.append(f"{rp.ROADMAP}: the markers `{rp.BEGIN}` ... `{rp.END}` are missing")
    elif "--write" in argv:
        (rp.ROOT / rp.ROADMAP).write_text(table, encoding="utf-8")
        print("generated lists written to", rp.ROADMAP)
    elif table != road:
        errors.append(f"{rp.ROADMAP}: the generated lists are stale (run: python -I tools/check_order.py --write)")
    for w in warnings:
        print("  warning (a policy the owner may override):", w)
    if errors:
        print("ORDER CHECK FAILED:")
        for e in errors:
            print("  -", e)
        return 1
    n_order = len(rp.flat_ids(p.order))
    print(f"order check passed: {len(p.tasks)} tasks ({n_order} in the plan, {sum(1 for s in p.status.values() if s.get('state') == 'walked')} walked), "
          f"one flat list, nothing comes before what it needs; {len(warnings)} policy warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
