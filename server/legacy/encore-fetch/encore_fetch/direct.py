"""Downloading the audio straight from the address yt-dlp found, without starting yt-dlp again (docs/tasks P1-01).

The extraction (`lean.InProcessExtractor`) already saved the stream's address, headers and size. Starting a second `yt-dlp` program
only to fetch that address cost 1 to 4 seconds before the first byte (measured on 2026-10-21). Here the bytes are fetched with plain
ranged HTTP requests into `<stem>.<ext>.part` (the name yt-dlp uses, so the live reader and the player that starts on the growing file
keep working) and the file is renamed when complete.

Any trouble (an expired address, a refusal, a short answer) raises [DirectFailed]: the caller then does it the old way.
"""
from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .download import DownloadError

#: The first request is small so the first bytes (and the player) arrive quickly; the rest are larger to save round trips.
FIRST_CHUNK = 256 * 1024
CHUNK = 2 * 1024 * 1024

Opener = Callable[..., Any]


class DirectFailed(Exception):
    """The direct download did not work; the old way should be tried."""


def _total_from(content_range: str | None) -> int | None:
    match = re.fullmatch(r"bytes\s+\d+-\d+/(\d+|\*)", (content_range or "").strip())
    return int(match.group(1)) if match and match.group(1) != "*" else None


def _extension(info: dict[str, Any]) -> str:
    ext = str(info.get("ext") or "webm")
    return ext if re.fullmatch(r"[a-z0-9]{2,5}", ext) else "webm"


def fetch(info: dict[str, Any], stem: Path, *, max_bytes: int, timeout: float = 20.0, opener: Opener | None = None) -> Path:
    """Fetches the stream described by [info] (a yt-dlp info dict) into `<stem>.<ext>`; returns the finished file."""
    url = info.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise DirectFailed("the info has no https stream address")
    headers = {k: str(v) for k, v in (info.get("http_headers") or {}).items() if k.lower() not in {"range", "host"}}
    size = info.get("filesize") or info.get("filesize_approx")
    size = int(size) if isinstance(size, (int, float)) and size > 0 else None
    if size is not None and size > max_bytes:
        raise DownloadError("too_big")
    opener = opener or urllib.request.urlopen

    ext = _extension(info)
    final = stem.with_name(f"{stem.name}.{ext}")
    part = final.with_name(final.name + ".part")
    stem.parent.mkdir(parents=True, exist_ok=True)
    position = 0
    total = size
    try:
        with part.open("wb") as out:
            while True:
                length = FIRST_CHUNK if position == 0 else CHUNK
                last = position + length - 1
                if total is not None:
                    last = min(last, total - 1)
                request = urllib.request.Request(url, headers={**headers, "Range": f"bytes={position}-{last}"})
                with opener(request, timeout=timeout) as response:
                    status = getattr(response, "status", 200)
                    data = response.read()
                    content_range = response.headers.get("Content-Range")
                if not data:
                    raise DirectFailed("the server sent no bytes")
                if status == 200 and position > 0:
                    raise DirectFailed("the server ignored the range request")
                if status == 200:
                    # The whole file in one answer (no range support): that is all there is.
                    out.write(data)
                    out.flush()
                    position = len(data)
                    total = position
                else:
                    out.write(data)
                    out.flush()
                    position += len(data)
                    total = _total_from(content_range) or total
                if position > max_bytes:
                    raise DownloadError("too_big")
                if total is not None and position >= total:
                    break
                if total is None and len(data) < length:
                    break  # a short answer without a known size: the end of the file
    except (urllib.error.URLError, OSError, ValueError) as error:
        part.unlink(missing_ok=True)
        raise DirectFailed(f"{error.__class__.__name__}: {error}") from error
    except (DirectFailed, DownloadError):
        part.unlink(missing_ok=True)
        raise
    os.replace(part, final)
    return final
