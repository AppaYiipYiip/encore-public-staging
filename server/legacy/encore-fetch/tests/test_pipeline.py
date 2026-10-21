"""The pipeline and the HTTP routing, with a fake yt-dlp and a fake music
server: no network, no library, no clock."""
import json
import tempfile
import unittest
from concurrent.futures import Executor, Future
from pathlib import Path

from encore_fetch.download import (DownloadError, Downloaded, YtDlpDownloader,
                                   classify_failure, cover_url_ok)
from encore_fetch.jobs import JobManager, Limits, Request
from encore_fetch.navidrome import Auth, Navidrome
from encore_fetch.resolve import (Candidate, RunResult, Want, YtDlpResolver,
                                  best)
from encore_fetch.server import Api

AUTH = Auth("marwa", "a" * 32, "salt1234")


class InlineExecutor(Executor):
    """Runs the job in the caller, so a test sees the finished job."""

    def submit(self, fn, /, *args, **kwargs):
        f: Future = Future()
        try:
            f.set_result(fn(*args, **kwargs))
        except BaseException as e:  # noqa: BLE001
            f.set_exception(e)
        return f


class FakeSearcher:
    """A resolver over canned candidates (scored like the real one)."""

    def __init__(self, hits):
        self.hits = hits
        self.queries = []

    def resolve(self, want: Want):
        self.queries.append(f"{want.artist} {want.title}")
        return best(want, list(self.hits))


class FakeDownloader:
    def __init__(self, fail_with=None):
        self.fail_with = fail_with
        self.calls = []
        self.extracted = []
        self.infos = []

    def extract(self, video_id, info):
        self.extracted.append(video_id)
        if self.fail_with:
            raise DownloadError(self.fail_with)
        info.parent.mkdir(parents=True, exist_ok=True)
        info.write_text("{}", encoding="utf-8")

    def download(self, video_id, stem, duration_s=None, info=None):
        self.calls.append(video_id)
        self.infos.append(info)
        if self.fail_with:
            raise DownloadError(self.fail_with)
        stem.parent.mkdir(parents=True, exist_ok=True)
        path = stem.with_suffix(".opus")
        path.write_bytes(b"OggS-audio")
        return Downloaded(path, "opus", 158)


class FakeNavidrome(Navidrome):
    """`present` = songs the library already has; `appears_after_scan`
    controls whether a scan makes the new file visible."""

    def __init__(self, present=None, appears_after_scan=True, valid=True):
        super().__init__("http://x.invalid")
        self.present = dict(present or {})
        self.appears_after_scan = appears_after_scan
        self.valid = valid
        self.scans = 0
        self.placed = None

    def verify(self, auth):
        return self.valid

    def start_scan(self, auth):
        self.scans += 1
        return True

    def find_song(self, auth, *, artist, title, album=None, relative_path=None):
        key = (artist.lower(), title.lower())
        if key in self.present:
            return self.present[key]
        if relative_path and self.appears_after_scan and self.scans:
            return "new-song-id"
        return None


