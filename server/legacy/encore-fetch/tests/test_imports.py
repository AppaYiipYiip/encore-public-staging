"""Importing a playlist as a background queue (ADR-100, ADR-101). Each test says what the person sees: the playlist that
appears in their account, the songs it could not find, what happens when YouTube refuses, when the server restarts, when
somebody else is importing too. No network, no real clock: a fake music server, fake downloads, a clock the test moves."""
import json
import tempfile
import unittest
from pathlib import Path

from encore_fetch.download import DownloadError, Downloaded
from encore_fetch.imports import (DONE, MISSING, READY, RUNNING, WAITING, ImportQueue, RefusedImport,
                                  parse_tracks)
from encore_fetch.jobs import JobManager, Limits, Request
from encore_fetch.navidrome import Auth
from encore_fetch.resolve import Candidate, Scored
from encore_fetch.server import Api

from tests.test_pipeline import AUTH, FakeDownloader, FakeNavidrome, InlineExecutor

NINA = Auth("nina", "b" * 32, "salt5678")


class AnySong:
    """A resolver that finds every song (each with its own upload), except the titles it is told are not on YouTube."""

    def __init__(self, missing=()):
        self.missing = set(missing)
        self.asked = []

    def resolve(self, want):
        self.asked.append(want.title)
        if want.title in self.missing:
            return None
        video = f"v{len(self.asked):010d}"
        return Scored(Candidate(video, want.title, f"{want.artist} - Topic", want.duration_s, True), 10.0, ("test",))


class ScriptedDownloader(FakeDownloader):
    """Fails the way it is told, for the titles it is told, a number of times (-1: always)."""

    def __init__(self):
        super().__init__()
        self.script = {}  # video id -> (code, times)
        self.attempts = {}

    def download(self, video_id, stem, duration_s=None, info=None):
        self.attempts[video_id] = self.attempts.get(video_id, 0) + 1
        code, times = self.script.get(video_id, (None, 0))
        if code and (times < 0 or self.attempts[video_id] <= times):
            raise DownloadError(code)
        return super().download(video_id, stem, duration_s, info)


class Library(FakeNavidrome):
    """A music server that lists a song under its own id after a scan, keeps playlists and stars per person."""

    def __init__(self, present=None):
        super().__init__(present=present)
        self.ids = {}
        self.playlists = {}  # person -> {id: (name, [song ids])}
        self.stars = {}
        self.never_lists = set()
        self.refuse_playlists = False

    def find_song(self, auth, *, artist, title, album=None, relative_path=None):
        key = (artist.lower(), title.lower())
        if key in self.present:
            return self.present[key]
        if title in self.never_lists:
            return None
        if relative_path and self.scans:
            self.ids[key] = f"id-{title}"
        return self.ids.get(key)

    def playlist_names(self, auth):
        return [name for name, _ in self.playlists.get(auth.user, {}).values()]

    def create_playlist(self, auth, name, song_ids):
        if self.refuse_playlists:
            return None
        mine = self.playlists.setdefault(auth.user, {})
        pid = f"pl{len(mine) + 1}"
        mine[pid] = (name, list(song_ids))
        return pid

    def add_to_playlist(self, auth, playlist_id, song_ids):
        if self.refuse_playlists:
            return False
        self.playlists[auth.user][playlist_id][1].extend(song_ids)
        return True

    def star(self, auth, song_ids):
        self.stars.setdefault(auth.user, []).extend(song_ids)
        return True

    def songs_in(self, person, name):
        for n, ids in self.playlists.get(person, {}).values():
            if n == name:
                return list(ids)
        return None


def tracks(*titles, artist="Opeth"):
    return [{"title": t, "artist": artist} for t in titles]


class ImportTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "music" / "nina").mkdir(parents=True)
        self.now = 1_000_000.0
        self.nd = Library()
        self.resolver = AnySong()
        self.downloader = ScriptedDownloader()
        self.manager = self.make_manager()
        self.queue = self.make_queue()

    def tick(self, seconds):
        self.now += seconds

    def make_manager(self, **kw):
        return JobManager(
            music_dir=self.root / "music", work_dir=self.root / "work", resolver=self.resolver,
            downloader=self.downloader, navidrome=self.nd, executor=InlineExecutor(), indexer=InlineExecutor(),
            cover=lambda url: None, tagger=lambda p, t, c: True, clock=lambda: self.now,
            sleep=lambda s: self.tick(s), min_free_gb=0, retry_delay_s=1.0, **kw)

    def make_queue(self, **kw):
        kw.setdefault("gap_s", 0.0)
        return ImportQueue(self.manager, self.nd, self.root / "imports", clock=lambda: self.now,
                           sleep=lambda s: self.tick(s), start=False, **kw)

    def run_all(self, queue=None, limit=200):
        queue = queue or self.queue
        for _ in range(limit):
            if not queue.step():
                break
        queue.pump()

    def start(self, titles, *, name="Evening", kind="playlist", auth=NINA, queue=None):
        return (queue or self.queue).create(auth, name=name, kind=kind, source="spotify", tracks=tracks(*titles))


