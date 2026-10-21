"""The people service's hands on the music server (docs/48): adding a person on either kind of server, a new password, the list with times.
A fake account tool stands in for `encore_user` and for Navidrome's admin API."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from encore_people.invites import ProvisionError
from encore_people.provision import NavidromeProvisioner


class ToolError(Exception):
    pass


class FakeAdmin:
    def __init__(self, libraries, users):
        self.libs = libraries
        self.user_list = users
        self.calls = []

    def libraries(self):
        return self.libs

    def users(self):
        return self.user_list

    def call(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "POST" and path == "/api/user":
            made = {"id": "id-" + payload["userName"], **payload}
            self.user_list.append({"id": made["id"], "userName": payload["userName"]})
            return made
        return {}


class FakeTool:
    ToolError = ToolError

    def __init__(self, libraries, users):
        self.admin = FakeAdmin(libraries, users)
        self.logins = 0
        self.login_error = None
        self.private_calls = []
        self.private_error = None

    def Admin(self, base, user, password):  # noqa: N802 - the real tool's class name
        self.logins += 1
        if self.login_error:
            raise ToolError(self.login_error)
        return self.admin

    @staticmethod
    def is_shared(path):
        return path.rstrip("/").endswith("/_shared")

    def add_person(self, admin, name, **kw):
        self.private_calls.append((name, kw))
        if kw.get("create_dir"):
            (Path(kw["create_dir"]) / name).mkdir(exist_ok=True)
        if self.private_error:
            raise ToolError(self.private_error)
        return {"libraries": [name, "_shared"]}

    def remove_person(self, admin, name, delete_library=False):
        pass


SHARED_LAYOUT = [{"id": "L1", "path": "/music", "name": "Music"}]
PRIVATE_LAYOUT = [{"id": "L1", "path": "/music/_shared", "name": "shared"}, {"id": "L2", "path": "/music/dana", "name": "dana"}]
USERS = [{"id": "u1", "userName": "dana", "name": "Dana", "email": "", "isAdmin": True,
          "lastAccessAt": "2026-10-18T18:05:52.502475328Z", "createdAt": "2026-10-01T10:00:00Z"}]


class ProvisionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.music = Path(self._tmp.name)

    def make(self, libraries, users=None, clock=None):
        self.tool = FakeTool(libraries, [dict(u) for u in (USERS if users is None else users)])
        kw = {"clock": clock} if clock else {}
        return NavidromeProvisioner("http://nd", "owner", "pw", self.music, account_tool=self.tool, **kw)

    def test_on_a_server_where_everybody_shares_one_library_a_person_is_given_that_library(self):
        provisioner = self.make(SHARED_LAYOUT)
        provisioner.add_person("tom", "temporary-pass")
        calls = self.tool.admin.calls
        self.assertEqual(calls[0][:2], ("POST", "/api/user"))
        self.assertEqual((calls[0][2]["userName"], calls[0][2]["password"], calls[0][2]["isAdmin"]), ("tom", "temporary-pass", False))
        self.assertEqual(calls[1], ("PUT", "/api/user/id-tom/library", {"libraryIds": ["L1"]}))
        self.assertEqual(self.tool.private_calls, [], "no private library is made on such a server")
        self.assertEqual(list(self.music.iterdir()), [], "and no folder: a person named like an artist is fine")

    def test_on_a_server_with_private_libraries_the_account_tool_makes_the_persons_own(self):
        provisioner = self.make(PRIVATE_LAYOUT)
        provisioner.add_person("tom", "temporary-pass")
        self.assertEqual(self.tool.private_calls[0][0], "tom")
        self.assertEqual(self.tool.admin.calls, [], "the tool did everything")
        self.assertEqual(provisioner.layout(), "private")

    def test_when_the_tool_refuses_the_person_is_told_in_a_sentence_and_no_folder_is_left_behind(self):
        provisioner = self.make(PRIVATE_LAYOUT)
        self.tool.private_error = "/music/tom and the existing library /music contain each other (secret path details)"
        with self.assertRaises(ProvisionError) as caught:
            provisioner.add_person("tom", "temporary-pass")
        self.assertNotIn("secret", str(caught.exception))
        self.assertIn("could not be set up", str(caught.exception))
        self.assertFalse((self.music / "tom").exists())

    def test_a_name_that_is_taken_is_refused_on_either_kind_of_server(self):
        for libraries in (SHARED_LAYOUT, PRIVATE_LAYOUT):
            provisioner = self.make(libraries)
            with self.assertRaises(ProvisionError) as caught:
                provisioner.add_person("dana", "temporary-pass")
            self.assertEqual(str(caught.exception), "That name is already taken. Choose another.")

    def test_a_new_password_is_set_through_the_music_servers_own_user_api(self):
        provisioner = self.make(SHARED_LAYOUT)
        provisioner.set_password("DANA", "a new password")
        method, path, payload = self.tool.admin.calls[0]
        self.assertEqual((method, path), ("PUT", "/api/user/u1"))
        self.assertEqual(payload, {"userName": "dana", "name": "Dana", "email": "", "isAdmin": True, "password": "a new password"})
        with self.assertRaises(ProvisionError):
            provisioner.set_password("nobody", "x")

    def test_the_list_carries_when_each_person_last_came_in_seconds(self):
        listing = self.make(SHARED_LAYOUT).listing()
        self.assertEqual(listing[0]["name"], "dana")
        self.assertTrue(listing[0]["admin"])
        self.assertAlmostEqual(listing[0]["lastAccess"], datetime(2026, 10, 18, 18, 5, 52, 502475, tzinfo=timezone.utc).timestamp(), places=3)
        self.assertEqual(listing[0]["createdAt"], datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp())

    def test_a_time_that_is_missing_or_odd_is_none(self):
        users = [{"id": "u2", "userName": "mia", "lastAccessAt": None, "createdAt": "not a time"}]
        listing = self.make(SHARED_LAYOUT, users).listing()
        self.assertEqual((listing[0]["lastAccess"], listing[0]["createdAt"]), (None, None))

    def test_one_sign_in_to_the_music_server_serves_many_operations(self):
        # the music server answers a flood of sign-ins with HTTP 429: it must be asked once, not once per click
        provisioner = self.make(SHARED_LAYOUT)
        provisioner.listing()
        provisioner.listing()
        provisioner.layout()
        provisioner.set_password("dana", "a new password")
        self.assertEqual(self.tool.logins, 1)

    def test_the_sign_in_is_renewed_when_it_runs_out_and_when_the_music_server_drops_it(self):
        now = [0.0]
        provisioner = self.make(SHARED_LAYOUT, clock=lambda: now[0])
        provisioner.listing()
        now[0] += provisioner.SESSION_S + 1
        provisioner.listing()
        self.assertEqual(self.tool.logins, 2)
        calls = []
        real = self.tool.admin.users

        def dropped_once():
            calls.append(1)
            if len(calls) == 1:
                raise ToolError("GET /api/user -> HTTP 401: nope")
            return real()

        self.tool.admin.users = dropped_once
        self.assertEqual(provisioner.listing()[0]["name"], "dana")
        self.assertEqual(self.tool.logins, 3, "one new sign-in, then it worked")

    def test_a_music_server_that_will_not_let_the_service_in_is_try_again_not_a_crash(self):
        from encore_people.people import DirectoryUnavailable
        provisioner = self.make(SHARED_LAYOUT)
        self.tool.login_error = "Could not sign in as 'owner' (HTTP 429)"
        with self.assertRaises(DirectoryUnavailable):
            provisioner.listing()

    def test_the_layout_is_told_to_the_owner(self):
        self.assertEqual(self.make(SHARED_LAYOUT).layout(), "shared")
        self.assertEqual(self.make(PRIVATE_LAYOUT).layout(), "private")


if __name__ == "__main__":
    unittest.main()
