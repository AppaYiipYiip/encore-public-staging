"""Reading a pasted playlist link (docs/39 F1, F9).

A person pastes the link of a public Spotify playlist or album, or of a YouTube / YouTube Music playlist, and the app
needs the list of songs in it so that it can add them to the person's library (each one through the same "play any
song" pipeline). Nothing is downloaded here: this only reads the list.

* **Spotify** publishes a public *embed* page for every playlist and album; it carries the title, the artists and the
  length of each song (up to the first hundred). No login, no API key.
* **YouTube / YouTube Music** playlists are listed through YouTube Music's own web interface (`ytmusicapi`): the real
  title, artists, album, length and video id of every entry, about 1.5 s for 150 songs. When that cannot read a
  playlist, yt-dlp lists it without downloading (`--flat-playlist`); those lists carry video titles
  ("Artist - Song (Official Video)") and the channel, so the artist and the song are teased apart here. Either way the
  video id is kept: for YouTube's own audio upload of a song it *is* the song (nothing is searched), and otherwise,
  when a song cannot be found by name, the video the person saved is used.

The service fetches pages for people, so it only ever asks the services named here (`ALLOWED_*`): never an address
somebody typed.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("encore_server.imports.readers")

#: A playlist longer than this is cut (and says so). A person's first import can be a whole "liked" list; the import queue (imports.py) works
#: through it at the Host's pace, so the cap is only a sanity limit. It was 2000 until 7 Nov 2026, when the owner's playlist of more than 2,500
#: songs was cut at 2000 without a word on its page (the screen that says so belongs to the old preview step); 10,000 is about 100 requests to
#: YouTube Music, a little over two minutes to read.
MAX_TRACKS = 10_000

#: Spotify's public embed page lists at most this many songs of a playlist, whatever its length, and does not say how
#: long the playlist really is. A playlist that fills it may be longer: the app says so and points to the file import.
SPOTIFY_EMBED_LIMIT = 100

SPOTIFY_HOSTS = frozenset({"open.spotify.com"})
YOUTUBE_HOSTS = frozenset({"www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com"})

_SPOTIFY_PATH = re.compile(r"^/(?:intl-[a-z]{2}(?:-[a-z]{2})?/)?(?:embed/)?(playlist|album)/([A-Za-z0-9]{22})/?$")
_YOUTUBE_LIST = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class PlaylistError(Exception):
    """Safe to show to the person: `message` says what happened, `code` is for the app."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str | None = None
    duration_s: int | None = None
    #: Every artist of the song, the first one first (`artist` is the first).
    artists: tuple[str, ...] = ()
    #: The video the playlist points at (YouTube only).
    video_id: str | None = None
    #: That video is YouTube's own "Artist - Topic" upload of the song (auto-generated official audio): it *is* the
    #: song, so there is nothing to search for.
    official: bool = False


@dataclass(frozen=True)
class Playlist:
    name: str
    source: str  # "spotify" | "youtube"
    kind: str  # "playlist" | "album"
    tracks: tuple[Track, ...]
    truncated: bool = False
    #: The picture the source gives the playlist (shown at once, before any song has been looked at).
    cover_url: str | None = None


# --------------------------------------------------------------------------- the playlist's own picture

#: Where a playlist picture may come from (the phone is told the address and fetches it itself: only these hosts are ever named).
COVER_HOSTS = ("ytimg.com", "googleusercontent.com", "ggpht.com", "scdn.co", "spotifycdn.com", "dzcdn.net")


def _cover_ok(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    ok = parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in COVER_HOSTS)
    return url if ok else None


def largest_picture(pictures: object) -> str | None:
    """The address of the biggest of `[{url, width, height}, ...]` (what both sources call their pictures), if its host is allowed."""
    best: tuple[int, str] | None = None
    for item in pictures if isinstance(pictures, list) else []:
        if not isinstance(item, dict):
            continue
        url = _cover_ok(item.get("url"))
        width = item.get("width")
        size = int(width) if isinstance(width, (int, float)) and not isinstance(width, bool) else 0
        if url is not None and (best is None or size > best[0]):
            best = (size, url)
    return best[1] if best else None


# --------------------------------------------------------------------------- reading text apart

