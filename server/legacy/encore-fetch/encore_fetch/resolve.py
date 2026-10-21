"""Choosing which YouTube upload is "the song".

Two sources, best first:

1. **YouTube Music search**, then the structured metadata of the top few hits
   (`track`, `artist`, `album`, `duration`: what an official upload declares).
   This tells the album version from the radio edit and from a live take.
2. **Plain YouTube search** (title, channel, duration only) when the first
   finds nothing acceptable.

Scoring is pure and unit-tested; the only I/O is the yt-dlp command line.
"""
from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Protocol

from .cookies import as_source
from .textnorm import mentions_version, norm_artist, norm_title, ratio


@dataclass(frozen=True)
class Want:
    """What the person asked for (from the catalogue)."""

    artist: str
    title: str
    album: str | None = None
    duration_s: int | None = None


@dataclass(frozen=True)
class Candidate:
    """One upload. Plain search fills the first five fields; metadata adds
    the structured ones."""

    video_id: str
    title: str
    channel: str
    duration_s: int | None
    is_topic: bool = False
    track: str | None = None
    artists: tuple[str, ...] = ()
    album: str | None = None
    year: int | None = None

    @property
    def structured(self) -> bool:
        return self.track is not None


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    score: float
    reasons: tuple[str, ...]


# A candidate must reach this to be used; below it the answer is "not found"
# rather than a wrong song.
ACCEPT = 4.0

# A plain-search hit this good (right title, the artist's own or Topic
# channel, the right length to the second) is taken at once: the slower
# YouTube Music metadata lookup is only for when it is not clear.
STRONG = 11.5


def _duration_points(want: Want, c: Candidate, max_duration_s: int,
                     reasons: list[str]) -> float:
    pts = 0.0
    if want.duration_s and c.duration_s:
        diff = abs(want.duration_s - c.duration_s)
        if diff <= 2:
            pts += 3.0
            reasons.append("duration<=2s")
        elif diff <= 6:
            pts += 1.5
            reasons.append("duration<=6s")
        elif diff > 15:
            pts -= 6.0
            reasons.append(f"duration off by {diff}s")
        else:
            pts -= 1.0
    # An upload longer than any song is a loop or a full album. When the length of the song is known the comparison
    # above already says so (off by more than 15 s), and a 25-minute song must not be refused for being long.
    if c.duration_s and c.duration_s > max_duration_s and not want.duration_s:
        pts -= 10.0
        reasons.append("too long")
    return pts


def score_plain(want: Want, c: Candidate, max_duration_s: int = 2700) -> Scored:
    """Title / channel / duration only (the fallback source)."""
    reasons: list[str] = []
    s = 0.0
    wt, ct = norm_title(want.title), norm_title(c.title)
    wa, ca = norm_artist(want.artist), norm_artist(c.channel)

    title_sim = max(ratio(wt, ct), ratio(wt, ct.replace(wa, "").strip()))
    if wt and wt in ct:
        title_sim = max(title_sim, 0.9)
    s += 5.0 * title_sim
    reasons.append(f"title={title_sim:.2f}")

    artist_sim = ratio(wa, ca)
    if c.is_topic or ca.endswith("topic"):
        s += 2.5
        reasons.append("topic")
    elif artist_sim >= 0.9:
        s += 2.5  # the artist's own channel
        reasons.append("artist channel")
    if artist_sim >= 0.8 or (wa and wa in ct) or (wa and wa in ca):
        s += 2.0
        reasons.append("artist")

    s += _duration_points(want, c, max_duration_s, reasons)
    asked = mentions_version(f"{want.title} {want.album or ''}")
    extra = mentions_version(c.title) - asked
    if extra:
        s -= 4.0
        reasons.append("version: " + ",".join(sorted(extra)))
    return Scored(c, round(s, 2), tuple(reasons))


def score_structured(want: Want, c: Candidate,
                     max_duration_s: int = 2700) -> Scored:
    """With the upload's declared track / artists / album."""
    reasons: list[str] = []
    s = 0.0
    wt = norm_title(want.title)
    ct = norm_title(c.track or c.title)
    title_sim = ratio(wt, ct)
    s += 5.0 * title_sim
    reasons.append(f"track={title_sim:.2f}")

    wa = norm_artist(want.artist)
    artists = [norm_artist(a) for a in c.artists if a] or [norm_artist(c.channel)]
    if any(ratio(wa, a) >= 0.85 or (wa and wa in a) for a in artists):
        s += 3.0
        reasons.append("artist")
    if want.album and c.album:
        album_sim = ratio(norm_title(want.album), norm_title(c.album))
        if album_sim >= 0.8:
            s += 2.0
            reasons.append("album")
    if c.is_topic or norm_artist(c.channel) == wa:
        s += 1.0
        reasons.append("official channel")

    s += _duration_points(want, c, max_duration_s, reasons)
    asked = mentions_version(f"{want.title} {want.album or ''}")
    shown = mentions_version(f"{c.title} {c.track or ''} {c.album or ''}")
    extra = shown - asked
    if extra:
        s -= 4.0
        reasons.append("version: " + ",".join(sorted(extra)))
    return Scored(c, round(s, 2), tuple(reasons))


def score(want: Want, c: Candidate, max_duration_s: int = 2700) -> Scored:
    return (score_structured if c.structured else score_plain)(
        want, c, max_duration_s)


