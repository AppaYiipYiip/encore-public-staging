"""The cover that goes into a kept song's file. A nicety: never a reason to fail a keep."""

from __future__ import annotations

import logging
import urllib.parse

import httpx

log = logging.getLogger("encore_server.keeper.covers")

#: A cover may only come from these hosts (a person's request must not make the server fetch arbitrary addresses).
COVER_HOSTS = (
    "dzcdn.net",
    "deezer.com",
    "ytimg.com",
    "ggpht.com",
    "googleusercontent.com",
    "coverartarchive.org",
    "archive.org",
    # What a playlist import's own picture allow-list (imports/readers.py) also trusts: a song described by an import carries these.
    "scdn.co",
    "spotifycdn.com",
)


def cover_url_ok(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in COVER_HOSTS)


def fetch_cover(url: str | None, *, max_bytes: int = 6 * 1024 * 1024, timeout: float = 10.0) -> bytes | None:
    """The image's bytes, or `None`."""
    if not cover_url_ok(url):
        return None
    assert url is not None
    try:
        with httpx.stream(
            "GET", url, timeout=timeout, headers={"User-Agent": "encore-server/1"}, follow_redirects=False
        ) as response:
            if response.status_code != 200:
                return None
            data = b""
            for piece in response.iter_bytes():
                data += piece
                if len(data) > max_bytes:
                    return None
    except httpx.HTTPError as error:
        log.info("no cover from %s: %s", urllib.parse.urlparse(url).hostname, type(error).__name__)
        return None
    return data or None
