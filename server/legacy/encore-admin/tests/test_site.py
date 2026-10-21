"""The admin website as an owner uses it: signing in with the app's login, the YouTube page, the sign-in window, and what a
guest or a stranger is (not) allowed to see."""
import http.client
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from encore_admin.config import Config
from encore_admin.docker_api import NAME, Docker, DockerError
from encore_admin.http_server import serve
from encore_admin.server import COOKIE, Api
from encore_admin.services import Services
from encore_admin.sessions import Sessions, Throttle
from encore_admin.signin import SigninWindows

from tests.fakes import GOOGLE_ONLY, NOTHING_YET, SIGNED_IN, FakeDocker, Stack, firefox_cookies

H = {"X-Encore-Admin": "1"}


class SiteTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.now = 1_000_000.0
        self.stack = Stack()
        self.docker = FakeDocker()
        self.config = Config(signin_minutes=15)
        self.probe_ok = True
        self.services = Services(navidrome_url=Stack.ND, people_url=Stack.PEOPLE, fetch_url=Stack.FETCH, quality_url=Stack.QUALITY,
                                 recs_url=Stack.RECS, http=self.stack.http)
        ids = iter(["a1b2c3d4", "e5f6a7b8", "01234567"])
        self.docker_client = Docker(self.docker, self.docker, self.config.signin_image)
        self.signin = SigninWindows(
            self.docker_client, self.services.fetch_call, network="encore-server_default",
            minutes=15, clock=lambda: self.now, background=lambda work: work(),
            new_id=lambda: next(ids), probe=lambda host, port: self.probe_ok)
        self.sessions = Sessions(8, clock=lambda: self.now)
        self.throttle = Throttle(clock=lambda: self.now)
        self.api = Api(self.config, self.services, self.signin, sessions=self.sessions, throttle=self.throttle,
                       stack=self.docker_client.stack, details=self.docker_client.details, logs=self.docker_client.logs,
                       restart=self.docker_client.restart)

    def call(self, method, path, body=None, cookie=None, headers=None, ip="10.0.0.2"):
        sent = dict(H if method != "GET" else {})
        sent.update(headers or {})
        if cookie:
            sent["Cookie"] = f"{COOKIE}={cookie}"
        raw = json.dumps(body).encode() if body is not None else b""
        r = self.api.handle(method, path, sent, raw, ip)
        try:
            data = json.loads(r.body)
        except ValueError:
            data = r.body
        return r, data

    def sign_in(self, user="dana", password="correct horse"):
        r, data = self.call("POST", "/admin/api/login", {"user": user, "password": password})
        self.assertEqual(r.status, 200, data)
        return r.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]


