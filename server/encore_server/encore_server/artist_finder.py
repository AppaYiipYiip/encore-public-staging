"""Pictures for the artists the music server found none for (N-15).

**Why they have none** (proved on a real server, audit B-123): the music server's only keyless source of an artist's picture is the catalogue's
search *by name*, and it takes the answer only when the catalogue's name is the same name. "Bob Marley" is listed there as "Bob Marley & The
Wailers", "Jay-Z" as "JAY Z", "Goo Goo Dolls" as "The Goo Goo Dolls", and a namesake with the very same spelling and no picture of its own
outranks the real artist. About one artist in ten has no picture, famous ones included, and the music server remembers that for good.

**What this does.** An artist is known by one of its own songs, not by its name: the catalogue is asked about a song the server holds ("Bob Marley",
"Could You Be Loved"), a hit counts only when its title is that song and its artist is the artist (or leads the credit: "Bob Marley & The
Wailers"), and the picture of *that* artist is written as `artist.jpg` in the artist's own folder (the one the keeper keeps its albums in) inside the server's own `Encore/` folder, which is
the music server's second source of an artist picture. So a Host's own upload or picture file still wins, every player of the music server sees it, it
survives a rebuild of the music server's database, and no phone changes: the picture arrives as the artist's `coverArt` through the ordinary
pictures route. The Host's own music folders are never written to; an artist whose songs live there is left to the music server (not covered, see
docs/11 ADR-R46).

**Which artists.** Only those the music server lists with no `coverArt`: it leaves the field out only after every one of its own sources has answered
"none" (an artist it is still resolving carries an id), so the list is made of settled misses, not of pictures on their way.

**Pace.** Part of the hourly errands, at most 20 artists a pass, three songs at most per artist, a pause between look-ups; a miss is remembered for a
week, and a catalogue that could not be asked ends the pass and is not remembered as a miss.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from .db import Database
from .deezer import PLACEHOLDER_ARTIST_PICTURE, LookupUnavailable, search_tracks
from .ids import now_ms
from .keeper.covers import cover_url_ok, fetch_cover
from .keeper.keeper import KEPT_FOLDER
from .keeper.placement import artist_folder, inside
from .textnorm import artist_parts, norm_artist, norm_title

log = logging.getLogger("encore_server.artist_finder")

#: How long an artist nothing was found for is left alone.
RETRY_AFTER_MS = 7 * 24 * 3600 * 1000
#: How many of an artist's own songs are tried before giving up on it.
SONGS_PER_ARTIST = 3
#: The picture's file name in the artist's folder: the first of the music server's own names for it (`artist.*`).
PICTURE_FILE = "artist.jpg"
#: What the music server takes for a picture file (its own `IsImageFile`): anything else named `artist.*` is not one.
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})

_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"


class Music(Protocol):
    """What the finder asks of the music server."""

    def artists_without_picture(self) -> list[tuple[str, str]] | None: ...

    def scanning(self) -> bool | None: ...


class ArtistLookup(Protocol):
    def __call__(self, artist: str, title: str, album: str | None) -> str | None:
        """The address of the artist's picture, or `None` (no hit proves who the artist is). Raises [LookupUnavailable] when it could not be asked."""
        ...


@dataclass(frozen=True)
class ArtistPicture:
    url: str
    source_id: str


def _key(name: str) -> str:
    """A name as it is compared: letters and digits only, no case, no leading "the". Names that are not written in Latin letters fold to nothing,
    and nothing is never equal to nothing (the caller refuses an empty key)."""
    folded = norm_artist(name)
    return folded[4:] if folded.startswith("the ") else folded


