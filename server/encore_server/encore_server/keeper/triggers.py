"""When the server keeps a song (docs/04 D-3): somebody saved it. Part of the same write as the save, so a save never loses its keep job."""

from __future__ import annotations

import sqlite3

from .. import refs
from ..scheduler import Scheduler


def want_kept(scheduler: Scheduler | None, conn: sqlite3.Connection, person: str, ref_ids: list[str]) -> None:
    """Queues a keep for each of these songs, once, unless the music server already has a file for it."""
    if scheduler is None or not scheduler.handles("keep") or not ref_ids:
        return
    for ref_id in dict.fromkeys(ref_ids):
        file = conn.execute(
            "SELECT 1 FROM song_file WHERE ref = ? AND navidrome_song_id IS NOT NULL LIMIT 1", (ref_id,)
        ).fetchone()
        if file is None and refs.ref_exists(conn, ref_id):
            scheduler.submit("keep", ref_id, person, conn=conn)
