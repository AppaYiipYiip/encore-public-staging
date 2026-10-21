"""One library per person (docs/26, 27): a song somebody asks for is saved in THEIR library folder and nowhere else.
Same fakes as the pipeline tests: no network, no real music server."""
import tempfile
import unittest
from pathlib import Path

from encore_fetch.jobs import JobManager, Request
from encore_fetch.library import PersonLayout

from test_pipeline import (GOOD, AUTH, FakeDownloader, FakeNavidrome,
                           FakeSearcher, InlineExecutor)

REQ = Request(artist="Opeth", title="Windowpane", album="Damnation", track=5, duration_s=467)


class PersonLayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.music = Path(self._tmp.name) / "music"
        self.work = Path(self._tmp.name) / "work"
        self.music.mkdir()
        self.now = 1_000_000.0

    def manager(self, layout: PersonLayout | None, *, nd=None) -> JobManager:
        self.downloader = FakeDownloader()
        self.nd = nd or FakeNavidrome()
        return JobManager(
            music_dir=self.music, work_dir=self.work, resolver=FakeSearcher([GOOD]), downloader=self.downloader,
            navidrome=self.nd, executor=InlineExecutor(), indexer=InlineExecutor(), cover=lambda url: None,
            tagger=lambda p, t, c: True, clock=lambda: self.now, sleep=lambda s: None, min_free_gb=0, people=layout)

    # ------------------------------------------------------------ the layout itself
    def test_a_person_with_a_library_folder_has_a_root(self) -> None:
        (self.music / "marwa").mkdir()
        layout = PersonLayout(self.music)
        self.assertEqual(layout.root_for("marwa"), self.music / "marwa")

    def test_a_person_without_a_folder_has_no_root(self) -> None:
        self.assertIsNone(PersonLayout(self.music).root_for("ben"))

    def test_a_mapped_person_uses_the_mapped_folder(self) -> None:
        (self.music / "owner-added").mkdir()
        layout = PersonLayout(self.music, folders={"owner": "owner-added"})
        self.assertEqual(layout.root_for("owner"), self.music / "owner-added")

    def test_nothing_that_climbs_out_or_is_shared_or_hidden_is_a_root(self) -> None:
        (self.music / "_shared").mkdir()
        (self.music / ".hidden").mkdir()
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        layout = PersonLayout(self.music, folders={"evil": "../elsewhere", "sneaky": "a/b", "shared": "_shared", "dot": ".hidden"})
        for who in ("evil", "sneaky", "shared", "dot", "..", ".", "", "a/b", "_shared", "../elsewhere"):
            self.assertIsNone(layout.root_for(who), who)

    def test_a_folder_that_is_a_link_out_of_the_library_is_refused(self) -> None:
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        link = self.music / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available here")
        self.assertIsNone(PersonLayout(self.music).root_for("linked"))

    # ------------------------------------------------------------ the pipeline
    def test_the_song_lands_in_the_requesters_own_library(self) -> None:
        (self.music / "marwa").mkdir()
        job = self.manager(PersonLayout(self.music)).submit(AUTH, REQ)
        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(job.path, "Opeth/Damnation/05 - Windowpane.opus", "relative to the person's library, as Navidrome reports it")
        self.assertTrue((self.music / "marwa" / job.path).is_file())
        self.assertFalse((self.music / "Opeth").exists(), "nothing is written at the root of everybody's music")

    def test_somebody_else_asking_for_the_same_song_gets_their_own_copy(self) -> None:
        for name in ("marwa", "ben"):
            (self.music / name).mkdir()
        m = self.manager(PersonLayout(self.music))
        m.submit(AUTH, REQ)
        from encore_fetch.navidrome import Auth
        m2 = self.manager(PersonLayout(self.music))
        job = m2.submit(Auth("ben", "b" * 32, "salt5678"), REQ)
        self.assertEqual(job.state, "ready", job.view())
        self.assertTrue((self.music / "ben" / "Opeth" / "Damnation" / "05 - Windowpane.opus").is_file())
        self.assertTrue((self.music / "marwa" / "Opeth" / "Damnation" / "05 - Windowpane.opus").is_file())

    def test_a_person_with_no_library_is_told_before_anything_is_downloaded(self) -> None:
        job = self.manager(PersonLayout(self.music)).submit(AUTH, REQ)
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.error, "no_library")
        self.assertIn("library", job.view()["message"], "the person is told in plain words what is missing")
        self.assertEqual(self.downloader.calls, [], "no download for somebody who has nowhere to put it")
        self.assertEqual(list(self.music.iterdir()), [])

    def test_a_song_the_person_can_already_play_needs_no_library_of_their_own(self) -> None:
        m = self.manager(PersonLayout(self.music), nd=FakeNavidrome(present={("opeth", "windowpane"): "42"}))
        job = m.submit(AUTH, REQ)
        self.assertEqual(job.state, "ready", job.view())
        self.assertEqual(job.song_id, "42")

    def test_without_a_layout_the_old_flat_behaviour_is_unchanged(self) -> None:
        job = self.manager(None).submit(AUTH, REQ)
        self.assertEqual(job.state, "ready", job.view())
        self.assertTrue((self.music / "Opeth" / "Damnation" / "05 - Windowpane.opus").is_file())


class ConfigTest(unittest.TestCase):
    def test_the_layout_settings_are_read_and_malformed_pairs_are_skipped(self) -> None:
        import os
        from unittest import mock

        from encore_fetch.config import Config

        env = {"PEOPLE": "1", "PERSON_FOLDERS": "owner=owner-added, sara = sara2 ,bad,=x,a="}
        with mock.patch.dict(os.environ, env, clear=False):
            config = Config.from_env()
        self.assertTrue(config.people)
        self.assertEqual(config.person_folders, {"owner": "owner-added", "sara": "sara2"})

    def test_off_by_default(self) -> None:
        import os
        from unittest import mock

        from encore_fetch.config import Config

        with mock.patch.dict(os.environ, {}, clear=True):
            config = Config.from_env()
        self.assertFalse(config.people)
        self.assertEqual(config.person_folders, {})


if __name__ == "__main__":
    unittest.main()