class SigningInTest(SiteTestBase):
    def test_the_owner_signs_in_with_the_same_name_and_password_as_the_app(self):
        r, data = self.call("POST", "/admin/api/login", {"user": "dana", "password": "correct horse"})
        self.assertEqual((r.status, data["user"]), (200, "dana"))
        cookie = r.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        key = cookie.split(";")[0].split("=", 1)[1]
        self.assertEqual(self.call("GET", "/admin/api/me", cookie=key)[1]["user"], "dana")

    def test_the_session_keeps_the_login_token_never_the_password(self):
        key = self.sign_in()
        session = self.sessions.get(key)
        self.assertNotIn("correct horse", repr(session.__dict__))
        self.assertEqual(len(session.token), 32)

    def test_a_wrong_password_is_said_in_a_sentence_and_five_in_a_row_lock_the_door_for_ten_minutes(self):
        for _ in range(5):
            r, data = self.call("POST", "/admin/api/login", {"user": "dana", "password": "nope"})
            self.assertEqual((r.status, data["message"]), (401, "That name and password did not work."))
        r, data = self.call("POST", "/admin/api/login", {"user": "dana", "password": "correct horse"})
        self.assertEqual((r.status, data["error"]), (429, "too_many_tries"))
        self.now += 601
        self.assertEqual(self.call("POST", "/admin/api/login", {"user": "dana", "password": "correct horse"})[0].status, 200)

    def test_a_guest_is_told_only_owners_can_manage_the_server_and_gets_no_session(self):
        r, data = self.call("POST", "/admin/api/login", {"user": "sam", "password": "guest pw"})
        self.assertEqual((r.status, data["message"]), (403, "Only owners can manage this server."))
        self.assertNotIn("Set-Cookie", r.headers)

    def test_nothing_is_shown_without_a_session(self):
        for path in ("/admin/api/me", "/admin/api/today", "/admin/api/youtube", "/admin/api/youtube/signin"):
            r, data = self.call("GET", path)
            self.assertEqual((r.status, data["error"]), (401, "sign_in"), path)
        self.assertEqual(self.call("GET", "/admin/api/me", cookie="made-up")[0].status, 401)

    def test_a_request_that_did_not_come_from_the_website_is_refused(self):
        r, data = self.call("POST", "/admin/api/login", {"user": "dana", "password": "correct horse"}, headers={"X-Encore-Admin": ""})
        self.assertEqual((r.status, data["error"]), (403, "forbidden"))

    def test_signing_out_ends_the_session(self):
        key = self.sign_in()
        r, _ = self.call("POST", "/admin/api/logout", {}, cookie=key)
        self.assertEqual(r.status, 200)
        self.assertEqual(self.call("GET", "/admin/api/me", cookie=key)[0].status, 401)

    def test_a_session_that_is_not_used_runs_out_after_the_hours_set(self):
        key = self.sign_in()
        self.now += 8 * 3600 + 1
        self.assertEqual(self.call("GET", "/admin/api/me", cookie=key)[0].status, 401)

    def test_bad_input_is_a_sentence_not_a_crash(self):
        self.assertEqual(self.call("POST", "/admin/api/login", {"user": 5, "password": "x"})[0].status, 400)
        self.assertEqual(self.call("POST", "/admin/api/login", {"user": "", "password": ""})[0].status, 400)
        r = self.api.handle("POST", "/admin/api/login", H, b"{nope", "10.0.0.2")
        self.assertEqual(r.status, 400)
        r = self.api.handle("POST", "/admin/api/login", H, b"[1]", "10.0.0.2")
        self.assertEqual(r.status, 400)

    def test_when_the_people_service_does_not_answer_a_music_server_administrator_counts_as_owner(self):
        original = self.stack.http

        def no_people(method, url, body=None):
            return (0, {}) if url.startswith(Stack.PEOPLE) else original(method, url, body)

        self.services = Services(navidrome_url=Stack.ND, people_url=Stack.PEOPLE, fetch_url=Stack.FETCH, http=no_people)
        self.api = Api(self.config, self.services, self.signin, sessions=self.sessions, throttle=self.throttle,
                       stack=self.docker_client.stack)
        self.assertEqual(self.call("POST", "/admin/api/login", {"user": "dana", "password": "correct horse"})[0].status, 200)
        self.assertEqual(self.call("POST", "/admin/api/login", {"user": "sam", "password": "guest pw"})[0].status, 403)


