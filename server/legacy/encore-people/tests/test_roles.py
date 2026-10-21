"""People and roles (ADR-092): owners, people who may invite, and guests.

The owner, 2026-10-17: "I can't trust them into inviting people ... multiple owners, a best friend who can invite but is not an owner, a list of
guests we can remove or edit." Each test says what a person on the server would see or be refused.
"""
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

NOW = 1_760_000_000.0


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> float:
        return self.now


def token(user: str, password: str, salt: str = "abc123") -> dict:
    return {"u": user, "t": hashlib.md5((password + salt).encode()).hexdigest(), "s": salt}


class Accounts:
    """The music server's accounts: who exists, their password, whether they administer it. One dict shared by the fake music
    server (which answers logins), the directory (which lists and removes) and the provisioner (which creates)."""

    def __init__(self) -> None:
        self.users = {  # name -> (password, administrator)
            "owner": ("owner-pass", True),
            "nora": ("nora-pass", False),   # a founding owner named in the settings
            "kim": ("kim-pass", False),     # will be given "can invite"
            "sara": ("sara-pass", False),
            "mia": ("mia-pass", False),
        }
        self.removed: list[str] = []

    # --- the music server (logins)
    def http(self, url: str) -> dict:
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        entry = self.users.get(q.get("u", ""))
        if not entry or q.get("t") != hashlib.md5((entry[0] + q.get("s", "")).encode()).hexdigest():
            return {"status": "failed", "error": {"code": 40, "message": "Wrong username or password"}}
        if "getUser" in parsed.path:
            return {"status": "ok", "user": {"username": q["u"], "adminRole": entry[1]}}
        return {"status": "ok"}

    # --- the directory (an administrator's view)
    def listing(self) -> list[dict]:
        return [{"name": n, "admin": a} for n, (_, a) in self.users.items()]

    def remove_person(self, name: str) -> None:
        self.removed.append(name)
        self.users.pop(name, None)

    # --- the provisioner (an invitation made an account)
    def add_person(self, username: str, password: str) -> None:
        self.users[username] = (password, False)


class RolesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.clock = Clock()
        self.accounts = Accounts()
        self.invites = Invites(self.root / "people.db", provisioner=self.accounts, clock=self.clock)
        self.addCleanup(self.invites.close)
        self.activity = Activity(self.root / "sharing.json", clock=self.clock)
        self.roles = Roles(self.root / "roles.db")
        self.addCleanup(self.roles.close)
        self.api = self.make_api()

    def make_api(self) -> Api:
        return Api(
            invites=self.invites, activity=self.activity, roles=self.roles, directory=self.accounts,
            navidrome=Navidrome("http://music", http=self.accounts.http, clock=self.clock),
            settings=Settings(public_url="https://music.example.ts.net", server_name="Home", owners=frozenset({"nora"})),
            clock=self.clock)

    # ------------------------------------------------------------ helpers
    def call(self, who: str | None, method: str, path: str, body: object | None = None):
        query = urlencode(token(who, self.accounts.users[who][0])) if who else ""
        data = json.dumps(body).encode() if body is not None else b""
        return self.api.handle(method, path + ("?" + query if query else ""), {}, data, "198.51.100.7")

    def json_of(self, response):
        return json.loads(response.body)

    def me(self, who: str) -> dict:
        return self.json_of(self.call(who, "GET", "/api/me"))

    def make_kim_an_inviter(self) -> None:
        self.assertEqual(self.call("owner", "PUT", "/api/people/kim", {"role": "inviter"}).status, 204)

    def invite(self, who: str, body: object | None = None) -> dict:
        r = self.call(who, "POST", "/api/invites", body)
        self.assertEqual(r.status, 201, r.body)
        return self.json_of(r)

    def redeem(self, made: dict, name: str):
        code = made["url"].rsplit("/", 1)[-1]
        r = self.api.handle("POST", f"/join/{code}/redeem", {}, json.dumps({"username": name, "password": "a-long-password"}).encode(),
                            "198.51.100.8")
        self.assertEqual(r.status, 201, r.body)

    def person(self, who: str, name: str) -> dict:
        listing = self.json_of(self.call(who, "GET", "/api/people"))["people"]
        return next(p for p in listing if p["user"] == name)

    # ------------------------------------------------------------ who is what
    def test_the_music_servers_administrator_is_an_owner(self) -> None:
        me = self.me("owner")
        self.assertEqual((me["role"], me["canInvite"], me["canManage"]), ("owner", True, True))

    def test_a_name_in_the_settings_is_a_founding_owner(self) -> None:
        me = self.me("nora")
        self.assertEqual((me["admin"], me["role"], me["canManage"]), (False, "owner", True))

    def test_everybody_else_is_a_guest_until_an_owner_says_otherwise(self) -> None:
        me = self.me("sara")
        self.assertEqual((me["role"], me["canInvite"], me["canManage"]), ("guest", False, False))

    # ------------------------------------------------------------ guests can do nothing about people
    def test_a_guest_cannot_invite_see_or_change_anybody(self) -> None:
        for method, path in (("POST", "/api/invites"), ("GET", "/api/invites"), ("GET", "/api/people"),
                             ("PUT", "/api/people/mia"), ("DELETE", "/api/people/mia")):
            r = self.call("sara", method, path, {"role": "owner"} if method == "PUT" else None)
            self.assertEqual(r.status, 403, f"{method} {path}")

    # ------------------------------------------------------------ an owner makes someone "can invite"
    def test_an_owner_can_let_a_trusted_friend_invite(self) -> None:
        self.make_kim_an_inviter()

        me = self.me("kim")
        self.assertEqual((me["role"], me["canInvite"], me["canManage"]), ("inviter", True, False))

    def test_the_change_survives_a_restart(self) -> None:
        self.make_kim_an_inviter()
        self.roles.close()
        self.roles = Roles(self.root / "roles.db")
        self.addCleanup(self.roles.close)
        self.api = self.make_api()

        self.assertEqual(self.me("kim")["role"], "inviter")

    def test_someone_who_can_invite_makes_guests_and_nothing_more(self) -> None:
        self.make_kim_an_inviter()

        asking_for_more = self.invite("kim", {"role": "inviter"})
        self.redeem(asking_for_more, "ben")

        self.assertEqual(self.person("owner", "ben")["role"], "guest",
                         "a person who may invite cannot hand out the right to invite")

    def test_someone_who_can_invite_cannot_see_or_change_people(self) -> None:
        self.make_kim_an_inviter()
        for method, path in (("GET", "/api/people"), ("PUT", "/api/people/sara"), ("DELETE", "/api/people/sara")):
            self.assertEqual(self.call("kim", method, path, {"role": "owner"} if method == "PUT" else None).status, 403, path)

    # ------------------------------------------------------------ the role travels with the invitation
    def test_an_invitation_from_an_owner_is_for_a_guest_unless_the_owner_says_more(self) -> None:
        plain = self.invite("owner")
        trusted = self.invite("owner", {"role": "inviter"})
        self.redeem(plain, "ben")
        self.redeem(trusted, "tom")

        self.assertEqual(self.person("owner", "ben")["role"], "guest")
        self.assertEqual(self.person("owner", "tom")["role"], "inviter")

    def test_the_new_person_is_listed_with_who_invited_them(self) -> None:
        self.make_kim_an_inviter()
        self.redeem(self.invite("kim"), "ben")

        ben = self.person("owner", "ben")

        self.assertEqual(ben["invitedBy"], "kim")
        self.assertGreater(ben["joinedAt"], 0)

    def test_an_unknown_role_in_an_invitation_is_refused(self) -> None:
        self.assertEqual(self.call("owner", "POST", "/api/invites", {"role": "emperor"}).status, 400)

    # ------------------------------------------------------------ invitations are each person's own
    def test_someone_who_can_invite_sees_and_cancels_only_their_own_invitations(self) -> None:
        self.make_kim_an_inviter()
        mine = self.invite("kim")
        other = self.invite("owner")

        seen = self.json_of(self.call("kim", "GET", "/api/invites"))["invites"]

        self.assertEqual([i["id"] for i in seen], [mine["id"]])
        self.assertEqual(self.call("kim", "DELETE", f"/api/invites/{other['id']}").status, 404)
        self.assertEqual(self.call("kim", "DELETE", f"/api/invites/{mine['id']}").status, 204)

    def test_an_owner_sees_every_invitation_and_can_cancel_any(self) -> None:
        self.make_kim_an_inviter()
        theirs = self.invite("kim")
        mine = self.invite("owner")

        seen = {i["id"] for i in self.json_of(self.call("owner", "GET", "/api/invites"))["invites"]}

        self.assertEqual(seen, {theirs["id"], mine["id"]})
        self.assertEqual(self.call("owner", "DELETE", f"/api/invites/{theirs['id']}").status, 204)

    # ------------------------------------------------------------ the list of people (owners only)
    def test_the_list_shows_everybody_with_their_role(self) -> None:
        self.make_kim_an_inviter()

        people = {p["user"]: p for p in self.json_of(self.call("owner", "GET", "/api/people"))["people"]}

        self.assertEqual({n: p["role"] for n, p in people.items()},
                         {"owner": "owner", "nora": "owner", "kim": "inviter", "sara": "guest", "mia": "guest"})
        self.assertTrue(people["owner"]["fixed"], "the administrator's role cannot be changed here")
        self.assertTrue(people["nora"]["fixed"], "nor a founding owner's")
        self.assertFalse(people["sara"]["fixed"])

    def test_the_list_never_carries_a_password_or_a_token(self) -> None:
        body = self.call("owner", "GET", "/api/people").body.decode()
        for secret in ("owner-pass", "sara-pass", "password"):
            self.assertNotIn(secret, body)

    # ------------------------------------------------------------ changing a role: the rules
    def test_an_owner_can_make_another_person_an_owner(self) -> None:
        self.assertEqual(self.call("owner", "PUT", "/api/people/sara", {"role": "owner"}).status, 204)

        self.assertEqual(self.me("sara")["canManage"], True)
        self.assertEqual(self.call("sara", "PUT", "/api/people/mia", {"role": "inviter"}).status, 204,
                         "a second owner can run the server too (a couple)")

    def test_an_owner_can_take_the_right_back(self) -> None:
        self.make_kim_an_inviter()

        self.assertEqual(self.call("owner", "PUT", "/api/people/kim", {"role": "guest"}).status, 204)

        self.assertEqual(self.me("kim")["canInvite"], False)

    def test_a_founding_owner_cannot_be_demoted_so_the_server_always_has_one(self) -> None:
        for who in ("owner", "nora"):
            r = self.call("owner", "PUT", f"/api/people/{who}", {"role": "guest"})
            self.assertEqual(r.status, 403, who)
            self.assertIn("founding", self.json_of(r)["error"].lower())
        self.assertEqual(self.me("nora")["role"], "owner")

    def test_an_unknown_role_or_person_is_refused_in_plain_words(self) -> None:
        bad = self.call("owner", "PUT", "/api/people/sara", {"role": "emperor"})
        self.assertEqual(bad.status, 400)
        self.assertEqual(self.call("owner", "PUT", "/api/people/ghost", {"role": "guest"}).status, 404)
        self.assertEqual(self.call("owner", "PUT", "/api/people/sara", {}).status, 400)

    def test_names_are_not_case_sensitive(self) -> None:
        self.assertEqual(self.call("owner", "PUT", "/api/people/SARA", {"role": "inviter"}).status, 204)

        self.assertEqual(self.me("sara")["role"], "inviter")

    # ------------------------------------------------------------ removing a person
    def test_an_owner_can_remove_a_guest_and_their_music_is_not_touched(self) -> None:
        r = self.call("owner", "DELETE", "/api/people/sara")

        self.assertEqual(r.status, 204)
        self.assertEqual(self.accounts.removed, ["sara"])
        names = [p["user"] for p in self.json_of(self.call("owner", "GET", "/api/people"))["people"]]
        self.assertNotIn("sara", names)

    def test_a_removed_person_can_no_longer_use_the_service_even_with_a_login_the_service_had_just_seen(self) -> None:
        self.assertEqual(self.call("sara", "GET", "/api/me").status, 200)  # the service now remembers sara's login for a few minutes

        self.call("owner", "DELETE", "/api/people/sara")

        # The music server forgot sara, and so must the service, at once.
        query = urlencode(token("sara", "sara-pass"))
        self.assertEqual(self.api.handle("GET", "/api/me?" + query, {}, b"", "198.51.100.7").status, 401)

    def test_removing_a_person_cancels_the_invitations_they_made(self) -> None:
        self.make_kim_an_inviter()
        open_one = self.invite("kim")

        self.call("owner", "DELETE", "/api/people/kim")

        code = open_one["url"].rsplit("/", 1)[-1]
        self.assertEqual(self.api.handle("GET", f"/join/{code}/info", {}, b"", "198.51.100.9").status, 404)

    def test_a_removed_person_forgets_their_role_and_what_they_shared(self) -> None:
        self.make_kim_an_inviter()
        self.activity.set_sharing("kim", True)
        self.activity.report("kim", {"title": "Dogs", "artist": "Pink Floyd", "state": "playing"})

        self.call("owner", "DELETE", "/api/people/kim")

        self.assertEqual(self.roles.get("kim"), None)
        self.assertFalse(self.activity.is_sharing("kim"))
        self.assertEqual([e.username for e in self.activity.others("owner")], [])

    def test_nobody_can_remove_a_founding_owner_or_themselves(self) -> None:
        self.call("owner", "PUT", "/api/people/sara", {"role": "owner"})
        for target in ("owner", "nora"):
            r = self.call("sara", "DELETE", f"/api/people/{target}")
            self.assertEqual(r.status, 403, target)
        mine = self.call("sara", "DELETE", "/api/people/sara")
        self.assertEqual(mine.status, 403)
        self.assertIn("yourself", self.json_of(mine)["error"].lower())
        self.assertEqual(self.accounts.removed, [])

    def test_removing_someone_who_is_not_there_says_so(self) -> None:
        self.assertEqual(self.call("owner", "DELETE", "/api/people/ghost").status, 404)

    # ------------------------------------------------------------ the old promise still holds
    def test_the_invitation_page_and_everything_signed_out_are_unchanged(self) -> None:
        made = self.invite("owner")
        code = made["url"].rsplit("/", 1)[-1]

        self.assertEqual(self.api.handle("GET", f"/join/{code}/info", {}, b"", "198.51.100.7").status, 200)
        self.assertEqual(self.call(None, "GET", "/api/people").status, 401)


if __name__ == "__main__":
    unittest.main()
