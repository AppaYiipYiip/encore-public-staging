"""The scanner link (docs/04 section 3, P2-01): every song the music server already has gets a ref and a file.

The Host's own collection, the songs the keeper put there, and anything added by hand all become refs the same way, so a person can
like, queue and add to playlists whatever the server has, and the server's files and the people's choices never share an id. A song
that already has a ref (matched by ISRC, then by artist, title and length) is *attached* to it, so one recording found in several
folders is one ref with several files. A file that is gone from the library loses its row; the ref, and every like and playlist
entry pointing at it, stays.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from . import library, refs
from .db import Database
from .errors import ApiError
from .ids import now_ms
from .navidrome import file_meta

log = logging.getLogger("encore_server.scanner")

PAGE = 500
_CODEC = {"opus": "opus", "ogg": "opus", "m4a": "aac", "aac": "aac", "mp3": "mp3", "flac": "flac", "wav": "wav"}


class Library(Protocol):
    def songs(self, offset: int, size: int = ...) -> list[dict[str, Any]] | None: ...


@dataclass
class LinkReport:
    seen: int = 0
    linked: int = 0
    new_refs: int = 0
    pruned: int = 0
    skipped: int = 0
    complete: bool = False


def _first(value: object) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) if value not in (None, "") else None


def described(song: dict[str, Any]) -> dict[str, Any] | None:
    """The music server's song as `refs.resolve` wants it, or `None` when it has no usable title and artist."""
    artists = [str(a.get("name")) for a in song.get("artists") or [] if isinstance(a, dict) and a.get("name")]
    if not artists and song.get("artist"):
        artists = [str(song["artist"])]
    title = str(song.get("title") or "").strip()
    if not title or not artists:
        return None
    album_artists = [str(a.get("name")) for a in song.get("albumArtists") or [] if isinstance(a, dict) and a.get("name")]
    seconds = song.get("duration")
    return {
        "title": title,
        "artists": artists,
        "album": song.get("album") or None,
        "albumArtist": (album_artists[0] if album_artists else None) or song.get("albumArtist") or None,
        "trackNo": song.get("track"),
        "discNo": song.get("discNumber"),
        "year": song.get("year"),
        "durationMs": int(seconds * 1000) if isinstance(seconds, (int, float)) and seconds > 0 else None,
        "isrc": _first(song.get("isrc")),
        "mbid": _first(song.get("musicBrainzId")),
    }


def link_library(db: Database, navidrome: Library, *, page: int = PAGE) -> LinkReport:
    """One pass over the music server's songs. Safe to run again at any time (nothing is created twice)."""
    report = LinkReport()
    began = now_ms()
    seen_ids: set[str] = set()
    offset = 0
    while True:
        songs = navidrome.songs(offset, page)
        if songs is None:
            log.info("the music server did not answer; the library link will try again later")
            return report  # incomplete: nothing is pruned
        with db.tx() as conn:
            for song in songs:
                report.seen += 1
                item = described(song)
                song_id = str(song.get("id") or "")
                if item is None or not song_id:
                    report.skipped += 1
                    continue
                seen_ids.add(song_id)
                try:
                    known = refs.find(conn, refs.parse_item(item)) is not None
                    ref = refs.resolve(conn, item)
                except ApiError:
                    report.skipped += 1
                    continue
                if not known:
                    report.new_refs += 1
                suffix = str(song.get("suffix") or "").lower()
                refs.attach_file(
                    conn,
                    ref["id"],
                    navidrome_song_id=song_id,
                    path=str(song.get("path") or "") or None,
                    codec=_CODEC.get(suffix, suffix or None),
                    bitrate_kbps=song.get("bitRate") if isinstance(song.get("bitRate"), int) else None,
                    source="library",
                    meta=file_meta(song),
                )
                report.linked += 1
        if len(songs) < page:
            break
        offset += len(songs)
    report.complete = True
    report.pruned = _prune(db, seen_ids, began)
    return report


def _prune(db: Database, seen_ids: set[str], before: int) -> int:
    """Files the music server no longer has: their rows go; the refs stay, so nothing a person has changes. Everybody who had the
    song is told that it now has to be streamed again. A file attached after the pass began (the keeper, mid-scan) is left alone."""
    removed = 0
    with db.tx() as conn:
        for row in conn.execute(
            "SELECT id, ref, navidrome_song_id FROM song_file WHERE navidrome_song_id IS NOT NULL AND added_at < ?", (before,)
        ).fetchall():
            if row["navidrome_song_id"] in seen_ids:
                continue
            conn.execute("DELETE FROM song_file WHERE id = ?", (row["id"],))
            # The newest remaining copy (if any) becomes the preferred one.
            conn.execute(
                "UPDATE song_file SET preferred = 1 WHERE id = (SELECT id FROM song_file WHERE ref = ? ORDER BY added_at DESC LIMIT 1)",
                (row["ref"],),
            )
            refs.touch_file(conn, row["ref"])
            library.touch_ref_holders(conn, row["ref"])
            removed += 1
    return removed


class LibraryLinker:
    """Runs [link_library] soon after the server starts and then every [every_s]; [poke] asks for a pass sooner (a person added music)."""

    def __init__(
        self,
        db: Database,
        navidrome: Library,
        *,
        first_after_s: float = 20.0,
        every_s: float = 3600.0,
        before: Callable[[], object] | None = None,
    ) -> None:
        self._db = db
        self._navidrome = navidrome
        self._before = before
        self._first = first_after_s
        self._every = every_s
        self._stop = threading.Event()
        self._soon = threading.Event()
        self._thread: threading.Thread | None = None
        self.last: LinkReport | None = None

    def run_once(self) -> LinkReport:
        if self._before is not None:
            try:
                self._before()
            except Exception:  # noqa: BLE001 - a side errand must not stop the link; it is tried again next time
                log.exception("the errand before the library link failed")
        self.last = link_library(self._db, self._navidrome)
        if self.last.linked or self.last.pruned:
            log.info(
                "library linked: %d songs seen, %d new refs, %d files pruned",
                self.last.seen,
                self.last.new_refs,
                self.last.pruned,
            )
        return self.last

    def poke(self) -> None:
        self._soon.set()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="library-link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._soon.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        wait = self._first
        while not self._stop.is_set():
            self._soon.wait(timeout=wait)
            self._soon.clear()
            if self._stop.is_set():
                return
            try:
                report = self.run_once()
                wait = self._every if report.complete else min(self._every, 120.0)
            except Exception:  # noqa: BLE001 - the loop must survive a hiccup; it is logged and tried again
                log.exception("the library link failed")
                wait = min(self._every, 300.0)
