"""Songs fetched before the album lookup existed are one-song albums with no picture; the backfill gives them theirs,
changing nothing else."""
import unittest
from pathlib import Path

from encore_fetch.backfill import Found, needs_a_look, run
from encore_fetch.catalogue import Meta

HARVEST = Meta("Blackwater Park", "https://cdn-images.dzcdn.net/1.jpg", 3, 1, 2001)


def files(*names):
    return [Path(f"/music/nina/{n}.opus") for n in names]


class NeedsALookTest(unittest.TestCase):
    def test_a_single_the_fetcher_made_up_has_no_album_of_its_own_and_no_picture(self):
        self.assertTrue(needs_a_look(Found("Harvest", "Opeth", "Harvest", False, 361)))
        self.assertTrue(needs_a_look(Found("Harvest", "Opeth", None, False, 361)))
        self.assertTrue(needs_a_look(Found("Harvest", "Opeth", "  harvest ", False, 361)))

    def test_a_song_with_a_real_album_or_a_picture_is_left_alone(self):
        self.assertFalse(needs_a_look(Found("Harvest", "Opeth", "Blackwater Park", False, 361)))
        self.assertFalse(needs_a_look(Found("Harvest", "Opeth", "Harvest", True, 361)))

    def test_a_file_that_says_nothing_about_itself_is_left_alone(self):
        self.assertFalse(needs_a_look(Found("", "Opeth", None, False, 361)))
        self.assertFalse(needs_a_look(Found("Harvest", "", None, False, 361)))


class RunTest(unittest.TestCase):
    def setUp(self):
        self.written = []
        self.said = []
        self.catalogue = {("Opeth", "Harvest"): HARVEST}
        self.tags = {
            "Harvest": Found("Harvest", "Opeth", "Harvest", False, 361),
            "Windowpane": Found("Windowpane", "Opeth", "Damnation", True, 467),
            "Nobody": Found("Nobody", "Nobody Real", "Nobody", False, 100),
            "Broken": None,
        }

    def go(self, names, apply, **kw):
        return run(
            files(*names), read=lambda p: self.tags[p.stem],
            lookup=lambda a, t, d: self.catalogue.get((a, t)),
            cover=lambda url: b"JPEG" if url else None,
            write=lambda p, tags, pic: (self.written.append((p.stem, tags, pic)), kw.get("ok", True))[1],
            apply=apply, say=self.said.append, **{k: v for k, v in kw.items() if k != "ok"})

    def test_a_look_changes_nothing_and_says_what_would_change(self):
        report = self.go(["Harvest", "Windowpane", "Nobody", "Broken"], apply=False)

        self.assertEqual(self.written, [])
        self.assertEqual((report.seen, report.wanted, report.found, report.changed), (4, 2, 1, 1))
        self.assertEqual(self.said, ["~ Opeth - Harvest  ->  Blackwater Park (2001)"])
        self.assertIn("would change", report.line(False))

    def test_applying_writes_only_the_album_number_year_and_picture(self):
        report = self.go(["Harvest", "Windowpane", "Nobody"], apply=True)

        (stem, tags, picture), = self.written
        self.assertEqual(stem, "Harvest")
        self.assertEqual((tags.title, tags.artist, tags.album, tags.track, tags.disc, tags.year),
                         ("Harvest", "Opeth", "Blackwater Park", 3, 1, 2001))
        self.assertEqual(picture, b"JPEG")
        self.assertEqual((report.changed, report.failed), (1, 0))

    def test_a_file_that_cannot_be_written_is_counted_and_left_alone(self):
        report = self.go(["Harvest"], apply=True, ok=False)
        self.assertEqual((report.changed, report.failed), (0, 1))

    def test_it_can_stop_after_a_number_of_songs(self):
        self.tags = {f"S{i}": Found(f"S{i}", "Opeth", None, False, 100) for i in range(5)}
        self.catalogue = {("Opeth", f"S{i}"): HARVEST for i in range(5)}
        report = self.go([f"S{i}" for i in range(5)], apply=True, limit=2)
        self.assertEqual(report.changed, 2)

    def test_it_is_gentle_with_the_catalogue(self):
        pauses = []
        self.go(["Harvest", "Nobody"], apply=False, pause=0.3, sleep=pauses.append)
        self.assertEqual(pauses, [0.3, 0.3])


if __name__ == "__main__":
    unittest.main()
