"""The service puts itself together from its settings."""
import tempfile
import unittest
from pathlib import Path

from encore_quality.__main__ import build
from encore_quality.config import Config


class BuildTest(unittest.TestCase):
    def test_it_builds_from_settings_and_the_engine_reads_the_owners_limits_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = Config(music_dir=root / "music", data_dir=root / "data", lidarr_api_key="a", slskd_api_key="b",
                            soularr_config=root / "soularr" / "config.ini")
            api, engine, maintenance = build(config)
            self.assertTrue((root / "data" / "quality.db").exists())
            self.assertEqual(engine._limits.daily_cap, 40)
            api._store.set_setting("daily_cap", "7")
            self.assertEqual(engine._limits.daily_cap, 7)
            self.assertFalse(maintenance.soulseek_on())
            api._store.close()


class ConfigTest(unittest.TestCase):
    def test_settings_come_from_the_environment_with_sane_fallbacks(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"PORT": "9000", "DAILY_CAP": "nonsense", "MIN_FREE_GB": "-4", "MUSIC_DIR": "/srv/music",
                                          "LIDARR_URL": "http://lidarr:8686/"}, clear=True):
            c = Config.from_env()
        self.assertEqual((c.port, c.daily_cap, c.min_free_gb), (9000, 40, 0.0))
        self.assertEqual((str(c.music_dir).replace("\\", "/"), c.lidarr_url), ("/srv/music", "http://lidarr:8686"))


if __name__ == "__main__":
    unittest.main()
