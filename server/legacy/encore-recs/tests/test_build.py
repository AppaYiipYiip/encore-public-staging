"""One person's lists, as they would see them (docs/47 sections 1 and 1b): new to them, never repeated, never a thing they said no to."""
import unittest

from encore_recs.build import MIN_TOTAL_WEIGHT, Hidden, build
from encore_recs.cache import Cache
from encore_recs.library import Library, Seed
from encore_recs.sources import Sources, Throttled
from encore_recs.textnorm import norm_artist, norm_title

from tests.fakes import FakeWorld

NOW = 1_760_000_000.0  # 2025-10-09


def library(artists=(), songs=()):
    titles: dict[str, set[str]] = {}
    for artist, title in songs:
        titles.setdefault(norm_artist(artist), set()).add(norm_title(title))
    return Library({norm_artist(a) for a in artists} | set(titles), set(), titles)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld()
        cache = Cache(":memory:")
        self.addCleanup(cache.close)
        self.sources = Sources(cache, self.world, sleep=lambda s: None)
        # Opeth's listeners also listen to Porcupine Tree, Dream Theater, Tool and Katatonia; Tool's to A Perfect Circle and Puscifer
        self.world.artist("Opeth", "mb-opeth", [("mb-pt", "Porcupine Tree", 2652), ("mb-dt", "Dream Theater", 2600), ("mb-tool", "Tool", 2400),
                                                ("mb-kat", "Katatonia", 2000)], deezer_id=1, songs=["Bleak", "Windowpane", "Ghost of Perdition", "Deliverance"])
        self.world.artist("Tool", "mb-tool", [("mb-apc", "A Perfect Circle", 3000), ("mb-pt", "Porcupine Tree", 1500), ("mb-pus", "Puscifer", 1200),
                                              ("mb-opeth", "Opeth", 1000)], deezer_id=2, songs=["Schism", "Sober", "Forty Six & 2"])
        self.world.artist("Porcupine Tree", "mb-pt", [], deezer_id=3, songs=["Blackest Eyes", "Trains", "Lazarus", "Arriving Somewhere"])
        self.world.artist("Dream Theater", "mb-dt", [], deezer_id=4, songs=["Pull Me Under", "Metropolis", "Octavarium"])
        self.world.artist("Katatonia", "mb-kat", [], deezer_id=5, songs=["Leaders", "July"])
        self.world.artist("A Perfect Circle", "mb-apc", [], deezer_id=6, songs=["Judith", "3 Libras", "The Outsider"])
        self.world.artist("Puscifer", "mb-pus", [], deezer_id=7, songs=["Momma Sed"])
        self.seeds = [Seed("Opeth", "mb-opeth", 30.0, 4, 18), Seed("Tool", "", 20.0, 2, 14)]

    def make(self, seeds=None, lib=None, hidden=None, seen=None, person="sam", now=NOW):
        return build(person, self.seeds if seeds is None else seeds, lib or library(), self.sources, hidden or Hidden(), seen or set(), now)

    def row(self, result, row_id):
        return next((r for r in result.rows if r["id"] == row_id), None)

    def test_a_person_who_has_barely_listened_is_told_to_play_a_few_songs_not_given_a_random_list(self):
        result = self.make(seeds=[Seed("Opeth", "mb-opeth", MIN_TOTAL_WEIGHT - 1, 0, 3)])
        self.assertEqual((result.state, result.rows, result.pool), ("empty", [], []))
        self.assertEqual(self.world.calls, [], "no point asking anybody")

    def test_made_for_you_is_new_music_by_artists_like_the_ones_they_play(self):
        made = self.row(self.make(), "made-for-you")["items"]
        artists = {s["artist"] for s in made}
        self.assertTrue({"Porcupine Tree", "A Perfect Circle", "Dream Theater"} <= artists)
        self.assertFalse(artists & {"Opeth", "Tool"}, "not the artists they already play")

    def test_every_suggestion_says_why_naming_the_artists_that_led_to_it(self):
        made = self.row(self.make(), "made-for-you")["items"]
        by_artist = {s["artist"]: s["reason"] for s in made}
        self.assertEqual(by_artist["Porcupine Tree"], "Because you play Opeth and Tool")
        self.assertEqual(by_artist["A Perfect Circle"], "Because you play Tool")
        self.assertEqual(by_artist["Dream Theater"], "Because you play Opeth")

    def test_an_artist_the_library_already_holds_is_not_a_discovery(self):
        made = self.row(self.make(lib=library(artists=["Porcupine Tree"])), "made-for-you")["items"]
        self.assertNotIn("Porcupine Tree", {s["artist"] for s in made})

    def test_no_more_than_three_songs_by_one_artist_and_never_two_in_a_row(self):
        made = self.row(self.make(), "made-for-you")["items"]
        counts = {}
        for s in made:
            counts[s["artist"]] = counts.get(s["artist"], 0) + 1
        self.assertLessEqual(max(counts.values()), 3)
        self.assertTrue(all(a["artist"] != b["artist"] for a, b in zip(made, made[1:])), [s["artist"] for s in made])

    def test_an_artist_with_even_one_song_in_the_library_is_not_a_discovery(self):
        made = self.row(self.make(lib=library(songs=[("Porcupine Tree", "Blackest Eyes (Remastered)")])), "made-for-you")["items"]
        self.assertNotIn("Porcupine Tree", {s["artist"] for s in made})

    def test_what_a_person_said_not_for_me_to_is_gone_from_every_list(self):
        hidden = Hidden(artists={norm_artist("Dream Theater")}, songs={(norm_artist("Porcupine Tree"), norm_title("Trains"))})
        result = self.make(hidden=hidden)
        everything = str(result.rows) + str(result.pool)
        self.assertNotIn("Dream Theater", everything)
        self.assertNotIn("'Trains'", everything)
        self.assertIn("Blackest Eyes", everything)

    def test_because_you_play_rows_carry_the_best_neighbours_with_a_song_each(self):
        row = self.row(self.make(), "because-opeth")
        self.assertEqual(row["title"], "Because you play Opeth")
        self.assertEqual(row["kind"], "artists")
        self.assertGreaterEqual(len(row["items"]), 3)
        first = row["items"][0]
        self.assertEqual(first["artist"], "Porcupine Tree")
        self.assertEqual(first["topSong"]["title"], "Blackest Eyes")

    def test_the_because_rows_do_not_repeat_each_other_each_uses_its_own_neighbours(self):
        self.world.similar["mb-tool"] += [{"artist_mbid": "mb-ps", "name": "Pain of Salvation", "score": 900},
                                          {"artist_mbid": "mb-nin", "name": "Nine Inch Nails", "score": 800}]
        self.world.artist("Pain of Salvation", "mb-ps", [], deezer_id=20, songs=["Linoleum"])
        self.world.artist("Nine Inch Nails", "mb-nin", [], deezer_id=21, songs=["Closer"])
        result = self.make()
        rows = [r for r in result.rows if r["kind"] == "artists"]
        self.assertEqual([r["id"] for r in rows], ["because-opeth", "because-tool"])
        seen = [i["artist"] for r in rows for i in r["items"]]
        self.assertEqual(len(seen), len(set(seen)), "an artist is in one row only")
        self.assertEqual(rows[0]["items"][0]["artist"], "Porcupine Tree", "Opeth's row starts with Opeth's own best neighbour")
        self.assertEqual(rows[1]["items"][0]["artist"], "A Perfect Circle", "Tool's row starts with Tool's own best neighbour")

    def test_deeper_cuts_are_songs_of_artists_they_love_that_they_do_not_have_yet(self):
        row = self.row(self.make(lib=library(songs=[("Opeth", "Bleak"), ("Opeth", "Windowpane")])), "deeper-cuts")
        opeth = [s["title"] for s in row["items"] if s["artist"] == "Opeth"]
        self.assertEqual(opeth, ["Ghost of Perdition", "Deliverance"])
        self.assertIn("More from Opeth", row["items"][0]["reason"])

    def test_new_releases_are_told_once(self):
        self.world.releases["mb-opeth"] = [{"id": "rg1", "title": "The Last Will", "first-release-date": "2025-10-01", "primary-type": "Album"},
                                           {"id": "rg0", "title": "Ancient", "first-release-date": "2024-01-01", "primary-type": "Album"}]
        first = self.make()
        row = self.row(first, "new-releases")
        self.assertEqual([(r["artist"], r["title"], r["isNew"]) for r in row["items"]], [("Opeth", "The Last Will", True)])
        again = self.row(self.make(seen=first.releases_seen), "new-releases")
        self.assertEqual([r["isNew"] for r in again["items"]], [False], "still shown for a while, but no longer news")

    def test_no_row_for_what_does_not_exist(self):
        ids = [r["id"] for r in self.make().rows]
        self.assertNotIn("new-releases", ids)
        self.assertIn("made-for-you", ids)

    def test_the_pool_for_smart_shuffle_is_songs_from_the_neighbours_two_per_artist(self):
        pool = self.make().pool
        self.assertTrue(8 <= len(pool) <= 100, len(pool))
        counts = {}
        for s in pool:
            counts[s["artist"]] = counts.get(s["artist"], 0) + 1
        self.assertLessEqual(max(counts.values()), 2)
        self.assertTrue(all(s["reason"].startswith("Because you play") for s in pool))

    def test_the_same_person_on_the_same_day_gets_the_same_lists_and_another_person_does_not_share_them(self):
        a, b = self.make(), self.make()
        self.assertEqual((a.rows, a.pool), (b.rows, b.pool))
        mia = self.make(seeds=[Seed("Katatonia", "mb-kat", 40.0, 5, 30)], person="mia")
        self.assertNotEqual(a.rows, mia.rows)

    def test_two_people_with_opposite_tastes_get_nothing_in_common_by_construction(self):
        self.world.artist("Abba", "mb-abba", [("mb-roxette", "Roxette", 100), ("mb-bj", "Bjorn Again", 90), ("mb-ace", "Ace of Base", 80)],
                          deezer_id=10, songs=["Waterloo"])
        self.world.artist("Roxette", "mb-roxette", [], deezer_id=11, songs=["Listen to Your Heart"])
        self.world.artist("Bjorn Again", "mb-bj", [], deezer_id=12, songs=["Dancing Queen Tribute"])
        self.world.artist("Ace of Base", "mb-ace", [], deezer_id=13, songs=["The Sign"])
        pop = self.make(seeds=[Seed("Abba", "mb-abba", 40.0, 5, 30)], person="mia")
        metal = self.make()
        self.assertFalse({s["artist"] for s in self.row(pop, "made-for-you")["items"]} & {s["artist"] for s in self.row(metal, "made-for-you")["items"]})

    def test_a_service_that_says_slow_down_stops_the_build_instead_of_giving_a_half_list(self):
        self.world.fail_with = 429
        with self.assertRaises(Throttled):
            self.make(seeds=[Seed("Unknown Seed", "", 50.0, 5, 40)])

    def test_a_seed_the_catalogue_cannot_name_for_certain_is_skipped_and_the_rest_still_work(self):
        self.world.mb_artists["Mystery"] = [{"id": "a", "name": "Mystery", "score": 100}, {"id": "b", "name": "Mystery", "score": 99}]
        result = self.make(seeds=self.seeds + [Seed("Mystery", "", 15.0, 1, 12)])
        self.assertEqual(result.state, "ready")
        self.assertIsNotNone(self.row(result, "made-for-you"))

    def test_an_artist_deezer_does_not_know_gives_no_song_but_does_not_break_the_list(self):
        self.world.deezer_artists.pop("Dream Theater")
        made = self.row(self.make(), "made-for-you")["items"]
        self.assertNotIn("Dream Theater", {s["artist"] for s in made})
        self.assertIn("Porcupine Tree", {s["artist"] for s in made})

    def test_nothing_private_goes_to_the_public_services(self):
        self.make()
        asked = " ".join(self.world.calls).lower()
        for private in ("sam", "password", "token"):
            self.assertNotIn(private, asked)


if __name__ == "__main__":
    unittest.main()