class ThePlaylistAppearsTest(ImportTestBase):
    def test_every_song_arrives_and_the_playlist_has_them_in_the_original_order(self):
        imp = self.start(["Windowpane", "Burden", "Harvest"])
        self.run_all()

        view = self.queue.view(imp)
        self.assertEqual((view["state"], view["total"], view["added"], view["missing"]), (DONE, 3, 3, 0))
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane", "id-Burden", "id-Harvest"])
        self.assertTrue(view["playlistReady"])
        self.assertEqual(view["playlistId"], "pl1")
        self.assertEqual(view["message"], "3 songs in the playlist.")

    def test_the_playlist_exists_after_the_first_song_and_fills_while_the_import_runs(self):
        imp = self.start(["Windowpane", "Burden", "Harvest"])

        self.queue.step()
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane"])
        self.assertEqual(self.queue.view(imp)["state"], RUNNING)
        self.queue.step()
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane", "id-Burden"])

    def test_the_songs_go_to_the_persons_own_library_not_somebody_elses(self):
        # (the layout itself is tested in test_people_layout; here: the queue hands the person's login to the pipeline)
        seen = []
        original = self.manager.submit
        self.manager.submit = lambda auth, request, **kw: (seen.append(auth.user), original(auth, request, **kw))[1]
        self.start(["Windowpane"])
        self.run_all()
        self.assertEqual(seen, ["nina"])

    def test_a_song_the_library_already_has_is_in_the_playlist_without_a_download(self):
        self.nd.present[("opeth", "burden")] = "id-owned"
        imp = self.start(["Windowpane", "Burden"])
        self.run_all()

        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane", "id-owned"])
        self.assertEqual(len(self.downloader.calls), 1)
        self.assertEqual(self.queue.view(imp)["added"], 2)

    def test_a_name_the_person_already_has_gets_a_number_instead_of_a_merge(self):
        self.start(["Windowpane"], name="Evening")
        self.run_all()
        self.start(["Burden"], name="Evening")
        self.run_all()

        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane"])
        self.assertEqual(self.nd.songs_in("nina", "Evening (2)"), ["id-Burden"])

    def test_liked_songs_are_starred_and_no_playlist_is_made(self):
        imp = self.start(["Windowpane", "Burden"], kind="liked", name="")
        self.run_all()

        self.assertEqual(self.nd.stars["nina"], ["id-Windowpane", "id-Burden"])
        self.assertNotIn("nina", self.nd.playlists)
        view = self.queue.view(imp)
        self.assertEqual((view["state"], view["message"], view["name"]), (DONE, "2 songs liked.", "Liked songs"))

    def test_a_music_server_that_refuses_the_playlist_is_asked_again_not_given_up_on(self):
        self.nd.refuse_playlists = True
        imp = self.start(["Windowpane"])
        self.run_all()
        self.assertEqual(self.queue.view(imp)["state"], RUNNING)
        self.assertFalse(self.queue.view(imp)["playlistReady"])

        self.nd.refuse_playlists = False
        self.queue.pump()
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane"])
        self.assertEqual(self.queue.view(imp)["state"], DONE)


class SongsThatAreNotThereTest(ImportTestBase):
    def test_a_song_that_is_not_on_youtube_is_listed_as_missing_and_the_rest_carry_on(self):
        self.resolver.missing = {"Burden"}
        imp = self.start(["Windowpane", "Burden", "Harvest"])
        self.run_all()

        view = self.queue.view(imp)
        self.assertEqual((view["state"], view["added"], view["missing"]), (DONE, 2, 1))
        self.assertEqual(view["missingSongs"], [{
            "title": "Burden", "artist": "Opeth", "reason": "not_found",
            "message": "Nothing matching was found on YouTube."}])
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane", "id-Harvest"])
        self.assertEqual(view["message"], "2 songs in the playlist, 1 could not be added.")

    def test_a_download_that_fails_now_and_then_is_tried_again_before_it_is_called_missing(self):
        self.start(["Windowpane"])
        self.downloader.script["v0000000001"] = ("download_failed", 2)  # the job itself retries once (6 s), so 2 runs
        self.run_all()
        # the first pipeline run fails twice inside the job (its own retry), the queue puts it back, the next run works
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane"])

    def test_a_song_that_keeps_failing_is_missing_after_three_tries(self):
        self.downloader.script["v0000000001"] = ("download_failed", -1)
        imp = self.start(["Windowpane", "Burden"])
        self.run_all()

        view = self.queue.view(imp)
        self.assertEqual((view["added"], view["missing"], view["state"]), (1, 1, DONE))
        self.assertEqual(view["missingSongs"][0]["reason"], "download_failed")
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Burden"])

    def test_a_song_without_an_artist_is_left_out_and_the_person_is_told(self):
        imp = self.queue.create(NINA, name="X", kind="playlist", source="file",
                                tracks=[{"title": "Song"}, {"title": "Windowpane", "artist": "Opeth"}, "junk", {}])
        self.assertEqual(len(imp.items), 1)
        self.assertEqual(self.queue.view(imp)["message"], "3 entries in the list could not be read and were left out.")

    def test_a_downloaded_song_the_music_server_never_lists_is_reported_not_waited_on_for_ever(self):
        self.nd.never_lists.add("Burden")
        imp = self.start(["Windowpane", "Burden", "Harvest"])
        self.run_all()
        # Windowpane is in the playlist; Burden holds the front of the line while the music server has time to list it
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane"])
        self.assertEqual(self.queue.view(imp)["state"], RUNNING)

        self.tick(200)
        self.queue.pump()

        view = self.queue.view(imp)
        self.assertEqual(view["state"], DONE)
        self.assertEqual([m["reason"] for m in view["missingSongs"]], ["not_listed"])
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane", "id-Harvest"])


