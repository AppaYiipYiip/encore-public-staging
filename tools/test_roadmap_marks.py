"""Tests of "done" (tools/roadmap_plan.py mark / owner_action): the owner's rules are that he is not the tester and that "built, not walked" is the word until an item is
proven; so Claude marks items (the one writer of status.json), and what the owner does is a note, from which the state shown is derived."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_notes as rn  # noqa: E402
import roadmap_plan as rp  # noqa: E402
import roadmap_testkit as kit  # noqa: E402

T0 = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def iso(minutes: int) -> str:
    return rn.iso(at(minutes))


#: P1-01 is something only the owner can finish (kind owner); P1-02 is accepted by his own judgement; P1-03 is plain engineering
ITEMS = {"P1-01": {"title": "A", "kind": "owner"}, "P1-02": {"title": "B", "kind": "feature", "judge": True}, "P1-03": {"title": "C", "kind": "feature"}}
#: P1-03 needs nothing here (in the default chain it needs P1-02), so it can be walked or reopened by itself
FREE = kit.BASE_TASKS.replace("Needs: P1-02 [i]. Why: it says so.", "Needs: none.")


class MarkTests(unittest.TestCase):
    def tree(self, **kw) -> Path:
        kw.setdefault("items", ITEMS)
        return kit.tree(**kw)

    def status(self, d: Path) -> dict:
        return json.loads((d / "docs/roadmap/status.json").read_text(encoding="utf-8"))

    def test_walked_needs_a_proof_and_takes_the_item_out_of_the_list_in_one_step(self) -> None:
        d = self.tree(tasks=FREE)
        for ev in ("", "ok", "x" * 5):
            with self.assertRaises(rn.NoteError) as cm:
                rp.mark(d, "P1-03", "walked", ev)
            self.assertIn("proof", str(cm.exception))
        with self.assertRaises(rn.NoteError):
            rp.mark(d, "P1-03", "walked", "token ghp_" + "a" * 36)
        r = rp.mark(d, "P1-03", "walked", "walked on the pair, record b12", by="Claude (Sonnet 5.5)", now=iso(0))
        self.assertEqual((r["state"], r["in_order"]), ("walked", False))
        self.assertEqual(self.status(d)["P1-03"], {"state": "walked", "evidence": "walked on the pair, record b12", "at": iso(0), "by": "Claude (Sonnet 5.5)"})
        self.assertEqual(rp.load(d).order, ["P1-01", "P1-02"])
        self.assertEqual(rp.validate(rp.load(d))[0], [])                      # the files stay consistent
        self.assertEqual(rp.estimates(rp.load(d))["counts"]["done"], 1)

    def test_built_stays_in_the_list_and_an_unknown_item_or_state_is_refused(self) -> None:
        d = self.tree()
        rp.mark(d, "P1-02", "built", "built in #12; waits for the walk", now=iso(0))
        self.assertEqual(rp.load(d).order, ["P1-01", "P1-02", "P1-03"])
        self.assertEqual(rp.state_of(rp.load(d), "P1-02"), "built")
        for item, state in (("P9-99", "built"), ("P1-02", "finished")):
            with self.assertRaises(rn.NoteError):
                rp.mark(d, item, state, "x" * 20)

    def test_todo_after_walked_puts_the_item_back_at_the_top(self) -> None:
        d = self.tree(tasks=FREE, status={"P1-03": {"state": "walked", "evidence": "old record b01"}}, order=["P1-01", "P1-02"])
        rp.mark(d, "P1-03", "todo", "", now=iso(0))
        self.assertEqual(rp.load(d).order[0], "P1-03")


class OwnerActionTests(unittest.TestCase):
    def tree(self, **kw) -> Path:
        kw.setdefault("items", ITEMS)
        return kit.tree(**kw)

    def test_the_owner_finishes_what_only_he_can_finish_and_can_take_it_back(self) -> None:
        d = self.tree()
        rp.owner_action(d, "P1-01", "finish", "Made the keystore and backed it up.", now=at(0))
        p = rp.load(d)
        self.assertEqual((rp.state_of(p, "P1-01"), p.order), ("walked", ["P1-02", "P1-03"]))
        self.assertIn("Made the keystore", rp.evidence_of(p, "P1-01"))
        self.assertEqual(rp.validate(p)[0], [])                              # P1-02 needs P1-01: satisfied by his word
        self.assertEqual(rp.estimates(p)["counts"]["done"], 1)
        self.assertEqual(p.status, {})                                       # status.json was not touched: one writer
        rp.owner_action(d, "P1-01", "uncheck", now=at(5))
        p = rp.load(d)
        self.assertEqual((rp.state_of(p, "P1-01"), p.order[0]), ("todo", "P1-01"))
        self.assertEqual(rp.validate(p)[0], [])

    def test_his_word_does_not_finish_an_engineering_item_and_a_judge_check_only_records(self) -> None:
        d = self.tree()
        with self.assertRaises(rn.NoteError) as cm:
            rp.owner_action(d, "P1-03", "finish", "", now=at(0))
        self.assertIn("Claude proves it", str(cm.exception))
        with self.assertRaises(rn.NoteError):
            rp.owner_action(d, "P1-03", "judge", "", now=at(0))              # not an item of his judgement
        rp.owner_action(d, "P1-02", "judge", "Home knew me after a week.", now=at(0))
        p = rp.load(d)
        self.assertEqual(rp.state_of(p, "P1-02"), "todo")                    # his check records; it does not prove
        self.assertIn("P1-02", p.owner_checks)
        rp.mark(d, "P1-02", "walked", "walked on the pair, record b13", now=iso(10))
        self.assertIn("you checked it on 2026-11-04", json.loads((d / "docs/roadmap/status.json").read_text(encoding="utf-8"))["P1-02"]["evidence"])   # cited as part of the proof

    def test_a_problem_reopens_a_built_item_at_the_top_and_waits_for_claude(self) -> None:
        d = self.tree(status={"P1-02": {"state": "built", "evidence": "built"}})
        rp.owner_action(d, "P1-02", "problem", "Downloads stop at 40 percent.", now=at(0))
        p = rp.load(d)
        self.assertEqual((rp.state_of(p, "P1-02"), p.order[:2]), ("reopened", ["P1-01", "P1-02"]))      # as far forward as its own need (P1-01) allows
        self.assertEqual(rp.validate(p)[0], [])
        self.assertEqual([n["item"] for n in rn.inbox(rn.read_all(d)[0], "agent")], ["P1-02"])       # a note waiting for an agent
        self.assertGreater(rp.remaining_days(p, "P1-02"), 0)

    def test_a_problem_on_a_walked_item_reopens_it_without_breaking_the_rules_and_a_new_mark_closes_it(self) -> None:
        d = self.tree(tasks=FREE, status={"P1-03": {"state": "walked", "evidence": "walked on the pair, record b09", "at": iso(-60)}}, order=["P1-01", "P1-02"])
        rp.owner_action(d, "P1-03", "problem", "Lyrics never load.", now=at(0))
        p = rp.load(d)
        self.assertEqual((rp.state_of(p, "P1-03"), p.order[0]), ("reopened", "P1-03"))
        self.assertEqual(rp.validate(p)[0], [])                              # walked + in the list is fine while it is reopened
        self.assertEqual(rp.estimates(p)["counts"], {"done": 0, "built": 0, "reopened": 1, "left": 3, "all": 3, "later": 0})
        rp.mark(d, "P1-03", "walked", "fixed in #20 and walked again, record b14", now=iso(30))
        p = rp.load(d)
        self.assertEqual((rp.state_of(p, "P1-03"), "P1-03" in p.order), ("walked", False))
        self.assertEqual(rp.validate(p)[0], [])
        # a report made AFTER that mark reopens it again
        rp.owner_action(d, "P1-03", "problem", "Broken again on my phone.", now=at(90))
        self.assertEqual(rp.state_of(rp.load(d), "P1-03"), "reopened")

    def test_an_old_status_entry_without_a_time_is_reopened_by_any_report(self) -> None:
        d = self.tree(tasks=FREE, status={"P1-03": {"state": "walked", "evidence": "an old record from before times were kept"}}, order=["P1-01", "P1-02"])
        rp.owner_action(d, "P1-03", "problem", "It does not work.", now=at(0))
        self.assertEqual(rp.state_of(rp.load(d), "P1-03"), "reopened")

    def test_a_reopened_item_goes_to_the_front_but_never_before_what_it_needs(self) -> None:
        # P1-02 needs P1-01 [d], which is still in the list: P1-02 goes right after it, not to the very top
        d = self.tree(tasks=FREE, status={"P1-02": {"state": "built", "evidence": "built"}}, order=["P1-03", "P1-01", "P1-02"])
        rp.owner_action(d, "P1-02", "problem", "It does not work.", now=at(0))
        p = rp.load(d)
        self.assertEqual(p.order, ["P1-03", "P1-01", "P1-02"])
        self.assertEqual(rp.validate(p)[0], [])
        d2 = self.tree(tasks=FREE, status={"P1-03": {"state": "built", "evidence": "built"}}, order=["P1-01", "P1-02", "P1-03"])
        rp.owner_action(d2, "P1-03", "problem", "It does not work.", now=at(0))
        self.assertEqual(rp.load(d2).order[0], "P1-03")                       # nothing to wait for: the very front

    def test_reopening_something_does_not_make_what_stands_on_it_invalid(self) -> None:
        d = self.tree(status={"P1-01": {"state": "walked", "evidence": "record b01 on the pair", "at": iso(-60)},
                              "P1-02": {"state": "walked", "evidence": "record b02 on the pair", "at": iso(-50)}}, order=["P1-03"])
        self.assertEqual(rp.validate(rp.load(d))[0], [])
        rp.owner_action(d, "P1-01", "problem", "Broken.", now=at(0))
        p = rp.load(d)
        self.assertEqual(rp.state_of(p, "P1-01"), "reopened")
        self.assertEqual(rp.validate(p)[0], [])                              # P1-02 stays walked: a bug to fix is not a reason to un-walk it

    def test_a_problem_needs_something_built_and_a_sentence(self) -> None:
        d = self.tree()
        with self.assertRaises(rn.NoteError) as cm:
            rp.owner_action(d, "P1-03", "problem", "x", now=at(0))
        self.assertIn("nothing is built yet", str(cm.exception))
        d2 = self.tree(status={"P1-03": {"state": "built", "evidence": "b"}})
        with self.assertRaises(rn.NoteError):
            rp.owner_action(d2, "P1-03", "problem", "  ", now=at(0))
        with self.assertRaises(rn.NoteError):
            rp.owner_action(d2, "P1-03", "dance", "x", now=at(0))

    def test_the_generated_list_shows_the_derived_done_items_with_their_proof(self) -> None:
        d = self.tree()
        rp.owner_action(d, "P1-01", "finish", "Protected main.", now=at(0))
        text = rp.render_table(rp.load(d))
        self.assertIn("| P1-01 | A | you said you did this on 2026-11-04: Protected main. |", text)
        self.assertNotIn("| 1 | P1-01 |", text)                              # a done item is not in the numbered list


if __name__ == "__main__":
    unittest.main()
