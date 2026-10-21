"""A playlist gives a title and an artist; the library needs an album, a cover, a number and a year (the owner,
2026-10-18: "importing a song would mean its icon is replaced by a letter?"). What is looked up must be the same
recording or nothing at all."""
import tempfile
import unittest
from pathlib import Path

from encore_fetch.catalogue import Deezer, Meta, pick
from encore_fetch.jobs import JobManager, Request

from tests.test_pipeline import AUTH, FakeDownloader, FakeNavidrome, FakeSearcher, GOOD, InlineExecutor


def hit(title, artist, album, duration, rank=500000, tid=1):
    return {"id": tid, "title": title, "duration": duration, "rank": rank,
            "artist": {"name": artist}, "album": {"title": album, "cover_xl": f"https://cdn-images.dzcdn.net/{tid}.jpg"}}


HARVEST = [
    hit("Harvest (Live)", "Opeth", "In Live Concert at the Royal Albert Hall", 370, tid=2),
    hit("Harvest", "Opeth", "Blackwater Park", 361, tid=1),
    hit("Stjernesludd", "Trine Hartz", "Stjernesludd", 226, tid=3),
]


class PickTest(unittest.TestCase):
    def test_the_studio_song_by_that_artist_is_chosen_over_a_live_one_and_a_stranger(self):
        self.assertEqual(pick(HARVEST, "Opeth", "Harvest", 359)["id"], 1)

    def test_a_live_recording_is_chosen_only_when_it_was_asked_for(self):
        self.assertEqual(pick(HARVEST, "Opeth", "Harvest (Live)", 370)["id"], 2)

    def test_a_song_of_another_length_is_not_the_same_recording(self):
        # an extended mix or a different take: no answer is better than the wrong album
        self.assertIsNone(pick(HARVEST, "Opeth", "Harvest", 200))
        self.assertEqual(pick(HARVEST, "Opeth", "Harvest", None)["id"], 1, "length unknown: the name decides")

    def test_a_different_artist_with_the_same_title_is_not_chosen(self):
        self.assertIsNone(pick([hit("Harvest", "Neil Young", "Harvest", 183)], "Opeth", "Harvest", 183))

    def test_a_remaster_mark_and_a_featured_artist_do_not_hide_the_song(self):
        found = pick([hit("Windowpane - Remastered 2008", "Opeth", "Damnation", 464)], "Opeth", "Windowpane (feat. X)", 467)
        self.assertEqual(found["album"]["title"], "Damnation")

    def test_a_studio_album_comes_before_a_greatest_hits(self):
        both = [hit("Burden", "Opeth", "Greatest Hits", 462, rank=900000, tid=5),
                hit("Burden", "Opeth", "Watershed", 462, rank=100, tid=6)]
        self.assertEqual(pick(both, "Opeth", "Burden", 462)["id"], 6)

    def test_nonsense_in_the_answer_is_not_a_crash(self):
        self.assertIsNone(pick([None, {}, {"title": 5, "artist": 7}, {"title": "Harvest"}], "Opeth", "Harvest", 361))


class LookupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "meta.json"
        self.asked = []
        self.now = 1_000_000.0

    def http(self, url):
        self.asked.append(url)
        if "/search/" in url:
            return {"data": HARVEST}
        return {"track_position": 5, "disk_number": 1, "release_date": "2001-03-12"}

    def deezer(self, **kw):
        return Deezer(self.path, http=kw.get("http", self.http), clock=lambda: self.now)

    def test_it_answers_with_the_album_the_cover_the_number_and_the_year(self):
        meta = self.deezer().lookup("Opeth", "Harvest", 361)
        self.assertEqual(meta, Meta(album="Blackwater Park", cover_url="https://cdn-images.dzcdn.net/1.jpg",
                                    track=5, disc=1, year=2001))

    def test_a_song_is_asked_about_once_and_remembered_across_restarts(self):
        self.deezer().lookup("Opeth", "Harvest", 361)
        count = len(self.asked)
        again = self.deezer().lookup("Opeth", "Harvest", 361)
        self.assertEqual(len(self.asked), count)
        self.assertEqual(again.album, "Blackwater Park")

    def test_nothing_found_is_remembered_for_a_short_while_only(self):
        d = self.deezer(http=lambda url: {"data": []})
        self.assertIsNone(d.lookup("Nobody", "Nothing", 100))
        self.now += 3600
        self.assertIsNone(self.deezer(http=lambda url: self.fail("asked again too soon")).lookup("Nobody", "Nothing", 100))
        self.now += 3 * 86400
        self.assertIsNone(d.lookup("Nobody", "Nothing", 100))

    def test_a_catalogue_that_is_down_is_no_answer_and_is_not_remembered(self):
        def down(url):
            raise OSError("no route")

        self.assertIsNone(self.deezer(http=down).lookup("Opeth", "Harvest", 361))
        self.assertEqual(self.deezer().lookup("Opeth", "Harvest", 361).album, "Blackwater Park")

    def test_without_the_track_detail_the_album_and_cover_still_come(self):
        def partial(url):
            if "/search/" in url:
                return {"data": HARVEST}
            raise OSError("detail failed")

        meta = self.deezer(http=partial).lookup("Opeth", "Harvest", 361)
        self.assertEqual((meta.album, meta.track, meta.year), ("Blackwater Park", None, None))
        self.assertIsNotNone(meta.cover_url)

    def test_a_damaged_cache_file_is_ignored(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.deezer().lookup("Opeth", "Harvest", 361).album, "Blackwater Park")


