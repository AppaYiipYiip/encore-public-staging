"""The cover that goes into a kept song's file. A nicety: never a reason to fail a keep."""

from __future__ import annotations

import logging
import os
import urllib.parse
from pathlib import Path

import httpx

from .placement import inside

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


def folder_wants_a_picture(kept_root: Path, file: Path) -> bool:
    """Whether the album folder of [file] is one a picture may be written into: inside [kept_root], the server's own `Encore/` folder (`placement.inside`, after links and dots are
    resolved: a folder of the Host's own music library never is), a folder that exists, and one that holds no `cover.*` and no `folder.*` of any kind (the Host's own picture, or an
    earlier one, is left as it is)."""
    folder = file.parent
    return inside(kept_root, folder) and folder.is_dir() and not any(folder.glob("cover.*")) and not any(folder.glob("folder.*"))


def write_folder_picture(kept_root: Path, file: Path, data: bytes | None) -> bool:
    """A `cover.jpg` in the album folder of [file], so the music server (and every other player of it) shows the album with its picture. Returns whether one was written.

    THE one function the keeper (a new keep filed under its album: N-34 slice 3), the cover finder (a picture found later) and the repair (slice 5) write a folder picture with,
    under the rule of [folder_wants_a_picture]. The picture is written under a hidden name and renamed, so a scan never reads half a picture."""
    if not data or not folder_wants_a_picture(kept_root, file):
        return False
    target, partial = file.parent / "cover.jpg", file.parent / ".cover.jpg.part"
    partial.write_bytes(data)
    os.replace(partial, target)
    return True
