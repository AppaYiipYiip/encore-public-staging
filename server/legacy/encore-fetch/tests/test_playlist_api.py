"""The playlist route (docs/39 F1, F9): a person pastes a playlist link in the app, the app asks this route for the
songs in it. Login required, rate limited, and every failure a sentence the app can show."""
import json
import tempfile
import unittest
from pathlib import Path

from encore_fetch.download import DownloadError
from encore_fetch.jobs import JobManager, Request
from encore_fetch.playlists import Playlist, PlaylistError, Track
from encore_fetch.resolve import Candidate
from encore_fetch.server import Api, parse_request

from tests.test_pipeline import (AUTH, FakeDownloader, FakeNavidrome,
                                 FakeSearcher, InlineExecutor)

LINK = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"


class PlaylistRouteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        (root / "music").mkdir()
        self.nd = FakeNavidrome()
        self.asked = []
        self.answer = Playlist(
            "Evening", "spotify", "playlist",
            (Track("Windowpane", "Opeth", duration_s=467, artists=("Opeth",)),
             Track("FN8", "Arcangel", video_id="NFvDHYMzj9U")))
        self.manager = JobManager(
            music_dir=root / "music", work_dir=root / "work",
            resolver=FakeSearcher([]), downloader=FakeDownloader(),
            navidrome=self.nd, executor=InlineExecutor(),
            indexer=InlineExecutor(), cover=lambda u: None,
            tagger=lambda p, t, c: True, sleep=lambda s: None, min_free_gb=0)
        self.api = self._api()
        self.q = "?u=marwa&t=" + "a" * 32 + "&s=salt1234"

    def _api(self, **kwargs):
        def reader(url):
            self.asked.append(url)
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

        return Api(self.manager, self.nd, playlist_reader=reader, **kwargs)

    def post(self, body, query=None, api=None):
        return (api or self.api).handle(
            "POST", "/api/playlist" + (query or self.q), {}, json.dumps(body).encode())

    def test_the_service_says_it_can_read_playlists(self):
        status, info = self.api.handle("GET", "/api/info", {})
        self.assertIn("playlist", info["features"])

    def test_it_answers_with_the_songs_in_the_form_the_app_uses(self):
        status, body = self.post({"url": LINK})

        self.assertEqual(status, 200)
        self.assertEqual(self.asked, [LINK])
        self.assertEqual((body["name"], body["source"], body["kind"], body["count"], body["truncated"]),
                         ("Evening", "spotify", "playlist", 2, False))
        self.assertEqual(body["tracks"][0], {
            "title": "Windowpane", "artist": "Opeth", "artists": ["Opeth"], "durationSec": 467})
        self.assertEqual(body["tracks"][1]["videoId"], "NFvDHYMzj9U")
        self.assertNotIn("videoId", body["tracks"][0])

    def test_it_needs_the_music_login(self):
        self.nd.valid = False
        self.assertEqual(self.post({"url": LINK})[0], 401)
        self.assertEqual(self.api.handle("POST", "/api/playlist", {}, b"{}")[0], 401)
        self.assertEqual(self.asked, [])

    def test_each_failure_is_a_sentence_and_a_word(self):
        for error, status in (("unsupported", 400), ("not_found", 404), ("unreadable", 422), ("empty", 422),
                              ("unreachable", 502)):
            self.answer = PlaylistError(error, f"sentence for {error}")
            code, body = self.post({"url": LINK})
            self.assertEqual((code, body["error"], body["message"]), (status, error, f"sentence for {error}"))

    def test_a_request_without_a_link_is_refused(self):
        for body in ({}, {"url": ""}, {"url": 5}, {"url": "x" * 600}):
            self.assertEqual(self.post(body)[0], 400, body)
        self.assertEqual(self.asked, [])

    def test_a_person_cannot_read_playlists_without_end(self):
        api = self._api(playlist_limit=3)
        for _ in range(3):
            self.assertEqual(self.post({"url": LINK}, api=api)[0], 200)
        status, body = self.post({"url": LINK}, api=api)
        self.assertEqual((status, body["error"]), (429, "rate_limited"))

    def test_a_service_with_no_reader_says_so(self):
        api = Api(self.manager, self.nd)
        status, body = api.handle("POST", "/api/playlist" + self.q, {}, b'{"url": "%s"}' % LINK.encode())
        self.assertEqual(status, 501)
        self.assertNotIn("playlist", api.handle("GET", "/api/info", {})[1]["features"])


