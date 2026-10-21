"""The HTTP surface (docs/35): who may call what, what is public, what is refused, rate limits. The Api class is driven directly
(no sockets), with a fake music server that knows two people: an administrator and an ordinary one."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from encore_people.activity import Activity
from encore_people.invites import Invites, ProvisionError
from encore_people.navidrome import Navidrome
from encore_people.server import Api, Settings

NOW = 1_760_000_000.0
PEOPLE = {"owner": ("owner-pass", True), "sara": ("sara-pass", False), "mia": ("mia-pass", False)}


def token(user: str, password: str, salt: str = "abc123") -> dict:
    return {"u": user, "t": hashlib.md5((password + salt).encode()).hexdigest(), "s": salt}


class FakeMusicServer:
    """Answers ping and getUser like Navidrome: the token must match; getUser tells whether the caller is an administrator."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str) -> dict:
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.calls.append(parsed.path.rsplit("/", 1)[-1].removesuffix(".view"))
        user = q.get("u", "")
        entry = PEOPLE.get(user)
        if not entry or q.get("t") != hashlib.md5((entry[0] + q.get("s", "")).encode()).hexdigest():
            return {"status": "failed", "error": {"code": 40, "message": "Wrong username or password"}}
        if parsed.path.endswith("/ping.view") or parsed.path.endswith("/ping"):
            return {"status": "ok"}
        if "getUser" in parsed.path:
            return {"status": "ok", "user": {"username": user, "adminRole": entry[1]}}
        return {"status": "failed", "error": {"code": 0, "message": "not found"}}


