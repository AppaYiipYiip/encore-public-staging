"""What each person plays and likes, read from the music server's own database (docs/47 section 3, option a; experiment S9).

No password is needed and the app sends nothing extra: the music server already keeps each person's stars and play counts. The module
only ever **reads**, and never the live file: it makes a private copy of the database (and its write-ahead log, where the newest changes
are) in a scratch folder, reads that, and deletes it. The music server never notices.
"""
from __future__ import annotations

import glob
import logging
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .textnorm import norm_artist, norm_title

log = logging.getLogger("encore_recs.library")

DAY = 86400.0


class LibraryUnavailable(Exception):
    """The music server's database could not be read (not mounted, not there yet, a layout this version does not know)."""


@dataclass(frozen=True)
class Seed:
    artist: str
    mbid: str       # from the files' tags when they carry one, else ''
    weight: float
    stars: int
    plays: int


class Reader:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def people(self) -> list[str]:
        return [str(r[0]) for r in self._db.execute("SELECT user_name FROM user ORDER BY user_name")]

    def seeds(self, person: str, now: float, limit: int = 40) -> list[Seed]:
        """The artists this person cares about, strongest first. A star counts three plays; songs played in the last 90 days count twice
        more; songs whose file is gone (an upgrade moved them) do not count."""
        recent = time.strftime("%Y-%m-%d", time.gmtime(now - 90 * DAY))
        rows = self._db.execute(
            """SELECT COALESCE(NULLIF(mf.album_artist, ''), mf.artist) AS artist,
                      MAX(COALESCE(NULLIF(mf.mbz_album_artist_id, ''), NULLIF(mf.mbz_artist_id, ''), '')) AS mbid,
                      SUM(CASE WHEN an.starred = 1 THEN 1 ELSE 0 END) AS stars,
                      SUM(an.play_count) AS plays,
                      SUM(CASE WHEN an.play_date IS NOT NULL AND an.play_date >= ? THEN 1 ELSE 0 END) AS recent
               FROM annotation an
               JOIN media_file mf ON mf.id = an.item_id
               JOIN user u ON u.id = an.user_id
               WHERE an.item_type = 'media_file' AND lower(u.user_name) = lower(?) AND mf.missing = 0
                     AND (an.starred = 1 OR an.play_count > 0)
               GROUP BY lower(COALESCE(NULLIF(mf.album_artist, ''), mf.artist))""", (recent, person)).fetchall()
        seeds = [Seed(str(r["artist"]), str(r["mbid"] or ""), 3.0 * (r["stars"] or 0) + (r["plays"] or 0) + 2.0 * (r["recent"] or 0),
                      int(r["stars"] or 0), int(r["plays"] or 0)) for r in rows if str(r["artist"] or "").strip()]
        return sorted((s for s in seeds if s.weight > 0), key=lambda s: -s.weight)[:limit]

    def library(self) -> "Library":
        """Every artist and song the server has (everybody's: a recommendation is for what the library does not hold yet)."""
        names: set[str] = set()
        mbids: set[str] = set()
        titles: dict[str, set[str]] = {}
        for r in self._db.execute("SELECT artist, album_artist, title, mbz_artist_id, mbz_album_artist_id FROM media_file WHERE missing = 0"):
            for artist in {str(r["artist"] or ""), str(r["album_artist"] or "")}:
                key = norm_artist(artist)
                if key:
                    names.add(key)
                    titles.setdefault(key, set()).add(norm_title(str(r["title"] or "")))
            for mbid in (r["mbz_artist_id"], r["mbz_album_artist_id"]):
                if mbid:
                    mbids.add(str(mbid))
        return Library(names, mbids, titles)


@dataclass(frozen=True)
class Library:
    artists: set[str]
    mbids: set[str]
    titles: dict[str, set[str]]

    def has_artist(self, name: str, mbid: str = "") -> bool:
        return (bool(mbid) and mbid in self.mbids) or norm_artist(name) in self.artists

    def has_song(self, artist: str, title: str) -> bool:
        return norm_title(title) in self.titles.get(norm_artist(artist), set())


@contextmanager
def open_snapshot(directory: Path, scratch: Path | None = None) -> Iterator[Reader]:
    """Copies the music server's database files from [directory] and opens the copy. The copy is deleted when the block ends."""
    files = glob.glob(str(directory / "navidrome.db*"))
    if not (directory / "navidrome.db").is_file():
        raise LibraryUnavailable("The music server's database is not there.")
    folder = Path(tempfile.mkdtemp(prefix="recs-", dir=str(scratch) if scratch else None))
    try:
        for source in files:
            shutil.copy(source, folder)
        db = sqlite3.connect(str(folder / "navidrome.db"))
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only = ON")
            db.execute("SELECT 1 FROM annotation LIMIT 1")
            db.execute("SELECT 1 FROM media_file LIMIT 1")
            db.execute("SELECT 1 FROM user LIMIT 1")
        except sqlite3.DatabaseError as error:
            db.close()
            raise LibraryUnavailable(f"The music server's database has a layout this version does not know ({error}).") from error
        try:
            yield Reader(db)
        finally:
            db.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
