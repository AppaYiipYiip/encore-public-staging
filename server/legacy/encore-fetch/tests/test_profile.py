"""The profile store: documents with versions, an idempotent event log, and
the HTTP routes in front of them. Real files in a temp folder, no network."""
import json
import tempfile
import unittest
from pathlib import Path

from encore_fetch.jobs import JobManager
from encore_fetch.navidrome import Auth, Navidrome
from encore_fetch.profile import (Conflict, ProfileError, ProfileStore,
                                  clean_event)
from encore_fetch.server import Api

NOW = 1_760_000_000.0          # 2025-10-09
NOW_MS = int(NOW * 1000)


def event(i, **extra):
    return {"id": f"dev1-{i}", "t": NOW_MS - 1000 * i, "song": f"s{i}",
            "title": f"Song {i}", "artist": "Opeth", "album": "Damnation",
            "genre": "Prog", "dur": 240, "ms": 230_000, "src": "album",
            "dev": "phone", **extra}


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.now = NOW
        self.store = self.make()

    def make(self, **kw):
        return ProfileStore(self.root, clock=lambda: self.now, **kw)

    # ------------------------------------------------------------ documents

    def test_a_document_is_versioned_from_one(self):
        self.assertIsNone(self.store.get_doc("marwa", "settings"))
        first = self.store.put_doc("marwa", "settings", 0, {"eq": "flat"})
        self.assertEqual(first, {"v": 1, "at": NOW_MS})
        second = self.store.put_doc("marwa", "settings", 1, {"eq": "bass"})
        self.assertEqual(second["v"], 2)
        got = self.store.get_doc("marwa", "settings")
        self.assertEqual((got["v"], got["data"]), (2, {"eq": "bass"}))

    def test_a_stale_write_is_refused_with_the_current_copy(self):
        self.store.put_doc("marwa", "settings", 0, {"a": 1})
        self.store.put_doc("marwa", "settings", 1, {"a": 2})      # device 1
        with self.assertRaises(Conflict) as caught:               # device 2
            self.store.put_doc("marwa", "settings", 1, {"a": 3})
        self.assertEqual(caught.exception.version, 2)
        self.assertEqual(caught.exception.data, {"a": 2})
        # it merges and retries on the version it was told about
        done = self.store.put_doc("marwa", "settings", 2, {"a": 2, "b": 3})
        self.assertEqual(done["v"], 3)

    def test_a_first_write_cannot_claim_an_existing_document(self):
        self.store.put_doc("marwa", "pins", 0, {"x": 1})
        with self.assertRaises(Conflict):
            self.store.put_doc("marwa", "pins", 0, {"x": 2})

    def test_documents_are_validated(self):
        with self.assertRaises(ProfileError) as e:
            self.store.put_doc("marwa", "../etc", 0, {})
        self.assertEqual(e.exception.status, 400)
        with self.assertRaises(ProfileError):
            self.store.put_doc("marwa", "Settings", 0, {})        # lower case
        with self.assertRaises(ProfileError):
            self.store.put_doc("marwa", "settings", 0, ["not", "an", "object"])
        small = self.make(max_doc_bytes=100)
        with self.assertRaises(ProfileError) as e:
            small.put_doc("marwa", "settings", 0, {"blob": "x" * 500})
        self.assertEqual(e.exception.status, 413)

    def test_the_number_of_documents_is_bounded(self):
        for i in range(32):
            self.store.put_doc("marwa", f"d{i}", 0, {})
        with self.assertRaises(ProfileError):
            self.store.put_doc("marwa", "one-too-many", 0, {})
        # an existing one can still be updated
        self.store.put_doc("marwa", "d0", 1, {"ok": True})

    def test_people_are_kept_apart_and_names_cannot_climb_out(self):
        self.store.put_doc("marwa", "settings", 0, {"mine": True})
        self.assertIsNone(self.store.get_doc("sara", "settings"))
        for bad in ("../marwa", "a/b", "", "x" * 80):
            with self.assertRaises(ProfileError):
                self.store.list(bad)

    def test_writes_are_atomic_no_temp_file_is_left(self):
        self.store.put_doc("marwa", "settings", 0, {"a": 1})
        left = [p.name for p in self.root.rglob("*.tmp")]
        self.assertEqual(left, [])

    def test_the_whole_profile_is_size_limited(self):
        tiny = self.make(max_total_bytes=300)
        tiny.put_doc("marwa", "a", 0, {"x": "y" * 100})
        with self.assertRaises(ProfileError) as e:
            tiny.put_doc("marwa", "b", 0, {"x": "y" * 400})
        self.assertEqual(e.exception.status, 413)

    # --------------------------------------------------------------- events

    def test_events_are_stored_once_whatever_the_retries(self):
        a = self.store.add_events("marwa", [event(1), event(2), event(3)])
        self.assertEqual(a, {"accepted": 3, "dupes": 0, "rejected": 0})
        b = self.store.add_events("marwa", [event(2), event(3), event(4)])
        self.assertEqual(b, {"accepted": 1, "dupes": 2, "rejected": 0})
        listed = self.store.list("marwa")["events"]
        self.assertEqual(listed, {"count": 4, "last": 4})

    def test_unusable_events_are_counted_not_stored(self):
        bad = [{"t": NOW_MS}, {"id": "x"}, "text", None,
               {"id": "y", "t": 5}, {"id": "z", "t": NOW_MS + 10 ** 12}]
        got = self.store.add_events("marwa", bad + [event(1)])
        self.assertEqual(got, {"accepted": 1, "dupes": 0, "rejected": 6})

    def test_events_keep_only_known_fields_and_clean_text(self):
        ev = clean_event({"id": "a", "t": NOW_MS, "title": "Wind\x00ow\x07pane",
                          "artist": "  Opeth  ", "evil": "x", "dur": -4,
                          "ms": 1000}, NOW_MS)
        self.assertEqual(ev, {"id": "a", "t": NOW_MS, "title": "Windowpane",
                              "artist": "Opeth", "ms": 1000})

    def test_a_call_and_a_day_have_limits(self):
        small = self.make(max_events_per_call=3, max_events_per_day=5)
        with self.assertRaises(ProfileError) as e:
            small.add_events("marwa", [event(i) for i in range(4)])
        self.assertEqual(e.exception.status, 413)
        small.add_events("marwa", [event(i) for i in range(3)])
        with self.assertRaises(ProfileError) as e:
            small.add_events("marwa", [event(i) for i in range(10, 13)])
        self.assertEqual(e.exception.status, 429)
        self.now += 86_400                     # tomorrow
        small.add_events("marwa", [event(i) for i in range(10, 13)])

    def test_events_survive_a_restart_and_stay_deduplicated(self):
        self.store.add_events("marwa", [event(1), event(2)])
        again = self.make()                     # a new process, the same folder
        got = again.add_events("marwa", [event(2), event(3)])
        self.assertEqual((got["accepted"], got["dupes"]), (1, 1))
        listed = again.read_events("marwa")
        self.assertEqual([e["id"] for e in listed["events"]],
                         ["dev1-1", "dev1-2", "dev1-3"])
        self.assertEqual([e["seq"] for e in listed["events"]], [1, 2, 3])

    def test_reading_pages_by_cursor_in_arrival_order(self):
        # events arrive out of time order (a phone that was offline)
        self.store.add_events("marwa", [event(i) for i in (5, 6, 7)])
        self.store.add_events("marwa", [event(i) for i in (1, 2)])
        page = self.store.read_events("marwa", since=0, limit=2)
        self.assertEqual([e["seq"] for e in page["events"]], [1, 2])
        self.assertEqual(page["next"], 2)
        page2 = self.store.read_events("marwa", since=page["next"], limit=2)
        self.assertEqual([e["seq"] for e in page2["events"]], [3, 4])
        page3 = self.store.read_events("marwa", since=page2["next"], limit=2)
        self.assertEqual([e["seq"] for e in page3["events"]], [5])
        self.assertIsNone(page3["next"])
        # a second device that already has seq 3 asks from there
        rest = self.store.read_events("marwa", since=3)
        self.assertEqual([e["seq"] for e in rest["events"]], [4, 5])

    def test_a_half_written_last_line_is_skipped(self):
        self.store.add_events("marwa", [event(1)])
        path = self.root / "marwa" / "events" / "events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write('{"seq": 2, "id": "dev1-torn", "t"')
        fresh = self.make()
        self.assertEqual(fresh.list("marwa")["events"]["count"], 1)
        self.assertEqual(len(fresh.read_events("marwa")["events"]), 1)


