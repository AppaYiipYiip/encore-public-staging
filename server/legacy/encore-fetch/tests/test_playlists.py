"""Reading a pasted playlist link (docs/39 F1, F9): the list of songs in a public Spotify or YouTube / YouTube Music
playlist or album, so the app can add them to a person's library. Pure logic plus two small readers whose I/O is
injected."""
import json
import unittest

from encore_fetch.playlists import (MAX_TRACKS, SPOTIFY_EMBED_LIMIT, PlaylistError, Track,
                                    clean_title, read_playlist,
                                    split_artist_title, spotify_tracks)


def spotify_page(name: str, tracks: list[dict]) -> str:
    """The shape of the public embed page (checked against the real one on 2026-10-17)."""
    data = {"props": {"pageProps": {"state": {"data": {"entity": {
        "name": name, "title": name, "type": "playlist", "trackList": tracks}}}}}}
    return ('<html><head></head><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(data) + "</script></body></html>")


def spotify_track(title: str, subtitle: str, ms: int = 200000) -> dict:
    return {"title": title, "subtitle": subtitle, "duration": ms, "isExplicit": False,
            "uri": "spotify:track:3XmwAZpIMNpTJy8faw3ajD"}


class CleanTitleTest(unittest.TestCase):
    def test_what_a_video_adds_to_a_song_goes(self):
        for raw in ("The Type (Official Music Video)", "The Type [Official Audio]",
                    "The Type (Video Oficial)", "The Type ( Video Lyric )",
                    "The Type (Performance Video)", "The Type (Lyrics)", "The Type | Official Video"):
            self.assertEqual(clean_title(raw), "The Type", raw)

    def test_featured_artists_go_the_name_of_the_song_stays(self):
        self.assertEqual(clean_title("POR EL CONTRARIO ft. Angela Aguilar"), "POR EL CONTRARIO")
        self.assertEqual(clean_title("Song (feat. Someone)"), "Song")

    def test_a_version_that_is_the_song_is_kept(self):
        self.assertEqual(clean_title("Windowpane (Live at Shepherd's Bush)"),
                         "Windowpane (Live at Shepherd's Bush)")
        self.assertEqual(clean_title("Blackwater Park (2008 Remaster)"), "Blackwater Park (2008 Remaster)")


class SplitArtistTitleTest(unittest.TestCase):
    def test_artist_dash_title(self):
        self.assertEqual(split_artist_title("Arcangel - FN8 ( Video Lyric )", "Arcangel"), ("Arcangel", "FN8"))

    def test_title_dash_artists_when_the_channel_is_the_right_hand_side(self):
        # "BELLAKEO (Video Oficial) - Peso Pluma, Anitta" on the channel "Peso Pluma"
        self.assertEqual(split_artist_title("BELLAKEO (Video Oficial) - Peso Pluma, Anitta", "Peso Pluma"),
                         ("Peso Pluma", "BELLAKEO"))

    def test_the_channel_decides_which_side_is_the_artist(self):
        self.assertEqual(
            split_artist_title("Becky G - POR EL CONTRARIO (Performance Video) ft. Angela Aguilar", "Becky G"),
            ("Becky G", "POR EL CONTRARIO"))

    def test_a_topic_channel_is_the_artist_and_the_title_is_clean(self):
        self.assertEqual(split_artist_title("The Leper Affinity", "Opeth - Topic"), ("Opeth", "The Leper Affinity"))

    def test_no_dash_the_channel_is_the_artist(self):
        self.assertEqual(split_artist_title("Windowpane (Official Video)", "OpethVEVO"), ("Opeth", "Windowpane"))

    def test_neither_side_is_the_channel_it_is_artist_dash_title(self):
        self.assertEqual(split_artist_title("Opeth - Windowpane", "Some Uploader"), ("Opeth", "Windowpane"))


class SpotifyTest(unittest.TestCase):
    def test_tracks_with_artist_title_and_length(self):
        html = spotify_page("Evening", [spotify_track("expectations (feat. Chappell Roan)",
                                                      "Olivia Rodrigo,\xa0Chappell Roan", 223935),
                                        spotify_track("Nicole Kidman", "ADELA", 181270)])

        name, tracks = spotify_tracks(html)

        self.assertEqual(name, "Evening")
        self.assertEqual(tracks[0], Track("expectations (feat. Chappell Roan)", "Olivia Rodrigo",
                                          duration_s=223, artists=("Olivia Rodrigo", "Chappell Roan")))
        self.assertEqual(tracks[1].duration_s, 181)

    def test_a_page_without_the_list_says_so(self):
        with self.assertRaises(PlaylistError) as ctx:
            spotify_tracks("<html>no data here</html>")
        self.assertEqual(ctx.exception.code, "unreadable")

    def test_songs_without_a_title_are_skipped(self):
        html = spotify_page("x", [spotify_track("", "Somebody"), spotify_track("Real", "Somebody")])
        self.assertEqual([t.title for t in spotify_tracks(html)[1]], ["Real"])


class ReadPlaylistTest(unittest.TestCase):
    def pages(self, html):
        asked = []

        def http(url: str) -> str:
            asked.append(url)
            return html

        return http, asked

    def test_a_spotify_playlist_is_read_from_its_embed_page(self):
        http, asked = self.pages(spotify_page("Evening", [spotify_track("Song", "Artist")]))

        playlist = read_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc", http=http)

        self.assertEqual(asked, ["https://open.spotify.com/embed/playlist/37i9dQZF1DXcBWIGoYBM5M"])
        self.assertEqual((playlist.source, playlist.name, playlist.kind), ("spotify", "Evening", "playlist"))
        self.assertEqual(playlist.tracks[0].artist, "Artist")

    def test_a_spotify_album_too_and_a_link_in_a_language_folder(self):
        http, asked = self.pages(spotify_page("Damnation", [spotify_track("Windowpane", "Opeth")]))

        playlist = read_playlist("https://open.spotify.com/intl-fr/album/4kZMWfXCP5uJi6tGRJ3IA0", http=http)

        self.assertEqual(asked, ["https://open.spotify.com/embed/album/4kZMWfXCP5uJi6tGRJ3IA0"])
        self.assertEqual(playlist.kind, "album")

    def test_a_youtube_playlist_comes_from_the_flat_listing(self):
        def ytdlp(url: str) -> dict:
            self.assertEqual(url, "https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI")
            return {"title": "Popular", "entries": [
                {"id": "fOT0BUpITw8", "title": "BELLAKEO (Video Oficial) - Peso Pluma, Anitta",
                 "channel": "Peso Pluma", "duration": 235},
                {"id": "NFvDHYMzj9U", "title": "Arcangel - FN8 ( Video Lyric )", "uploader": "Arcangel",
                 "duration": 650},
                {"id": "xxxxxxxxxxx", "title": "[Private video]", "duration": None},
                None]}

        playlist = read_playlist("https://music.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI",
                                 ytdlp=ytdlp)

        self.assertEqual((playlist.source, playlist.name), ("youtube", "Popular"))
        self.assertEqual([(t.artist, t.title, t.video_id) for t in playlist.tracks],
                         [("Peso Pluma", "BELLAKEO", "fOT0BUpITw8"), ("Arcangel", "FN8", "NFvDHYMzj9U")])
        self.assertEqual(playlist.tracks[0].duration_s, 235)

    def test_a_topic_upload_is_marked_official_and_a_music_video_is_not(self):
        playlist = read_playlist("https://music.youtube.com/playlist?list=PLMXloh6Hpt1I", ytdlp=lambda url: {
            "title": "liked", "entries": [
                {"id": "sj27caXHKm4", "title": "In Mist She Was Standing", "channel": "Opeth - Topic"},
                {"id": "NFvDHYMzj9U", "title": "Arcangel - FN8 ( Video Lyric )", "channel": "Arcangel"}]})
        self.assertEqual([(t.title, t.official) for t in playlist.tracks],
                         [("In Mist She Was Standing", True), ("FN8", False)])

    def test_a_very_long_playlist_is_cut_and_says_so(self):
        many = [spotify_track(f"Song {i}", "Artist") for i in range(MAX_TRACKS + 20)]
        http, _ = self.pages(spotify_page("Long", many))

        playlist = read_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", http=http)

        self.assertEqual(len(playlist.tracks), MAX_TRACKS)
        self.assertTrue(playlist.truncated)

    def test_a_spotify_playlist_that_fills_the_embed_page_may_be_longer_and_says_so(self):
        # Spotify's embed page shows 100 songs of a playlist and never says how long the playlist is; two of the owner's
        # test playlists came back as exactly 100. "Not truncated" would have been a lie.
        full = [spotify_track(f"Song {i}", "Artist") for i in range(SPOTIFY_EMBED_LIMIT)]
        http, _ = self.pages(spotify_page("Long", full))
        playlist = read_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", http=http)
        self.assertEqual(len(playlist.tracks), SPOTIFY_EMBED_LIMIT)
        self.assertTrue(playlist.truncated)

    def test_a_shorter_spotify_playlist_is_whole(self):
        http, _ = self.pages(spotify_page("Short", [spotify_track(f"Song {i}", "Artist") for i in range(67)]))
        playlist = read_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", http=http)
        self.assertFalse(playlist.truncated)

    def test_a_youtube_playlist_of_a_few_hundred_songs_is_not_cut(self):
        entries = [{"id": f"{i:011d}", "title": f"Artist - Song {i}", "channel": "Artist"} for i in range(700)]
        playlist = read_playlist("https://music.youtube.com/playlist?list=PLMXloh6Hpt1I",
                                 ytdlp=lambda url: {"title": "liked", "entries": entries})
        self.assertEqual(len(playlist.tracks), 700)
        self.assertFalse(playlist.truncated)

    def test_only_these_services_are_asked(self):
        # The service fetches pages for people: it must never be pointed at anything else (the server's own
        # network, a look-alike address).
        http, asked = self.pages("")
        for link in ("http://169.254.169.254/latest/meta-data/",
                     "https://open.spotify.com.evil.example/playlist/37i9dQZF1DXcBWIGoYBM5M",
                     "https://evil.example/open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
                     "file:///etc/passwd", "ftp://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
                     "https://example.org/playlist?list=PL123", "not a link", ""):
            with self.assertRaises(PlaylistError, msg=link) as ctx:
                read_playlist(link, http=http, ytdlp=lambda u: {})
            self.assertEqual(ctx.exception.code, "unsupported", link)
        self.assertEqual(asked, [])

    def test_a_service_that_does_not_answer_is_said_plainly(self):
        def http(url: str) -> str:
            raise OSError("timed out")

        with self.assertRaises(PlaylistError) as ctx:
            read_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", http=http)
        self.assertEqual(ctx.exception.code, "unreachable")
        self.assertIn("did not answer", ctx.exception.message)

    def test_a_private_or_missing_youtube_playlist_is_said_plainly(self):
        def ytdlp(url: str) -> dict:
            raise RuntimeError("YouTube said: The playlist does not exist.")

        with self.assertRaises(PlaylistError) as ctx:
            read_playlist("https://www.youtube.com/playlist?list=PL1234567890abcdefghijklmnopqrstu", ytdlp=ytdlp)
        self.assertEqual(ctx.exception.code, "not_found")


if __name__ == "__main__":
    unittest.main()
