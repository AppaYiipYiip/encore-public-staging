"""What the service asks of the music server: who is asking, which file a song is, a rescan."""
import hashlib
import unittest

from encore_quality.navidrome import Auth, Navidrome

from tests.fakes import FakeNavidrome


def token(user, password, salt="abc123"):
    return Auth(user, hashlib.md5((password + salt).encode()).hexdigest(), salt)


class NavidromeTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeNavidrome()
        self.now = [0.0]
        self.nd = Navidrome("http://nd", admin_user="owner", admin_password="owner-pw", transport=self.fake, clock=lambda: self.now[0])
        self.sam = token("sam", "sam-pw")
        self.song = self.fake.add_song("Gojira/Magma/03 - Silvera.opus", title="Silvera", artist="Gojira", album="Magma", track=3,
                                       release_group="rg-1")

    def test_a_persons_token_is_checked_by_the_music_server_and_remembered_briefly(self):
        self.assertTrue(self.nd.verify(self.sam))
        asked = len(self.fake.calls)
        self.assertTrue(self.nd.verify(self.sam))
        self.assertEqual(len(self.fake.calls), asked, "remembered")
        self.now[0] += 301
        self.assertTrue(self.nd.verify(self.sam))
        self.assertGreater(len(self.fake.calls), asked)

    def test_a_wrong_password_is_not_verified(self):
        self.assertFalse(self.nd.verify(token("sam", "not his password")))
        self.assertFalse(self.nd.verify(token("nobody", "x")))

    def test_an_unreachable_music_server_means_not_verified(self):
        self.fake.down = True
        self.assertFalse(self.nd.verify(self.sam))

    def test_forgetting_a_person_makes_the_next_check_ask_again(self):
        self.nd.verify(self.sam)
        self.nd.forget("SAM")
        asked = len(self.fake.calls)
        self.nd.verify(self.sam)
        self.assertGreater(len(self.fake.calls), asked)

    def test_who_is_an_administrator_is_the_music_servers_word(self):
        self.assertFalse(self.nd.is_admin(self.sam))
        self.assertTrue(self.nd.is_admin(token("owner", "owner-pw")))

    def test_a_person_can_see_a_song_unless_it_is_hidden_from_them_or_gone(self):
        self.assertEqual(self.nd.song_as(self.sam, self.song)["title"], "Silvera")
        self.fake.hidden_from[self.song] = {"sam"}
        self.assertIsNone(self.nd.song_as(self.sam, self.song))
        self.assertIsNone(self.nd.song_as(token("mia", "mia-pw"), "no-such-song"))

    def test_the_administrators_view_says_where_the_file_is_and_what_it_is(self):
        found = self.nd.file_of(self.song)
        self.assertEqual((found.path, found.library_path, found.suffix), ("Gojira/Magma/03 - Silvera.opus", "/music", "opus"))
        self.assertEqual((found.title, found.artist, found.album, found.year, found.track), ("Silvera", "Gojira", "Magma", 2016, 3))
        self.assertEqual((found.duration, found.bit_rate, found.release_group), (200.0, 128, "rg-1"))

    def test_without_the_administrators_login_paths_are_not_available(self):
        nd = Navidrome("http://nd", transport=self.fake)
        self.assertIsNone(nd.file_of(self.song))
        self.assertFalse(nd.start_scan())

    def test_a_wrong_administrator_password_gives_nothing(self):
        nd = Navidrome("http://nd", admin_user="owner", admin_password="wrong", transport=self.fake)
        self.assertIsNone(nd.file_of(self.song))

    def test_an_expired_administrator_sign_in_is_renewed_once(self):
        self.nd.file_of(self.song)
        self.fake.revoke_jwt_once = True
        self.assertIsNotNone(self.nd.file_of(self.song))
        logins = [c for c in self.fake.calls if c[1].endswith("/auth/login")]
        self.assertEqual(len(logins), 2)

    def test_the_administrator_signs_in_once_for_many_questions(self):
        for _ in range(5):
            self.nd.file_of(self.song)
        self.assertEqual(len([c for c in self.fake.calls if c[1].endswith("/auth/login")]), 1)

    def test_a_file_is_found_by_its_path_but_never_a_missing_one(self):
        self.assertEqual(self.nd.find_by_path("Gojira/Magma/03 - Silvera.opus").id, self.song)
        self.assertIsNone(self.nd.find_by_path("Gojira/Magma/03 - Silvera.flac"))
        self.fake.songs[self.song]["missing"] = True
        self.assertIsNone(self.nd.find_by_path("Gojira/Magma/03 - Silvera.opus"))

    def test_a_rescan_is_asked_as_the_administrator(self):
        self.assertTrue(self.nd.start_scan())
        self.assertEqual(self.fake.scans, 1)
        self.fake.scanning = True
        self.assertTrue(self.nd.scanning())

    def test_an_odd_record_is_not_a_song(self):
        self.assertIsNone(Navidrome._file({"id": "x"}))
        self.assertIsNone(Navidrome._file("text"))
        self.assertIsNone(Navidrome._file(None))


if __name__ == "__main__":
    unittest.main()
