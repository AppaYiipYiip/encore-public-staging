"""The public services recommendations come from: asked politely, remembered, and never believed when unsure (docs/47 section 2)."""
import unittest

from encore_recs.cache import MISSING, Cache
from encore_recs.sources import SIMILAR_ALGORITHM, Sources, Throttle, Throttled, user_agent

from tests.fakes import FakeWorld


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class CacheTest(unittest.TestCase):
    def test_what_was_learned_is_remembered_until_it_expires(self):
        clock = Clock()
        cache = Cache(":memory:", clock)
        cache.put("k", {"a": 1}, 100)
        self.assertEqual(cache.get("k"), {"a": 1})
        clock.now += 101
        self.assertIs(cache.get("k"), MISSING)

    def test_a_remembered_nothing_is_different_from_never_asked(self):
        cache = Cache(":memory:")
        self.assertIs(cache.get("k"), MISSING)
        cache.put("k", None, None)
        self.assertIsNone(cache.get("k"))

    def test_expired_entries_can_be_swept(self):
        clock = Clock()
        cache = Cache(":memory:", clock)
        cache.put("old", 1, 10)
        cache.put("forever", 2, None)
        clock.now += 11
        self.assertEqual(cache.sweep(), 1)
        self.assertEqual(cache.get("forever"), 2)


class ThrottleTest(unittest.TestCase):
    def test_calls_are_spaced_by_the_services_rule(self):
        clock = Clock()
        throttle = Throttle(1.1, clock, clock.sleep)
        for _ in range(3):
            throttle.wait()
        self.assertEqual(len(clock.slept), 2)
        self.assertTrue(all(abs(s - 1.1) < 1e-9 for s in clock.slept))