def pick_artist_picture(hits: list[dict[str, Any]], *, artist: str, title: str) -> ArtistPicture | None:
    """The picture of the artist who made the song [title], among the catalogue's [hits] for it; `None` when no hit proves it.

    A hit counts when its title is the song's, and its artist is [artist] (the same name), or [artist] is the lead name of its credit ("Bob Marley"
    in "Bob Marley & The Wailers"; the second name of a credit is somebody else's picture). The same name wins over a lead name, whatever the order.
    A picture of nobody (the grey silhouette) is dropped before choosing, so a namesake with a real picture is found behind one without."""
    want_title, want_artist = norm_title(title), _key(artist)
    if not want_title or not want_artist:
        return None
    best: tuple[int, ArtistPicture] | None = None
    for hit in hits:
        credited = hit.get("artist")
        if not isinstance(credited, dict) or norm_title(str(hit.get("title", ""))) != want_title:
            continue
        name = str(credited.get("name", ""))
        if _key(name) == want_artist:
            rank = 2
        else:
            parts = artist_parts(name)
            if not parts or _key(parts[0]) != want_artist:
                continue
            rank = 1
        picture = credited.get("picture_xl") or credited.get("picture_big")
        if not isinstance(picture, str) or PLACEHOLDER_ARTIST_PICTURE in picture or not cover_url_ok(picture):
            continue
        if best is None or rank > best[0]:
            best = (rank, ArtistPicture(picture, str(credited.get("id", ""))))
    return best[1] if best else None


def deezer_artist_picture(artist: str, title: str, album: str | None, *, client: httpx.Client | None = None) -> str | None:
    """The address of [artist]'s picture, known by its song [title]; `None` when the catalogue's answer does not prove who the artist is. Raises
    [LookupUnavailable] when the catalogue could not be asked."""
    found = pick_artist_picture(search_tracks(artist, title, client=client), artist=artist, title=title)
    return found.url if found else None


@dataclass
class ArtistReport:
    looked: int = 0
    found: int = 0
    complete: bool = True


