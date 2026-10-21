"""Keeping the quality tier in shape, and saying so in plain words (docs/46, docs/49 P4)."""
import os
import tempfile
import unittest
from pathlib import Path

from encore_quality import delivery
from encore_quality.config import Config
from encore_quality.lidarr import Lidarr
from encore_quality.maintenance import Maintenance
from encore_quality.navidrome import Navidrome
from encore_quality.slskd import Slskd
from encore_quality.store import Store

from tests.fakes import FakeLidarr, FakeNavidrome, FakeSlskdFull


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.music = root / "music"
        self.music.mkdir()
        self.config = Config(music_dir=self.music, soularr_config=root / "soularr" / "config.ini", lidarr_api_key="LKEY-secret",
                             slskd_api_key="SKEY-secret", min_free_gb=0.0)
        self.now = 1_760_000_000.0
        self.lidarr_fake = FakeLidarr()
        self.slskd_fake = FakeSlskdFull()
        self.nd_fake = FakeNavidrome(self.music)
        self.store = Store(":memory:", lambda: self.now)
        self.addCleanup(self.store.close)
        self.m = self.make()

    def make(self) -> Maintenance:
        nd = Navidrome("http://nd", admin_user="owner", admin_password="owner-pw", transport=self.nd_fake)
        return Maintenance(config=self.config, lidarr=Lidarr(self.lidarr_fake), slskd=Slskd(self.slskd_fake), navidrome=nd, store=self.store,
                           clock=lambda: self.now)


class MaintenanceTest(Base):
    def test_a_fresh_install_gets_its_folders_its_lidarr_settings_and_soularrs_settings(self):
        self.m.run()
        for folder in (delivery.POOL_DIR, delivery.DOWNLOADS_DIR, delivery.INCOMPLETE_DIR, delivery.REPLACED_DIR):
            self.assertTrue((self.music / folder).is_dir(), folder)
        self.assertIsNotNone(self.m.wiring)
        self.assertEqual([f["path"] for f in self.lidarr_fake.root_folders], [self.m.pool_in_lidarr])
        self.assertTrue(self.m.pool_in_lidarr.endswith("/.encore/pool"))
        text = self.config.soularr_config.read_text()
        self.assertIn("api_key = LKEY-secret", text)
        self.assertIn(".encore/downloads", text)

    def test_running_it_again_changes_nothing(self):
        self.m.run()
        calls = len([c for c in self.lidarr_fake.calls if c[0] in ("POST", "PUT")])
        stamp = self.config.soularr_config.stat().st_mtime_ns
        self.m.run()
        self.assertEqual(len([c for c in self.lidarr_fake.calls if c[0] in ("POST", "PUT")]), calls)
        self.assertEqual(self.config.soularr_config.stat().st_mtime_ns, stamp)

    def test_when_lidarr_does_not_answer_it_says_so_and_recovers_by_itself(self):
        self.lidarr_fake.down = True
        self.m.run()
        self.assertIsNone(self.m.wiring)
        self.assertIn("Lidarr", self.m.last_error)
        self.assertFalse(self.m.health()["lidarr"]["up"])
        self.lidarr_fake.down = False
        self.m.run()
        self.assertIsNotNone(self.m.wiring)
        self.assertEqual(self.m.last_error, "")

    def test_soulseek_is_off_until_the_owner_switches_it_on_and_off_means_off(self):
        self.assertFalse(self.m.soulseek_on())
        self.m.run()
        self.assertFalse(self.slskd_fake.logged_in, "a client that came up connected is disconnected: nothing is shared or sent")
        self.m.set_soulseek(True)
        self.assertTrue(self.slskd_fake.logged_in)
        self.m.set_soulseek(False)
        self.assertFalse(self.slskd_fake.logged_in)

    def test_the_owners_choice_is_kept_across_a_restart_and_a_dropped_connection_is_restored(self):
        self.m.set_soulseek(True)
        self.slskd_fake.logged_in = False  # the network dropped it
        again = self.make()
        self.assertTrue(again.soulseek_on())
        again.run()
        self.assertTrue(self.slskd_fake.logged_in)

    def test_nothing_is_sent_to_slskd_when_it_is_off_and_already_disconnected(self):
        self.slskd_fake.logged_in = False
        self.m.run()
        self.assertEqual([c for c in self.slskd_fake.calls if c[0] in ("PUT", "DELETE")], [])

    def test_slskd_not_answering_is_not_a_crash(self):
        self.slskd_fake.down = True
        self.m.set_soulseek(True)
        self.m.run()
        self.assertFalse(self.m.health()["slskd"]["up"])

    def test_quick_copies_kept_longer_than_two_weeks_are_cleared(self):
        old = self.music / delivery.REPLACED_DIR / "A/B/c.opus"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"x")
        os.utime(old, (self.now - 20 * 86400, self.now - 20 * 86400))
        self.m.run()
        self.assertFalse(old.exists())

    def test_an_unwritable_music_folder_is_said_in_a_sentence(self):
        self.config = Config(music_dir=self.music / "no" / "such" / "place", soularr_config=self.config.soularr_config)
        m = self.make()
        original = Path.mkdir

        def refuse(self_, *a, **k):
            raise PermissionError(13, "Permission denied")

        Path.mkdir = refuse
        try:
            m.run()
        finally:
            Path.mkdir = original
        self.assertIn("not writable", m.last_error)