def best(want: Want, candidates: list[Candidate],
         max_duration_s: int = 2700) -> Scored | None:
    scored = sorted(
        (score(want, c, max_duration_s) for c in candidates),
        key=lambda x: x.score,
        reverse=True,
    )
    if not scored or scored[0].score < ACCEPT:
        return None
    return scored[0]


# ----------------------------------------------------------------- yt-dlp


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str], int], RunResult]


def run_command(argv: list[str], timeout: int) -> RunResult:
    try:
        # yt-dlp writes UTF-8; do not depend on the machine's locale (the
        # Windows default would garble or reject non-Latin titles).
        p = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False
        )
        return RunResult(p.returncode, p.stdout, p.stderr)
    except subprocess.TimeoutExpired:
        return RunResult(124, "", "timeout")
    except FileNotFoundError:
        return RunResult(127, "", "not installed")


class Searcher(Protocol):
    def search(self, query: str, limit: int) -> list[Candidate]: ...


class Resolver(Protocol):
    def resolve(self, want: Want) -> Scored | None: ...


def _json(result: RunResult) -> object | None:
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def parse_search(data: object) -> list[Candidate]:
    """Flat search entries -> plain candidates."""
    out: list[Candidate] = []
    entries = data.get("entries") if isinstance(data, dict) else None
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        vid, title = e.get("id"), e.get("title")
        if not isinstance(vid, str) or not isinstance(title, str):
            continue
        channel = e.get("channel") or e.get("uploader") or ""
        dur = e.get("duration")
        out.append(Candidate(
            video_id=vid, title=title, channel=str(channel),
            duration_s=int(dur) if isinstance(dur, (int, float)) else None,
            is_topic=str(channel).endswith(" - Topic"),
        ))
    return out


def parse_music_hits(data: object, limit: int = 5) -> list[str]:
    """Video ids of the song hits of a YouTube Music search page."""
    ids: list[str] = []
    entries = data.get("entries") if isinstance(data, dict) else None
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        vid = e.get("id")
        url = str(e.get("url") or "")
        if (isinstance(vid, str) and e.get("ie_key") == "Youtube"
                and "watch?v=" in url and vid not in ids):
            ids.append(vid)
        if len(ids) >= limit:
            break
    return ids


def parse_metadata(data: object) -> Candidate | None:
    """`yt-dlp -j` of one watch page -> a structured candidate."""
    if not isinstance(data, dict):
        return None
    vid = data.get("id")
    if not isinstance(vid, str):
        return None
    title = str(data.get("title") or "")
    track = data.get("track")
    artist = data.get("artist") or ""
    artists = tuple(a.strip() for a in str(artist).split(",") if a.strip())
    channel = str(data.get("channel") or data.get("uploader") or "")
    dur = data.get("duration")
    year = data.get("release_year")
    return Candidate(
        video_id=vid,
        title=title,
        channel=channel,
        duration_s=int(dur) if isinstance(dur, (int, float)) else None,
        is_topic=channel.endswith(" - Topic"),
        track=str(track) if track else (title or None),
        artists=artists,
        album=str(data["album"]) if data.get("album") else None,
        year=int(year) if isinstance(year, (int, float)) else None,
    )


class YtDlpResolver:
    """YouTube Music first, plain YouTube search as the fallback."""

    def __init__(self, binary: str = "yt-dlp", *, cookies: object = None,
                 runner: Runner = run_command, timeout: int = 45,
                 max_duration_s: int = 2700, parallel: int = 3) -> None:
        self._binary = binary
        self._cookies = as_source(cookies)
        self._run = runner
        self._timeout = timeout
        self._max = max_duration_s
        self._parallel = parallel

    def _argv(self, *parts: str) -> list[str]:
        argv = [self._binary, "--no-warnings", "--no-playlist"]
        argv += self._cookies.lease(count=False).args
        return argv + list(parts)

    # -- sources
    def music_candidates(self, query: str) -> list[Candidate]:
        from urllib.parse import quote

        page = _json(self._run(self._argv(
            "--flat-playlist", "-J", "--",
            f"https://music.youtube.com/search?q={quote(query)}"),
            self._timeout))
        ids = parse_music_hits(page)
        if not ids:
            return []

        def one(vid: str) -> Candidate | None:
            data = _json(self._run(self._argv(
                "-j", "--skip-download", "--",
                f"https://music.youtube.com/watch?v={vid}"), self._timeout))
            return parse_metadata(data)

        with ThreadPoolExecutor(max_workers=self._parallel) as pool:
            found = list(pool.map(one, ids))
        return [c for c in found if c is not None]

    def plain_candidates(self, query: str, limit: int = 8) -> list[Candidate]:
        data = _json(self._run(self._argv(
            "--flat-playlist", "-J", "--", f"ytsearch{limit}:{query}"),
            self._timeout))
        return parse_search(data)

    # -- the question
    def resolve(self, want: Want) -> Scored | None:
        query = f"{want.artist} {want.title}"
        plain = self.plain_candidates(query)  # one quick call
        first = best(want, plain, self._max)
        if first is not None and first.score >= STRONG:
            return first
        # Not clear-cut: ask YouTube Music what each hit declares itself to
        # be (track, artist, album, length) and choose among everything.
        return best(want, self.music_candidates(query) + plain, self._max)