class ArtistFinder:
    def __init__(
        self,
        db: Database,
        music: Music,
        lookup: ArtistLookup | None = None,
        *,
        music_dir: Path | None,
        fetch: Callable[[str | None], bytes | None] = fetch_cover,
        after: Callable[[], object] | None = None,
        per_pass: int = 20,
        pause_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], int] = now_ms,
    ) -> None:
        self._db = db
        self._music = music
        # Looked up when the finder is made, not when this module is loaded, so a test can put its own in (B27).
        self._lookup: ArtistLookup = lookup if lookup is not None else deezer_artist_picture
        self._root = music_dir
        self._fetch = fetch
        self._after = after
        self._per_pass = per_pass
        self._pause = pause_s
        self._sleep = sleep
        self._clock = clock

    # ------------------------------------------------------------------ one pass

    def run_once(self) -> ArtistReport:
        report = ArtistReport()
        if self._root is None or self._music.scanning() is not False:
            return report  # no folder of the server's own to write to, or the music server is busy (or silent): its pictures are not settled
        listed = self._music.artists_without_picture()
        if listed is None:
            return report
        now = self._clock()
        due = self._due(listed, now)
        wrote = False
        for artist_id, name in due:
            if report.looked >= self._per_pass:
                report.complete = False
                break
            folder, songs = self._own_songs(name)
            if folder is None or self._has_picture_file(folder):
                continue  # nowhere the server may write, or a picture of the Host's own there: nothing is asked of the catalogue
            report.looked += 1
            try:
                url = self._ask(name, songs)
            except LookupUnavailable as error:
                log.info("the catalogue could not be asked (%s); the pass stops, nothing is remembered", error)
                report.looked -= 1
                report.complete = False
                break
            data = self._fetch(url) if url else None
            written = data is not None and self._write(folder, data)
            self._remember(artist_id, name, now, "found" if written else "none", url)
            self._sleep(self._pause)
            if written:
                wrote = True
                report.found += 1
                log.info("a picture for the artist %s was written into its folder", name)
        if wrote and self._after is not None:
            try:
                self._after()  # the music server learns of the new picture now, not at its next scan
            except Exception:  # noqa: BLE001 - it scans on its own schedule anyway
                log.info("could not ask the music server to scan", exc_info=True)
        return report

    def _due(self, listed: list[tuple[str, str]], now: int) -> list[tuple[str, str]]:
        """The listed artists to look for now: those not asked about within the window, the ones asked about longest ago (never: first) at the front,
        so a pass that stops at its limit goes on with others at the next."""
        with self._db.read() as conn:
            tried = {
                row["artist_id"]: row["tried_at"]
                for row in conn.execute("SELECT artist_id, tried_at FROM artist_picture").fetchall()
            }
        due = [
            (artist_id, name)
            for artist_id, name in listed
            if tried.get(artist_id) is None or now - tried[artist_id] >= RETRY_AFTER_MS
        ]
        due.sort(key=lambda item: tried.get(item[0]) or 0)
        return due

    def _ask(self, name: str, songs: list[tuple[str, str | None]]) -> str | None:
        for index, (title, album) in enumerate(songs):
            if index:
                self._sleep(self._pause)
            url = self._lookup(name, title, album)
            if url:
                return url
        return None

    def _remember(self, artist_id: str, name: str, now: int, outcome: str, url: str | None) -> None:
        with self._db.tx() as conn:
            conn.execute(
                "INSERT INTO artist_picture (artist_id, name, tried_at, outcome, source, source_url) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(artist_id) DO UPDATE SET name = excluded.name, tried_at = excluded.tried_at, outcome = excluded.outcome,"
                " source = excluded.source, source_url = excluded.source_url",
                (artist_id, name, now, outcome, "deezer" if url else None, url),
            )

    # ------------------------------------------------------------------ what the server holds of an artist

    def _own_songs(self, name: str) -> tuple[Path | None, list[tuple[str, str | None]]]:
        """The folder of the server's own that is this artist's (`Encore/<artist>`) and a few of the artist's songs the server holds, or no folder.

        The folder is the one the keeper itself puts the artist's albums in ([artist_folder], the keeper's own rule), and it must be a real folder
        directly inside `Encore/`: a picture can then never land in `Encore/` itself or above it, where the music server would use it for every
        artist that has none. The paths the server has stored for its files are not used: for a file found by a library scan the music server's own
        `path` is made up from the tags, not the real one (found by the integration test)."""
        assert self._root is not None
        kept = self._root / KEPT_FOLDER
        folder = artist_folder(kept, name)
        if (
            folder is None
            or not inside(kept, folder)
            or folder.resolve().parent != kept.resolve()
            or not os.access(folder, os.W_OK)
        ):
            return None, []
        with self._db.read() as conn:
            rows = _own_songs(conn, name)
        songs: list[tuple[str, str | None]] = []
        seen: set[str] = set()
        for row in rows:
            if row["title"] not in seen and len(songs) < SONGS_PER_ARTIST:
                seen.add(row["title"])
                songs.append((str(row["title"]), row["album"]))
        return (folder, songs) if songs else (None, [])

    @staticmethod
    def _has_picture_file(folder: Path) -> bool:
        """An `artist.<picture>` already there (the Host's own, or ours from before): left as it is, whatever its case or type. Only what the music
        server itself takes for a picture counts: our own half-written `artist.jpg.part` (a pass killed between writing and renaming) or an
        `artist.nfo` of some other tool must not hide the artist from the finder for ever."""
        try:
            return any(
                child.is_file() and child.name.lower().startswith("artist.") and child.suffix.lower() in IMAGE_SUFFIXES
                for child in folder.iterdir()
            )
        except OSError:
            return True

    @staticmethod
    def _write(folder: Path, data: bytes) -> bool:
        """The picture, whole or not at all (the music server must never see half a file): only a JPEG or a PNG, written aside and then renamed."""
        if not (data.startswith(_JPEG) or data.startswith(_PNG)):
            return False
        aside = folder / (PICTURE_FILE + ".part")
        try:
            aside.write_bytes(data)
            os.replace(aside, folder / PICTURE_FILE)
        except OSError as error:
            log.info("could not write the picture into %s: %s", folder.name, type(error).__name__)
            aside.unlink(missing_ok=True)
            return False
        return True


def _own_songs(conn: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    """The songs the server holds a file of whose lead artist, or album artist when they say one, is [name]: the songs the music server files under
    this artist (the keeper tags the album artist, and an artist is listed with albums only as an album artist)."""
    return conn.execute(
        "SELECT r.title AS title, r.album AS album FROM song_ref r"
        " WHERE EXISTS (SELECT 1 FROM song_file f WHERE f.ref = r.id)"
        " AND COALESCE(NULLIF(r.album_artist, ''), json_extract(r.artists, '$[0]')) = ?"
        " ORDER BY r.id",
        (name,),
    ).fetchall()
