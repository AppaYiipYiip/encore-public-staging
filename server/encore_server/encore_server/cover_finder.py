"""Pictures for songs that have none: a song that came from a plain music library, or from a list that carried no artwork.

The app shows a song's picture from its ref (`coverUrl`), so a picture found here reaches every phone through the ordinary feeds. The
look-up is the catalogue's public search (Deezer), a few songs a second, once per album where the album is known; a song nothing is
found for is not asked about again for a week.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from . import library, refs
from .db import Database
from .ids import now_ms
from .keeper.covers import cover_url_ok, fetch_cover
from .keeper.keeper import KEPT_FOLDER
from .keeper.placement import inside
from .textnorm import norm_artist, norm_title

log = logging.getLogger("encore_server.cover_finder")

SEARCH_URL = "https://api.deezer.com/search"
#: How long a song nothing was found for is left alone.
RETRY_AFTER_MS = 7 * 24 * 3600 * 1000


class Lookup(Protocol):
    def __call__(self, artist: str, title: str, album: str | None) -> str | None: ...


def deezer_lookup(artist: str, title: str, album: str | None, *, client: httpx.Client | None = None) -> str | None:
    """The picture of the album this recording is on, from the catalogue; `None` when it is not sure which song it is.

    A plain search (the catalogue's field search finds nothing for many real songs), and then only a hit whose artist and title are the
    ones asked for counts."""
    own = client is None
    http = client or httpx.Client(timeout=8.0, headers={"User-Agent": "encore-server/1"})
    try:
        response = http.get(SEARCH_URL, params={"q": f"{artist} {title}", "limit": 8})
        if response.status_code != 200:
            return None
        body = response.json()
        found = body.get("data") if isinstance(body, dict) else None
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if own:
            http.close()
    if not isinstance(found, list):
        return None
    want_artist, want_title = norm_artist(artist), norm_title(title)
    best: tuple[int, str] | None = None
    for hit in found:
        if not isinstance(hit, dict):
            continue
        hit_artist = norm_artist(str((hit.get("artist") or {}).get("name", "")))
        hit_title = norm_title(str(hit.get("title", "")))
        if hit_artist != want_artist or hit_title != want_title:
            continue
        cover = hit.get("album") or {}
        url = cover.get("cover_xl") or cover.get("cover_big")
        if not isinstance(url, str) or not cover_url_ok(url):
            continue
        score = 2 if album and norm_title(str(cover.get("title", ""))) == norm_title(album) else 1
        if best is None or score > best[0]:
            best = (score, url)
    return best[1] if best else None


@dataclass
class CoverReport:
    looked: int = 0
    found: int = 0
    complete: bool = True


class CoverFinder:
    def __init__(
        self,
        db: Database,
        lookup: Lookup | None = None,
        *,
        per_pass: int = 300,
        pause_s: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        music_dir: Path | None = None,
        fetch: Callable[[str | None], bytes | None] = fetch_cover,
        after: Callable[[], object] | None = None,
    ) -> None:
        self._music = music_dir
        self._fetch = fetch
        self._after = after
        self._wrote_art = False
        self._db = db
        # Looked up when the finder is made, not when this module is loaded, so a test can put its own in (B27).
        self._lookup: Lookup = lookup if lookup is not None else deezer_lookup
        self._per_pass = per_pass
        self._pause = pause_s
        self._sleep = sleep

    def _wanting(self, conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
        """Songs somebody has (a like, a playlist entry) or the server keeps, without a picture, kept ones and liked ones first."""
        return conn.execute(
            "SELECT r.id, r.title, r.artists, r.album, r.album_artist FROM song_ref r"
            " WHERE r.cover_url IS NULL AND (r.cover_tried_at IS NULL OR r.cover_tried_at < ?)"
            " AND (EXISTS (SELECT 1 FROM song_file f WHERE f.ref = r.id)"
            "  OR EXISTS (SELECT 1 FROM library_item i WHERE i.kind = 'like' AND i.target = r.id)"
            "  OR EXISTS (SELECT 1 FROM playlist_entry e WHERE e.ref = r.id AND e.deleted_at IS NULL))"
            " ORDER BY r.album, r.id LIMIT ?",
            (now_ms() - RETRY_AFTER_MS, limit),
        ).fetchall()

    #: The `setting` row that says the songs which gained a derived cover (P1-26) were announced to the phones that already had them.
    _ANNOUNCED = "derived_video_covers_announced"

    def _announce_derived_once(self) -> int:
        """P1-26: a song with a YouTube video and no other picture is served with the video's own thumbnail (`refs.video_thumbnail`). That is
        computed when the ref is served, so a phone that synced the song earlier would not see it change: once, tell every holder of such a song
        (a like, a playlist entry) and the files feed that it changed, the way a found cover does. Later songs are served right the first time."""
        with self._db.tx() as conn:
            if conn.execute("SELECT 1 FROM setting WHERE key = ?", (self._ANNOUNCED,)).fetchone() is not None:
                return 0
            rows = conn.execute(
                "SELECT id FROM song_ref WHERE ytm_video_id IS NOT NULL AND cover_url IS NULL AND thumb_url IS NULL"
            ).fetchall()
            for row in rows:
                library.touch_ref_holders(conn, row["id"])
                if conn.execute("SELECT 1 FROM song_file WHERE ref = ?", (row["id"],)).fetchone() is not None:
                    refs.touch_file(conn, row["id"])
            conn.execute("INSERT INTO setting (key, value) VALUES (?, '1')", (self._ANNOUNCED,))
        return len(rows)

    def run_once(self) -> CoverReport:
        self._announce_derived_once()
        report = CoverReport()
        with self._db.read() as conn:
            rows = self._wanting(conn, self._per_pass + 1)
        report.complete = len(rows) <= self._per_pass
        by_album: dict[tuple[str, str], str] = {}
        for row in rows[: self._per_pass]:
            artists = _artists(row["artists"])
            if not artists:
                continue
            album = row["album"]
            key = (norm_artist(row["album_artist"] or artists[0]), norm_title(album)) if album else None
            url = by_album.get(key) if key is not None else None
            if url is None:
                report.looked += 1
                url = self._lookup(artists[0], row["title"], album)
                if key is not None and url:
                    by_album[key] = url
                self._sleep(self._pause)
            self._store(row["id"], url)
            report.found += 1 if url else 0
        if report.found:
            log.info("pictures found for %d of %d songs", report.found, report.looked)
        if self._wrote_art and self._after is not None:
            self._wrote_art = False
            try:
                self._after()  # the music server learns of the new folder pictures now, not at its next scan
            except Exception:  # noqa: BLE001 - it scans on its own schedule anyway
                log.info("could not ask the music server to scan", exc_info=True)
        return report

    def _store(self, ref_id: str, url: str | None) -> None:
        with self._db.tx() as conn:
            if url:
                conn.execute("UPDATE song_ref SET cover_url = ?, cover_tried_at = ? WHERE id = ?", (url, now_ms(), ref_id))
                # Everybody who has the song, and everybody browsing the server's files, learns it has a picture.
                library.touch_ref_holders(conn, ref_id)
                files = conn.execute("SELECT path FROM song_file WHERE ref = ?", (ref_id,)).fetchall()
                if files:
                    refs.touch_file(conn, ref_id)
                folders = [str(f["path"]) for f in files if f["path"]]
            else:
                conn.execute("UPDATE song_ref SET cover_tried_at = ? WHERE id = ?", (now_ms(), ref_id))
                folders = []
        for relative in folders:
            self._folder_picture(relative, url)

    def _folder_picture(self, relative: str, url: str | None) -> None:
        """A `cover.jpg` in the album folder of a file this server keeps, so the music server (and every other player of it) shows the album
        with its picture; a folder that already has one is left as it is."""
        if self._music is None or not url or not relative.startswith(KEPT_FOLDER + "/"):
            return
        folder = (self._music / relative).parent
        if not inside(self._music, folder) or not folder.is_dir() or any(folder.glob("cover.*")) or any(folder.glob("folder.*")):
            return
        data = self._fetch(url)
        if data:
            (folder / "cover.jpg").write_bytes(data)
            self._wrote_art = True


def _artists(raw: Any) -> list[str]:
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(a) for a in loaded if isinstance(a, str) and a] if isinstance(loaded, list) else []
