"""What the server asks of the music server (Navidrome) on its own account, not on a person's: start a scan, find the library's id for
a song that was just kept, list the songs that are already there.

Who is asking for a *person* is `auth.NavidromeVerifier`'s job (the token the app sends). The server's own account is an administrator
the installer made; its password is in the server's environment and nowhere else.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

import httpx

from .auth import subsonic_token
from .textnorm import norm_artist, norm_title, ratio, version_signature

log = logging.getLogger("encore_server.navidrome")


class NavidromeClient:
    def __init__(self, base_url: str, user: str, password: str, *, client: httpx.Client | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._user = user
        self._password = password
        self._client = client or httpx.Client(timeout=15.0)

    @property
    def configured(self) -> bool:
        return bool(self._user and self._password)

    def _call(self, method: str, **params: object) -> dict[str, Any] | None:
        """The `subsonic-response` when the music server said ok; `None` for anything else (a busy music server is not an exception)."""
        salt = secrets.token_hex(6)
        query = {
            "u": self._user,
            "t": subsonic_token(self._password, salt),
            "s": salt,
            "v": "1.16.1",
            "c": "encore-server",
            "f": "json",
            **{k: str(v) for k, v in params.items()},
        }
        try:
            response = self._client.get(f"{self._base}/rest/{method}.view", params=query)
            body = response.json().get("subsonic-response", {})
        except (httpx.HTTPError, ValueError) as error:
            log.info("the music server did not answer %s: %s", method, type(error).__name__)
            return None
        return body if isinstance(body, dict) and body.get("status") == "ok" else None

    def ping(self) -> bool:
        return self._call("ping") is not None

    def start_scan(self, *, full: bool = False) -> bool:
        return self._call("startScan", fullScan="true" if full else "false") is not None

    def scan_status(self) -> dict[str, Any] | None:
        """`{scanning, lastScan, count}` of the music server's scanner; `None` when it cannot say."""
        body = self._call("getScanStatus")
        return None if body is None else dict(body.get("scanStatus") or {})

    def scanning(self) -> bool | None:
        """Whether a scan is running now; `None` when the music server cannot say."""
        status = self.scan_status()
        return None if status is None else bool(status.get("scanning"))

    def find_song(
        self, *, artist: str, title: str, album: str | None = None, relative_path: str | None = None, size: int | None = None
    ) -> str | None:
        """The library's id for the song, or `None` (not scanned yet, or not there). [size] is the file's size in bytes: of several
        songs with the same words it picks the file that is ours (Navidrome's own `path` is built from the tags, not the real one)."""
        for query in (f"{artist} {title}", title):
            body = self._call("search3", query=query, songCount=40, artistCount=0, albumCount=0)
            if body is None:
                return None
            found = pick_song(
                _as_list((body.get("searchResult3") or {}).get("song")),
                artist=artist,
                title=title,
                album=album,
                relative_path=relative_path,
                size=size,
            )
            if found is not None:
                return found
        return None

    def get_song(self, song_id: str) -> dict[str, Any] | None:
        body = self._call("getSong", id=song_id)
        song = (body or {}).get("song")
        return song if isinstance(song, dict) else None

    def songs(self, offset: int, size: int = 500) -> list[dict[str, Any]] | None:
        """A page of every song in the library (an empty search lists them all); `None` when the music server did not answer."""
        body = self._call("search3", query='""', songOffset=offset, songCount=size, artistCount=0, albumCount=0)
        if body is None:
            return None
        return _as_list((body.get("searchResult3") or {}).get("song"))


def _as_list(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def pick_song(
    songs: list[dict[str, Any]],
    *,
    artist: str,
    title: str,
    album: str | None,
    relative_path: str | None,
    size: int | None = None,
) -> str | None:
    """The song among [songs] that is the one asked for: by its path when the path is known, else the same title, the same version
    ("(Live)", "(Remix)" are other recordings), a close artist, and the album as a tie-break."""
    if relative_path:
        want = relative_path.replace("\\", "/").lower()
        for s in songs:
            path = str(s.get("path") or "").replace("\\", "/").lower()
            if path and (path == want or path.endswith("/" + want)):
                return str(s.get("id"))
    wanted_title, wanted_artist, wanted_version = norm_title(title), norm_artist(artist), version_signature(title)
    best: tuple[float, str] | None = None
    for s in songs:
        found_title = str(s.get("title") or "")
        if norm_title(found_title) != wanted_title or version_signature(found_title) != wanted_version:
            continue
        closeness = max(
            ratio(wanted_artist, norm_artist(str(s.get("artist") or ""))),
            ratio(wanted_artist, norm_artist(str(s.get("albumArtist") or ""))),
        )
        if closeness < 0.8:
            continue
        score = closeness + (0.2 if album and norm_title(str(s.get("album") or "")) == norm_title(album) else 0.0)
        if size is not None and s.get("size") == size:
            score += 1.0  # the same number of bytes: the very file that was just kept
        if best is None or score > best[0]:
            best = (score, str(s.get("id")))
    return best[1] if best else None


#: What of the music server's description of a song the app gets with the ref (it needs these to show the song's album, artist and
#: cover, and to play and download the file, without asking the music server again).
_META_KEYS = (
    "albumId",
    "artistId",
    "coverArt",
    "suffix",
    "contentType",
    "size",
    "bitRate",
    "samplingRate",
    "bitDepth",
    "channels",
    "genre",
    "created",
    "replayGain",
    "musicBrainzId",
)


def file_meta(song: dict[str, Any]) -> dict[str, Any]:
    return {key: song[key] for key in _META_KEYS if song.get(key) not in (None, "")}