class FakeNavidrome(Navidrome):
    def __init__(self):
        super().__init__("http://x.invalid")
        self.valid = True

    def verify(self, auth):
        return self.valid


class ApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.nd = FakeNavidrome()
        manager = JobManager(
            music_dir=root / "music", work_dir=root / "work",
            resolver=None, downloader=None, navidrome=self.nd,
            min_free_gb=0)
        self.api = Api(manager, self.nd, ProfileStore(root / "profile"))
        self.q = "?u=marwa&t=" + "a" * 32 + "&s=salt1234"

    def call(self, method, path, body=None, extra=""):
        data = b"" if body is None else json.dumps(body).encode()
        return self.api.handle(method, path + self.q + extra, {}, data)

    def test_the_service_says_it_keeps_profiles(self):
        status, info = self.api.handle("GET", "/api/info", {})
        self.assertIn("profile", info["features"])

    def test_every_route_needs_the_music_login(self):
        for method, path in (("GET", "/api/profile"),
                             ("GET", "/api/profile/doc/settings"),
                             ("PUT", "/api/profile/doc/settings"),
                             ("POST", "/api/profile/events"),
                             ("GET", "/api/profile/events")):
            self.assertEqual(self.api.handle(method, path, {}, b"{}")[0], 401,
                             path)
        self.nd.valid = False
        self.assertEqual(self.call("GET", "/api/profile")[0], 401)

    def test_a_document_round_trip_and_a_conflict(self):
        self.assertEqual(
            self.call("GET", "/api/profile/doc/settings")[0], 404)
        status, put = self.call("PUT", "/api/profile/doc/settings",
                                {"baseV": 0, "data": {"eq": "flat"}})
        self.assertEqual((status, put["v"]), (200, 1))
        status, got = self.call("GET", "/api/profile/doc/settings")
        self.assertEqual((status, got["data"]), (200, {"eq": "flat"}))
        status, stale = self.call("PUT", "/api/profile/doc/settings",
                                  {"baseV": 0, "data": {"eq": "bass"}})
        self.assertEqual(status, 409)
        self.assertEqual((stale["v"], stale["data"]), (1, {"eq": "flat"}))
        status, listing = self.call("GET", "/api/profile")
        self.assertEqual(listing["docs"]["settings"]["v"], 1)

    def test_bad_bodies_are_400s_not_crashes(self):
        for body in ({"data": "text"}, {"baseV": -1, "data": {}},
                     {"baseV": True, "data": {}}, ["x"]):
            self.assertEqual(
                self.call("PUT", "/api/profile/doc/settings", body)[0], 400,
                body)
        status, _ = self.api.handle("PUT", "/api/profile/doc/settings" + self.q,
                                    {}, b"not json")
        self.assertEqual(status, 400)
        self.assertEqual(self.call("POST", "/api/profile/events", ["x"])[0], 400)
        self.assertEqual(self.call(
            "POST", "/api/profile/events", {"events": "nope"})[0], 400)
        self.assertEqual(self.call(
            "GET", "/api/profile/events", extra="&since=abc")[0], 400)

    def test_events_over_http(self):
        status, got = self.call("POST", "/api/profile/events",
                                {"events": [event(1), event(2)]})
        self.assertEqual((status, got["accepted"]), (200, 2))
        status, got = self.call("POST", "/api/profile/events",
                                {"events": [event(2)]})
        self.assertEqual(got["dupes"], 1)
        status, page = self.call("GET", "/api/profile/events", extra="&since=1")
        self.assertEqual([e["seq"] for e in page["events"]], [2])

    def test_routes_and_methods_are_closed_by_default(self):
        self.assertEqual(self.call("DELETE", "/api/profile")[0], 405)
        self.assertEqual(self.call("DELETE", "/api/profile/doc/x")[0], 405)
        self.assertEqual(self.call("GET", "/api/profile/nothing")[0], 404)
        self.assertEqual(self.call("GET", "/api/profile/doc/Bad..Name")[0], 404)

    def test_without_a_store_the_routes_do_not_exist(self):
        root = Path(self._tmp.name)
        manager = JobManager(
            music_dir=root / "m", work_dir=root / "w", resolver=None,
            downloader=None, navidrome=self.nd, min_free_gb=0)
        api = Api(manager, self.nd)
        status, info = api.handle("GET", "/api/info", {})
        self.assertNotIn("profile", info["features"])
        self.assertEqual(api.handle("GET", "/api/profile" + self.q, {})[0], 404)


if __name__ == "__main__":
    unittest.main()