#: A bracket group that only says what kind of upload this is.
_NOISE_WORDS = (
    r"official|video|audio|lyrics?|visuali[sz]er|hd|4k|performance|clip|officiel|oficial|music|"
    r"with|explicit|topic|version|animated|mv|m/v"
)
_NOISE_GROUP = re.compile(rf"\s*[\(\[]\s*(?:(?:{_NOISE_WORDS})\b[\s,/&+-]*)+[\)\]]", re.IGNORECASE)
_PIPE_NOISE = re.compile(rf"\s*\|\s*(?:(?:{_NOISE_WORDS})\b[\s,/&+-]*)+$", re.IGNORECASE)
_FEAT_GROUP = re.compile(r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s[^\)\]]*[\)\]]", re.IGNORECASE)
_FEAT_TAIL = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s.*$", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
_TOPIC = re.compile(r"\s*-\s*Topic$", re.IGNORECASE)
_VEVO = re.compile(r"\s*VEVO$", re.IGNORECASE)
_FIRST_ARTIST = re.compile(r"\s*(?:,|&|\bx\b|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b|\band\b)\s*", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def clean_title(raw: str) -> str:
    """`The Type (Official Music Video) ft. Somebody` -> `The Type`. A bracket that is part of the song
    (`(Live at Wembley)`, `(2008 Remaster)`) stays: it is a different recording."""
    text = _NOISE_GROUP.sub("", raw)
    text = _PIPE_NOISE.sub("", text)
    text = _FEAT_GROUP.sub("", text)
    text = _FEAT_TAIL.sub("", text)
    return _SPACES.sub(" ", text).strip()


def _fold(text: str) -> str:
    import unicodedata

    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return _NON_ALNUM.sub("", folded)


def _first_artist(text: str) -> str:
    return _FIRST_ARTIST.split(text.strip(), maxsplit=1)[0].strip()


def _is_channel(channel: str, side: str) -> bool:
    a, b = _fold(channel), _fold(side)
    return bool(a) and bool(b) and (a in b or b in a)


def split_artist_title(raw_title: str, channel: str) -> tuple[str, str]:
    """The artist and the song of a video: `("Arcangel", "FN8")` from `Arcangel - FN8 ( Video Lyric )`.

    The channel decides which side of a dash is the artist (`Song - Artist` is as common as `Artist - Song`); a
    "- Topic" channel *is* the artist and its titles are already clean; with no dash the channel is the artist."""
    channel = (channel or "").strip()
    if _TOPIC.search(channel):
        return _TOPIC.sub("", channel).strip(), clean_title(raw_title)
    name = _VEVO.sub("", channel).strip()
    if " - " in raw_title:
        left, right = raw_title.split(" - ", 1)
        if _is_channel(name, left) or not _is_channel(name, right):
            return clean_title(left), clean_title(right)
        return _first_artist(clean_title(right)), clean_title(left)
    return name, clean_title(raw_title)


# --------------------------------------------------------------------------- Spotify

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def _find(obj: object, key: str, depth: int = 0) -> object | None:
    if depth > 14:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj
        for value in obj.values():
            found = _find(value, key, depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find(value, key, depth + 1)
            if found is not None:
                return found
    return None


def spotify_tracks(html: str) -> tuple[str, list[Track]]:
    """The name and the songs of a Spotify embed page."""
    name, tracks, _ = spotify_page(html)
    return name, tracks


def spotify_page(html: str) -> tuple[str, list[Track], str | None]:
    """The name, the songs and the picture of a Spotify embed page."""
    match = _NEXT_DATA.search(html or "")
    if not match:
        raise PlaylistError("unreadable", "Could not read that playlist. Is it public?")
    try:
        entity = _find(json.loads(match.group(1)), "trackList")
    except ValueError:
        entity = None
    if not isinstance(entity, dict) or not isinstance(entity.get("trackList"), list):
        raise PlaylistError("unreadable", "Could not read that playlist. Is it public?")
    name = str(entity.get("name") or entity.get("title") or "").strip() or "Imported playlist"
    tracks: list[Track] = []
    for item in entity["trackList"]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        artists = tuple(a.strip() for a in re.split(r",\s*|,\xa0", str(item.get("subtitle") or "")) if a.strip())
        millis = item.get("duration")
        tracks.append(
            Track(
                title=title,
                artist=artists[0] if artists else "",
                duration_s=int(millis // 1000) if isinstance(millis, (int, float)) and millis > 0 else None,
                artists=artists,
            )
        )
    art = entity.get("coverArt") or entity.get("visualIdentity")
    sources = art.get("sources") or art.get("image") if isinstance(art, dict) else None
    return name, tracks, largest_picture(sources)


# --------------------------------------------------------------------------- the readers


def _http_get(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - the host was checked
        return str(response.read(4_000_000).decode("utf-8", "replace"))


def _youtube_tracks(data: dict[str, Any]) -> tuple[str, list[Track]]:
    name = str(data.get("title") or "").strip() or "Imported playlist"
    tracks: list[Track] = []
    for entry in data.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("title") or "").strip()
        if not raw or raw in ("[Private video]", "[Deleted video]"):
            continue
        channel = str(entry.get("channel") or entry.get("uploader") or "")
        artist, title = split_artist_title(raw, channel)
        if not title:
            continue
        video_id = str(entry.get("id") or "")
        official = bool(_TOPIC.search(channel.strip()))
        duration = entry.get("duration")
        tracks.append(
            Track(
                title=title,
                artist=artist,
                duration_s=int(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
                artists=(artist,) if artist else (),
                video_id=video_id if _VIDEO_ID.match(video_id) else None,
                official=official and bool(_VIDEO_ID.match(video_id)),
            )
        )
    return name, tracks


#: YouTube Music's kinds of entry that *are* the song: YouTube's own audio upload of it (a "Topic" release, or the label's).
_SONG_TYPES = frozenset({"MUSIC_VIDEO_TYPE_ATV", "MUSIC_VIDEO_TYPE_OFFICIAL_SOURCE_MUSIC"})


def _ytmusic_tracks(data: dict[str, Any]) -> tuple[str, list[Track]]:
    """The name and the songs of what `ytmusicapi.get_playlist` answers (checked against the real answer: tests/fixtures/ytm)."""
    name = str(data.get("title") or "").strip() or "Imported playlist"
    tracks: list[Track] = []
    for entry in data.get("tracks") or []:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("title") or "").strip()
        if not raw:
            continue
        names = [
            _VEVO.sub("", _TOPIC.sub("", str(a.get("name") or ""))).strip()
            for a in entry.get("artists") or []
            if isinstance(a, dict)
        ]
        names = [n for n in names if n]
        title = clean_title(raw)
        if not title:
            continue
        # An entry YouTube no longer has keeps its name, artist and album (so it is searched by name) but has no video.
        video_id = entry.get("videoId") if entry.get("isAvailable") is not False else None
        video_id = video_id if isinstance(video_id, str) and _VIDEO_ID.match(video_id) else None
        album = entry.get("album")
        album_name = str(album.get("name") or "").strip() if isinstance(album, dict) else ""
        seconds = entry.get("duration_seconds")
        tracks.append(
            Track(
                title=title,
                artist=names[0] if names else "",
                album=album_name or None,
                duration_s=int(seconds)
                if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0
                else None,
                artists=tuple(names),
                video_id=video_id,
                official=video_id is not None and entry.get("videoType") in _SONG_TYPES,
            )
        )
    return name, tracks


def read_playlist(
    url: str,
    *,
    http: Callable[[str], str] = _http_get,
    ytdlp: Callable[[str], dict[str, Any]] | None = None,
    ytmusic: Callable[[str], dict[str, Any]] | None = None,
) -> Playlist:
    """The songs of the playlist or album at [url]; raises [PlaylistError] with a sentence for the person."""
    try:
        link = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        link = urllib.parse.urlsplit("")
    host = (link.hostname or "").lower()
    unsupported = PlaylistError(
        "unsupported", "That is not a link to a Spotify or YouTube playlist. Open the playlist, share it, and paste the link."
    )
    if link.scheme != "https" or not host:
        raise unsupported

    if host in SPOTIFY_HOSTS:
        found = _SPOTIFY_PATH.match(link.path)
        if not found:
            raise unsupported
        kind, ident = found.group(1), found.group(2)
        try:
            html = http(f"https://open.spotify.com/embed/{kind}/{ident}")
        except Exception as error:  # noqa: BLE001 - any network trouble reads the same to the person
            raise PlaylistError("unreachable", "Spotify did not answer. Try again in a minute.") from error
        name, tracks, cover = spotify_page(html)
        return _playlist(name, "spotify", kind, tracks, cut=len(tracks) >= SPOTIFY_EMBED_LIMIT, cover=cover)

    if host in YOUTUBE_HOSTS:
        query = urllib.parse.parse_qs(link.query)
        ident = (query.get("list") or [""])[0]
        if link.path not in ("/playlist", "/watch") or not _YOUTUBE_LIST.match(ident):
            raise unsupported
        if ytmusic is not None:
            cover = None
            try:
                answer = ytmusic(ident)
                name, tracks = _ytmusic_tracks(answer)
                cover = largest_picture(answer.get("thumbnails"))
            except Exception as error:  # noqa: BLE001 - the quick way in; yt-dlp is asked next and says why when it cannot
                log.info("YouTube Music could not list playlist %s (%s); asking yt-dlp", ident, error)
                tracks = []
            if tracks:
                return _playlist(name, "youtube", "playlist", tracks, cover=cover)
        if ytdlp is None:
            raise PlaylistError("unreachable", "This server cannot read YouTube playlists.")
        try:
            data = ytdlp(f"https://www.youtube.com/playlist?list={ident}")
        except Exception as error:  # noqa: BLE001
            text = str(error).lower()
            if any(w in text for w in ("does not exist", "private", "unavailable", "not available", "no such")):
                raise PlaylistError(
                    "not_found", "That playlist is private or does not exist. It must be public (or unlisted) to be read."
                ) from error
            raise PlaylistError("unreachable", "YouTube did not answer. Try again in a minute.") from error
        name, tracks = _youtube_tracks(data if isinstance(data, dict) else {})
        return _playlist(name, "youtube", "playlist", tracks)

    raise unsupported


def _playlist(name: str, source: str, kind: str, tracks: list[Track], *, cut: bool = False, cover: str | None = None) -> Playlist:
    if not tracks:
        raise PlaylistError("empty", "That playlist has no songs we can read. Is it empty, or private?")
    return Playlist(name, source, kind, tuple(tracks[:MAX_TRACKS]), truncated=cut or len(tracks) > MAX_TRACKS, cover_url=cover)


def ytdlp_reader(
    python: str | None = None, *, timeout: int = 180, run: Callable[..., Any] | None = None
) -> Callable[[str], dict[str, Any]]:
    """A function that lists a playlist with yt-dlp (no download), run as `python -m yt_dlp` so that it is the same copy the rest of the server uses:
    the one the server switched to (docs/11 ADR-R39) is first on `PYTHONPATH`, which the child inherits. A `yt-dlp` command would ignore it."""
    import subprocess
    import sys

    def read(url: str) -> dict[str, Any]:
        argv = [
            python or sys.executable,
            "-m",
            "yt_dlp",
            "--flat-playlist",
            "-J",
            "--no-warnings",
            "--playlist-end",
            str(MAX_TRACKS + 1),
            url,
        ]
        runner = run or subprocess.run
        done = runner(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        if done.returncode != 0:
            raise RuntimeError((done.stderr or "yt-dlp failed").strip()[-300:])
        data = json.loads(done.stdout or "{}")
        return data if isinstance(data, dict) else {}

    return read


def ytmusic_reader(*, factory: Callable[[], Any] | None = None) -> Callable[[str], dict[str, Any]]:
    """A function that lists a playlist through YouTube Music's web interface (no download, no login): the real title,
    artists, album, length and video id of every entry, about 1.5 s for 150 songs."""
    local = threading.local()

    def read(ident: str) -> dict[str, Any]:
        client: Any = getattr(local, "client", None)
        if client is None:
            if factory is not None:
                client = factory()
            else:
                from ytmusicapi import YTMusic  # imported here: the server runs without it (yt-dlp reads playlists then)

                client = YTMusic()
            local.client = client
        answer = client.get_playlist(ident, limit=MAX_TRACKS + 1)
        return answer if isinstance(answer, dict) else {}

    return read
