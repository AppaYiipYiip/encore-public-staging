"""Playing by streaming (stream.py, docs/tasks P1-02): the audio is passed on as it arrives, with Range, and a song of any length plays."""
import http.client
import io
import json
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path

from encore_fetch.direct import CHUNK, FIRST_CHUNK
from encore_fetch.download import DownloadError
from encore_fetch.jobs import Request
from encore_fetch.server import Api, serve
from encore_fetch.stream import StreamError, StreamProxy

from tests.test_pipeline import AUTH, FakeNavidrome


class FakeYouTube:
    """The googlevideo side: honours Range with 206 and Content-Range, and can refuse (403) the first requests of a fresh address.

    Every address carries a generation (`g=N`, issued by `info_file`); once `only_generation` is set, only that one works (the older
    ones have expired)."""

    def __init__(self, data: bytes, *, refuse_first: int = 0, expired_after: int | None = None):
        self.data = data
        self.refuse_first = refuse_first
        self.expired_after = expired_after
        self.only_generation: int | None = None
        self.requests: list[str] = []

    def __call__(self, request, timeout=None):
        rng = request.get_header("Range")
        self.requests.append(rng)
        generation = int(request.full_url.rsplit("g=", 1)[1]) if "g=" in request.full_url else 0
        expired = self.only_generation is not None and generation != self.only_generation
        if expired or len(self.requests) <= self.refuse_first or (
                self.expired_after is not None and len(self.requests) > self.expired_after):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b""))
        start, end = (int(x) for x in rng.removeprefix("bytes=").split("-"))
        end = min(end, len(self.data) - 1)
        body = self.data[start:end + 1]

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
        path.write_text(json.dumps({"url": f"https://rr1.example.googlevideo.com/videoplayback?x=1&g={len(issued)}", "ext": ext,
                                    "filesize": size, "http_headers": {"User-Agent": "test", "Range": "x", "Host": "x"}}),
                        encoding="utf-8")
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

    def proxy(self, youtube, *, candidates=None, extract=None, fault="", ttl=3000.0, first_byte_s=10.0):
        extractor = extract or info_file(size=len(self.data))

        def recording(video_id, path):
            self.extracted.append(video_id)
            extractor(video_id, path)

        def sleep(seconds):
            self.slept.append(seconds)
            self.now += seconds

        return StreamProxy(candidates=candidates or (lambda request: [("aaaaaaaaaaa", "t", 7200)]), extract=recording, work_dir=self.work,
                           opener=youtube, sleep=sleep, clock=lambda: self.now, fault=fault, info_ttl_s=ttl, first_byte_s=first_byte_s)

    def read(self, upstream):
        return b"".join(upstream.body)

    def test_the_whole_song_is_passed_on_in_order(self):
        up = self.proxy(FakeYouTube(self.data)).open(Request("A", "B"), None)

        self.assertEqual(up.status, 200)
        self.assertEqual(up.headers["Content-Type"], "audio/webm")
        self.assertEqual(up.headers["Content-Length"], str(len(self.data)))
        self.assertEqual(self.read(up), self.data)

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

    def test_the_first_bytes_arrive_in_a_small_request(self):
        youtube = FakeYouTube(self.data)
        up = self.proxy(youtube).open(Request("A", "B"), None)
        next(up.body)

        self.assertEqual(youtube.requests, [f"bytes=0-{FIRST_CHUNK - 1}"], "a player starts on the first bytes, not after a big one")

    def test_a_song_of_two_hours_is_not_refused_for_its_length(self):
        up = self.proxy(FakeYouTube(self.data), candidates=lambda request: [("aaaaaaaaaaa", "Surah", 8481)]).open(
            Request("Reciter", "Surat Al-Baqarah", duration_s=8481), None)
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

        up = self.proxy(FakeYouTube(self.data), extract=extract,
                        candidates=lambda request: [("aaaaaaaaaaa", "x", 200), ("bbbbbbbbbbb", "y", 200)]).open(Request("A", "B"), None)

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
        self.assertEqual(got, self.data[:len(got)])
        self.assertLess(len(got), len(self.data))


class RouteTest(unittest.TestCase):
    """Through the real HTTP handler: the headers, Range and the sentences a player and the app see."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = bytes(range(256)) * (3 * CHUNK // 256 + 5)
        self.youtube = FakeYouTube(self.data)
        proxy = StreamProxy(candidates=lambda request: [("aaaaaaaaaaa", "t", 200)], extract=info_file(size=len(self.data)),
                            work_dir=Path(self._tmp.name), opener=self.youtube, sleep=lambda s: None)

        class Manager:  # the route needs nothing of the manager
            pass

        self.api = Api(Manager(), FakeNavidrome(), streams=proxy)
        self.httpd = serve(self.api, "127.0.0.1", 0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.q = "u=marwa&t=" + "a" * 32 + "&s=salt1234&artist=Opeth&title=Windowpane"

    def get(self, path, headers=None, method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=20)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, dict(response.getheaders()), body

    def test_a_player_gets_the_song_with_the_headers_it_needs(self):
        status, headers, body = self.get("/api/stream?" + self.q)

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "audio/webm")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(body, self.data)

    def test_a_seek_is_a_206_with_the_bytes_from_there(self):
        status, headers, body = self.get("/api/stream?" + self.q, {"Range": "bytes=1000-1999"})

        self.assertEqual(status, 206)
        self.assertEqual(headers["Content-Range"], f"bytes 1000-1999/{len(self.data)}")
        self.assertEqual(body, self.data[1000:2000])

    def test_a_video_id_alone_is_enough(self):
        status, _, body = self.get("/api/stream?u=marwa&t=" + "a" * 32 + "&s=salt1234&videoId=dQw4w9WgXcQ")
        self.assertEqual((status, body[:4]), (200, self.data[:4]))

    def test_without_a_login_it_is_a_401(self):
        status, _, _ = self.get("/api/stream?artist=Opeth&title=Windowpane")
        self.assertEqual(status, 401)

    def test_without_a_song_it_is_a_400(self):
        status, _, body = self.get("/api/stream?u=marwa&t=" + "a" * 32 + "&s=salt1234")
        self.assertEqual(status, 400)
        self.assertIn(b"videoId", body)

    def test_a_failure_is_json_with_a_sentence(self):
        def extract(video_id, path):
            raise DownloadError("blocked")

        self.api._streams = StreamProxy(candidates=lambda request: [("aaaaaaaaaaa", "t", 200)], extract=extract,
                                        work_dir=Path(self._tmp.name), opener=self.youtube, sleep=lambda s: None)
        status, headers, body = self.get("/api/stream?" + self.q)

        self.assertEqual(status, 503)
        data = json.loads(body)
        self.assertEqual(data["error"], "blocked")
        self.assertIn("Try again", data["message"])

    def test_the_service_says_how_youtube_is(self):
        status, info = self.api.handle("GET", "/api/info", {})
        self.assertEqual(info["youtube"], {"state": "ok"})

    def test_the_service_says_it_can_stream(self):
        status, info = self.api.handle("GET", "/api/info", {})
        self.assertIn("stream", info["features"])

    def test_a_head_request_gets_the_headers_and_no_body(self):
        status, headers, body = self.get("/api/stream?" + self.q, method="HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(headers["Content-Length"], str(len(self.data)))


if __name__ == "__main__":
    unittest.main()