class WhenYouTubeRefusesTest(ImportTestBase):
    def test_the_queue_rests_and_carries_on_by_itself_and_no_song_is_lost_to_the_refusal(self):
        self.downloader.script["v0000000001"] = ("blocked", 2)  # refused twice (the job's own retry), then it works
        imp = self.start(["Windowpane", "Burden"])

        self.queue.step()  # the refusal
        view = self.queue.view(imp)
        self.assertEqual(view["paused"], "cooling_off")
        self.assertIn("refusing", view["pausedMessage"])
        self.assertEqual(view["done"], 0)
        # nothing starts while it rests
        self.assertFalse(self.queue.step())

        self.tick(100)
        self.run_all()
        view = self.queue.view(imp)
        self.assertEqual((view["state"], view["added"], view["missing"]), (DONE, 2, 0))

    def test_a_song_that_is_refused_again_while_others_arrive_is_that_songs_problem(self):
        self.downloader.script["v0000000001"] = ("blocked", -1)
        self.queue = self.make_queue(cool_base_s=10, cool_max_s=10)
        imp = self.start(["Stuck", "Fine 1", "Fine 2", "Fine 3", "Fine 4", "Fine 5"])
        for _ in range(40):
            self.now = max(self.now, self.queue._cool_until) + 1
            if not self.queue.step():
                self.queue.pump()
                if self.queue.view(imp)["state"] == DONE:
                    break
        view = self.queue.view(imp)
        self.assertEqual((view["state"], view["added"], view["missing"]), (DONE, 5, 1))
        self.assertEqual(view["missingSongs"][0]["title"], "Stuck")
        self.assertEqual(view["missingSongs"][0]["reason"], "blocked")

    def test_a_refused_song_waits_behind_the_others_instead_of_stopping_the_line(self):
        self.downloader.script["v0000000001"] = ("blocked", 2)
        imp = self.start(["First", "Second"])
        self.queue.step()  # First is refused
        self.now = self.queue._cool_until + 1
        self.queue.step()  # the rest is over: Second goes first, First waits its turn
        self.assertEqual([i.state for i in self.queue.get("nina", imp.id).items], [WAITING, READY])
        self.assertIsNone(self.nd.songs_in("nina", "Evening"), "the playlist keeps the original order: First comes first")
        self.run_all()
        self.tick(500)
        self.run_all()
        self.assertEqual(self.queue.view(imp)["added"], 2)
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-First", "id-Second"])

    def test_each_refusal_rests_longer_up_to_a_limit(self):
        self.downloader.script["v0000000001"] = ("blocked", -1)
        self.queue = self.make_queue(cool_base_s=60, cool_max_s=200)
        self.start(["Windowpane"])
        rests = []
        for _ in range(5):
            self.queue.step()
            rests.append(round(self.queue._cool_until - self.now))
            self.now = self.queue._cool_until + 1
        self.assertEqual(rests[:3], [60, 120, 200])
        self.assertEqual(max(rests), 200)

    def test_a_low_disk_pauses_the_queue_and_keeps_the_song(self):
        class Full(ScriptedDownloader):
            full = True

            def download(self, video_id, stem, duration_s=None, info=None):
                if self.full:
                    raise DownloadError("disk_full")
                return super().download(video_id, stem, duration_s, info)

        self.downloader = Full()
        self.manager = self.make_manager()
        self.queue = self.make_queue()
        imp = self.start(["Windowpane"])
        self.queue.step()
        self.assertEqual(self.queue.view(imp)["paused"], "disk_full")
        self.assertEqual(self.queue.view(imp)["missing"], 0)

        self.downloader.full = False
        self.tick(700)
        self.run_all()
        self.assertEqual(self.queue.view(imp)["state"], DONE)