class TheSelfTest(Base):
    def by_key(self, checks):
        return {c["key"]: c for c in checks}

    def test_a_healthy_server_passes_every_question_in_plain_words(self):
        self.m.set_soulseek(True)
        self.m.run()
        (self.config.soularr_config.parent / "soularr.log").write_text("ran")
        checks = self.by_key(self.m.selftest())
        self.assertEqual({c["state"] for c in checks.values()}, {"ok"}, checks)
        self.assertIn("3 people answered", checks["network"]["note"])
        self.assertIn("without a second copy", checks["folders"]["note"])

    def test_soulseek_switched_off_is_reported_as_off_not_as_a_problem_and_no_search_is_made(self):
        self.m.run()
        checks = self.by_key(self.m.selftest())
        self.assertEqual(checks["soulseek"]["state"], "off")
        self.assertNotIn("network", checks)
        self.assertEqual([c for c in self.slskd_fake.calls if c[1] == "/searches"], [])

    def test_each_failure_says_which_part_and_what_is_wrong(self):
        self.m.set_soulseek(True)
        self.m.run()
        self.lidarr_fake.down = True
        self.slskd_fake.down = True
        self.nd_fake.admin_login = ("owner", "something else")
        checks = self.by_key(self.m.selftest())
        for key in ("lidarr", "slskd", "admin"):
            self.assertEqual(checks[key]["state"], "problem", key)
            self.assertTrue(checks[key]["note"], key)

    def test_the_test_never_shows_a_key_or_a_password(self):
        self.m.set_soulseek(True)
        self.m.run()
        text = str(self.m.selftest()) + str(self.m.health())
        for secret in ("LKEY-secret", "SKEY-secret", "owner-pw"):
            self.assertNotIn(secret, text)

    def test_a_search_nobody_answers_is_a_problem_with_a_hint(self):
        self.m.set_soulseek(True)
        self.m.run()
        self.slskd_fake.peers_answering = 0
        checks = self.by_key(self.m.selftest())
        self.assertEqual(checks["network"]["state"], "problem")
        self.assertIn("blocked", checks["network"]["note"])

    def test_the_link_probe_leaves_nothing_behind(self):
        self.m.run()
        self.m.selftest(search=False)
        self.assertEqual([p.name for p in (self.music / delivery.POOL_DIR).iterdir()], [])
        self.assertEqual([p.name for p in (self.music / delivery.DOWNLOADS_DIR).iterdir()], [".incomplete"], "only slskd's own folder")

    def test_when_the_disk_is_nearly_full_it_says_how_much_room_there_is(self):
        self.config = Config(music_dir=self.music, soularr_config=self.config.soularr_config, min_free_gb=10 ** 9)
        m = self.make()
        m.run()
        checks = self.by_key(m.selftest(search=False))
        self.assertEqual(checks["space"]["state"], "problem")
        self.assertIn("GB free", checks["space"]["note"])


if __name__ == "__main__":
    unittest.main()
