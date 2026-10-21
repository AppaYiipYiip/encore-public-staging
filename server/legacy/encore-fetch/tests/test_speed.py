"""Songs that somebody already fetched are there at once for the next person (2026-10-17, `docs/39` F16).

Measured on the reference server: search 2.1 s + the streams 2.5 s + download 9.6 s for one song, on a line that carries 450 KB/s.
The line cannot be made faster; what a person waits for twice can be made to disappear."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from encore_fetch.download import DownloadError
from encore_fetch.jobs import JobManager, Request
from encore_fetch.library import PersonLayout
from encore_fetch.navidrome import Auth
from encore_fetch.resolve import Candidate

from test_pipeline import (AUTH, GOOD, FakeDownloader, FakeNavidrome,
                           FakeSearcher, InlineExecutor)

KIM = Auth("kim", "b" * 32, "salt5678")


class SpeedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.music = root / "music"
        self.work = root / "work"
        for person in ("marwa", "kim"):
            (self.music / person).mkdir(parents=True)
        self.now = 1_000_000.0
        self.tagged = []
        self.nd = FakeNavidrome()

    def manager(self, *, hits=(GOOD,), downloader=None, **kw):
        self.searcher = FakeSearcher(hits)
        self.downloader = downloader or FakeDownloader()
        return JobManager(
            music_dir=self.music, work_dir=self.work, resolver=self.searcher,
            downloader=self.downloader, navidrome=self.nd,
            executor=InlineExecutor(), indexer=InlineExecutor(),
            cover=lambda url: None,
            tagger=lambda path, tags, cover: self.tagged.append((path.name, tags.album)) or True,
            clock=lambda: self.now, sleep=lambda s: None, min_free_gb=0,
            people=PersonLayout(self.music), **kw)

    wanted = Request(artist="Opeth", title="Windowpane", album="Damnation", track=5, duration_s=467)

    def test_the_next_person_gets_the_song_without_a_search_or_a_download(self):
        m = self.manager()
        first = m.submit(AUTH, self.wanted)
        second = m.submit(KIM, self.wanted)

        self.assertEqual((first.state, second.state), ("ready", "ready"), second.view())
        self.assertEqual(self.searcher.queries, ["Opeth Windowpane"], "searched once, for the first person")
        self.assertEqual(self.downloader.calls, ["vid12345678"], "downloaded once")
        self.assertEqual(self.downloader.extracted, ["vid12345678"], "the streams were asked for once")
        self.assertTrue((self.music / "kim" / second.path).is_file())

    def test_each_person_has_their_own_file_with_their_own_tags(self):
        m = self.manager()
        first = m.submit(AUTH, self.wanted)
        second = m.submit(KIM, Request(artist="Opeth", title="Windowpane", album="Best of Opeth", track=2, duration_s=467))

        mine = self.music / "marwa" / first.path
        kims = self.music / "kim" / second.path
        self.assertNotEqual(os.stat(mine).st_ino, os.stat(kims).st_ino,
                            "a copy, not a link: tagging one must not change the other's song")
        self.assertEqual([a for _, a in self.tagged], ["Damnation", "Best of Opeth"])
        self.assertTrue(first.path != second.path)

    def test_a_search_is_remembered_for_the_days_after_a_restart(self):
        self.manager().submit(AUTH, self.wanted)
        for f in (self.work / "cache").glob("*"):
            f.unlink()  # the files are gone, what was found is not

        again = self.manager()  # a new process, the same folders
        job = again.submit(KIM, self.wanted)

        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(self.searcher.queries, [], "it did not search again")
        self.assertEqual(self.downloader.calls, ["vid12345678"])

    def test_a_remembered_search_is_forgotten_after_a_month(self):
        m = self.manager()
        m.submit(AUTH, self.wanted)
        self.now += 31 * 86400

        again = self.manager()
        again.submit(KIM, self.wanted)

        self.assertEqual(self.searcher.queries, ["Opeth Windowpane"])

    def test_a_video_that_is_gone_is_searched_again_once(self):
        self.manager().submit(AUTH, self.wanted)
        for f in (self.work / "cache").glob("*"):
            f.unlink()
        newer = Candidate("newvideo1234", "Windowpane", "Opeth - Topic", 467, True)

        class Gone(FakeDownloader):
            def download(self, video_id, stem, duration_s=None, info=None):
                if video_id == "vid12345678":
                    raise DownloadError("unavailable")
                return super().download(video_id, stem, duration_s, info)

            def extract(self, video_id, info):
                if video_id == "vid12345678":
                    raise DownloadError("unavailable")
                return super().extract(video_id, info)

        m = self.manager(hits=(newer,), downloader=Gone())
        job = m.submit(KIM, self.wanted)

        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(self.searcher.queries, ["Opeth Windowpane"], "asked again, found the new upload")
        self.assertEqual(self.downloader.calls, ["newvideo1234"])

    def test_a_preparation_for_a_song_in_the_cache_asks_nothing(self):
        m = self.manager()
        m.submit(AUTH, self.wanted)
        self.downloader.extracted.clear()

        job = m.prepare(KIM, self.wanted)

        self.assertEqual(job.state, "prepared")
        self.assertEqual(self.downloader.extracted, [], "nothing to ask YouTube: the file is here")

    def test_the_cache_stays_within_its_size(self):
        m = self.manager(cache_max_mb=0)  # no room at all
        m.submit(AUTH, self.wanted)
        m.submit(KIM, self.wanted)

        self.assertEqual(self.downloader.calls, ["vid12345678", "vid12345678"], "no cache: both downloaded")
        self.assertEqual(list((self.work / "cache").glob("*.opus")), [])

    def test_the_oldest_songs_leave_first(self):
        # Room for two songs: the fake file is 10 bytes, the limit 20.
        m = self.manager(cache_max_bytes=20)
        for n, title in enumerate(("One", "Two", "Three")):
            hit = Candidate(f"vid0000000{n}", title, "Opeth - Topic", 100, True)
            m2 = self.manager(hits=(hit,), cache_max_bytes=20)
            self.now += 10
            m2.submit(AUTH, Request(artist="Opeth", title=title, duration_s=100))
        kept = sorted(p.stem for p in (self.work / "cache").glob("*.opus"))

        self.assertNotIn("vid00000000", kept, "the first one left")
        self.assertIn("vid00000002", kept, "the newest stayed")

    def test_a_missing_cache_file_is_downloaded_again(self):
        m = self.manager()
        m.submit(AUTH, self.wanted)
        for f in (self.work / "cache").glob("*.opus"):
            f.unlink()
        self.downloader.calls.clear()

        job = m.submit(KIM, self.wanted)

        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(self.downloader.calls, ["vid12345678"])

    def test_the_notes_about_a_cached_song_hold_its_codec_and_bitrate(self):
        self.manager().submit(AUTH, self.wanted)
        notes = list((self.work / "cache").glob("*.json"))

        self.assertEqual(len(notes), 1)
        data = json.loads(notes[0].read_text(encoding="utf-8"))
        self.assertEqual((data["codec"], data["kbps"]), ("opus", 158))


if __name__ == "__main__":
    unittest.main()
