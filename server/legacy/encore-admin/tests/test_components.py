"""The Parts page (docs/49 P3): how each part is doing, its recent messages with secrets hidden, and a restart that can reach only the stack's own parts."""
import struct
import unittest

from encore_admin import redact
from encore_admin.docker_api import STACK, Docker, DockerError, _unframe

from tests.fakes import FakeDocker
from tests.test_site import SiteTestBase


def frame(kind: int, text: str) -> bytes:
    body = text.encode()
    return bytes([kind, 0, 0, 0]) + struct.pack(">I", len(body)) + body


class RedactTest(unittest.TestCase):
    def test_keys_tokens_and_passwords_are_hidden_wherever_they_appear(self):
        cases = {
            "GET /rest/ping.view?u=sam&t=0123456789abcdef0123456789abcdef&s=abc123 200": "t=***",
            "X-Api-Key: 0123456789abcdef0123456789abcdef": "***",
            "login with password=hunter2 failed": "password=***",
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abcdef.ghijk": "***",
            "joined with tskey-auth-kAbCdEf123456-abcdefghijklmnop": "***",
            '{"apikey": "0123456789abcdef0123456789abcdef"}': "***",
            "slskd api_key = 0123456789abcdef0123456789abcdef": "api_key = ***",
        }
        for original, expected in cases.items():
            clean = redact.line(original)
            self.assertIn(expected, clean, original)
            for secret in ("0123456789abcdef", "hunter2", "eyJhbGci", "kAbCdEf", "abc123"):
                self.assertNotIn(secret, clean, original)

    def test_ordinary_lines_are_left_alone(self):
        for text in ("2026-10-18 22:15:05 INFO encore_recs: recommendations service on 8705", "Importing 23 tracks from /music/.encore/downloads/Album",
                     "Lidarr now files into /music/.encore/pool"):
            self.assertEqual(redact.line(text), text)


class FramesTest(unittest.TestCase):
    def test_framed_messages_become_text(self):
        self.assertEqual(_unframe(frame(1, "hello\n") + frame(2, "oops\n")), b"hello\noops\n")

    def test_a_container_with_a_terminal_sends_plain_text(self):
        self.assertEqual(_unframe(b"just text\nmore\n"), b"just text\nmore\n")

    def test_a_cut_off_frame_is_not_trusted_as_frames(self):
        cut = frame(1, "hello")[:-2]
        self.assertEqual(_unframe(cut), cut)


class TheDockerClientTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDocker()
        self.docker = Docker(self.fake, self.fake, "img:1")

    def test_details_say_how_each_part_is_doing_and_what_it_runs(self):
        found = self.docker.details()
        self.assertEqual(found["navidrome"]["state"], "running")
        self.assertTrue(found["navidrome"]["image"])
        self.assertNotIn("some-other-app", found)

    def test_only_parts_of_the_stack_can_be_restarted_and_never_the_website_itself(self):
        self.docker.restart("encore-fetch")
        self.assertEqual(self.fake.calls[-1][:2], ("POST", "/containers/encore-fetch/restart?t=10"))
        for refused in ("encore-admin", "some-other-app", "../x", "encore-signin-a1b2c3d4", "", "navidrome; rm -rf"):
            with self.assertRaises(DockerError, msg=refused):
                self.docker.restart(refused)
        self.assertEqual(len([c for c in self.fake.calls if "restart" in c[1]]), 1, "nothing else reached Docker")

    def test_docker_refusing_a_restart_is_an_error_not_silence(self):
        self.fake.restart_status = 500
        with self.assertRaises(DockerError):
            self.docker.restart("encore-fetch")

    def test_messages_are_the_last_lines_with_secrets_hidden(self):
        self.fake.log_text["encore-fetch"] = "".join(f"line {n}\n" for n in range(300)) + "GET /x?t=0123456789abcdef0123456789abcdef&s=zz\n"
        lines = self.docker.logs("encore-fetch", tail=50)
        self.assertEqual(len(lines), 50)
        self.assertEqual(lines[0], "line 251")
        self.assertIn("t=***", lines[-1])
        self.assertNotIn("0123456789abcdef", "\n".join(lines))

    def test_messages_of_something_that_is_not_a_part_of_the_stack_are_not_available(self):
        for refused in ("some-other-app", "../etc", ""):
            with self.assertRaises(DockerError, msg=refused):
                self.docker.logs(refused)

    def test_the_stack_list_covers_the_quality_and_suggestions_parts(self):
        for name in ("encore-quality", "encore-lidarr", "encore-slskd", "encore-soularr", "encore-recs"):
            self.assertIn(name, STACK)


