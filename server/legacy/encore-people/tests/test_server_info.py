"""One answer to "what can this server do?" (docs/45c item 1, ADR-105): the app asks once, without signing in, and shows only what
the server has. Each part of the stack is asked in its own words and the answer is put together here."""
import unittest
from pathlib import Path

from encore_people.activity import Activity
from encore_people.navidrome import Navidrome
from encore_people.parts import Parts
from encore_people.people import Roles
from encore_people.server import Api, Settings

from tests.test_manage import ManageTest


class FakeStack:
    """What the other parts answer to `GET <their url>`; a part that is not listed does not answer at all."""

    def __init__(self):
        self.answers = {
            "http://nd" + Parts.MUSIC_PATH: {"subsonic-response": {"status": "failed", "type": "navidrome", "serverVersion": "0.64.2 (abc)",
                                                                   "error": {"code": 10, "message": "missing parameter: 'u'"}}},
            "http://fetch/api/info": {"service": "encore-fetch", "version": 1, "build": "0.1.0",
                                      "features": ["play-now", "prepare", "playlist", "import", "youtube-login", "profile"],
                                      "formats": ["opus", "m4a"], "youtubeSignedIn": True, "secret": "never shown"},
            "http://hub/api/info": {"service": "encore-hub", "version": 1, "features": ["jam"]},
            "http://quality/api/info": {"service": "encore-quality", "version": 1, "features": ["quality-requests", "upgrade-map"]},
            "http://recs/api/info": {"service": "encore-recs", "version": 1, "features": ["recs-home", "recs-pool", "recs-hide"]},
        }
        self.asked: list[str] = []

    def __call__(self, url, timeout):
        self.asked.append(url)
        return self.answers.get(url)


class OneAnswerTest(ManageTest):
    def setUp(self):
        super().setUp()
        self.stack = FakeStack()
        self.api = self.make_api()

    def make_api(self, public_url="https://music.example.ts.net"):
        stack = getattr(self, "stack", None) or FakeStack()
        self.parts = Parts(music_url="http://nd", fetch_url="http://fetch", hub_url="http://hub", quality_url="http://quality", recs_url="http://recs",
                           get=stack, clock=self.clock)
        return Api(invites=self.invites, activity=Activity(Path(self._tmp.name) / "sharing.json", clock=self.clock),
                   navidrome=Navidrome("http://music", http=self.music, clock=self.clock),
                   settings=Settings(public_url=public_url, server_name="Home music"), roles=Roles(), directory=self.directory,
                   standing=self.standing, clock=self.clock, parts=self.parts)

    def test_the_app_gets_one_list_for_the_whole_server_without_signing_in(self):
        r = self.call("GET", "/api/server")
        self.assertEqual(r.status, 200)
        answer = self.j(r)
        self.assertEqual(answer["service"], "encore")
        self.assertEqual(answer["name"], "Home music")
        self.assertEqual(answer["address"], "https://music.example.ts.net")
        self.assertEqual(answer["features"], sorted(answer["features"]), "a list in one order, so a change is easy to see")
        for feature in ("music", "play-now", "playlist", "import", "youtube-login", "profile", "jam", "invites", "invite-links",
                        "manage", "forgot-password", "activity", "quality-requests", "upgrade-map", "recs-home", "recs-pool", "recs-hide"):
            self.assertIn(feature, answer["features"])
        self.assertEqual(answer["parts"]["music"], {"up": True, "version": "0.64.2"})
        self.assertTrue(answer["parts"]["fetch"]["up"])
        self.assertTrue(answer["parts"]["fetch"]["youtubeSignedIn"])

    def test_a_part_that_is_not_answering_takes_its_buttons_away_instead_of_leading_to_not_available(self):
        del self.stack.answers["http://hub/api/info"]
        del self.stack.answers["http://fetch/api/info"]
        answer = self.j(self.call("GET", "/api/server"))
        self.assertEqual(answer["parts"]["hub"], {"up": False})
        self.assertEqual(answer["parts"]["fetch"], {"up": False})
        for feature in ("jam", "play-now", "import", "youtube-login"):
            self.assertNotIn(feature, answer["features"])
        self.assertIn("music", answer["features"], "the rest is still there")

    def test_the_quality_and_suggestion_services_are_part_of_the_one_answer_and_hidden_when_they_are_not_there(self):
        del self.stack.answers["http://quality/api/info"]
        self.clock.now += Parts.FRESH_S + 1
        answer = self.j(self.call("GET", "/api/server"))
        self.assertEqual(answer["parts"]["quality"], {"up": False})
        self.assertNotIn("quality-requests", answer["features"])
        self.assertIn("recs-home", answer["features"])

    def test_a_music_server_that_is_down_is_said(self):
        del self.stack.answers["http://nd" + Parts.MUSIC_PATH]
        answer = self.j(self.call("GET", "/api/server"))
        self.assertEqual(answer["parts"]["music"], {"up": False})
        self.assertNotIn("music", answer["features"])

    def test_nothing_secret_or_private_is_in_the_answer(self):
        text = self.call("GET", "/api/server").body.decode()
        self.assertNotIn("never shown", text)
        self.assertNotIn("token", text.lower())
        self.assertNotIn("@", text, "no e-mail address of any account")

    def test_the_invitation_link_is_offered_only_when_the_server_has_an_address_to_put_in_it(self):
        self.api = self.make_api(public_url="")
        answer = self.j(self.call("GET", "/api/server"))
        self.assertIn("invites", answer["features"])
        self.assertNotIn("invite-links", answer["features"])

    def test_forgot_password_is_offered_only_when_the_server_can_change_passwords(self):
        self.api = Api(invites=self.invites, activity=Activity(Path(self._tmp.name) / "s2.json", clock=self.clock),
                       navidrome=Navidrome("http://music", http=self.music, clock=self.clock),
                       settings=Settings(public_url="https://x", server_name="Home music"), roles=Roles(), directory=None,
                       standing=self.standing, clock=self.clock, parts=self.parts)
        answer = self.j(self.call("GET", "/api/server"))
        self.assertNotIn("forgot-password", answer["features"])
        self.assertNotIn("manage", answer["features"])

    def test_a_crowd_of_phones_does_not_make_the_server_ask_its_parts_every_time(self):
        self.call("GET", "/api/server")
        asked = len(self.stack.asked)
        self.call("GET", "/api/server")
        self.call("GET", "/api/server")
        self.assertEqual(len(self.stack.asked), asked, "answered from what it just learned")
        self.clock.now += Parts.FRESH_S + 1
        self.call("GET", "/api/server")
        self.assertGreater(len(self.stack.asked), asked, "and asks again once that is old")

    def test_with_or_without_the_prefix_and_only_to_read(self):
        a, b = self.call("GET", "/api/server"), self.call("GET", "/people/api/server")
        self.assertEqual((a.status, a.body), (b.status, b.body))
        self.assertEqual(self.call("POST", "/api/server").status, 405)

    def test_a_server_without_a_part_configured_does_not_list_it_as_down(self):
        parts = Parts(music_url="http://nd", fetch_url=None, hub_url=None, get=self.stack, clock=self.clock)
        self.assertEqual(sorted(parts.look()), ["music"])


