"""Imports (docs/tasks P2-04): a pasted link or a file of songs becomes a playlist of song refs in the time it takes to read the list.

The request does only what is quick: read the list, give every song a ref (the video the source named is attached when it *is* the song),
make the playlist, remember the import. Finding each song's upload (`match`, priority 3) and keeping a copy (`keep`, priority 4) are
background work, fair-shared with everybody else's. The counts a person sees come from the `import` rows and nowhere else.
"""

from __future__ import annotations

import importlib.util
import logging
import shutil
import sqlite3
from collections.abc import Callable
from typing import Any, Protocol

from .. import library, refs
from ..db import Database
from ..errors import ApiError
from ..ids import is_id, new_id, now_ms
from ..keeper.triggers import want_kept
from ..live import Hub
from ..scheduler import Retry, Scheduler, WorkItem
from ..sources.youtube.errors import DownloadError
from ..sources.youtube.source import Wanted, wanted_from_ref
from .readers import Playlist, PlaylistError, Track, read_playlist, ytdlp_reader, ytmusic_reader

log = logging.getLogger("encore_server.imports")

#: A file of songs the app parsed is cut here (a person's whole history can be long; the link readers have their own limit).
MAX_SONGS = 5000
_SOURCES = ("youtube", "spotify", "file")
_REST = {"blocked": 900.0, "timeout": 300.0, "slow": 300.0}


class Finder(Protocol):
    def find(self, wanted: Wanted) -> str | None: ...

    def resting_for(self) -> float: ...


def _song_of(track: Track) -> dict[str, Any]:
    """A track the readers found, described the way `refs.resolve` wants it. The video is attached to the ref only when it *is* the song
    (YouTube's own audio upload); any other upload is kept aside and used when the song cannot be found by its name."""
    return {
        "title": track.title,
        "artists": list(track.artists) or ([track.artist] if track.artist else []),
        "album": track.album,
        "durationMs": track.duration_s * 1000 if track.duration_s else None,
        "videoId": track.video_id if track.official else None,
    }


def default_reader() -> Callable[[str], Playlist]:
    """Reads playlist links the way this machine can: YouTube Music's own interface when `ytmusicapi` is installed, `yt-dlp` as the fallback."""
    ytmusic = ytmusic_reader() if importlib.util.find_spec("ytmusicapi") is not None else None
    ytdlp = ytdlp_reader() if shutil.which("yt-dlp") is not None else None
    if ytmusic is None and ytdlp is None:
        log.warning("neither ytmusicapi nor yt-dlp is installed: YouTube playlist links cannot be read")

    def read(url: str) -> Playlist:
        return read_playlist(url, ytmusic=ytmusic, ytdlp=ytdlp)

    return read


def _picture(body: dict[str, Any]) -> str | None:
    """A file import may name a picture for its playlist (an https address on a host the readers allow)."""
    from .readers import _cover_ok

    return _cover_ok(body.get("cover"))


