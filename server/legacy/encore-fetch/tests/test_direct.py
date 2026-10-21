"""Fetching a found stream with plain ranged requests (direct.py) and its use by the downloader."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from encore_fetch.direct import CHUNK, FIRST_CHUNK, DirectFailed, fetch
from encore_fetch.download import DownloadError, YtDlpDownloader
from encore_fetch.cookies import Lease
from encore_fetch.resolve import RunResult


class FakeStream:
    """Behaves like the opener for googlevideo: honours Range with 206 + Content-Range, or misbehaves on request."""

    def __init__(self, data: bytes, *, ignore_range=False, fail_after=None, no_content_range=False, empty_after=None,
                 refuse_first=0):
        self.data = data
        self.ignore_range = ignore_range
        self.fail_after = fail_after
        self.no_content_range = no_content_range
        self.empty_after = empty_after
        self.refuse_first = refuse_first
        self.requests: list[tuple[str, str]] = []

    def __call__(self, request, timeout=None):
        rng = request.get_header("Range")
        self.requests.append((request.full_url, rng))
        if len(self.requests) <= self.refuse_first:
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b""))
        if self.fail_after is not None and len(self.requests) > self.fail_after:
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b""))
        if self.empty_after is not None and len(self.requests) > self.empty_after:
            return self._response(200 if self.ignore_range else 206, b"", None)
        if self.ignore_range or rng is None:
            return self._response(200, self.data, None)
        start, end = (int(x) for x in rng.removeprefix("bytes=").split("-"))
        end = min(end, len(self.data) - 1)
        header = None if self.no_content_range else f"bytes {start}-{end}/{len(self.data)}"
        return self._response(206, self.data[start:end + 1], header)

    @staticmethod
    def _response(status, body, content_range):
        class Response:
            def __init__(self):
                self.status = status
                self.headers = {"Content-Range": content_range} if content_range else {}
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Response()


def info_for(data: bytes, **extra) -> dict:
    return {"url": "https://rr1.example.googlevideo.com/videoplayback?x=1", "ext": "webm", "filesize": len(data),
            "http_headers": {"User-Agent": "test", "Range": "bytes=0-1", "Host": "ignored"}, **extra}


class FetchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.stem = Path(self._tmp.name) / "work" / "job1"
        self.data = bytes(range(256)) * (3 * CHUNK // 256 + 7)  # a bit over three chunks

    def test_the_whole_file_arrives_in_order_and_is_renamed_when_complete(self):
        stream = FakeStream(self.data)
        path = fetch(info_for(self.data), self.stem, max_bytes=10**9, opener=stream)
        self.assertEqual(path.name, "job1.webm")
        self.assertEqual(path.read_bytes(), self.data)
        self.assertFalse(path.with_name("job1.webm.part").exists())

    def test_the_first_request_is_small_so_the_player_can_start_early(self):
        stream = FakeStream(self.data)
        fetch(info_for(self.data), self.stem, max_bytes=10**9, opener=stream)
        self.assertEqual(stream.requests[0][1], f"bytes=0-{FIRST_CHUNK - 1}")
        self.assertEqual(stream.requests[1][1], f"bytes={FIRST_CHUNK}-{FIRST_CHUNK + CHUNK - 1}")

    def test_the_callers_own_range_and_host_headers_are_never_forwarded(self):
        seen = []

        def opener(request, timeout=None):
            seen.append(dict(request.header_items()))
            return FakeStream(self.data)(request, timeout)

        fetch(info_for(self.data), self.stem, max_bytes=10**9, opener=opener)
        self.assertEqual(seen[0].get("User-agent"), "test")
        self.assertTrue(seen[0]["Range"].startswith("bytes=0-"))
        self.assertNotIn("Host", seen[0])

    def test_a_growing_file_exists_while_it_downloads(self):
        names = []

        def opener(request, timeout=None):
            names.append(sorted(p.name for p in self.stem.parent.iterdir()))
            return FakeStream(self.data)(request, timeout)

        fetch(info_for(self.data), self.stem, max_bytes=10**9, opener=opener)
        self.assertIn("job1.webm.part", names[1])  # what the live reader and the player look for (download.live_source)

    def test_a_server_that_ignores_ranges_sends_the_whole_file_once(self):
        stream = FakeStream(self.data, ignore_range=True)
        path = fetch(info_for(self.data), self.stem, max_bytes=10**9, opener=stream)
        self.assertEqual(path.read_bytes(), self.data)
        self.assertEqual(len(stream.requests), 1)

    def test_without_a_known_size_the_end_is_a_short_answer(self):
        data = self.data[: FIRST_CHUNK + 1000]
        info = info_for(data)
        info.pop("filesize")
        path = fetch(info, self.stem, max_bytes=10**9, opener=FakeStream(data, no_content_range=True))
        self.assertEqual(path.read_bytes(), data)

    def test_a_new_address_that_is_refused_at_first_is_retried_until_it_opens(self):
        # Measured: a fresh address of the TV client answers 403 for the first 2 to 4 seconds, then works.
        stream = FakeStream(self.data, refuse_first=3)
        slept = []
        path = fetch(info_for(self.data), self.stem, max_bytes=10**9, opener=stream, sleep=slept.append)
        self.assertEqual(path.read_bytes(), self.data)
        self.assertEqual(len(slept), 3)

    def test_an_address_that_never_opens_gives_up_after_a_few_seconds(self):
        slept = []
        with self.assertRaises(DirectFailed):
            fetch(info_for(self.data), self.stem, max_bytes=10**9, opener=FakeStream(self.data, refuse_first=99), sleep=slept.append)
        self.assertLess(sum(slept), 6.0)
        self.assertEqual(list(self.stem.parent.glob("job1*")), [])

    def test_a_refusal_in_the_middle_is_an_expired_address_and_is_not_retried(self):
        slept = []
        with self.assertRaises(DirectFailed):
            fetch(info_for(self.data), self.stem, max_bytes=10**9, opener=FakeStream(self.data, fail_after=1), sleep=slept.append)
        self.assertEqual(slept, [])

    def test_a_refused_address_fails_cleanly_and_leaves_nothing(self):
        with self.assertRaises(DirectFailed):
            fetch(info_for(self.data), self.stem, max_bytes=10**9, opener=FakeStream(self.data, fail_after=1), sleep=lambda s: None)
        self.assertEqual(list(self.stem.parent.glob("job1*")), [])

    def test_an_empty_answer_is_a_failure_not_an_endless_loop(self):
        with self.assertRaises(DirectFailed):
            fetch(info_for(self.data), self.stem, max_bytes=10**9, opener=FakeStream(self.data, empty_after=1))

    def test_a_file_over_the_limit_is_refused_before_a_byte_is_fetched(self):
        stream = FakeStream(self.data)
        with self.assertRaises(DownloadError) as caught:
            fetch(info_for(self.data), self.stem, max_bytes=1000, opener=stream)
        self.assertEqual(caught.exception.code, "too_big")
        self.assertEqual(stream.requests, [])

    def test_only_https_addresses_are_used(self):
        info = info_for(self.data)
        info["url"] = "http://rr1.example.googlevideo.com/x"
        with self.assertRaises(DirectFailed):
            fetch(info, self.stem, max_bytes=10**9, opener=FakeStream(self.data))

    def test_an_odd_extension_cannot_escape_the_work_folder(self):
        info = info_for(self.data, ext="../../evil")
        path = fetch(info, self.stem, max_bytes=10**9, opener=FakeStream(self.data))
        self.assertEqual(path.parent, self.stem.parent)
        self.assertEqual(path.suffix, ".webm")


class DownloaderUsesDirectTest(unittest.TestCase):
    """The downloader tries the direct way first, and falls back to yt-dlp when it cannot."""

    class NoAccount:
        def lease(self, count=True):
            return Lease()

    class WithAccount:
        def lease(self, count=True):
            return Lease(["--cookies", "/secret.txt"], account_id="a", report=lambda *_: None)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.stem = root / "job"
        self.info = root / "job.info.json"
        self.data = b"x" * 5000
        self.info.write_text(json.dumps(info_for(self.data)), encoding="utf-8")
        self.commands = []

    def runner_that_writes(self, argv, timeout):
        self.commands.append(argv)
        if argv[0] == "yt-dlp":
            (self.stem.parent / "job.webm").write_bytes(self.data)
        else:  # the remux
            Path(argv[-1]).write_bytes(self.data)
        return RunResult(0, "", "")

    def downloader(self, cookies, opener=None, direct=True):
        import encore_fetch.direct as direct_module

        if opener is not None:
            self.addCleanup(setattr, direct_module.urllib.request, "urlopen", direct_module.urllib.request.urlopen)
            direct_module.urllib.request.urlopen = opener
        return YtDlpDownloader("yt-dlp", cookies=cookies, runner=self.runner_that_writes, direct=direct)

    def test_a_good_direct_download_starts_no_yt_dlp(self):
        d = self.downloader(self.NoAccount(), opener=FakeStream(self.data))
        got = d.download("abcdefghijk", self.stem, 100, self.info)
        self.assertEqual(got.path.read_bytes(), self.data)
        self.assertFalse([c for c in self.commands if c[0] == "yt-dlp"])

    def test_a_refused_address_falls_back_to_yt_dlp(self):
        d = self.downloader(self.NoAccount(), opener=FakeStream(self.data, fail_after=0))
        got = d.download("abcdefghijk", self.stem, 100, self.info)
        self.assertEqual(got.path.read_bytes(), self.data)
        self.assertEqual(len([c for c in self.commands if c[0] == "yt-dlp"]), 1)

    def test_with_an_account_the_direct_download_is_still_used(self):
        # The stream address is signed by YouTube: fetching it needs no cookie.
        d = self.downloader(self.WithAccount(), opener=FakeStream(self.data))
        got = d.download("abcdefghijk", self.stem, 100, self.info)
        self.assertEqual(got.path.read_bytes(), self.data)
        self.assertFalse([c for c in self.commands if c[0] == "yt-dlp"])

    def test_the_switch_turns_it_off(self):
        d = self.downloader(self.NoAccount(), opener=FakeStream(self.data), direct=False)
        d.download("abcdefghijk", self.stem, 100, self.info)
        self.assertEqual(len([c for c in self.commands if c[0] == "yt-dlp"]), 1)


if __name__ == "__main__":
    unittest.main()
