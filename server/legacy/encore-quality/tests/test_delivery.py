"""Putting the better copy in place and keeping a way back, on a real folder (docs/46 section 4)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from encore_quality import delivery
from encore_quality.delivery import DeliveryError, place, purge_replaced, undo


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.music = Path(self._tmp.name) / "music"
        self.quick_rel = "Gojira/Magma/03 - Silvera.opus"
        self.quick = self.music / self.quick_rel
        self.quick.parent.mkdir(parents=True)
        self.quick.write_bytes(b"quick-copy-bytes")
        self.pool = self.music / ".encore/pool/Gojira/Magma (2016)/03 - Silvera.flac"
        self.pool.parent.mkdir(parents=True)
        self.pool.write_bytes(b"F" * 5000)

    def test_the_better_copy_is_a_second_name_for_the_pool_file_next_to_where_the_quick_copy_was(self):
        placed = place(self.music, self.quick_rel, self.pool)
        target = self.music / "Gojira/Magma/03 - Silvera.flac"
        self.assertEqual(placed.quality_rel, "Gojira/Magma/03 - Silvera.flac")
        self.assertTrue(placed.linked)
        self.assertTrue(os.path.samefile(target, self.pool), "the same bytes: the disk is used once")
        self.assertEqual(os.stat(target).st_nlink, 2)

    def test_the_quick_copy_is_moved_aside_not_deleted_and_the_music_server_will_not_see_it(self):
        placed = place(self.music, self.quick_rel, self.pool)
        self.assertFalse(self.quick.exists())
        kept = self.music / placed.replaced_rel
        self.assertEqual(kept.read_bytes(), b"quick-copy-bytes")
        self.assertTrue(any(part.startswith(".") for part in Path(placed.replaced_rel).parts[:1]), "inside a dot-folder")

    def test_nothing_is_changed_when_the_better_copy_is_not_there(self):
        self.pool.unlink()
        with self.assertRaises(DeliveryError):
            place(self.music, self.quick_rel, self.pool)
        self.assertTrue(self.quick.exists())

    def test_a_different_file_already_at_the_new_name_is_never_overwritten(self):
        other = self.music / "Gojira/Magma/03 - Silvera.flac"
        other.write_bytes(b"somebody else's file")
        with self.assertRaises(DeliveryError) as caught:
            place(self.music, self.quick_rel, self.pool)
        self.assertIn("Another file", str(caught.exception))
        self.assertEqual(other.read_bytes(), b"somebody else's file")
        self.assertTrue(self.quick.exists())

    def test_doing_it_twice_changes_nothing_the_second_time(self):
        first = place(self.music, self.quick_rel, self.pool)
        second = place(self.music, self.quick_rel, self.pool)
        self.assertEqual(first.quality_rel, second.quality_rel)
        self.assertEqual((self.music / first.replaced_rel).read_bytes(), b"quick-copy-bytes")

    def test_a_missing_original_that_was_never_swapped_is_said(self):
        self.quick.unlink()
        with self.assertRaises(DeliveryError) as caught:
            place(self.music, self.quick_rel, self.pool)
        self.assertIn("not there any more", str(caught.exception))

    def test_a_path_that_climbs_out_of_the_music_folder_is_refused(self):
        outside = Path(self._tmp.name) / "secret.flac"
        outside.write_bytes(b"x")
        for bad in ("../secret.opus", "Gojira/../../secret.opus", "/etc/passwd"):
            with self.assertRaises(DeliveryError, msg=bad):
                place(self.music, bad, self.pool)
        with self.assertRaises(DeliveryError):
            place(self.music, self.quick_rel, outside)
        self.assertTrue(self.quick.exists())

    def test_when_the_two_folders_are_on_different_drives_the_file_is_copied_not_lost(self):
        with mock.patch("os.link", side_effect=OSError(18, "Invalid cross-device link")):
            placed = place(self.music, self.quick_rel, self.pool)
        self.assertFalse(placed.linked)
        self.assertEqual((self.music / placed.quality_rel).read_bytes(), b"F" * 5000)
        self.assertFalse(self.quick.exists())

    def test_when_the_quick_copy_cannot_be_moved_the_library_is_not_left_with_two_copies(self):
        with mock.patch("os.replace", side_effect=OSError(13, "Permission denied")):
            with self.assertRaises(DeliveryError):
                place(self.music, self.quick_rel, self.pool)
        self.assertFalse((self.music / "Gojira/Magma/03 - Silvera.flac").exists())
        self.assertTrue(self.quick.exists())

    def test_the_way_back_puts_the_quick_copy_back_and_takes_the_better_one_out_of_the_library(self):
        placed = place(self.music, self.quick_rel, self.pool)
        undo(self.music, placed)
        self.assertEqual(self.quick.read_bytes(), b"quick-copy-bytes")
        self.assertFalse((self.music / placed.quality_rel).exists())
        self.assertTrue(self.pool.exists(), "the pool keeps its copy")

    def test_the_way_back_says_so_when_the_quick_copy_was_already_removed(self):
        placed = place(self.music, self.quick_rel, self.pool)
        (self.music / placed.replaced_rel).unlink()
        with self.assertRaises(DeliveryError):
            undo(self.music, placed)

    def test_quick_copies_are_kept_fourteen_days_counting_from_the_swap(self):
        old = os.stat(self.quick).st_mtime - 100 * 86400
        os.utime(self.quick, (old, old))  # a quick copy made long ago
        placed = place(self.music, self.quick_rel, self.pool)
        kept = self.music / placed.replaced_rel
        self.assertGreater(kept.stat().st_mtime, old + 99 * 86400, "the clock started at the swap")
        now = kept.stat().st_mtime
        self.assertEqual(purge_replaced(self.music, now + 13 * 86400), 0)
        self.assertTrue(kept.exists())
        self.assertEqual(purge_replaced(self.music, now + 15 * 86400), 1)
        self.assertFalse(kept.exists())
        self.assertFalse((self.music / delivery.REPLACED_DIR / "Gojira").exists(), "the empty folders go too")

    def test_purging_with_nothing_kept_is_fine(self):
        self.assertEqual(purge_replaced(self.music, 1e12), 0)


if __name__ == "__main__":
    unittest.main()
