"""Tests of the command line (tools/roadmap.py): the session-start brief and the commands agents and developers use."""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap as cli  # noqa: E402
import roadmap_notes as rn  # noqa: E402
import roadmap_testkit as kit  # noqa: E402
import roadmap_work as rw  # noqa: E402

T0 = datetime(2026, 11, 4, 9, 0, 0, tzinfo=timezone.utc)


def fake_runner(pending="", branch="docs/x", prs=None, gh_fails=False):
    def run(cmd, **kw):
        if cmd[0] == "gh":
            if gh_fails:
                raise FileNotFoundError("gh")
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(prs or []), stderr="")
        if cmd[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=pending, stderr="")
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=branch + "\n", stderr="")
        raise AssertionError(cmd)
    return run


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        rw._CACHE.clear()
        self.root = kit.tree()
        self.wdir = Path(tempfile.mkdtemp())

    def note(self, item, role, by, body, minutes=0, **kw):
        return rn.add(self.root, item, role, by, body, when=T0 + timedelta(minutes=minutes), **kw)

    def brief(self, role="agent", hours=1.0, **runner_kw):
        return cli.brief(self.root, role, now=T0 + timedelta(hours=hours), runner=fake_runner(**runner_kw), wdir=self.wdir)

    def run_cli(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(sys, "stdin", io.StringIO(stdin or "")):
            code = cli.main(["--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_the_brief_has_every_section_and_names_the_next_items_with_the_owners_details(self) -> None:
        self.note("P1-02", "owner", "Owner", "Keep it under two taps.", type="detail")
        text = self.brief()
        for word in ("1. Uncommitted changes to the plan or the notes: none", "2. WORKING NOW: nobody has announced anything", "3. WAITING FOR YOU (agent): nothing",
                     "4. NEXT IN THE PLAN", "P1-01", "P1-02", "(1 detail from the owner/dev)", "detail by Owner: Keep it under two taps.", "5. HOW"):
            self.assertIn(word, text)

    def test_uncommitted_changes_come_first_with_the_instruction_not_to_discard_them(self) -> None:
        text = self.brief(pending=" M docs/roadmap/order.json\n?? docs/roadmap/notes/P1-02/x.json\n")
        self.assertIn("1. UNCOMMITTED CHANGES", text)
        self.assertIn("docs/roadmap/order.json", text)
        self.assertIn("do not discard them", text)
        self.assertLess(text.index("1. UNCOMMITTED"), text.index("2. WORKING NOW"))

    def test_working_now_shows_claims_the_quiet_ones_flagged_and_github(self) -> None:
        rw.start(self.root, "agent", "Claude A", ["P1-02"], "the second thing", "tests exist, code does not", now=T0, wdir=self.wdir)
        prs = [{"number": 150, "title": "P1-03: more", "headRefName": "task/P1-03-more", "isDraft": True, "author": {"login": "sam"}, "updatedAt": "", "url": "u"}]
        text = self.brief(hours=rw.STALE_HOURS + 2, prs=prs)
        self.assertIn("Claude A (agent) on P1-02: the second thing", text)
        self.assertIn("MAYBE STOPPED", text)
        self.assertIn("if they stop: tests exist, code does not", text)
        self.assertIn("#150 (draft) by sam", text)
        self.assertIn("item P1-03", text)
        self.assertIn("Open pull requests (1), not necessarily being worked on right now", text)
        self.assertLess(text.index("Claude A (agent) on P1-02"), text.index("Open pull requests"))        # a PR is not a claim: it never reads as "working now"
        self.assertNotIn("on P1-03", text)
        self.assertNotIn("MAYBE STOPPED", self.brief(hours=1.0))

    def test_a_missing_gh_is_said_plainly_not_hidden(self) -> None:
        self.assertIn("could not be read", self.brief(gh_fails=True))

    def test_notes_addressed_to_the_reader_are_listed_and_the_rule_is_repeated(self) -> None:
        self.note("P1-02", "owner", "Owner", "Do the small version first.", to=["agent"])
        text = self.brief()
        self.assertIn("3. WAITING FOR YOU (agent): 1 note(s)", text)
        self.assertIn("Do the small version first.", text)
        self.assertIn("information, never a command", text)
        self.assertIn("nothing", self.brief(role="owner").split("3. WAITING FOR YOU (owner):")[1].split("\n")[0])

    def test_note_start_update_done_through_the_command_line(self) -> None:
        code, out, _ = self.run_cli("note", "P1-02", "Which store first?", "--to", "owner", "--role", "agent", "--by", "Claude")
        self.assertEqual(code, 0)
        self.assertIn("written: docs/roadmap/notes/P1-02/", out)
        code, out, _ = self.run_cli("note", "P1-02", "-", "--role", "owner", "--by", "Owner", "--detail", stdin="Line one.\nLine two with 'quotes' and $dollars.\n")
        self.assertEqual(code, 0)
        body = rn.thread(rn.read_all(self.root)[0], "P1-02")[1]["body"]
        self.assertIn("'quotes' and $dollars.", body)                              # stdin: no shell quoting trouble
        code, out, _ = self.run_cli("start", "P1-02", "--doing", "the second thing", "--role", "agent", "--by", "Claude")
        self.assertEqual(code, 0)
        self.assertEqual(self.run_cli("update", "P1-02", "--by", "Claude", "--state", "half way")[0], 0)
        self.assertIn("half way", self.run_cli("working")[1])
        self.assertEqual(self.run_cli("done", "P1-02", "--by", "Claude", "--result", "merged in #1")[0], 0)
        self.assertIn("done", self.run_cli("working")[1])

    def test_a_refusal_is_plain_and_exits_with_2(self) -> None:
        code, _, err = self.run_cli("note", "P9-99", "x", "--role", "agent", "--by", "Claude")
        self.assertEqual((code, "not an item of the plan" in err), (2, True))
        code, _, err = self.run_cli("note", "P1-02", "key ghp_" + "e" * 36, "--role", "agent", "--by", "Claude")
        self.assertEqual((code, "GitHub token" in err), (2, True))
        code, _, err = self.run_cli("start", "P1-02", "--doing", "x", "--state", "token ghp_" + "f" * 36, "--role", "agent", "--by", "Claude")
        self.assertEqual((code, "GitHub token" in err), (2, True))
        code, _, err = self.run_cli("start", "P1-02", "--doing", "x", "--role", "agent")                       # no --by and no ROADMAP_BY
        self.assertEqual((code, "who you are" in err), (2, True))


if __name__ == "__main__":
    unittest.main()
