"""The fast way to find and locate a song (docs/tasks P1-01).

The old resolver started up to eight `yt-dlp` programs for one song: a plain search, a YouTube Music search page, then up to five full
page extractions only to read each candidate's title and length (measured on 2026-10-21: 33 to 35 seconds before a download even began).
This module does the same job with what is cheap:

* **Search**: YouTube Music's own search answers (title, artists, album, length, video id) in one JSON call of about a second
  (`ytmusicapi`). Both word orders are asked at once, because YouTube Music answers "artist title" and "title artist" differently
  (recorded in `tests/fixtures/ytm`: "Maria Tambien Khruangbin" finds the studio song, "Khruangbin Maria Tambien" does not).
* **Choosing** keeps the project's own tested scoring (`resolve.best`) and adds one rule: a *song* result whose artists do not include the
  one asked for is never taken, however well the title matches ("Taragalte" by another artist is not Oum's "Taragalte").
* **Locating** the stream runs `yt_dlp` inside this process, one extractor per thread, so the player code and the JavaScript solver are
  loaded once, not for every song.

Everything outside the network is pure and unit-tested with recorded answers. A failure of the fast path falls back to the old resolver.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Callable, Protocol

from .download import FORMAT, DownloadError, classify_failure
from .resolve import ACCEPT, Candidate, Resolver, Scored, Want, score
from .textnorm import norm_artist, norm_title, ratio, version_signature

log = logging.getLogger("encore_fetch.lean")

#: A structured (song) answer this good is taken without asking for videos too: a right title, artist, album or length, the artist's
#: own or Topic channel (the scoring tops out at 14).
STRONG_SONG = 10.0


# ----------------------------------------------------------------- mapping YouTube Music answers to candidates


def _artist_names(raw: dict[str, Any]) -> tuple[str, ...]:
    names = []
    for a in raw.get("artists") or []:
        name = a.get("name") if isinstance(a, dict) else None
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return tuple(names)


def _seconds(raw: dict[str, Any]) -> int | None:
    value = raw.get("duration_seconds")
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    text = raw.get("duration")
    if isinstance(text, str) and text.count(":") in (1, 2):
        try:
            parts = [int(p) for p in text.split(":")]
        except ValueError:
            return None
        total = 0
        for p in parts:
            total = total * 60 + p
        return total or None
    return None


def candidate_from_song(raw: dict[str, Any]) -> Candidate | None:
    """A "song" result: an official audio-backed track, with its declared title, artists and album."""
    video_id, title = raw.get("videoId"), raw.get("title")
    if not isinstance(video_id, str) or not isinstance(title, str):
        return None
    artists = _artist_names(raw)
    album = raw.get("album")
    year = raw.get("year")
    return Candidate(
        video_id=video_id,
        title=title,
        channel=(artists[0] + " - Topic") if artists else "",
        duration_s=_seconds(raw),
        is_topic=True,
        track=title,
        artists=artists,
        album=album.get("name") if isinstance(album, dict) and album.get("name") else None,
        year=int(year) if isinstance(year, str) and year.isdigit() else None,
    )


def candidate_from_video(raw: dict[str, Any]) -> Candidate | None:
    """A "video" result: only the upload's title, its channel and its length are known."""
    video_id, title = raw.get("videoId"), raw.get("title")
    if not isinstance(video_id, str) or not isinstance(title, str):
        return None
    artists = _artist_names(raw)
    channel = artists[0] if artists else ""
    return Candidate(
        video_id=video_id,
        title=title,
        channel=channel,
        duration_s=_seconds(raw),
        is_topic=channel.endswith(" - Topic"),
    )


# ----------------------------------------------------------------- searching


class Searcher(Protocol):
    """Something that answers YouTube Music searches (the real one, or recorded answers in tests)."""

    def songs(self, query: str, limit: int) -> list[dict[str, Any]]: ...

    def videos(self, query: str, limit: int) -> list[dict[str, Any]]: ...


class YtmusicApiSearcher:
    """The real searcher: `ytmusicapi`, one client per thread (its HTTP session is not meant to be shared between threads)."""

    def __init__(self) -> None:
        self._local = threading.local()

    def _client(self):
        client = getattr(self._local, "client", None)
        if client is None:
            from ytmusicapi import YTMusic  # imported late: tests and the fake mode never need it

            client = self._local.client = YTMusic()
        return client

    def songs(self, query: str, limit: int) -> list[dict[str, Any]]:
        return self._client().search(query, filter="songs", limit=limit)

    def videos(self, query: str, limit: int) -> list[dict[str, Any]]:
        return self._client().search(query, filter="videos", limit=limit)


