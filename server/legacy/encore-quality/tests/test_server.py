"""The quality service as the app and the owner's website use it (docs/46 section 9)."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from encore_quality import store
from encore_quality.config import Config
from encore_quality.lidarr import Lidarr
from encore_quality.maintenance import Maintenance
from encore_quality.navidrome import Navidrome
from encore_quality.server import MAX_ACTIVE_PER_PERSON, Api
from encore_quality.slskd import Slskd
from encore_quality.store import Store

from tests.fakes import FakeLidarr, FakeNavidrome, FakeSlskdFull


def login(user, password, salt="s4lt"):
    return {"u": user, "t": hashlib.md5((password + salt).encode()).hexdigest(), "s": salt}


SAM, MIA, OWNER = login("sam", "sam-pw"), login("mia", "mia-pw"), login("owner", "owner-pw")


class ServerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.music = Path(self._tmp.name) / "music"
        self.music.mkdir()
        self.now = 1_760_000_000.0
        self.nd_fake = FakeNavidrome(self.music)
        self.nd_fake.passwords["sam"] = "sam-pw"
        self.song = self.nd_fake.add_song("Gojira/Magma/03 - Silvera.opus", title="Silvera", artist="Gojira", album="Magma", track=3)
        self.config = Config(music_dir=self.music, soularr_config=Path(self._tmp.name) / "soularr" / "config.ini", people_url="http://people",
                             min_free_gb=0.0, lidarr_api_key="lk", slskd_api_key="sk")
        self.store = Store(":memory:", lambda: self.now)
        self.addCleanup(self.store.close)
        self.lidarr_fake, self.slskd_fake = FakeLidarr(), FakeSlskdFull()
        self.people_owners = {"owner"}
        self.nd = Navidrome("http://nd", admin_user="owner", admin_password="owner-pw", transport=self.nd_fake, clock=lambda: self.now)
        self.maintenance = Maintenance(config=self.config, lidarr=Lidarr(self.lidarr_fake), slskd=Slskd(self.slskd_fake), navidrome=self.nd,
                                       store=self.store, clock=lambda: self.now)
        self.people_up = True
        self.api = Api(config=self.config, store=self.store, navidrome=self.nd, maintenance=self.maintenance, http_get=self.people,
                       clock=lambda: self.now)

    def people(self, url):
        if not self.people_up:
            return 0, {}
        user = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))["u"]
        return 200, {"canManage": user in self.people_owners}

    def call(self, method, path, who=None, body=None, raw=None, ip="198.51.100.7"):
        query = urlencode(who) if who else ""
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        r = self.api.handle(method, path + ("?" + query if query and "?" not in path else ("&" + query if query else "")), {}, data, ip)
        return r

    def j(self, r):
        return json.loads(r.body)

    def ask(self, who=SAM, song=None):
        return self.call("POST", "/api/quality/requests", who, {"songId": song or self.song})


class APersonAsksTest(ServerTest):
    def test_the_app_can_ask_what_this_is_without_signing_in(self):
        r = self.call("GET", "/api/info")
        self.assertEqual(r.status, 200)
        self.assertEqual(self.j(r), {"service": "encore-quality", "version": 1, "features": ["quality-requests", "upgrade-map"]})
        self.assertEqual(self.call("GET", "/quality/api/info").body, r.body, "with or without the prefix")
        self.assertEqual(self.call("POST", "/api/info").status, 405)

    def test_everything_else_needs_the_persons_own_music_login(self):
        self.assertEqual(self.call("GET", "/api/quality/requests").status, 401)
        self.assertEqual(self.call("GET", "/api/quality/requests", login("sam", "not his password")).status, 401)
        self.assertEqual(self.call("GET", "/api/admin/quality").status, 401)

    def test_asking_for_a_better_copy_is_accepted_and_shows_in_the_persons_list_in_plain_words(self):
        r = self.ask()
        self.assertEqual(r.status, 202, r.body)
        made = self.j(r)["request"]
        self.assertEqual((made["title"], made["artist"], made["album"], made["state"]), ("Silvera", "Gojira", "Magma", "queued"))
        self.assertEqual(made["label"], "Waiting")
        self.assertTrue(made["message"])
        listing = self.j(self.call("GET", "/api/quality/requests", SAM))["requests"]
        self.assertEqual([x["id"] for x in listing], [made["id"]])

    def test_asking_twice_is_the_same_request_not_two(self):
        first = self.j(self.ask())["request"]["id"]
        second = self.j(self.ask())["request"]["id"]
        self.assertEqual(first, second)
        self.assertEqual(len(self.j(self.call("GET", "/api/quality/requests", SAM))["requests"]), 1)

    def test_a_person_sees_only_their_own_requests_and_cannot_touch_anybody_elses(self):
        sam_id = self.j(self.ask(SAM))["request"]["id"]
        self.assertEqual(self.j(self.call("GET", "/api/quality/requests", MIA))["requests"], [])
        self.assertEqual(self.call("GET", f"/api/quality/requests/{sam_id}", MIA).status, 404)
        self.assertEqual(self.call("DELETE", f"/api/quality/requests/{sam_id}", MIA).status, 404)
        self.assertEqual(self.call("GET", f"/api/quality/requests/{sam_id}", SAM).status, 200)

    def test_a_song_the_person_cannot_see_is_not_theirs_to_ask_for(self):
        self.nd_fake.hidden_from[self.song] = {"sam"}
        r = self.ask(SAM)
        self.assertEqual(r.status, 404)
        self.assertEqual(self.ask(SAM, song="no-such-song").status, 404)
        self.assertEqual(self.store.in_state(*store.ACTIVE), [])

    def test_when_the_service_cannot_see_where_songs_are_kept_the_person_is_told_to_ask_the_owner(self):
        self.nd_fake.admin_login = ("owner", "changed")
        r = self.ask()
        self.assertEqual(r.status, 503)
        self.assertIn("Ask the owner", self.j(r)["error"])

    def test_a_song_inside_the_hidden_folders_is_refused(self):
        hidden = self.nd_fake.add_song(".encore/pool/A/B/c.flac", title="c", artist="A", album="B")
        self.assertEqual(self.ask(song=hidden).status, 400)

    def test_several_songs_at_once_are_asked_in_one_go(self):
        other = self.nd_fake.add_song("Gojira/Magma/02 - Magma.opus", title="Magma", artist="Gojira", album="Magma", track=2)
        r = self.call("POST", "/api/quality/requests", SAM, {"songIds": [self.song, other, self.song]})
        self.assertEqual(r.status, 202)
        self.assertEqual(len(self.j(r)["requests"]), 2, "the repeated song counts once")

    def test_nonsense_in_the_request_is_a_sentence_not_a_crash(self):
        for body in ({}, {"songId": 5}, {"songId": ""}, {"songIds": []}, {"songIds": "x"}, {"songIds": [1, 2]}, {"songIds": ["a"] * 201}):
            r = self.call("POST", "/api/quality/requests", SAM, body)
            self.assertEqual(r.status, 400, body)
            self.assertIn("error", self.j(r))

    def test_too_many_songs_waiting_at_once_is_held_back_politely(self):
        for n in range(MAX_ACTIVE_PER_PERSON):
            self.store.add_want(person="sam", song_id=f"x{n}", artist="A", album="B", title="T", year=None, track=None, duration=None,
                                quick_path=f"A/B/{n}.opus")
        r = self.ask()
        self.assertEqual(r.status, 429)
        self.assertIn("Wait until some are done", self.j(r)["error"])

    def test_a_person_can_stop_a_request_once(self):
        made = self.j(self.ask())["request"]["id"]
        self.assertEqual(self.call("DELETE", f"/api/quality/requests/{made}", SAM).status, 204)
        self.assertEqual(self.j(self.call("GET", f"/api/quality/requests/{made}", SAM))["state"], "cancelled")
        self.assertEqual(self.call("DELETE", f"/api/quality/requests/{made}", SAM).status, 409)

    def test_the_upgrade_map_tells_a_phone_which_ids_became_which(self):
        self.store.add_upgrade("sam", "old1", "new1", "FLAC")
        self.store.add_upgrade("mia", "old2", "new2", "FLAC")
        first = self.j(self.call("GET", "/api/quality/upgrades", SAM))
        self.assertEqual([(u["old"], u["new"]) for u in first["upgrades"]], [("old1", "new1"), ("old2", "new2")])
        self.assertEqual(first["last"], 2)
        later = self.j(self.call("GET", "/api/quality/upgrades?after=1", SAM))
        self.assertEqual([u["old"] for u in later["upgrades"]], ["old2"])
        none = self.j(self.call("GET", "/api/quality/upgrades?after=2", SAM))
        self.assertEqual((none["upgrades"], none["last"]), ([], 2), "a phone that is up to date keeps its number")
        self.assertEqual(self.call("GET", "/api/quality/upgrades?after=x", SAM).status, 400)
        self.assertEqual(self.call("GET", "/api/quality/upgrades", None).status, 401, "even this needs a login")

    def test_the_status_says_whether_high_quality_is_switched_on_and_ready(self):
        off = self.j(self.call("GET", "/api/quality/status", SAM))
        self.assertEqual((off["enabled"], off["ready"]), (False, False))
        self.assertIn("not switched on", off["message"])
        self.maintenance.set_soulseek(True)
        starting = self.j(self.call("GET", "/api/quality/status", SAM))
        self.assertEqual((starting["enabled"], starting["ready"]), (True, False), "on, but Lidarr is not wired yet")
        self.maintenance.run()
        ready = self.j(self.call("GET", "/api/quality/status", SAM))
        self.assertEqual((ready["enabled"], ready["ready"], ready["message"]), (True, True, "Ready."))


class TheOwnerTest(ServerTest):
    def test_only_an_owner_may_manage_and_a_guest_is_told_so(self):
        for path, method in (("/api/admin/quality", "GET"), ("/api/admin/quality/selftest", "POST"), ("/api/admin/quality/settings", "PUT")):
            r = self.call(method, path, SAM, {})
            self.assertEqual(r.status, 403, path)
            self.assertIn("Only owners", self.j(r)["error"])

    def test_when_the_people_service_does_not_answer_a_music_server_administrator_counts(self):
        self.people_up = False
        self.assertEqual(self.call("GET", "/api/admin/quality", OWNER).status, 200)
        self.assertEqual(self.call("GET", "/api/admin/quality", SAM).status, 403)

    def test_the_summary_shows_the_parts_the_counts_and_what_went_wrong_by_song_not_by_person(self):
        self.ask(SAM)
        want = self.store.of_person("sam")[0]
        self.store.update(want.id, state=store.NO_MATCH, detail="The music catalogue has no album by that name for this artist.")
        r = self.j(self.call("GET", "/api/admin/quality", OWNER))
        self.assertEqual(r["counts"], {"no_match": 1})
        self.assertEqual(r["trouble"][0]["title"], "Silvera")
        self.assertIn("catalogue", r["trouble"][0]["message"])
        self.assertNotIn("sam", json.dumps(r["trouble"]), "who asked is their own business")
        self.assertEqual(r["today"], {"started": 0, "limit": 40})
        self.assertIn("lidarr", r["health"])

    def test_the_owner_switches_soulseek_on_and_off_and_it_takes_effect(self):
        self.maintenance.run()
        self.assertFalse(self.slskd_fake.logged_in)
        r = self.call("PUT", "/api/admin/quality/settings", OWNER, {"soulseek": True})
        self.assertEqual(r.status, 200)
        self.assertTrue(self.j(r)["settings"]["soulseek"])
        self.assertTrue(self.slskd_fake.logged_in)
        self.call("PUT", "/api/admin/quality/settings", OWNER, {"soulseek": False})
        self.assertFalse(self.slskd_fake.logged_in)

    def test_the_daily_limit_and_the_free_space_floor_are_changed_within_sensible_bounds(self):
        r = self.call("PUT", "/api/admin/quality/settings", OWNER, {"dailyCap": 10, "minFreeGb": 20})
        self.assertEqual(self.j(r)["settings"], {"soulseek": False, "dailyCap": 10, "minFreeGb": 20.0})
        self.assertEqual((self.api.limits().daily_cap, self.api.limits().min_free_gb), (10, 20.0), "the engine reads them")
        for bad in ({"dailyCap": 0}, {"dailyCap": 501}, {"dailyCap": "ten"}, {"dailyCap": True}, {"minFreeGb": -1}, {"minFreeGb": "x"},
                    {"soulseek": "yes"}):
            self.assertEqual(self.call("PUT", "/api/admin/quality/settings", OWNER, bad).status, 400, bad)

    def test_the_self_test_asks_every_question_and_remembers_the_answer_for_the_summary(self):
        self.maintenance.set_soulseek(True)
        self.maintenance.run()
        r = self.call("POST", "/api/admin/quality/selftest", OWNER, {})
        self.assertEqual(r.status, 200)
        result = self.j(r)
        self.assertTrue(result["ok"])
        self.assertTrue({c["key"] for c in result["checks"]} >= {"lidarr", "wiring", "slskd", "soulseek", "folders", "space"})
        self.assertEqual(self.j(self.call("GET", "/api/admin/quality", OWNER))["lastSelfTest"]["ok"], True)

    def test_a_failed_self_test_is_not_ok(self):
        self.maintenance.run()
        self.lidarr_fake.down = True
        self.assertFalse(self.j(self.call("POST", "/api/admin/quality/selftest", OWNER, {}))["ok"])

    def test_the_owner_can_send_a_stuck_request_to_look_again_but_not_one_that_is_working(self):
        self.ask()
        want = self.store.of_person("sam")[0]
        self.assertEqual(self.call("POST", f"/api/admin/quality/requests/{want.id}/retry", OWNER, {}).status, 409)
        self.store.update(want.id, state=store.FAILED, attempts=3)
        self.assertEqual(self.call("POST", f"/api/admin/quality/requests/{want.id}/retry", OWNER, {}).status, 204)
        again = self.store.get(want.id)
        self.assertEqual((again.state, again.attempts), (store.QUEUED, 0))
        self.assertEqual(self.call("POST", "/api/admin/quality/requests/999/retry", OWNER, {}).status, 404)


class TheEdgesTest(ServerTest):
    def test_wrong_methods_unknown_paths_and_broken_bodies(self):
        self.assertEqual(self.call("PUT", "/api/quality/requests", SAM, {}).status, 405)
        self.assertEqual(self.call("GET", "/api/nothing", SAM).status, 404)
        self.assertEqual(self.call("GET", "/elsewhere", SAM).status, 404)
        self.assertEqual(self.call("GET", "/api/quality/requests/abc", SAM).status, 404)
        self.assertEqual(self.call("POST", "/api/quality/requests", SAM, raw=b"{nope").status, 400)
        self.assertEqual(self.call("POST", "/api/quality/requests", SAM, raw=b"[1]").status, 400)
        self.assertEqual(self.call("POST", "/api/quality/requests", SAM, raw=b"x" * 70_000).status, 413)

    def test_a_flood_of_requests_from_one_person_is_slowed(self):
        codes = [self.call("GET", "/api/quality/status", SAM).status for _ in range(130)]
        self.assertIn(429, codes)
        self.assertEqual(codes[0], 200)
        self.assertEqual(self.call("GET", "/api/quality/status", MIA).status, 200, "others are not slowed with them")


if __name__ == "__main__":
    unittest.main()
