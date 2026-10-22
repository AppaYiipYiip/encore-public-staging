"""Where a kept song goes: `<music>/Encore/Artist/Album/NN - Title.opus` (disc prefix `DD-TT -` for multi-disc releases).

One shared folder: a song is kept once for everybody (docs/04 section 3). Folder names that already exist are reused (ignoring case
and punctuation) so a kept song joins the album that is there instead of starting a second one.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..textnorm import norm_title, safe_path_part, version_signature

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


def track_filename(title: str, *, track: int | None, disc: int | None, total_discs: int | None, suffix: str) -> str:
    name = safe_path_part(title, "Track")
    if track is not None and track > 0:
        prefix = f"{disc:02d}-{track:02d} - " if disc is not None and (total_discs or 1) > 1 else f"{track:02d} - "
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
    artist_dir = _existing_child(music_dir, artist_name) or (music_dir / artist_name)
    album_name = safe_path_part(album or "Singles", "Singles")
    album_dir = _existing_child(artist_dir, album_name) or (artist_dir / album_name)
    return Placement(
        album_dir,
        track_filename(title, track=track, disc=disc, total_discs=total_discs, suffix=suffix),
    )


def find_existing(placement: Placement, title: str) -> Path | None:
    """A file for the same song already in the target folder (any format)."""
    folder = placement.folder
    if not folder.is_dir():
        return None
    # Compared as the file system has it: "Weird Fishes / Arpeggi" is the file "Weird Fishes - Arpeggi", whose part after the dash
    # would otherwise read as a version ("live", "remix") of a different song.
    name = safe_path_part(title, "Track")
    want = norm_title(name)
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
        if norm_title(stem) == want and version_signature(stem) == version_signature(name):
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
    with contextlib.suppress(OSError):
        src.unlink()
    return target
