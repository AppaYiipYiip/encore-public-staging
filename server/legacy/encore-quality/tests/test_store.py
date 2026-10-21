"""What the service remembers."""
import tempfile
import unittest
from pathlib import Path

from encore_quality import store
from encore_quality.store import Store


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def ask(s, person="sam", song="s1", title="Silvera", **extra):
    return s.add_want(person=person, song_id=song, artist="Gojira", album="Magma", title=title, year=2016, track=3, duration=229.0,
                      quick_path="Gojira/Magma/03 - Silvera.opus", **extra)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.s = Store(":memory:", self.clock)
        self.addCleanup(self.s.close)

    def test_a_request_starts_in_the_queue_with_a_sentence(self):
        want, created = ask(self.s)
        self.assertTrue(created)
        self.assertEqual((want.state, want.person, want.title), (store.QUEUED, "sam", "Silvera"))
        self.assertTrue(want.detail)

    def test_asking_twice_for_the_same_song_gives_the_first_request_back(self):
        first, _ = ask(self.s)
        again, created = ask(self.s)
        self.assertFalse(created)
        self.assertEqual(again.id, first.id)

    def test_two_people_asking_for_the_same_song_each_have_their_own_request(self):
        a, _ = ask(self.s, person="sam")
        b, created = ask(self.s, person="mia", song="s1")
        self.assertTrue(created)
        self.assertNotEqual(a.id, b.id)

    def test_after_a_request_is_finished_the_song_can_be_asked_for_again(self):
        first, _ = ask(self.s)
        self.s.update(first.id, state=store.NOT_FOUND)
        again, created = ask(self.s)
        self.assertTrue(created or again.id != first.id)
        self.s.update(again.id, state=store.CANCELLED)
        third, created = ask(self.s)
        self.assertTrue(created)

    def test_a_person_sees_only_their_own_requests_newest_first(self):
        ask(self.s, person="sam", song="a")
        ask(self.s, person="mia", song="b")
        ask(self.s, person="sam", song="c")
        self.assertEqual([w.song_id for w in self.s.of_person("sam")], ["c", "a"])
        self.assertEqual([w.song_id for w in self.s.of_person("mia")], ["b"])

    def test_an_update_changes_only_what_is_named_and_stamps_the_time(self):
        want, _ = ask(self.s)
        self.clock.now += 60
        changed = self.s.update(want.id, state=store.SEARCHING, detail="Looking.")
        self.assertEqual((changed.state, changed.detail, changed.title), (store.SEARCHING, "Looking.", "Silvera"))
        self.assertEqual(changed.updated, self.clock.now)
        self.assertEqual(changed.created, 1_000_000.0)

    def test_an_update_cannot_name_a_column_that_does_not_exist(self):
        want, _ = ask(self.s)
        with self.assertRaises(ValueError):
            self.s.update(want.id, nonsense=1)

    def test_what_is_in_somebodys_hands_is_found_by_state(self):
        a, _ = ask(self.s, song="a")
        b, _ = ask(self.s, song="b")
        self.s.update(b.id, state=store.SEARCHING)
        self.assertEqual([w.id for w in self.s.in_state(store.QUEUED)], [a.id])
        self.assertEqual({w.id for w in self.s.in_state(*store.ACTIVE)}, {a.id, b.id})
        self.assertEqual(self.s.counts(), {store.QUEUED: 1, store.SEARCHING: 1})

    def test_the_upgrade_map_is_read_in_order_after_the_last_number_a_phone_saw(self):
        one = self.s.add_upgrade("sam", "old1", "new1", "FLAC")
        two = self.s.add_upgrade("mia", "old2", "new2", "FLAC")
        self.assertEqual([u["old"] for u in self.s.upgrades_after(0)], ["old1", "old2"])
        self.assertEqual([u["old"] for u in self.s.upgrades_after(one)], ["old2"])
        self.assertEqual(self.s.upgrades_after(two), [])

    def test_a_swap_that_is_already_in_the_map_is_not_added_twice(self):
        # two people can hold the same song: the second swap of it is the first one
        first = self.s.add_upgrade("sam", "old", "new", "FLAC")
        again = self.s.add_upgrade("mia", "old", "new", "FLAC")
        self.assertEqual(first, again)
        self.assertEqual(len(self.s.upgrades_after(0)), 1)

    def test_a_removed_person_leaves_no_request_behind_but_the_map_stays_true(self):
        ask(self.s, person="sam")
        self.s.add_upgrade("sam", "a", "b", "FLAC")
        ask(self.s, person="mia", song="z")
        self.s.forget_person("sam")
        self.assertEqual(self.s.of_person("sam"), [])
        self.assertEqual(len(self.s.upgrades_after(0)), 1, "the files were swapped; the map says so for everybody")
        self.assertEqual(len(self.s.of_person("mia")), 1)

    def test_settings_are_kept_and_replaced(self):
        self.assertEqual(self.s.setting("soulseek", "off"), "off")
        self.s.set_setting("soulseek", "on")
        self.s.set_setting("soulseek", "on")
        self.assertEqual(self.s.setting("soulseek", "off"), "on")

    def test_it_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "quality.db"
            first = Store(path)
            ask(first)
            first.set_setting("k", "v")
            first.close()
            second = Store(path)
            self.assertEqual(len(second.of_person("sam")), 1)
            self.assertEqual(second.setting("k"), "v")
            second.close()


if __name__ == "__main__":
    unittest.main()