def queries_for(want: Want) -> list[str]:
    """The words to search for, in both orders (one query when they are the same)."""
    artist, title = want.artist.strip(), want.title.strip()
    first, second = f"{artist} {title}".strip(), f"{title} {artist}".strip()
    return [first] if first == second else [first, second]


#: How alike two titles must be for a song result to be "the same song" (the scoring alone let a 0.21 title through on the artist's name).
MIN_TITLE_SIMILARITY = 0.6

#: How alike two artist names must be to be the same artist ("Oum" is not "Oum Dermam Stars").
MIN_ARTIST_SIMILARITY = 0.9

_ARTIST_SPLIT = re.compile(r"\s*(?:,|&|\+|\bfeat\.?\s|\bft\.?\s|\bfeaturing\b|\bx\b|\bwith\b)\s*", re.IGNORECASE)


def artist_matches(asked: str, names: tuple[str, ...]) -> bool:
    """Whether the artist asked for is one of the artists the upload declares. Whole names only: "Oum" is not "Oum Dermam Stars"."""
    # The whole name first (an artist can be called "Earth, Wind & Fire"), then the names a combined string is made of.
    wanted = [norm_artist(asked)] + [norm_artist(part) for part in _ARTIST_SPLIT.split(asked) if part.strip()]
    declared = [norm_artist(n) for n in names]
    return any(w and d and ratio(w, d) >= MIN_ARTIST_SIMILARITY for w in wanted for d in declared)


def title_matches(want: Want, c: Candidate) -> bool:
    got = c.track or c.title
    if ratio(norm_title(want.title), norm_title(got)) < MIN_TITLE_SIMILARITY:
        return False
    # A rework, a live take or a remix that was asked for must be the one that is offered ("Fade Into You (The Avener Rework)" is
    # not "Fade Into You"); a plain song asked for is not held to what the upload adds (that is the scoring's business).
    wanted = version_signature(want.title)
    return not wanted or bool(wanted & version_signature(got))


def rank(want: Want, candidates: list[Candidate], max_duration_s: int = 2700) -> list[Scored]:
    """Every acceptable candidate, best first. A song result is only considered when it is by the artist asked for and has a similar
    title: a wrong song is worse than "not found"."""
    kept = [c for c in candidates if not c.structured or (artist_matches(want.artist, c.artists) and title_matches(want, c))]
    scored = sorted((score(want, c, max_duration_s) for c in kept), key=lambda s: s.score, reverse=True)
    return [s for s in scored if s.score >= ACCEPT]


def choose(want: Want, candidates: list[Candidate], max_duration_s: int = 2700) -> Scored | None:
    """The best acceptable candidate (see [rank])."""
    ranked = rank(want, candidates, max_duration_s)
    return ranked[0] if ranked else None