class TheYouTubePageTest(SiteTestBase):
    def test_the_page_shows_what_the_songs_service_says_and_asks_it_as_the_owner(self):
        self.stack.summary = {"accounts": [{"id": "abcd1234", "label": "Spare", "state": "working"}], "signedIn": True, "perHour": 400}
        key = self.sign_in()
        r, data = self.call("GET", "/admin/api/youtube", cookie=key)
        self.assertEqual((r.status, data["perHour"]), (200, 400))
        method, path, query, body = self.stack.calls[-1]
        self.assertEqual((method, path, query["u"]), ("GET", "", "dana"))
        self.assertNotIn("correct horse", json.dumps(query))

    def test_adding_renaming_and_signing_out_reach_the_songs_service(self):
        key = self.sign_in()
        self.call("POST", "/admin/api/youtube/accounts", {"label": "Spare", "cookies": "x"}, cookie=key)
        self.call("POST", "/admin/api/youtube/accounts/abcd1234", {"pace": "normal"}, cookie=key)
        self.call("POST", "/admin/api/youtube/accounts/abcd1234/signout", {}, cookie=key)
        seen = [(m, p, b) for m, p, _, b in self.stack.calls]
        self.assertEqual(seen, [("POST", "/accounts", {"label": "Spare", "cookies": "x"}),
                                ("POST", "/accounts/abcd1234", {"pace": "normal"}),
                                ("POST", "/accounts/abcd1234/signout", {})])

    def test_a_sentence_from_the_songs_service_reaches_the_person(self):
        key = self.sign_in()
        self.stack.fetch_status_override = 422
        r, data = self.call("POST", "/admin/api/youtube/accounts", {"label": "x", "cookies": "junk"}, cookie=key)
        self.assertEqual((r.status, data["message"]), (422, "That is not a cookies.txt file."))

    def test_when_the_songs_service_is_down_the_page_says_so(self):
        key = self.sign_in()
        self.stack.fetch_up = False
        r, data = self.call("GET", "/admin/api/youtube", cookie=key)
        self.assertEqual((r.status, data["error"]), (502, "unreachable"))
        r, data = self.call("GET", "/admin/api/today", cookie=key)
        self.assertEqual((r.status, data["songsServiceUp"]), (200, False))

    def test_today_lists_an_account_that_needs_the_owner(self):
        self.stack.summary = {"accounts": [{"id": "abcd1234", "label": "Spare", "state": "needs_you", "message": "Sign in again."}],
                              "signedIn": False, "perHour": None}
        key = self.sign_in()
        data = self.call("GET", "/admin/api/today", cookie=key)[1]
        self.assertEqual(data["needsYou"], [{"text": "Spare: Sign in again.", "link": "#/youtube"}])

    def test_unknown_paths_and_wrong_methods(self):
        key = self.sign_in()
        self.assertEqual(self.call("GET", "/admin/api/nothing", cookie=key)[0].status, 404)
        self.assertEqual(self.call("POST", "/admin/api/youtube", {}, cookie=key)[0].status, 405)
        self.assertEqual(self.call("GET", "/admin/api/youtube/accounts", cookie=key)[0].status, 405)
        self.assertEqual(self.call("GET", "/admin/api/youtube/other", cookie=key)[0].status, 404)


