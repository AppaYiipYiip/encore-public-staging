"""Where a kept song goes: `<music>/Encore/Artist/Album/NN - Title.opus` (disc prefix `DD-TT -` for multi-disc releases).

One shared folder: a song is kept once for everybody (docs/04 section 3). Folder names that already exist are reused (ignoring case
and punctuation) so a kept song joins the album that is there instead of starting a second one.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..textnorm import (
    UNKNOWN_ARTIST,
    fold,
    is_placeholder_album,
    norm_title,
    safe_path_part,
    title_key,
    version_signature,
    words,
)

AUDIO_SUFFIXES = {".opus", ".ogg", ".m4a", ".mp3", ".flac", ".aac", ".wav"}


@dataclass(frozen=True)
class Placement:
    folder: Path
    filename: str

    @property
    def path(self) -> Path:
        return self.folder / self.filename


def _folder_key(name: str) -> str:
    """A folder name as its letters and digits in any alphabet, joined (P2-25: it was `a-z0-9`, so every Arabic or Russian artist folder was `''`, and a folder
    that was there was never joined). The same fold as the keys, so a folder written with other marks or another case is the same folder."""
    return "".join(words(norm_title(name) or fold(name)))


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


def artist_folder(kept_root: Path, artist: str) -> Path | None:
    """The folder under [kept_root] (the server's own `Encore/` folder) that the keeper puts [artist]'s albums in, if it exists yet: the very one
    [plan_placement] chooses, so what finds an artist's folder and what makes it can never disagree."""
    name = safe_path_part(artist, UNKNOWN_ARTIST)
    folder = _existing_child(kept_root, name) or (kept_root / name)
    return folder if folder.is_dir() else None


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
    artist_name = safe_path_part(artist, UNKNOWN_ARTIST)
    artist_dir = _existing_child(music_dir, artist_name) or (music_dir / artist_name)
    album_name = safe_path_part(album or "Singles", "Singles")
    album_dir = _existing_child(artist_dir, album_name) or (artist_dir / album_name)
    return Placement(
        album_dir,
        track_filename(title, track=track, disc=disc, total_discs=total_discs, suffix=suffix),
    )


def plan_for_ref(root: Path, ref: dict[str, Any], suffix: str = ".opus") -> Placement:
    """Where the file of a song goes, planned from the song's ref (the API's shape: `artists`, `albumArtist`, `album`, `title`, `trackNo`, `discNo`). THE one function the keeper,
    the dry run of the new keeps (N-34 slice 3: what a keep would be filed under) and the repair of the files already kept (slice 5) plan with. Nothing is created here.
    **The music server's placeholder (`[Unknown Album]`) is no album**: it is never made a folder (`textnorm.is_placeholder_album`, the same definition the tags use): that folder IS the
    bucket N-34 empties, and a song put in it once and in `Singles` the next time was saved twice (audit B-110's own example)."""
    album = ref.get("album")
    return plan_placement(
        root,
        artist=ref.get("albumArtist") or ref["artists"][0],
        album=None if is_placeholder_album(album) else album,
        title=ref["title"],
        track=ref.get("trackNo"),
        disc=ref.get("discNo"),
        suffix=suffix,
    )


def find_existing(placement: Placement, title: str, *, skip: Callable[[Path], bool] | None = None) -> Path | None:
    """A file for the same song already in the target folder (any format). A file for which [skip] says yes is not the song's to take: the keeper skips the files another
    song holds (N-34 slice 3, audit B-110: two refs of one song were handed one file)."""
    folder = placement.folder
    if not folder.is_dir():
        return None
    # Compared as the file system has it: "Weird Fishes / Arpeggi" is the file "Weird Fishes - Arpeggi", whose part after the dash
    # would otherwise read as a version ("live", "remix") of a different song.
    name = safe_path_part(title, "Track")
    want = title_key(
        name
    )  # the key, not the bare words: a title in any alphabet is found, one that folds to nothing is still itself
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
        if title_key(stem) == want and version_signature(stem) == version_signature(name) and not (skip is not None and skip(f)):
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
