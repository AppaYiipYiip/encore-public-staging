"""The fast search and in-process extraction (P1-01), tested against REAL YouTube Music answers recorded in tests/fixtures/ytm
(tools/record_ytm_fixtures.py). Nothing here invents a search result."""

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from encore_server.sources.youtube import lean
from encore_server.sources.youtube.errors import DownloadError
from encore_server.sources.youtube.lean import (
    InProcessExtractor,
    LeanResolver,
    candidate_from_song,
    candidate_from_video,
    choose,
    queries_for,
)
from encore_server.sources.youtube.scoring import Candidate, Scored, Want

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ytm"


def _slug(text: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def recorded(query: str, kind: str) -> list[dict]:
    path = FIXTURES / f"{_slug(query)}.{kind}.json"
    if not path.is_file():
        return []  # nothing was recorded for this question: the service had no answer for it
    return json.loads(path.read_text(encoding="utf-8"))["results"]


class RecordedSearcher:
    """Answers with what YouTube Music really answered when the fixtures were recorded, and remembers what was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def songs(self, query: str, limit: int) -> list[dict]:
        with self._lock:
            self.asked.append(("songs", query))
        return recorded(query, "songs")

    def videos(self, query: str, limit: int) -> list[dict]:
        with self._lock:
            self.asked.append(("videos", query))
        return recorded(query, "videos")


def declared(found: Scored | None) -> tuple:
    """(title, artists, album) the chosen upload declares about itself."""
    assert found is not None
    c = found.candidate
    return c.track or c.title, c.artists, c.album


class MappingTest(unittest.TestCase):
    def test_a_song_result_becomes_a_structured_topic_candidate(self):
        raw = recorded("Maria Tambien Khruangbin", "songs")[0]
        c = candidate_from_song(raw)
        self.assertTrue(c.structured)
        self.assertTrue(c.is_topic)
        self.assertEqual(c.artists, ("Khruangbin",))
        self.assertEqual(c.album, "Con Todo El Mundo")
        self.assertEqual(c.duration_s, 191)

    def test_a_video_result_has_only_title_channel_and_length(self):
        raw = recorded("Surah Al-Baqarah Mishary Alafasy", "videos")[0]
        c = candidate_from_video(raw)
        self.assertFalse(c.structured)
        self.assertEqual(c.duration_s, 8481)  # 2 hours 21 minutes: length is not a problem for finding it

    def test_odd_answers_are_skipped_not_fatal(self):
        self.assertIsNone(candidate_from_song({"title": "no id"}))
        self.assertIsNone(candidate_from_song({"videoId": 12, "title": "x"}))
        self.assertIsNone(candidate_from_video({}))

    def test_length_can_come_from_the_text(self):
        c = candidate_from_song({"videoId": "abcdefghijk", "title": "x", "duration": "1:02:03", "artists": []})
        self.assertEqual(c.duration_s, 3723)

    def test_both_word_orders_are_asked_once_each(self):
        self.assertEqual(queries_for(Want("Nas", "N.Y. State of Mind")), ["Nas N.Y. State of Mind", "N.Y. State of Mind Nas"])
        self.assertEqual(len(queries_for(Want("", "Only a title"))), 1)


class RealAnswersTest(unittest.TestCase):
    """The owner's kinds of searches: mainstream, a cover-heavy title, non-Latin, obscure, and a 2-hour recitation."""

    def resolve(self, want: Want, max_duration_s: int = 2700):
        self.searcher = RecordedSearcher()
        resolver = LeanResolver(self.searcher, max_duration_s=max_duration_s)
        self.addCleanup(resolver._pool.shutdown)
        return resolver.resolve(want)

    def test_the_studio_song_is_found_although_the_artist_first_search_lacks_it(self):
        # "Khruangbin Maria Tambien" lists only a live take of the song; "Maria Tambien Khruangbin" lists the studio song first.
        found = self.resolve(Want("Khruangbin", "Maria Tambien", "Con Todo El Mundo", 191))
        title, artists, album = declared(found)
        self.assertEqual((title, album), ("Maria También", "Con Todo El Mundo"))
        self.assertEqual(artists, ("Khruangbin",))

    def test_a_live_take_is_not_chosen_for_the_studio_song(self):
        found = self.resolve(Want("Khruangbin", "Maria Tambien", None, 191))
        self.assertNotIn("live", declared(found)[0].lower())

    def test_mainstream_song_with_featured_artist(self):
        found = self.resolve(Want("Daft Punk", "Instant Crush", "Random Access Memories", 338))
        title, artists, album = declared(found)
        self.assertEqual(album, "Random Access Memories")
        self.assertIn("Daft Punk", artists)

    def test_a_title_many_covers_share_finds_the_original_artist(self):
        found = self.resolve(Want("Radiohead", "Weird Fishes / Arpeggi", "In Rainbows", 319))
        title, artists, album = declared(found)
        self.assertEqual(artists, ("Radiohead",))
        self.assertEqual(album, "In Rainbows")

    def test_title_with_punctuation(self):
        found = self.resolve(Want("Nas", "N.Y. State of Mind", "Illmatic", 294))
        self.assertEqual(declared(found)[1], ("Nas",))
        self.assertEqual(declared(found)[2], "Illmatic")

    def test_non_latin_artist_written_in_latin_letters(self):
        found = self.resolve(Want("Fairuz", "Kifak Inta", "Kifak Inta", 212))
        self.assertEqual(declared(found)[1], ("Fairuz",))

    def test_a_song_by_another_artist_is_never_taken(self):
        # YouTube Music's first answer to "Taragalte Oum" is "Taragalte, Oum" by a different artist: the right answer is "not found".
        self.assertIsNone(self.resolve(Want("Oum", "Taragalte", None, 192)))

    def test_a_two_hour_recitation_is_found_as_a_video(self):
        found = self.resolve(Want("Mishary Alafasy", "Surah Al-Baqarah", None, 8481), max_duration_s=2700)
        self.assertIsNotNone(found)
        self.assertGreater(found.candidate.duration_s, 7000)

    def test_a_clear_song_does_not_wait_for_a_second_kind_of_search(self):
        self.resolve(Want("Nas", "N.Y. State of Mind", "Illmatic", 294))
        kinds = [kind for kind, _ in self.searcher.asked]
        self.assertEqual(kinds.count("songs"), 2)
        self.assertNotIn("videos", kinds)

    def test_the_video_search_uses_the_title_first_word_order(self):
        self.resolve(Want("Mishary Alafasy", "Surah Al-Baqarah", None, 8481))
        videos = [q for kind, q in self.searcher.asked if kind == "videos"]
        self.assertEqual(videos, ["Surah Al-Baqarah Mishary Alafasy"])


class ChoosingTest(unittest.TestCase):
    def test_a_song_by_a_different_artist_is_dropped_before_scoring(self):
        wrong = Candidate("aaaaaaaaaaa", "Taragalte", "Ollf - Topic", 192, True, track="Taragalte", artists=("Ollf",))
        self.assertIsNone(choose(Want("Oum", "Taragalte", None, 192), [wrong]))

    def test_a_song_with_several_artists_matches_any_of_them(self):
        c = Candidate(
            "bbbbbbbbbbb", "Mariella", "Khruangbin - Topic", 311, True, track="Mariella", artists=("Khruangbin", "Leon Bridges")
        )
        found = choose(Want("Leon Bridges", "Mariella", None, 311), [c])
        self.assertEqual(found.candidate.video_id, "bbbbbbbbbbb")


class ArtistNamesTest(unittest.TestCase):
    def test_whole_names_only(self):
        self.assertFalse(lean.artist_matches("Oum", ("Oum Dermam Stars",)))
        self.assertTrue(lean.artist_matches("Oum", ("Oum",)))

    def test_a_name_with_an_x_is_not_split(self):
        self.assertTrue(lean.artist_matches("Alex Turner", ("Alex Turner",)))
        self.assertTrue(lean.artist_matches("Alexandra", ("Alexandra",)))

    def test_a_name_that_contains_commas_and_ampersands_matches_as_a_whole(self):
        self.assertTrue(lean.artist_matches("Earth, Wind & Fire", ("Earth, Wind & Fire",)))

    def test_a_combined_artist_string_matches_any_of_its_artists(self):
        self.assertTrue(lean.artist_matches("Daft Punk, Julian Casablancas", ("Julian Casablancas",)))
        self.assertTrue(lean.artist_matches("Daft Punk feat. Pharrell Williams", ("Daft Punk", "Pharrell Williams")))

    def test_accents_and_case_do_not_matter(self):
        self.assertTrue(lean.artist_matches("Beyonce", ("Beyoncé",)))
        self.assertTrue(lean.artist_matches("sigur ros", ("Sigur Rós",)))

    def test_a_title_that_is_barely_alike_does_not_pass(self):
        c = Candidate(
            "ccccccccccc", "Habibi Waynk Habibi.", "x - Topic", 181, True, track="Habibi Waynk Habibi.", artists=("Oum",)
        )
        self.assertFalse(lean.title_matches(Want("Oum", "Taragalte"), c))


class FailureHandlingTest(unittest.TestCase):
    class Broken:
        def songs(self, query, limit):
            raise OSError("the service is down")

        videos = songs

    class Hanging:
        def __init__(self):
            self.release = threading.Event()

        def songs(self, query, limit):
            self.release.wait(5)
            return []

        videos = songs

    class Fallback:
        def __init__(self):
            self.asked = []

        def resolve(self, want):
            self.asked.append(want)
            return Scored(Candidate("fallbackid1", want.title, "x", None), 9.0, ("fallback",))

    def resolver(self, searcher, **kw):
        r = LeanResolver(searcher, **kw)
        self.addCleanup(lambda: r._pool.shutdown(wait=False, cancel_futures=True))
        return r

    def test_a_failing_service_falls_back_to_the_old_search(self):
        fb = self.Fallback()
        found = self.resolver(self.Broken(), fallback=fb).resolve(Want("A", "B"))
        self.assertEqual(found.candidate.video_id, "fallbackid1")
        self.assertEqual(len(fb.asked), 1)

    def test_without_a_fallback_the_failure_is_an_honest_error_not_not_found(self):
        with self.assertRaises(DownloadError) as caught:
            self.resolver(self.Broken()).resolve(Want("A", "B"))
        self.assertEqual(caught.exception.code, "unavailable")

    def test_a_hanging_service_is_given_up_on_in_time(self):
        hanging = self.Hanging()
        self.addCleanup(hanging.release.set)
        fb = self.Fallback()
        started = threading.Event()
        started.set()
        import time

        t0 = time.monotonic()
        found = self.resolver(hanging, fallback=fb, timeout_s=0.2).resolve(Want("A", "B"))
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual(found.candidate.video_id, "fallbackid1")

    def test_no_program_is_started_on_the_fast_path(self):
        def boom(*a, **k):
            raise AssertionError("the fast path must not start a program")

        searcher = RecordedSearcher()
        with mock.patch.object(subprocess, "run", boom), mock.patch.object(subprocess, "Popen", boom):
            found = self.resolver(searcher).resolve(Want("Nas", "N.Y. State of Mind", "Illmatic", 294))
        self.assertIsNotNone(found)


class FakeYtDlp:
    """A stand-in for the yt_dlp module with the two names the extractor uses."""

    class utils:
        class DownloadError(Exception):
            pass

    created = 0
    answer: dict | None = None
    error: str | None = None
    #: An error only the fast client (the one given `extractor_args`) raises.
    fast_error: str | None = None
    #: The player clients each look-up was asked for (`()` = yt-dlp's own choice).
    asked: list = []

    class YoutubeDL:
        def __init__(self, options):
            FakeYtDlp.created += 1
            self.options = options

        def extract_info(self, url, download):
            assert download is False
            clients = tuple(self.options.get("extractor_args", {}).get("youtube", {}).get("player_client", ()))
            FakeYtDlp.asked.append(clients)
            if FakeYtDlp.fast_error and clients:
                raise FakeYtDlp.utils.DownloadError(FakeYtDlp.fast_error)
            if FakeYtDlp.error:
                raise FakeYtDlp.utils.DownloadError(FakeYtDlp.error)
            return FakeYtDlp.answer

        def sanitize_info(self, info):
            return info


class InProcessExtractorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.info = Path(self._tmp.name) / "work" / "job.info.json"
        FakeYtDlp.created, FakeYtDlp.answer, FakeYtDlp.error = 0, {"id": "abcdefghijk", "formats": [1, 2]}, None
        patcher = mock.patch.dict(sys.modules, {"yt_dlp": FakeYtDlp, "yt_dlp.utils": FakeYtDlp.utils})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_answer_is_saved_as_the_downloader_expects_it(self):
        InProcessExtractor().extract("abcdefghijk", self.info)
        self.assertEqual(json.loads(self.info.read_text(encoding="utf-8")), FakeYtDlp.answer)

    def test_one_extractor_is_kept_per_thread(self):
        ex = InProcessExtractor()
        ex.extract("abcdefghijk", self.info)
        ex.extract("abcdefghijk", self.info)
        self.assertEqual(FakeYtDlp.created, 1)
        other = threading.Thread(target=ex.extract, args=("abcdefghijk", self.info))
        other.start()
        other.join()
        self.assertEqual(FakeYtDlp.created, 2)

    def test_the_bot_check_is_reported_as_a_block(self):
        FakeYtDlp.error = "ERROR: [youtube] x: Sign in to confirm you're not a bot"
        with self.assertRaises(DownloadError) as caught:
            InProcessExtractor().extract("abcdefghijk", self.info)
        self.assertEqual(caught.exception.code, "blocked")

    def test_an_age_gate_is_about_one_song_not_a_block(self):
        FakeYtDlp.error = "ERROR: [youtube] x: Sign in to confirm your age"
        with self.assertRaises(DownloadError) as caught:
            InProcessExtractor().extract("abcdefghijk", self.info)
        self.assertEqual(caught.exception.code, "age_restricted")


class FastClientTest(unittest.TestCase):
    """A visitor is first tried with the fast YouTube client (visionos: 1.3 s against 3.7 s), then with yt-dlp's own choice."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.info = Path(self._tmp.name) / "job.info.json"
        FakeYtDlp.created, FakeYtDlp.answer, FakeYtDlp.error = 0, {"id": "abcdefghijk", "url": "https://x"}, None
        FakeYtDlp.asked = []
        FakeYtDlp.fast_error = None
        patcher = mock.patch.dict(sys.modules, {"yt_dlp": FakeYtDlp, "yt_dlp.utils": FakeYtDlp.utils})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = 0.0

    def extractor(self, **kw):
        return InProcessExtractor(clock=lambda: self.now, **kw)

    def test_a_visitor_is_tried_with_the_fast_client_first(self):
        self.extractor().extract("abcdefghijk", self.info)
        self.assertEqual(FakeYtDlp.asked, [("visionos",)])

    def test_an_account_always_uses_yt_dlps_own_choice(self):
        self.extractor().extract("abcdefghijk", self.info, "/secret/cookies.txt")
        self.assertEqual(FakeYtDlp.asked, [()])

    def test_the_fast_client_can_be_switched_off(self):
        self.extractor(fast_clients=()).extract("abcdefghijk", self.info)
        self.assertEqual(FakeYtDlp.asked, [()])

    def test_a_video_the_fast_client_cannot_play_is_tried_with_yt_dlps_own_choice(self):
        FakeYtDlp.fast_error = "ERROR: [youtube] x: Requested format is not available"
        self.extractor().extract("abcdefghijk", self.info)
        self.assertEqual(FakeYtDlp.asked, [("visionos",), ()])
        self.assertIn("url", self.info.read_text(encoding="utf-8"))

    def test_an_age_gate_on_the_fast_client_gets_the_other_one_a_chance(self):
        FakeYtDlp.fast_error = "ERROR: [youtube] x: Sign in to confirm your age"
        self.extractor().extract("abcdefghijk", self.info)
        self.assertEqual(FakeYtDlp.asked, [("visionos",), ()])

    def test_a_block_is_not_looked_up_twice(self):
        FakeYtDlp.fast_error = "ERROR: [youtube] x: Sign in to confirm you're not a bot"
        with self.assertRaises(DownloadError) as caught:
            self.extractor().extract("abcdefghijk", self.info)
        self.assertEqual(caught.exception.code, "blocked")
        self.assertEqual(FakeYtDlp.asked, [("visionos",)], "YouTube refusing the server says nothing about the client")

    def test_a_video_that_is_gone_is_not_looked_up_twice(self):
        FakeYtDlp.fast_error = "ERROR: [youtube] x: Video unavailable"
        with self.assertRaises(DownloadError) as caught:
            self.extractor().extract("abcdefghijk", self.info)
        self.assertEqual(caught.exception.code, "unavailable")
        self.assertEqual(FakeYtDlp.asked, [("visionos",)])

    def test_a_fast_client_that_keeps_failing_is_rested_for_an_hour(self):
        FakeYtDlp.fast_error = "ERROR: [youtube] x: Requested format is not available"
        ex = self.extractor(breaker_after=3, breaker_s=3600)
        for _ in range(3):
            ex.extract("abcdefghijk", self.info)
        FakeYtDlp.asked.clear()

        ex.extract("abcdefghijk", self.info)
        self.assertEqual(FakeYtDlp.asked, [()], "the fast client is left out while it rests")

        self.now += 3601
        FakeYtDlp.asked.clear()
        FakeYtDlp.fast_error = None
        ex.extract("abcdefghijk", self.info)
        self.assertEqual(FakeYtDlp.asked, [("visionos",)], "and tried again after the hour")

    def test_a_success_clears_the_count(self):
        ex = self.extractor(breaker_after=3)
        FakeYtDlp.fast_error = "ERROR: [youtube] x: Requested format is not available"
        ex.extract("abcdefghijk", self.info)
        ex.extract("abcdefghijk", self.info)
        FakeYtDlp.fast_error = None
        ex.extract("abcdefghijk", self.info)
        FakeYtDlp.fast_error = "ERROR: [youtube] x: Requested format is not available"
        ex.extract("abcdefghijk", self.info)
        FakeYtDlp.asked.clear()
        ex.extract("abcdefghijk", self.info)
        self.assertEqual(FakeYtDlp.asked[0], ("visionos",), "two failures, a success, two more: not three in a row")


if __name__ == "__main__":
    unittest.main()
