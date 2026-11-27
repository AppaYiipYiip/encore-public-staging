"""Where a `song_file` row's file lies, for the code that wants to READ or WRITE it (N-53; docs/tasks/N-53-real-place-of-library-files.md).

`song_file.path` is a location only when `song_file.path_real` is 1: the keeper placed the file there, or the hourly errand (`real_paths.py`) asked the music server's native API and found the file there. The
`path` the scanner stores is the music server's Subsonic path, which it builds from the TAGS (measured on the real music server), so a path that names a file proves nothing about that row. **Every reader
that needs a location goes through [trusted_file]** (the audio-key errand does; the repairs to come must), and a checked path that no longer names a file is not trusted any more: the mark is taken back and
the errand asks the music server again.
"""

from __future__ import annotations

from pathlib import Path

from .db import Database
from .keeper.placement import inside


def on_disk(music_dir: Path, stored: str) -> Path | None:
    """The file a stored path names (relative to [music_dir], taken as it is, never searched for, never `..`), or `None` (not there, or not inside the music folder). It says nothing of whether the
    path is a LOCATION: see the module's text."""
    parts = stored.replace("\\", "/")
    if not parts or any(part in ("..", ".") for part in parts.split("/")):
        return None
    candidate = music_dir / parts
    return candidate if inside(music_dir, candidate) and candidate.is_file() else None


def trusted_file(db: Database, music_dir: Path, file_id: str, stored: str) -> Path | None:
    """The file of a row whose path is CHECKED (`path_real = 1`), or `None`.

    A checked path that names no file now (the file was moved or deleted, a disk is not mounted) is not trusted any more: **the mark is taken back** (`path_real = 0`, and the row goes to the front of the
    errand's queue), so the music server is asked where the file lies now. Only if the row still holds the path the caller read (a keeper that linked it meanwhile is not undone)."""
    file = on_disk(music_dir, stored)
    if file is None:
        with db.tx() as conn:
            conn.execute(
                "UPDATE song_file SET path_real = 0, path_checked_at = NULL WHERE id = ? AND path = ? AND path_real = 1",
                (file_id, stored),
            )
    return file