class LeanResolver:
    """Finds the video id of a song with YouTube Music's own search (see the module text)."""

    def __init__(self, searcher: Searcher, *, fallback: Resolver | None = None, max_duration_s: int = 2700,
                 timeout_s: float = 12.0, workers: int = 4, limit: int = 8) -> None:
        self._searcher = searcher
        self._fallback = fallback
        self._max = max_duration_s
        self._timeout = timeout_s
        self._limit = limit
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="lean-search")

    # -- the question
    def resolve(self, want: Want) -> Scored | None:
        ranked = self.resolve_ranked(want)
        return ranked[0] if ranked else None

    def resolve_ranked(self, want: Want) -> list[Scored]:
        """Every acceptable upload, best first: the caller can try the next one when the best cannot be fetched (age gate, taken down)."""
        try:
            return self._resolve(want)
        except (DownloadError, FutureTimeout, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            # The fast path failed (the service is down, its answer changed shape, a timeout): the slow way still works.
            log.warning("lean search failed (%s); %s", error.__class__.__name__,
                        "using the yt-dlp search" if self._fallback else "no fallback")
            if self._fallback is not None:
                found = self._fallback.resolve(want)
                return [found] if found is not None else []
            raise DownloadError("unavailable", "the song search is not answering") from error

    def _resolve(self, want: Want) -> list[Scored]:
        queries = queries_for(want)
        futures: list[Future] = [self._pool.submit(self._searcher.songs, q, self._limit) for q in queries]
        candidates: dict[str, Candidate] = {}
        for future in futures:
            for raw in future.result(timeout=self._timeout):
                c = candidate_from_song(raw)
                if c is not None:
                    candidates.setdefault(c.video_id, c)
        ranked = rank(want, list(candidates.values()), self._max)
        if ranked and ranked[0].score >= STRONG_SONG:
            return ranked
        # Not clear-cut: long content (a recitation, a mix) and uploads that are not "songs" only appear as videos.
        video_future = self._pool.submit(self._searcher.videos, queries[-1], self._limit)
        for raw in video_future.result(timeout=self._timeout):
            c = candidate_from_video(raw)
            if c is not None:
                candidates.setdefault(c.video_id, c)
        return rank(want, list(candidates.values()), self._max)


# ----------------------------------------------------------------- locating the stream in this process


#: What yt-dlp says when the video itself is gone (not when one client cannot play it).
_GONE_VIDEO = re.compile(r"video unavailable|private video|has been removed|account associated with this video has been terminated|"
                         r"copyright|this video is not available", re.IGNORECASE)


class InProcessExtractor:
    """`yt_dlp` as a library: one extractor per thread, kept between songs (player code, solver and cookies stay loaded).

    Writes the same JSON that `yt-dlp -j` prints, so the downloader can carry on with `--load-info-json` as before.

    A visitor (no YouTube account) is first tried with the [fast_clients] (`visionos`): measured on the real server on 2026-10-22 it
    extracts in 1.3 s against 3.7 s for yt-dlp's own choice, and its stream address opens at once (the TV client's answers 403 for two
    to four seconds). When that fails for a reason that is not "YouTube blocks this server", yt-dlp's own choice is tried, so a
    video the fast client cannot play still plays. A fast client that fails [breaker_after] times in a row (YouTube changed it) is left
    out for [breaker_s] seconds. An account's cookies always use yt-dlp's own choice (some clients ignore cookies).
    """

    def __init__(self, *, socket_timeout: int = 20, cache_dir: Path | None = None, fast_clients: tuple[str, ...] = ("visionos",),
                 breaker_after: int = 3, breaker_s: float = 3600.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._timeout = socket_timeout
        self._cache = cache_dir
        self._fast = tuple(fast_clients)
        self._breaker_after = breaker_after
        self._breaker_s = breaker_s
        self._clock = clock
        self._failures = 0
        self._resting_until = 0.0
        self._local = threading.local()

    def _extractor(self, cookiefile: str | None, clients: tuple[str, ...] = ()):
        """This thread's extractor for [cookiefile] and [clients] (none = a visitor, yt-dlp's own choice). Kept between songs, so the
        player code is loaded once."""
        by_kind = getattr(self._local, "by_kind", None)
        if by_kind is None:
            by_kind = self._local.by_kind = {}
        key = (cookiefile, clients)
        ydl = by_kind.get(key)
        if ydl is None:
            import yt_dlp  # imported late: the fake mode and most tests never need it

            options: dict[str, Any] = {
                "quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
                "format": FORMAT, "socket_timeout": self._timeout,
            }
            if self._cache is not None:
                options["cachedir"] = str(self._cache)
            if cookiefile:
                options["cookiefile"] = cookiefile
            if clients:
                options["extractor_args"] = {"youtube": {"player_client": list(clients)}}
            ydl = by_kind[key] = yt_dlp.YoutubeDL(options)
        return ydl

    def _fast_allowed(self, cookiefile: str | None) -> bool:
        return bool(self._fast) and not cookiefile and self._clock() >= self._resting_until

    def extract(self, video_id: str, info: Path, cookiefile: str | None = None) -> None:
        import yt_dlp

        url = f"https://music.youtube.com/watch?v={video_id}"
        data = None
        used = None
        if self._fast_allowed(cookiefile):
            try:
                used = self._extractor(None, self._fast)
                data = used.extract_info(url, download=False)
                self._failures = 0
            except yt_dlp.utils.DownloadError as error:
                text = str(error)
                code = classify_failure(text)
                if code == "blocked" or _GONE_VIDEO.search(text):
                    # About the server or the video, not the client: a second look-up would only repeat it. ("Requested format is not
                    # available" is about the client, and gets the second look-up.)
                    raise DownloadError(code, text[-300:]) from error
                self._failures += 1
                if self._failures >= self._breaker_after:
                    self._resting_until = self._clock() + self._breaker_s
                    log.warning("the fast YouTube client failed %d times in a row; resting it for %d s", self._failures,
                                int(self._breaker_s))
        if data is None:
            try:
                used = self._extractor(cookiefile)
                data = used.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as error:
                text = str(error)
                raise DownloadError(classify_failure(text), text[-300:]) from error
        info.parent.mkdir(parents=True, exist_ok=True)
        info.write_text(json.dumps(used.sanitize_info(data)), encoding="utf-8")


__all__ = [
    "ACCEPT", "InProcessExtractor", "LeanResolver", "Searcher", "YtmusicApiSearcher", "candidate_from_song",
    "artist_matches", "candidate_from_video", "choose", "queries_for", "rank", "title_matches",
]