class ImportService:
    def __init__(
        self,
        db: Database,
        hub: Hub,
        finder: Finder | None,
        *,
        read: Callable[[str], Playlist] | None = None,
    ) -> None:
        self._db = db
        self._hub = hub
        self._scheduler: Scheduler | None = None
        self._finder = finder
        self._read = read if read is not None else default_reader()

    def use(self, scheduler: Scheduler | None) -> None:
        """The scheduler that runs this service's matching (made after the service, because it needs the service's handler)."""
        self._scheduler = scheduler

    # ------------------------------------------------------------------ the request

    def create(self, person: str, body: dict[str, Any]) -> dict[str, Any]:
        import_id = body.get("id")
        if import_id is not None and not is_id(import_id, "im"):
            raise ApiError("validation", "An import id looks like im_ followed by 26 characters.")
        liked = body.get("liked") is True
        playlist_id = None if liked else body.get("playlistId") or new_id("pl")
        if playlist_id is not None and not is_id(playlist_id, "pl"):
            raise ApiError("validation", "A playlist id looks like pl_ followed by 26 characters.")
        if import_id is not None:
            with self._db.read() as conn:
                again = self._record(conn, person, str(import_id))
            if again is not None:
                return {"import": again, "playlistId": again["playlistId"]}

        source, url, name, songs, extra, truncated, cover = self._what(body)
        import_id = import_id or new_id("im")
        with self._db.tx() as conn:
            made = [refs.resolve(conn, song) for song in songs]
            now = now_ms()
            if liked:
                # Every song is liked and no playlist is made; the first of the list is the newest like, so Liked Songs reads the way the list did.
                for position, ref in enumerate(made):
                    library.set_item(conn, person, "like", ref["id"], at=now - position * 1000)
            else:
                assert playlist_id is not None
                library.create_playlist(conn, person, playlist_id, name, cover)
                for start in range(0, len(made), library.MAX_ENTRIES_PER_CALL):
                    chunk = made[start : start + library.MAX_ENTRIES_PER_CALL]
                    library.add_entries(conn, person, playlist_id, [{"ref": r["id"]} for r in chunk])
            conn.execute(
                "INSERT INTO import (id, person, source, url, name, playlist, truncated, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (import_id, person, source, url, name, playlist_id, 1 if truncated else 0, now, now),
            )
            for position, (ref, raw) in enumerate(zip(made, extra, strict=True)):
                state = self._first_state(ref)
                conn.execute(
                    "INSERT INTO import_entry (import, position, ref, state, video) VALUES (?,?,?,?,?)",
                    (import_id, position, ref["id"], state, raw),
                )
            pending = [
                row["ref"]
                for row in conn.execute(
                    "SELECT DISTINCT ref FROM import_entry WHERE import = ? AND state = 'pending'", (import_id,)
                )
            ]
            for ref_id in pending:
                if self._scheduler is not None and self._finder is not None:
                    self._scheduler.submit("match", ref_id, person, conn=conn)
            if self._finder is None:
                conn.execute("UPDATE import_entry SET state = 'not_found' WHERE import = ? AND state = 'pending'", (import_id,))
            want_kept(self._scheduler, conn, person, [r["id"] for r in made])
            self._settle(conn, str(import_id))
            record = self._record(conn, person, str(import_id))
            playlist = (
                None
                if playlist_id is None
                else library.playlist_json(
                    conn, conn.execute("SELECT * FROM playlist WHERE id = ?", (playlist_id,)).fetchone(), with_entries=True
                )
            )
            cursor = library.latest_cursor(conn, person)
        self._hub.publish(person, {"type": "library.changed", "cursor": str(cursor)})
        return {"import": record, "playlistId": playlist_id, "playlist": playlist, "refs": made, "cursor": str(cursor)}

    def _what(
        self, body: dict[str, Any]
    ) -> tuple[str, str | None, str, list[dict[str, Any]], list[str | None], bool, str | None]:
        """(source, url, name, the songs, each song's own video if any, cut, the picture the source gave the list)."""
        url = body.get("url")
        songs = body.get("songs")
        if isinstance(url, str) and url.strip():
            try:
                playlist = self._read(url.strip())
            except PlaylistError as error:
                code = {"unreachable": "source_unreachable", "not_found": "not_found"}.get(error.code, "validation")
                raise ApiError(code, error.message, details={"reason": error.code}) from error
            name = str(body.get("name") or playlist.name).strip() or playlist.name
            return (
                playlist.source,
                url.strip(),
                name,
                [_song_of(t) for t in playlist.tracks],
                [None if t.official else t.video_id for t in playlist.tracks],
                playlist.truncated,
                playlist.cover_url,
            )
        if isinstance(songs, list) and songs:
            name = str(body.get("name") or "").strip()
            if not name:
                raise ApiError("validation", "A playlist needs a name.")
            source = body.get("source") if body.get("source") in _SOURCES else "file"
            parsed = [refs.parse_item(s) for s in songs[:MAX_SONGS]]
            described = [
                {
                    "title": p["title"],
                    "artists": p["artists"],
                    "album": p["album"],
                    "albumArtist": p["album_artist"],
                    "year": p["year"],
                    "durationMs": p["duration_ms"],
                    "isrc": p["isrc"],
                    "videoId": p["ytm_video_id"],
                    "coverUrl": p["cover_url"],
                }
                for p in parsed
            ]
            return str(source), None, name, described, [None] * len(described), len(songs) > MAX_SONGS, _picture(body)
        raise ApiError("validation", "Send a link (url) or a list of songs (name and songs).")

    @staticmethod
    def _first_state(ref: dict[str, Any]) -> str:
        """A song that already has a copy, or an upload to play it from, needs no matching."""
        return "matched" if ref.get("videoId") or (ref.get("file") or {}).get("navidromeSongId") else "pending"

    # ------------------------------------------------------------------ looking at it

    def get(self, person: str, import_id: str) -> dict[str, Any]:
        with self._db.read() as conn:
            record = self._record(conn, person, import_id)
        if record is None:
            raise ApiError("not_found", "That import does not exist (any more).")
        return record

    def listing(self, person: str) -> list[dict[str, Any]]:
        with self._db.read() as conn:
            ids = [
                r["id"]
                for r in conn.execute("SELECT id FROM import WHERE person = ? ORDER BY created_at DESC LIMIT 50", (person,))
            ]
            return [r for r in (self._record(conn, person, i) for i in ids) if r is not None]

    def entries(self, person: str, import_id: str) -> list[dict[str, Any]]:
        """Each song of the import and where it stands (the app's "Not found" rows and its "Find it" search come from here)."""
        with self._db.read() as conn:
            if self._record(conn, person, import_id) is None:
                raise ApiError("not_found", "That import does not exist (any more).")
            return [
                {"position": r["position"], "ref": r["ref"], "state": r["state"]}
                for r in conn.execute(
                    "SELECT position, ref, state FROM import_entry WHERE import = ? ORDER BY position", (import_id,)
                )
            ]

    @staticmethod
    def _record(conn: sqlite3.Connection, person: str, import_id: str) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM import WHERE id = ? AND person = ?", (import_id, person)).fetchone()
        if row is None:
            return None
        counts = {
            r["state"]: r["n"]
            for r in conn.execute("SELECT state, COUNT(*) AS n FROM import_entry WHERE import = ? GROUP BY state", (import_id,))
        }
        kept = conn.execute(
            "SELECT COUNT(*) FROM import_entry e WHERE e.import = ? AND EXISTS"
            " (SELECT 1 FROM song_file f WHERE f.ref = e.ref AND f.navidrome_song_id IS NOT NULL)",
            (import_id,),
        ).fetchone()[0]
        return {
            "id": row["id"],
            "source": row["source"],
            "name": row["name"],
            "state": row["state"],
            "playlistId": row["playlist"],
            "total": sum(counts.values()),
            "matched": counts.get("matched", 0),
            "unmatched": counts.get("not_found", 0),
            "pending": counts.get("pending", 0),
            "kept": kept,
            "truncated": bool(row["truncated"]),
            "createdAt": row["created_at"],
        }

    # ------------------------------------------------------------------ Stop

    def stop(self, person: str, import_id: str) -> dict[str, Any]:
        with self._db.tx() as conn:
            row = conn.execute("SELECT state FROM import WHERE id = ? AND person = ?", (import_id, person)).fetchone()
            if row is None:
                raise ApiError("not_found", "That import does not exist (any more).")
            refs_of = [r["ref"] for r in conn.execute("SELECT DISTINCT ref FROM import_entry WHERE import = ?", (import_id,))]
            if row["state"] == "running":
                conn.execute("UPDATE import SET state = 'stopped', updated_at = ? WHERE id = ?", (now_ms(), import_id))
        if self._scheduler is not None:
            self._scheduler.cancel_refs(person, refs_of, kinds=("match", "keep"))
        record = self.get(person, import_id)
        self._publish(person, record)
        return record

    # ------------------------------------------------------------------ the background work

    def match(self, item: WorkItem) -> None:
        """Finds the upload of one song for everybody who imported it. The song stays playable by name whatever this finds."""
        if self._finder is None:
            return
        resting = self._finder.resting_for()
        if resting > 0:
            raise Retry("YouTube is being given a rest", after_s=resting)
        with self._db.read() as conn:
            ref = refs.get_ref(conn, item.ref)
            rows = conn.execute(
                "SELECT e.import AS import, e.position AS position, e.video AS video FROM import_entry e JOIN import i ON i.id = e.import"
                " WHERE e.ref = ? AND e.state = 'pending' AND i.state = 'running'",
                (item.ref,),
            ).fetchall()
        if not rows:
            return
        video = ref.get("videoId")
        if video is None and not (ref.get("file") or {}).get("navidromeSongId"):
            try:
                video = self._finder.find(wanted_from_ref(ref))
            except DownloadError as error:
                if error.code in _REST:
                    raise Retry(
                        f"YouTube is not answering ({error.code})", after_s=max(_REST[error.code], self._finder.resting_for())
                    ) from error
                video = None
            if video is None:
                video = next((r["video"] for r in rows if r["video"]), None)
                if video is not None:
                    with self._db.tx() as conn:
                        refs.remember_video(conn, item.ref, str(video))
        found = video is not None or bool((ref.get("file") or {}).get("navidromeSongId"))
        persons: dict[str, str] = {}
        with self._db.tx() as conn:
            for row in rows:
                conn.execute(
                    "UPDATE import_entry SET state = ? WHERE import = ? AND position = ? AND state = 'pending'",
                    ("matched" if found else "not_found", row["import"], row["position"]),
                )
                persons[row["import"]] = conn.execute("SELECT person FROM import WHERE id = ?", (row["import"],)).fetchone()[
                    "person"
                ]
            for import_id in persons:
                self._settle(conn, import_id)
        for import_id, person in persons.items():
            record = self.get(person, import_id)
            self._publish(person, record)

    @staticmethod
    def _settle(conn: sqlite3.Connection, import_id: str) -> None:
        """An import is done when no song of it waits to be matched."""
        waiting = conn.execute(
            "SELECT 1 FROM import_entry WHERE import = ? AND state = 'pending' LIMIT 1", (import_id,)
        ).fetchone()
        if waiting is None:
            conn.execute(
                "UPDATE import SET state = 'done', updated_at = ? WHERE id = ? AND state = 'running'", (now_ms(), import_id)
            )

    def _publish(self, person: str, record: dict[str, Any]) -> None:
        self._hub.publish(
            person,
            {
                "type": "import.progress",
                "importId": record["id"],
                "state": record["state"],
                **{k: record[k] for k in ("total", "matched", "unmatched", "pending", "kept")},
            },
        )
