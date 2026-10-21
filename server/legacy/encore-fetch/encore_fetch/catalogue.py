"""What a playlist does not say about a song: its album, its cover, its number, its year.

A Spotify or YouTube playlist gives a title and an artist. Without more, a fetched song became a "single named after
itself" with no cover, and the person's library filled with one-song albums shown as a letter on a coloured tile
(the owner, 2026-10-18: "importing a song would mean its icon is replaced by a letter?"). The catalogue the app
already uses for search, Deezer's public one (no key, no account), knows all four. This looks one song up and answers
only when it is sure it is the same recording: no answer is better than the wrong album.

Nothing here can fail a song: an answer is a nicety, and every error is "no answer".
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .cache import song_key
from .textnorm import mentions_version, norm_artist, norm_title, ratio

log = logging.getLogger("encore_fetch.catalogue")

API = "https://api.deezer.com"

#: Albums that are collections, not where a song belongs, when a better one exists.
_COLLECTION_WORDS = ("greatest hits", "best of", "essential", "collection", "anthology", "the very best", "hits",
                     "playlist", "radio", "now that", "top ", "mix")


@dataclass(frozen=True)
class Meta:
    album: str | None = None
    cover_url: str | None = None
    track: int | None = None
    disc: int | None = None
    year: int | None = None

    def to_json(self) -> dict:
        return {k: v for k, v in (("album", self.album), ("cover", self.cover_url), ("track", self.track),
                                  ("disc", self.disc), ("year", self.year)) if v}

    @staticmethod
    def from_json(data: dict) -> "Meta":
        return Meta(album=data.get("album"), cover_url=data.get("cover"), track=data.get("track"),
                    disc=data.get("disc"), year=data.get("year"))


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "encore-fetch/1"})
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - the host is fixed above
        return json.loads(response.read(2_000_000))


def _album_is_a_collection(title: str) -> bool:
    low = title.lower()
    return any(word in low for word in _COLLECTION_WORDS)


def pick(candidates: list[dict], artist: str, title: str, duration_s: int | None,
         *, duration_slack: int = 10) -> dict | None:
    """The catalogue entry that is certainly [artist]'s [title], or `None`.

    The title must be the same song (after dropping "(Remastered)" and "feat."), the artist the same (or a close
    spelling), no version word the person did not ask for ("live", "remix", "instrumental"), and the length within a
    few seconds when both are known. Of the ones that are left a studio album comes before a collection, then the one
    nearest in length, then the better known."""
    wanted_title, wanted_artist = norm_title(title), norm_artist(artist)
    asked_versions = mentions_version(title)
    good: list[tuple[tuple, dict]] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        name = str(_obj(c.get("artist")).get("name") or "")
        album = str(_obj(c.get("album")).get("title") or "")
        got = str(c.get("title") or "")
        if norm_title(got) != wanted_title:
            continue
        if ratio(norm_artist(name), wanted_artist) < 0.8:
            continue
        if not mentions_version(got) <= asked_versions or not mentions_version(album) <= asked_versions:
            continue  # a live or remixed recording of it
        length = c.get("duration")
        gap = abs(int(length) - duration_s) if isinstance(length, (int, float)) and duration_s else None
        if gap is not None and gap > duration_slack:
            continue
        good.append(((_album_is_a_collection(album), gap if gap is not None else 0, -int(c.get("rank") or 0)), c))
    return min(good, key=lambda g: g[0])[1] if good else None


class Deezer:
    """Looks songs up, remembering answers (and "nothing") in a small file so a song is asked about once."""

    def __init__(
        self,
        cache_path: Path | None = None,
        *,
        http: Callable[[str], dict] = _get_json,
        clock: Callable[[], float] = time.time,
        keep_s: float = 90 * 86400.0,
        keep_nothing_s: float = 2 * 86400.0,
    ) -> None:
        self._path = cache_path
        self._http = http
        self._clock = clock
        self._keep = keep_s
        self._keep_nothing = keep_nothing_s
        self._lock = threading.Lock()
        self._seen: dict[str, dict] = {}
        if cache_path is not None and cache_path.is_file():
            try:
                loaded = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._seen = loaded
            except (OSError, ValueError):
                log.warning("the catalogue cache %s is not readable; starting empty", cache_path.name)

    def lookup(self, artist: str, title: str, duration_s: int | None = None) -> Meta | None:
        key = song_key(artist, title, None)
        now = self._clock()
        with self._lock:
            entry = self._seen.get(key)
            if entry is not None:
                age = now - float(entry.get("at") or 0)
                if age < (self._keep if entry.get("meta") else self._keep_nothing):
                    return Meta.from_json(entry["meta"]) if entry.get("meta") else None
        try:
            meta = self._ask(artist, title, duration_s)
        except Exception as error:  # noqa: BLE001 - a lookup never fails a song, and a blip is not remembered
            log.info("catalogue lookup for %s - %s failed: %s", artist, title, type(error).__name__)
            return None
        with self._lock:
            self._seen[key] = {"at": now, "meta": meta.to_json() if meta else None}
            self._save()
        return meta

    def _ask(self, artist: str, title: str, duration_s: int | None) -> Meta | None:
        query = urllib.parse.urlencode({"q": f"{artist} {title}", "limit": 12})
        found = self._http(f"{API}/search/track?{query}")
        best = pick(list(found.get("data") or []), artist, title, duration_s)
        if best is None:
            return None
        album = _obj(best.get("album"))
        cover = album.get("cover_xl") or album.get("cover_big") or album.get("cover")
        track = disc = year = None
        try:
            detail = self._http(f"{API}/track/{int(best['id'])}")
            track = _positive(detail.get("track_position"))
            disc = _positive(detail.get("disk_number"))
            year = _year(detail.get("release_date"))
        except Exception:  # noqa: BLE001 - the album and cover are worth having without the number
            log.info("catalogue track detail for %s failed", best.get("id"))
        return Meta(album=str(album.get("title") or "") or None, cover_url=cover or None, track=track, disc=disc,
                    year=year)

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._seen, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.warning("the catalogue cache could not be saved")


def _obj(value: object) -> dict:
    """A catalogue field that should be an object; anything else is an empty one."""
    return value if isinstance(value, dict) else {}


def _positive(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def _year(value: object) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() and 1900 <= int(text) <= 2100 else None
