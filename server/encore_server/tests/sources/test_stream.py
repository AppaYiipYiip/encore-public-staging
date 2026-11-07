"""Playing by streaming (sources/youtube/stream.py): the audio is passed on as it arrives, with Range, and a song of any length plays."""

import io
import json
import tempfile
import unittest
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from encore_server.sources.youtube.errors import DownloadError
from encore_server.sources.youtube.rest import Lookups
from encore_server.sources.youtube.stream import CHUNK, FIRST_CHUNK, StreamError, StreamProxy


@dataclass
class Request:
    """What the proxy hands to its candidate finder (here the finder is a fake that ignores it)."""

    artist: str
    title: str
    duration_s: int | None = None


class FakeYouTube:
    """The googlevideo side: honours Range with 206 and Content-Range, and can refuse (403) the first requests of a fresh address.

    Every address carries a generation (`g=N`, issued by `info_file`); once `only_generation` is set, only that one works (the older
    ones have expired)."""

    def __init__(
        self, data: bytes, *, refuse_first: int = 0, expired_after: int | None = None, refuse_nth: frozenset[int] = frozenset()
    ):
        self.data = data
        self.refuse_first = refuse_first
        self.expired_after = expired_after
        #: Requests (counted from 1) refused once each with 403: a chunk that fails in the middle of a long file.
        self.refuse_nth = refuse_nth
        self.only_generation: int | None = None
        self.requests: list[str] = []

    def __call__(self, request, timeout=None):
        rng = request.get_header("Range")
        self.requests.append(rng)
        generation = int(request.full_url.rsplit("g=", 1)[1]) if "g=" in request.full_url else 0
        expired = self.only_generation is not None and generation != self.only_generation
        if (
            expired
            or len(self.requests) <= self.refuse_first
            or (self.expired_after is not None and len(self.requests) > self.expired_after)
            or len(self.requests) in self.refuse_nth
        ):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b""))
        start, end = (int(x) for x in rng.removeprefix("bytes=").split("-"))
        end = min(end, len(self.data) - 1)
        body = self.data[start : end + 1]

        class Response:
            status = 206
            headers = {"Content-Range": f"bytes {start}-{end}/{len(self.data)}"}

            def read(self_inner):
                return body

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        return Response()


def info_file(size=None, ext="webm"):
    issued = []

    def extract(video_id, path):
        issued.append(video_id)
        path.write_text(
            json.dumps(
                {
                    "url": f"https://rr1.example.googlevideo.com/videoplayback?x=1&g={len(issued)}",
                    "ext": ext,
                    "filesize": size,
                    "http_headers": {"User-Agent": "test", "Range": "x", "Host": "x"},
                }
            ),
            encoding="utf-8",
        )

    return extract


class ProxyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name)
        # Two hours of audio (a recitation): about 163 MB in life; here a few chunks are enough to prove nothing limits it.
        self.data = bytes(range(256)) * (5 * CHUNK // 256 + 3)
        self.now = 1000.0
        self.slept: list[float] = []
        self.extracted: list[str] = []

    def proxy(self, youtube, *, candidates=None, extract=None, fault="", ttl=3000.0, first_byte_s=10.0, lookups=None):
        extractor = extract or info_file(size=len(self.data))

        def recording(video_id, path):
            self.extracted.append(video_id)
            extractor(video_id, path)

        def sleep(seconds):
            self.slept.append(seconds)
            self.now += seconds

        return StreamProxy(
            candidates=candidates or (lambda request: [("aaaaaaaaaaa", "t", 7200)]),
            extract=recording,
            work_dir=self.work,
            opener=youtube,
            sleep=sleep,
            clock=lambda: self.now,
            fault=fault,
            info_ttl_s=ttl,
            first_byte_s=first_byte_s,
            lookups=lookups,
        )

    def read(self, upstream):
        return b"".join(upstream.body)

    def test_the_whole_song_is_passed_on_in_order(self):
        up = self.proxy(FakeYouTube(self.data)).open(Request("A", "B"), None)

        self.assertEqual(up.status, 200)
        self.assertEqual(up.headers["Content-Type"], "audio/webm")
        self.assertEqual(up.headers["Content-Length"], str(len(self.data)))
        self.assertEqual(self.read(up), self.data)

    def test_a_prepared_song_needs_no_look_up_when_it_is_played(self):
        """P1-04 / audit B-107: the next song of a queue is made ready (its upload and its stream's address, no bytes) before the person presses Next."""
        youtube = FakeYouTube(self.data)
        proxy = self.proxy(youtube)
        self.assertFalse(proxy.has_address("aaaaaaaaaaa"))

        self.assertTrue(proxy.prepare(Request("A", "B")))

        self.assertEqual(self.extracted, ["aaaaaaaaaaa"], "the address was asked for once")
        self.assertEqual(youtube.requests, [], "nothing of the song itself was fetched")
        self.assertTrue(proxy.has_address("aaaaaaaaaaa"))
        up = proxy.open(Request("A", "B"), None)
        self.assertEqual(self.extracted, ["aaaaaaaaaaa"], "the play did not ask for the address again")
        self.assertEqual(self.read(up), self.data)

    def test_a_prepared_address_that_is_too_old_is_not_counted_as_kept(self):
        proxy = self.proxy(FakeYouTube(self.data), ttl=100.0)
        proxy.prepare(Request("A", "B"))
        self.now += 200.0
        self.assertFalse(proxy.has_address("aaaaaaaaaaa"))

    def test_nothing_is_prepared_when_no_upload_is_found(self):
        proxy = self.proxy(FakeYouTube(self.data), candidates=lambda request: [])
        self.assertFalse(proxy.prepare(Request("A", "B")))
        self.assertEqual(self.extracted, [])

    def test_nothing_is_prepared_while_the_fault_says_youtube_refuses(self):
        proxy = self.proxy(FakeYouTube(self.data), fault="youtube_refuse")
        self.assertFalse(proxy.prepare(Request("A", "B")))
        self.assertEqual(self.extracted, [])

    def test_a_player_that_jumps_gets_the_range_it_asked_for(self):
        youtube = FakeYouTube(self.data)
        start = len(self.data) - 5000
        up = self.proxy(youtube).open(Request("A", "B"), f"bytes={start}-")

        self.assertEqual(up.status, 206)
        self.assertEqual(up.headers["Content-Range"], f"bytes {start}-{len(self.data) - 1}/{len(self.data)}")
        self.assertEqual(up.headers["Content-Length"], "5000")
        self.assertEqual(self.read(up), self.data[start:])
        self.assertEqual(len(youtube.requests), 1, "one small request: the jump costs nothing but those bytes")

    def test_a_closed_range_is_exactly_that_many_bytes(self):
        up = self.proxy(FakeYouTube(self.data)).open(Request("A", "B"), "bytes=100-199")
        self.assertEqual(self.read(up), self.data[100:200])
        self.assertEqual(up.headers["Content-Range"], f"bytes 100-199/{len(self.data)}")

    def test_the_stage_lines_say_how_many_look_ups_were_made_today(self):
        """A test run has a budget of look-ups at YouTube (at most 10 from a home address). The count was logged only every 25th time, so a run could not
        be counted from the server's own log; now each song's two stage lines carry it."""
        lookups = Lookups()
        for _ in range(3):
            lookups.note()
        with self.assertLogs("encore_server.sources.youtube.stream", level="INFO") as logged:
            up = self.proxy(FakeYouTube(self.data), lookups=lookups).open(Request("A", "B"), None)
            self.read(up)
        text = "\n".join(logged.output)

        self.assertIn("the first bytes after", text)
        self.assertIn("the address was asked for", text)
        for line in logged.output:
            self.assertIn("(look-ups today: 3)", line, "every stage line names the count")

    def test_without_a_counter_the_stage_lines_are_as_they_were(self):
        with self.assertLogs("encore_server.sources.youtube.stream", level="INFO") as logged:
            self.read(self.proxy(FakeYouTube(self.data)).open(Request("A", "B"), None))

        self.assertTrue(all("look-ups" not in line for line in logged.output))

    def test_the_first_bytes_arrive_in_a_small_request(self):
        youtube = FakeYouTube(self.data)
        up = self.proxy(youtube).open(Request("A", "B"), None)
        next(up.body)

        self.assertEqual(
            youtube.requests, [f"bytes=0-{FIRST_CHUNK - 1}"], "a player starts on the first bytes, not after a big one"
        )

    def test_a_song_of_two_hours_is_not_refused_for_its_length(self):
        up = self.proxy(FakeYouTube(self.data), candidates=lambda request: [("aaaaaaaaaaa", "Surah", 8481)]).open(
            Request("Reciter", "Surat Al-Baqarah", duration_s=8481), None
        )
        self.assertEqual(up.status, 200)

    def test_the_address_is_asked_for_once_however_many_players_ask(self):
        proxy = self.proxy(FakeYouTube(self.data))
        for _ in range(3):
            proxy.open(Request("A", "B"), "bytes=0-9")

        self.assertEqual(self.extracted, ["aaaaaaaaaaa"])

    def test_an_address_that_has_expired_is_asked_for_again_once(self):
        youtube = FakeYouTube(self.data)
        proxy = self.proxy(youtube)
        proxy.open(Request("A", "B"), "bytes=0-9")
        youtube.only_generation = 2  # the address that was kept stops working; the next one issued works

        up = proxy.open(Request("A", "B"), "bytes=0-9")

        self.assertEqual(self.read(up), self.data[:10])
        self.assertEqual(self.extracted.count("aaaaaaaaaaa"), 2, "asked again for a fresh address")

    def test_a_fresh_address_that_answers_403_for_a_few_seconds_is_waited_for(self):
        youtube = FakeYouTube(self.data, refuse_first=3)
        up = self.proxy(youtube).open(Request("A", "B"), None)

        self.assertEqual(up.status, 200)
        self.assertEqual(self.slept[:3], [0.5, 0.5, 0.75])

    def test_when_the_first_byte_cannot_come_in_time_the_answer_is_a_sentence(self):
        youtube = FakeYouTube(self.data, refuse_first=99)
        with self.assertRaises(StreamError) as caught:
            self.proxy(youtube, first_byte_s=3.0).open(Request("A", "B"), None)

        self.assertEqual(caught.exception.status, 504)
        self.assertIn("could not be started in time", caught.exception.message)

    def test_an_upload_that_is_gone_is_replaced_by_the_next_best(self):
        def extract(video_id, path):
            if video_id == "aaaaaaaaaaa":
                raise DownloadError("age_restricted")
            info_file(size=len(self.data))(video_id, path)

        up = self.proxy(
            FakeYouTube(self.data),
            extract=extract,
            candidates=lambda request: [("aaaaaaaaaaa", "x", 200), ("bbbbbbbbbbb", "y", 200)],
        ).open(Request("A", "B"), None)

        self.assertEqual(self.read(up), self.data)

    def test_every_upload_refused_says_why(self):
        def extract(video_id, path):
            raise DownloadError("age_restricted")

        with self.assertRaises(StreamError) as caught:
            self.proxy(FakeYouTube(self.data), extract=extract).open(Request("A", "B"), None)
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "age_restricted"))

    def test_nothing_found_is_a_404_with_words(self):
        with self.assertRaises(StreamError) as caught:
            self.proxy(FakeYouTube(self.data), candidates=lambda request: []).open(Request("A", "B"), None)
        self.assertEqual((caught.exception.status, caught.exception.code), (404, "not_found"))

    def test_youtube_blocking_the_server_is_a_503_with_words(self):
        def extract(video_id, path):
            raise DownloadError("blocked")

        with self.assertRaises(StreamError) as caught:
            self.proxy(FakeYouTube(self.data), extract=extract).open(Request("A", "B"), None)
        self.assertEqual(caught.exception.status, 503)
        self.assertIn("not letting this server", caught.exception.message)

    def test_the_fault_flags_make_a_misbehaving_youtube_for_tests_of_the_app(self):
        for flag, status in (("youtube_refuse", 503), ("no_results", 404)):
            with self.assertRaises(StreamError, msg=flag) as caught:
                self.proxy(FakeYouTube(self.data), fault=flag).open(Request("A", "B"), None)
            self.assertEqual(caught.exception.status, status, flag)

        with self.assertRaises(StreamError) as caught:
            self.proxy(FakeYouTube(self.data), fault="slow_extract:20000", first_byte_s=10.0).open(Request("A", "B"), None)
        self.assertEqual(caught.exception.status, 504, "a slow look-up ends in the sentence, not in a hang")

    def test_a_stream_that_stops_half_way_ends_quietly(self):
        youtube = FakeYouTube(self.data, expired_after=2)
        up = self.proxy(youtube).open(Request("A", "B"), None)

        got = self.read(up)
        self.assertEqual(got, self.data[: len(got)])
        self.assertLess(len(got), len(self.data))
