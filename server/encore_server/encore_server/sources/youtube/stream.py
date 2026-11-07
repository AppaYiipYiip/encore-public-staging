"""Playing a song by streaming it: `GET /api/stream` (docs/tasks P1-02).

The service used to download a whole song before the app could seek in it, and refused anything longer than 45 minutes: a two-hour
recitation could not be played at all. Here the audio is *proxied*: the request resolves the song, asks YouTube for its stream address
(the address is bound to this server's public address, so only this server can open it), and passes the bytes on as they arrive, with
`Range` support, so a player can start at once and jump to any minute. Nothing is kept and nothing has a length limit: keeping a song
(adding it to the library) is the download path in `jobs.py`.

A request that cannot send a first audio byte within [first_byte_s] answers `504` with a plain sentence instead of hanging.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import DownloadError

log = logging.getLogger("encore_server.sources.youtube.stream")

#: The first request is small so the first bytes (and the player) arrive quickly; the rest are larger to save round trips.
FIRST_CHUNK = 256 * 1024
CHUNK = 2 * 1024 * 1024

#: A freshly issued stream address of some YouTube clients answers 403 for a few seconds and then works: the first request is retried
#: for at most this long in all. Later requests are never retried: an address that has worked and then fails has expired.
OPENING_DELAYS = (0.5, 0.5, 0.75, 1.0, 1.25, 1.25)


#: Answers that ask for another upload of the song, not for another try.
_GONE = frozenset({"unavailable", "not_found", "age_restricted"})

MIME = {
    "webm": "audio/webm",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "mp3": "audio/mpeg",
}

#: What a person is told, in plain words, for what can go wrong.
MESSAGES = {
    "not_found": "Nothing matching that song was found.",
    "unavailable": "YouTube has no copy of that song that can be played.",
    "age_restricted": "That song needs an age check, so it cannot be played here.",
    "blocked": "YouTube is not letting this server fetch songs right now. Try again in a little while.",
    "slow": "The song could not be started in time. Try again.",
    "failed": "The song could not be fetched. Try again.",
}
STATUS = {"not_found": 404, "unavailable": 404, "age_restricted": 404, "blocked": 503, "slow": 504, "failed": 502}


class StreamError(Exception):
    """A request that cannot be answered with audio: `status` and `code` go to the app, `message` is a sentence for the person."""

    def __init__(self, code: str) -> None:
        super().__init__(MESSAGES.get(code, MESSAGES["failed"]))
        self.code = code if code in MESSAGES else "failed"
        self.status = STATUS[self.code]
        self.message = MESSAGES[self.code]


@dataclass
class Upstream:
    """What the handler sends: the status and headers, then the bytes."""

    status: int
    headers: dict[str, str]
    body: Iterator[bytes]
    close: Callable[[], None] = lambda: None


@dataclass
class _Info:
    url: str
    headers: dict[str, str]
    size: int | None
    ext: str
    at: float


def _total_from(content_range: str | None) -> int | None:
    match = re.fullmatch(r"bytes\s+\d+-\d+/(\d+|\*)", (content_range or "").strip())
    return int(match.group(1)) if match and match.group(1) != "*" else None


def _client_range(header: str | None) -> tuple[int, int | None] | None:
    """`bytes=a-b` / `bytes=a-` -> (start, end or None). A suffix range or anything odd is not supported here (the whole song)."""
    match = re.fullmatch(r"bytes=(\d+)-(\d*)", (header or "").strip())
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else None
    return (start, end) if end is None or end >= start else None


class StreamProxy:
    def __init__(
        self,
        *,
        candidates: Callable[[Any], list[tuple[str, str, int | None]]],
        extract: Callable[[str, Path], None],
        work_dir: Path,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        first_byte_s: float = 10.0,
        info_ttl_s: float = 3000.0,
        fault: str = "",
        lookups: Any = None,
    ) -> None:
        #: The count of requests made to YouTube today (`rest.Lookups`): named in the stage lines below, so that a person or a test run can read from the
        #: server's own log how many look-ups it used (the rule is at most 10 in a test run, and the count was only ever logged every 25th).
        self._lookups = lookups
        self._candidates = candidates
        self._extract = extract
        self._work = work_dir
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep
        self._clock = clock
        self._first_byte = first_byte_s
        self._ttl = info_ttl_s
        # Fault injection for tests of the whole app against a misbehaving YouTube: youtube_refuse | slow_extract:<ms> | no_results.
        self._fault = fault.strip()
        self._infos: dict[str, _Info] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lookups_said(self) -> str:
        """` (look-ups today: N)` for the stage lines, or nothing when no counter was given."""
        return f" (look-ups today: {self._lookups.today})" if self._lookups is not None else ""

    # ------------------------------------------------------------------ the request

    def open(self, request: Any, range_header: str | None) -> Upstream:
        began = self._clock()
        deadline = began + self._first_byte
        if self._fault == "no_results":
            raise StreamError("not_found")
        if self._fault == "youtube_refuse":
            raise StreamError("blocked")
        try:
            found = self._candidates(request)
        except DownloadError as error:
            raise StreamError(error.code) from error
        if not found:
            raise StreamError("not_found")
        found_at = self._clock()
        last: StreamError | None = None
        for video_id, _title, _duration in found[:3]:
            try:
                upstream = self._start(video_id, range_header, deadline)
                log.info(
                    "stream %s: the song found in %.1f s, the first bytes after %.1f s%s",
                    video_id,
                    found_at - began,
                    self._clock() - began,
                    self._lookups_said(),
                )
                return upstream
            except DownloadError as error:
                last = StreamError(error.code)
                if error.code not in _GONE:
                    raise last from error
        raise last or StreamError("not_found")

    # ------------------------------------------------------------------ keeping: the whole file

    def download(self, request: Any, stem: Path, *, max_bytes: int, timeout_s: float = 120.0) -> Path:
        """Fetches the whole song into `<stem>.<ext>` (renamed from `.part` when complete) and returns the file.

        The address a play just asked for is reused, so saving a song someone is listening to needs no second look-up. Raises
        [DownloadError] with a code the keeper understands (`unavailable`, `too_big`, `blocked`, `download_failed` ...)."""
        deadline = self._clock() + timeout_s
        found = self._candidates(request)
        if not found:
            raise DownloadError("not_found")
        last: DownloadError | None = None
        for video_id, _title, _duration in found[:3]:
            try:
                return self._save(video_id, stem, max_bytes, deadline)
            except StreamError as error:
                if error.code not in _GONE:
                    raise DownloadError("timeout" if error.code == "slow" else error.code) from error
                last = DownloadError(error.code)
            except DownloadError as error:
                if error.code not in _GONE:
                    raise
                last = error
        raise last or DownloadError("not_found")

    def _save(self, video_id: str, stem: Path, max_bytes: int, deadline: float) -> Path:
        for fresh in (False, True):
            info = self._info(video_id, deadline, fresh=fresh)
            if info.size is not None and info.size > max_bytes:
                raise DownloadError("too_big")
            try:
                return self._write(info, stem, max_bytes, deadline)
            except urllib.error.HTTPError as refused:
                # The address that was kept has expired (or never opened): ask again, once.
                if fresh or refused.code not in (403, 404, 410):
                    log.warning(
                        "keep %s: HTTP %s on %s address, giving up", video_id, refused.code, "a fresh" if fresh else "the kept"
                    )
                    raise DownloadError("download_failed", f"HTTP {refused.code}") from refused
            except (urllib.error.URLError, OSError) as error:
                raise DownloadError("download_failed", f"{type(error).__name__}: {error}") from error
        raise DownloadError("download_failed")  # unreachable: the second round either returns or raises

    def _write(self, info: _Info, stem: Path, max_bytes: int, deadline: float) -> Path:
        final = stem.with_name(f"{stem.name}.{info.ext}")
        part = final.with_name(final.name + ".part")
        stem.parent.mkdir(parents=True, exist_ok=True)
        position = 0
        total = info.size
        try:
            with part.open("wb") as out:
                while True:
                    length = FIRST_CHUNK if position == 0 else CHUNK
                    last = position + length - 1
                    if total is not None:
                        last = min(last, total - 1)
                    try:
                        status, data, content_range = self._get(info, position, last, deadline if position == 0 else None)
                    except urllib.error.HTTPError as refused:
                        # Audit B-104 (7 Nov 2026): about 1 chunk request in 8 of a keep was refused with 403 and one song never got through, and the log
                        # did not say where. Where it happens decides what the fix is (the first chunk, a later one, a fresh address). The host only:
                        # the address itself is signed and is never logged.
                        log.warning(
                            "keep: HTTP %s from %s at byte %d of %s (a request for %d bytes)",
                            refused.code,
                            urllib.parse.urlparse(info.url).hostname,
                            position,
                            total if total is not None else "?",
                            last - position + 1,
                        )
                        raise
                    if not data:
                        raise DownloadError("download_failed", "the server sent no bytes")
                    if status == 200 and position > 0:
                        raise DownloadError("download_failed", "the server ignored the range request")
                    out.write(data)
                    position += len(data)
                    # status 200 to a range request: no range support upstream, the whole file arrived in one answer
                    total = position if status == 200 else _total_from(content_range) or total
                    if position > max_bytes:
                        raise DownloadError("too_big")
                    if (total is not None and position >= total) or (total is None and len(data) < length):
                        break
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        os.replace(part, final)
        return final

    # -------------------------------------------------------------- what YouTube says

    def _lock_for(self, video_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(video_id, threading.Lock())

    def _info(self, video_id: str, deadline: float, *, fresh: bool = False) -> _Info:
        """The stream's address, headers and size: kept for most of an hour, asked for once however many players ask at once."""
        with self._lock_for(video_id):
            known = self._infos.get(video_id)
            if known is not None and not fresh and self._clock() - known.at < self._ttl:
                return known
            if self._fault.startswith("slow_extract:"):
                self._sleep(int(self._fault.split(":", 1)[1] or 0) / 1000.0)
            if self._clock() >= deadline:
                raise StreamError("slow")
            self._work.mkdir(parents=True, exist_ok=True)
            path = self._work / f"stream-{video_id}.info.json"
            asked = self._clock()
            try:
                self._extract(video_id, path)
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise DownloadError("download_failed", str(error)) from error
            finally:
                path.unlink(missing_ok=True)
            url = data.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise DownloadError("download_failed", "no stream address")
            size = data.get("filesize") or data.get("filesize_approx")
            ext = str(data.get("ext") or "webm")
            info = _Info(
                url=url,
                headers={k: str(v) for k, v in (data.get("http_headers") or {}).items() if k.lower() not in {"range", "host"}},
                size=int(size) if isinstance(size, (int, float)) and size > 0 else None,
                ext=ext if re.fullmatch(r"[a-z0-9]{2,5}", ext) else "webm",
                at=self._clock(),
            )
            self._infos[video_id] = info
            log.info("stream %s: the address was asked for (%.1f s)%s", video_id, self._clock() - asked, self._lookups_said())
            return info

    # ------------------------------------------------------------- the bytes

    def _get(self, info: _Info, first: int, last: int, deadline: float | None) -> tuple[int, bytes, str | None]:
        """One ranged request. The first request of a fresh address is retried while it answers 403 (a TV-client address works a few
        seconds after it is issued), for as long as the deadline allows."""
        request = urllib.request.Request(info.url, headers={**info.headers, "Range": f"bytes={first}-{last}"})
        waits = iter(OPENING_DELAYS if deadline is not None else ())
        while True:
            try:
                with self._open(request, timeout=20) as response:
                    return getattr(response, "status", 200), response.read(), response.headers.get("Content-Range")
            except urllib.error.HTTPError as refused:
                delay = next(waits, None) if refused.code == 403 else None
                if delay is None or (deadline is not None and self._clock() + delay >= deadline):
                    raise
                self._sleep(delay)

    def _start(self, video_id: str, range_header: str | None, deadline: float) -> Upstream:
        info = self._info(video_id, deadline)
        try:
            return self._begin(info, range_header, deadline)
        except urllib.error.HTTPError as refused:
            if refused.code not in (403, 404, 410):
                raise StreamError("failed") from refused
        except (urllib.error.URLError, OSError):
            raise StreamError("failed") from None
        # The address that was kept has expired: ask again, once.
        info = self._info(video_id, deadline, fresh=True)
        try:
            return self._begin(info, range_header, deadline)
        except urllib.error.HTTPError as refused:
            # A fresh address that still answers 403 when the time is up has simply not opened yet.
            raise StreamError("slow" if refused.code == 403 else "failed") from refused
        except (urllib.error.URLError, OSError):
            raise StreamError("failed") from None

    def _begin(self, info: _Info, range_header: str | None, deadline: float) -> Upstream:
        asked = _client_range(range_header)
        start = asked[0] if asked else 0
        end = asked[1] if asked else None
        if end is None and info.size is not None:
            end = info.size - 1
        last = start + FIRST_CHUNK - 1
        if end is not None:
            last = min(last, end)
        status, data, content_range = self._get(info, start, last, deadline)
        if not data:
            raise StreamError("failed")
        if status == 200 and start > 0:
            raise StreamError("failed")
        total = _total_from(content_range) or info.size
        if status == 200:
            total = len(data)  # no range support upstream: the whole file in one answer
            end = total - 1
        elif end is None and total is not None:
            end = total - 1
        headers = {"Content-Type": MIME.get(info.ext, "application/octet-stream"), "Accept-Ranges": "bytes"}
        if end is not None:
            headers["Content-Length"] = str(end - start + 1)
        if asked and total is not None and end is not None:
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        client_status = 206 if asked else 200

        def chunks() -> Iterator[bytes]:
            position = start
            yield data
            position += len(data)
            while end is None or position <= end:
                stop = position + CHUNK - 1
                if end is not None:
                    stop = min(stop, end)
                try:
                    status_, piece, _ = self._get(info, position, stop, None)
                except (urllib.error.URLError, OSError) as error:
                    log.info("the stream stopped at %d: %s", position, error)
                    return
                if not piece or status_ == 200:
                    return
                yield piece
                position += len(piece)
                if end is None and len(piece) < CHUNK:
                    return

        return Upstream(client_status, headers, chunks())
