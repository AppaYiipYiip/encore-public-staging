"""Pure logic: text normalisation, candidate scoring, library placement,
song matching, request parsing."""
import tempfile
import unittest
from pathlib import Path

from encore_fetch.library import (find_existing, free_gb, inside,
                                  place_file, plan_placement, track_filename,
                                  unique_path)
from encore_fetch.navidrome import pick_song
from encore_fetch.resolve import Candidate, Want, best, parse_search, score
from encore_fetch.server import BadRequest, auth_from, parse_request
from encore_fetch.textnorm import (mentions_version, norm_artist, norm_title,
                                   safe_path_part)


class TextNormTest(unittest.TestCase):
    def test_title_noise_is_removed(self):
        self.assertEqual(norm_title("Blackwater Park (Remastered 2015) [Official Audio]"),
                         "blackwater park")
        self.assertEqual(norm_title("Song feat. Someone"), "song")
        self.assertEqual(norm_title("Déjà Vu"), "deja vu")

    def test_artist_topic_suffix_goes(self):
        self.assertEqual(norm_artist("Opeth - Topic"), "opeth")
        self.assertEqual(norm_artist("OpethVEVO"), "opeth")

    def test_version_words_are_whole_words(self):
        self.assertEqual(mentions_version("Song (Live at Wembley)"), {"live"})
        self.assertEqual(mentions_version("Alive"), set())
        self.assertIn("remix", mentions_version("Song - Club Remix"))

    def test_path_parts_cannot_escape(self):
        self.assertEqual(safe_path_part("../../etc/passwd"), "-..-etc-passwd")
        self.assertEqual(safe_path_part("AC/DC"), "AC-DC")
        self.assertEqual(safe_path_part("  ..  "), "Unknown")
        self.assertEqual(safe_path_part("a\x00b\nc"), "abc")
        self.assertEqual(safe_path_part("x" * 500), "x" * 120)
        self.assertEqual(safe_path_part('What?: "Yes"'), "What-- -Yes-")


