"""Tests of the plan library's newer rules (tools/roadmap_plan.py): a foreign key in order.json, and an idea typed on the board."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_notes as rn  # noqa: E402
import roadmap_plan as rp  # noqa: E402
import roadmap_testkit as kit  # noqa: E402


class PlanTests(unittest.TestCase):
    def errors(self, d: Path) -> list[str]:
        return rp.validate(rp.load(d))[0]

    def test_a_save_counter_left_in_order_json_by_an_old_writer_is_an_error(self) -> None:
        d = kit.tree()
        p = d / "docs/roadmap/order.json"
        p.write_text(p.read_text(encoding="utf-8").replace('{\n', '{\n  "version": 26,\n', 1), encoding="utf-8")
        self.assertTrue(any("unknown key" in e and "version" in e for e in self.errors(d)))

    def test_an_idea_becomes_the_next_proposal_and_is_valid_before_any_write_up_exists(self) -> None:
        d = kit.tree()
        a = rp.add_idea(d, "A better logo", "Something that works on a dark launcher.", "design", "S", "Owner")
        b = rp.add_idea(d, "Dark mode for the admin pages", "", "host", "M", "Owner")
        self.assertEqual((a["id"], b["id"]), ("N-01", "N-02"))
        items = json.loads((d / "docs/roadmap/items.json").read_text(encoding="utf-8"))
        self.assertEqual(items["N-01"], {"kind": "design", "title": "A better logo", "note": "Something that works on a dark launcher.",
                                         "proposal": True, "pending": True, "size": "S", "needs": [], "from": "Owner"})
        self.assertEqual(self.errors(d), [])
        self.assertEqual(items["P1-01"], kit.ITEMS["P1-01"])                       # nothing else was touched

    def test_an_idea_goes_straight_into_the_one_list_at_the_end_or_at_the_top(self) -> None:
        d = kit.tree()
        a = rp.add_idea(d, "Share links", "", "feature", "M", "Owner")
        self.assertEqual((a["id"], a["position"], rp.load(d).order), ("N-01", "end", ["P1-01", "P1-02", "P1-03", "N-01"]))
        b = rp.add_idea(d, "Sleep timer", "", "feature", "S", "Owner", position="top")
        self.assertEqual((b["id"], rp.load(d).order[:2]), ("N-02", ["N-02", "P1-01"]))
        self.assertEqual(self.errors(d), [])                                              # an idea in the list needs no write-up yet
        self.assertEqual(rp.estimates(rp.load(d))["items"]["N-01"]["days"], 3)
        with self.assertRaises(rn.NoteError):
            rp.add_idea(d, "x", "", "feature", "M", "Owner", position="middle")

    def test_a_pending_idea_that_got_its_row_must_lose_the_flag_and_a_row_needs_an_idea(self) -> None:
        d = kit.tree()
        rp.add_idea(d, "Share links", "", "feature", "M", "Owner")
        (d / "docs/tasks/PROPOSED.md").write_text("| N-01 | to share a link |\n", encoding="utf-8")
        self.assertTrue(any("list different proposals" in e for e in self.errors(d)))     # row written, `pending` still set
        f = d / "docs/roadmap/items.json"
        items = json.loads(f.read_text(encoding="utf-8"))
        del items["N-01"]["pending"]
        f.write_text(json.dumps(items), encoding="utf-8")
        self.assertEqual(self.errors(d), [])                                               # row written and flag removed: consistent
        (d / "docs/tasks/PROPOSED.md").write_text("| N-01 | x |\n| N-07 | no idea behind this row |\n", encoding="utf-8")
        self.assertTrue(any("N-07" in e for e in self.errors(d)))

    def test_a_bad_idea_is_refused_and_the_file_is_untouched(self) -> None:
        d = kit.tree()
        before = (d / "docs/roadmap/items.json").read_bytes()
        for args, word in ((("", "", "feature", "M", "o"), "short title"), (("t" * 121, "", "feature", "M", "o"), "short title"),
                           (("x", "n" * 601, "feature", "M", "o"), "too long"), (("x", "", "process", "M", "o"), "kind"),
                           (("x", "", "feature", "XL", "o"), "size"), (("x", "token ghp_" + "d" * 36, "feature", "M", "o"), "GitHub token")):
            with self.assertRaises(rn.NoteError, msg=args) as cm:
                rp.add_idea(d, *args)
            self.assertIn(word, str(cm.exception))
        self.assertEqual((d / "docs/roadmap/items.json").read_bytes(), before)

    def test_the_real_items_file_round_trips_byte_for_byte(self) -> None:
        raw = (rp.ROOT / "docs/roadmap/items.json").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(json.dumps(json.loads(raw), indent=1, ensure_ascii=False) + "\n", raw)      # so adding an idea is a one-item diff




class TitleRuleTests(unittest.TestCase):
    """D-59: titles are plain words (the owner is not a coder), and invisible work says so."""

    def errors(self, title, kind="feature", extra=None):
        items = {**kit.ITEMS, "P1-01": {"title": title, "kind": kind}, **(extra or {})}
        d = kit.tree(items=items)
        return rp.validate(rp.load(d))

    def test_behind_the_scenes_must_match_the_kind_both_ways(self) -> None:
        e, _ = self.errors("Behind the scenes: tidy the code", "plumbing")
        self.assertEqual(e, [])
        e, _ = self.errors("Behind the scenes: tidy the code", "feature")
        self.assertTrue(any("kind is feature" in x for x in e), e)
        e, _ = self.errors("Tidy the code", "plumbing")
        self.assertTrue(any("must start with" in x for x in e), e)

    def test_ids_and_jargon_are_refused_in_a_title_but_ordinary_words_pass(self) -> None:
        for bad, word in (("Finish P2-22 first", "item id"), ("Fix the CI", "CI"), ("Walk record b11", "b11"), ("Move to Docker", "Docker")):
            e, _ = self.errors(bad)
            self.assertTrue(any(word in x for x in e), (bad, e))
        e, w = self.errors("A Home made for you: smart shuffle, radio and \"Not for me\"")
        self.assertEqual((e, w), ([], []))                                      # whole words, case-sensitive: "smart" is not "SMART", "circuit" is not "CI"

    def test_a_long_title_only_warns(self) -> None:
        e, w = self.errors(" ".join(["word"] * 17))
        self.assertEqual(e, [])
        self.assertTrue(any("17 words" in x for x in w), w)

    def test_an_item_only_the_owner_can_do_costs_no_claude_days(self) -> None:
        d = kit.tree(items={**kit.ITEMS, "P1-01": {"title": "Make the key", "kind": "owner"}})
        p = rp.load(d)
        self.assertEqual(rp.remaining_days(p, "P1-01"), 0.0)
        self.assertGreater(rp.remaining_days(p, "P1-02"), 0.0)
        self.assertEqual(rp.estimates(p)["items"]["P1-01"]["remaining"], 0.0)


if __name__ == "__main__":
    unittest.main()
