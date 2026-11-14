"""The memory of refusals as the YouTube source uses it (N-13): the song ref's own `missing_*` columns behind four small questions.

The source (`sources/youtube/source.py`) knows nothing about the database; it is given one of these. A test gives it a fake; the server wires this one in
`api.create_app`, so any `YoutubeSource` the application runs has it.
"""

from __future__ import annotations

from collections.abc import Callable

from . import refs
from .db import Database
from .ids import now_ms
from .missing import Standing, standing_of


class RefVerdicts:
    def __init__(self, database: Database, clock: Callable[[], int] = now_ms) -> None:
        self._db = database
        self._clock = clock

    def standing(self, ref_id: str) -> Standing | None:
        """What this song's ref remembers (live or not), or `None`. A read: nothing is written on the way to a play."""
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT missing_reason, missing_at, missing_tried_at, missing_rev FROM song_ref WHERE id = ?", (ref_id,)
            ).fetchone()
        return None if row is None else standing_of(row, self._clock())

    def record(self, ref_id: str, reason: str) -> None:
        with self._db.tx() as conn:
            refs.remember_missing(conn, ref_id, reason, now=self._clock())

    def clear(self, ref_id: str) -> None:
        with self._db.tx() as conn:
            refs.clear_missing(conn, ref_id)
