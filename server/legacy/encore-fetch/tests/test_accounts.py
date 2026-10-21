"""The YouTube accounts page's engine (docs/50): several accounts, the work split between them, a rest for one that is
refused while the others carry on, honest numbers, nothing lost on a restart."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from encore_fetch.accounts import PACES, Accounts
from encore_fetch.cookies import CookieProblem, StaticSource, as_source

from tests.test_admin import FUTURE, GOOD, TAB, row


def cookies_for(name: str, expiry: int = FUTURE) -> str:
    """A signed-in export that differs per account (so two accounts are two files)."""
    return "# Netscape HTTP Cookie File\n" + "\n".join([
        row(".youtube.com", "__Secure-3PSID", expiry, http_only=True), row(".youtube.com", f"VISITOR_{name}", expiry),
        row(".google.com", "SID", expiry)]) + "\n"


class AccountsTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.now = 1_000_000.0
        self.accounts = self.make()

    def make(self, **kw):
        return Accounts(self.root / "youtube", clock=lambda: self.now, **kw)

    def tick(self, seconds):
        self.now += seconds

    def add(self, label="Spare account", name="a"):
        # the expiry is 200 days after the test's own clock, not after the real one
        return self.accounts.add(label, cookies_for(name, int(self.now) + 200 * 86400))["id"]


class AddingAndSigningOutTest(AccountsTestBase):
    def test_a_new_account_is_working_gentle_and_named_by_its_label(self):
        account_id = self.add("Spare account")
        card = self.accounts.summary()["accounts"][0]
        self.assertEqual((card["id"], card["label"], card["state"], card["pace"]), (account_id, "Spare account", "working", "gentle"))
        self.assertEqual(card["perHourAllowed"], PACES["gentle"])
        self.assertEqual(self.accounts.capacity(), PACES["gentle"])

    def test_a_file_that_is_not_a_signed_in_export_is_told_in_a_sentence_and_nothing_is_kept(self):
        with self.assertRaises(CookieProblem) as caught:
            self.accounts.add("Bad", "hello world")
        self.assertIn("not a cookies.txt", caught.exception.message)
        self.assertEqual(self.accounts.summary()["accounts"], [])
        self.assertEqual(list((self.root / "youtube").glob("*.txt")) if (self.root / "youtube").exists() else [], [])

    def test_the_login_is_kept_private(self):
        account_id = self.add()
        path = self.root / "youtube" / f"{account_id}.txt"
        self.assertTrue(path.is_file())
        if os.name == "posix":
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

    def test_signing_out_deletes_the_login_and_leaves_the_other_account_alone(self):
        first, second = self.add("One", "a"), self.add("Two", "b")
        self.assertTrue(self.accounts.sign_out(first))
        self.assertFalse((self.root / "youtube" / f"{first}.txt").exists())
        self.assertEqual([c["label"] for c in self.accounts.summary()["accounts"]], ["Two"])
        self.assertTrue((self.root / "youtube" / f"{second}.txt").exists())
        self.assertFalse(self.accounts.sign_out(first), "signing out twice is not an error, it just says there was nothing")

    def test_with_no_account_there_is_no_capacity_and_the_visitor_has_no_cookies(self):
        self.assertIsNone(self.accounts.capacity())
        lease = self.accounts.lease()
        self.assertEqual((lease.args, lease.account_id), ([], None))

    def test_rename_and_pace(self):
        account_id = self.add("Spare")
        self.accounts.rename(account_id, "  Music account  ")
        self.accounts.set_pace(account_id, "normal")
        card = self.accounts.summary()["accounts"][0]
        self.assertEqual((card["label"], card["pace"], card["perHourAllowed"]), ("Music account", "normal", PACES["normal"]))
        with self.assertRaises(ValueError):
            self.accounts.set_pace(account_id, "turbo")
        with self.assertRaises(ValueError):
            self.accounts.rename(account_id, "   ")

    def test_a_long_label_is_cut(self):
        account_id = self.add("x" * 200)
        self.assertEqual(len(self.accounts.summary()["accounts"][0]["label"]), 40)


class SplittingTheWorkTest(AccountsTestBase):
    def test_the_work_is_spread_over_the_accounts_by_room_left(self):
        a, b = self.add("One", "a"), self.add("Two", "b")
        used = [self.accounts.lease().account_id for _ in range(100)]
        self.assertEqual(sorted({u for u in used}), sorted([a, b]))
        self.assertLessEqual(abs(used.count(a) - used.count(b)), 1, "two equal accounts share equally")

    def test_a_lease_gives_the_cookies_of_the_account_it_picked(self):
        a = self.add("One", "a")
        lease = self.accounts.lease()
        self.assertEqual(lease.args, ["--cookies", str(self.root / "youtube" / f"{a}.txt")])

    def test_an_account_at_its_hourly_allowance_is_left_alone_until_the_hour_has_passed(self):
        a, b = self.add("One", "a"), self.add("Two", "b")
        self.accounts.set_pace(a, "gentle")
        self.accounts.set_pace(b, "gentle")
        for _ in range(PACES["gentle"] * 2):
            self.assertIsNotNone(self.accounts.lease().account_id)
        self.assertIsNone(self.accounts.lease().account_id, "both are full: a tap falls back to the visitor limit")
        self.tick(3601)
        self.assertIsNotNone(self.accounts.lease().account_id)

    def test_a_lookup_does_not_use_up_the_allowance(self):
        a = self.add("One", "a")
        for _ in range(PACES["gentle"] * 2):
            self.accounts.lease(count=False)
        self.assertEqual(self.accounts.summary()["accounts"][0]["thisHour"], 0)
        self.assertEqual(self.accounts.lease().account_id, a)

    def test_the_numbers_on_the_card_are_the_real_ones(self):
        a = self.add("One", "a")
        for _ in range(5):
            self.accounts.lease().done("ok")
        card = self.accounts.summary()["accounts"][0]
        self.assertEqual((card["thisHour"], card["day"], card["refusalsDay"]), (5, 5, 0))
        self.tick(3 * 3600)
        card = self.accounts.summary()["accounts"][0]
        self.assertEqual((card["thisHour"], card["day"]), (0, 5))
        self.tick(22 * 3600)
        self.assertEqual(self.accounts.summary()["accounts"][0]["day"], 0)


class WhenYouTubeRefusesAnAccountTest(AccountsTestBase):
    def refuse(self, lease):
        lease.done("blocked")

    def test_a_refused_account_rests_and_the_other_carries_on(self):
        a, b = self.add("One", "a"), self.add("Two", "b")
        lease = self.accounts.lease()
        self.refuse(lease)
        cards = {c["id"]: c for c in self.accounts.summary()["accounts"]}
        self.assertEqual(cards[lease.account_id]["state"], "resting")
        other = b if lease.account_id == a else a
        self.assertEqual(cards[other]["state"], "working")
        self.assertEqual({self.accounts.lease().account_id for _ in range(10)}, {other})
        self.assertEqual(self.accounts.capacity(), PACES["gentle"], "only the other one's allowance counts while one rests")

    def test_the_rest_is_ninety_seconds_then_doubles_and_ends_by_itself(self):
        a = self.add("One", "a")
        self.refuse(self.accounts.lease())
        card = self.accounts.summary()["accounts"][0]
        self.assertEqual(card["state"], "resting")
        self.assertAlmostEqual(card["restUntil"] - self.now, 90, delta=1)
        self.tick(91)
        self.assertEqual(self.accounts.summary()["accounts"][0]["state"], "working")
        self.refuse(self.accounts.lease())
        self.assertAlmostEqual(self.accounts.summary()["accounts"][0]["restUntil"] - self.now, 180, delta=1)

    def test_refusals_in_a_burst_are_one_event(self):
        a = self.add("One", "a")
        leases = [self.accounts.lease() for _ in range(4)]  # four songs in flight when YouTube said no
        for lease in leases:
            self.refuse(lease)
        card = self.accounts.summary()["accounts"][0]
        self.assertAlmostEqual(card["restUntil"] - self.now, 90, delta=1, msg="one rest, not four doublings")
        self.assertNotEqual(card["state"], "needs_you")
        self.assertEqual(card["refusalsDay"], 1)

    def test_the_allowance_shrinks_once_per_ten_minutes_and_creeps_back_by_the_hour(self):
        self.add("One", "a")
        self.refuse(self.accounts.lease())
        self.assertEqual(self.accounts.summary()["accounts"][0]["perHourAllowed"], int(PACES["gentle"] * 0.7))
        self.tick(3601)
        self.assertGreater(self.accounts.summary()["accounts"][0]["perHourAllowed"], int(PACES["gentle"] * 0.7))
        self.tick(5 * 3601)
        self.assertEqual(self.accounts.summary()["accounts"][0]["perHourAllowed"], PACES["gentle"])

    def test_an_account_that_keeps_being_refused_asks_for_a_new_sign_in(self):
        self.add("One", "a")
        for _ in range(3):
            self.tick(2000)
            self.refuse(self.accounts.lease())
        card = self.accounts.summary()["accounts"][0]
        self.assertEqual(card["state"], "needs_you")
        self.assertIn("Sign in again", card["message"])
        self.assertIsNone(self.accounts.lease().account_id, "an account that needs a sign-in is not used")
        self.assertIsNone(self.accounts.capacity())

    def test_one_good_answer_clears_the_count(self):
        self.add("One", "a")
        for _ in range(2):
            self.tick(2000)
            self.refuse(self.accounts.lease())
        self.tick(2000)
        self.accounts.lease().done("ok")
        for _ in range(2):
            self.tick(2000)
            self.refuse(self.accounts.lease())
        self.assertNotEqual(self.accounts.summary()["accounts"][0]["state"], "needs_you")

    def test_signing_in_again_replaces_the_login_and_clears_the_trouble(self):
        a = self.add("One", "a")
        for _ in range(3):
            self.tick(2000)
            self.refuse(self.accounts.lease())
        self.accounts.replace_login(a, cookies_for("a2"))
        self.assertEqual(self.accounts.summary()["accounts"][0]["state"], "working")
        self.assertEqual(self.accounts.summary()["accounts"][0]["perHourAllowed"], PACES["gentle"])


class WhenTheLoginRunsOutTest(AccountsTestBase):
    def test_an_expired_login_is_reported_and_not_used(self):
        self.add("One", "a")
        self.tick(300 * 86400)  # the cookies end 200 days from the start of the test
        card = self.accounts.summary()["accounts"][0]
        self.assertEqual(card["state"], "needs_you")
        self.assertIn("run out", card["message"])
        self.assertIsNone(self.accounts.capacity())


class RestartTest(AccountsTestBase):
    def test_labels_paces_and_rests_survive_a_restart(self):
        a = self.add("Spare", "a")
        self.accounts.set_pace(a, "normal")
        self.accounts.rename(a, "Music")
        self.accounts.lease().done("blocked")
        again = self.make()
        card = again.summary()["accounts"][0]
        self.assertEqual((card["label"], card["pace"], card["state"]), ("Music", "normal", "resting"))
        self.assertEqual(card["refusalsDay"], 1, "the day's numbers are kept too")

    def test_a_damaged_list_is_ignored(self):
        self.add("Spare", "a")
        (self.root / "youtube" / "accounts.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(self.make().summary()["accounts"], [])

    def test_the_login_a_single_file_server_had_becomes_the_first_account(self):
        legacy = self.root / "youtube-cookies.txt"
        legacy.write_text(GOOD, encoding="utf-8")
        accounts = self.make(legacy_file=legacy)
        cards = accounts.summary()["accounts"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["state"], "working")
        self.assertFalse(legacy.exists(), "moved, not copied: one place for a login")
        self.assertEqual(len(self.make(legacy_file=legacy).summary()["accounts"]), 1)

    def test_a_login_file_dropped_while_the_service_runs_becomes_an_account_without_a_restart(self):
        legacy = self.root / "youtube-cookies.txt"
        accounts = self.make(legacy_file=legacy)
        self.assertIsNone(accounts.capacity())
        legacy.write_text(GOOD, encoding="utf-8")
        self.assertEqual(accounts.capacity(), PACES["gentle"])
        self.assertFalse(legacy.exists())
        self.assertEqual(len(accounts.summary()["accounts"]), 1)

    def test_a_legacy_file_that_is_not_usable_is_left_alone(self):
        legacy = self.root / "youtube-cookies.txt"
        legacy.write_text("junk", encoding="utf-8")
        self.assertEqual(self.make(legacy_file=legacy).summary()["accounts"], [])
        self.assertTrue(legacy.exists())


class StaticSourceTest(unittest.TestCase):
    def test_a_single_cookies_file_still_works_as_a_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.txt"
            self.assertEqual(as_source(str(path)).lease().args, [])
            path.write_text(GOOD, encoding="utf-8")
            lease = as_source(str(path)).lease()
            self.assertEqual(lease.args, ["--cookies", str(path)])
            lease.done("blocked")  # nothing to rest: harmless
            self.assertEqual(as_source(None).lease().args, [])
            source = StaticSource(None)
            self.assertIs(as_source(source), source)


class WhoTheAccountIsTest(AccountsTestBase):
    """A card says which Google account it is (the owner: "say the name of the account")."""

    GOOGLE = {"name": "Okeyo Oyeko", "email": "okeyo@example.com"}

    def make(self, **kw):
        kw.setdefault("identify", lambda path: self.answer)
        return super().make(**kw)

    def setUp(self):
        self.answer = dict(self.GOOGLE)
        super().setUp()

    def test_an_account_without_a_chosen_name_is_named_by_its_email(self):
        self.accounts.add("", cookies_for("a", int(self.now) + 200 * 86400))
        self.accounts.add("YouTube account 2", cookies_for("b", int(self.now) + 200 * 86400))
        first, second = self.accounts.summary()["accounts"]
        self.assertEqual((first["label"], first["email"], first["name"]), ("okeyo@example.com", "okeyo@example.com", "Okeyo Oyeko"))
        self.assertEqual(second["label"], "okeyo@example.com", "a generic name is replaced by the real one")

    def test_a_name_the_owner_chose_is_kept_and_the_email_still_shown(self):
        self.accounts.add("Spare", cookies_for("a", int(self.now) + 200 * 86400))
        card = self.accounts.summary()["accounts"][0]
        self.assertEqual((card["label"], card["email"]), ("Spare", "okeyo@example.com"))

    def test_when_google_does_not_say_the_account_is_still_kept_with_a_plain_name(self):
        self.answer = None
        self.accounts.add("", cookies_for("a", int(self.now) + 200 * 86400))
        card = self.accounts.summary()["accounts"][0]
        self.assertEqual(card["label"], "YouTube account")
        self.assertNotIn("email", card)

    def test_a_failing_lookup_never_stops_an_account_from_being_kept(self):
        def broken(path):
            raise OSError("offline")

        self.accounts = self.make(identify=broken)
        self.accounts.add("Spare", cookies_for("a", int(self.now) + 200 * 86400))
        self.assertEqual(len(self.accounts.summary()["accounts"]), 1)

    def test_signing_in_again_updates_who_it_is(self):
        account_id = self.accounts.add("Spare", cookies_for("a", int(self.now) + 200 * 86400))["id"]
        self.answer = {"name": "Somebody Else", "email": "else@example.com"}
        self.accounts.replace_login(account_id, cookies_for("b", int(self.now) + 200 * 86400))
        self.assertEqual(self.accounts.summary()["accounts"][0]["email"], "else@example.com")

    def test_who_it_is_survives_a_restart_and_is_filled_in_for_accounts_saved_before(self):
        self.answer = None
        account_id = self.accounts.add("Spare", cookies_for("a", int(self.now) + 200 * 86400))["id"]
        self.assertNotIn("email", self.accounts.summary()["accounts"][0])
        self.answer = dict(self.GOOGLE)
        self.accounts.identify_missing()
        self.assertEqual(self.accounts.summary()["accounts"][0]["email"], "okeyo@example.com")
        again = self.make()
        self.assertEqual(again.summary()["accounts"][0]["email"], "okeyo@example.com")
        self.assertEqual(again.summary()["accounts"][0]["id"], account_id)


class ReadingGoogleAnswerTest(unittest.TestCase):
    def test_the_first_signed_in_account_is_read_and_the_picture_and_id_are_ignored(self):
        from encore_fetch.identity import parse_accounts
        raw = ('["gaia.l.a.r",[["gaia.l.a",1,"Okeyo Oyeko","okeyo@example.com","https://lh3.googleusercontent.com/x/photo.jpg",1,1,0,'
               '"106082581771824809791","okeyo"]]]')
        self.assertEqual(parse_accounts(raw), {"name": "Okeyo Oyeko", "email": "okeyo@example.com"})

    def test_anything_else_is_nothing(self):
        from encore_fetch.identity import parse_accounts
        for raw in ("", "not json", "[]", '["gaia.l.a.r",[]]', '{"a": 1}', '[["gaia.l.a", 1, "No Email"]]'):
            self.assertIsNone(parse_accounts(raw), raw)


class TheDownloaderUsesTheAccountsTest(AccountsTestBase):
    """What yt-dlp is told, and what the accounts are told back."""

    class Runner:
        def __init__(self):
            self.calls = []
            self.answers = []  # (returncode, stderr), in order; the last one repeats

        def __call__(self, argv, timeout):
            import subprocess
            self.calls.append(argv)
            code, err = self.answers[min(len(self.calls), len(self.answers)) - 1]
            return subprocess.CompletedProcess(argv, code, "{}" if code == 0 else "", err)

    def downloader(self, runner):
        from encore_fetch.download import YtDlpDownloader
        return YtDlpDownloader("yt-dlp", cookies=self.accounts, runner=runner)

    def test_an_extraction_goes_out_with_an_account_and_counts_as_a_song(self):
        a = self.add("One", "a")
        runner = self.Runner()
        runner.answers = [(0, "")]
        self.downloader(runner).extract("vid12345678", self.root / "x" / "i.json")
        self.assertIn(str(self.root / "youtube" / f"{a}.txt"), runner.calls[0])
        self.assertEqual(self.accounts.summary()["accounts"][0]["thisHour"], 1)

    def test_a_refusal_rests_that_account_and_the_error_says_which_one(self):
        from encore_fetch.download import DownloadError
        a = self.add("One", "a")
        runner = self.Runner()
        runner.answers = [(1, "ERROR: Sign in to confirm you're not a bot")]
        with self.assertRaises(DownloadError) as caught:
            self.downloader(runner).extract("vid12345678", self.root / "x" / "i.json")
        self.assertEqual((caught.exception.code, caught.exception.account), ("blocked", a))
        self.assertEqual(self.accounts.summary()["accounts"][0]["state"], "resting")

    def test_an_ordinary_failure_is_not_the_accounts_fault(self):
        from encore_fetch.download import DownloadError
        self.add("One", "a")
        runner = self.Runner()
        runner.answers = [(1, "ERROR: Video unavailable")]
        with self.assertRaises(DownloadError):
            self.downloader(runner).extract("vid12345678", self.root / "x" / "i.json")
        self.assertEqual(self.accounts.summary()["accounts"][0]["state"], "working")

    def test_a_download_from_a_saved_extraction_is_not_counted_twice(self):
        self.add("One", "a")
        info = self.root / "x" / "i.json"
        info.parent.mkdir(parents=True)
        info.write_text("{}", encoding="utf-8")
        runner = self.Runner()
        runner.answers = [(1, "ERROR: unable to download")]
        from encore_fetch.download import DownloadError
        with self.assertRaises(DownloadError):
            self.downloader(runner).download("vid12345678", self.root / "x" / "song", info=info)
        # the saved extraction failed once and YouTube was asked again once: that second ask is the only new count
        self.assertEqual(self.accounts.summary()["accounts"][0]["thisHour"], 1)

    def test_a_visitor_run_has_no_cookies_when_there_is_no_account(self):
        runner = self.Runner()
        runner.answers = [(0, "")]
        self.downloader(runner).extract("vid12345678", self.root / "x" / "i.json")
        self.assertNotIn("--cookies", runner.calls[0])


if __name__ == "__main__":
    unittest.main()