class TheSignInWindowTest(SiteTestBase):
    def open_window(self, replace=None):
        key = self.sign_in()
        r, data = self.call("POST", "/admin/api/youtube/signin", {"replace": replace} if replace else {}, cookie=key)
        self.assertEqual(r.status, 200, data)
        return key, data

    def browser_has(self, rows, **kw):
        """What the browser's cookie file holds right now (as `docker cp` would hand it over)."""
        self.docker.files = firefox_cookies(rows, **kw)

    def test_opening_it_starts_a_fresh_browser_that_only_this_page_can_reach(self):
        key, window = self.open_window()
        self.assertEqual((window["state"], window["window"], window["path"]), ("waiting", "a1b2c3d4", "/window-a1b2c3d4/"))
        self.assertNotIn("password", window, "no second password: the page itself is the only way in")
        created = [b for m, p, b in self.docker.calls if p.startswith("/containers/create")][0]
        self.assertEqual(created["Image"], self.config.signin_image)
        self.assertIn("USER_ID=1000", created["Env"])
        self.assertFalse([e for e in created["Env"] if e.startswith(("PASSWORD", "CUSTOM_USER", "WEB_AUTHENTICATION", "SECURE_CONNECTION"))])
        self.assertTrue([e for e in created["Env"] if e.startswith("FF_OPEN_URL=https://accounts.google.com/")], "starts on Google's sign-in")
        self.assertEqual(created["HostConfig"]["NetworkMode"], "encore-server_default")
        self.assertNotIn("Binds", created["HostConfig"], "nothing is shared with the host: it works the same on any system")
        self.assertNotIn("PortBindings", created["HostConfig"], "nothing is published to the machine or the home network")
        self.assertNotIn("ExposedPorts", created)
        self.assertEqual(created["HostConfig"]["RestartPolicy"], {"Name": "no"})
        self.assertIn("/containers/encore-signin-a1b2c3d4/start", [p for m, p, b in self.docker.calls])

    def test_the_page_waits_to_show_the_window_until_the_browser_answers(self):
        key, window = self.open_window()
        self.probe_ok = False
        status = self.call("GET", "/admin/api/youtube/signin/a1b2c3d4", cookie=key)[1]
        self.assertEqual((status["state"], status["ready"]), ("waiting", False))
        self.probe_ok = True
        status = self.call("GET", "/admin/api/youtube/signin/a1b2c3d4", cookie=key)[1]
        self.assertEqual((status["state"], status["ready"]), ("waiting", True))

    def test_the_first_time_the_browser_is_downloaded(self):
        self.docker.image_present = False
        key, window = self.open_window()
        self.assertEqual(window["state"], "waiting")
        self.assertIn("POST /images/create", self.docker.verbs())

    def test_only_one_window_is_open_at_a_time(self):
        key, first = self.open_window()
        r, second = self.call("POST", "/admin/api/youtube/signin", {}, cookie=key)
        self.assertEqual(second["window"], first["window"])
        self.assertEqual(len([v for v in self.docker.verbs() if v == "POST /containers/create"]), 1)
        r, current = self.call("GET", "/admin/api/youtube/signin", cookie=key)
        self.assertEqual(current["window"], first["window"])

    def test_the_page_learns_when_somebody_has_signed_in_in_the_window(self):
        key, window = self.open_window()
        status = self.call("GET", "/admin/api/youtube/signin/a1b2c3d4", cookie=key)[1]
        self.assertEqual(status["state"], "waiting", "no cookie file at all yet")
        self.browser_has(NOTHING_YET)
        status = self.call("GET", "/admin/api/youtube/signin/a1b2c3d4", cookie=key)[1]
        self.assertEqual(status["state"], "waiting")
        self.browser_has(GOOGLE_ONLY)
        status = self.call("GET", "/admin/api/youtube/signin/a1b2c3d4", cookie=key)[1]
        self.assertEqual(status["state"], "waiting", "Google alone is not enough: downloads need YouTube's own login")
        self.assertIn("Almost there", status["detail"])
        self.browser_has(SIGNED_IN)
        status = self.call("GET", "/admin/api/youtube/signin/a1b2c3d4", cookie=key)[1]
        self.assertEqual(status["state"], "signed_in")

    def test_a_sign_in_that_is_still_only_in_the_browsers_log_is_seen(self):
        key, window = self.open_window()
        self.browser_has(SIGNED_IN, in_log=True)
        self.assertIn(self.docker.files and "/config/profile/cookies.sqlite-wal", self.docker.files, "the cookies are only in the log")
        self.assertEqual(self.call("GET", "/admin/api/youtube/signin/a1b2c3d4", cookie=key)[1]["state"], "signed_in")

    def test_pressing_done_keeps_the_sign_in_as_an_account_and_deletes_the_window(self):
        key, window = self.open_window()
        self.browser_has(SIGNED_IN)
        seen = []
        self.stack.on_import = lambda: seen.append(self.docker.verbs())
        self.stack.summary = {"accounts": [{"id": "abcd1234", "label": "Spare account"}], "signedIn": True, "perHour": 400}
        r, data = self.call("POST", "/admin/api/youtube/signin/a1b2c3d4/finish", {"label": "Spare account"}, cookie=key)
        self.assertEqual((r.status, data["accounts"][0]["label"]), (200, "Spare account"))
        method, path, query, body = self.stack.calls[-1]
        self.assertEqual((method, path, body["label"]), ("POST", "/accounts", "Spare account"))
        self.assertIn("__Secure-3PSID", body["cookies"], "the songs service is given a cookies file made from the browser's own")
        self.assertIn("DELETE /containers/encore-signin-a1b2c3d4", self.docker.verbs())
        self.assertEqual(self.call("GET", "/admin/api/youtube/signin", cookie=key)[1], {"state": "gone"})
        verbs = seen[0]
        self.assertIn("POST /containers/encore-signin-a1b2c3d4/stop", verbs)
        last_read = max(i for i, v in enumerate(verbs) if v.endswith("/archive"))
        self.assertGreater(last_read, verbs.index("POST /containers/encore-signin-a1b2c3d4/stop"),
                           "the cookies that are kept are read AFTER the browser was stopped cleanly: they are its latest and nothing rotates them")

    def test_the_name_left_empty_is_not_sent_so_the_account_is_named_by_its_email(self):
        key, window = self.open_window()
        self.browser_has(SIGNED_IN)
        self.call("POST", "/admin/api/youtube/signin/a1b2c3d4/finish", {"label": ""}, cookie=key)
        self.assertNotIn("label", self.stack.calls[-1][3])

    def test_signing_in_again_replaces_that_accounts_login(self):
        key, window = self.open_window(replace="abcd1234")
        self.assertEqual(window["replace"], "abcd1234")
        self.browser_has(SIGNED_IN)
        self.call("POST", "/admin/api/youtube/signin/a1b2c3d4/finish", {"label": "ignored"}, cookie=key)
        method, path, query, body = self.stack.calls[-1]
        self.assertEqual((method, path), ("POST", "/accounts/abcd1234/login"))
        self.assertNotIn("label", body)

    def test_a_sign_in_that_could_not_be_kept_gives_the_person_their_window_back(self):
        key, window = self.open_window()
        self.browser_has(SIGNED_IN)
        self.stack.finish_status = 500
        r, data = self.call("POST", "/admin/api/youtube/signin/a1b2c3d4/finish", {}, cookie=key)
        self.assertEqual(r.status, 502)
        starts = [v for v in self.docker.verbs() if v == "POST /containers/encore-signin-a1b2c3d4/start"]
        self.assertEqual(len(starts), 2, "started once at the beginning and once more to give the window back")
        self.assertEqual(self.call("GET", "/admin/api/youtube/signin", cookie=key)[1]["window"], "a1b2c3d4")

    def test_pressing_done_before_signing_in_says_so_and_keeps_the_window_open(self):
        key, window = self.open_window()
        self.browser_has(GOOGLE_ONLY)
        r, data = self.call("POST", "/admin/api/youtube/signin/a1b2c3d4/finish", {"label": "x"}, cookie=key)
        self.assertEqual((r.status, data["message"]), (422, "Nobody has signed in in that window yet."))
        self.assertEqual(self.call("GET", "/admin/api/youtube/signin", cookie=key)[1]["window"], "a1b2c3d4")
        self.assertNotIn("POST /containers/encore-signin-a1b2c3d4/stop", self.docker.verbs(), "the window is left running")
        self.assertEqual(self.stack.calls, [], "nothing is handed to the songs service")

    def test_cancelling_deletes_the_window(self):
        key, window = self.open_window()
        r, data = self.call("POST", "/admin/api/youtube/signin/a1b2c3d4/cancel", {}, cookie=key)
        self.assertEqual((r.status, data["closed"]), (200, True))
        self.assertIn("DELETE /containers/encore-signin-a1b2c3d4", self.docker.verbs())

    def test_a_window_nobody_used_closes_by_itself(self):
        key, window = self.open_window()
        self.now += 15 * 60 + 1
        self.signin.sweep()
        self.assertEqual(self.call("GET", "/admin/api/youtube/signin", cookie=key)[1], {"state": "gone"})
        self.assertIn("DELETE /containers/encore-signin-a1b2c3d4", self.docker.verbs())

    def test_a_browser_that_closed_is_said_in_a_sentence(self):
        key, window = self.open_window()
        self.docker.running = False
        r, status = self.call("GET", "/admin/api/youtube/signin/a1b2c3d4", cookie=key)
        self.assertEqual(status["state"], "failed")
        self.assertIn("closed", status["message"])

    def test_a_browser_that_cannot_start_is_said_in_a_sentence_and_cleaned_up(self):
        self.docker.create_status = 500
        key, window = self.open_window()
        self.assertEqual(window["state"], "failed")
        self.assertIn("could not be started", window["message"])
        self.assertIn("DELETE /containers/encore-signin-a1b2c3d4", self.docker.verbs())

    def test_a_download_that_fails_is_said_in_a_sentence(self):
        self.docker.image_present = False
        self.docker.pull_error = "no space left on device"
        key, window = self.open_window()
        self.assertEqual(window["state"], "failed")
        self.assertNotIn("no space left", json.dumps(window), "docker's own words are for the log, not the page")

    def test_windows_left_behind_by_a_restart_are_removed_at_start(self):
        self.docker.leftover = ["encore-signin-deadbeef", "not-ours"]
        self.signin.clean_leftovers()
        self.assertIn("DELETE /containers/encore-signin-deadbeef", self.docker.verbs())
        self.assertNotIn("DELETE /containers/not-ours", self.docker.verbs())

    def test_a_window_name_that_is_not_one_of_ours_is_refused(self):
        key = self.sign_in()
        self.assertEqual(self.call("GET", "/admin/api/youtube/signin/..%2F..", cookie=key)[0].status, 404)
        self.assertEqual(self.call("POST", "/admin/api/youtube/signin", {"replace": "../../x"}, cookie=key)[0].status, 400)
        self.assertEqual(self.call("GET", "/admin/api/youtube/signin/ffffffff", cookie=key)[1], {"state": "gone"})


