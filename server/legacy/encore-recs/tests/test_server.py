"""The recommendations service as the app and the owner's page use it (docs/47): a person sees their own lists; the owner sees counts only."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from encore_recs.build import Result
from encore_recs.builder import FRESH_S, RETRY_S, Builder
from encore_recs.cache import Cache
from encore_recs.navidrome import Navidrome
from encore_recs.server import EMPTY_SENTENCE, OFF_SENTENCE, WAITING_SENTENCE, Api
from encore_recs.sources import Sources
from encore_recs.store import Store

from tests.fakes import FakeWorld, MusicDb


def login(user, password, salt="s4lt"):
    return {"u": user, "t": hashlib.md5((password + salt).encode()).hexdigest(), "s": salt}


SAM, MIA, OWNER = login("sam", "sam-pw"), login("mia", "mia-pw"), login("owner", "owner-pw")


class FakeNavidromeHttp:
    def __init__(self):
        self.pw = {"sam": "sam-pw", "mia": "mia-pw", "owner": "owner-pw"}

    def __call__(self, url):
        import urllib.parse
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
        ok = q["u"] in self.pw and hashlib.md5((self.pw[q["u"]] + q["s"]).encode()).hexdigest() == q["t"]
        method = urllib.parse.urlsplit(url).path.rsplit("/", 1)[1]
        if not ok:
            return {"status": "failed"}
        if method == "getUser.view":
            return {"status": "ok", "user": {"adminRole": q["u"] == "owner"}}
        return {"status": "ok"}


class ServerBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.nd_dir = root / "navidrome"
        self.nd_dir.mkdir()
        self.db = MusicDb(self.nd_dir)
        self.addCleanup(self.db.close)
        for name in ("sam", "mia", "owner"):
            self.db.person(name)
        self.now = [1_760_000_000.0]
        self.world = FakeWorld()
        cache = Cache(":memory:")
        self.addCleanup(cache.close)
        self.store = Store(":memory:", lambda: self.now[0])
        self.addCleanup(self.store.close)
        self.builder = Builder(store=self.store, sources=Sources(cache, self.world, sleep=lambda s: None), database_dir=self.nd_dir,
                               scratch=root, clock=lambda: self.now[0])
        self.people_owners = {"owner"}
        self.background = []
        self.api = Api(store=self.store, navidrome=Navidrome("http://nd", http=FakeNavidromeHttp()), builder=self.builder,
                       people_url="http://people", http_get=self.people, clock=lambda: self.now[0],
                       run_in_background=lambda work: self.background.append(work))

    def people(self, url):
        user = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))["u"]
        return 200, {"canManage": user in self.people_owners}

    def call(self, method, path, who=None, body=None, raw=None):
        query = urlencode(who) if who else ""
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        return self.api.handle(method, path + ("?" + query if query and "?" not in path else ("&" + query if query else "")), {}, data, "198.51.100.7")

    def j(self, r):
        return json.loads(r.body)

    def listen(self, person, artist, songs, plays=6):
        for title in songs:
            self.db.play(person, self.db.song(artist, title), plays=plays)

    def world_with_metal(self):
        self.world.artist("Opeth", "mb-opeth", [("mb-pt", "Porcupine Tree", 2000), ("mb-dt", "Dream Theater", 1900), ("mb-kat", "Katatonia", 1800)],
                          deezer_id=1, songs=["Bleak", "Windowpane"])
        self.world.artist("Porcupine Tree", "mb-pt", [], deezer_id=3, songs=["Blackest Eyes", "Trains"])
        self.world.artist("Dream Theater", "mb-dt", [], deezer_id=4, songs=["Pull Me Under", "Metropolis"])
        self.world.artist("Katatonia", "mb-kat", [], deezer_id=5, songs=["Leaders", "July"])


class APersonsListsTest(ServerBase):
    def test_the_app_can_ask_what_this_is_without_signing_in(self):
        r = self.call("GET", "/api/info")
        self.assertEqual(self.j(r)["service"], "encore-recs")
        self.assertEqual(self.call("GET", "/recs/api/info").body, r.body)

    def test_everything_else_needs_the_persons_music_login(self):
        self.assertEqual(self.call("GET", "/api/recs/home").status, 401)
        self.assertEqual(self.call("GET", "/api/recs/home", login("sam", "wrong")).status, 401)

    def test_a_person_with_no_lists_yet_is_told_they_are_being_made(self):
        r = self.j(self.call("GET", "/api/recs/home", SAM))
        self.assertEqual((r["state"], r["message"], r["rows"]), ("waiting", WAITING_SENTENCE, []))

    def test_a_person_who_has_barely_listened_is_told_to_play_a_few_songs(self):
        self.listen("sam", "Opeth", ["Bleak"], plays=1)
        self.builder.run(everyone=True)
        r = self.j(self.call("GET", "/api/recs/home", SAM))
        self.assertEqual((r["state"], r["message"]), ("empty", EMPTY_SENTENCE))

    def test_after_the_build_a_person_gets_their_own_rows_and_nobody_elses(self):
        self.world_with_metal()
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        self.builder.run(everyone=True)
        sam = self.j(self.call("GET", "/api/recs/home", SAM))
        self.assertEqual(sam["state"], "ready")
        self.assertIn("made-for-you", [r["id"] for r in sam["rows"]])
        made = next(r for r in sam["rows"] if r["id"] == "made-for-you")["items"]
        self.assertIn("Porcupine Tree", {s["artist"] for s in made})
        mia = self.j(self.call("GET", "/api/recs/home", MIA))
        self.assertEqual(mia["state"], "empty", "mia has played nothing: she gets none of sam's suggestions")
        self.assertEqual(mia["rows"], [])

    def test_the_pool_for_smart_shuffle_is_the_persons_own(self):
        self.world_with_metal()
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        self.builder.run(everyone=True)
        pool = self.j(self.call("GET", "/api/recs/pool", SAM))
        self.assertTrue(pool["songs"])
        self.assertEqual(self.j(self.call("GET", "/api/recs/pool", MIA))["songs"], [])

    def test_not_for_me_hides_at_once_and_can_be_undone(self):
        self.world_with_metal()
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        self.builder.run(everyone=True)
        made = lambda: [s["artist"] for r in self.j(self.call("GET", "/api/recs/home", SAM))["rows"] if r["id"] == "made-for-you" for s in r["items"]]
        self.assertIn("Dream Theater", made())
        r = self.call("POST", "/api/recs/hide", SAM, {"artist": "Dream Theater"})
        self.assertEqual(r.status, 201)
        self.assertNotIn("Dream Theater", made(), "gone from the list without waiting for tomorrow's build")
        self.assertNotIn("Dream Theater", str(self.j(self.call("GET", "/api/recs/pool", SAM))))
        self.assertEqual([h["artist"] for h in self.j(self.call("GET", "/api/recs/hidden", SAM))["hidden"]], ["Dream Theater"])
        self.assertEqual(self.j(self.call("GET", "/api/recs/hidden", MIA))["hidden"], [], "nobody else's list is touched")
        self.call("DELETE", f"/api/recs/hidden/{r.body and self.j(r)['id']}", SAM)
        self.assertIn("Dream Theater", made())

    def test_one_song_can_be_hidden_without_hiding_the_artist(self):
        self.world_with_metal()
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        self.builder.run(everyone=True)
        self.call("POST", "/api/recs/hide", SAM, {"artist": "Porcupine Tree", "title": "Trains"})
        text = str(self.j(self.call("GET", "/api/recs/home", SAM)))
        self.assertNotIn("'Trains'", text.replace('"', "'"))
        self.assertIn("Blackest Eyes", text)

    def test_hiding_nonsense_or_somebody_elses_entry_is_refused(self):
        for body in ({}, {"artist": ""}, {"artist": 5}, {"artist": "X", "title": 5}):
            self.assertEqual(self.call("POST", "/api/recs/hide", SAM, body).status, 400, body)
        made = self.j(self.call("POST", "/api/recs/hide", SAM, {"artist": "Dream Theater"}))["id"]
        self.assertEqual(self.call("DELETE", f"/api/recs/hidden/{made}", MIA).status, 404)
        self.assertEqual(self.call("DELETE", f"/api/recs/hidden/{made}", SAM).status, 204)

    def test_how_a_suggestion_did_is_counted_for_everybody_together(self):
        for event in ("shown", "played", "played", "starred"):
            self.assertEqual(self.call("POST", "/api/recs/feedback", SAM, {"surface": "made-for-you", "event": event}).status, 204)
        self.assertEqual(self.call("POST", "/api/recs/feedback", MIA, {"surface": "because:opeth", "event": "shown"}).status, 204)
        self.assertEqual(self.call("POST", "/api/recs/feedback", SAM, {"surface": "nonsense", "event": "shown"}).status, 400)
        self.assertEqual(self.call("POST", "/api/recs/feedback", SAM, {"surface": "pool", "event": "bought"}).status, 400)
        self.assertEqual(self.store.totals(), {"made-for-you": {"shown": 1, "played": 2, "starred": 1}, "because": {"shown": 1}})

    def test_switched_off_by_the_owner_the_person_is_told_so_and_nothing_is_shown(self):
        self.world_with_metal()
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        self.builder.run(everyone=True)
        self.call("PUT", "/api/admin/recs/settings", OWNER, {"enabled": False})
        r = self.j(self.call("GET", "/api/recs/home", SAM))
        self.assertEqual((r["state"], r["message"], r["rows"]), ("off", OFF_SENTENCE, []))
        self.assertEqual(self.j(self.call("GET", "/api/recs/pool", SAM))["songs"], [])

    def test_edges(self):
        self.assertEqual(self.call("POST", "/api/recs/home", SAM, {}).status, 405)
        self.assertEqual(self.call("GET", "/api/nothing", SAM).status, 404)
        self.assertEqual(self.call("POST", "/api/recs/hide", SAM, raw=b"{nope").status, 400)
        self.assertEqual(self.call("POST", "/api/recs/hide", SAM, raw=b"x" * 9000).status, 413)


class TheOwnerSeesCountsOnlyTest(ServerBase):
    def setUp(self):
        super().setUp()
        self.world_with_metal()
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        self.builder.run(everyone=True)

    def test_only_an_owner_may_look_or_change_anything(self):
        for method, path in (("GET", "/api/admin/recs"), ("PUT", "/api/admin/recs/settings"), ("POST", "/api/admin/recs/rebuild")):
            r = self.call(method, path, SAM, {"enabled": True})
            self.assertEqual(r.status, 403, path)

    def test_the_owners_view_has_no_list_no_reason_and_no_name(self):
        r = self.call("GET", "/api/admin/recs", OWNER)
        text = r.body.decode()
        self.assertEqual(r.status, 200)
        for private in ("Porcupine Tree", "Dream Theater", "Because you play", "Opeth", "sam", "Bleak"):
            self.assertNotIn(private, text, "the owner never sees what anybody's list was made from")
        summary = self.j(r)
        self.assertEqual((summary["enabled"], summary["peopleWithLists"]), (True, 1))
        self.assertEqual(summary["lastRun"]["people"], 3)
        self.assertIn("Only artist and song names", summary["sentence"])

    def test_the_owner_switches_suggestions_off_and_on(self):
        self.assertFalse(self.j(self.call("PUT", "/api/admin/recs/settings", OWNER, {"enabled": False}))["enabled"])
        self.assertTrue(self.j(self.call("PUT", "/api/admin/recs/settings", OWNER, {"enabled": True}))["enabled"])
        self.assertEqual(self.call("PUT", "/api/admin/recs/settings", OWNER, {"enabled": "yes"}).status, 400)

    def test_a_rebuild_is_asked_for_and_happens_in_the_background_once_at_a_time(self):
        self.assertEqual(self.call("POST", "/api/admin/recs/rebuild", OWNER, {}).status, 202)
        self.assertEqual(self.call("POST", "/api/admin/recs/rebuild", OWNER, {}).status, 202)
        self.assertEqual(len(self.background), 1, "a second press while it runs starts nothing")
        built_at = self.store.build_of("sam")["builtAt"]
        self.now[0] += 60  # a minute later, long before the nightly pass would look again
        self.background[0]()
        self.assertGreater(self.store.build_of("sam")["builtAt"], built_at, "'rebuild now' means now, not 'when the lists are old enough'")
        self.assertFalse(self.j(self.call("GET", "/api/admin/recs", OWNER))["rebuilding"])


class TheNightlyBuildTest(ServerBase):
    def test_the_nightly_pass_makes_lists_for_everybody_who_is_due_and_leaves_fresh_ones(self):
        self.world_with_metal()
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        first = self.builder.run(everyone=True)
        self.assertEqual((first["people"], first["built"], first["empty"]), (3, 1, 2))
        calls = len(self.world.calls)
        self.builder.run(everyone=True)
        self.assertEqual(len(self.world.calls), calls, "lists younger than twenty hours are not made again")
        self.now[0] += FRESH_S + 1
        self.builder.run(everyone=True)
        self.assertGreater(len(self.world.calls), calls - 1)

    def test_between_nights_only_people_without_a_real_list_are_tried_and_not_every_few_minutes(self):
        self.world_with_metal()
        self.builder.run(everyone=True)       # nobody has played anything: everybody is "empty"
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        self.builder.run(everyone=False)
        self.assertEqual(self.store.build_of("sam")["state"], "empty", "tried too soon after the last time")
        self.now[0] += RETRY_S + 1
        self.builder.run(everyone=False)
        self.assertEqual(self.store.build_of("sam")["state"], "ready", "a person who has now played enough gets a first list within the hour")

    def test_a_service_that_says_slow_down_ends_the_run_and_the_old_lists_stay(self):
        self.world_with_metal()
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        self.builder.run(everyone=True)
        before = self.store.build_of("sam")
        self.now[0] += FRESH_S + 1
        self.world.fail_with = 429
        self.listen("sam", "Tool", ["Sober"])   # a new artist whose id is not cached yet: the catalogue is asked, and says no
        summary = self.builder.run(everyone=True)
        self.assertTrue(summary["throttled"])
        self.assertEqual(self.store.build_of("sam")["rows"], before["rows"], "the last lists stay")

    def test_a_person_who_stopped_listening_keeps_their_last_lists(self):
        self.world_with_metal()
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        self.builder.run(everyone=True)
        self.db.db.execute("UPDATE annotation SET play_count = 0, starred = 0")
        self.db.db.commit()
        self.now[0] += FRESH_S + 1
        self.builder.run(everyone=True)
        self.assertEqual(self.store.build_of("sam")["state"], "ready")

    def test_when_the_music_servers_database_cannot_be_read_that_is_remembered_not_crashed_over(self):
        broken = Builder(store=self.store, sources=Sources(Cache(":memory:"), self.world), database_dir=Path(self._tmp.name) / "nowhere")
        summary = broken.run(everyone=True)
        self.assertTrue(summary["unreadable"])
        self.assertTrue(broken.last_run()["unreadable"])

    def test_a_person_who_leaves_leaves_nothing_behind(self):
        self.world_with_metal()
        self.listen("sam", "Opeth", ["Bleak", "Windowpane"])
        self.builder.run(everyone=True)
        self.store.hide("sam", "Dream Theater")
        self.store.forget_person("sam")
        self.assertIsNone(self.store.build_of("sam"))
        self.assertEqual(self.store.hidden_list("sam"), [])
        self.assertEqual(self.store.seen_releases("sam"), set())


if __name__ == "__main__":
    unittest.main()
