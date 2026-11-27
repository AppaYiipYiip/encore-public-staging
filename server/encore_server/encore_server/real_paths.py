"""Where a library song's file REALLY lies (N-53; docs/tasks/N-53-real-place-of-library-files.md): the hourly errand that gives a `song_file` row its real place.

**The problem.** `song_file.path` is read by everything that wants to find a kept file on the disk, and all of them assume it is the file's location relative to the music folder. For a file the keeper
placed it is. For every other file the scanner stores the `path` of the music server's Subsonic API, which the real music server (0.64.2, measured in CI) builds from the TAGS, not from the place the file
lies. A file the keeper placed whose row the scanner made first keeps that built path too (`attach_file` keeps the path a row has).

**The answer.** `song_file.path_real` says `path` was checked: 1 when the keeper placed the file itself, or when the music server's NATIVE API (the one the server already signs in to as the administrator,
`navidrome_admin.py`) named the place and the file is there. This errand asks the native API, 100 ids at a time, for every row not yet checked, and stores the real place **only if the file is on the disk at
that place inside the music folder and has the size the music server reports for the row** (a music server whose library is another folder, a disk not mounted, another song's file by the same relative
path). It is also the re-link of the rows that existed before: every row starts at 0 and is checked over a few passes.

**Fairness and safety.** A row that cannot be resolved (the song is gone from the music server, the file is not here) is stamped (`path_checked_at`) and goes behind the rows never tried, so it cannot keep
the others from their turn. A write is compare-and-set (the row must still be unchecked and still the same file of the music server): a keeper that linked the same file meanwhile is not overwritten. A music
server that does not answer (or refuses the administrator) stops the pass and stamps nothing. The errand never moves, retags or deletes anything, and `path` is not part of any API answer, so no phone is told.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple, Protocol

from .audio_key import on_disk
from .db import Database
from .ids import now_ms
from .navidrome_admin import AdminUnavailable

log = logging.getLogger("encore_server.real_paths")

#: How many ids one question to the music server names.
CHUNK = 100
#: At most this many rows and this long a pass: the hourly pass catches up with a library in a few hours and never holds the errands for long.
BATCH = 1000
BUDGET_S = 30.0


class Places(Protocol):
    """What the errand needs of the music server's native API (`NavidromeAdmin.song_places`): music-server song id -> the file's place relative to the library, for the ids it knows."""

    @property
    def configured(self) -> bool: ...

    def song_places(self, ids: Sequence[str]) -> dict[str, str]: ...


class Pass(NamedTuple):
    """What one pass did: rows given their real place, rows tried and not resolved (they go to the back), rows not tried (over the budget or the music server did not answer)."""

    resolved: int
    unresolved: int
    left: int


_TODO = (
    "SELECT id, navidrome_song_id, json_extract(meta, '$.size') AS seen_size FROM song_file"
    " WHERE path_real = 0 AND navidrome_song_id IS NOT NULL"
    " ORDER BY path_checked_at, preferred DESC, added_at DESC, id LIMIT ?"
)


class RealPaths:
    """The errand. [clock] is given so that a test needs no wait."""

    def __init__(
        self,
        db: Database,
        music_dir: Path,
        places: Places,
        *,
        clock: Callable[[], float] = time.monotonic,
        batch: int = BATCH,
        budget_s: float = BUDGET_S,
        chunk: int = CHUNK,
    ) -> None:
        self._db = db
        self._music = music_dir
        self._places = places
        self._clock = clock
        self._batch = batch
        self._budget = budget_s
        self._chunk = chunk

    def run_once(self) -> Pass:
        if not self._places.configured:
            return Pass(0, 0, 0)
        with self._db.read() as conn:
            todo = conn.execute(_TODO, (self._batch,)).fetchall()
        began = self._clock()
        resolved = unresolved = 0
        for start in range(0, len(todo), self._chunk):
            chunk = todo[start : start + self._chunk]
            if self._clock() - began > self._budget:
                return Pass(resolved, unresolved, len(todo) - start)
            try:
                found = self._places.song_places([str(row["navidrome_song_id"]) for row in chunk])
            except AdminUnavailable as error:
                log.warning(
                    "real paths: the music server could not be asked (%s); nothing is stamped, the next pass tries again", error
                )
                return Pass(resolved, unresolved, len(todo) - start)
            with self._db.tx() as conn:
                for row in chunk:
                    if self._settle(conn, row, found.get(str(row["navidrome_song_id"]))):
                        resolved += 1
                    else:
                        unresolved += 1
        if resolved:
            log.info("real paths: %d files now have their real place, %d could not be resolved", resolved, unresolved)
        return Pass(resolved, unresolved, 0)

    def _settle(self, conn: sqlite3.Connection, row: sqlite3.Row, place: str | None) -> bool:
        """Gives the row its real place when the file is there with the size the music server reports; otherwise stamps it. Returns whether it was given."""
        file = on_disk(self._music, place) if place else None
        if file is not None:
            try:
                size = file.stat().st_size
            except OSError:
                file = None
            else:
                seen = row["seen_size"]
                if seen is not None and size != seen:
                    file = None  # not the file the music server means (another library's, or retagged and not scanned yet): not trusted now
        if file is not None and place is not None:
            done = conn.execute(
                "UPDATE song_file SET path = ?, path_real = 1, path_checked_at = ? WHERE id = ? AND path_real = 0 AND navidrome_song_id = ?",
                (place.replace("\\", "/"), now_ms(), row["id"], row["navidrome_song_id"]),
            )
            return done.rowcount == 1
        conn.execute("UPDATE song_file SET path_checked_at = ? WHERE id = ? AND path_real = 0", (now_ms(), row["id"]))
        return False
