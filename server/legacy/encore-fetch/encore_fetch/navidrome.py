"""The little the service needs from the music server: who is asking (the
same Subsonic token the app already sends), a rescan, and "is this song in the
library yet, and under which id?"."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .textnorm import norm_artist, norm_title, ratio


@dataclass(frozen=True)
class Auth:
    """Subsonic token authentication: `t = md5(password + salt)`."""

    user: str
    token: str
    salt: str

    def params(self) -> dict[str, str]:
        return {"u": self.user, "t": self.token, "s": self.salt}


# (url) -> the `subsonic-response` object; raises on network trouble.
Http = Callable[[str], dict]


def urllib_http(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "encore-fetch/1"})
    with urllib.request.urlopen(req, timeout=12) as r:  # noqa: S310
        body = json.load(r)
    return body.get("subsonic-response", {})


class Navidrome:
    def __init__(
        self,
        base_url: str,
        *,
        http: Http = urllib_http,
        admin: Auth | None = None,
        clock: Callable[[], float] = time.monotonic,
        verify_ttl: float = 300.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._http = http
        self._admin = admin
        self._clock = clock
        self._ttl = verify_ttl
        self._verified: dict[Auth, float] = {}

    def _url(self, method: str, auth: Auth, **params: object) -> str:
        q = {**auth.params(), "v": "1.16.1", "c": "encore-fetch", "f": "json"}
        q.update({k: str(v) for k, v in params.items()})
        return f"{self._base}/rest/{method}.view?{urllib.parse.urlencode(q)}"

    def _url_many(self, method: str, auth: Auth, pairs: list[tuple[str, str]]) -> str:
        """Like [_url] for calls that repeat a parameter (`songId=a&songId=b`)."""
        q = [*auth.params().items(), ("v", "1.16.1"), ("c", "encore-fetch"), ("f", "json"), *pairs]
        return f"{self._base}/rest/{method}.view?{urllib.parse.urlencode(q)}"

    def _ok(self, url: str) -> dict | None:
        """The `subsonic-response` when the music server said ok, else `None` (a busy server is not an exception)."""
        try:
            response = self._http(url)
        except Exception:  # noqa: BLE001
            return None
        return response if response.get("status") == "ok" else None

    def verify(self, auth: Auth) -> bool:
        """`True` when the music server accepts these credentials. Answers
        are remembered briefly so polling does not hammer it."""
        now = self._clock()
        seen = self._verified.get(auth)
        if seen is not None and now - seen < self._ttl:
            return True
        try:
            ok = self._http(self._url("ping", auth)).get("status") == "ok"
        except Exception:  # noqa: BLE001
            return False
        if ok:
            self._verified[auth] = now
        return ok

    def is_admin(self, auth: Auth) -> bool:
        """Whether the music server says this person administers it."""
        response = self._ok(self._url("getUser", auth, username=auth.user))
        return bool(((response or {}).get("user") or {}).get("adminRole"))

    def start_scan(self, auth: Auth) -> bool:
        """Asks for a library scan: as the person, then (when configured) as
        an administrator. Servers that do not allow it for ordinary users
        still pick the file up on their own schedule."""
        for who in (auth, self._admin):
            if who is None:
                continue
            try:
                if self._http(self._url("startScan", who)).get("status") == "ok":
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def find_song(
        self,
        auth: Auth,
        *,
        artist: str,
        title: str,
        album: str | None = None,
        relative_path: str | None = None,
    ) -> str | None:
        """The library id of the song, or `None`."""
        try:
            response = self._http(self._url(
                "search3", auth, query=title, songCount=40,
                artistCount=0, albumCount=0))
        except Exception:  # noqa: BLE001
            return None
        songs = (response.get("searchResult3") or {}).get("song") or []
        if isinstance(songs, dict):
            songs = [songs]
        return pick_song(songs, artist=artist, title=title, album=album,
                         relative_path=relative_path)


    # -- what an import needs: playlists and stars, always as the person (their own library, their own list)

    def playlist_names(self, auth: Auth) -> list[str]:
        """The names of the person's playlists (so an import never silently merges into one that exists)."""
        response = self._ok(self._url("getPlaylists", auth))
        found = ((response or {}).get("playlists") or {}).get("playlist") or []
        if isinstance(found, dict):
            found = [found]
        return [str(p.get("name") or "") for p in found if isinstance(p, dict)]

    def create_playlist(self, auth: Auth, name: str, song_ids: list[str]) -> str | None:
        """Makes a playlist holding [song_ids]; its id, or `None` when the music server did not accept it."""
        response = self._ok(self._url_many("createPlaylist", auth, [("name", name), *(("songId", i) for i in song_ids)]))
        if response is None:
            return None
        made = response.get("playlist")
        if isinstance(made, dict) and made.get("id"):
            return str(made["id"])
        # An older reply carries no playlist: find it by name (the newest one with that name).
        for entry in reversed(((self._ok(self._url("getPlaylists", auth)) or {}).get("playlists") or {})
                              .get("playlist") or []):
            if isinstance(entry, dict) and entry.get("name") == name and entry.get("id"):
                return str(entry["id"])
        return None

    def add_to_playlist(self, auth: Auth, playlist_id: str, song_ids: list[str]) -> bool:
        return self._ok(self._url_many(
            "updatePlaylist", auth, [("playlistId", playlist_id), *(("songIdToAdd", i) for i in song_ids)])) is not None

    def star(self, auth: Auth, song_ids: list[str]) -> bool:
        """Likes the songs (what the heart in the app does)."""
        return self._ok(self._url_many("star", auth, [("id", i) for i in song_ids])) is not None


def pick_song(songs: list[dict], *, artist: str, title: str,
              album: str | None, relative_path: str | None) -> str | None:
    if relative_path:
        want = relative_path.replace("\\", "/").lower()
        for s in songs:
            path = str(s.get("path") or "").replace("\\", "/").lower()
            if path and (path == want or path.endswith("/" + want)):
                return str(s.get("id"))
    wt, wa = norm_title(title), norm_artist(artist)
    best: tuple[float, str] | None = None
    for s in songs:
        if norm_title(str(s.get("title") or "")) != wt:
            continue
        a = max(
            ratio(wa, norm_artist(str(s.get("artist") or ""))),
            ratio(wa, norm_artist(str(s.get("albumArtist") or ""))),
        )
        if a < 0.8:
            continue
        bonus = 0.0
        if album and norm_title(str(s.get("album") or "")) == norm_title(album):
            bonus = 0.2
        score = a + bonus
        if best is None or score > best[0]:
            best = (score, str(s.get("id")))
    return best[1] if best else None
