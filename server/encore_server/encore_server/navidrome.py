"""What the server asks of the music server (Navidrome) on its own account, not on a person's: start a scan, find the library's id for
a song that was just kept, list the songs that are already there.

Who is asking for a *person* is `auth.NavidromeVerifier`'s job (the token the app sends). The server's own account is an administrator
the installer made; its password is in the server's environment and nowhere else.
"""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import Iterator
from typing import Any

import httpx

from .auth import subsonic_token
from .sources.youtube.stream import Upstream
from .textnorm import norm_artist, norm_title, ratio, version_signature

log = logging.getLogger("encore_server.navidrome")

#: The biggest picture passed on to a phone (a cover is a few hundred kilobytes; this stops a wrong answer from filling memory).
_MAX_COVER = 3 * 1024 * 1024


class NavidromeClient:
    def __init__(self, base_url: str, user: str, password: str, *, client: httpx.Client | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._user = user
        self._password = password
        self._client = client or httpx.Client(timeout=15.0)

    @property
    def configured(self) -> bool:
        return bool(self._user and self._password)

    def _query(self, **params: object) -> dict[str, str]:
        """A call as the server's own account: its login, never a person's."""
        salt = secrets.token_hex(6)
        return {
            "u": self._user,
            "t": subsonic_token(self._password, salt),
            "s": salt,
            "v": "1.16.1",
            "c": "encore-server",
            **{k: str(v) for k, v in params.items()},
        }

    def _call(self, method: str, **params: object) -> dict[str, Any] | None:
        """The `subsonic-response` when the music server said ok; `None` for anything else (a busy music server is not an exception)."""
        query = self._query(f="json", **params)
        try:
            response = self._client.get(f"{self._base}/rest/{method}.view", params=query)
            body = response.json().get("subsonic-response", {})
        except (httpx.HTTPError, ValueError) as error:
            log.info("the music server did not answer %s: %s", method, type(error).__name__)
            return None
        return body if isinstance(body, dict) and body.get("status") == "ok" else None

    # ------------------------------------------------------------------ what a phone is given (docs/tasks P2-20)

    def open_stream(
        self,
        song_id: str,
        range_header: str | None,
        *,
        max_bit_rate: int | None = None,
        fmt: str | None = None,
        estimate_length: bool = False,
    ) -> Upstream | None:
        """A kept song's audio, passed on as it arrives, with `Range`, as the server's own account: the phone never needs the music server's
        login. `None` when the music server does not answer or has no such song (it says so with a 200 and a text body, not an audio one)."""
        extra: dict[str, object] = {"id": song_id}
        if max_bit_rate:
            extra["maxBitRate"] = max_bit_rate
        if fmt:
            extra["format"] = fmt
        if estimate_length:
            extra["estimateContentLength"] = "true"
        request = self._client.build_request(
            "GET",
            f"{self._base}/rest/stream.view",
            params=self._query(**extra),
            headers={"Range": range_header} if range_header else {},
        )
        try:
            response = self._client.send(request, stream=True)
        except httpx.HTTPError as error:
            log.info("the music server did not answer a stream: %s", type(error).__name__)
            return None
        kind = response.headers.get("content-type", "")
        if response.status_code not in (200, 206) or not (
            kind.startswith("audio/") or kind.startswith("video/") or kind == "application/octet-stream"
        ):
            response.close()
            log.info("the music server had no song %s to stream (HTTP %s, %s)", song_id, response.status_code, kind or "no type")
            return None
        keep = ("content-type", "content-length", "content-range", "accept-ranges")
        headers = {name: value for name, value in response.headers.items() if name.lower() in keep}

        def body() -> Iterator[bytes]:
            try:
                yield from response.iter_raw(64 * 1024)
            finally:
                response.close()

        return Upstream(status=response.status_code, headers=headers, body=body(), close=response.close)

    def cover(self, cover_id: str, size: int | None = None) -> tuple[bytes, str] | None:
        """The picture the music server has under [cover_id] (and its type), or `None`."""
        extra: dict[str, object] = {"id": cover_id}
        if size:
            extra["size"] = size
        try:
            response = self._client.get(f"{self._base}/rest/getCoverArt.view", params=self._query(**extra))
        except httpx.HTTPError as error:
            log.info("the music server did not answer a cover: %s", type(error).__name__)
            return None
        kind = response.headers.get("content-type", "")
        if response.status_code != 200 or not kind.startswith("image/") or len(response.content) > _MAX_COVER:
            return None
        return response.content, kind

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


# Where the music server joins the artists of a song into one string ("Beanie Sigel, Freeway"; "Ludacris, Missy "Misdemeanor" Elliott"), and the words
# people join them with in a title or a tag.
_ARTIST_SEPARATORS = re.compile(r"\s*(?:,|;|/|&|\bfeat\.?|\bft\.?|\bfeaturing\b|\band\b|\bwith\b|\bx\b)\s*", re.IGNORECASE)


def artist_names(joined: str) -> list[str]:
    """The artist string as it is, then each name in it: "Fat Joe, Lil Wayne" is that, "Fat Joe" and "Lil Wayne". More names only ever add ways to
    match; the title (and its version) must still be the same."""
    names = [joined]
    names.extend(part for part in _ARTIST_SEPARATORS.split(joined) if part.strip() and part != joined)
    return names


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
    ("(Live)", "(Remix)" are other recordings), a close artist, and the album as a tie-break.

    **The very file that was just kept is the strongest answer (audit B-105, 7 Nov 2026):** the same title and version at exactly the same number of
    bytes. The artist is then not asked to be close: the music server lists a song with several artists as one joined string ("Beanie Sigel,
    Freeway"), which is nothing like the first artist alone, and 9 of 189 songs of an imported playlist were saved and never found for that reason."""
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
        listed_artists = [*artist_names(str(s.get("artist") or "")), *artist_names(str(s.get("albumArtist") or ""))]
        closeness = max((ratio(wanted_artist, norm_artist(name)) for name in listed_artists), default=0.0)
        same_file = size is not None and s.get("size") == size  # the same number of bytes: the very file that was just kept
        if closeness < 0.8 and not same_file:
            continue
        score = closeness + (0.2 if album and norm_title(str(s.get("album") or "")) == norm_title(album) else 0.0)
        if same_file:
            score += 1.0
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
