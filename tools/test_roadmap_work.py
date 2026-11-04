"""Tests of "Working now" (tools/roadmap_work.py): claims shared by every worktree of the clone, quiet ones flagged, GitHub pull requests matched to items."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_notes as rn  # noqa: E402
import roadmap_work as rw  # noqa: E402

T0 = datetime(2026, 11, 4, 9, 0, 0, tzinfo=timezone.utc)
KNOWN = {"P2-22", "P3-12", "N-04"}


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


class WorkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.d = self.root / "shared"

    def start(self, hours=0.0, **kw):
        args = dict(role="agent", by="Claude (Sonnet 5.5)", items=["P2-22"], doing="the notification ask", known_items=KNOWN, now=at(hours), wdir=self.d)
        args.update(kw)
        return rw.start(self.root, **args)

    def test_a_claim_is_listed_with_who_what_and_how_long_quiet(self) -> None:
        c = self.start(state="the tests exist, the code does not", branch="task/P2-22-ask-once")
        got = rw.list_claims(self.root, now=at(2.5), wdir=self.d)
        self.assertEqual([x["id"] for x in got], [c["id"]])
        self.assertEqual((got[0]["hours_quiet"], got[0]["maybe_stopped"]), (2.5, False))
        self.assertEqual(got[0]["state"], "the tests exist, the code does not")

    def test_a_claim_quiet_for_a_working_day_is_flagged_but_never_deleted(self) -> None:
        self.start()
        got = rw.list_claims(self.root, now=at(rw.STALE_HOURS + 1), wdir=self.d)
        self.assertTrue(got[0]["maybe_stopped"])
        self.assertEqual(len(list(self.d.glob("*.json"))), 1)

    def test_an_update_resets_the_quiet_time_and_keeps_the_rest(self) -> None:
        c = self.start()
        rw.update(self.root, "P2-22", by=c["by"], state="implementation written, tests green", now=at(7), wdir=self.d)
        got = rw.list_claims(self.root, now=at(9), wdir=self.d)[0]
        self.assertEqual((got["hours_quiet"], got["state"], got["doing"], got["started"]), (2.0, "implementation written, tests green", "the notification ask", c["started"]))

    def test_done_moves_a_claim_below_the_live_ones_and_it_goes_after_three_days(self) -> None:
        a = self.start(items=["P2-22"])
        self.start(hours=1, items=["P3-12"], doing="the first friend")
        rw.finish(self.root, a["id"], result="merged in #141", now=at(2), wdir=self.d)
        got = rw.list_claims(self.root, now=at(3), wdir=self.d)
        self.assertEqual([(x["items"], x["status"]) for x in got], [(["P3-12"], "active"), (["P2-22"], "done")])
        self.assertEqual(got[1]["state"], "merged in #141")
        self.assertEqual(len(list(self.d.glob("*.json"))), 2)       # both files are still there while the finished one is recent
        late = at(2 + 24 * rw.KEEP_DONE_DAYS + 1)
        self.assertEqual([x["items"] for x in rw.list_claims(self.root, now=late, wdir=self.d)], [["P3-12"]])
        self.assertEqual(len(list(self.d.glob("*.json"))), 1)       # the finished claim is removed after three days; the live one never is

    def test_two_people_on_one_item_must_say_which_claim(self) -> None:
        a = self.start(by="Claude A")
        self.start(by="Dev Sam", role="dev")
        with self.assertRaises(rn.NoteError) as cm:
            rw.update(self.root, "P2-22", doing="x", wdir=self.d)
        self.assertIn("2 live claims", str(cm.exception))
        self.assertEqual(rw.update(self.root, "P2-22", by="Claude A", doing="narrower", wdir=self.d)["id"], a["id"])

    def test_bad_claims_are_refused_in_plain_words(self) -> None:
        for kw, word in (({"items": []}, "at least one item"), ({"items": ["P9-99"]}, "not an item"), ({"doing": " "}, "few words"), ({"by": ""}, "who you are"),
                         ({"role": "boss"}, "role"), ({"state": "key ghp_" + "c" * 36}, "GitHub token")):
            with self.assertRaises(rn.NoteError, msg=kw) as cm:
                self.start(**kw)
            self.assertIn(word, str(cm.exception))

    def test_a_foreign_or_half_written_file_never_breaks_the_list(self) -> None:
        self.start()
        (self.d / "junk.json").write_text("{nope", encoding="utf-8")
        (self.d / "other.json").write_text(json.dumps({"id": "other", "status": "weird", "items": []}), encoding="utf-8")
        self.assertEqual(len(rw.list_claims(self.root, now=at(1), wdir=self.d)), 1)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_every_worktree_of_a_clone_resolves_the_same_folder(self) -> None:
        repo = Path(tempfile.mkdtemp())
        run = lambda *a, cwd=repo: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)  # noqa: E731
        run("init", "-q")
        run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        wt = Path(tempfile.mkdtemp()) / "second"
        run("worktree", "add", "-q", str(wt), "-b", "other")
        self.assertEqual(rw.work_dir(repo).resolve(), rw.work_dir(wt).resolve())
        self.assertEqual(rw.work_dir(repo).name, rw.DIRNAME)
        self.assertNotEqual(rw.work_dir(repo).resolve(), repo.resolve() / rw.DIRNAME)       # inside .git, so it is never a change to commit
        self.assertEqual(run("status", "--porcelain").stdout.strip(), "")
        rw.start(repo, "agent", "Claude", ["_board"], "writing a claim in one worktree")
        self.assertEqual(len(rw.list_claims(wt)), 1)                                         # ... and the other worktree sees it
        self.assertEqual(run("status", "--porcelain").stdout.strip(), "")

    def test_without_git_the_fallback_folder_inside_the_root_is_used(self) -> None:
        def no_git(*a, **k):
            raise FileNotFoundError("git")
        self.assertEqual(rw.work_dir(self.root, runner=no_git), self.root / rw.FALLBACK)


class GithubTests(unittest.TestCase):
    PRS = [{"number": 136, "title": "Songs without an album", "headRefName": "task/RC1-songs-without-an-album", "isDraft": True, "author": {"login": "a"}, "updatedAt": "2026-11-03T20:00:00Z", "url": "u1"},
           {"number": 150, "title": "P2-22: ask once for notification permission", "headRefName": "task/P2-22-ask-once-for-download-notifications", "isDraft": False, "author": {"login": "sam"}, "updatedAt": "2026-11-04T08:00:00Z", "url": "u2"}]

    def fake(self, out=None, code=0, boom=None):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            if boom:
                raise boom
            return subprocess.CompletedProcess(cmd, code, stdout=json.dumps(out if out is not None else self.PRS), stderr="")
        run.calls = calls
        return run

    def setUp(self) -> None:
        rw._CACHE.clear()

    def test_pull_requests_are_matched_to_items_by_the_id_in_the_branch_or_the_title(self) -> None:
        prs = rw.github_prs(Path("x"), runner=self.fake())
        self.assertEqual([(p["number"], p["items"], p["draft"]) for p in prs], [(136, [], True), (150, ["P2-22"], False)])
        self.assertEqual(prs[1]["author"], "sam")

    def test_the_answer_is_cached_so_the_page_does_not_call_github_every_few_seconds(self) -> None:
        run = self.fake()
        t = [0.0]
        rw.github_prs(Path("x"), runner=run, clock=lambda: t[0])
        t[0] = 30
        rw.github_prs(Path("x"), runner=run, clock=lambda: t[0])
        self.assertEqual(len(run.calls), 1)
        t[0] = 61
        rw.github_prs(Path("x"), runner=run, clock=lambda: t[0])
        self.assertEqual(len(run.calls), 2)

    def test_missing_signed_out_or_offline_gh_leaves_the_list_out_without_an_error(self) -> None:
        self.assertIsNone(rw.github_prs(Path("x"), runner=self.fake(boom=FileNotFoundError("gh"))))
        self.assertIsNone(rw.github_prs(Path("y"), runner=self.fake(code=1)))
        self.assertIsNone(rw.github_prs(Path("z"), runner=self.fake(boom=subprocess.TimeoutExpired("gh", 10))))


if __name__ == "__main__":
    unittest.main()