class ThePartsPageTest(SiteTestBase):
    def setUp(self):
        super().setUp()
        self.key = self.sign_in()

    def test_every_part_that_exists_is_listed_in_plain_words_and_the_rest_are_not(self):
        del self.docker.stack_containers["encore-hub"]
        r, data = self.call("GET", "/admin/api/components", cookie=self.key)
        self.assertEqual(r.status, 200)
        names = {p["container"]: p for p in data["parts"]}
        self.assertEqual(names["navidrome"]["name"], "Music server")
        self.assertEqual(names["navidrome"]["state"], "running")
        self.assertNotIn("encore-hub", names)
        self.assertFalse(names["encore-admin"]["canRestart"])
        self.assertTrue(names["encore-fetch"]["canRestart"])

    def test_an_image_made_on_this_machine_is_not_shown_as_a_hash(self):
        self.docker.stack_containers["encore-people"] = ("running", "Up 3 hours")
        from encore_admin.components import describe
        shown = describe({"encore-people": {"state": "running", "image": "sha256:7f7723786eb6d4dc"}, "encore-fetch": {"state": "running", "image": "encore-server-encore-fetch"},
                          "navidrome": {"state": "running", "image": "deluan/navidrome:0.64.2"}})
        self.assertEqual({p["container"]: p["image"] for p in shown}, {"navidrome": "deluan/navidrome:0.64.2", "encore-people": "built on this machine",
                                                                       "encore-fetch": "built on this machine"})

    def test_a_part_that_is_not_well_says_so(self):
        self.docker.stack_containers["encore-fetch"] = ("restarting", "Restarting (1) 3 seconds ago")
        data = self.call("GET", "/admin/api/components", cookie=self.key)[1]
        part = next(p for p in data["parts"] if p["container"] == "encore-fetch")
        self.assertEqual((part["state"], part["note"]), ("restarting", "Keeps stopping and starting again."))

    def test_when_docker_cannot_be_asked_the_page_says_so_instead_of_listing_nothing_as_if_all_were_off(self):
        self.docker.stack_containers = None
        r, data = self.call("GET", "/admin/api/components", cookie=self.key)
        self.assertEqual((r.status, data), (200, {"dockerOk": False, "parts": []}))

    def test_a_part_is_restarted_by_the_owner(self):
        r, _ = self.call("POST", "/admin/api/components/encore-fetch/restart", {}, cookie=self.key)
        self.assertEqual(r.status, 204)
        self.assertIn(("POST", "/containers/encore-fetch/restart?t=10"), [(m, p) for m, p, _ in self.docker.calls])

    def test_the_website_cannot_restart_itself_and_says_why(self):
        r, data = self.call("POST", "/admin/api/components/encore-admin/restart", {}, cookie=self.key)
        self.assertEqual((r.status, data["error"]), (400, "cannot_restart"))
        self.assertIn("cannot restart itself", data["message"])

    def test_only_known_parts_can_be_named_at_all(self):
        for name in ("evil", "..%2f..", "encore-signin-a1b2c3d4"):
            self.assertEqual(self.call("POST", f"/admin/api/components/{name}/restart", {}, cookie=self.key)[0].status, 404, name)
            self.assertEqual(self.call("GET", f"/admin/api/components/{name}/logs", cookie=self.key)[0].status, 404, name)

    def test_the_recent_messages_of_a_part_come_without_secrets(self):
        self.docker.log_text["navidrome"] = "started\nGET /rest/ping.view?u=sam&t=0123456789abcdef0123456789abcdef&s=zz\n"
        r, data = self.call("GET", "/admin/api/components/navidrome/logs", cookie=self.key)
        self.assertEqual(r.status, 200)
        self.assertEqual(data["lines"][0], "started")
        self.assertNotIn("0123456789abcdef", str(data))

    def test_docker_refusing_is_a_sentence(self):
        self.docker.restart_status = 500
        r, data = self.call("POST", "/admin/api/components/encore-fetch/restart", {}, cookie=self.key)
        self.assertEqual((r.status, data["error"]), (502, "docker"))
        self.assertIn("could not be done", data["message"])

    def test_the_page_needs_a_signed_in_owner_and_the_right_methods(self):
        self.assertEqual(self.call("GET", "/admin/api/components")[0].status, 401)
        self.assertEqual(self.call("POST", "/admin/api/components/encore-fetch/restart", {})[0].status, 401)
        self.assertEqual(self.call("POST", "/admin/api/components", {}, cookie=self.key)[0].status, 405)
        self.assertEqual(self.call("GET", "/admin/api/components/encore-fetch/restart", cookie=self.key)[0].status, 405)
        self.assertEqual(self.call("POST", "/admin/api/components/encore-fetch/logs", {}, cookie=self.key)[0].status, 405)


if __name__ == "__main__":
    unittest.main()
