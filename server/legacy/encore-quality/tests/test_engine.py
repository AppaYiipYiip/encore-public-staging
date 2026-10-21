"""The journey of a request, as the person lives it: asked for, waiting, found, swapped, or told honestly why not (docs/46 sections 1 and 3)."""
import os
import tempfile
import unittest
from pathlib import Path

from encore_quality import store
from encore_quality.engine import DAY, Engine, Limits
from encore_quality.lidarr import Lidarr
from encore_quality.navidrome import Navidrome
from encore_quality.slskd import Slskd
from encore_quality.store import Store
from encore_quality.wiring import Wiring

from tests.fakes import FakeLidarr, FakeNavidrome

POOL = "/music/.encore/pool"
TRACKS = [("Silvera", 229), ("Magma", 440), ("Stranded", 254)]


def lookup_album(title="Magma", artist="Gojira", rg="rg-magma", mb_artist="mb-gojira", date="2016-06-17T00:00:00Z", kind="Album"):
    return {"title": title, "artist": {"artistName": artist, "foreignArtistId": mb_artist}, "foreignAlbumId": rg, "albumType": kind,
            "releaseDate": date, "secondaryTypes": [], "releases": [{}]}


class FakeSlskd:
    def __init__(self):
        self.busy = False
        self.connected = True

    def __call__(self, method, path, body=None):
        if path == "/transfers/downloads":
            files = [{"state": "InProgress"}] if self.busy else [{"state": "Completed, Succeeded"}]
            return 200, [{"username": "peer", "directories": [{"directory": "share\\Gojira - Magma (2016) [FLAC]", "files": files}]}]
        return 404, None