class SavedVideoTest(unittest.TestCase):
    """A YouTube playlist points at a video. When the name finds nothing, that video is the song."""

    def make(self, hits):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "music").mkdir()
        self.downloader = FakeDownloader()
        return JobManager(
            music_dir=root / "music", work_dir=root / "work",
            resolver=FakeSearcher(hits), downloader=self.downloader,
            navidrome=FakeNavidrome(), executor=InlineExecutor(),
            indexer=InlineExecutor(), cover=lambda u: None,
            tagger=lambda p, t, c: True, sleep=lambda s: None, min_free_gb=0)

    def test_a_request_may_carry_the_video_id(self):
        request = parse_request({"artist": "Arcangel", "title": "FN8", "videoId": "NFvDHYMzj9U"})
        self.assertEqual(request.video_id, "NFvDHYMzj9U")
        for bad in ("short", "has spaces!!", "x" * 40, 7):
            with self.assertRaises(Exception):
                parse_request({"artist": "a", "title": "b", "videoId": bad})

    def test_a_tapped_song_may_say_which_official_upload_it_came_from(self):
        request = parse_request({"artist": "A", "title": "B", "videoId": "NFvDHYMzj9U", "official": True})
        self.assertTrue(request.video_first)
        # without a real video id, or when it is not literally true, it is only a name to search for
        self.assertFalse(parse_request({"artist": "A", "title": "B", "official": True}).video_first)
        self.assertFalse(parse_request({"artist": "A", "title": "B", "videoId": "NFvDHYMzj9U",
                                        "official": "yes"}).video_first)

    def test_when_the_name_finds_nothing_the_saved_video_is_downloaded(self):
        manager = self.make([])
        job = manager.submit(AUTH, Request(artist="Arcangel", title="FN8", video_id="NFvDHYMzj9U"))

        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(self.downloader.calls, ["NFvDHYMzj9U"])

    def test_without_it_a_song_nobody_finds_is_still_not_found(self):
        manager = self.make([])
        job = manager.submit(AUTH, Request(artist="Arcangel", title="FN8"))

        self.assertEqual(job.state, "failed")

    def test_a_good_match_by_name_wins_over_the_saved_video(self):
        good = Candidate("abcdefghijk", "FN8", "Arcangel - Topic", 215, True)
        manager = self.make([good])
        job = manager.submit(AUTH, Request(artist="Arcangel", title="FN8", duration_s=215,
                                           video_id="NFvDHYMzj9U"))

        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(self.downloader.calls, ["abcdefghijk"])

    def test_an_official_upload_is_used_at_once_without_searching(self):
        # YouTube Music's own "Artist - Topic" upload of the song *is* the song. Searching again took 2-12 s a song and
        # could pick a different version.
        good = Candidate("abcdefghijk", "FN8", "Arcangel - Topic", 215, True)
        manager = self.make([good])
        job = manager.submit(AUTH, Request(artist="Arcangel", title="FN8", duration_s=215,
                                           video_id="NFvDHYMzj9U", video_first=True))

        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(self.downloader.calls, ["NFvDHYMzj9U"])
        self.assertEqual(manager._resolver.queries, [], "nothing was searched")

    def test_an_official_upload_that_has_gone_is_searched_for_after_all(self):
        good = Candidate("abcdefghijk", "FN8", "Arcangel - Topic", 215, True)

        class Gone(FakeDownloader):
            def extract(self, video_id, info):
                if video_id == "NFvDHYMzj9U":
                    raise DownloadError("unavailable")
                super().extract(video_id, info)

        manager = self.make([good])
        manager._downloader = self.downloader = Gone()
        job = manager.submit(AUTH, Request(artist="Arcangel", title="FN8", duration_s=215,
                                           video_id="NFvDHYMzj9U", video_first=True))

        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(self.downloader.calls, ["abcdefghijk"])


if __name__ == "__main__":
    unittest.main()
