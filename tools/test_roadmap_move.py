"""Tests of Now and Later (D-58) and of a move that CARRIES what it needs: the owner's drag is never refused for a need, other items move with it."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_plan as rp  # noqa: E402
import roadmap_testkit as kit  # noqa: E402

#: A, B needs A, C needs B, D free, E (policy need on C)
TASKS = ("## P1-01 — A — Size S\n* **Order.** Needs: none.\n"
         "## P1-02 — B — Size S\n* **Order.** Needs: P1-01 [d].\n"
         "## P1-03 — C — Size S\n* **Order.** Needs: P1-02 [d].\n"
         "## P1-04 — D — Size S\n* **Order.** Needs: none.\n"
         "## P1-05 — E — Size S\n* **Order.** Needs: P1-03 [p]. Why: a rule.\n")
ITEMS = {f"P1-0{i}": {"title": t, "kind": "feature"} for i, t in enumerate("ABCDE", 1)}


class MoveTests(unittest.TestCase):
    def plan(self, order, later=()):
        d = kit.tree(tasks=TASKS, items=ITEMS, order=list(order))
        rp.write_order(d, list(order), list(later))
        return d, rp.load(d)

    def move(self, p, item, to, before=None):
        return rp.move_item(p, item, to, before)

    def test_moving_up_brings_the_needs_along_just_before_it(self) -> None:
        d, p = self.plan(["P1-04", "P1-01", "P1-02", "P1-03", "P1-05"])
        now, later, also = self.move(p, "P1-03", "now", "P1-04")           # drop C in front of D
        self.assertEqual((now, later), (["P1-01", "P1-02", "P1-03", "P1-04", "P1-05"], []))
        self.assertEqual(sorted(also), ["P1-01", "P1-02"])

    def test_moving_down_pushes_what_needs_it_to_just_after_it(self) -> None:
        d, p = self.plan(["P1-01", "P1-02", "P1-03", "P1-04", "P1-05"])
        now, later, also = self.move(p, "P1-01", "now", "P1-05")           # drop A in front of E
        self.assertEqual(now, ["P1-04", "P1-01", "P1-02", "P1-03", "P1-05"])
        self.assertEqual(sorted(also), ["P1-02", "P1-03"])

    def test_moving_to_later_takes_everything_that_needs_it_along(self) -> None:
        d, p = self.plan(["P1-01", "P1-02", "P1-03", "P1-04", "P1-05"])
        now, later, also = self.move(p, "P1-02", "later")
        self.assertEqual((now, later), (["P1-01", "P1-04", "P1-05"], ["P1-02", "P1-03"]))          # C needs B, so it goes too; E only has a policy need
        self.assertEqual(also, ["P1-03"])

    def test_moving_to_now_brings_its_later_needs_along_in_front_of_it(self) -> None:
        d, p = self.plan(["P1-04"], later=["P1-01", "P1-02", "P1-03", "P1-05"])
        now, later, also = self.move(p, "P1-03", "now")
        self.assertEqual((now, later), (["P1-04", "P1-01", "P1-02", "P1-03"], ["P1-05"]))
        self.assertEqual(sorted(also), ["P1-01", "P1-02"])

    def test_a_move_inside_later_is_carried_the_same_way(self) -> None:
        d, p = self.plan(["P1-04"], later=["P1-01", "P1-02", "P1-03"])
        now, later, also = self.move(p, "P1-03", "later", "P1-01")
        self.assertEqual(later, ["P1-01", "P1-02", "P1-03"])                # C cannot go in front of what it needs
        self.assertEqual(now, ["P1-04"])

    def test_a_result_that_is_already_fine_moves_nothing_else(self) -> None:
        d, p = self.plan(["P1-01", "P1-02", "P1-04"])
        now, later, also = self.move(p, "P1-04", "now", "P1-01")
        self.assertEqual((now, also), (["P1-04", "P1-01", "P1-02"], []))

    def test_the_board_save_carries_and_reports_what_moved(self) -> None:
        d, p = self.plan(["P1-01", "P1-02", "P1-03", "P1-04", "P1-05"])
        code, body = rp.apply_move(d, {"version": p.version, "item": "P1-02", "to": "later"})
        self.assertEqual((code, body["also_moved"]), (200, ["P1-03"]))
        q = rp.load(d)
        self.assertEqual((q.order, q.later), (["P1-01", "P1-04", "P1-05"], ["P1-02", "P1-03"]))
        self.assertEqual(rp.validate(q)[0], [])
        self.assertEqual(rp.apply_move(d, {"version": p.version, "item": "P1-02", "to": "now"})[0], 409)       # the page was stale
        self.assertEqual(rp.apply_move(d, {"version": q.version, "item": "P9-99", "to": "now"})[0], 400)
        self.assertEqual(rp.apply_move(d, {"version": q.version, "item": "P1-02", "to": "somewhere"})[0], 400)


class ListRulesTests(unittest.TestCase):
    def tree(self, order, later):
        d = kit.tree(tasks=TASKS, items=ITEMS, order=list(order))
        rp.write_order(d, list(order), list(later))
        return rp.load(d)

    def test_a_now_item_that_needs_a_later_item_is_an_error_but_a_policy_need_only_warns(self) -> None:
        p = self.tree(["P1-02", "P1-04", "P1-05"], ["P1-01", "P1-03"])
        errs, warns = rp.validate(p)
        self.assertTrue(any("P1-02 is in Now but needs P1-01, which is in Later" in e for e in errs), errs)
        self.assertTrue(any("P1-05 is in Now but needs P1-03, which is in Later" in w for w in warns), warns)

    def test_later_work_may_need_what_is_being_built_now_and_order_inside_later_is_checked(self) -> None:
        self.assertEqual(rp.validate(self.tree(["P1-01", "P1-04"], ["P1-02", "P1-03", "P1-05"]))[0], [])
        errs, _ = rp.validate(self.tree(["P1-01", "P1-04"], ["P1-03", "P1-02", "P1-05"]))
        self.assertTrue(any("P1-03 comes before P1-02" in e for e in errs), errs)

    def test_an_id_in_both_lists_or_in_neither_is_an_error_and_estimates_count_only_now(self) -> None:
        errs, _ = rp.validate(self.tree(["P1-01", "P1-02", "P1-03", "P1-04"], ["P1-04", "P1-05"]))
        self.assertTrue(any("P1-04 appears 2 times" in e for e in errs), errs)
        errs, _ = rp.validate(self.tree(["P1-01", "P1-02", "P1-03"], ["P1-05"]))
        self.assertTrue(any("P1-04: in no place of the plan" in e for e in errs), errs)
        p = self.tree(["P1-01", "P1-02"], ["P1-03", "P1-04", "P1-05"])
        self.assertEqual(rp.estimates(p)["counts"], {"done": 0, "built": 0, "reopened": 0, "left": 2, "all": 2, "later": 3})
        self.assertEqual(set(rp.estimates(p)["items"]), {"P1-01", "P1-02"})

    def test_write_order_keeps_later_when_it_is_not_given_and_the_generated_list_shows_it(self) -> None:
        d = kit.tree(tasks=TASKS, items=ITEMS, order=["P1-01", "P1-02"])
        rp.write_order(d, ["P1-01", "P1-02", "P1-04"], ["P1-03", "P1-05"])
        rp.write_order(d, ["P1-04", "P1-01", "P1-02"])                       # an old caller that knows nothing about Later
        self.assertEqual(rp.load(d).later, ["P1-03", "P1-05"])
        self.assertIn("**Later** (2 items", rp.render_table(rp.load(d)))

    def test_ideas_can_go_to_later_and_mark_walked_removes_from_both(self) -> None:
        d = kit.tree(tasks=TASKS, items=ITEMS, order=["P1-01", "P1-02", "P1-03", "P1-05"])
        rp.write_order(d, ["P1-01", "P1-02", "P1-03", "P1-05"], ["P1-04"])
        a = rp.add_idea(d, "Play a song from Alexa", "", "feature", "M", "Owner", position="later")
        self.assertEqual(rp.load(d).later, ["P1-04", a["id"]])
        rp.mark(d, "P1-04", "walked", "walked on the pair, record b30")          # P1-04 needs nothing
        self.assertEqual(rp.load(d).later, [a["id"]])
        self.assertEqual(rp.validate(rp.load(d))[0], [])


if __name__ == "__main__":
    unittest.main()
