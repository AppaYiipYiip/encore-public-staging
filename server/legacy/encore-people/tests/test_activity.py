"""Friend activity (docs/35 section 4): opt-in, last song only, expiry, nothing about what was played on disk."""
import json
import tempfile
import unittest
from pathlib import Path

from encore_people.activity import Activity, EXPIRY_PLAYING_S, EXPIRY_PAUSED_S

NOW = 1_760_000_000.0
SONG = {"title": "Dogs", "artist": "Pink Floyd", "album": "Animals", "coverUrl": "https://cdn.example/cover.jpg",
        "state": "playing"}


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> float:
        return self.now


class ActivityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.file = Path(self._tmp.name) / "sharing.json"
        self.clock = Clock()
        self.a = Activity(self.file, clock=self.clock)

    # ------------------------------------------------------------ opt-in
    def test_nobody_shares_until_they_say_so(self) -> None:
        self.assertFalse(self.a.is_sharing("sara"))
        self.assertFalse(self.a.report("sara", SONG), "a report from someone who has not opted in is ignored")
        self.assertEqual(self.a.others("ben"), [])

    def test_a_person_who_shares_is_seen_by_others_but_not_by_themselves(self) -> None:
        self.a.set_sharing("sara", True)
        self.assertTrue(self.a.report("sara", SONG))
        seen = self.a.others("ben")
        self.assertEqual(len(seen), 1)
        self.assertEqual((seen[0].username, seen[0].title, seen[0].artist, seen[0].album), ("sara", "Dogs", "Pink Floyd", "Animals"))
        self.assertEqual(seen[0].state, "playing")
        self.assertEqual(seen[0].since, NOW)
        self.assertEqual(self.a.others("sara"), [], "you never see your own entry")

    def test_switching_sharing_off_removes_the_entry_at_once(self) -> None:
        self.a.set_sharing("sara", True)
        self.a.report("sara", SONG)
        self.a.set_sharing("sara", False)
        self.assertEqual(self.a.others("ben"), [])
        self.assertFalse(self.a.report("sara", SONG))

    def test_the_choice_survives_a_restart_but_the_song_does_not(self) -> None:
        self.a.set_sharing("sara", True)
        self.a.report("sara", SONG)
        again = Activity(self.file, clock=self.clock)
        self.assertTrue(again.is_sharing("sara"), "the opt-in is the person's choice and is kept")
        self.assertEqual(again.others("ben"), [], "what was playing is memory only")

    def test_nothing_about_what_was_played_is_written_to_disk(self) -> None:
        self.a.set_sharing("sara", True)
        self.a.report("sara", {**SONG, "title": "A Very Secret Title 12345"})
        on_disk = self.file.read_text(encoding="utf-8")
        self.assertNotIn("Secret", on_disk)
        self.assertEqual(json.loads(on_disk), {"sharing": ["sara"]})

    # ------------------------------------------------------------ what is kept
    def test_only_the_last_song_is_kept(self) -> None:
        self.a.set_sharing("sara", True)
        self.a.report("sara", SONG)
        self.clock.now += 60
        self.a.report("sara", {**SONG, "title": "Sheep"})
        seen = self.a.others("ben")
        self.assertEqual([e.title for e in seen], ["Sheep"])
        self.assertEqual(seen[0].since, NOW + 60)

    def test_newest_first_across_people(self) -> None:
        for name in ("sara", "tom"):
            self.a.set_sharing(name, True)
        self.a.report("sara", SONG)
        self.clock.now += 30
        self.a.report("tom", {**SONG, "title": "Sheep"})
        self.assertEqual([e.username for e in self.a.others("ben")], ["tom", "sara"])

    def test_clearing_removes_the_entry(self) -> None:
        self.a.set_sharing("sara", True)
        self.a.report("sara", SONG)
        self.a.clear("sara")  # for example, private listening was switched on
        self.assertEqual(self.a.others("ben"), [])

    # ------------------------------------------------------------ expiry
    def test_a_song_that_started_long_ago_disappears(self) -> None:
        self.a.set_sharing("sara", True)
        self.a.report("sara", SONG)
        self.clock.now += EXPIRY_PLAYING_S - 1
        self.assertEqual(len(self.a.others("ben")), 1)
        self.clock.now += 2
        self.assertEqual(self.a.others("ben"), [])

    def test_a_paused_song_disappears_sooner(self) -> None:
        self.a.set_sharing("sara", True)
        self.a.report("sara", {**SONG, "state": "paused"})
        self.clock.now += EXPIRY_PAUSED_S + 1
        self.assertEqual(self.a.others("ben"), [])

    def test_an_update_keeps_a_long_song_alive(self) -> None:
        self.a.set_sharing("sara", True)
        self.a.report("sara", SONG)
        self.clock.now += EXPIRY_PLAYING_S - 60
        self.a.report("sara", SONG)  # the app reports again (same song): still playing
        self.clock.now += 120
        self.assertEqual(len(self.a.others("ben")), 1)

    # ------------------------------------------------------------ what is accepted
    def test_fields_are_cleaned_and_bounded(self) -> None:
        self.a.set_sharing("sara", True)
        self.assertTrue(self.a.report("sara", {"title": "  Hello\x00\x07 World  " + "x" * 500, "artist": "A\nB", "album": None,
                                              "coverUrl": "javascript:alert(1)", "state": "playing"}))
        e = self.a.others("ben")[0]
        self.assertLessEqual(len(e.title), 200)
        self.assertNotIn("\x00", e.title + e.artist)
        self.assertNotIn("\n", e.artist)
        self.assertIsNone(e.cover_url, "a cover address that is not http(s) is dropped, not trusted")
        self.assertEqual(e.album, "")

    def test_a_report_without_a_title_is_ignored(self) -> None:
        self.a.set_sharing("sara", True)
        self.assertFalse(self.a.report("sara", {"title": "   ", "artist": "x", "state": "playing"}))
        self.assertFalse(self.a.report("sara", "not a dict"))  # type: ignore[arg-type]
        self.assertEqual(self.a.others("ben"), [])

    def test_an_unknown_state_is_treated_as_paused(self) -> None:
        self.a.set_sharing("sara", True)
        self.a.report("sara", {**SONG, "state": "exploding"})
        self.assertEqual(self.a.others("ben")[0].state, "paused")

    def test_an_entry_carries_no_song_id_and_no_path(self) -> None:
        self.a.set_sharing("sara", True)
        self.a.report("sara", {**SONG, "id": "abc123", "path": "/music/sara/private/Dogs.opus"})
        e = self.a.others("ben")[0]
        self.assertFalse(hasattr(e, "id") or hasattr(e, "path"))

    def test_the_store_is_bounded(self) -> None:
        for i in range(500):
            name = f"user{i:03d}"
            self.a.set_sharing(name, True)
            self.a.report(name, SONG)
            self.clock.now += 1
        self.assertLessEqual(len(self.a.others("nobody")), 200)

    def test_a_damaged_sharing_file_means_nobody_shares(self) -> None:
        self.file.write_text("{ not json", encoding="utf-8")
        again = Activity(self.file, clock=self.clock)
        self.assertFalse(again.is_sharing("sara"))


if __name__ == "__main__":
    unittest.main()