class World(unittest.TestCase):
    """A music folder with one quick copy in it, a music server that reads it, a Lidarr that knows Magma, and a clock."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.music = Path(self._tmp.name) / "music"
        self.now = 1_760_000_000.0
        self.quick_rel = "Gojira/Magma/03 - Silvera.opus"
        (self.music / self.quick_rel).parent.mkdir(parents=True)
        (self.music / self.quick_rel).write_bytes(b"quick")
        self.nd_fake = FakeNavidrome(self.music)
        self.song_id = self.nd_fake.add_song(self.quick_rel, title="Silvera", artist="Gojira", album="Magma", track=3, duration=229.0,
                                             year=2016)
        self.nd = Navidrome("http://nd", admin_user="owner", admin_password="owner-pw", transport=self.nd_fake)
        self.lidarr_fake = FakeLidarr()
        self.lidarr_fake.catalog = [lookup_album()]
        self.lidarr = Lidarr(self.lidarr_fake)
        self.slskd_fake = FakeSlskd()
        self.store = Store(":memory:", lambda: self.now)
        self.addCleanup(self.store.close)
        self.soulseek = True
        self.free = 500 * 1024 ** 3
        self.wiring: Wiring | None = Wiring(quality_id=1, metadata_id=1, pool=POOL)
        self.limits = Limits()
        self.engine = self.make_engine()

    def make_engine(self) -> Engine:
        return Engine(store=self.store, lidarr=self.lidarr, navidrome=self.nd, music=self.music, wiring=lambda: self.wiring,
                      slskd=Slskd(self.slskd_fake), limits=self.limits, soulseek_on=lambda: self.soulseek, clock=lambda: self.now,
                      free_bytes=lambda path: self.free)

    # -- helpers
    def ask(self, person="sam", song_id=None, rel=None, **kw):
        file = self.nd.file_of(song_id or self.song_id)
        want, _ = self.store.add_want(person=person, song_id=file.id, artist=kw.get("artist", file.artist), album=kw.get("album", file.album),
                                      title=kw.get("title", file.title), year=file.year, track=file.track, duration=file.duration,
                                      quick_path=rel or file.path)
        return want

    def state(self, want):
        return self.store.get(want.id).state

    def step(self, times=1):
        for _ in range(times):
            self.engine.step()

    def pool_file(self, name="03 - Silvera.flac"):
        path = self.music / ".encore/pool/Gojira/Magma (2016)" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"F" * 4000)
        return path

    def learn_album(self, artist_id=None, tracks=TRACKS, **extra):
        """Lidarr finishes learning the artist: the album and its tracks exist."""
        artist_id = artist_id or self.lidarr_fake.artists[0]["id"]
        album_id = self.lidarr_fake.add_album(artist_id, "Magma", tracks, foreignAlbumId="rg-magma", **extra)
        self.lidarr_fake.finish_refresh(artist_id)
        return album_id

    def arrive(self, album_id):
        """Soularr and Lidarr have filed the album in the pool (and the files are really there)."""
        files = self.lidarr_fake.import_album(album_id, POOL + "/Gojira/Magma (2016)")
        for file in files:
            self.pool_file(os.path.basename(file["path"]))

    def journey_to_searching(self):
        want = self.ask()
        self.step()  # matched, artist added
        album_id = self.learn_album()
        self.step()  # wanted
        return want, album_id


class TheHappyJourney(World):
    def test_a_new_request_is_matched_and_lidarr_is_asked_about_the_artist(self):
        want = self.ask()
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.GETTING_READY)
        self.assertEqual(got.release_group, "rg-magma")
        self.assertIn("a few minutes", got.detail)
        artist = self.lidarr_fake.artists[0]
        self.assertEqual(artist["foreignArtistId"], "mb-gojira")
        self.assertTrue(artist["monitored"])
        self.assertEqual(artist["monitorNewItems"], "none", "the whole discography is not wanted")
        self.assertEqual(artist["addOptions"], {"monitor": "none", "searchForMissingAlbums": False})

    def test_while_the_artists_releases_load_it_says_so_and_nothing_is_wanted_yet(self):
        want = self.ask()
        self.step()
        self.step(3)
        self.assertEqual(self.state(want), store.GETTING_READY)
        self.assertEqual([m for m in self.lidarr_fake.calls if m == ("PUT", "/album/monitor")], [])

    def test_once_the_releases_are_known_exactly_that_album_is_wanted_and_no_other(self):
        want = self.ask()
        self.step()
        artist_id = self.lidarr_fake.artists[0]["id"]
        other = self.lidarr_fake.add_album(artist_id, "From Mars to Sirius", [("Ocean Planet", 200)], foreignAlbumId="rg-other")
        wanted = self.learn_album()
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.SEARCHING)
        self.assertEqual(got.lidarr_album, wanted)
        self.assertTrue(self.lidarr_fake.albums[wanted]["monitored"])
        self.assertFalse(self.lidarr_fake.albums[other]["monitored"], "only the one album")
        self.assertGreater(got.next_try, self.now, "a deadline for giving up is set")

    def test_when_the_album_arrives_the_better_copy_takes_the_place_of_the_quick_one(self):
        want, album_id = self.journey_to_searching()
        self.arrive(album_id)
        self.step()  # delivering: placed, the music server told to look
        self.step()  # the music server has noticed
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.READY, got.detail)
        self.assertIn("FLAC", got.detail)
        self.assertFalse((self.music / self.quick_rel).exists())
        flac = self.music / "Gojira/Magma/03 - Silvera.flac"
        self.assertTrue(flac.exists())
        self.assertEqual(flac.stat().st_nlink, 2, "a second name for the pool file: the disk is used once")
        self.assertTrue((self.music / ".encore/replaced" / self.quick_rel).exists(), "the way back is kept")

    def test_the_swap_is_published_so_a_phone_can_move_its_likes_and_playlist_places(self):
        want, album_id = self.journey_to_searching()
        self.arrive(album_id)
        self.step(2)
        new_id = self.store.get(want.id).new_song_id
        self.assertNotEqual(new_id, self.song_id, "the music server gives the new file a new id (docs/46 S1)")
        self.assertEqual(self.store.upgrades_after(0), [{"n": 1, "old": self.song_id, "new": new_id, "quality": "FLAC", "at": self.now}])

    def test_peers_sending_the_album_is_told_as_downloading(self):
        want, album_id = self.journey_to_searching()
        self.slskd_fake.busy = True
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.DOWNLOADING)
        self.assertEqual(got.detail, "Downloading it now.")
        self.slskd_fake.busy = False
        self.step()
        self.assertEqual(self.state(want), store.SEARCHING)

    def test_a_song_that_is_already_in_the_better_quality_is_left_alone(self):
        (self.music / "Gojira/Magma").mkdir(parents=True, exist_ok=True)
        (self.music / "Gojira/Magma/01 - Already.flac").write_bytes(b"f")
        flac_id = self.nd_fake.add_song("Gojira/Magma/01 - Already.flac", title="Already", artist="Gojira", album="Magma", bit_rate=1000)
        want = self.ask(song_id=flac_id)
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.READY)
        self.assertIn("Already", got.detail)
        self.assertEqual(self.lidarr_fake.artists, [], "Lidarr was not even asked")

    def test_a_320_kbps_file_is_good_enough(self):
        self.nd_fake.songs[self.song_id]["bitRate"] = 320
        want = self.ask()
        self.step()
        self.assertEqual(self.state(want), store.READY)

    def test_an_artist_lidarr_already_knows_is_not_added_again(self):
        first = self.ask()
        self.step()
        self.learn_album()
        self.step()
        (self.music / "Gojira/Magma/02 - Magma.opus").write_bytes(b"x")
        second_song = self.nd_fake.add_song("Gojira/Magma/02 - Magma.opus", title="Magma", artist="Gojira", album="Magma", track=2,
                                            duration=440.0)
        second = self.ask(song_id=second_song)
        adds_before = len([c for c in self.lidarr_fake.calls if c == ("POST", "/artist")])
        self.step()
        self.assertEqual(len([c for c in self.lidarr_fake.calls if c == ("POST", "/artist")]), adds_before)
        self.assertEqual(self.store.get(second.id).lidarr_artist, self.lidarr_fake.artists[0]["id"])
        self.assertEqual(len(self.lidarr_fake.artists), 1)


class WhenItCannotStartYet(World):
    def test_without_soulseek_switched_on_requests_wait_and_nothing_goes_to_lidarr(self):
        self.soulseek = False
        want = self.ask()
        self.step(3)
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.QUEUED)
        self.assertIn("not switched on", got.detail)
        self.assertEqual(self.lidarr_fake.artists, [])
        self.soulseek = True
        self.step()
        self.assertEqual(self.state(want), store.GETTING_READY, "it starts by itself the moment the owner says yes")

    def test_when_the_quality_tools_do_not_answer_the_request_waits_and_no_try_is_used_up(self):
        self.lidarr_fake.down = True
        want = self.ask()
        self.step(5)
        got = self.store.get(want.id)
        self.assertEqual((got.state, got.attempts), (store.QUEUED, 0))
        self.assertIn("starting up", got.detail)
        self.lidarr_fake.down = False
        self.step()
        self.assertEqual(self.state(want), store.GETTING_READY)

    def test_before_the_wiring_is_done_requests_wait(self):
        self.wiring = None
        want = self.ask()
        self.step()
        self.assertEqual(self.state(want), store.QUEUED)

    def test_the_daily_limit_of_albums_holds_the_rest_until_tomorrow(self):
        self.limits = Limits(daily_cap=1)
        self.engine = self.make_engine()
        first = self.ask()
        self.step()
        (self.music / "Tool/Lateralus").mkdir(parents=True)
        (self.music / "Tool/Lateralus/01 - Schism.opus").write_bytes(b"x")
        other = self.nd_fake.add_song("Tool/Lateralus/01 - Schism.opus", title="Schism", artist="Tool", album="Lateralus")
        self.lidarr_fake.catalog = [lookup_album("Lateralus", "Tool", "rg-lat", "mb-tool", "2001-05-14T00:00:00Z")]
        second = self.ask(song_id=other)
        self.step()
        got = self.store.get(second.id)
        self.assertEqual(got.state, store.QUEUED)
        self.assertIn("Today's limit", got.detail)
        self.learn_album()  # the first artist finishes loading, so the only thing holding the second back is the limit
        self.step()
        self.assertEqual(self.state(second), store.QUEUED, "still today")
        self.now += DAY
        self.step()
        self.assertEqual(self.state(second), store.GETTING_READY, "tomorrow it goes on")
        self.assertEqual(self.state(first), store.SEARCHING)

    def test_when_the_disk_is_almost_full_no_new_albums_are_asked_for(self):
        self.free = 1 * 1024 ** 3
        want = self.ask()
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.QUEUED)
        self.assertIn("out of space", got.detail)
        self.assertEqual(self.lidarr_fake.artists, [])

    def test_only_one_new_artist_loads_at_a_time_because_each_takes_minutes(self):
        first = self.ask()
        self.step()
        (self.music / "Tool/Lateralus").mkdir(parents=True)
        (self.music / "Tool/Lateralus/01 - Schism.opus").write_bytes(b"x")
        other = self.nd_fake.add_song("Tool/Lateralus/01 - Schism.opus", title="Schism", artist="Tool", album="Lateralus")
        self.lidarr_fake.catalog = [lookup_album("Lateralus", "Tool", "rg-lat", "mb-tool", "2001-05-14T00:00:00Z")]
        second = self.ask(song_id=other)
        self.step()
        self.assertEqual(self.state(second), store.QUEUED)
        self.assertIn("Waiting its turn", self.store.get(second.id).detail)
        self.assertEqual(len(self.lidarr_fake.artists), 1)
        self.learn_album()
        self.step()
        self.step()
        self.assertEqual(self.state(second), store.GETTING_READY, "the first artist is done, so the next may start")
        self.assertEqual(len(self.lidarr_fake.artists), 2)

    def test_the_new_artist_wait_works_whichever_way_lidarr_names_the_running_refresh(self):
        for style in ("ids", "one", "none"):
            self.lidarr_fake.refresh_seen_as = style
            self.assertTrue(self.lidarr.refreshing(5) is False)
            self.lidarr_fake.refreshing.add(5)
            self.assertTrue(self.lidarr.refreshing(5), style)
            self.lidarr_fake.refreshing.discard(5)


class WhenItCannotBeMatched(World):
    def test_an_album_the_catalogue_does_not_have_is_said_in_plain_words_and_nothing_is_added(self):
        self.lidarr_fake.catalog = []
        want = self.ask()
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.NO_MATCH)
        self.assertIn("catalogue", got.detail)
        self.assertEqual(self.lidarr_fake.artists, [])

    def test_another_artists_album_with_the_same_name_is_never_taken(self):
        self.lidarr_fake.catalog = [lookup_album(artist="Some Cover Band", mb_artist="mb-cover")]
        want = self.ask()
        self.step()
        self.assertEqual(self.state(want), store.NO_MATCH)
        self.assertEqual(self.lidarr_fake.artists, [])

    def test_a_song_that_is_not_on_the_album_found_is_a_different_edition_and_is_not_swapped(self):
        want = self.ask()
        self.step()
        self.learn_album(tracks=[("Something Else", 200), ("Another", 210)])
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.NO_MATCH)
        self.assertIn("different edition", got.detail)
        self.assertTrue((self.music / self.quick_rel).exists())

    def test_a_song_a_different_length_is_a_different_edition_and_is_not_swapped(self):
        want, album_id = self.journey_to_searching()
        self.lidarr_fake.tracks[album_id][0]["duration"] = 262_000  # 33 s longer than the quick copy
        self.arrive(album_id)
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.NO_MATCH)
        self.assertIn("different length", got.detail)
        self.assertTrue((self.music / self.quick_rel).exists(), "the quick copy stays")
        self.assertEqual(self.store.upgrades_after(0), [])

    def test_a_length_within_a_few_seconds_is_the_same_song(self):
        want, album_id = self.journey_to_searching()
        self.lidarr_fake.tracks[album_id][0]["duration"] = 231_500
        self.arrive(album_id)
        self.step(2)
        self.assertEqual(self.state(want), store.READY)

    def test_a_song_removed_from_the_library_meanwhile_is_a_plain_failure(self):
        want = self.ask()
        del self.nd_fake.songs[self.song_id]
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.FAILED)
        self.assertIn("not in the library", got.detail)

    def test_a_single_is_found_by_the_songs_own_name(self):
        self.lidarr_fake.catalog = [lookup_album("Silvera", "Gojira", "rg-single", kind="Single", date="2016-05-20T00:00:00Z")]
        want = self.ask(album="Silvera - Single")
        self.step()
        self.assertEqual(self.store.get(want.id).release_group, "rg-single")


class WhenNobodyHasIt(World):
    def test_after_a_week_of_looking_it_is_not_found_and_lidarr_is_told_to_stop_asking(self):
        want, album_id = self.journey_to_searching()
        self.now += 6 * DAY
        self.step()
        self.assertEqual(self.state(want), store.SEARCHING)
        self.now += 2 * DAY
        self.step()
        got = self.store.get(want.id)
        self.assertEqual((got.state, got.attempts), (store.NOT_FOUND, 1))
        self.assertIn("look again in a week", got.detail)
        self.assertFalse(self.lidarr_fake.albums[album_id]["monitored"])

    def test_it_is_looked_for_again_a_week_later_and_a_third_failure_is_final(self):
        want, album_id = self.journey_to_searching()
        for attempt in (1, 2):
            self.now += 8 * DAY
            self.step()
            self.assertEqual(self.state(want), store.NOT_FOUND)
            self.assertEqual(self.store.get(want.id).attempts, attempt)
            self.now += 8 * DAY
            self.step()  # a week on: back in the queue and matched again (the artist is known)
            self.assertEqual(self.state(want), store.GETTING_READY)
            self.step()  # the album is wanted again
            self.assertEqual(self.state(want), store.SEARCHING)
            self.assertTrue(self.lidarr_fake.albums[album_id]["monitored"])
        self.now += 8 * DAY
        self.step()
        got = self.store.get(want.id)
        self.assertEqual((got.state, got.attempts, got.next_try), (store.NOT_FOUND, 3, None))
        self.assertIn("three tries", got.detail)
        self.now += 30 * DAY
        self.step()
        self.assertEqual(self.state(want), store.NOT_FOUND, "no fourth try")

    def test_an_album_somebody_else_still_wants_stays_wanted(self):
        first, album_id = self.journey_to_searching()
        second = self.ask(person="mia")
        self.step(2)
        self.assertEqual(self.state(second), store.SEARCHING)
        self.now += 8 * DAY
        # the first runs out of time; the second was asked for later and has its own week
        self.store.update(second.id, next_try=self.now + 5 * DAY)
        self.step()
        self.assertEqual(self.state(first), store.NOT_FOUND)
        self.assertTrue(self.lidarr_fake.albums[album_id]["monitored"], "mia is still waiting for it")

    def test_a_refresh_that_undid_the_wanted_mark_is_put_back(self):
        want, album_id = self.journey_to_searching()
        self.lidarr_fake.albums[album_id]["monitored"] = False
        self.step()
        self.assertTrue(self.lidarr_fake.albums[album_id]["monitored"])


class WhenTheSwapGoesWrong(World):
    def test_a_better_copy_that_is_not_where_lidarr_says_is_a_failure_with_a_sentence_and_the_quick_copy_stays(self):
        want, album_id = self.journey_to_searching()
        self.lidarr_fake.import_album(album_id, POOL + "/Gojira/Magma (2016)")  # Lidarr says it is filed; the file is not there
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.FAILED)
        self.assertIn("Could not put the better copy in place", got.detail)
        self.assertTrue((self.music / self.quick_rel).exists())

    def test_until_the_music_server_has_noticed_the_file_the_request_keeps_trying_and_asks_for_a_scan(self):
        want, album_id = self.journey_to_searching()
        self.arrive(album_id)
        scans = self.nd_fake.scans
        self.nd_fake.scan = lambda: setattr(self.nd_fake, "scans", self.nd_fake.scans + 1)  # a scan that finds nothing yet
        self.step()
        got = self.store.get(want.id)
        self.assertEqual(got.state, store.DELIVERING)
        self.assertGreater(self.nd_fake.scans, scans)
        self.assertEqual(self.store.upgrades_after(0), [])
        asked = self.nd_fake.scans
        self.step()
        self.assertEqual(self.nd_fake.scans, asked, "not asking again every few seconds")
        self.now += 31
        self.step()
        self.assertGreater(self.nd_fake.scans, asked)

    def test_two_people_with_the_same_song_both_get_it_and_the_map_has_one_entry(self):
        sam, album_id = self.journey_to_searching()
        mia = self.ask(person="mia")
        self.step(2)
        self.arrive(album_id)
        self.step(3)
        self.assertEqual(self.state(sam), store.READY)
        self.assertEqual(self.state(mia), store.READY, self.store.get(mia.id).detail)
        self.assertEqual(len(self.store.upgrades_after(0)), 1)
        self.assertEqual(self.store.get(sam.id).new_song_id, self.store.get(mia.id).new_song_id)

    def test_a_crash_in_the_middle_changes_nothing_a_new_engine_carries_on(self):
        want = self.ask()
        self.step()
        self.engine = self.make_engine()  # a restart: nothing is kept in memory
        album_id = self.learn_album()
        self.step()
        self.assertEqual(self.state(want), store.SEARCHING)
        self.engine = self.make_engine()
        self.arrive(album_id)
        self.step(2)
        self.assertEqual(self.state(want), store.READY)

    def test_one_request_that_breaks_does_not_stop_the_others(self):
        self.store.add_want(person="mia", song_id="boom", artist="X", album="Y", title="Z", year=None, track=None, duration=None,
                            quick_path="X/Y/Z.opus")
        real = self.nd.file_of

        def file_of(song_id):
            if song_id == "boom":
                raise RuntimeError("something unexpected")
            return real(song_id)

        self.nd.file_of = file_of
        want, album_id = self.journey_to_searching()
        self.arrive(album_id)
        self.step(2)
        self.assertEqual(self.state(want), store.READY)


if __name__ == "__main__":
    unittest.main()
