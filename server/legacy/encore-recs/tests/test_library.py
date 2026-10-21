"""What a person plays and likes, read from a private copy of the music server's database (docs/47 section 3; S9)."""
import tempfile
import unittest
from pathlib import Path

from encore_recs.library import LibraryUnavailable, open_snapshot

from tests.fakes import MusicDb


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name) / "navidrome"
        self.folder.mkdir()
        self.scratch = Path(self._tmp.name) / "scratch"
        self.scratch.mkdir()
        self.db = MusicDb(self.folder)
        self.addCleanup(self.db.close)
        self.db.person("sam")
        self.db.person("mia")
        self.now = 1_760_000_000.0  # 2025-10-09

    def read(self, person="sam", limit=40):
        with open_snapshot(self.folder, self.scratch) as reader:
            return reader.seeds(person, self.now, limit)

    def test_what_is_still_only_in_the_servers_log_is_read_too(self):
        # the music server keeps its newest changes in a write-ahead log beside the file: a copy of the file alone would miss them
        song = self.db.song("Opeth", "Bleak")
        self.db.play("sam", song, plays=4)
        self.assertTrue((self.folder / "navidrome.db-wal").stat().st_size > 0)
        self.assertEqual([s.artist for s in self.read()], ["Opeth"])

    def test_a_star_counts_three_plays_and_a_song_played_lately_counts_double_again(self):
        old = self.db.song("Tool", "Sober")
        self.db.play("sam", old, plays=3, when="2020-01-01 00:00:00+00:00")
        starred = self.db.song("Gojira", "Silvera")
        self.db.play("sam", starred, plays=0, starred=True, when=None)
        recent = self.db.song("Mastodon", "Blood and Thunder")
        self.db.play("sam", recent, plays=1, when="2025-10-01 00:00:00+00:00")
        weights = {s.artist: s.weight for s in self.read()}
        self.assertEqual(weights, {"Tool": 3.0, "Gojira": 3.0, "Mastodon": 3.0})
        self.assertEqual([s.stars for s in self.read() if s.artist == "Gojira"], [1])

    def test_the_strongest_artist_comes_first_and_the_list_is_capped(self):
        for n in range(10):
            song = self.db.song(f"Artist {n}", "Song")
            self.db.play("sam", song, plays=n + 1, when="2020-01-01 00:00:00+00:00")
        seeds = self.read(limit=3)
        self.assertEqual([s.artist for s in seeds], ["Artist 9", "Artist 8", "Artist 7"])

    def test_each_person_is_read_on_their_own_and_never_mixed_with_anybody_elses(self):
        self.db.play("sam", self.db.song("Opeth", "Bleak"), plays=5)
        self.db.play("mia", self.db.song("Abba", "Waterloo"), plays=5)
        self.assertEqual([s.artist for s in self.read("sam")], ["Opeth"])
        self.assertEqual([s.artist for s in self.read("mia")], ["Abba"])
        self.assertEqual(self.read("nobody"), [])
        self.assertEqual([s.artist for s in self.read("SAM")], ["Opeth"], "names are not case sensitive")

    def test_a_song_whose_file_is_gone_does_not_count(self):
        gone = self.db.song("Gone", "Away", missing=True)
        self.db.play("sam", gone, plays=9, starred=True)
        self.assertEqual(self.read(), [])

    def test_songs_only_listed_not_played_or_liked_do_not_count(self):
        self.db.song("Unplayed", "Song")
        self.db.play("sam", self.db.song("Zero", "Song"), plays=0, starred=False)
        self.assertEqual(self.read(), [])

    def test_the_album_artist_is_the_artist_and_a_tagged_id_is_kept(self):
        a = self.db.song("Guest Singer", "Duet", album_artist="Main Band", mbid="mb-main")
        b = self.db.song("Main Band", "Solo", mbid="mb-main")
        self.db.play("sam", a, plays=2)
        self.db.play("sam", b, plays=2)
        seeds = self.read()
        self.assertEqual([(s.artist, s.mbid, s.plays) for s in seeds], [("Main Band", "mb-main", 4)])

    def test_the_whole_library_is_known_so_recommendations_can_be_new_to_it(self):
        self.db.song("Opeth", "Bleak", mbid="mb-opeth")
        self.db.song("Opeth", "Windowpane")
        self.db.song("Gone", "Away", missing=True)
        with open_snapshot(self.folder, self.scratch) as reader:
            library = reader.library()
        self.assertTrue(library.has_artist("OPETH"))
        self.assertTrue(library.has_artist("Somebody Else", "mb-opeth"))
        self.assertFalse(library.has_artist("Gone"))
        self.assertTrue(library.has_song("Opeth", "Bleak (Remastered 2011)"))
        self.assertFalse(library.has_song("Opeth", "Ghost of Perdition"))

    def test_the_copy_is_deleted_and_the_live_file_is_never_touched(self):
        before = (self.folder / "navidrome.db").stat().st_mtime_ns
        with open_snapshot(self.folder, self.scratch) as reader:
            reader.people()
            self.assertTrue(any(self.scratch.iterdir()), "a private copy exists while it is read")
        self.assertEqual(list(self.scratch.iterdir()), [], "and is gone after")
        self.assertEqual((self.folder / "navidrome.db").stat().st_mtime_ns, before)

    def test_a_missing_or_foreign_database_is_said_not_crashed_over(self):
        with self.assertRaises(LibraryUnavailable):
            with open_snapshot(Path(self._tmp.name) / "nowhere", self.scratch):
                pass
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        (other / "navidrome.db").write_bytes(b"this is not a database at all, not even close, just text" * 20)
        with self.assertRaises(LibraryUnavailable):
            with open_snapshot(other, self.scratch):
                pass
        self.assertEqual(list(self.scratch.iterdir()), [], "nothing left behind after a failure")

    def test_people_are_listed(self):
        with open_snapshot(self.folder, self.scratch) as reader:
            self.assertEqual(reader.people(), ["mia", "sam"])


if __name__ == "__main__":
    unittest.main()