class DockerIsKeptNarrowTest(unittest.TestCase):
    def docker(self, fake=None):
        fake = fake or FakeDocker()
        return Docker(fake, fake, "lscr.io/linuxserver/chromium:latest"), fake

    def test_only_sign_in_windows_can_be_touched(self):
        docker, fake = self.docker()
        for bad in ("nginx", "encore-signin-", "encore-signin-ABCDEFGH", "encore-signin-abcdefg;rm", "../encore-signin-abcdefgh"):
            for action in (docker.start, docker.remove, docker.running):
                with self.assertRaises(DockerError):
                    action(bad)
        self.assertEqual(fake.calls, [], "nothing reached docker")

    def test_a_window_is_made_from_a_fixed_template_and_the_odd_arguments_are_refused(self):
        docker, fake = self.docker()
        docker.create("encore-signin-a1b2c3d4", network="encore-server_default")
        config = fake.calls[0][2]
        self.assertEqual(sorted(config["HostConfig"]), ["Memory", "NetworkMode", "RestartPolicy", "ShmSize"])
        self.assertNotIn("Privileged", config["HostConfig"])
        self.assertNotIn("PortBindings", config["HostConfig"])
        self.assertNotIn("Binds", config["HostConfig"])
        self.assertNotIn("Cmd", config)
        self.assertNotIn("Entrypoint", config)
        self.assertLessEqual(config["HostConfig"]["Memory"], 1024 * 1024 * 1024, "a small server must be able to carry it")
        for bad in ("bad name;x", "", "-x"):
            with self.assertRaises(DockerError):
                docker.create("encore-signin-a1b2c3d4", network=bad)
        with self.assertRaises(DockerError):
            docker.create("evil", network="encore-server_default")

    def test_only_a_cookie_file_of_one_of_our_windows_can_be_copied_out(self):
        docker, fake = self.docker()
        fake.files = firefox_cookies(SIGNED_IN)
        self.assertIsNotNone(docker.read_file("encore-signin-a1b2c3d4", "/config/profile/cookies.sqlite"))
        self.assertIsNone(docker.read_file("encore-signin-a1b2c3d4", "/config/profile/nothing.sqlite"), "a missing file is None, not an error")
        for name, path in (("nginx", "/config/profile/cookies.sqlite"), ("encore-signin-a1b2c3d4", "/etc/passwd"),
                           ("encore-signin-a1b2c3d4", "/config/../etc/passwd"), ("encore-signin-a1b2c3d4", "config/x")):
            with self.assertRaises(DockerError):
                docker.read_file(name, path)
        archives = [p for m, p, b in fake.calls if "/archive" in p]
        self.assertEqual(len(archives), 2, "the refused ones never reached Docker")

    def test_a_clean_stop_is_a_stop_of_one_of_our_windows_only(self):
        docker, fake = self.docker()
        docker.stop("encore-signin-a1b2c3d4")
        self.assertIn("POST /containers/encore-signin-a1b2c3d4/stop?t=15", [f"{m} {p}" for m, p, b in fake.calls])
        with self.assertRaises(DockerError):
            docker.stop("nginx")

    def test_the_image_name_is_checked(self):
        fake = FakeDocker()
        for bad in ("", "x; rm -rf /", "a b", "-flag", "img:tag:extra"):
            with self.assertRaises(ValueError):
                Docker(fake, fake, bad)

    def test_a_pull_that_docker_reports_as_an_error_raises(self):
        docker, fake = self.docker()
        fake.pull_error = "denied"
        with self.assertRaises(DockerError):
            docker.pull()
        fake.pull_error = None
        docker.pull()
        self.assertIn("fromImage=lscr.io%2Flinuxserver%2Fchromium&tag=latest", [p for m, p, b in fake.calls if "images/create" in p][-1])

    def test_leftovers_are_found_by_label_and_only_our_names_count(self):
        docker, fake = self.docker()
        fake.leftover = ["encore-signin-abcdef12", "something-else"]
        self.assertEqual(docker.leftovers(), ["encore-signin-abcdef12"])