class AskingTest(unittest.TestCase):
    def test_a_slow_part_cannot_make_the_whole_answer_slow(self):
        import time
        started = time.monotonic()

        def slow(url, timeout):
            self.assertLessEqual(timeout, 3, "each part is given a short time")
            time.sleep(0.05)
            return {"features": ["x"]}

        looked = Parts(music_url="http://nd", fetch_url="http://fetch", hub_url="http://hub", get=slow).look()
        self.assertLess(time.monotonic() - started, 0.14, "the parts are asked together, not one after the other")
        self.assertTrue(looked["fetch"]["up"])

    def test_a_part_that_answers_nonsense_is_down_not_a_crash(self):
        for nonsense in ("text", 5, [1], {"features": "jam"}, {"features": [1, None, {"a": 1}]}):
            looked = Parts(music_url="http://nd", fetch_url="http://fetch", hub_url=None, get=lambda url, timeout, n=nonsense: n).look()
            self.assertIn("up", looked["fetch"], nonsense)

    def test_something_else_answering_where_the_music_server_should_is_not_the_music_server(self):
        for other in ({"status": "ok"}, {"subsonic-response": "x"}, {"subsonic-response": None}, "pong"):
            looked = Parts(music_url="http://nd", fetch_url=None, hub_url=None, get=lambda url, timeout, o=other: o).look()
            self.assertEqual(looked["music"], {"up": False}, other)

    def test_only_plain_short_feature_names_are_passed_on(self):
        answers = {"http://hub/api/info": {"features": ["jam", "x" * 100, "has space", "<script>", 7]}}
        looked = Parts(music_url="http://nd", fetch_url=None, hub_url="http://hub", get=lambda url, timeout: answers.get(url)).look()
        self.assertEqual(looked["hub"]["features"], ["jam"])


if __name__ == "__main__":
    unittest.main()