class Provisioner:
    def __init__(self) -> None:
        self.created: list[str] = []

    def add_person(self, username: str, password: str) -> None:
        if username in PEOPLE or username in self.created:
            raise ProvisionError("that name is taken")
        self.created.append(username)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> float:
        return self.now


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.clock = Clock()
        self.music = FakeMusicServer()
        self.prov = Provisioner()
        self.invites = Invites(root / "people.db", provisioner=self.prov, clock=self.clock)
        self.addCleanup(self.invites.close)
        self.activity = Activity(root / "sharing.json", clock=self.clock)
        self.api = self.make_api()

    def make_api(self, owners: frozenset[str] = frozenset()) -> Api:
        return Api(
            invites=self.invites, activity=self.activity,
            navidrome=Navidrome("http://music", http=self.music, clock=self.clock),
            settings=Settings(public_url="https://music.example.ts.net", server_name="Home music", owners=owners),
            clock=self.clock)

    # ------------------------------------------------------------ helpers
    def call(self, method: str, path: str, *, auth: tuple[str, str] | None = None, body: object | None = None,
             ip: str = "198.51.100.7", raw: bytes | None = None):
        query = urlencode(token(*auth)) if auth else ""
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        return self.api.handle(method, path + ("?" + query if query else ""), {}, data, ip)

    def json_of(self, response) -> dict:
        return json.loads(response.body)

    def admin_invite(self) -> dict:
        r = self.call("POST", "/api/invites", auth=("owner", "owner-pass"))
        self.assertEqual(r.status, 201, r.body)
        return self.json_of(r)

    # ------------------------------------------------------------ who is asking
    def test_a_wrong_password_is_refused(self) -> None:
        self.assertEqual(self.call("GET", "/api/me", auth=("sara", "nope")).status, 401)

    def test_no_credentials_is_refused(self) -> None:
        self.assertEqual(self.call("GET", "/api/me").status, 401)

    def test_me_says_who_and_whether_admin(self) -> None:
        self.assertEqual(self.json_of(self.call("GET", "/api/me", auth=("owner", "owner-pass"))),
                         {"user": "owner", "admin": True, "role": "owner", "canInvite": True, "canManage": True, "sharing": False,
                          "mustChangePassword": False})
        sara = self.json_of(self.call("GET", "/api/me", auth=("sara", "sara-pass")))
        self.assertEqual((sara["admin"], sara["canInvite"]), (False, False))

    def test_a_good_token_is_remembered_so_polling_does_not_hammer_the_music_server(self) -> None:
        for _ in range(5):
            self.call("GET", "/api/me", auth=("sara", "sara-pass"))
        self.assertEqual(self.music.calls.count("ping"), 1)

    def test_headers_work_like_the_query(self) -> None:
        t = token("sara", "sara-pass")
        r = self.api.handle("GET", "/api/me", {"X-Encore-User": t["u"], "X-Encore-Token": t["t"], "X-Encore-Salt": t["s"]}, b"", "198.51.100.7")
        self.assertEqual(r.status, 200)

    def test_the_prefix_is_optional(self) -> None:
        # Whether the front door strips /people or keeps it is not known until the real Funnel (docs/35 section 5).
        a = self.call("GET", "/api/me", auth=("sara", "sara-pass"))
        b = self.call("GET", "/people/api/me", auth=("sara", "sara-pass"))
        self.assertEqual((a.status, a.body), (b.status, b.body))

    def test_info_tells_the_app_what_this_is_without_a_login(self) -> None:
        # The app asks every address it knows "are you the people service?" before it sends anybody's token anywhere
        # (the same question encore-fetch answers on /api/info).
        r = self.call("GET", "/api/info")
        self.assertEqual(r.status, 200)
        self.assertEqual(self.json_of(r), {"service": "encore-people", "version": 1, "features": ["invites", "activity", "manage"],
                                                "inviteLinks": True})
        self.assertEqual(self.music.calls, [], "answering must not need the music server")
        self.assertEqual(self.call("GET", "/people/api/info").body, r.body, "with or without the prefix")
        self.assertEqual(self.call("POST", "/api/info").status, 405)

    # ------------------------------------------------------------ invites: admin only
    def test_only_an_administrator_can_make_an_invite(self) -> None:
        self.assertEqual(self.call("POST", "/api/invites", auth=("sara", "sara-pass")).status, 403)
        self.assertEqual(self.call("POST", "/api/invites").status, 401)
        made = self.admin_invite()
        self.assertTrue(made["url"].startswith("https://music.example.ts.net/people/join/"))
        self.assertEqual(made["expiresAt"], NOW + 7 * 24 * 3600)

    def test_without_a_public_address_there_is_no_invite_to_hand_out(self) -> None:
        bare = Api(invites=self.invites, activity=self.activity,
                   navidrome=Navidrome("http://music", http=self.music, clock=self.clock),
                   settings=Settings(public_url="", server_name="Home music"), clock=self.clock)
        t = token("owner", "owner-pass")
        r = bare.handle("POST", "/api/invites?" + urlencode(t), {}, b"", "198.51.100.7")
        self.assertEqual(r.status, 409)
        self.assertIn("remote access", json.loads(r.body)["error"].lower())
        self.assertEqual(self.invites.list(), [], "no invitation may be made that nobody can open")

    def test_the_link_carries_the_public_address_only(self) -> None:
        made = self.admin_invite()
        self.assertNotIn("192.168", made["url"])
        self.assertNotIn("localhost", made["url"])

    def test_a_person_the_operator_named_can_invite_without_being_an_administrator(self) -> None:
        # On the owner's server the daily account is an ordinary one (an administrator sees every library), so the person who
        # runs the server names who may invite (PEOPLE_INVITERS) instead of being made an administrator.
        self.api = self.make_api(owners=frozenset({"sara"}))
        sara = ("sara", "sara-pass")

        me = self.json_of(self.call("GET", "/api/me", auth=sara))
        self.assertEqual((me["admin"], me["canInvite"]), (False, True))
        made = self.call("POST", "/api/invites", auth=sara)
        self.assertEqual(made.status, 201, made.body)
        listing = self.call("GET", "/api/invites", auth=sara)
        self.assertEqual(listing.status, 200)
        self.assertEqual(self.json_of(listing)["invites"][0]["inviter"], "sara")
        invite_id = self.json_of(made)["id"]
        self.assertEqual(self.call("DELETE", f"/api/invites/{invite_id}", auth=sara).status, 204)

    def test_everyone_not_named_still_cannot_invite(self) -> None:
        self.api = self.make_api(owners=frozenset({"sara"}))
        mia = ("mia", "mia-pass")

        self.assertEqual(self.json_of(self.call("GET", "/api/me", auth=mia))["canInvite"], False)
        self.assertEqual(self.call("POST", "/api/invites", auth=mia).status, 403)
        self.assertEqual(self.call("GET", "/api/invites", auth=mia).status, 403)

    def test_the_administrator_can_still_invite_when_others_are_named(self) -> None:
        self.api = self.make_api(owners=frozenset({"sara"}))

        self.assertEqual(self.call("POST", "/api/invites", auth=("owner", "owner-pass")).status, 201)

    def test_listing_and_revoking_are_admin_only_and_never_show_a_code(self) -> None:
        made = self.admin_invite()
        self.assertEqual(self.call("GET", "/api/invites", auth=("sara", "sara-pass")).status, 403)
        listing = self.json_of(self.call("GET", "/api/invites", auth=("owner", "owner-pass")))
        self.assertEqual(listing["invites"][0]["state"], "open")
        code = made["url"].rsplit("/", 1)[-1]
        self.assertNotIn(code, json.dumps(listing))
        self.assertEqual(self.call("DELETE", f"/api/invites/{made['id']}", auth=("sara", "sara-pass")).status, 403)
        self.assertEqual(self.call("DELETE", f"/api/invites/{made['id']}", auth=("owner", "owner-pass")).status, 204)
        self.assertEqual(self.call("GET", f"/join/{code}/info").status, 404)

    # ------------------------------------------------------------ the friend's side: public
    def test_the_landing_page_for_a_good_code(self) -> None:
        code = self.admin_invite()["url"].rsplit("/", 1)[-1]
        r = self.call("GET", f"/join/{code}")
        self.assertEqual(r.status, 200)
        self.assertIn("text/html", r.headers["Content-Type"])
        page = r.body.decode()
        self.assertIn("Home music", page)
        self.assertIn("owner", page)  # who invited
        self.assertIn("https://music.example.ts.net", page)  # what to type into the app
        self.assertNotIn("<script src=", page, "no outside scripts")
        self.assertIn("no-store", r.headers.get("Cache-Control", ""))

    def test_the_finished_page_offers_a_setup_link_the_app_understands(self) -> None:
        # After the account is made the friend should paste ONE link into the app ("Got a setup link? Paste it"),
        # not copy an address by hand: the address, the server's name and the new account's name, and no password.
        code = self.admin_invite()["url"].rsplit("/", 1)[-1]
        page = self.call("GET", f"/join/{code}").body.decode()

        self.assertIn("Copy setup link", page)
        self.assertIn("Got a setup link? Paste it", page, "the words of the app's own button")
        script = page[page.index("<script>"):]
        link_line = next(line for line in script.splitlines() if "encore://connect" in line)
        self.assertIn("server=", link_line)
        self.assertIn("&name=", link_line)
        self.assertIn("&user=", link_line)
        self.assertIn("d.username", link_line, "the name the service made, from its answer")
        self.assertNotIn("password", link_line.lower(), "a link is never a place for a password")
        self.assertNotIn(".value", link_line, "built from the answer, not from what was typed")
        self.assertIn("overflow-wrap:anywhere", page, "when the browser will not copy, the long link is shown and must wrap, not run off the screen")

    def test_a_hostile_server_name_cannot_break_out_of_the_page(self) -> None:
        # The name is set by whoever runs the server (SERVER_NAME), but it ends up in HTML and in a script: neither may be breakable.
        evil = 'x</script><script>alert(1)</script><b onmouseover="1">'
        self.api = Api(
            invites=self.invites, activity=self.activity,
            navidrome=Navidrome("http://music", http=self.music, clock=self.clock),
            settings=Settings(public_url="https://music.example.ts.net", server_name=evil), clock=self.clock)
        code = self.admin_invite()["url"].rsplit("/", 1)[-1]

        page = self.call("GET", f"/join/{code}").body.decode()

        self.assertEqual(page.count("<script>"), 1, "no second script element")
        self.assertEqual(page.count("</script>"), 1, "the one script is not closed early")
        self.assertNotIn("<b onmouseover", page)

    def test_a_wrong_expired_and_revoked_code_all_get_the_same_answer(self) -> None:
        good = self.admin_invite()
        code = good["url"].rsplit("/", 1)[-1]
        revoked = self.admin_invite()
        self.call("DELETE", f"/api/invites/{revoked['id']}", auth=("owner", "owner-pass"))
        rcode = revoked["url"].rsplit("/", 1)[-1]
        answers = {self.call("GET", f"/join/{c}").body for c in ("nonsense-code-0000000000", rcode)}
        self.clock.now += 8 * 24 * 3600
        answers.add(self.call("GET", f"/join/{code}").body)
        self.assertEqual(len(answers), 1, "the three cases must be indistinguishable")
        self.assertEqual(self.call("GET", f"/join/{code}").status, 404)

    def test_redeeming_makes_the_account_and_a_second_try_fails(self) -> None:
        code = self.admin_invite()["url"].rsplit("/", 1)[-1]
        r = self.call("POST", f"/join/{code}/redeem", body={"username": "ben", "password": "ben-long-password"})
        self.assertEqual(r.status, 201, r.body)
        self.assertEqual(self.json_of(r)["username"], "ben")
        self.assertEqual(self.prov.created, ["ben"])
        again = self.call("POST", f"/join/{code}/redeem", body={"username": "tom", "password": "tom-long-password"})
        self.assertEqual(again.status, 404)

    def test_a_taken_name_or_a_short_password_is_explained_and_keeps_the_invitation(self) -> None:
        code = self.admin_invite()["url"].rsplit("/", 1)[-1]
        taken = self.call("POST", f"/join/{code}/redeem", body={"username": "sara", "password": "long enough password"})
        self.assertEqual(taken.status, 400)
        self.assertIn("taken", self.json_of(taken)["error"])
        short = self.call("POST", f"/join/{code}/redeem", body={"username": "ben", "password": "short"})
        self.assertEqual(short.status, 400)
        self.assertEqual(self.call("GET", f"/join/{code}/info").status, 200, "a mistake must not burn the invitation")

    def test_garbage_bodies_are_refused_cleanly(self) -> None:
        code = self.admin_invite()["url"].rsplit("/", 1)[-1]
        for raw in (b"", b"not json", b"[1,2]", b'{"username": 5, "password": []}', b"x" * 20000):
            r = self.call("POST", f"/join/{code}/redeem", raw=raw)
            self.assertIn(r.status, (400, 413), raw[:20])

    def test_guessing_codes_is_rate_limited_per_address(self) -> None:
        statuses = [self.call("GET", f"/join/guess-{i:020d}", ip="203.0.113.50").status for i in range(40)]
        self.assertIn(429, statuses)
        self.assertEqual(self.call("GET", "/join/guess-other", ip="203.0.113.51").status, 404, "another address is unaffected")

    # ------------------------------------------------------------ activity
    def test_activity_is_off_until_the_person_opts_in(self) -> None:
        song = {"title": "Dogs", "artist": "Pink Floyd", "album": "Animals", "state": "playing"}
        self.assertEqual(self.call("PUT", "/api/activity", auth=("sara", "sara-pass"), body=song).status, 204)
        self.assertEqual(self.json_of(self.call("GET", "/api/activity", auth=("owner", "owner-pass")))["friends"], [])
        self.assertEqual(self.call("PUT", "/api/activity/sharing", auth=("sara", "sara-pass"), body={"on": True}).status, 204)
        self.call("PUT", "/api/activity", auth=("sara", "sara-pass"), body=song)
        friends = self.json_of(self.call("GET", "/api/activity", auth=("owner", "owner-pass")))["friends"]
        self.assertEqual([(f["user"], f["title"]) for f in friends], [("sara", "Dogs")])
        self.assertEqual(friends[0]["since"], NOW)
        self.assertEqual(self.json_of(self.call("GET", "/api/activity", auth=("sara", "sara-pass")))["friends"], [])

    def test_private_listening_clears_the_entry(self) -> None:
        self.call("PUT", "/api/activity/sharing", auth=("sara", "sara-pass"), body={"on": True})
        self.call("PUT", "/api/activity", auth=("sara", "sara-pass"), body={"title": "Dogs", "state": "playing"})
        self.assertEqual(self.call("DELETE", "/api/activity", auth=("sara", "sara-pass")).status, 204)
        self.assertEqual(self.json_of(self.call("GET", "/api/activity", auth=("owner", "owner-pass")))["friends"], [])

    def test_activity_needs_a_valid_login(self) -> None:
        for method, path in (("GET", "/api/activity"), ("PUT", "/api/activity"), ("DELETE", "/api/activity"),
                             ("PUT", "/api/activity/sharing")):
            self.assertEqual(self.call(method, path, body={"on": True}).status, 401, (method, path))

    # ------------------------------------------------------------ everything else
    def test_unknown_paths_and_methods(self) -> None:
        self.assertEqual(self.call("GET", "/nothing-here").status, 404)
        self.assertEqual(self.call("DELETE", "/api/me", auth=("sara", "sara-pass")).status, 405)

    def test_no_response_ever_contains_the_admin_login(self) -> None:
        for r in (self.call("GET", "/api/me", auth=("owner", "owner-pass")), self.call("POST", "/api/invites", auth=("owner", "owner-pass")),
                  self.call("GET", "/api/invites", auth=("owner", "owner-pass"))):
            self.assertNotIn(b"owner-pass", r.body)


if __name__ == "__main__":
    unittest.main()