GOOD = Candidate("vid12345678", "Windowpane", "Opeth - Topic", 467, True)


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.music = Path(self._tmp.name) / "music"
        self.work = Path(self._tmp.name) / "work"
        self.music.mkdir()
        self.now = 1_000_000.0

    def manager(self, *, hits=(GOOD,), downloader=None, nd=None, tagger=None, **kw):
        self.searcher = FakeSearcher(hits)
        self.downloader = downloader or FakeDownloader()
        self.nd = nd or FakeNavidrome()
        return JobManager(
            music_dir=self.music, work_dir=self.work, resolver=self.searcher,
            downloader=self.downloader, navidrome=self.nd,
            executor=InlineExecutor(), indexer=InlineExecutor(),
            cover=lambda url: None, tagger=tagger or (lambda p, t, c: True),
            clock=lambda: self.now, sleep=self._sleep, min_free_gb=0, **kw)

    def _sleep(self, seconds):
        self.now += seconds

    req = Request(artist="Opeth", title="Windowpane", album="Damnation",
                  track=5, duration_s=467)

    def test_a_missing_song_is_fetched_placed_and_indexed(self):
        m = self.manager()
        job = m.submit(AUTH, self.req)
        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(job.song_id, "new-song-id")
        self.assertEqual(job.path, "Opeth/Damnation/05 - Windowpane.opus")
        self.assertTrue((self.music / job.path).is_file())
        self.assertEqual(self.downloader.calls, ["vid12345678"])
        self.assertEqual(self.nd.scans, 1)
        self.assertEqual(job.codec, "opus")
        self.assertIsNone(job._auth, "credentials are dropped when done")

    def test_a_song_already_in_the_library_is_ready_without_downloading(self):
        m = self.manager(nd=FakeNavidrome(present={("opeth", "windowpane"): "42"}))
        job = m.submit(AUTH, self.req)
        self.assertEqual((job.state, job.song_id), ("ready", "42"))
        self.assertEqual(self.downloader.calls, [])
        self.assertEqual(self.searcher.queries, [])

    def test_nothing_suitable_found(self):
        other = Candidate("zzzzzzzzzzz", "Totally Different", "Else", 100)
        job = self.manager(hits=(other,)).submit(AUTH, self.req)
        self.assertEqual((job.state, job.error), ("failed", "not_found"))
        self.assertIn("Could not find", job.view()["message"])
        self.assertEqual(self.downloader.calls, [])

    def test_download_errors_keep_their_reason(self):
        for code in ("blocked", "unavailable", "age_restricted"):
            m = self.manager(downloader=FakeDownloader(fail_with=code))
            job = m.submit(AUTH, Request(artist="Opeth", title=f"Windowpane {code}"))
            # the title differs so each is a new job; the candidate no
            # longer matches, so give it a matching hit
            m2 = self.manager(
                hits=(Candidate("vid12345678", f"Windowpane {code}", "Opeth - Topic", None, True),),
                downloader=FakeDownloader(fail_with=code))
            job = m2.submit(AUTH, Request(artist="Opeth", title=f"Windowpane {code}"))
            self.assertEqual((job.state, job.error), ("failed", code))

    def test_a_song_asked_for_without_an_album_is_a_single_named_after_itself(self):
        # The owner saw "[Unknown Album]" on an artist's page: two songs were fetched with no album, so the file had an empty album
        # tag and the music server shows exactly that. A song with no album is a single: its album is its own title.
        tagged = []
        m = self.manager(tagger=lambda path, tags, cover: tagged.append(tags) or True)
        job = m.submit(AUTH, Request(artist="Opeth", title="Windowpane", duration_s=467))

        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(tagged[0].album, "Windowpane")
        self.assertEqual(job.path, "Opeth/Singles/Windowpane.opus", "it still sits in the artist's Singles folder")

    def test_a_song_with_a_real_album_keeps_it(self):
        tagged = []
        m = self.manager(tagger=lambda path, tags, cover: tagged.append(tags) or True)
        m.submit(AUTH, self.req)

        self.assertEqual(tagged[0].album, "Damnation")

    def test_a_failed_job_says_why_in_the_log(self):
        # A temporary block by YouTube looked like this from the outside: a row that said "not answering", and a log with nothing in it.
        class Blocked(FakeDownloader):
            def extract(self, video_id, info):
                raise DownloadError("blocked", "ERROR: [youtube] x: Sign in to confirm you're not a bot\n"
                                               "Use --cookies-from-browser or --cookies for the authentication.")

        with self.assertLogs("encore_fetch", level="WARNING") as logs:
            job = self.manager(downloader=Blocked()).submit(AUTH, self.req)

        self.assertEqual((job.state, job.error), ("failed", "blocked"))
        (line,) = logs.output
        for expected in (job.id, "blocked", "Opeth - Windowpane", "not a bot"):
            self.assertIn(expected, line)
        self.assertNotIn("\n", line, "one line per event")
        self.assertNotIn("a" * 32, line, "never the login")

    def test_two_people_asking_for_the_same_song_each_get_their_own_job(self):
        # Found in the first real friend journey (2026-10-17): a friend asked for a song the owner's test account had asked for a few
        # minutes earlier, got the OTHER person's finished job, streamed it, and the song never reached her own library (so it could not
        # be liked or put in a playlist). A job belongs to one person: the same song asked by two people is two jobs.
        m = self.manager()
        alice = Auth("alice", "a" * 32, "salt1234")
        bob = Auth("bob", "b" * 32, "salt1234")

        first = m.submit(alice, self.req)
        second = m.submit(bob, self.req)

        self.assertNotEqual(first.id, second.id)
        self.assertEqual((first.user, second.user), ("alice", "bob"))
        self.assertEqual(m.get(first.id).user, "alice", "alice's job stays hers")

    def test_the_same_person_asking_twice_still_shares_one_job(self):
        m = self.manager()
        again = m.submit(AUTH, self.req)
        first = m.submit(AUTH, self.req)
        self.assertEqual(first.id, again.id, "one person, one song: one job, not two downloads")

    def test_a_blip_is_tried_again_before_the_person_sees_a_failure(self):
        # The owner saw "not answering" on a song. Whatever the cause, one failed try is not worth an error on the screen:
        # the server waits a moment and tries once more (the second try usually works, and the log keeps both).
        class FlakyOnce(FakeDownloader):
            asked = 0

            def extract(self, video_id, info):
                FlakyOnce.asked += 1
                if FlakyOnce.asked == 1:
                    raise DownloadError("blocked", "HTTP Error 429: Too Many Requests")
                super().extract(video_id, info)

        FlakyOnce.asked = 0
        with self.assertLogs("encore_fetch", level="INFO") as logs:
            job = self.manager(downloader=FlakyOnce()).submit(AUTH, self.req)

        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(FlakyOnce.asked, 2)
        self.assertTrue(any("trying again" in l and "429" in l for l in logs.output), logs.output)

    def test_it_waits_before_the_second_try(self):
        waited = []

        class Down(FakeDownloader):
            def extract(self, video_id, info):
                raise DownloadError("download_failed", "connection reset")

        m = self.manager(downloader=Down())
        m._sleep = lambda s: waited.append(s)
        job = m.submit(AUTH, self.req)

        self.assertEqual((job.state, job.error), ("failed", "download_failed"))
        self.assertEqual(len(waited), 1, "one pause, then one more try, then the failure is shown")
        self.assertGreaterEqual(waited[0], 3)

    def test_an_ordinary_answer_is_not_tried_again(self):
        asked = []

        class Gone(FakeDownloader):
            def extract(self, video_id, info):
                asked.append(video_id)
                raise DownloadError("unavailable", "Video unavailable")

        job = self.manager(downloader=Gone()).submit(AUTH, self.req)

        self.assertEqual((job.state, job.error), ("failed", "unavailable"))
        self.assertEqual(len(asked), 1, "a song YouTube does not have stays missing; asking twice changes nothing")

    def test_the_failure_does_not_blame_a_cause_nobody_proved(self):
        from encore_fetch.jobs import MESSAGES
        for code in ("blocked", "download_failed", "timeout"):
            self.assertNotIn("YouTube", MESSAGES[code], code)

    def test_a_song_that_is_simply_not_found_is_news_but_not_a_warning(self):
        other = Candidate("zzzzzzzzzzz", "Totally Different", "Else", 100)
        with self.assertLogs("encore_fetch", level="INFO") as logs:
            self.manager(hits=(other,)).submit(AUTH, self.req)

        failed = [l for l in logs.output if "failed" in l]
        self.assertEqual(len(failed), 1)
        self.assertIn("not_found", failed[0])
        self.assertTrue(failed[0].startswith("INFO:"), failed[0])

    def test_a_song_is_playable_even_when_the_music_server_never_lists_it(self):
        m = self.manager(nd=FakeNavidrome(appears_after_scan=False),
                         index_wait_s=6.0)
        job = m.submit(AUTH, self.req)
        self.assertEqual(job.state, "ready")
        self.assertIsNone(job.song_id)
        self.assertEqual(job.view()["stream"], f"/api/play/{job.id}/audio")
        self.assertTrue((self.music / job.path).is_file())
        self.assertGreaterEqual(self.nd.scans, 1)

    def test_indexing_can_be_switched_off_for_development(self):
        m = self.manager(skip_index=True)
        job = m.submit(AUTH, self.req)
        self.assertEqual(job.state, "ready")
        self.assertEqual(self.nd.scans, 0)
        self.assertIn("stream", job.view())

    def test_same_song_twice_by_one_person_shares_one_job(self):
        # (Two PEOPLE asking for the same song get a job each: see test_two_people_asking_for_the_same_song_each_get_their_own_job.)
        m = self.manager()
        a = m.submit(AUTH, self.req)
        b = m.submit(Auth(AUTH.user, "b" * 32, "salt9999"), self.req)  # the same person on another phone
        self.assertIs(a, b)
        self.assertEqual(self.downloader.calls, ["vid12345678"])

    def test_limits(self):
        m = self.manager(daily_limit=2)
        m.submit(AUTH, Request(artist="Opeth", title="Windowpane"))
        m.submit(AUTH, Request(artist="Opeth", title="Windowpane 2"))
        with self.assertRaises(Limits):
            m.submit(AUTH, Request(artist="Opeth", title="Windowpane 3"))

    def test_finished_jobs_are_forgotten_after_a_while(self):
        m = self.manager(keep_s=60)
        job = m.submit(AUTH, self.req)
        self.assertIs(m.get(job.id), job)
        self.now += 120
        m.submit(AUTH, Request(artist="Other", title="Thing"))
        self.assertIsNone(m.get(job.id))

    # ------------------------------------------------ prepare ahead of a tap

    def test_prepare_looks_the_song_up_and_parks_without_downloading(self):
        m = self.manager()
        job = m.prepare(AUTH, self.req)
        self.assertEqual(job.state, "prepared", job.view())
        self.assertEqual(self.searcher.queries, ["Opeth Windowpane"])
        self.assertEqual(self.downloader.extracted, ["vid12345678"])
        self.assertEqual(self.downloader.calls, [])
        self.assertTrue(job.info.is_file())
        self.assertIsNone(job._auth, "credentials are dropped while parked")
        self.assertEqual(self.nd.scans, 0)
        self.assertNotIn("stream", job.view())

    def test_the_tap_after_a_prepare_goes_straight_to_the_download(self):
        m = self.manager()
        prepared = m.prepare(AUTH, self.req)
        job = m.submit(AUTH, self.req)
        self.assertIs(job, prepared)
        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(job.song_id, "new-song-id")
        # asked and extracted once, and the download used what was saved
        self.assertEqual(self.searcher.queries, ["Opeth Windowpane"])
        self.assertEqual(self.downloader.extracted, ["vid12345678"])
        self.assertEqual(self.downloader.infos, [job.info])
        self.assertFalse(job.prepare_only)

    def test_prepare_for_a_song_that_is_already_there_is_ready(self):
        m = self.manager(
            nd=FakeNavidrome(present={("opeth", "windowpane"): "42"}))
        job = m.prepare(AUTH, self.req)
        self.assertEqual((job.state, job.song_id), ("ready", "42"))
        self.assertEqual(self.downloader.extracted, [])

    def test_a_tap_while_the_lookup_is_still_running_does_not_park(self):
        waiting = []

        class Manual(Executor):
            def submit(self, fn, /, *args, **kwargs):
                f: Future = Future()
                waiting.append((f, fn, args, kwargs))
                return f

        m = JobManager(
            music_dir=self.music, work_dir=self.work,
            resolver=FakeSearcher([GOOD]), downloader=FakeDownloader(),
            navidrome=FakeNavidrome(), executor=Manual(),
            indexer=InlineExecutor(), cover=lambda u: None,
            tagger=lambda p, t, c: True, clock=lambda: self.now,
            sleep=self._sleep, min_free_gb=0)
        prepared = m.prepare(AUTH, self.req)      # queued, not run yet
        job = m.submit(AUTH, self.req)            # the person taps first
        self.assertIs(job, prepared)
        self.assertFalse(job.prepare_only)
        self.assertEqual(len(waiting), 1, "one pipeline run, not two")
        f, fn, args, kwargs = waiting[0]
        f.set_result(fn(*args, **kwargs))
        self.assertEqual(job.state, "ready", job.view())

    def test_a_prepared_song_nobody_taps_is_forgotten_and_swept(self):
        m = self.manager(prepare_ttl_s=60)
        job = m.prepare(AUTH, self.req)
        info = job.info
        self.assertTrue(info.is_file())
        self.now += 120
        m.prepare(AUTH, Request(artist="Other", title="Thing"))
        self.assertIsNone(m.get(job.id))
        self.assertFalse(info.exists())

    def test_prepares_are_limited_per_person_and_hour(self):
        m = self.manager(prepare_limit=2)
        m.prepare(AUTH, Request(artist="A", title="One"))
        m.prepare(AUTH, Request(artist="A", title="Two"))
        with self.assertRaises(Limits):
            m.prepare(AUTH, Request(artist="A", title="Three"))
        self.now += 3600
        m.prepare(AUTH, Request(artist="A", title="Three"))

    def test_a_prepare_does_not_use_up_the_daily_allowance_but_the_tap_does(self):
        m = self.manager(daily_limit=1)
        m.prepare(AUTH, self.req)
        m.submit(AUTH, self.req)
        with self.assertRaises(Limits):
            m.submit(AUTH, Request(artist="Opeth", title="Windowpane 2"))

    def test_a_tap_over_the_limit_leaves_the_prepared_song_parked(self):
        m = self.manager(daily_limit=0)
        prepared = m.prepare(AUTH, self.req)
        with self.assertRaises(Limits):
            m.submit(AUTH, self.req)
        self.assertEqual(prepared.state, "prepared")
        self.assertTrue(prepared.prepare_only)


class ApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.nd = FakeNavidrome()
        self.manager = JobManager(
            music_dir=root / "music", work_dir=root / "work",
            resolver=FakeSearcher([GOOD]), downloader=FakeDownloader(),
            navidrome=self.nd, executor=InlineExecutor(),
            indexer=InlineExecutor(), cover=lambda u: None,
            tagger=lambda p, t, c: True, sleep=lambda s: None, min_free_gb=0)
        (root / "music").mkdir()
        self.api = Api(self.manager, self.nd)
        self.q = "?u=marwa&t=" + "a" * 32 + "&s=salt1234"

    def post(self, body, query=None):
        return self.api.handle("POST", "/api/play" + (query or self.q), {},
                               json.dumps(body).encode())

    def _api_with(self, **limits):
        root = Path(self._tmp.name)
        manager = JobManager(
            music_dir=root / "music", work_dir=root / "work",
            resolver=FakeSearcher([GOOD]), downloader=FakeDownloader(),
            navidrome=self.nd, executor=InlineExecutor(),
            indexer=InlineExecutor(), cover=lambda u: None,
            tagger=lambda p, t, c: True, sleep=lambda s: None, min_free_gb=0,
            **limits)
        return Api(manager, self.nd)

    def test_too_many_at_once_and_the_days_limit_are_told_apart(self):
        # The app waits and asks again by itself for the first ("try again in a minute"); that is
        # right only for the first. The day's limit does not change in a minute.
        body = json.dumps({"artist": "Opeth", "title": "Windowpane"}).encode()
        status, busy = self._api_with(active_limit=0).handle(
            "POST", "/api/play" + self.q, {}, body)
        self.assertEqual((status, busy["error"]), (429, "rate_limited"))
        self.assertIn("minute", busy["message"])
        status, today = self._api_with(daily_limit=0).handle(
            "POST", "/api/play" + self.q, {}, body)
        self.assertEqual((status, today["error"]), (429, "daily_limit"))
        self.assertNotIn("minute", today["message"])
        self.assertIn("tomorrow", today["message"])

    def test_info_needs_no_login(self):
        status, body = self.api.handle("GET", "/api/info", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["service"], "encore-fetch")
        self.assertIn("play-now", body["features"])
        self.assertIn("prepare", body["features"])

    def test_prepare_needs_the_login_then_parks_the_song(self):
        body = json.dumps({"artist": "Opeth", "title": "Windowpane",
                           "album": "Damnation"}).encode()
        self.assertEqual(
            self.api.handle("POST", "/api/prepare", {}, body)[0], 401)
        self.assertEqual(self.api.handle(
            "GET", "/api/prepare" + self.q, {})[0], 405)
        status, job = self.api.handle(
            "POST", "/api/prepare" + self.q, {}, body)
        self.assertEqual(status, 202)
        self.assertEqual(job["state"], "prepared")
        # the tap that follows is the same job, now downloaded
        status, played = self.post({"artist": "Opeth", "title": "Windowpane",
                                    "album": "Damnation"})
        self.assertEqual((status, played["id"], played["state"]),
                         (200, job["id"], "ready"))

    def test_a_bad_prepare_body_is_a_400(self):
        self.assertEqual(self.api.handle(
            "POST", "/api/prepare" + self.q, {}, b"{}")[0], 400)

    def test_play_needs_the_music_login(self):
        self.assertEqual(self.api.handle("POST", "/api/play", {}, b"{}")[0], 401)
        self.nd.valid = False
        self.assertEqual(self.post({"artist": "A", "title": "B"})[0], 401)

    def test_start_then_poll(self):
        status, job = self.post({"artist": "Opeth", "title": "Windowpane",
                                 "album": "Damnation", "trackNumber": 5,
                                 "durationSec": 467})
        self.assertEqual(status, 200)  # the inline executor finished it
        self.assertEqual(job["state"], "ready")
        status, polled = self.api.handle(
            "GET", f"/api/play/{job['id']}{self.q}", {})
        self.assertEqual(status, 200)
        self.assertEqual(polled["songId"], "new-song-id")

    def test_the_audio_needs_the_login_and_is_the_file(self):
        status, job = self.post({"artist": "Opeth", "title": "Windowpane",
                                 "album": "Damnation"})
        self.assertEqual(status, 200)
        url = f"/api/play/{job['id']}/audio"
        self.assertEqual(self.api.handle("GET", url, {})[0], 401)
        status, body = self.api.handle("GET", url + self.q, {})
        self.assertEqual(status, 200)
        self.assertEqual(body.mime, "audio/ogg")
        self.assertEqual(body.path.read_bytes(), b"OggS-audio")

    def test_audio_of_an_unfinished_or_unknown_job_is_404(self):
        self.assertEqual(self.api.handle(
            "GET", "/api/play/0123456789abcdef/audio" + self.q, {})[0], 404)

    def test_bad_bodies_and_unknown_jobs(self):
        self.assertEqual(self.post({"artist": "A"})[0], 400)
        self.assertEqual(self.api.handle("POST", "/api/play" + self.q, {}, b"nope")[0], 400)
        self.assertEqual(self.api.handle(
            "GET", "/api/play/0123456789abcdef" + self.q, {})[0], 404)
        self.assertEqual(self.api.handle("GET", "/nothing", {})[0], 404)
        self.assertEqual(self.api.handle("PUT", "/api/info", {})[0], 405)


