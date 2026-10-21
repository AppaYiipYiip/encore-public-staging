"""Putting the better copy where the quick copy was, and keeping a way back (docs/46 sections 4 and 7).

The quality copy is a **hard link** of the file in the pool, in the same folder as the quick copy and with the same name apart from the
ending (`03 - Silvera.opus` -> `03 - Silvera.flac`): the same bytes under a second name, so the pool and the library cost the disk once.
The quick copy is **moved** (never deleted here) into a hidden folder, where it stays for 14 days; the music server ignores dot-folders.
Everything stays inside the music folder, which is one mount, which is what makes a hard link possible at all (experiment S2).
"""
from __future__ import annotations

import errno
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("encore_quality.delivery")

#: The quality tier's folders, inside the music folder (one mount, so a hard link is possible) and out of the music server's sight
#: (it ignores folders that start with a dot).
POOL_DIR = ".encore/pool"
DOWNLOADS_DIR = ".encore/downloads"
#: slskd refuses to start unless this folder already exists.
INCOMPLETE_DIR = ".encore/downloads/.incomplete"
#: Where the quick copies wait for 14 days.
REPLACED_DIR = ".encore/replaced"
KEEP_QUICK_COPY_DAYS = 14


class DeliveryError(Exception):
    """The swap could not be made; the message is for the owner's page."""


@dataclass(frozen=True)
class Placed:
    quality_rel: str      # the new file, relative to the music folder
    replaced_rel: str     # where the quick copy went, relative to the music folder
    quick_rel: str        # where the quick copy was
    linked: bool          # False when the folders are on different drives and the file had to be copied


def _inside(root: Path, path: Path) -> Path:
    """[path] resolved, and proven to be inside [root] (no `..`, no link pointing out)."""
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise DeliveryError("That file is outside the music folder.") from None
    return resolved


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def place(music: Path, quick_rel: str, pool_file: Path) -> Placed:
    """Links [pool_file] next to the quick copy and moves the quick copy aside. Safe to run twice: a swap already done is left as it is."""
    quick = _inside(music, music / quick_rel)
    pool = _inside(music, pool_file)
    if not pool.is_file():
        raise DeliveryError("The better copy is not where it should be.")
    new_rel = str(Path(quick_rel).with_suffix(pool.suffix.lower())).replace("\\", "/")
    target = _inside(music, music / new_rel)
    replaced = _inside(music, music / REPLACED_DIR / quick_rel)
    replaced_rel = str(replaced.relative_to(music.resolve())).replace("\\", "/")

    if not quick.exists():
        if target.exists() and _same_file(target, pool):
            return Placed(new_rel, replaced_rel, quick_rel, True)  # already swapped, the quick copy is already away
        raise DeliveryError("The original file is not there any more.")
    if target.exists() and not _same_file(target, pool):
        raise DeliveryError("Another file is already where the better copy would go.")

    linked = True
    if not target.exists():
        try:
            os.link(pool, target)
        except OSError as error:
            if error.errno not in (errno.EXDEV, errno.EPERM, errno.EMLINK, errno.EACCES) and not isinstance(error, PermissionError):
                raise DeliveryError(f"The better copy could not be linked ({error.strerror}).") from error
            log.warning("could not hard link %s (%s): copying instead", pool, error.strerror)
            try:
                shutil.copy2(pool, target)
            except OSError as copy_error:
                raise DeliveryError(f"The better copy could not be put in place ({copy_error.strerror}).") from copy_error
            linked = False
    if quick != target:
        try:
            replaced.parent.mkdir(parents=True, exist_ok=True)
            os.replace(quick, replaced)
            os.utime(replaced)  # the 14 days count from the swap, not from when the quick copy was made
        except OSError as error:
            _quietly_remove(target)  # do not leave two copies of the song in the library
            raise DeliveryError(f"The original could not be moved aside ({error.strerror}).") from error
    return Placed(new_rel, replaced_rel, quick_rel, linked)


def undo(music: Path, placed: Placed) -> None:
    """Puts the quick copy back and removes the better one from the library (the pool keeps its copy)."""
    replaced = _inside(music, music / placed.replaced_rel)
    quick = _inside(music, music / placed.quick_rel)
    if not replaced.is_file():
        raise DeliveryError("The original is not kept any more.")
    quick.parent.mkdir(parents=True, exist_ok=True)
    os.replace(replaced, quick)
    _quietly_remove(_inside(music, music / placed.quality_rel))


def purge_replaced(music: Path, now: float, *, days: int = KEEP_QUICK_COPY_DAYS) -> int:
    """Deletes quick copies kept longer than [days] (and the empty folders around them). How many files went."""
    root = music / REPLACED_DIR
    if not root.is_dir():
        return 0
    removed = 0
    limit = now - days * 86400
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            if path.is_file() and path.stat().st_mtime < limit:
                path.unlink()
                removed += 1
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            continue
    return removed


def free_bytes(music: Path) -> int:
    return shutil.disk_usage(music).free


def _quietly_remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
