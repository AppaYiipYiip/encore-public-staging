"""Fakes of Lidarr, the music server and slskd, answering the way the real programs did when they were tried (docs/46 results)."""
from __future__ import annotations

import copy
import re
import urllib.parse


def _quality(i, name):
    return {"quality": {"id": i, "name": name}, "items": [], "allowed": False}


def quality_schema():
    return {"name": "", "upgradeAllowed": False, "cutoff": 0, "items": [
        _quality(0, "Unknown"),
        {"name": "Low Quality Lossy", "id": 1002, "allowed": False, "items": [_quality(1, "MP3-192"), _quality(9, "AAC-192")]},
        {"name": "High Quality Lossy", "id": 1004, "allowed": False, "items": [_quality(2, "MP3-VBR-V0"), _quality(4, "MP3-320")]},
        {"name": "Lossless", "id": 1005, "allowed": False, "items": [_quality(6, "FLAC"), _quality(7, "ALAC"), _quality(21, "FLAC 24bit")]},
        _quality(13, "WAV")]}


def metadata_schema():
    return {"name": "", "primaryAlbumTypes": [{"albumType": {"id": i, "name": n}, "allowed": n == "Album"}
                                              for i, n in enumerate(("Album", "EP", "Single", "Broadcast", "Other"))],
            "secondaryAlbumTypes": [{"albumType": {"id": i, "name": n}, "allowed": n == "Studio"} for i, n in enumerate(("Studio", "Live", "Remix"))],
            "releaseStatuses": [{"releaseStatus": {"id": i, "name": n}, "allowed": n == "Official"}
                                for i, n in enumerate(("Official", "Promotion", "Bootleg"))]}


