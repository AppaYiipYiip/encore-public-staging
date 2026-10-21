"""Which release a song comes from: named after what a person would notice (the right edition, and never a wrong album)."""
import unittest

from encore_quality.matching import NO_ARTIST, NO_RELEASE, Song, choose
from encore_quality.textnorm import norm_album, norm_artist, norm_title, same_artist


def album(title, artist, kind="Album", date="2001-01-01", secondary=(), mbid=None, releases=1):
    return {"title": title, "artist": {"artistName": artist}, "albumType": kind, "releaseDate": date, "secondaryTypes": list(secondary),
            "foreignAlbumId": mbid or f"mbid-{title}-{date}", "releases": [{}] * releases}


class NamesTest(unittest.TestCase):
    def test_an_edition_is_the_same_album(self):
        for edition in ("Magma (Deluxe Edition)", "Magma - Remastered 2020", "Magma [Expanded]", "MAGMA", "Magma (Bonus Tracks)"):
            self.assertEqual(norm_album(edition), "magma", edition)

    def test_a_different_album_stays_different(self):
        self.assertNotEqual(norm_album("Magma"), norm_album("Magma Rising"))
        self.assertEqual(norm_album("OK Computer OKNOTOK 1997 2017"), "ok computer oknotok 1997 2017")

    def test_an_album_whose_whole_title_is_a_bracket_keeps_it(self):
        self.assertEqual(norm_album("(Untitled)"), "untitled")
        self.assertEqual(norm_album("[ ]"), "")

    def test_accents_and_punctuation_do_not_matter(self):
        self.assertEqual(norm_artist("Beyoncé"), norm_artist("Beyonce"))
        self.assertEqual(norm_artist("Guns N' Roses"), norm_artist("Guns N Roses"))
        self.assertEqual(norm_artist("Simon & Garfunkel"), norm_artist("Simon and Garfunkel"))
        self.assertEqual(norm_artist("The Beatles"), norm_artist("Beatles"))

    def test_a_song_title_loses_what_a_store_adds(self):
        self.assertEqual(norm_title("Song (Remastered 2011) [Official Audio]"), "song")
        self.assertEqual(norm_title("Song - 2011 Remaster"), "song")
        self.assertEqual(norm_title("Song (feat. Someone)"), "song")

    def test_two_artists_with_similar_names_are_not_the_same(self):
        self.assertTrue(same_artist("Tool", "TOOL"))
        self.assertFalse(same_artist("Tool", "Tools"))
        self.assertFalse(same_artist("Opeth", "Opus"))
        self.assertFalse(same_artist("", "Opeth"))


class ChoosingTest(unittest.TestCase):
    def test_the_album_the_song_is_on_is_chosen_not_a_tribute_to_it(self):
        found = [album("Tool Lateralus album with SM64 Soundfont", "OkNevermind"),
                 album("Vitamin String Quartet Tribute to Tool's Lateralus", "Vitamin String Quartet"),
                 album("Lateralus", "Tool", date="2001-05-14", mbid="the-album"),
                 album("Lateralus", "Tool", kind="Single", date="2002-02-01")]
        choice = choose(Song("Tool", "Lateralus", "Schism", 2001), found)
        self.assertTrue(choice.found)
        self.assertEqual(choice.album["foreignAlbumId"], "the-album")

    def test_the_plain_album_is_preferred_to_its_live_version_of_the_same_name(self):
        found = [album("Blackwater Park", "Opeth", secondary=["Live"], date="2010-01-01", mbid="live"),
                 album("Blackwater Park", "Opeth", date="2001-03-12", mbid="studio")]
        self.assertEqual(choose(Song("Opeth", "Blackwater Park", "Bleak", 2001), found).album["foreignAlbumId"], "studio")

    def test_a_catalogue_edition_name_still_finds_the_album(self):
        found = [album("Magma", "Gojira", date="2016-06-17", mbid="magma")]
        self.assertEqual(choose(Song("Gojira", "Magma (Deluxe Edition)", "Silvera"), found).album["foreignAlbumId"], "magma")

    def test_a_single_is_found_by_the_songs_own_name_when_the_album_is_unknown_to_the_catalogue(self):
        found = [album("Silvera", "Gojira", kind="Single", date="2016-05-20", mbid="the-single")]
        self.assertEqual(choose(Song("Gojira", "Silvera - Single", "Silvera"), found).album["foreignAlbumId"], "the-single")

    def test_the_song_title_alone_never_picks_an_album_of_another_name(self):
        found = [album("From Mars to Sirius", "Gojira")]
        choice = choose(Song("Gojira", "Magma", "Silvera"), found)
        self.assertFalse(choice.found)
        self.assertEqual(choice.reason, NO_RELEASE)

    def test_another_artists_album_of_the_same_name_is_never_taken(self):
        choice = choose(Song("Tool", "Lateralus", "Schism"), [album("Lateralus", "Some Cover Band")])
        self.assertFalse(choice.found)
        self.assertEqual(choice.reason, NO_ARTIST)

    def test_nothing_found_is_said(self):
        self.assertEqual(choose(Song("Tool", "Lateralus", "Schism"), []).reason, NO_ARTIST)

    def test_when_two_editions_have_the_same_name_the_closer_year_wins(self):
        found = [album("Greatest Hits", "Queen", date="1981-11-02", mbid="1981"), album("Greatest Hits", "Queen", date="2011-01-01", mbid="2011")]
        self.assertEqual(choose(Song("Queen", "Greatest Hits", "x", 1982), found).album["foreignAlbumId"], "1981")
        self.assertEqual(choose(Song("Queen", "Greatest Hits", "x", 2010), found).album["foreignAlbumId"], "2011")

    def test_an_id_in_the_files_tags_is_trusted_over_names(self):
        found = [album("Other name entirely", "Somebody", mbid="from-the-tags"), album("Lateralus", "Tool")]
        choice = choose(Song("Tool", "Lateralus", "Schism", release_group="from-the-tags"), found)
        self.assertEqual(choice.album["foreignAlbumId"], "from-the-tags")


if __name__ == "__main__":
    unittest.main()
