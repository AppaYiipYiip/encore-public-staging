"""A YouTube login (a cookies.txt) is optional and may appear at any time: the next song simply uses it."""
import tempfile
import unittest
from pathlib import Path

from encore_fetch.config import Config
from encore_fetch.cookies import cookie_args


class CookiesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "youtube-cookies.txt"

    def test_without_a_file_nothing_is_passed_to_yt_dlp(self):
        self.assertEqual(cookie_args(str(self.path)), [])
        self.assertEqual(cookie_args(None), [])
        self.assertEqual(cookie_args(""), [])

    def test_an_empty_file_is_not_a_login(self):
        self.path.write_text("", encoding="utf-8")
        self.assertEqual(cookie_args(str(self.path)), [])

    def test_a_file_that_appears_later_is_used_by_the_next_song_without_a_restart(self):
        self.assertEqual(cookie_args(str(self.path)), [])
        self.path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        self.assertEqual(cookie_args(str(self.path)), ["--cookies", str(self.path)])
        self.path.unlink()
        self.assertEqual(cookie_args(str(self.path)), [])

    def test_the_default_place_is_the_work_folder(self):
        import os
        old = os.environ.pop("YT_COOKIES_FILE", None)
        os.environ["WORK_DIR"] = "/work"
        try:
            self.assertTrue(Config.from_env().cookies_file.replace("\\", "/").endswith("/work/youtube-cookies.txt"))
            os.environ["YT_COOKIES_FILE"] = "/elsewhere/c.txt"
            self.assertEqual(Config.from_env().cookies_file, "/elsewhere/c.txt")
        finally:
            os.environ.pop("YT_COOKIES_FILE", None)
            os.environ.pop("WORK_DIR", None)
            if old is not None:
                os.environ["YT_COOKIES_FILE"] = old


if __name__ == "__main__":
    unittest.main()