class UserAgentTest(unittest.TestCase):
    def test_it_says_what_this_is_and_names_no_address_that_is_not_ours(self):
        agent = user_agent("0.1.0")
        self.assertEqual(agent, "EncoreServer/0.1.0 (self-hosted music server)")
        self.assertNotIn("http", agent, "musicbrainz refused a User-Agent with an invented project address")

    def test_a_way_to_reach_the_owner_is_included_only_when_the_owner_gave_one(self):
        self.assertIn("contact: me@example.org", user_agent("0.1.0", "me@example.org"))
        self.assertNotIn("contact", user_agent("0.1.0", "   "))
        self.assertLessEqual(len(user_agent("0.1.0", "x" * 500)), 140, "a long value is cut, not trusted")


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld()
        self.clock = Clock()
        self.cache = Cache(":memory:", self.clock)
        self.addCleanup(self.cache.close)
        self.sources = Sources(self.cache, self.world, sleep=self.clock.sleep, clock=self.clock)

    def test_an_artist_is_taken_only_when_exactly_one_of_that_exact_name_scores_nearly_perfectly(self):
        self.world.mb_artists["Gojira"] = [{"id": "fr", "name": "Gojira", "score": 100}, {"id": "ca", "name": "Gojira", "score": 80}]
        self.assertEqual(self.sources.musicbrainz_artist("Gojira"), "fr")

    def test_two_equally_good_artists_with_one_name_are_never_guessed_between(self):
        self.world.mb_artists["Nirvana"] = [{"id": "us", "name": "Nirvana", "score": 100}, {"id": "uk", "name": "Nirvana", "score": 98}]
        self.assertIsNone(self.sources.musicbrainz_artist("Nirvana"))

    def test_a_similar_name_is_not_the_same_artist(self):
        self.world.mb_artists["Tool"] = [{"id": "x", "name": "Tools", "score": 100}]
        self.assertIsNone(self.sources.musicbrainz_artist("Tool"))
        self.world.mb_artists["Opeth"] = [{"id": "y", "name": "Opeth", "score": 70}]
        self.assertIsNone(self.sources.musicbrainz_artist("Opeth"), "a weak score is not an answer")

    def test_a_second_question_about_the_same_artist_is_answered_from_memory(self):
        self.world.mb_artists["Gojira"] = [{"id": "fr", "name": "Gojira", "score": 100}]
        self.sources.musicbrainz_artist("Gojira")
        self.sources.musicbrainz_artist("GOJIRA")
        self.assertEqual(len(self.world.calls), 1)

    def test_an_artist_the_catalogue_does_not_know_is_remembered_as_unknown(self):
        self.assertIsNone(self.sources.musicbrainz_artist("Nobody At All"))
        self.assertIsNone(self.sources.musicbrainz_artist("Nobody At All"))
        self.assertEqual(len(self.world.calls), 1, "not asked again every night")

    def test_the_services_rules_are_followed_one_call_a_second_for_musicbrainz(self):
        for name in ("A", "B", "C"):
            self.sources.musicbrainz_artist(name)
        self.assertGreaterEqual(sum(self.clock.slept), 2.0)

    def test_similar_artists_come_with_their_scores_and_use_the_current_algorithm(self):
        self.world.similar["mb-opeth"] = [{"artist_mbid": "mb-pt", "name": "Porcupine Tree", "score": 2652, "type": "Group"},
                                          {"artist_mbid": "mb-dt", "name": "Dream Theater", "score": 2643}, {"name": "no id"}]
        found = self.sources.similar_artists("mb-opeth")
        self.assertEqual(found, [{"mbid": "mb-pt", "name": "Porcupine Tree", "score": 2652.0},
                                 {"mbid": "mb-dt", "name": "Dream Theater", "score": 2643.0}])
        self.assertIn(SIMILAR_ALGORITHM, self.world.calls[0])

    def test_the_best_known_artist_of_the_exact_name_is_the_one_on_deezer(self):
        self.world.deezer_artists["Porcupine Tree"] = [{"id": 1, "name": "Porcupine Tree", "nb_fan": 54}, {"id": 4069, "name": "Porcupine Tree", "nb_fan": 144351},
                                                       {"id": 2, "name": "Porcupine Tree Tribute", "nb_fan": 9999999}]
        self.assertEqual(self.sources.deezer_artist("Porcupine Tree"), 4069)

    def test_top_songs_are_plain_title_artist_album_length_and_how_played(self):
        self.world.artist("Opeth", "mb-opeth", [], deezer_id=7, songs=["Bleak", "Windowpane"])
        top = self.sources.deezer_top(7)
        self.assertEqual([(t["title"], t["artist"], t["album"]) for t in top], [("Bleak", "Opeth", "Opeth album"), ("Windowpane", "Opeth", "Opeth album")])
        self.assertGreater(top[0]["rank"], top[1]["rank"])

    def test_fresh_releases_are_the_ones_on_or_after_a_date_newest_first(self):
        self.world.releases["mb-opeth"] = [
            {"id": "a", "title": "Old", "first-release-date": "2019-09-27", "primary-type": "Album"},
            {"id": "b", "title": "New", "first-release-date": "2026-10-01", "primary-type": "Album"},
            {"id": "c", "title": "Newer EP", "first-release-date": "2026-10-08", "primary-type": "EP"},
            {"id": "d", "title": "No exact date", "first-release-date": "2026", "primary-type": "Album"}]
        got = self.sources.fresh_releases("mb-opeth", "2026-09-15")
        self.assertEqual([(g["title"], g["type"]) for g in got], [("Newer EP", "ep"), ("New", "album")])

    def test_a_service_that_is_busy_for_a_moment_is_asked_again_after_a_wait_and_the_build_goes_on(self):
        self.world.mb_artists["Gojira"] = [{"id": "fr", "name": "Gojira", "score": 100}]
        self.world.fail_first = 2
        self.assertEqual(self.sources.musicbrainz_artist("Gojira"), "fr")
        self.assertEqual(len(self.world.calls), 3)
        self.assertGreaterEqual(sum(self.clock.slept), 5.0 + 15.0, "it waited before asking again")

    def test_a_service_that_stays_busy_ends_the_build_after_a_few_tries_not_at_the_first_no(self):
        self.world.fail_with = 503
        with self.assertRaises(Throttled):
            self.sources.musicbrainz_artist("Gojira")
        self.assertEqual(len(self.world.calls), 4)

    def test_a_clear_refusal_is_not_asked_again(self):
        self.world.fail_with = 403
        with self.assertRaises(Throttled):
            self.sources.musicbrainz_artist("Gojira")
        self.assertEqual(len(self.world.calls), 1)

    def test_a_service_that_does_not_answer_or_says_slow_down_stops_the_build_and_remembers_nothing(self):
        for status in (0, 429, 503):
            self.world.fail_with = status
            with self.assertRaises(Throttled):
                self.sources.musicbrainz_artist("Opeth")
        self.world.fail_with = None
        self.world.mb_artists["Opeth"] = [{"id": "o", "name": "Opeth", "score": 100}]
        self.assertEqual(self.sources.musicbrainz_artist("Opeth"), "o", "the failure was not cached as 'unknown'")

    def test_nothing_about_a_person_is_in_any_request(self):
        self.world.artist("Opeth", "mb-opeth", [("mb-pt", "Porcupine Tree", 1)], deezer_id=7, songs=["Bleak"])
        self.sources.musicbrainz_artist("Opeth")
        self.sources.similar_artists("mb-opeth")
        self.sources.deezer_artist("Opeth")
        self.sources.deezer_top(7)
        asked = " ".join(self.world.calls).lower()
        for private in ("sam", "mia", "owner", "password", "token", "listener"):
            self.assertNotIn(private, asked)


if __name__ == "__main__":
    unittest.main()