class FakeLidarr:
    """`Http` for the Lidarr client. The state is plain attributes so a test can arrange and inspect it."""

    def __init__(self):
        self.down = False
        self.calls: list[tuple[str, str]] = []
        self.root_folders: list[dict] = []
        self.quality_profiles: list[dict] = []
        self.metadata_profiles: list[dict] = []
        self.naming = {"id": 1, "renameTracks": False}
        self.media = {"id": 1, "copyUsingHardlinks": True}
        self.catalog: list[dict] = []          # what an album search finds
        self.artists: list[dict] = []
        self.albums: dict[int, dict] = {}
        self.tracks: dict[int, list[dict]] = {}
        self.track_files: dict[int, list[dict]] = {}
        self.refreshing: set[int] = set()      # artist ids whose refresh is still running
        self.refresh_seen_as: str = "ids"      # how the running command names the artist
        self.version = "3.1.0.4875"
        self._ids = iter(range(1, 10_000))

    # -- the Http interface
    def __call__(self, method, path, body=None):
        self.calls.append((method, path))
        if self.down:
            return 0, None
        url = urllib.parse.urlsplit(path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        handler = self._route(method, url.path)
        if handler is None:
            return 404, {"message": "NotFound"}
        return handler(body, query, url.path)

    def _route(self, method, path):
        table = [
            ("GET", r"/system/status", lambda b, q, p: (200, {"version": self.version})),
            ("GET", r"/rootfolder", lambda b, q, p: (200, copy.deepcopy(self.root_folders))),
            ("POST", r"/rootfolder", self._post_root),
            ("GET", r"/qualityprofile/schema", lambda b, q, p: (200, quality_schema())),
            ("GET", r"/qualityprofile", lambda b, q, p: (200, copy.deepcopy(self.quality_profiles))),
            ("POST", r"/qualityprofile", self._post_quality),
            ("PUT", r"/qualityprofile/\d+", self._put_quality),
            ("GET", r"/metadataprofile/schema", lambda b, q, p: (200, metadata_schema())),
            ("GET", r"/metadataprofile", lambda b, q, p: (200, copy.deepcopy(self.metadata_profiles))),
            ("POST", r"/metadataprofile", self._post_metadata),
            ("PUT", r"/metadataprofile/\d+", self._put_metadata),
            ("GET", r"/config/naming", lambda b, q, p: (200, dict(self.naming))),
            ("PUT", r"/config/naming/\d+", self._put_naming),
            ("GET", r"/config/mediamanagement", lambda b, q, p: (200, dict(self.media))),
            ("PUT", r"/config/mediamanagement/\d+", self._put_media),
            ("GET", r"/album/lookup", lambda b, q, p: (200, copy.deepcopy(self.catalog))),
            ("GET", r"/artist", lambda b, q, p: (200, copy.deepcopy(self.artists))),
            ("GET", r"/artist/\d+", self._get_artist),
            ("PUT", r"/artist/\d+", self._put_artist),
            ("POST", r"/artist", self._post_artist),
            ("GET", r"/album", self._get_albums),
            ("PUT", r"/album/monitor", self._monitor),
            ("GET", r"/album/\d+", lambda b, q, p: (200, copy.deepcopy(self.albums[int(p.rsplit('/', 1)[1])]))),
            ("GET", r"/track", lambda b, q, p: (200, copy.deepcopy(self.tracks.get(int(q["albumId"]), [])))),
            ("GET", r"/trackfile", lambda b, q, p: (200, copy.deepcopy(self.track_files.get(int(q["albumId"]), [])))),
            ("GET", r"/command", self._commands),
        ]
        for verb, pattern, handler in table:
            if verb == method and re.fullmatch(pattern, path):
                return handler
        return None

    # -- handlers
    def _post_root(self, body, q, p):
        if any(f["path"] == body["path"] for f in self.root_folders):
            return 400, [{"errorMessage": f"Path '{body['path']}' is already configured as a root folder"}]
        self.root_folders.append({"id": next(self._ids), **body})
        return 201, self.root_folders[-1]

    @staticmethod
    def _leaves(profile):
        return [leaf for item in profile["items"] for leaf in (item["items"] or [item])]

    def _validate_quality(self, body):
        allowed = [leaf["quality"]["id"] for leaf in self._leaves(body) if leaf.get("allowed")]
        if not allowed:
            return 400, [{"errorMessage": "Must contain at least one allowed quality"}]
        if body["cutoff"] not in allowed:
            return 400, [{"errorMessage": "Cutoff must be an allowed quality or group"}]
        return None

    def _post_quality(self, body, q, p):
        if any(x["name"] == body["name"] for x in self.quality_profiles):
            return 409, {"message": "constraint failed UNIQUE constraint failed: QualityProfiles.Name"}
        bad = self._validate_quality(body)
        if bad:
            return bad
        self.quality_profiles.append({**copy.deepcopy(body), "id": next(self._ids)})
        return 201, copy.deepcopy(self.quality_profiles[-1])

    def _put_quality(self, body, q, p):
        bad = self._validate_quality(body)
        if bad:
            return bad
        for i, x in enumerate(self.quality_profiles):
            if x["id"] == body["id"]:
                self.quality_profiles[i] = copy.deepcopy(body)
                return 200, body
        return 404, None

    def _post_metadata(self, body, q, p):
        if any(x["name"] == body["name"] for x in self.metadata_profiles):
            return 409, {"message": "constraint failed UNIQUE constraint failed: MetadataProfiles.Name"}
        self.metadata_profiles.append({**copy.deepcopy(body), "id": next(self._ids)})
        return 201, copy.deepcopy(self.metadata_profiles[-1])

    def _put_metadata(self, body, q, p):
        for i, x in enumerate(self.metadata_profiles):
            if x["id"] == body["id"]:
                self.metadata_profiles[i] = copy.deepcopy(body)
                return 200, body
        return 404, None

    def _put_naming(self, body, q, p):
        self.naming = dict(body)
        return 200, body

    def _put_media(self, body, q, p):
        self.media = dict(body)
        return 200, body

    def _post_artist(self, body, q, p):
        if any(a["foreignArtistId"] == body["foreignArtistId"] for a in self.artists):
            return 400, [{"errorMessage": "This artist has already been added"}]
        artist = {**copy.deepcopy(body), "id": next(self._ids)}
        self.artists.append(artist)
        self.refreshing.add(artist["id"])
        return 201, copy.deepcopy(artist)

    def _get_artist(self, body, q, p):
        found = next((a for a in self.artists if a["id"] == int(p.rsplit("/", 1)[1])), None)
        return (200, copy.deepcopy(found)) if found else (404, None)

    def _put_artist(self, body, q, p):
        for i, a in enumerate(self.artists):
            if a["id"] == body["id"]:
                self.artists[i] = copy.deepcopy(body)
                return 202, body
        return 404, None

    def _get_albums(self, body, q, p):
        artist = int(q.get("artistId", 0))
        return 200, [copy.deepcopy(a) for a in self.albums.values() if a["artistId"] == artist]

    def _monitor(self, body, q, p):
        for album_id in body["albumIds"]:
            self.albums[album_id]["monitored"] = body["monitored"]
        return 202, None

    def _commands(self, body, q, p):
        out = []
        for artist_id in sorted(self.refreshing):
            if self.refresh_seen_as == "ids":
                shape = {"artistIds": [artist_id]}
            elif self.refresh_seen_as == "one":
                shape = {"artistId": artist_id}
            else:
                shape = {}
            out.append({"name": "RefreshArtist", "status": "started", "body": shape})
        out.append({"name": "RssSync", "status": "completed", "body": {}})
        return 200, out

    # -- arranging
    def finish_refresh(self, artist_id):
        self.refreshing.discard(artist_id)
        for album in self.albums.values():
            if album["artistId"] == artist_id and not album["releases"]:
                album["releases"] = [{"id": next(self._ids), "monitored": True}]

    def add_album(self, artist_id, title, tracks, **extra):
        album_id = next(self._ids)
        self.albums[album_id] = {"id": album_id, "artistId": artist_id, "title": title, "monitored": False, "releases": [],
                                 "albumType": "Album", "releaseDate": "2001-01-01T00:00:00Z", **extra}
        self.tracks[album_id] = [{"id": next(self._ids), "albumId": album_id, "title": t, "trackNumber": n + 1, "absoluteTrackNumber": n + 1,
                                  "mediumNumber": 1, "duration": d * 1000, "hasFile": False, "trackFileId": 0}
                                 for n, (t, d) in enumerate(tracks)]
        return album_id

    def import_album(self, album_id, directory):
        """Lidarr has filed the album in the pool: one track file per track."""
        files = []
        for track in self.tracks[album_id]:
            file_id = next(self._ids)
            track.update({"hasFile": True, "trackFileId": file_id})
            files.append({"id": file_id, "albumId": album_id, "path": f"{directory}/{track['trackNumber']:02d} - {track['title']}.flac",
                          "size": 30_000, "quality": {"quality": {"id": 6, "name": "FLAC"}}})
        self.track_files[album_id] = files
        self.albums[album_id]["statistics"] = {"trackFileCount": len(files), "trackCount": len(files), "percentOfTracks": 100}
        return files


# ------------------------------------------------------------------------------------------------------------- the music server

import hashlib  # noqa: E402
from pathlib import Path  # noqa: E402

AUDIO = {".opus", ".m4a", ".mp3", ".flac", ".ogg"}


def song_id_of(path: str) -> str:
    """The real server's ids follow the file's path (measured, docs/46 S1): another path, another id."""
    return hashlib.sha1(path.encode()).hexdigest()[:22]


class FakeNavidrome:
    """`Transport` for the music-server client. With [music] set, a scan reads that folder like the real server does: dot-folders are
    ignored, a song's id follows its path, a file that vanished is gone."""

    def __init__(self, music: Path | None = None):
        self.music = music
        self.passwords = {"sam": "sam-pw", "mia": "mia-pw", "owner": "owner-pw"}
        self.admins = {"owner"}
        self.admin_login = ("owner", "owner-pw")
        self.songs: dict[str, dict] = {}
        self.hidden_from: dict[str, set[str]] = {}   # song id -> people who cannot see it
        self.scans = 0
        self.scanning = False
        self.jwt = "jwt-1"
        self.calls: list[tuple[str, str]] = []
        self.down = False
        self.revoke_jwt_once = False

    # -- arranging
    def add_song(self, path: str, *, title: str, artist: str, album: str, year: int = 2016, track: int = 1, duration: float = 200.0,
                 bit_rate: int = 128, release_group: str = "") -> str:
        song_id = song_id_of(path)
        self.songs[song_id] = {"id": song_id, "path": path, "libraryPath": "/music", "title": title, "artist": artist, "albumArtist": artist,
                               "album": album, "year": year, "trackNumber": track, "duration": duration, "suffix": path.rsplit(".", 1)[-1],
                               "bitRate": bit_rate, "mbzReleaseGroupId": release_group, "missing": False}
        return song_id

    def scan(self):
        """What a real scan does to the folder: songs for new files, 'missing' for vanished ones."""
        self.scans += 1
        if self.music is None:
            return
        seen = set()
        for file in self.music.rglob("*"):
            relative = file.relative_to(self.music)
            if file.is_file() and file.suffix.lower() in AUDIO and not any(part.startswith(".") for part in relative.parts):
                rel = str(relative).replace("\\", "/")
                seen.add(rel)
                if song_id_of(rel) not in self.songs:
                    parts = rel.split("/")
                    stem = parts[-1].rsplit(".", 1)[0]
                    track, _, title = stem.partition(" - ")
                    self.add_song(rel, title=title or stem, artist=parts[0] if len(parts) > 2 else "", album=parts[1] if len(parts) > 2 else "",
                                  track=int(track) if track.isdigit() else 1, bit_rate=1000 if rel.endswith(".flac") else 128)
                self.songs[song_id_of(rel)]["missing"] = False
        for song in self.songs.values():
            if song["path"] not in seen and self.music is not None:
                song["missing"] = True

    # -- the transport
    def __call__(self, method, url, body=None, headers=None):
        self.calls.append((method, url))
        if self.down:
            return 0, None
        parts = urllib.parse.urlsplit(url)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        path = parts.path
        if path.startswith("/rest/"):
            return self._subsonic(path[len("/rest/"):-len(".view")], query)
        if path == "/auth/login":
            if body and (body.get("username"), body.get("password")) == self.admin_login:
                return 200, {"token": self.jwt}
            return 401, {"error": "Invalid username or password"}
        if path.startswith("/api/"):
            if self.revoke_jwt_once:
                self.revoke_jwt_once = False
                self.jwt = "jwt-2"
            if (headers or {}).get("X-ND-Authorization") != f"Bearer {self.jwt}":
                return 401, {"error": "unauthorized"}
            return self._native(path[len("/api/"):], query)
        return 404, None

    def _valid(self, q):
        password = self.passwords.get(q.get("u", ""))
        return password is not None and hashlib.md5((password + q.get("s", "")).encode()).hexdigest() == q.get("t")

    def _subsonic(self, method, q):
        if not self._valid(q):
            return 200, {"subsonic-response": {"status": "failed", "error": {"code": 40}}}
        ok = {"status": "ok", "version": "1.16.1"}
        if method == "ping":
            return 200, {"subsonic-response": ok}
        if method == "getUser":
            return 200, {"subsonic-response": {**ok, "user": {"username": q["u"], "adminRole": q["u"] in self.admins}}}
        if method == "getSong":
            song = self.songs.get(q.get("id", ""))
            if song is None or q["u"] in self.hidden_from.get(song["id"], set()) or song["missing"]:
                return 200, {"subsonic-response": {"status": "failed", "error": {"code": 70}}}
            return 200, {"subsonic-response": {**ok, "song": {k: song[k] for k in ("id", "title", "artist", "album", "year", "suffix")}}}
        if method == "startScan":
            if q["u"] not in self.admins:
                return 200, {"subsonic-response": {"status": "failed", "error": {"code": 50}}}
            self.scan()
            return 200, {"subsonic-response": {**ok, "scanStatus": {"scanning": self.scanning}}}
        if method == "getScanStatus":
            return 200, {"subsonic-response": {**ok, "scanStatus": {"scanning": self.scanning}}}
        return 404, None

    def _native(self, path, q):
        if path.startswith("song/"):
            song = self.songs.get(urllib.parse.unquote(path[len("song/"):]))
            return (200, dict(song)) if song else (404, None)
        if path == "song":
            wanted = q.get("path")
            return 200, [dict(s) for s in self.songs.values() if wanted is None or s["path"] == wanted][:3]
        return 404, None


class FakeSlskdFull:
    """`Http` for the slskd client: connection state, shares, downloads and searches."""

    def __init__(self):
        self.down = False
        self.logged_in = True
        self.share_files = 0
        self.downloads: list = []
        self.peers_answering = 3
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path))
        if self.down:
            return 0, None
        if path == "/application":
            return 200, {"version": {"current": "0.26.1.0"}, "server": {"isConnected": self.logged_in, "isLoggedIn": self.logged_in}}
        if path == "/server" and method == "PUT":
            self.logged_in = True
            return 200, None
        if path == "/server" and method == "DELETE":
            self.logged_in = False
            return 200, None
        if path == "/shares":
            return 200, {"local": [{"files": self.share_files}]}
        if path == "/transfers/downloads":
            return 200, self.downloads
        if path == "/searches" and method == "POST":
            return 200, {"id": "s1"}
        if path == "/searches/s1" and method == "GET":
            return 200, {"isComplete": True}
        if path == "/searches/s1/responses":
            return 200, [{}] * self.peers_answering
        if path == "/searches/s1" and method == "DELETE":
            return 200, None
        return 404, None