class SongsGetTheirAlbumTest(unittest.TestCase):
    """The pipeline fills what a playlist did not say, never replacing what the caller knew."""

    def make(self, enricher):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "music").mkdir()
        self.tagged = []
        self.covers = []
        return JobManager(
            music_dir=root / "music", work_dir=root / "work", resolver=FakeSearcher([GOOD]),
            downloader=FakeDownloader(), navidrome=FakeNavidrome(), executor=InlineExecutor(),
            indexer=InlineExecutor(), cover=lambda url: (self.covers.append(url), b"JPEG")[1],
            tagger=lambda path, tags, cover: (self.tagged.append((tags, cover)), True)[1],
            sleep=lambda s: None, min_free_gb=0, enricher=enricher)

    def test_an_imported_song_gets_the_real_album_cover_number_and_year(self):
        manager = self.make(lambda artist, title, dur: Meta("Damnation", "https://cdn-images.dzcdn.net/9.jpg", 5, 1, 2003))
        job = manager.submit(AUTH, Request(artist="Opeth", title="Windowpane", duration_s=467))

        self.assertEqual(job.state, "ready", job.view())
        tags, cover = self.tagged[0]
        self.assertEqual((tags.album, tags.track, tags.disc, tags.year), ("Damnation", 5, 1, 2003))
        self.assertEqual(cover, b"JPEG")
        self.assertEqual(self.covers, ["https://cdn-images.dzcdn.net/9.jpg"])
        self.assertIn("Damnation", job.path, "it is filed under its album, not as a single named after itself")

    def test_what_the_caller_already_knew_is_kept(self):
        manager = self.make(lambda artist, title, dur: Meta("Other Album", "https://cdn-images.dzcdn.net/9.jpg", 9, 1, 1999))
        manager.submit(AUTH, Request(artist="Opeth", title="Windowpane", album="Damnation", track=5,
                                     cover_url="https://cdn-images.dzcdn.net/mine.jpg", year=2003))
        tags, _ = self.tagged[0]
        self.assertEqual((tags.album, tags.track, tags.year), ("Damnation", 5, 2003))
        self.assertEqual(self.covers, ["https://cdn-images.dzcdn.net/mine.jpg"])

    def test_a_catalogue_with_nothing_to_say_leaves_the_song_a_single(self):
        manager = self.make(lambda artist, title, dur: None)
        job = manager.submit(AUTH, Request(artist="Opeth", title="Windowpane"))
        self.assertEqual(job.state, "ready")
        self.assertEqual(self.tagged[0][0].album, "Windowpane")

    def test_a_song_the_catalogue_does_not_know_gets_the_pictures_of_its_video(self):
        manager = self.make(lambda artist, title, dur: None)
        job = manager.submit(AUTH, Request(artist="Opeth", title="Windowpane"))
        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(self.covers, ["https://i.ytimg.com/vi/vid12345678/maxresdefault.jpg"])
        self.assertEqual(self.tagged[0][1], b"JPEG")

    def test_the_catalogue_cover_comes_first_and_the_video_is_only_the_fallback(self):
        manager = self.make(lambda artist, title, dur: Meta("Damnation", "https://cdn-images.dzcdn.net/9.jpg"))
        manager.submit(AUTH, Request(artist="Opeth", title="Windowpane"))
        self.assertEqual(self.covers, ["https://cdn-images.dzcdn.net/9.jpg"], "found at once: nothing else is asked")

    def test_a_video_without_a_big_picture_falls_back_to_the_next_size_then_to_none(self):
        manager = self.make(lambda artist, title, dur: None)
        pictures = {"hq720": b"SMALL"}
        manager._cover = lambda url: (self.covers.append(url), next((b for k, b in pictures.items() if k in url), None))[1]
        manager.submit(AUTH, Request(artist="Opeth", title="Windowpane"))
        self.assertEqual([u.rsplit("/", 1)[1] for u in self.covers], ["maxresdefault.jpg", "hq720.jpg"])
        self.assertEqual(self.tagged[0][1], b"SMALL")

        pictures.clear()
        self.covers.clear()
        job = manager.submit(AUTH, Request(artist="Opeth", title="Another one"))
        self.assertEqual(job.state, "ready", "no picture at all is still a song")
        self.assertIsNone(self.tagged[-1][1])

    def test_a_catalogue_that_breaks_never_fails_the_song(self):
        def broken(artist, title, dur):
            raise RuntimeError("boom")

        job = self.make(broken).submit(AUTH, Request(artist="Opeth", title="Windowpane"))
        self.assertEqual(job.state, "ready", job.view())

    def test_no_lookup_is_made_when_the_caller_knew_everything(self):
        asked = []
        manager = self.make(lambda artist, title, dur: asked.append(title))
        manager.submit(AUTH, Request(artist="Opeth", title="Windowpane", album="Damnation",
                                     cover_url="https://cdn-images.dzcdn.net/mine.jpg"))
        self.assertEqual(asked, [])


if __name__ == "__main__":
    unittest.main()