class ScoringTest(unittest.TestCase):
    want = Want("Opeth", "The Leper Affinity", "Blackwater Park", 622)

    def c(self, title, channel, dur, topic=False):
        return Candidate("abc123def45", title, channel, dur, topic)

    def test_topic_upload_with_right_length_wins(self):
        good = self.c("The Leper Affinity", "Opeth - Topic", 621, True)
        video = self.c("Opeth - The Leper Affinity (Official Video)", "OpethVEVO", 640)
        winner = best(self.want, [video, good])
        self.assertIsNotNone(winner)
        self.assertEqual(winner.candidate, good)

    def test_live_and_cover_versions_lose(self):
        live = self.c("Opeth - The Leper Affinity (Live)", "Opeth", 622)
        cover = self.c("The Leper Affinity cover", "SomeGuy", 620)
        studio = self.c("Opeth - The Leper Affinity", "Opeth", 622)
        winner = best(self.want, [live, cover, studio])
        self.assertEqual(winner.candidate, studio)

    def test_live_is_fine_when_asked_for(self):
        want = Want("Opeth", "The Leper Affinity (Live)", None, 700)
        live = self.c("Opeth - The Leper Affinity (Live)", "Opeth", 700)
        self.assertIsNotNone(best(want, [live]))

    def test_wrong_song_is_not_accepted(self):
        other = self.c("Opeth - Windowpane", "Opeth - Topic", 467, True)
        self.assertIsNone(best(self.want, [other]))

    def test_a_twenty_five_minute_song_is_not_refused_for_being_long(self):
        epic = Want("Dream Theater", "Octavarium", None, 1442)
        found = best(epic, [self.c("Dream Theater - Octavarium", "Dream Theater - Topic", 1442, True)])
        self.assertIsNotNone(found)

    def test_a_ten_hour_loop_is_not_accepted_as_a_twenty_five_minute_song(self):
        epic = Want("Dream Theater", "Octavarium", None, 1442)
        loop = self.c("Octavarium 10 HOURS", "Dream Theater - Topic", 36000, True)
        self.assertIsNone(best(epic, [loop]))

    def test_without_a_known_length_a_very_long_upload_is_still_penalised(self):
        blind = Want("Dream Theater", "Octavarium", None, None)
        loop = self.c("Dream Theater - Octavarium", "Dream Theater - Topic", 36000, True)
        self.assertIsNone(best(blind, [loop]))

    def test_a_ten_hour_loop_is_not_accepted(self):
        loop = self.c("The Leper Affinity 10 HOURS", "Opeth - Topic", 36000, True)
        self.assertIsNone(best(self.want, [loop], max_duration_s=900))

    def test_duration_decides_between_equal_titles(self):
        a = self.c("The Leper Affinity", "Opeth - Topic", 622, True)
        b = self.c("The Leper Affinity", "Opeth - Topic", 400, True)
        self.assertGreater(score(self.want, a).score, score(self.want, b).score)

    def test_parse_search_is_tolerant(self):
        data = {"entries": [
            {"id": "aaaaaaaaaaa", "title": "T", "channel": "X - Topic", "duration": 200.5},
            {"id": 5, "title": "bad"},
            {"title": "no id"},
            "junk",
            {"id": "bbbbbbbbbbb", "title": "U", "uploader": "Y"},
        ]}
        got = parse_search(data)
        self.assertEqual([c.video_id for c in got], ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        self.assertTrue(got[0].is_topic)
        self.assertEqual(got[0].duration_s, 200)
        self.assertEqual(parse_search(None), [])
        self.assertEqual(parse_search({"entries": None}), [])


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "music"
        self.root.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def test_filename_patterns_follow_the_library(self):
        self.assertEqual(track_filename("White Stains", track=7, disc=1,
                                        total_discs=1, suffix=".opus"),
                         "07 - White Stains.opus")
        self.assertEqual(track_filename("White Stains", track=7, disc=1,
                                        total_discs=2, suffix=".opus"),
                         "01-07 - White Stains.opus")
        self.assertEqual(track_filename("Loose", track=None, disc=None,
                                        total_discs=None, suffix=".m4a"),
                         "Loose.m4a")

    def test_existing_folders_are_reused_case_and_punctuation_blind(self):
        (self.root / "Opeth" / "Blackwater Park").mkdir(parents=True)
        p = plan_placement(self.root, artist="OPETH", album="blackwater park!",
                           title="The Drapery Falls", track=6)
        self.assertEqual(p.folder, self.root / "Opeth" / "Blackwater Park")
        self.assertEqual(p.filename, "06 - The Drapery Falls.opus")

    def test_new_artist_and_album_are_created_by_name(self):
        p = plan_placement(self.root, artist="Messa", album="Feast for Water",
                           title="White Stains", track=7)
        self.assertEqual(p.path,
                         self.root / "Messa" / "Feast for Water" / "07 - White Stains.opus")

    def test_no_album_goes_to_singles(self):
        p = plan_placement(self.root, artist="Messa", album=None, title="X")
        self.assertEqual(p.folder.name, "Singles")

    def test_hostile_names_stay_inside(self):
        p = plan_placement(self.root, artist="../..", album="../../etc",
                           title="../x", track=1)
        self.assertTrue(inside(self.root, p.path))

    def test_existing_song_in_any_format_is_found(self):
        folder = self.root / "Opeth" / "Blackwater Park"
        folder.mkdir(parents=True)
        (folder / "06 - The Drapery Falls.mp3").write_bytes(b"x")
        p = plan_placement(self.root, artist="Opeth", album="Blackwater Park",
                           title="The Drapery Falls", track=6)
        self.assertEqual(find_existing(p, "The Drapery Falls").name,
                         "06 - The Drapery Falls.mp3")
        self.assertIsNone(find_existing(p, "Windowpane"))

    def test_place_file_moves_and_never_overwrites(self):
        src = Path(self._tmp.name) / "work" / "a.opus"
        src.parent.mkdir()
        src.write_bytes(b"one")
        p = plan_placement(self.root, artist="A", album="B", title="C", track=1)
        first = place_file(src, p, self.root)
        self.assertEqual(first.read_bytes(), b"one")
        self.assertFalse(src.exists())
        src.write_bytes(b"two")
        second = place_file(src, p, self.root)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), b"one")
        self.assertEqual(unique_path(first).name, "01 - C (3).opus")

    def test_free_space_of_a_folder_that_does_not_exist_yet(self):
        missing = self.root / "not" / "yet"
        self.assertGreater(free_gb(missing), 0)

    def test_place_file_refuses_outside_the_library(self):
        src = Path(self._tmp.name) / "a.opus"
        src.write_bytes(b"x")
        from encore_fetch.library import Placement
        outside = Placement(Path(self._tmp.name) / "elsewhere", "x.opus")
        with self.assertRaises(ValueError):
            place_file(src, outside, self.root)


