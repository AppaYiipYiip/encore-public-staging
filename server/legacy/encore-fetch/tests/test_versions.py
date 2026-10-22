"""Which recording is it (docs/19): the library's "Fade Into You (The Avener Rework)" is not "Fade Into You". Found on the
emulator on 2026-10-22: tapping the plain song in search played the rework, because the title comparison dropped every bracket."""
import tempfile
import unittest
from pathlib import Path

from encore_fetch.lean import Candidate, Want, title_matches
from encore_fetch.library import Placement, find_existing
from encore_fetch.navidrome import pick_song
from encore_fetch.textnorm import version_signature


class SignatureTest(unittest.TestCase):
    def test_a_plain_title_says_nothing(self):
        self.assertEqual(version_signature("Fade Into You"), frozenset())

    def test_a_rework_a_live_take_and_a_remix_say_which_they_are(self):
        self.assertEqual(version_signature("Fade Into You (The Avener Rework)"), {"avener", "rework"})
        self.assertEqual(version_signature("Song - Live at Wembley"), {"live", "at", "wembley"})
        self.assertEqual(version_signature("Song [Club Remix]"), {"club", "remix"})
        self.assertEqual(version_signature("Windowpane (Live at Shepherd's Bush Empire, London)"),
                         {"live", "at", "shepherds", "bush", "empire", "london"})

    def test_noise_is_not_a_version(self):
        for title in ("Song (feat. Someone)", "Song (Remastered 2011)", "Song - Remastered 2011", "Song [Explicit]",
                      "Song (2013 Remaster) (feat. Y)", "Song (Radio Edit)", "Song (Album Version)", "Song - Single Version",
                      "Hotel California (2013 Remaster)", "Song (Official Video)"):
            self.assertEqual(version_signature(title), frozenset(), title)

    def test_accents_and_case_do_not_matter(self):
        self.assertEqual(version_signature("Chanson (LIVE à Paris)"), version_signature("chanson (live a paris)"))


class LibraryLookupTest(unittest.TestCase):
    songs = [
        {"id": "rework", "title": "Fade Into You (The Avener Rework)", "artist": "Mazzy Star",
         "album": "The Wanderings Of The Avener"},
        {"id": "live", "title": "Fade Into You (Live)", "artist": "Mazzy Star", "album": "Live"},
    ]

    def test_the_plain_song_is_not_in_a_library_that_only_has_its_rework(self):
        self.assertIsNone(pick_song(self.songs, artist="Mazzy Star", title="Fade Into You", album=None, relative_path=None))

    def test_the_rework_is_found_when_the_rework_is_asked_for(self):
        self.assertEqual(pick_song(self.songs, artist="Mazzy Star", title="Fade Into You (The Avener Rework)", album=None,
                                   relative_path=None), "rework")

    def test_a_remaster_mark_or_a_featured_artist_is_still_the_same_song(self):
        songs = [{"id": "p", "title": "Hotel California", "artist": "Eagles", "album": "Hotel California"}]
        self.assertEqual(pick_song(songs, artist="Eagles", title="Hotel California (2013 Remaster)", album=None,
                                   relative_path=None), "p")
        songs = [{"id": "c", "title": "Instant Crush", "artist": "Daft Punk", "album": "RAM"}]
        self.assertEqual(pick_song(songs, artist="Daft Punk", title="Instant Crush (feat. Julian Casablancas)", album=None,
                                   relative_path=None), "c")

    def test_the_song_in_the_albums_folder_is_found_only_when_it_is_the_same_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "01 - Fade Into You (Live).opus").write_bytes(b"x")
            placement = Placement(folder, "01 - Fade Into You.opus")
            self.assertIsNone(find_existing(placement, "Fade Into You"))
            self.assertIsNotNone(find_existing(placement, "Fade Into You (Live)"))


class ResolverTest(unittest.TestCase):
    def candidate(self, title: str) -> Candidate:
        return Candidate(video_id="aaaaaaaaaaa", title=title, channel="Mazzy Star", duration_s=200, track=title,
                         artists=("Mazzy Star",))

    def want(self, title: str) -> Want:
        return Want(artist="Mazzy Star", title=title, album=None, duration_s=None)

    def test_a_rework_that_was_asked_for_is_not_answered_with_the_plain_song(self):
        self.assertFalse(title_matches(self.want("Fade Into You (The Avener Rework)"), self.candidate("Fade Into You")))
        self.assertTrue(title_matches(self.want("Fade Into You (The Avener Rework)"),
                                      self.candidate("Fade Into You (The Avener Rework)")))

    def test_a_plain_song_asked_for_still_matches_its_plain_upload_and_a_remaster(self):
        self.assertTrue(title_matches(self.want("Fade Into You"), self.candidate("Fade Into You")))
        self.assertTrue(title_matches(self.want("Fade Into You"), self.candidate("Fade Into You (2013 Remaster)")))


if __name__ == "__main__":
    unittest.main()