class ThePagesTest(SiteTestBase):
    def test_the_front_page_and_its_files_are_served_and_nothing_else(self):
        for path, kind in (("/", "text/html"), ("/app.js", "javascript"), ("/style.css", "text/css"), ("/tokens.css", "text/css"),
                           ("/fonts/Figtree-Regular.ttf", "font/ttf")):
            r = self.api.handle("GET", path, {}, b"")
            self.assertEqual(r.status, 200, path)
            self.assertIn(kind, r.content_type)
        for path in ("/../server.py", "/fonts/../server.py", "/server.py", "/static/app.js", "/etc/passwd", "/fonts/nothing.ttf"):
            self.assertEqual(self.api.handle("GET", path, {}, b"").status, 404, path)

    def test_the_pages_are_read_only(self):
        self.assertEqual(self.api.handle("POST", "/", H, b"").status, 405)

    def test_no_page_loads_anything_from_the_internet_or_marks_text_up_from_the_server(self):
        static = Path(__file__).parent.parent / "encore_admin" / "static"
        for name in ("index.html", "app.js", "style.css"):
            text = (static / name).read_text(encoding="utf-8")
            self.assertNotIn("http://", text.replace("https://myaccount.google.com", ""), name)
            self.assertNotIn("innerHTML", text, name)
            self.assertNotIn("eval(", text, name)
        self.assertNotIn("https://cdn", (static / "index.html").read_text(encoding="utf-8"))

    def test_the_colours_are_the_apps_own(self):
        root = Path(__file__).resolve().parents[4]
        result = subprocess.run([sys.executable, str(root / "tools" / "gen_admin_tokens.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class OverRealHttpTest(SiteTestBase):
    """One run through a real socket, to see the headers a browser would see."""

    def test_headers_cookie_and_cors_posture(self):
        httpd = serve(self.api, "127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        port = httpd.server_address[1]

        def get(path, headers=None, method="GET", body=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            data = r.read()
            c.close()
            return r, data

        r, data = get("/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"Encore admin", data)
        self.assertIn("default-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(r.getheader("Cache-Control"), "no-store")
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"), "no other site may call this one")

        body = json.dumps({"user": "dana", "password": "correct horse"})
        r, data = get("/admin/api/login", {"Content-Type": "application/json", "X-Encore-Admin": "1"}, "POST", body)
        self.assertEqual(r.status, 200, data)
        cookie = r.getheader("Set-Cookie").split(";")[0]
        r, data = get("/admin/api/me", {"Cookie": cookie})
        self.assertEqual(json.loads(data)["user"], "dana")
        r, data = get("/admin/api/login?x=1", {"X-Encore-Admin": "1"}, "POST", json.dumps({"user": "dana", "password": "bad"}))
        self.assertEqual(r.status, 401)


if __name__ == "__main__":
    unittest.main()