class WhenTheServerRestartsTest(ImportTestBase):
    def test_the_import_is_on_disk_and_carries_on_once_the_app_speaks_and_fetches_nothing_twice(self):
        imp = self.start(["Windowpane", "Burden", "Harvest"])
        self.queue.step()
        fetched = list(self.downloader.calls)
        self.queue.close()

        # a new process: nothing in memory but the files
        again = self.make_queue()
        view = again.view(again.get("nina", imp.id))
        self.assertEqual((view["state"], view["added"], view["paused"]), (RUNNING, 1, "waiting_for_app"))
        self.assertFalse(again.step(), "nothing may be fetched in a person's name before their app has spoken")

        again.touch(NINA)
        self.run_all(again)
        self.assertEqual(self.queue.view(imp)["state"], RUNNING)  # the old object is a dead process
        view = again.view(again.get("nina", imp.id))
        self.assertEqual((view["state"], view["added"]), (DONE, 3))
        self.assertEqual(self.downloader.calls[:1], fetched)
        self.assertEqual(len(self.downloader.calls), 3)
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane", "id-Burden", "id-Harvest"])

    def test_no_login_is_ever_written_to_disk(self):
        self.start(["Windowpane"])
        self.run_all()
        for path in (self.root / "imports").glob("*"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(NINA.token, text)
            self.assertNotIn(NINA.salt, text)

    def test_a_song_in_flight_when_the_process_died_is_fetched_again(self):
        imp = self.start(["Windowpane"])
        imp.items[0].state = "working"
        self.queue._save(imp)
        again = self.make_queue()
        self.assertEqual(again.get("nina", imp.id).items[0].state, WAITING)

    def test_an_unreadable_file_is_left_alone_and_the_others_load(self):
        self.start(["Windowpane"])
        (self.root / "imports" / "broken.json").write_text("{not json", encoding="utf-8")
        again = self.make_queue()
        self.assertEqual(len(again.list("nina")), 1)
        self.assertTrue((self.root / "imports" / "broken.json").exists())

    def test_finished_imports_are_forgotten_after_two_weeks(self):
        imp = self.start(["Windowpane"])
        self.run_all()
        self.now += 15 * 86400
        again = self.make_queue()
        self.assertEqual(again.list("nina"), [])
        self.assertFalse((self.root / "imports" / f"{imp.id}.json").exists())


class SeveralPeopleTest(ImportTestBase):
    def test_a_big_import_does_not_make_somebody_elses_small_one_wait_for_the_end(self):
        (self.root / "music" / "mia").mkdir()
        mia = Auth("mia", "c" * 32, "salt9999")
        big = self.start([f"Big {i}" for i in range(10)], name="Big")
        small = self.start(["Small 1", "Small 2"], name="Small", auth=mia)

        for _ in range(4):
            self.queue.step()
        self.assertEqual(self.queue.view(small)["added"], 2)
        self.assertEqual(self.queue.view(big)["added"], 2)

    def test_one_persons_playlists_come_one_after_another_not_all_at_once(self):
        first = self.start([f"First {i}" for i in range(3)], name="First")
        self.tick(5)
        second = self.start([f"Second {i}" for i in range(3)], name="Second")

        for _ in range(3):
            self.queue.step()
        self.assertEqual((self.queue.view(first)["added"], self.queue.view(second)["added"]), (3, 0))
        self.assertEqual(self.queue.view(first)["state"], DONE)

    def test_nobody_can_see_or_stop_somebody_elses_import(self):
        imp = self.start(["Windowpane"])
        self.assertIsNone(self.queue.get("mia", imp.id))
        self.assertIsNone(self.queue.cancel("mia", imp.id))
        self.assertEqual(self.queue.list("mia"), [])

    def test_an_import_does_not_use_up_the_days_taps(self):
        self.manager = self.make_manager(daily_limit=2, active_limit=1)
        self.queue = self.make_queue()
        imp = self.start([f"Song {i}" for i in range(6)])
        self.run_all()
        self.assertEqual(self.queue.view(imp)["added"], 6)
        # and a tap afterwards still works
        job = self.manager.submit(NINA, Request(artist="Opeth", title="A tap"))
        self.assertEqual(job.state, "ready")
        with self.assertRaises(Limits):
            self.manager.submit(NINA, Request(artist="Opeth", title="Another"))
            self.manager.submit(NINA, Request(artist="Opeth", title="And another"))


class PacingTest(ImportTestBase):
    """YouTube lets a visitor without a login fetch about 300 videos an hour from one address and refused the server after
    about 100 songs in 20 minutes (2026-10-18, the owner's 683-song liked list): the queue stays under an allowance."""

    def test_the_queue_stops_at_the_hourly_allowance_and_goes_on_by_itself(self):
        self.queue = self.make_queue(max_per_hour=3)
        imp = self.start([f"Song {i}" for i in range(6)])
        for _ in range(6):
            self.queue.step()

        view = self.queue.view(imp)
        self.assertEqual((view["added"], view["paused"]), (3, "pacing"))
        self.assertIn("YouTube lets only so many songs through an hour", view["pausedMessage"])

        self.tick(3601)
        self.run_all()
        self.assertEqual(self.queue.view(imp)["added"], 6)

    def test_songs_the_library_already_has_do_not_use_the_allowance(self):
        for i in range(8):
            self.nd.present[("opeth", f"owned {i}")] = f"id-owned-{i}"
        self.queue = self.make_queue(max_per_hour=2)
        imp = self.start([f"Owned {i}" for i in range(8)])
        self.run_all()
        self.assertEqual(self.queue.view(imp)["state"], DONE)
        self.assertEqual(self.downloader.calls, [])

    def test_a_tap_counts_against_the_same_allowance_as_an_import(self):
        # one address, one allowance: a person tapping songs uses the budget of the import running beside it
        self.queue = self.make_queue(max_per_hour=2)
        self.manager.submit(NINA, Request(artist="Opeth", title="Tapped one"))
        self.manager.submit(NINA, Request(artist="Opeth", title="Tapped two"))
        imp = self.start(["Song 1"])
        self.assertFalse(self.queue.step())
        self.assertEqual(self.queue.view(imp)["paused"], "pacing")

    def test_a_refusal_shrinks_the_allowance_and_it_creeps_back_by_the_hour(self):
        self.downloader.script["v0000000001"] = ("blocked", -1)
        self.queue = self.make_queue(max_per_hour=100, cool_base_s=1, cool_max_s=1)
        self.start(["Stuck"])
        self.queue.step()
        self.assertEqual(self.queue._cap, 70)
        self.tick(3601)
        self.assertEqual(self.queue._effective_cap(self.now), 92)
        self.tick(3601)
        self.assertEqual(self.queue._effective_cap(self.now), 100)

    def test_a_burst_of_refusals_is_one_event_not_six(self):
        self.queue = self.make_queue(max_per_hour=200, cool_base_s=1, cool_max_s=1)
        for _ in range(6):
            self.queue._note_refusal()
            self.tick(20)
        self.assertEqual(self.queue._cap, 140, "200 cut once by 30%, not six times to the floor")
        self.tick(700)
        self.queue._note_refusal()
        self.assertEqual(self.queue._cap, 98, "a second episode ten minutes later cuts again")

    def test_a_restart_does_not_make_the_server_forget_what_it_just_fetched_or_that_it_was_refused(self):
        self.queue = self.make_queue(max_per_hour=3, cool_base_s=1, cool_max_s=1)
        self.start(["Song 1", "Song 2", "Song 3", "Song 4"])
        for _ in range(3):
            self.queue.step()
        self.queue._note_refusal()
        self.queue.close()

        # a new process: a new manager and a new queue over the same folder
        self.manager = self.make_manager()
        again = self.make_queue(max_per_hour=3, cool_base_s=1, cool_max_s=1)
        again.touch(NINA)

        self.assertEqual(self.manager.downloads_since(3600), 3, "the three songs of the last hour are remembered")
        self.assertEqual(again._cap, 3, "the allowance was never raised above the setting by a refusal")
        self.assertEqual(again._blocks, 1)
        self.assertFalse(again.step(), "still at the allowance: nothing starts")

    def test_a_damaged_pace_file_is_ignored(self):
        self.start(["Song 1"])
        self.queue.step()
        (self.root / "imports" / "_pace.json").write_text("{nope", encoding="utf-8")
        again = self.make_queue()
        self.assertEqual(again._cap, 200)

    def test_youtube_accounts_lift_the_allowance_to_what_they_allow(self):
        # signed-in accounts have their own, about seven times a visitor's (yt-dlp wiki): the first aim of the YouTube login
        ceiling = {"now": None}
        self.queue = self.make_queue(max_per_hour=3, account_ceiling=lambda: ceiling["now"])
        imp = self.start([f"Song {i}" for i in range(8)])
        for _ in range(8):
            self.queue.step()
        self.assertEqual((self.queue.view(imp)["added"], self.queue.view(imp)["paused"]), (3, "pacing"))

        ceiling["now"] = 10
        self.run_all()
        self.assertEqual(self.queue.view(imp)["added"], 8, "with an account the same hour allows ten")

    def test_an_account_arriving_ends_the_rest_the_visitor_limit_caused(self):
        ceiling = {"now": None}
        self.queue = self.make_queue(max_per_hour=100, cool_base_s=600, cool_max_s=600, account_ceiling=lambda: ceiling["now"])
        self.queue._note_refusal()
        self.start(["Song 1"])
        self.assertFalse(self.queue.step(), "resting after the visitor's refusal")

        ceiling["now"] = 400
        self.assertTrue(self.queue.step(), "an account has its own allowance: no reason to keep resting")
        self.assertEqual(self.queue._effective_cap(self.now), 400)

    def test_when_the_accounts_go_the_visitor_allowance_comes_back(self):
        ceiling = {"now": 10}
        self.queue = self.make_queue(max_per_hour=3, account_ceiling=lambda: ceiling["now"])
        self.assertEqual(self.queue._effective_cap(self.now), 10)
        ceiling["now"] = None
        self.assertEqual(self.queue._effective_cap(self.now), 3)

    def test_a_second_account_adds_its_allowance_and_a_resting_one_takes_it_away(self):
        ceiling = {"now": 400}
        self.queue = self.make_queue(max_per_hour=200, account_ceiling=lambda: ceiling["now"])
        self.assertEqual(self.queue._effective_cap(self.now), 400)
        ceiling["now"] = 800
        self.assertEqual(self.queue._effective_cap(self.now), 800)
        ceiling["now"] = 400
        self.assertEqual(self.queue._effective_cap(self.now), 400)

    def test_a_refusal_of_one_account_does_not_rest_the_queue_while_another_account_has_room(self):
        self.queue = self.make_queue(max_per_hour=100, cool_base_s=600, cool_max_s=600, account_ceiling=lambda: 400)
        self.queue._note_refusal("account-1")
        self.start(["Song 1"])
        self.assertTrue(self.queue.step(), "that account rests by itself; the queue carries on with the others")

    def test_a_refusal_with_no_account_left_rests_the_queue_as_before(self):
        ceiling = {"now": 400}
        self.queue = self.make_queue(max_per_hour=100, cool_base_s=600, cool_max_s=600, account_ceiling=lambda: ceiling["now"])
        ceiling["now"] = None  # the only account is resting now
        self.queue._note_refusal("account-1")
        self.start(["Song 1"])
        self.assertFalse(self.queue.step())

    def test_a_refusal_of_a_visitor_run_rests_the_queue_even_when_accounts_exist(self):
        self.queue = self.make_queue(max_per_hour=100, cool_base_s=600, cool_max_s=600, account_ceiling=lambda: 400)
        self.queue._note_refusal(None)
        self.start(["Song 1"])
        self.assertFalse(self.queue.step())

    def test_accounts_that_cannot_be_looked_at_count_as_none(self):
        def broken():
            raise OSError("disk gone")

        self.queue = self.make_queue(max_per_hour=3, account_ceiling=broken)
        self.assertEqual(self.queue._effective_cap(self.now), 3)

    def test_the_manager_tells_the_queue_which_account_was_refused(self):
        seen = []
        self.manager.refusal_listener = seen.append

        def refuse(video_id, stem, duration_s=None, info=None):
            raise DownloadError("blocked", account="account-1")

        self.downloader.download = refuse
        self.manager.submit(NINA, Request(artist="Opeth", title="A tapped song"))
        self.assertEqual(seen, ["account-1"])

    def test_a_slow_import_says_who_can_make_it_faster_only_while_nobody_is_signed_in(self):
        ceiling = {"now": None}
        self.queue = self.make_queue(max_per_hour=1, account_ceiling=lambda: ceiling["now"])
        imp = self.start(["Song 1", "Song 2", "Song 3"])
        for _ in range(3):
            self.queue.step()
        self.assertIn("server's owner signs it in to YouTube", self.queue.view(imp)["pausedMessage"])
        ceiling["now"] = 1
        self.queue.step()
        self.assertEqual(self.queue.view(imp)["paused"], "pacing")
        self.assertNotIn("owner", self.queue.view(imp)["pausedMessage"])

    def test_a_tap_that_is_refused_makes_the_import_rest_too(self):
        imp = self.start(["Song 1", "Song 2"])
        self.downloader.script["v0000000001"] = ("blocked", -1)
        self.manager.submit(NINA, Request(artist="Opeth", title="A tapped song"))  # refused by YouTube

        self.assertFalse(self.queue.step(), "the import must not carry on into a refusal")
        self.assertEqual(self.queue.view(imp)["paused"], "cooling_off")


class NotSongsTest(ImportTestBase):
    """A YouTube Music liked list holds concerts and hour-long videos (the owner's did)."""

    def test_a_song_of_twenty_five_or_thirty_five_minutes_is_a_song_an_hour_long_video_is_not(self):
        # the owner, 2026-10-18: "I know bands that have songs that are 25 min or even 35 min"
        imp = self.queue.create(NINA, name="liked", kind="playlist", source="youtube", tracks=[
            {"title": "A song", "artist": "Opeth", "durationSec": 240},
            {"title": "A long epic", "artist": "Neal Morse", "durationSec": 2000},
            {"title": "An even longer epic", "artist": "Edge of Sanity", "durationSec": 2400},
            {"title": "Death Stranding ambience", "artist": "Video Game Worlds", "durationSec": 3700},
            {"title": "Unknown length", "artist": "Opeth"}])
        self.run_all()

        view = self.queue.view(imp)
        self.assertEqual((view["state"], view["added"], view["missing"]), (DONE, 4, 1))
        self.assertEqual([m["title"] for m in view["missingSongs"]], ["Death Stranding ambience"])
        self.assertEqual({m["reason"] for m in view["missingSongs"]}, {"too_long"})
        self.assertIn("Too long to be treated as a song", view["missingSongs"][0]["message"])
        self.assertNotIn("Death Stranding ambience", self.resolver.asked)

    def test_a_song_wrongly_left_out_by_the_old_limit_comes_back_when_it_is_next_in_line(self):
        imp = self.start(["First"])
        late = type(imp.items[0])(title="Epic", artist="Band", duration_s=2000, state=MISSING, reason="too_long")
        imp.items.append(late)
        self.run_all()
        view = self.queue.view(imp)
        self.assertEqual((view["state"], view["added"], view["missing"]), (DONE, 2, 0))

    def test_an_import_made_before_the_rule_is_held_to_it_when_it_is_next_in_line(self):
        imp = self.start(["Early"])
        imp.items.append(type(imp.items[0])(title="Concert", artist="Band", duration_s=5000))
        self.run_all()
        view = self.queue.view(imp)
        self.assertEqual((view["state"], view["added"], view["missing"]), (DONE, 1, 1))
        self.assertNotIn("Concert", self.resolver.asked)

    def test_a_list_of_nothing_but_long_videos_is_over_at_once(self):
        imp = self.queue.create(NINA, name="x", kind="playlist", source="youtube", tracks=[
            {"title": "Concert", "artist": "Band", "durationSec": 5000}])
        self.queue.pump()
        self.assertEqual(self.queue.view(imp)["state"], DONE)


class SkippingSongsTest(ImportTestBase):
    """A 683-song list has songs the person does not want: they are never fetched, and are not "not found"."""

    def test_a_song_not_fetched_yet_can_be_dropped_and_is_never_fetched(self):
        imp = self.start(["Keep 1", "Drop me", "Keep 2"])
        self.queue.skip("nina", imp.id, [1])
        self.run_all()

        view = self.queue.view(imp)
        self.assertEqual((view["state"], view["added"], view["missing"], view["skipped"]), (DONE, 2, 0, 1))
        self.assertEqual(view["missingSongs"], [], "a song the person dropped is not a song that was not found")
        self.assertNotIn("Drop me", self.resolver.asked)
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Keep 1", "id-Keep 2"])
        self.assertEqual(view["message"], "2 songs in the playlist.")

    def test_a_song_already_in_the_library_is_left_alone(self):
        imp = self.start(["First", "Second"])
        self.queue.step()
        self.queue.skip("nina", imp.id, [0, 1])
        view = self.queue.view(imp)
        self.assertEqual((view["added"], view["skipped"]), (1, 1))

    def test_the_whole_list_says_which_songs_were_dropped(self):
        imp = self.start(["A", "B"])
        self.queue.skip("nina", imp.id, [1])
        songs = self.queue.view(imp, songs=True)["songs"]
        self.assertEqual((songs[1]["state"], songs[1]["reason"], songs[1]["message"]),
                         ("missing", "skipped", "You chose not to import this song."))

    def test_bad_numbers_are_refused_and_nobody_can_drop_somebody_elses_songs(self):
        imp = self.start(["A", "B"])
        for bad in ([5], [-1], ["0"], [True], "0", None):
            with self.assertRaises(RefusedImport):
                self.queue.skip("nina", imp.id, bad)
        self.assertIsNone(self.queue.skip("mia", imp.id, [0]))

    def test_over_the_route(self):
        api = Api(self.manager, self.nd, imports=self.queue)
        q = "?u=nina&t=" + "b" * 32 + "&s=salt5678"
        _, made = api.handle("POST", "/api/import" + q, {}, json.dumps({"name": "X", "tracks": tracks("A", "B")}).encode())
        status, body = api.handle("POST", f"/api/import/{made['id']}/skip" + q, {}, b'{"indexes": [1]}')
        self.assertEqual((status, body["skipped"], body["waiting"]), (200, 1, 1))
        self.assertEqual(api.handle("POST", f"/api/import/{made['id']}/skip" + q, {}, b'{"indexes": [9]}')[0], 400)
        self.assertEqual(api.handle("GET", f"/api/import/{made['id']}/skip" + q, {}, b"")[0], 405)


class StoppingAndLimitsTest(ImportTestBase):
    def test_stopping_keeps_what_arrived_and_fetches_no_more(self):
        imp = self.start(["Windowpane", "Burden", "Harvest"])
        self.queue.step()
        self.queue.cancel("nina", imp.id)

        self.assertFalse(self.queue.step())
        view = self.queue.view(imp)
        self.assertEqual((view["state"], view["added"], view["waiting"]), ("cancelled", 1, 2))
        self.assertEqual(self.nd.songs_in("nina", "Evening"), ["id-Windowpane"])

    def test_a_list_that_is_empty_or_far_too_long_is_refused_with_a_sentence(self):
        with self.assertRaises(RefusedImport) as empty:
            self.queue.create(NINA, name="x", kind="playlist", source="file", tracks=[])
        self.assertEqual((empty.exception.status, empty.exception.code), (422, "empty"))
        with self.assertRaises(RefusedImport) as many:
            parse_tracks([{"title": "t", "artist": "a"}] * 5001)
        self.assertEqual(many.exception.status, 413)
        with self.assertRaises(RefusedImport):
            parse_tracks("not a list")

    def test_an_official_upload_is_kept_only_with_a_real_video_id(self):
        items, _ = parse_tracks([
            {"title": "A", "artist": "X", "videoId": "sj27caXHKm4", "official": True},
            {"title": "B", "artist": "X", "official": True},
            {"title": "C", "artist": "X", "videoId": "sj27caXHKm4", "official": "yes"},
        ])
        self.assertEqual([i.official for i in items], [True, False, False])

    def test_an_official_upload_goes_to_the_pipeline_first_and_survives_a_restart(self):
        imp = self.queue.create(NINA, name="X", kind="playlist", source="youtube", tracks=[
            {"title": "Windowpane", "artist": "Opeth", "videoId": "sj27caXHKm4", "official": True}])
        self.queue.step()
        self.assertEqual(self.downloader.calls, ["sj27caXHKm4"])
        self.assertEqual(self.resolver.asked, [], "no search for an official upload")
        self.assertTrue(self.queue.get("nina", imp.id).items[0].official)
        again = self.make_queue()
        self.assertTrue(again.get("nina", imp.id).items[0].official)

    def test_odd_text_in_a_title_is_cleaned_or_refused_never_passed_on(self):
        items, skipped = parse_tracks([
            {"title": "  Two   spaces \n here ", "artist": "A"},
            {"title": "bell\x07", "artist": "A"},
            {"title": "x" * 300, "artist": "A"},
            {"title": "ok", "artist": "A", "videoId": "not an id", "durationSec": 99999},
        ])
        self.assertEqual([i.title for i in items], ["Two spaces here", "ok"])
        self.assertEqual(skipped, 2)
        self.assertIsNone(items[1].video_id)
        self.assertIsNone(items[1].duration_s)

    def test_a_person_cannot_pile_up_endless_imports(self):
        for _ in range(12):
            self.start(["Windowpane"])
        with self.assertRaises(RefusedImport) as refused:
            self.start(["Windowpane"])
        self.assertEqual(refused.exception.status, 429)

    def test_the_estimate_comes_from_how_long_songs_really_took(self):
        self.queue = self.make_queue(max_per_hour=100000)  # the allowance does not matter here
        imp = self.start([f"Song {i}" for i in range(10)])
        self.assertEqual(self.queue.view(imp)["etaSec"], int(10 * (14 + 0) / 2))  # nothing measured yet: 14 s a song
        imp.took = [20.0, 20.0]
        self.assertEqual(self.queue.view(imp)["etaSec"], 100)

    def test_the_estimate_is_never_quicker_than_the_hourly_allowance(self):
        imp = self.start([f"Song {i}" for i in range(10)])  # 200 an hour: 18 s a song at the quickest
        imp.took = [4.0, 4.0]
        self.assertEqual(self.queue.view(imp)["etaSec"], 180)


class TheRoutesTest(ImportTestBase):
    def setUp(self):
        super().setUp()
        self.api = Api(self.manager, self.nd, imports=self.queue)
        self.q = "?u=nina&t=" + "b" * 32 + "&s=salt5678"

    def call(self, method, path, body=None, query=None):
        raw = json.dumps(body).encode() if body is not None else b""
        status, payload = self.api.handle(method, path + (self.q if query is None else query), {}, raw)
        return status, payload

    def test_the_service_says_it_can_import(self):
        self.assertIn("import", self.api.handle("GET", "/api/info", {})[1]["features"])
        self.assertNotIn("import", Api(self.manager, self.nd).handle("GET", "/api/info", {})[1]["features"])

    def test_handing_over_a_list_answers_at_once_and_the_person_can_watch_it(self):
        status, body = self.call("POST", "/api/import", {"name": "Evening", "kind": "playlist", "source": "youtube",
                                                         "tracks": tracks("Windowpane", "Burden")})
        self.assertEqual(status, 202)
        self.assertEqual((body["name"], body["total"], body["state"], body["added"]), ("Evening", 2, RUNNING, 0))

        self.run_all()
        status, body = self.call("GET", f"/api/import/{body['id']}")
        self.assertEqual((status, body["state"], body["added"], body["playlistReady"]), (200, DONE, 2, True))

    def test_the_whole_list_can_be_asked_for_with_where_each_song_is(self):
        self.resolver.missing = {"Burden"}
        _, made = self.call("POST", "/api/import", {"name": "Evening", "tracks": [
            {"title": "Windowpane", "artist": "Opeth", "album": "Damnation", "durationSec": 467},
            {"title": "Burden", "artist": "Opeth"},
            {"title": "Harvest", "artist": "Opeth", "videoId": "sj27caXHKm4", "official": True}]})
        self.queue.step()
        self.queue.step()
        _, plain = self.call("GET", f"/api/import/{made['id']}")
        self.assertNotIn("songs", plain, "the list is only sent when it is asked for")

        status, body = self.api.handle("GET", f"/api/import/{made['id']}" + self.q + "&songs=1", {}, b"")

        self.assertEqual(status, 200)
        self.assertEqual([(s["title"], s["state"]) for s in body["songs"]],
                         [("Windowpane", "ready"), ("Burden", "missing"), ("Harvest", "waiting")])
        self.assertEqual(body["songs"][0]["album"], "Damnation")
        self.assertEqual(body["songs"][1]["reason"], "not_found")
        self.assertEqual(body["songs"][1]["message"], "Nothing matching was found on YouTube.")
        self.assertEqual((body["songs"][2]["videoId"], body["songs"][2]["official"]), ("sj27caXHKm4", True))

    def test_the_list_of_imports_is_short_and_newest_first(self):
        self.call("POST", "/api/import", {"name": "One", "tracks": tracks("A")})
        self.tick(5)
        self.call("POST", "/api/import", {"name": "Two", "tracks": tracks("B")})
        status, body = self.call("GET", "/api/import")
        self.assertEqual([i["name"] for i in body["imports"]], ["Two", "One"])
        self.assertTrue(all("missingSongs" not in i for i in body["imports"]))

    def test_it_needs_the_music_login(self):
        self.nd.valid = False
        self.assertEqual(self.call("POST", "/api/import", {"tracks": tracks("A")})[0], 401)
        self.assertEqual(self.call("GET", "/api/import", query="")[0], 401)

    def test_somebody_elses_import_is_not_found(self):
        _, mine = self.call("POST", "/api/import", {"name": "Mine", "tracks": tracks("A")})
        self.q = "?u=mia&t=" + "c" * 32 + "&s=salt9999"
        self.assertEqual(self.call("GET", f"/api/import/{mine['id']}")[0], 404)
        self.assertEqual(self.call("POST", f"/api/import/{mine['id']}/cancel")[0], 404)

    def test_cancelling_over_the_route(self):
        _, mine = self.call("POST", "/api/import", {"name": "Mine", "tracks": tracks("A", "B")})
        status, body = self.call("POST", f"/api/import/{mine['id']}/cancel")
        self.assertEqual((status, body["state"]), (200, "cancelled"))

    def test_bad_requests_are_answered_with_a_word_and_a_sentence(self):
        status, body = self.call("POST", "/api/import", {"tracks": []})
        self.assertEqual((status, body["error"]), (422, "empty"))
        self.assertTrue(body["message"])
        self.assertEqual(self.call("POST", "/api/import", {"name": "x"})[0], 400)
        self.assertEqual(self.api.handle("POST", "/api/import" + self.q, {}, b"[1]")[0], 400)
        self.assertEqual(self.api.handle("POST", "/api/import" + self.q, {}, b"{")[0], 400)
        self.assertEqual(self.call("GET", "/api/import/zzzz")[0], 404)
        self.assertEqual(self.call("DELETE", "/api/import")[0], 405)

    def test_the_apps_call_is_what_lets_a_restarted_server_carry_on(self):
        _, made = self.call("POST", "/api/import", {"name": "Mine", "tracks": tracks("A")})
        self.queue.close()
        self.queue = self.make_queue()
        self.api = Api(self.manager, self.nd, imports=self.queue)
        self.assertFalse(self.queue.step())
        status, body = self.call("GET", f"/api/import/{made['id']}")  # the app asks how it is going
        self.assertEqual(status, 200)
        self.assertTrue(self.queue.step())


if __name__ == "__main__":
    unittest.main()
