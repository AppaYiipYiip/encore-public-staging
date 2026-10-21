"""The owner's YouTube sign-in (docs/44, ADR-103): the owner puts a login (a cookies.txt) in the app, nobody else may, the
file is checked, kept private and used by the next song."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from encore_fetch import cookies as youtube_login
from encore_fetch.accounts import Accounts
from encore_fetch.cookies import CookieProblem, check_text, cookie_args
from encore_fetch.jobs import JobManager
from encore_fetch.navidrome import Auth
from encore_fetch.owners import OwnerCheck
from encore_fetch.server import Api

from tests.test_pipeline import FakeNavidrome, FakeSearcher, FakeDownloader, InlineExecutor

TAB = "\t"
FUTURE = int(time.time()) + 200 * 86400


def row(domain, name, expiry=FUTURE, http_only=False):
    return ("#HttpOnly_" if http_only else "") + TAB.join([domain, "TRUE", "/", "TRUE", str(expiry), name, "value"])


GOOD = "# Netscape HTTP Cookie File\n" + "\n".join([
    row(".youtube.com", "__Secure-3PSID", http_only=True), row(".youtube.com", "VISITOR_INFO1_LIVE"),
    row(".google.com", "SID")]) + "\n"


class CheckTest(unittest.TestCase):
    def test_a_signed_in_youtube_export_is_accepted_and_described(self):
        report = check_text(GOOD)
        self.assertEqual((report.rows, report.login_cookies), (3, 2))
        self.assertEqual(report.expires, FUTURE)

    def test_each_wrong_file_is_told_what_is_wrong_in_a_sentence(self):
        cases = {
            "hello world\n": "not a cookies.txt",
            "": "no cookies",
            "# Netscape HTTP Cookie File\n" + row(".example.org", "SID") + "\n": "no youtube.com cookies",
            "# Netscape HTTP Cookie File\n" + row(".youtube.com", "VISITOR_INFO1_LIVE") + "\n": "not signed in",
            "# Netscape HTTP Cookie File\n" + row(".youtube.com", "SID", 100) + "\n": "already run out",
            "x" * 500_000: "too big",
        }
        for text, words in cases.items():
            with self.assertRaises(CookieProblem, msg=words) as caught:
                check_text(text)
            self.assertIn(words, caught.exception.message)


class FileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = str(Path(self._tmp.name) / "work" / "youtube-cookies.txt")

    def test_installing_keeps_the_file_private_and_the_next_song_uses_it(self):
        self.assertEqual(cookie_args(self.path), [])
        youtube_login.install(self.path, GOOD)
        self.assertEqual(cookie_args(self.path), ["--cookies", self.path])
        if os.name == "posix":
            self.assertEqual(oct(Path(self.path).stat().st_mode & 0o777), "0o600")
        self.assertEqual(Path(self.path).read_text(encoding="utf-8"), GOOD)

    def test_a_bad_file_never_replaces_a_good_one(self):
        youtube_login.install(self.path, GOOD)
        with self.assertRaises(CookieProblem):
            youtube_login.install(self.path, "junk")
        self.assertEqual(Path(self.path).read_text(encoding="utf-8"), GOOD)

    def test_status_says_signed_in_with_when_it_runs_out_and_not_signed_in_without_a_file(self):
        self.assertEqual(youtube_login.status(self.path), {"signedIn": False})
        youtube_login.install(self.path, GOOD)
        status = youtube_login.status(self.path)
        self.assertEqual((status["signedIn"], status["loginCookies"], status["expires"]), (True, 2, FUTURE))

    def test_removing_it_and_removing_it_twice(self):
        youtube_login.install(self.path, GOOD)
        youtube_login.remove(self.path)
        youtube_login.remove(self.path)
        self.assertEqual(youtube_login.status(self.path), {"signedIn": False})


class RouteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        (root / "music").mkdir()
        self.nd = FakeNavidrome()
        manager = JobManager(
            music_dir=root / "music", work_dir=root / "work", resolver=FakeSearcher([]), downloader=FakeDownloader(),
            navidrome=self.nd, executor=InlineExecutor(), indexer=InlineExecutor(), cover=lambda u: None,
            tagger=lambda p, t, c: True, sleep=lambda s: None, min_free_gb=0)
        self.owners = {"marwa"}
        self.accounts = Accounts(root / "work" / "youtube")

        self.manager = manager
        self.api = Api(manager, self.nd, owner_check=lambda auth: auth.user in self.owners, accounts=self.accounts,
                       visitor_per_hour=200)
        self.q = "?u=marwa&t=" + "a" * 32 + "&s=salt1234"

    def call(self, method, path, body=None, query=None):
        raw = json.dumps(body).encode() if body is not None else b""
        return self.api.handle(method, path + (self.q if query is None else query), {}, raw)

    def test_the_service_says_it_has_owner_controls_only_when_it_has_and_whether_it_is_signed_in(self):
        info = self.api.handle("GET", "/api/info", {})[1]
        self.assertIn("youtube-login", info["features"])
        self.assertFalse(info["youtubeSignedIn"])
        self.call("POST", "/api/admin/youtube/accounts", {"label": "Spare", "cookies": GOOD})
        self.assertTrue(self.api.handle("GET", "/api/info", {})[1]["youtubeSignedIn"])
        self.assertNotIn("youtube-login", Api(self.manager, self.nd).handle("GET", "/api/info", {})[1]["features"])

    def test_the_owner_adds_an_account_sees_what_it_may_do_renames_it_and_signs_it_out(self):
        status, body = self.call("GET", "/api/admin/youtube")
        self.assertEqual((status, body["accounts"], body["signedIn"], body["visitorPerHour"]), (200, [], False, 200))
        status, body = self.call("POST", "/api/admin/youtube/accounts", {"label": "Spare account", "cookies": GOOD})
        self.assertEqual(status, 200)
        card = body["accounts"][0]
        self.assertEqual((card["label"], card["state"], card["pace"], card["perHourAllowed"]), ("Spare account", "working", "gentle", 400))
        self.assertEqual((body["signedIn"], body["perHour"], body["paces"]["gentle"]), (True, 400, 400))
        self.assertNotIn("cookies", json.dumps(body), "a login is never shown back")

        status, body = self.call("POST", "/api/admin/youtube/accounts/" + card["id"], {"label": "Music", "pace": "normal"})
        self.assertEqual((body["accounts"][0]["label"], body["accounts"][0]["pace"], body["perHour"]), ("Music", "normal", 800))

        status, body = self.call("POST", "/api/admin/youtube/accounts/" + card["id"] + "/signout")
        self.assertEqual((status, body["accounts"], body["signedIn"]), (200, [], False))

    def test_somebody_who_is_not_the_owner_may_neither_look_nor_change(self):
        self.owners = set()
        for method, path, body in (("GET", "/api/admin/youtube", None),
                                   ("POST", "/api/admin/youtube/accounts", {"cookies": GOOD}),
                                   ("POST", "/api/admin/youtube/accounts/abc", {"label": "x"}),
                                   ("POST", "/api/admin/youtube/accounts/abc/login", {"cookies": GOOD})):
            status, answer = self.call(method, path, body)
            self.assertEqual((status, answer["error"]), (403, "owner_only"), path)
        self.assertEqual(self.accounts.summary()["accounts"], [])

    def test_the_music_login_is_needed(self):
        self.nd.valid = False
        self.assertEqual(self.call("GET", "/api/admin/youtube")[0], 401)
        self.assertEqual(self.call("GET", "/api/admin/youtube", query="")[0], 401)

    def test_a_file_that_cannot_be_used_is_said_in_a_sentence_and_kept_out(self):
        status, body = self.call("POST", "/api/admin/youtube/accounts", {"cookies": "hello"})
        self.assertEqual((status, body["error"]), (422, "unusable"))
        self.assertIn("not a cookies.txt", body["message"])
        self.assertEqual(self.accounts.summary()["accounts"], [])
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts", {})[0], 400)
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts", {"cookies": 5})[0], 400)
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts", {"cookies": GOOD, "label": 5})[0], 400)
        self.assertEqual(self.api.handle("POST", "/api/admin/youtube/accounts" + self.q, {}, b"{nope")[0], 400)
        self.assertEqual(self.api.handle("POST", "/api/admin/youtube/accounts" + self.q, {}, b"[1]")[0], 400)

    def test_a_pace_or_name_that_makes_no_sense_is_refused(self):
        account_id = self.accounts.add("Spare", GOOD)["id"]
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts/" + account_id, {"pace": "turbo"})[0], 400)
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts/" + account_id, {"label": "   "})[0], 400)

    def test_the_owner_can_check_that_an_account_really_works(self):
        checked = []
        self.api._account_tester = lambda path: checked.append(path.name) or {"ok": True, "login": True, "fetch": True, "message": "Works."}
        account_id = self.accounts.add("Spare", GOOD)["id"]
        status, body = self.call("POST", "/api/admin/youtube/accounts/" + account_id + "/test")
        self.assertEqual((status, body["ok"], body["message"]), (200, True, "Works."))
        self.assertEqual(checked, [account_id + ".txt"])
        self.assertEqual(self.call("GET", "/api/admin/youtube/accounts/" + account_id + "/test")[0], 405)
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts/nope/test")[0], 404)

    def test_a_server_that_cannot_check_accounts_says_so(self):
        account_id = self.accounts.add("Spare", GOOD)["id"]
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts/" + account_id + "/test")[0], 501)

    def test_signing_in_again_replaces_the_login_of_that_account_and_clears_the_trouble(self):
        account_id = self.accounts.add("Spare", GOOD)["id"]
        status, body = self.call("POST", "/api/admin/youtube/accounts/" + account_id + "/login", {"cookies": GOOD})
        self.assertEqual((status, len(body["accounts"]), body["accounts"][0]["state"]), (200, 1, "working"))
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts/" + account_id + "/login", {"cookies": "junk"})[0], 422)
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts/" + account_id + "/login", {})[0], 400)
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts/nope/login", {"cookies": GOOD})[0], 404)
        self.assertEqual(self.call("GET", "/api/admin/youtube/accounts/" + account_id + "/login")[0], 405)

    def test_wrong_methods_unknown_accounts_and_unknown_paths(self):
        self.assertEqual(self.call("POST", "/api/admin/youtube")[0], 405)
        self.assertEqual(self.call("GET", "/api/admin/youtube/accounts")[0], 405)
        self.assertEqual(self.call("GET", "/api/admin/youtube/accounts/nope")[0], 404)
        account_id = self.accounts.add("Spare", GOOD)["id"]
        self.assertEqual(self.call("GET", "/api/admin/youtube/accounts/" + account_id)[0], 405)
        self.assertEqual(self.call("GET", "/api/admin/youtube/accounts/" + account_id + "/signout")[0], 405)
        self.assertEqual(self.call("POST", "/api/admin/youtube/accounts/" + account_id + "/other")[0], 404)
        self.assertEqual(self.call("GET", "/api/admin/other")[0], 404)


class OwnerCheckTest(unittest.TestCase):
    AUTH = Auth("marwa", "a" * 32, "salt1234")

    def test_the_people_services_word_decides(self):
        asked = []

        def people(url):
            asked.append(url)
            return {"canManage": True}

        nd = FakeNavidrome()
        nd.is_admin = lambda auth: self.fail("the music server must not be asked when the people service answered")
        self.assertTrue(OwnerCheck("http://encore-people:8702", nd, people)(self.AUTH))
        self.assertTrue(asked[0].startswith("http://encore-people:8702/api/me?"))
        self.assertIn("u=marwa", asked[0])
        self.assertFalse(OwnerCheck("http://x", nd, lambda url: {"canManage": False})(self.AUTH))
        self.assertFalse(OwnerCheck("http://x", nd, lambda url: {})(self.AUTH))

    def test_without_the_people_service_a_music_server_administrator_is_the_owner(self):
        nd = FakeNavidrome()
        nd.is_admin = lambda auth: True
        self.assertTrue(OwnerCheck(None, nd)(self.AUTH))

        def down(url):
            raise OSError("no route")

        self.assertTrue(OwnerCheck("http://x", nd, down)(self.AUTH), "the people service not answering is not 'no'")
        nd.is_admin = lambda auth: False
        self.assertFalse(OwnerCheck("http://x", nd, down)(self.AUTH))


if __name__ == "__main__":
    unittest.main()
