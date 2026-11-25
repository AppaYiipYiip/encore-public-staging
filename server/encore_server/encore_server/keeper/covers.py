"""The cover that goes into a kept song's file. A nicety: never a reason to fail a keep."""

from __future__ import annotations

import logging
import os
import urllib.parse
import uuid
from pathlib import Path

import httpx

from .placement import inside, is_shared_folder

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


#: The names the music server takes as a folder's picture, in its own order (`cover.*`, `folder.*`, `front.*`), compared in lower case: the answer must not depend on whether the
#: file system folds case (a glob does on Windows and does not on Linux).
PICTURE_PREFIXES = ("cover.", "folder.", "front.")


def folder_has_a_picture(folder: Path) -> bool:
    """Whether [folder] already holds a picture under one of the names of [PICTURE_PREFIXES], in any case. A folder that cannot be listed is answered yes: nothing is written."""
    try:
        return any(entry.name.lower().startswith(PICTURE_PREFIXES) for entry in folder.iterdir())
    except OSError:
        return True


def folder_wants_a_picture(kept_root: Path, file: Path) -> bool:
    """Whether the album folder of [file] is one a picture may be written into: inside [kept_root], the server's own `Encore/` folder (`placement.inside`, after links and dots are
    resolved: a folder of the Host's own music library never is), a folder that exists, **not the shared `Singles` folder** (it holds songs of no album: one picture there would be
    the picture of nothing; decided on the folder, `placement.is_shared_folder`), and one that holds no picture of any case (`folder_has_a_picture`: the Host's own, or an earlier
    one, is left as it is)."""
    folder = file.parent
    return inside(kept_root, folder) and folder.is_dir() and not is_shared_folder(folder) and not folder_has_a_picture(folder)


def _write(path: Path, data: bytes, *, exclusive: bool) -> None:
    """Creates [path] with [data] (the default permissions: the music server reads it as another user). [exclusive]: it must not exist yet."""
    flags = os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0) | (os.O_EXCL if exclusive else 0)
    with os.fdopen(os.open(path, flags, 0o666), "wb") as handle:
        handle.write(data)


def write_folder_picture(kept_root: Path, file: Path, data: bytes | None) -> bool:
    """A `cover.jpg` in the album folder of [file], so the music server (and every other player of it) shows the album with its picture. Returns whether one was written.

    THE one function the keeper (a new keep filed under its album: N-34 slice 3), the cover finder (a picture found later) and the repair (slice 5) write a folder picture with,
    under the rule of [folder_wants_a_picture]. **Written under a unique hidden name of this writer's own** (two writers of one folder never share a temp file), **published with
    a hard link, which fails when the target exists** (so a picture another writer made first is never replaced: the no-overwrite is atomic, not check-then-replace), and **the
    temp is removed whatever happens**, so a full disk or a failure half-way leaves no litter. A file system without hard links (some network shares) takes an exclusive create of
    the target instead, removed again if its write fails. Raises `OSError` on a real failure: the keeper catches it, a picture is never a reason to fail a keep."""
    if not data or not folder_wants_a_picture(kept_root, file):
        return False
    target = file.parent / "cover.jpg"
    temp = file.parent / f".cover.{os.getpid()}.{uuid.uuid4().hex}.part"
    try:
        _write(temp, data, exclusive=True)
        try:
            os.link(temp, target)
        except FileExistsError:
            return False
        except OSError:
            try:
                _write(target, data, exclusive=True)
            except FileExistsError:
                return False
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        return True
    finally:
        temp.unlink(missing_ok=True)
