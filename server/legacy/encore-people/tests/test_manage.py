"""Looking after people from the admin (docs/48): add a person, reset a password (a temporary one or a one-time link), "I forgot my
password" reaching the owner, lock, last seen, and what a person can do for themself."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from encore_people.activity import Activity
from encore_people.invites import Invites
from encore_people.navidrome import Navidrome
from encore_people.people import Roles
from encore_people.server import Api, Settings
from encore_people.standing import ASK_EVERY_S, CODE_TTL_S, Standing

from tests.test_api import NOW, PEOPLE, Clock, FakeMusicServer, Provisioner, token


class Directory:
    """The music server's accounts, as the admin's login sees them, including what a password change does."""

    def __init__(self):
        self.accounts = {
            "owner": {"admin": True, "lastAccess": NOW - 60, "createdAt": NOW - 90 * 86400},
            "sara": {"admin": False, "lastAccess": NOW - 3 * 86400, "createdAt": NOW - 30 * 86400},
            "mia": {"admin": False, "lastAccess": None, "createdAt": NOW - 86400},
        }
        self.passwords: dict[str, str] = {}
        self.removed: list[str] = []

    def listing(self):
        return [{"name": n, "admin": a["admin"], "lastAccess": a["lastAccess"], "createdAt": a["createdAt"]} for n, a in self.accounts.items()]

    def remove_person(self, name):
        self.removed.append(name)
        self.accounts.pop(name, None)

    def set_password(self, name, password):
        self.passwords[name] = password

    def add_person(self, username, password):
        if username in self.accounts:
            from encore_people.invites import ProvisionError
            raise ProvisionError("That name is already taken. Choose another.")
        self.accounts[username] = {"admin": False, "lastAccess": None, "createdAt": NOW}
        self.passwords[username] = password


class ManageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.clock = Clock()
        self.music = FakeMusicServer()
        self.directory = Directory()
        self.invites = Invites(root / "people.db", provisioner=Provisioner(), clock=self.clock)
        self.addCleanup(self.invites.close)
        self.standing = Standing(clock=self.clock)
        self.addCleanup(self.standing.close)
        self.api = self.make_api()

    def make_api(self, public_url="https://music.example.ts.net"):
        return Api(invites=self.invites, activity=Activity(Path(self._tmp.name) / "sharing.json", clock=self.clock),
                   navidrome=Navidrome("http://music", http=self.music, clock=self.clock),
                   settings=Settings(public_url=public_url, server_name="Home music"), roles=Roles(), directory=self.directory,
                   standing=self.standing, clock=self.clock)

    def call(self, method, path, *, auth=None, body=None, ip="198.51.100.7"):
        query = urlencode(token(*auth)) if auth else ""
        data = json.dumps(body).encode() if body is not None else b""
        return self.api.handle(method, path + ("?" + query if query else ""), {}, data, ip)

    def j(self, response):
        return json.loads(response.body)

    OWNER = ("owner", "owner-pass")
    SARA = ("sara", "sara-pass")


class WhenTheMusicServerIsBusyTest(ManageTest):
    def test_the_owner_is_told_to_try_again_not_given_an_error_page(self):
        from encore_people.people import DirectoryUnavailable

        def busy():
            raise DirectoryUnavailable("HTTP 429")

        self.directory.listing = busy
        r = self.call("GET", "/api/people", auth=self.OWNER)
        self.assertEqual(r.status, 503)
        self.assertIn("Try again in a moment", self.j(r)["error"])


class TheListTest(ManageTest):
    def test_each_person_shows_when_they_last_came_and_what_state_their_account_is_in(self):
        self.standing.set_flags("sara", paused=True)
        self.standing.set_flags("mia", must_change=True)
        self.standing.ask("sara")
        people = {p["user"]: p for p in self.j(self.call("GET", "/api/people", auth=self.OWNER))["people"]}
        self.assertEqual(people["owner"]["lastAccess"], NOW - 60)
        self.assertEqual((people["sara"]["paused"], people["sara"]["resetAsked"]), (True, NOW))
        self.assertEqual((people["mia"]["mustChange"], people["mia"]["lastAccess"]), (True, None))
        self.assertEqual(people["mia"]["createdAt"], NOW - 86400)

    def test_a_person_who_is_not_an_owner_sees_nothing_of_this(self):
        self.assertEqual(self.call("GET", "/api/people", auth=self.SARA).status, 403)
        self.assertEqual(self.call("POST", "/api/people", auth=self.SARA, body={"name": "tom"}).status, 403)
        self.assertEqual(self.call("GET", "/api/resets", auth=self.SARA).status, 403)


class AddingAPersonTest(ManageTest):
    def test_the_owner_adds_a_person_and_reads_out_a_temporary_password_once(self):
        r = self.call("POST", "/api/people", auth=self.OWNER, body={"name": "tom"})
        self.assertEqual(r.status, 201, r.body)
        body = self.j(r)
        self.assertEqual(body["user"], "tom")
        self.assertRegex(body["temporaryPassword"], r"^[a-z]+(-[a-z]+){3}-\d\d$")
        self.assertEqual(self.directory.passwords["tom"], body["temporaryPassword"])
        tom = next(p for p in self.j(self.call("GET", "/api/people", auth=self.OWNER))["people"] if p["user"] == "tom")
        self.assertEqual((tom["role"], tom["mustChange"], tom["invitedBy"]), ("guest", True, "owner"))

    def test_a_person_can_be_added_as_someone_who_may_invite(self):
        self.call("POST", "/api/people", auth=self.OWNER, body={"name": "tom", "role": "inviter"})
        tom = next(p for p in self.j(self.call("GET", "/api/people", auth=self.OWNER))["people"] if p["user"] == "tom")
        self.assertEqual(tom["role"], "inviter")

    def test_a_name_that_will_not_do_is_said_in_a_sentence(self):
        for name in ("ab", "Tom Smith", "admin", "9lives", ""):
            r = self.call("POST", "/api/people", auth=self.OWNER, body={"name": name})
            self.assertEqual(r.status, 400, name)
            self.assertTrue(self.j(r)["error"])
        r = self.call("POST", "/api/people", auth=self.OWNER, body={"name": "sara"})
        self.assertEqual((r.status, self.j(r)["error"]), (409, "That name is already taken. Choose another."))
        self.assertEqual(self.call("POST", "/api/people", auth=self.OWNER, body={"name": "tom", "role": "owner"}).status, 400)
        self.assertEqual(self.call("POST", "/api/people", auth=self.OWNER, body={}).status, 400)


class ResettingAPasswordTest(ManageTest):
    def test_a_temporary_password_replaces_the_old_one_and_must_be_changed(self):
        self.standing.ask("sara")
        r = self.call("POST", "/api/people/sara/password", auth=self.OWNER, body={"mode": "temporary"})
        self.assertEqual(r.status, 200, r.body)
        temp = self.j(r)["temporaryPassword"]
        self.assertEqual(self.directory.passwords["sara"], temp)
        self.assertEqual(self.standing.flags("sara"), (False, True))
        self.assertEqual(self.standing.asks(), {}, "the request is answered")

    def test_a_one_time_link_is_made_and_works_once_for_an_hour(self):
        self.standing.ask("sara")
        r = self.call("POST", "/api/people/sara/password", auth=self.OWNER, body={"mode": "link"})
        body = self.j(r)
        self.assertEqual(r.status, 200, r.body)
        self.assertTrue(body["url"].startswith("https://music.example.ts.net/people/reset/"))
        self.assertEqual(body["expiresAt"], NOW + CODE_TTL_S)
        code = body["code"]
        info = self.j(self.call("GET", f"/people/reset/{code}/info"))
        self.assertEqual((info["valid"], info["user"]), (True, "sara"))
        self.assertEqual(self.directory.passwords, {}, "nothing is changed until the person chooses")
        done = self.call("POST", f"/people/reset/{code}/redeem", body={"password": "a brand new one"})
        self.assertEqual(done.status, 200, done.body)
        self.assertEqual(self.directory.passwords["sara"], "a brand new one")
        self.assertEqual(self.standing.flags("sara"), (False, False))
        again = self.call("POST", f"/people/reset/{code}/redeem", body={"password": "another try here"})
        self.assertEqual(again.status, 404)
        self.assertEqual(self.directory.passwords["sara"], "a brand new one")

    def test_a_link_that_ran_out_or_was_replaced_does_not_work(self):
        first = self.j(self.call("POST", "/api/people/sara/password", auth=self.OWNER, body={"mode": "link"}))["code"]
        second = self.j(self.call("POST", "/api/people/sara/password", auth=self.OWNER, body={"mode": "link"}))["code"]
        self.assertEqual(self.call("POST", f"/people/reset/{first}/redeem", body={"password": "long enough pw"}).status, 404)
        self.clock.now += CODE_TTL_S + 1
        self.assertEqual(self.call("POST", f"/people/reset/{second}/redeem", body={"password": "long enough pw"}).status, 404)
        self.assertEqual(self.j(self.call("GET", f"/people/reset/{second}/info"))["valid"], False)

    def test_the_new_password_has_to_be_a_real_one_and_a_bad_try_does_not_use_the_link_up(self):
        code = self.j(self.call("POST", "/api/people/sara/password", auth=self.OWNER, body={"mode": "link"}))["code"]
        short = self.call("POST", f"/people/reset/{code}/redeem", body={"password": "short"})
        self.assertEqual(short.status, 400)
        self.assertIn("8 characters", self.j(short)["error"])
        self.assertEqual(self.call("POST", f"/people/reset/{code}/redeem", body={"password": "long enough pw"}).status, 200)

    def test_the_page_a_person_opens_names_them_and_a_dead_link_says_so(self):
        code = self.j(self.call("POST", "/api/people/sara/password", auth=self.OWNER, body={"mode": "link"}))["code"]
        page = self.call("GET", f"/people/reset/{code}")
        self.assertEqual(page.status, 200)
        self.assertIn(b"sara", page.body)
        self.assertIn(b"Home music", page.body)
        self.assertEqual(self.call("GET", "/people/reset/not-a-real-code-at-all").status, 404)

    def test_without_a_public_address_the_owner_still_gets_the_code_to_read_out(self):
        api = self.make_api(public_url="")
        r = api.handle("POST", "/api/people/sara/password?" + urlencode(token(*self.OWNER)), {}, json.dumps({"mode": "link"}).encode(), "1.1.1.1")
        body = json.loads(r.body)
        self.assertEqual(r.status, 200)
        self.assertIsNone(body["url"])
        self.assertTrue(body["code"])

    def test_who_may_not_be_reset_from_here(self):
        for target in ("owner",):
            r = self.call("POST", f"/api/people/{target}/password", auth=self.OWNER, body={"mode": "temporary"})
            self.assertEqual(r.status, 403, target)
        self.assertEqual(self.call("POST", "/api/people/nobody/password", auth=self.OWNER, body={"mode": "temporary"}).status, 404)
        self.assertEqual(self.call("POST", "/api/people/sara/password", auth=self.OWNER, body={"mode": "email"}).status, 400)
        self.assertEqual(self.call("POST", "/api/people/mia/password", auth=self.SARA, body={"mode": "temporary"}).status, 403)
        self.assertEqual(self.directory.passwords, {})


class LockingTest(ManageTest):
    def test_locking_replaces_the_password_with_one_nobody_knows_and_marks_the_person_paused(self):
        r = self.call("POST", "/api/people/sara/lock", auth=self.OWNER)
        self.assertEqual(r.status, 204)
        self.assertGreater(len(self.directory.passwords["sara"]), 20)
        self.assertNotIn(self.directory.passwords["sara"], ("sara-pass",))
        self.assertEqual(self.standing.flags("sara"), (True, False))

    def test_unlocking_is_a_reset_and_ends_the_pause(self):
        self.call("POST", "/api/people/sara/lock", auth=self.OWNER)
        r = self.call("POST", "/api/people/sara/unlock", auth=self.OWNER)
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual(self.directory.passwords["sara"], self.j(r)["temporaryPassword"])
        self.assertEqual(self.standing.flags("sara"), (False, True))

    def test_the_owner_cannot_lock_themself_or_another_founding_owner(self):
        self.assertEqual(self.call("POST", "/api/people/owner/lock", auth=self.OWNER).status, 403)
        self.assertEqual(self.call("POST", "/api/people/nobody/lock", auth=self.OWNER).status, 404)
        self.assertEqual(self.call("POST", "/api/people/mia/lock", auth=self.SARA).status, 403)

    def test_removing_a_person_forgets_their_standing_too(self):
        self.standing.set_flags("mia", paused=True)
        self.standing.ask("mia")
        self.call("POST", "/api/people/mia/password", auth=self.OWNER, body={"mode": "link"})
        self.assertEqual(self.call("DELETE", "/api/people/mia", auth=self.OWNER).status, 204)
        self.assertEqual((self.standing.flags("mia"), self.standing.asks()), ((False, False), {}))


class ForgotMyPasswordTest(ManageTest):
    ANSWER = {"ok": True, "message": "If that is an account on this server, its owner has been told. Ask them for a link."}

    def test_the_answer_is_the_same_whether_or_not_the_name_is_an_account(self):
        real = self.call("POST", "/api/reset/ask", body={"user": "sara"})
        fake = self.call("POST", "/api/reset/ask", body={"user": "nobody-here"})
        self.assertEqual((real.status, self.j(real)), (202, self.ANSWER))
        self.assertEqual((fake.status, self.j(fake)), (202, self.ANSWER))

    def test_only_a_real_account_reaches_the_owner_and_only_the_owner_sees_it(self):
        self.call("POST", "/api/reset/ask", body={"user": "Sara"})
        self.call("POST", "/api/reset/ask", body={"user": "nobody-here"})
        asks = self.j(self.call("GET", "/api/resets", auth=self.OWNER))["requests"]
        self.assertEqual([(a["user"], a["askedAt"]) for a in asks], [("sara", NOW)])
        self.assertEqual(self.call("GET", "/api/resets", auth=self.SARA).status, 403)

    def test_asking_again_within_ten_minutes_changes_nothing(self):
        self.call("POST", "/api/reset/ask", body={"user": "sara"})
        self.clock.now += ASK_EVERY_S - 1
        self.call("POST", "/api/reset/ask", body={"user": "sara"})
        self.assertEqual(self.standing.asks()["sara"], NOW)
        self.clock.now += 2
        self.call("POST", "/api/reset/ask", body={"user": "sara"})
        self.assertEqual(self.standing.asks()["sara"], self.clock.now)

    def test_the_owner_can_dismiss_a_request(self):
        self.call("POST", "/api/reset/ask", body={"user": "sara"})
        self.assertEqual(self.call("DELETE", "/api/resets/sara", auth=self.OWNER).status, 204)
        self.assertEqual(self.j(self.call("GET", "/api/resets", auth=self.OWNER))["requests"], [])

    def test_a_flood_of_asks_from_one_address_is_slowed_down(self):
        statuses = [self.call("POST", "/api/reset/ask", body={"user": f"name{i}"}, ip="203.0.113.9").status for i in range(30)]
        self.assertIn(429, statuses)
        self.assertEqual(statuses[0], 202)

    def test_bad_input_is_a_sentence_not_a_crash(self):
        for body in ({}, {"user": 5}, {"user": ""}, {"user": "x" * 500}):
            self.assertEqual(self.call("POST", "/api/reset/ask", body=body).status, 400, body)
        self.assertEqual(self.api.handle("POST", "/api/reset/ask", {}, b"{nope", "1.2.3.4").status, 400)


class ChangingMyOwnPasswordTest(ManageTest):
    def test_me_says_when_a_new_password_has_to_be_chosen(self):
        self.assertFalse(self.j(self.call("GET", "/api/me", auth=self.SARA))["mustChangePassword"])
        self.standing.set_flags("sara", must_change=True)
        self.assertTrue(self.j(self.call("GET", "/api/me", auth=self.SARA))["mustChangePassword"])

    def test_choosing_a_new_password_replaces_the_temporary_one_and_ends_the_request(self):
        self.standing.set_flags("sara", must_change=True)
        r = self.call("POST", "/api/me/password", auth=self.SARA, body={"password": "my very own password"})
        self.assertEqual(r.status, 204, r.body)
        self.assertEqual(self.directory.passwords["sara"], "my very own password")
        self.assertEqual(self.standing.flags("sara"), (False, False))

    def test_a_weak_password_is_said_in_a_sentence_and_nothing_changes(self):
        r = self.call("POST", "/api/me/password", auth=self.SARA, body={"password": "short"})
        self.assertEqual(r.status, 400)
        self.assertIn("8 characters", self.j(r)["error"])
        self.assertEqual(self.directory.passwords, {})
        self.assertEqual(self.call("POST", "/api/me/password", body={"password": "long enough password"}).status, 401)


if __name__ == "__main__":
    unittest.main()