class PickSongTest(unittest.TestCase):
    songs = [
        {"id": "1", "title": "Windowpane", "artist": "Opeth", "album": "Damnation",
         "path": "Opeth/Damnation/05 - Windowpane.opus"},
        {"id": "2", "title": "Windowpane", "artist": "Opeth", "album": "Live",
         "path": "Opeth/Live/03 - Windowpane.mp3"},
        {"id": "3", "title": "Windowpane", "artist": "Other Band", "album": "X",
         "path": "Other Band/X/01 - Windowpane.mp3"},
    ]

    def test_path_is_the_surest_match(self):
        self.assertEqual(pick_song(self.songs, artist="Opeth", title="Windowpane",
                                   album=None,
                                   relative_path="Opeth/Live/03 - Windowpane.mp3"), "2")

    def test_album_breaks_a_tie(self):
        self.assertEqual(pick_song(self.songs, artist="Opeth", title="Windowpane",
                                   album="Damnation", relative_path=None), "1")

    def test_other_artists_do_not_match(self):
        self.assertIsNone(pick_song(self.songs, artist="Nobody", title="Windowpane",
                                    album=None, relative_path=None))


class RequestParsingTest(unittest.TestCase):
    def test_valid(self):
        r = parse_request({"artist": " Opeth ", "title": "Windowpane",
                           "trackNumber": 5, "durationSec": 467,
                           "coverUrl": "https://cdn-images.dzcdn.net/x.jpg"})
        self.assertEqual((r.artist, r.title, r.track, r.duration_s),
                         ("Opeth", "Windowpane", 5, 467))

    def test_rejects_missing_and_odd_values(self):
        for bad in ({}, {"artist": "A"}, {"artist": "A", "title": 5},
                    {"artist": "A", "title": "B", "trackNumber": 0},
                    {"artist": "A", "title": "B", "trackNumber": True},
                    {"artist": "A\x00", "title": "B"},
                    {"artist": "A", "title": "x" * 500}):
            with self.assertRaises(BadRequest, msg=str(bad)):
                parse_request(bad)

    def test_auth_from_query_or_headers(self):
        tok = "a" * 32
        self.assertEqual(auth_from({"u": "marwa", "t": tok, "s": "abcd1234"}, {}).user,
                         "marwa")
        self.assertEqual(auth_from({}, {"X-Encore-User": "m", "X-Encore-Token": tok,
                                        "X-Encore-Salt": "abcd"}).salt, "abcd")
        self.assertIsNone(auth_from({"u": "m", "t": "short", "s": "abcd"}, {}))
        self.assertIsNone(auth_from({"u": "../x", "t": tok, "s": "abcd"}, {}))


if __name__ == "__main__":
    unittest.main()
