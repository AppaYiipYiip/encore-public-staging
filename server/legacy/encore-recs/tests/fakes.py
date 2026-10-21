"""A music server's database as the real one lays it out (the columns this module reads), and fake public services."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE user (id TEXT PRIMARY KEY, user_name TEXT, is_admin INTEGER DEFAULT 0);
CREATE TABLE media_file (id TEXT PRIMARY KEY, path TEXT, title TEXT, artist TEXT, album_artist TEXT, album TEXT,
  mbz_artist_id TEXT DEFAULT '', mbz_album_artist_id TEXT DEFAULT '', missing INTEGER DEFAULT 0);
CREATE TABLE annotation (user_id TEXT, item_id TEXT, item_type TEXT, play_count INTEGER DEFAULT 0, play_date TEXT, rating INTEGER DEFAULT 0,
  starred INTEGER DEFAULT 0, starred_at TEXT, rated_at TEXT);
"""


class MusicDb:
    """Builds a database file like the music server's. Kept open in write-ahead mode so what is written lives in the log, as on a live server."""

    def __init__(self, folder: Path):
        self.path = folder / "navidrome.db"
        self.db = sqlite3.connect(str(self.path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA wal_autocheckpoint=0")  # never fold the log into the main file: the newest data stays only in the log
        self.db.executescript(SCHEMA)
        self.db.commit()
        self._n = 0

    def person(self, name: str, admin: bool = False) -> str:
        self.db.execute("INSERT INTO user (id, user_name, is_admin) VALUES (?,?,?)", (f"u-{name}", name, int(admin)))
        self.db.commit()
        return f"u-{name}"

    def song(self, artist: str, title: str, *, album: str = "Album", mbid: str = "", missing: bool = False, album_artist: str = "") -> str:
        self._n += 1
        song_id = f"s{self._n}"
        self.db.execute("INSERT INTO media_file (id, path, title, artist, album_artist, album, mbz_artist_id, missing) VALUES (?,?,?,?,?,?,?,?)",
                        (song_id, f"{artist}/{album}/{title}.opus", title, artist, album_artist, album, mbid, int(missing)))
        self.db.commit()
        return song_id

    def play(self, person: str, song_id: str, *, plays: int = 1, starred: bool = False, when: str | None = "2026-10-10 12:00:00+00:00") -> None:
        self.db.execute("INSERT INTO annotation (user_id, item_id, item_type, play_count, play_date, starred) VALUES (?,?,?,?,?,?)",
                        (f"u-{person}", song_id, "media_file", plays, when, int(starred)))
        self.db.commit()

    def close(self):
        self.db.close()


class FakeWorld:
    """`Get` for the public services: canned answers, a record of what was asked, and a switch for each to misbehave."""

    def __init__(self):
        self.mb_artists: dict[str, list[dict]] = {}        # name -> search results
        self.similar: dict[str, list[dict]] = {}           # mbid -> labs results
        self.deezer_artists: dict[str, list[dict]] = {}    # name -> search results
        self.deezer_tops: dict[int, list[dict]] = {}       # id -> tracks
        self.releases: dict[str, list[dict]] = {}          # mbid -> release groups
        self.calls: list[str] = []
        self.fail_with: int | None = None
        self.fail_first = 0          # the first this-many calls answer 503 and then the service is fine again

    def __call__(self, url: str):
        import json
        import urllib.parse
        self.calls.append(url)
        if self.fail_with is not None:
            return self.fail_with, None
        if len(self.calls) <= self.fail_first:
            return 503, None
        parts = urllib.parse.urlsplit(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        if parts.netloc == "musicbrainz.org" and parts.path == "/ws/2/artist/":
            name = q["query"].split('"')[1]
            return 200, {"artists": self.mb_artists.get(name, [])}
        if parts.netloc == "musicbrainz.org" and parts.path == "/ws/2/release-group":
            return 200, {"release-groups": self.releases.get(q["artist"], [])}
        if parts.netloc == "labs.api.listenbrainz.org":
            return 200, self.similar.get(q["artist_mbids"], [])
        if parts.netloc == "api.deezer.com" and parts.path == "/search/artist":
            name = q["q"].strip('"')
            return 200, {"data": self.deezer_artists.get(name, [])}
        if parts.netloc == "api.deezer.com" and parts.path.endswith("/top"):
            artist_id = int(parts.path.split("/")[2])
            return 200, {"data": self.deezer_tops.get(artist_id, [])}
        return 404, None

    # -- arranging
    def artist(self, name: str, mbid: str, similar: list[tuple[str, str, float]], *, deezer_id: int | None = None, songs: list[str] | None = None):
        self.mb_artists[name] = [{"id": mbid, "name": name, "score": 100}]
        self.similar[mbid] = [{"artist_mbid": m, "name": n, "score": s} for m, n, s in similar]
        if deezer_id is not None:
            self.deezer_artists[name] = [{"id": deezer_id, "name": name, "nb_fan": 1000}]
            self.deezer_tops[deezer_id] = [{"title": t, "title_short": t, "artist": {"name": name}, "album": {"title": f"{name} album"},
                                            "duration": 200 + i, "rank": 500_000 - i * 1000} for i, t in enumerate(songs or [])]
