"""Where a fetched song goes in the music library, and the guards around it.

The owner's library is `Artist/Album/NN - Title.ext` (disc prefix `DD-TT -`
for multi-disc releases). Folder names that already exist are reused
(case-insensitively, ignoring punctuation) so a fetched song joins the album
that is there instead of starting a second one.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .textnorm import norm_title, safe_path_part, version_signature

AUDIO_SUFFIXES = {".opus", ".ogg", ".m4a", ".mp3", ".flac", ".aac", ".wav"}


@dataclass(frozen=True)
class Placement:
    folder: Path
    filename: str

    @property
    def path(self) -> Path:
        return self.folder / self.filename


def _folder_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", norm_title(name) or name.lower())


def _existing_child(parent: Path, wanted: str) -> Path | None:
    """The sub-folder of [parent] that is the same name as [wanted] apart from
    case and punctuation, if there is one."""
    if not parent.is_dir():
        return None
    key = _folder_key(wanted)
    if not key:
        return None
    try:
        children = sorted(c for c in parent.iterdir() if c.is_dir())
    except OSError:
        return None
    for child in children:
        if child.name.lower() == wanted.lower():
            return child
    for child in children:
        if _folder_key(child.name) == key:
            return child
    return None


def track_filename(title: str, *, track: int | None, disc: int | None,
                   total_discs: int | None, suffix: str) -> str:
    name = safe_path_part(title, "Track")
    if track is not None and track > 0:
        if disc is not None and (total_discs or 1) > 1:
            prefix = f"{disc:02d}-{track:02d} - "
        else:
            prefix = f"{track:02d} - "
        name = prefix + name
    return name + suffix


def plan_placement(
    music_dir: Path,
    *,
    artist: str,
    album: str | None,
    title: str,
    track: int | None = None,
    disc: int | None = None,
    total_discs: int | None = None,
    suffix: str = ".opus",
) -> Placement:
    """Where the file goes. Nothing is created here."""
    artist_name = safe_path_part(artist, "Unknown Artist")
    artist_dir = _existing_child(music_dir, artist_name) or (
        music_dir / artist_name)
    album_name = safe_path_part(album or "Singles", "Singles")
    album_dir = _existing_child(artist_dir, album_name) or (
        artist_dir / album_name)
    return Placement(
        album_dir,
        track_filename(title, track=track, disc=disc,
                       total_discs=total_discs, suffix=suffix),
    )


def find_existing(placement: Placement, title: str) -> Path | None:
    """A file for the same song already in the target folder (any format)."""
    folder = placement.folder
    if not folder.is_dir():
        return None
    want = norm_title(title)
    if not want:
        return None
    try:
        files = sorted(folder.iterdir())
    except OSError:
        return None
    for f in files:
        if f.suffix.lower() not in AUDIO_SUFFIXES or not f.is_file():
            continue
        stem = re.sub(r"^\d{1,2}(-\d{1,2})?\s*-\s*", "", f.stem)
        if norm_title(stem) == want and version_signature(stem) == version_signature(title):
            return f
    return None


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 100):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(str(path))


def free_gb(path: Path) -> float:
    """Free space of the volume [path] is on. A folder that does not exist
    yet (the first song of a new library) is measured through its nearest
    existing parent."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free / 1e9


def inside(root: Path, candidate: Path) -> bool:
    """`candidate` is [root] or below it (after resolving links and dots)."""
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


class PersonLayout:
    """One library per person (docs/26): a song somebody asks for is saved in THEIR folder under the music root, so only they (and
    nobody else) can play it, exactly like the music they brought themselves.

    A person's folder is called like the person, unless [folders] says otherwise (for example `owner` -> `owner-added` when
    `owner` is an existing collection that is mounted read-only). The folder must already exist: the people tool made it together
    with the person's library, and a fetch must never invent a place that no library covers."""

    def __init__(self, music_dir: Path, folders: dict[str, str] | None = None) -> None:
        self._music = music_dir
        self._folders = dict(folders or {})

    def root_for(self, user: str) -> Path | None:
        name = self._folders.get(user, user)
        if (not name or name in (".", "..") or "/" in name or "\\" in name
                or name.startswith((".", "_"))):  # never climb out, never the shared or a hidden folder
            return None
        root = self._music / name
        if not root.is_dir() or not inside(self._music, root):
            return None
        if root.resolve() == self._music.resolve():
            return None
        return root


def place_file(src: Path, placement: Placement, music_dir: Path) -> Path:
    """Moves [src] into the library. Refuses to write outside [music_dir]."""
    target = unique_path(placement.path)
    if not inside(music_dir, target):
        raise ValueError("target is outside the library")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Same file system -> rename; otherwise copy then remove, and never leave
    # a half-written file where the scanner could pick it up.
    tmp = target.with_name("." + target.name + ".part")
    shutil.copyfile(src, tmp)
    os.replace(tmp, target)
    try:
        src.unlink()
    except OSError:
        pass
    return target