class DownloaderTest(unittest.TestCase):
    def test_argv_keeps_the_best_audio_untouched_and_ends_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookies = Path(tmp) / "c.txt"
            d = YtDlpDownloader("yt-dlp", cookies=str(cookies), max_file_mb=50)
            argv = d.argv("vid12345678", Path("/work/j1"))
            self.assertNotIn("--cookies", argv, "a login that is not there is not asked for")
            cookies.write_text("# Netscape HTTP Cookie File", encoding="utf-8")
            argv = d.argv("vid12345678", Path("/work/j1"))
        self.assertIn("bestaudio[acodec=opus]/bestaudio", argv)
        self.assertNotIn("-x", argv)  # written as it arrives, remuxed after
        self.assertEqual(argv[-2], "--")
        self.assertTrue(argv[-1].endswith("watch?v=vid12345678"))
        self.assertIn(str(cookies), argv)

    def test_rejects_a_video_id_that_could_be_an_option(self):
        d = YtDlpDownloader()
        with self.assertRaises(DownloadError):
            d.download("--exec rm -rf /", Path("/tmp/x"))

    def test_failure_text_maps_to_codes(self):
        self.assertEqual(classify_failure("ERROR: Sign in to confirm you're not a bot"),
                         "blocked")
        self.assertEqual(classify_failure("ERROR: Video unavailable"), "unavailable")
        # Checked on the real server (2026-10-18): an age-gated video says this while others download fine. It is about
        # that one video, not about the server, so it is "needs an age check", not "blocked".
        self.assertEqual(classify_failure("Sign in to confirm your age. Use --cookies-from-browser or --cookies"),
                         "age_restricted")
        self.assertEqual(classify_failure("whatever"), "download_failed")

    def test_a_successful_run_returns_the_produced_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        stem = Path(tmp.name) / "job"

        def runner(argv, timeout):
            Path(str(stem) + ".opus").write_bytes(b"x" * 4000)
            return RunResult(0, "", "")

        got = YtDlpDownloader(runner=runner).download("vid12345678", stem, 200)
        self.assertEqual(got.codec, "opus")
        self.assertEqual(got.path.name, "job.opus")
        self.assertEqual(got.bitrate_kbps, 0)  # 4 kB over 200 s

    def test_extract_saves_the_streams_and_a_download_starts_from_them(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        info = work / "job.info.json"
        stem = work / "job"
        calls = []

        def runner(argv, timeout):
            calls.append(argv)
            if "-j" in argv:
                return RunResult(0, '{"id": "vid12345678"}\n', "")
            Path(str(stem) + ".opus").write_bytes(b"x" * 4000)
            return RunResult(0, "", "")

        d = YtDlpDownloader(runner=runner)
        d.extract("vid12345678", info)
        self.assertEqual(json.loads(info.read_text("utf-8")),
                         {"id": "vid12345678"})
        self.assertEqual(calls[0][-2], "--")
        d.download("vid12345678", stem, 200, info=info)
        second = calls[1]
        self.assertIn("--load-info-json", second)
        self.assertEqual(second[second.index("--load-info-json") + 1],
                         str(info))
        self.assertNotIn("--", second, "no address: it comes from the file")

    def test_a_stale_saved_extraction_is_replaced_by_a_fresh_one(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        info = work / "job.info.json"
        info.write_text("{}", encoding="utf-8")
        stem = work / "job"
        calls = []

        def runner(argv, timeout):
            calls.append(argv)
            if "--load-info-json" in argv:
                return RunResult(1, "", "HTTP Error 403: Forbidden")
            Path(str(stem) + ".opus").write_bytes(b"x" * 4000)
            return RunResult(0, "", "")

        got = YtDlpDownloader(runner=runner).download(
            "vid12345678", stem, 200, info=info)
        self.assertEqual(got.path.name, "job.opus")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][-2], "--", "the second run asks YouTube")

    def test_a_failed_extraction_keeps_its_reason(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        def runner(argv, timeout):
            return RunResult(1, "", "ERROR: Sign in to confirm you're not a bot")

        with self.assertRaises(DownloadError) as caught:
            YtDlpDownloader(runner=runner).extract(
                "vid12345678", Path(tmp.name) / "i.json")
        self.assertEqual(caught.exception.code, "blocked")

    def test_extract_rejects_a_video_id_that_could_be_an_option(self):
        with self.assertRaises(DownloadError):
            YtDlpDownloader().extract("--exec x", Path("/tmp/i.json"))

    def test_cover_hosts_are_allow_listed(self):
        self.assertTrue(cover_url_ok("https://cdn-images.dzcdn.net/images/cover/x/500.jpg"))
        self.assertFalse(cover_url_ok("http://cdn-images.dzcdn.net/x.jpg"))
        self.assertFalse(cover_url_ok("https://evil.example.com/x.jpg"))
        self.assertFalse(cover_url_ok("https://dzcdn.net.evil.com/x.jpg"))
        self.assertFalse(cover_url_ok(None))


class ResolverTest(unittest.TestCase):
    """The yt-dlp resolver with a scripted command line."""

    MUSIC_PAGE = {"entries": [
        {"id": "Rgrt_8mXrK8", "ie_key": "Youtube",
         "url": "https://music.youtube.com/watch?v=Rgrt_8mXrK8"},
        {"id": "4D7u5KF7SP8", "ie_key": "Youtube",
         "url": "https://music.youtube.com/watch?v=4D7u5KF7SP8"},
        {"id": "UCxxxx", "ie_key": "YoutubeTab",
         "url": "https://music.youtube.com/browse/UCxxxx"},
    ]}
    META = {
        "Rgrt_8mXrK8": {"id": "Rgrt_8mXrK8", "title": "Get Lucky (Radio Edit)",
                        "track": "Get Lucky (Radio Edit)",
                        "artist": "Daft Punk, Pharrell Williams",
                        "album": "Get Lucky", "duration": 248,
                        "channel": "Daft Punk", "release_year": 2013},
        "4D7u5KF7SP8": {"id": "4D7u5KF7SP8", "title": "Get Lucky",
                        "track": "Get Lucky",
                        "artist": "Daft Punk, Pharrell Williams",
                        "album": "Random Access Memories", "duration": 370,
                        "channel": "Daft Punk", "release_year": 2013},
    }

    def runner(self, calls):
        def run(argv, timeout):
            calls.append(argv)
            last = argv[-1]
            if "music.youtube.com/search" in last:
                return RunResult(0, json.dumps(self.MUSIC_PAGE), "")
            if last.startswith("https://music.youtube.com/watch?v="):
                vid = last.split("=")[-1]
                return RunResult(0, json.dumps(self.META[vid]), "")
            return RunResult(1, "", "unexpected " + last)
        return run

    def test_the_album_version_is_chosen_by_its_declared_album_and_length(self):
        r = YtDlpResolver(runner=self.runner([]))
        got = r.resolve(Want("Daft Punk", "Get Lucky",
                             "Random Access Memories", 369))
        self.assertIsNotNone(got)
        self.assertEqual(got.candidate.video_id, "4D7u5KF7SP8")
        self.assertIn("album", got.reasons)
        self.assertEqual(got.candidate.artists,
                         ("Daft Punk", "Pharrell Williams"))

    def test_the_radio_edit_is_chosen_when_that_is_the_length_asked(self):
        r = YtDlpResolver(runner=self.runner([]))
        got = r.resolve(Want("Daft Punk", "Get Lucky (Radio Edit)", None, 248))
        self.assertEqual(got.candidate.video_id, "Rgrt_8mXrK8")

    def test_falls_back_to_plain_search_when_music_search_finds_nothing(self):
        plain = {"entries": [{"id": "plainplain1", "title": "Opeth - Windowpane",
                              "channel": "Opeth", "duration": 467}]}

        def run(argv, timeout):
            last = argv[-1]
            if "music.youtube.com/search" in last:
                return RunResult(1, "", "boom")
            if last.startswith("ytsearch"):
                return RunResult(0, json.dumps(plain), "")
            return RunResult(1, "", "no")

        got = YtDlpResolver(runner=run).resolve(
            Want("Opeth", "Windowpane", None, 467))
        self.assertIsNotNone(got)
        self.assertEqual(got.candidate.video_id, "plainplain1")
        self.assertFalse(got.candidate.structured)

    def test_a_clear_plain_hit_skips_the_slow_lookup(self):
        calls = []
        plain = {"entries": [{"id": "plainplain1", "title": "Opeth - Windowpane",
                              "channel": "Opeth - Topic", "duration": 467}]}

        def run(argv, timeout):
            calls.append(argv[-1])
            if argv[-1].startswith("ytsearch"):
                return RunResult(0, json.dumps(plain), "")
            return RunResult(1, "", "must not be asked")

        got = YtDlpResolver(runner=run).resolve(
            Want("Opeth", "Windowpane", "Damnation", 467))
        self.assertEqual(got.candidate.video_id, "plainplain1")
        self.assertEqual(len(calls), 1)

    def test_nothing_acceptable_is_none(self):
        r = YtDlpResolver(runner=lambda a, t: RunResult(1, "", "down"))
        self.assertIsNone(r.resolve(Want("A", "B")))

    def test_option_looking_queries_stay_after_the_separator(self):
        calls = []
        YtDlpResolver(runner=self.runner(calls)).resolve(
            Want("--exec", "-o /etc/passwd"))
        self.assertTrue(calls)
        for argv in calls:
            self.assertIn("--", argv)
            self.assertEqual(argv.index("--"), len(argv) - 2)


class DispatcherTest(unittest.TestCase):
    def _job(self, bulk):
        from encore_fetch.jobs import Job
        return Job(id="x", key="k", user="u",
                   request=Request(artist="A", title="T", bulk=bulk))

    def test_a_tapped_song_does_not_wait_behind_a_bulk_album(self):
        import threading
        from encore_fetch.jobs import Dispatcher
        gate = threading.Event()
        ran = []
        d = Dispatcher(workers=2, bulk_slots=1)
        self.addCleanup(d.shutdown)

        def work(job, label):
            ran.append(label)
            if label.startswith("bulk"):
                gate.wait(5)

        for i in range(3):
            d.submit(work, self._job(True), f"bulk{i}")
        f = d.submit(work, self._job(False), "now")
        f.result(timeout=3)          # finished while bulk0 is still blocked
        self.assertIn("now", ran)
        self.assertEqual([r for r in ran if r.startswith("bulk")], ["bulk0"])
        gate.set()

    def test_a_lookup_ahead_waits_for_tapped_songs_but_not_for_an_album(self):
        import threading
        from encore_fetch.jobs import Dispatcher, Job
        gate = threading.Event()
        order = []
        d = Dispatcher(workers=1, bulk_slots=1, prep_slots=1)
        self.addCleanup(d.shutdown)

        def job(kind):
            j = Job(id="x", key="k", user="u",
                    request=Request(artist="A", title="T",
                                    bulk=(kind == "bulk")),
                    prepare_only=(kind == "prep"))
            return j

        def work(j, label):
            order.append(label)
            if label == "first":
                gate.wait(5)

        d.submit(work, job("now"), "first")       # occupies the only worker
        futures = [
            d.submit(work, job("bulk"), "bulk"),
            d.submit(work, job("prep"), "prep"),
            d.submit(work, job("now"), "now"),
        ]
        gate.set()
        for f in futures:
            f.result(timeout=3)
        self.assertEqual(order, ["first", "now", "prep", "bulk"])

    def test_priority_is_first_in_first_out_within_a_kind(self):
        from encore_fetch.jobs import Dispatcher
        order = []
        d = Dispatcher(workers=1, bulk_slots=1)
        self.addCleanup(d.shutdown)
        futures = [d.submit(lambda j, n: order.append(n), self._job(False), n)
                   for n in range(5)]
        for f in futures:
            f.result(timeout=3)
        self.assertEqual(order, [0, 1, 2, 3, 4])


class LiveStreamTest(unittest.TestCase):
    """A song is playable while it is still arriving."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name)

    def job(self, state="downloading"):
        from encore_fetch.jobs import Job
        j = Job(id="0123456789abcdef", key="k", user="u",
                request=Request(artist="A", title="T"), state=state)
        j.stem = self.work / "0123456789abcdef"
        return j

    def test_reads_the_part_file_as_it_grows_and_follows_the_rename(self):
        from encore_fetch.server import iter_live
        job = self.job()
        part = self.work / "0123456789abcdef.webm.part"
        part.write_bytes(b"A" * 100)
        steps = []

        def sleep(_):
            steps.append(1)
            if len(steps) == 1:
                with part.open("ab") as f:
                    f.write(b"B" * 50)
            elif len(steps) == 2:
                part.rename(self.work / "0123456789abcdef.webm")
                job.state = "tagging"      # the download is over

        got = b"".join(iter_live(job, sleep=sleep))
        self.assertEqual(got, b"A" * 100 + b"B" * 50)

    def test_gives_up_when_nothing_arrives(self):
        from encore_fetch.server import iter_live
        job = self.job()
        t = [0.0]

        def clock():
            t[0] += 10
            return t[0]

        got = list(iter_live(job, sleep=lambda s: None, clock=clock,
                             idle_limit=30))
        self.assertEqual(got, [])

    def test_a_failed_job_ends_the_stream(self):
        from encore_fetch.server import iter_live
        job = self.job(state="failed")
        (self.work / "0123456789abcdef.webm.part").write_bytes(b"xx")
        self.assertEqual(b"".join(iter_live(job, sleep=lambda s: None)), b"xx")

    def test_streamable_needs_a_few_seconds_of_audio(self):
        job = self.job()
        part = self.work / "0123456789abcdef.webm.part"
        part.write_bytes(b"x" * 1000)
        self.assertFalse(job.streamable())
        part.write_bytes(b"x" * 30000)
        self.assertTrue(job.streamable())
        self.assertEqual(job.view()["stream"], "/api/play/0123456789abcdef/audio")

    def test_the_audio_route_serves_a_download_in_progress(self):
        from encore_fetch.server import LiveBody
        root = self.work
        manager = JobManager(
            music_dir=root / "music", work_dir=root / "work",
            resolver=FakeSearcher([GOOD]), downloader=FakeDownloader(),
            navidrome=FakeNavidrome(), executor=InlineExecutor(),
            indexer=InlineExecutor(), cover=lambda u: None,
            tagger=lambda p, t, c: True, sleep=lambda s: None, min_free_gb=0)
        job = self.job()
        manager._jobs[job.id] = job
        (self.work / "0123456789abcdef.webm.part").write_bytes(b"x" * 30000)
        api = Api(manager, FakeNavidrome())
        q = "?u=marwa&t=" + "a" * 32 + "&s=salt1234"
        status, body = api.handle("GET", f"/api/play/{job.id}/audio" + q, {})
        self.assertEqual(status, 200)
        self.assertIsInstance(body, LiveBody)


class RangeTest(unittest.TestCase):
    def test_ranges(self):
        from encore_fetch.server import parse_range
        self.assertEqual(parse_range("bytes=0-99", 1000), (0, 99))
        self.assertEqual(parse_range("bytes=500-", 1000), (500, 999))
        self.assertEqual(parse_range("bytes=-100", 1000), (900, 999))
        self.assertEqual(parse_range("bytes=900-5000", 1000), (900, 999))

    def test_unusable_ranges_mean_the_whole_file(self):
        from encore_fetch.server import parse_range
        for bad in (None, "", "items=0-5", "bytes=5-2", "bytes=2000-",
                    "bytes=0-1,5-6", "bytes=-0", "bytes=a-b"):
            self.assertIsNone(parse_range(bad, 1000), bad)


class TaggingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_ffmpeg_arguments_copy_the_audio_and_replace_tags(self):
        from encore_fetch.tagging import Tags, ffmpeg_args
        argv = ffmpeg_args(Path("/w/a.opus"), Path("/w/a.tagged.opus"),
                           Tags("Windowpane", "Opeth", "Damnation",
                                track=5, disc=1, year=2003))
        joined = " ".join(argv)
        self.assertIn("-c copy", joined)
        self.assertIn("-map_metadata -1", joined)
        self.assertIn("title=Windowpane", joined)
        self.assertIn("album_artist=Opeth", joined)
        self.assertIn("track=5", joined)
        self.assertIn("date=2003", joined)
        self.assertEqual(argv[-1], str(Path("/w/a.tagged.opus")))

    def test_falls_back_to_ffmpeg_and_replaces_the_file(self):
        from encore_fetch.tagging import Tags, write_tags
        path = Path(self._tmp.name) / "a.opus"
        path.write_bytes(b"not really opus")
        seen = []

        def runner(argv, timeout):
            seen.append(argv)
            Path(argv[-1]).write_bytes(b"tagged audio")
            return RunResult(0, "", "")

        ok = write_tags(path, Tags("T", "A"), None, runner=runner,
                        ffmpeg="/usr/bin/ffmpeg")
        self.assertTrue(ok)
        self.assertEqual(seen[0][0], "/usr/bin/ffmpeg")
        self.assertEqual(path.read_bytes(), b"tagged audio")
        self.assertEqual(list(path.parent.glob("*.tagged.*")), [])

    def test_a_failing_ffmpeg_leaves_the_download_alone(self):
        from encore_fetch.tagging import Tags, write_tags
        path = Path(self._tmp.name) / "a.opus"
        path.write_bytes(b"original")
        ok = write_tags(path, Tags("T", "A"), None,
                        runner=lambda a, t: RunResult(1, "", "boom"))
        self.assertFalse(ok)
        self.assertEqual(path.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
