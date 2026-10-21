"""Putting Lidarr and Soularr in the right state, and keeping them there (docs/46, results S3)."""
import tempfile
import unittest
from pathlib import Path

from encore_quality.lidarr import Lidarr
from encore_quality.wiring import ACCEPTED, CUTOFF, NAME, ensure_lidarr, render_soularr, write_if_changed

from tests.fakes import FakeLidarr

POOL = "/music/.encore/pool"


def accepted_of(profile):
    return {leaf["quality"]["id"] for item in profile["items"] for leaf in (item["items"] or [item]) if leaf["allowed"]}


class LidarrWiringTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeLidarr()
        self.lidarr = Lidarr(self.fake)

    def test_a_fresh_lidarr_is_given_its_folder_its_profiles_and_renaming(self):
        wiring = ensure_lidarr(self.lidarr, POOL)
        self.assertEqual([f["path"] for f in self.fake.root_folders], [POOL])
        quality = self.fake.quality_profiles[0]
        self.assertEqual((quality["name"], quality["id"]), (NAME, wiring.quality_id))
        self.assertEqual(accepted_of(quality), set(ACCEPTED), "FLAC and 320 / V0 MP3 only: below that is what the quick copy already is")
        self.assertEqual(quality["cutoff"], CUTOFF)
        self.assertTrue(quality["upgradeAllowed"])
        self.assertTrue(self.fake.naming["renameTracks"], "else the album folder is dropped and two '01 - Intro' collide")
        self.assertEqual(self.fake.metadata_profiles[0]["id"], wiring.metadata_id)

    def test_singles_eps_and_live_albums_are_all_allowed_because_the_song_may_be_on_any_of_them(self):
        ensure_lidarr(self.lidarr, POOL)
        profile = self.fake.metadata_profiles[0]
        for kind in profile["primaryAlbumTypes"] + profile["secondaryAlbumTypes"]:
            self.assertTrue(kind["allowed"], kind["albumType"]["name"])
        allowed_status = {s["releaseStatus"]["name"] for s in profile["releaseStatuses"] if s["allowed"]}
        self.assertEqual(allowed_status, {"Official", "Promotion"}, "no bootlegs")

    def test_running_it_again_creates_nothing_twice(self):
        first = ensure_lidarr(self.lidarr, POOL)
        before = [c for c in self.fake.calls if c[0] in ("POST", "PUT")]
        second = ensure_lidarr(self.lidarr, POOL)
        after = [c for c in self.fake.calls if c[0] in ("POST", "PUT")]
        self.assertEqual(first, second)
        self.assertEqual(before, after, "only looks")
        self.assertEqual((len(self.fake.root_folders), len(self.fake.quality_profiles), len(self.fake.metadata_profiles)), (1, 1, 1))

    def test_a_profile_somebody_loosened_is_put_back(self):
        ensure_lidarr(self.lidarr, POOL)
        for leaf in self.fake.quality_profiles[0]["items"]:
            if leaf["quality"]["id"] == 1:
                leaf["allowed"] = True  # MP3-192: somebody let a poor copy in
        ensure_lidarr(self.lidarr, POOL)
        self.assertEqual(accepted_of(self.fake.quality_profiles[0]), set(ACCEPTED))

    def test_a_metadata_profile_that_hides_singles_is_put_back(self):
        ensure_lidarr(self.lidarr, POOL)
        self.fake.metadata_profiles[0]["primaryAlbumTypes"][2]["allowed"] = False
        ensure_lidarr(self.lidarr, POOL)
        self.assertTrue(all(k["allowed"] for k in self.fake.metadata_profiles[0]["primaryAlbumTypes"]))

    def test_a_folder_already_configured_is_not_added_again_even_with_a_trailing_slash(self):
        self.fake.root_folders.append({"id": 99, "path": POOL + "/"})
        ensure_lidarr(self.lidarr, POOL)
        self.assertEqual(len(self.fake.root_folders), 1)

    def test_an_existing_profile_of_another_name_is_left_alone(self):
        self.fake.quality_profiles.append({**{"name": "Any", "id": 1, "cutoff": 2, "upgradeAllowed": False}, "items": []})
        ensure_lidarr(self.lidarr, POOL)
        self.assertEqual([p["name"] for p in self.fake.quality_profiles], ["Any", NAME])


class SoularrConfigTest(unittest.TestCase):
    def render(self):
        return render_soularr(lidarr_key="LKEY", lidarr_url="http://lidarr:8686", slskd_key="SKEY", slskd_url="http://slskd:5030",
                              downloads="/music/.encore/downloads")

    def test_both_programs_are_pointed_at_each_other_and_at_the_same_downloads_folder(self):
        text = self.render()
        self.assertIn("api_key = LKEY", text)
        self.assertIn("api_key = SKEY", text)
        self.assertIn("host_url = http://lidarr:8686", text)
        self.assertIn("host_url = http://slskd:5030", text)
        self.assertEqual(text.count("download_dir = /music/.encore/downloads"), 2)

    def test_only_flac_and_320_mp3_are_asked_for_never_128(self):
        line = next(l for l in self.render().splitlines() if l.startswith("allowed_filetypes"))
        self.assertTrue(line.endswith("mp3 320"))
        self.assertNotIn(",mp3,", line + ",")
        self.assertIn("flac", line)

    def test_it_is_written_only_when_it_changed_and_only_the_service_can_read_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "soularr" / "config.ini"
            self.assertTrue(write_if_changed(path, self.render()))
            stamp = path.stat().st_mtime_ns
            self.assertFalse(write_if_changed(path, self.render()), "unchanged: untouched")
            self.assertEqual(path.stat().st_mtime_ns, stamp)
            self.assertTrue(write_if_changed(path, self.render().replace("LKEY", "NEW")))
            self.assertIn("api_key = NEW", path.read_text())
            self.assertEqual([p.name for p in path.parent.iterdir()], ["config.ini"], "no temporary file left behind")
            if hasattr(path.stat(), "st_mode") and path.parent.drive == "":
                self.assertEqual(path.stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
