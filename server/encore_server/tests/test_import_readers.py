"""Reading a pasted playlist link (docs/39 F1, F9): the list of songs in a public Spotify or YouTube / YouTube Music
playlist or album, so the app can add them to a person's library. Pure logic plus two small readers whose I/O is
injected."""

import json
import pathlib
import unittest

from encore_server.imports.readers import (
    MAX_TRACKS,
    SPOTIFY_EMBED_LIMIT,
    PlaylistError,
    Track,
    clean_title,
    read_playlist,
    split_artist_title,
    spotify_tracks,
    ytmusic_reader,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "ytm"
LINK = "https://music.youtube.com/playlist?list=OLAK5uy_m59x-hBFsC789l1_qWwFXwH3gjntwy_CA"


def recorded(name: str) -> dict:
    """What `ytmusicapi.get_playlist` really answered on 2026-10-22 (thumbnails left out)."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def spotify_page(name: str, tracks: list[dict]) -> str:
    """The shape of the public embed page (checked against the real one on 2026-10-17)."""
    data = {
        "props": {
            "pageProps": {"state": {"data": {"entity": {"name": name, "title": name, "type": "playlist", "trackList": tracks}}}}
        }
    }
    return (
        '<html><head></head><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(data)
        + "</script></body></html>"
    )


def spotify_track(title: str, subtitle: str, ms: int = 200000) -> dict:
    return {
        "title": title,
        "subtitle": subtitle,
        "duration": ms,
        "isExplicit": False,
        "uri": "spotify:track:3XmwAZpIMNpTJy8faw3ajD",
    }


class CleanTitleTest(unittest.TestCase):
    def test_what_a_video_adds_to_a_song_goes(self):
        for raw in (
            "The Type (Official Music Video)",
            "The Type [Official Audio]",
            "The Type (Video Oficial)",
            "The Type ( Video Lyric )",
            "The Type (Performance Video)",
            "The Type (Lyrics)",
            "The Type | Official Video",
        ):
            self.assertEqual(clean_title(raw), "The Type", raw)

    def test_featured_artists_go_the_name_of_the_song_stays(self):
        self.assertEqual(clean_title("POR EL CONTRARIO ft. Angela Aguilar"), "POR EL CONTRARIO")
        self.assertEqual(clean_title("Song (feat. Someone)"), "Song")

    def test_a_version_that_is_the_song_is_kept(self):
        self.assertEqual(clean_title("Windowpane (Live at Shepherd's Bush)"), "Windowpane (Live at Shepherd's Bush)")
        self.assertEqual(clean_title("Blackwater Park (2008 Remaster)"), "Blackwater Park (2008 Remaster)")


class SplitArtistTitleTest(unittest.TestCase):
    def test_artist_dash_title(self):
        self.assertEqual(split_artist_title("Arcangel - FN8 ( Video Lyric )", "Arcangel"), ("Arcangel", "FN8"))

    def test_title_dash_artists_when_the_channel_is_the_right_hand_side(self):
        # "BELLAKEO (Video Oficial) - Peso Pluma, Anitta" on the channel "Peso Pluma"
        self.assertEqual(
            split_artist_title("BELLAKEO (Video Oficial) - Peso Pluma, Anitta", "Peso Pluma"), ("Peso Pluma", "BELLAKEO")
        )

    def test_the_channel_decides_which_side_is_the_artist(self):
        self.assertEqual(
            split_artist_title("Becky G - POR EL CONTRARIO (Performance Video) ft. Angela Aguilar", "Becky G"),
            ("Becky G", "POR EL CONTRARIO"),
        )

    def test_a_topic_channel_is_the_artist_and_the_title_is_clean(self):
        self.assertEqual(split_artist_title("The Leper Affinity", "Opeth - Topic"), ("Opeth", "The Leper Affinity"))

    def test_no_dash_the_channel_is_the_artist(self):
        self.assertEqual(split_artist_title("Windowpane (Official Video)", "OpethVEVO"), ("Opeth", "Windowpane"))

    def test_neither_side_is_the_channel_it_is_artist_dash_title(self):
        self.assertEqual(split_artist_title("Opeth - Windowpane", "Some Uploader"), ("Opeth", "Windowpane"))


class SpotifyTest(unittest.TestCase):
    def test_tracks_with_artist_title_and_length(self):
        html = spotify_page(
            "Evening",
            [
                spotify_track("expectations (feat. Chappell Roan)", "Olivia Rodrigo,\xa0Chappell Roan", 223935),
                spotify_track("Nicole Kidman", "ADELA", 181270),
            ],
        )

        name, tracks = spotify_tracks(html)

        self.assertEqual(name, "Evening")
        self.assertEqual(
            tracks[0],
            Track(
                "expectations (feat. Chappell Roan)",
                "Olivia Rodrigo",
                duration_s=223,
                artists=("Olivia Rodrigo", "Chappell Roan"),
            ),
        )
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
            return {
                "title": "Popular",
                "entries": [
                    {
                        "id": "fOT0BUpITw8",
                        "title": "BELLAKEO (Video Oficial) - Peso Pluma, Anitta",
                        "channel": "Peso Pluma",
                        "duration": 235,
                    },
                    {"id": "NFvDHYMzj9U", "title": "Arcangel - FN8 ( Video Lyric )", "uploader": "Arcangel", "duration": 650},
                    {"id": "xxxxxxxxxxx", "title": "[Private video]", "duration": None},
                    None,
                ],
            }

        playlist = read_playlist("https://music.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI", ytdlp=ytdlp)

        self.assertEqual((playlist.source, playlist.name), ("youtube", "Popular"))
        self.assertEqual(
            [(t.artist, t.title, t.video_id) for t in playlist.tracks],
            [("Peso Pluma", "BELLAKEO", "fOT0BUpITw8"), ("Arcangel", "FN8", "NFvDHYMzj9U")],
        )
        self.assertEqual(playlist.tracks[0].duration_s, 235)

    def test_a_topic_upload_is_marked_official_and_a_music_video_is_not(self):
        playlist = read_playlist(
            "https://music.youtube.com/playlist?list=PLMXloh6Hpt1I",
            ytdlp=lambda url: {
                "title": "liked",
                "entries": [
                    {"id": "sj27caXHKm4", "title": "In Mist She Was Standing", "channel": "Opeth - Topic"},
                    {"id": "NFvDHYMzj9U", "title": "Arcangel - FN8 ( Video Lyric )", "channel": "Arcangel"},
                ],
            },
        )
        self.assertEqual([(t.title, t.official) for t in playlist.tracks], [("In Mist She Was Standing", True), ("FN8", False)])

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
        playlist = read_playlist(
            "https://music.youtube.com/playlist?list=PLMXloh6Hpt1I", ytdlp=lambda url: {"title": "liked", "entries": entries}
        )
        self.assertEqual(len(playlist.tracks), 700)
        self.assertFalse(playlist.truncated)

    def test_only_these_services_are_asked(self):
        # The service fetches pages for people: it must never be pointed at anything else (the server's own
        # network, a look-alike address).
        http, asked = self.pages("")
        for link in (
            "http://169.254.169.254/latest/meta-data/",
            "https://open.spotify.com.evil.example/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "https://evil.example/open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "file:///etc/passwd",
            "ftp://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "https://example.org/playlist?list=PL123",
            "not a link",
            "",
        ):
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


class YouTubeMusicPlaylistTest(unittest.TestCase):
    """The quick way in: YouTube Music's own listing, checked against answers recorded from the real service."""

    def test_an_album_comes_with_real_titles_artists_album_length_and_the_video_of_every_song(self):
        playlist = read_playlist(LINK, ytmusic=lambda ident: recorded("playlist_album.json"))

        self.assertEqual((playlist.source, playlist.name, len(playlist.tracks)), ("youtube", "In Rainbows", 10))
        first = playlist.tracks[0]
        self.assertEqual((first.title, first.artist, first.album, first.duration_s), ("15 Step", "Radiohead", "In Rainbows", 238))
        self.assertEqual(first.video_id, "bgsmr7t8zGE")
        self.assertTrue(all(t.official and t.video_id for t in playlist.tracks), "YouTube's own audio uploads: nothing to search")

    def test_a_playlist_of_a_hundred_and_fifty_songs_is_read_whole(self):
        playlist = read_playlist(
            "https://music.youtube.com/playlist?list=PLiXZsbFff5pE3hkUVO0QK-qNFIoPGZmOI",
            ytmusic=lambda ident: recorded("playlist_community.json"),
        )

        self.assertEqual((playlist.name, len(playlist.tracks), playlist.truncated), ("Early 2000s hip hop", 149, False))
        self.assertEqual(sum(1 for t in playlist.tracks if t.video_id), 147)

    def test_a_song_youtube_no_longer_has_keeps_its_name_and_is_searched_by_it(self):
        playlist = read_playlist(LINK, ytmusic=lambda ident: recorded("playlist_community.json"))

        gone = next(t for t in playlist.tracks if t.title == "We Fly High")
        self.assertEqual((gone.artist, gone.album, gone.duration_s), ("Jim Jones", "Hustler's P.o.m.e.", 240))
        self.assertIsNone(gone.video_id)
        self.assertFalse(gone.official)

    def test_a_music_video_is_not_taken_for_the_song_and_its_title_is_cleaned(self):
        playlist = read_playlist(LINK, ytmusic=lambda ident: recorded("playlist_community.json"))

        video = next(t for t in playlist.tracks if t.video_id == "2IH8tNQAzSs")
        self.assertEqual((video.title, video.artist, video.official), ("Lollipop", "Lil Wayne", False))

    def test_the_playlist_id_is_what_is_asked_for(self):
        asked = []

        def listing(ident: str) -> dict:
            asked.append(ident)
            return recorded("playlist_album.json")

        read_playlist("https://www.youtube.com/watch?v=abc&list=OLAK5uy_m59x-hBFsC789l1_qWwFXwH3gjntwy_CA", ytmusic=listing)
        self.assertEqual(asked, ["OLAK5uy_m59x-hBFsC789l1_qWwFXwH3gjntwy_CA"])

    def test_yt_dlp_is_not_asked_when_the_quick_way_worked(self):
        def ytdlp(url: str) -> dict:
            raise AssertionError("yt-dlp must not be started for a list YouTube Music gave")

        read_playlist(LINK, ytmusic=lambda ident: recorded("playlist_album.json"), ytdlp=ytdlp)

    def test_when_the_quick_way_fails_yt_dlp_reads_the_playlist(self):
        def listing(ident: str) -> dict:
            raise RuntimeError("Server returned HTTP 404: Not Found")

        playlist = read_playlist(
            LINK,
            ytmusic=listing,
            ytdlp=lambda url: {
                "title": "Old way",
                "entries": [{"id": "sj27caXHKm4", "title": "In Mist She Was Standing", "channel": "Opeth - Topic"}],
            },
        )

        self.assertEqual((playlist.name, playlist.tracks[0].artist), ("Old way", "Opeth"))

    def test_when_the_quick_way_finds_no_songs_yt_dlp_is_asked_too(self):
        playlist = read_playlist(
            LINK,
            ytmusic=lambda ident: {"title": "x", "tracks": []},
            ytdlp=lambda url: {
                "title": "Old way",
                "entries": [{"id": "sj27caXHKm4", "title": "Song", "channel": "Artist - Topic"}],
            },
        )
        self.assertEqual(playlist.name, "Old way")

    def test_a_private_playlist_is_still_said_plainly_when_both_ways_fail(self):
        def listing(ident: str) -> dict:
            raise RuntimeError("nope")

        def ytdlp(url: str) -> dict:
            raise RuntimeError("YouTube said: This playlist is private.")

        with self.assertRaises(PlaylistError) as ctx:
            read_playlist(LINK, ytmusic=listing, ytdlp=ytdlp)
        self.assertEqual(ctx.exception.code, "not_found")

    def test_a_very_long_listing_is_cut_and_says_so(self):
        many = {
            "title": "Long",
            "tracks": [
                {
                    "videoId": f"{i:011d}",
                    "title": f"Song {i}",
                    "isAvailable": True,
                    "artists": [{"name": "Artist"}],
                    "album": None,
                    "duration_seconds": 200,
                    "videoType": "MUSIC_VIDEO_TYPE_ATV",
                }
                for i in range(MAX_TRACKS + 5)
            ],
        }
        playlist = read_playlist(LINK, ytmusic=lambda ident: many)
        self.assertEqual(len(playlist.tracks), MAX_TRACKS)
        self.assertTrue(playlist.truncated)

    def test_entries_with_odd_shapes_are_skipped_not_fatal(self):
        odd = {
            "title": "Odd",
            "tracks": [
                None,
                "text",
                {"title": ""},
                {"title": "No artist", "artists": None},
                {
                    "title": "Fine",
                    "videoId": "sj27caXHKm4",
                    "artists": [{"name": "Opeth - Topic"}],
                    "videoType": "MUSIC_VIDEO_TYPE_ATV",
                    "isAvailable": True,
                },
            ],
        }
        playlist = read_playlist(LINK, ytmusic=lambda ident: odd)
        self.assertEqual(
            [(t.title, t.artist, t.official) for t in playlist.tracks], [("No artist", "", False), ("Fine", "Opeth", True)]
        )

    def test_the_reader_asks_for_one_more_than_the_limit_so_a_cut_is_noticed(self):
        calls = []

        class Client:
            def get_playlist(self, ident, limit=None):
                calls.append((ident, limit))
                return {"title": "x", "tracks": []}

        ytmusic_reader(factory=Client)("PLabcdefghijk")
        self.assertEqual(calls, [("PLabcdefghijk", MAX_TRACKS + 1)])


if __name__ == "__main__":
    unittest.main()


class SongThumbnailTest(unittest.TestCase):
    """P1-26: an imported song keeps the thumbnail its source gives it, so a song Deezer does not know shows a picture, not a letter."""

    def _ytm(self, **entry):
        base = {
            "videoId": "abcdefghijk",
            "title": "Song",
            "isAvailable": True,
            "artists": [{"name": "Artist"}],
            "album": None,
            "duration_seconds": 200,
            "videoType": "MUSIC_VIDEO_TYPE_ATV",
        }
        return {"title": "Mix", "tracks": [{**base, **entry}]}

    def test_a_youtube_music_track_keeps_its_largest_thumbnail(self):
        data = self._ytm(
            thumbnails=[
                {"url": "https://lh3.googleusercontent.com/a=w60-h60", "width": 60, "height": 60},
                {"url": "https://lh3.googleusercontent.com/a=w120-h120", "width": 120, "height": 120},
            ]
        )
        playlist = read_playlist(LINK, ytmusic=lambda ident: data)
        self.assertEqual(playlist.tracks[0].thumbnail, "https://lh3.googleusercontent.com/a=w120-h120")

    def test_a_track_without_a_thumbnail_has_none(self):
        playlist = read_playlist(LINK, ytmusic=lambda ident: self._ytm())
        self.assertIsNone(playlist.tracks[0].thumbnail)

    def test_a_thumbnail_on_a_host_the_picture_rules_do_not_allow_is_not_kept(self):
        data = self._ytm(thumbnails=[{"url": "https://evil.example/a.jpg", "width": 544, "height": 544}])
        playlist = read_playlist(LINK, ytmusic=lambda ident: data)
        self.assertIsNone(playlist.tracks[0].thumbnail)

    def test_a_yt_dlp_entry_keeps_its_largest_thumbnail(self):
        listing = {
            "title": "Mix",
            "entries": [
                {
                    "id": "abcdefghijk",
                    "title": "Artist - Song",
                    "channel": "Artist",
                    "duration": 200,
                    "thumbnails": [
                        {"url": "https://i.ytimg.com/vi/abcdefghijk/default.jpg", "width": 120, "height": 90},
                        {"url": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg", "width": 480, "height": 360},
                    ],
                }
            ],
        }
        playlist = read_playlist(LINK, ytdlp=lambda url: listing)
        self.assertEqual(playlist.tracks[0].thumbnail, "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg")


class PlaylistPictureTest(unittest.TestCase):
    """The picture a playlist has at its source, so the app can show it before any song has been looked at."""

    def test_the_biggest_picture_on_an_allowed_host_wins(self):
        from encore_server.imports.readers import largest_picture

        pictures = [
            {"url": "https://i.ytimg.com/small.jpg", "width": 60},
            {"url": "https://lh3.googleusercontent.com/big=w544", "width": 544},
            {"url": "https://evil.example/huge.jpg", "width": 4000},
            {"url": "http://i.ytimg.com/plain.jpg", "width": 9999},
        ]
        self.assertEqual(largest_picture(pictures), "https://lh3.googleusercontent.com/big=w544")

    def test_nothing_usable_is_none(self):
        from encore_server.imports.readers import largest_picture

        for odd in (None, [], "x", [{"url": 5}], [{"url": "https://evil.example/a.jpg"}], [None]):
            self.assertIsNone(largest_picture(odd), odd)

    def test_a_youtube_music_playlist_brings_its_thumbnail(self):
        data = recorded("playlist_album.json")
        data["thumbnails"] = [
            {"url": "https://lh3.googleusercontent.com/a=w60", "width": 60, "height": 60},
            {"url": "https://lh3.googleusercontent.com/a=w544", "width": 544, "height": 544},
        ]

        playlist = read_playlist(LINK, ytmusic=lambda ident: data)

        self.assertEqual(playlist.cover_url, "https://lh3.googleusercontent.com/a=w544")

    def test_a_spotify_page_brings_its_cover(self):
        page = spotify_page_with_cover("Mix", [spotify_track("Song", "Artist")], "https://i.scdn.co/image/abc")
        playlist = read_playlist("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", http=lambda url: page)

        self.assertEqual(playlist.cover_url, "https://i.scdn.co/image/abc")


def spotify_page_with_cover(name, tracks, cover):
    data = {
        "props": {
            "pageProps": {
                "state": {
                    "data": {
                        "entity": {
                            "name": name,
                            "title": name,
                            "type": "playlist",
                            "trackList": tracks,
                            "coverArt": {"sources": [{"url": cover, "width": 640, "height": 640}]},
                        }
                    }
                }
            }
        }
    }
    return (
        '<html><head></head><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(data)
        + "</script></body></html>"
    )
