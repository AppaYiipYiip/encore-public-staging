"""The catalogue as this server serves it: what a phone asks (a search, an artist page, an album page, a genre), made of cached, single-flighted,
budgeted outside requests, and mapped to ONE shape of ours (P2-12 slice 1, docs/11 ADR-R47, docs/17 section 3).

**Where it sits.** `deezer.py` holds the gate (the rate, the order, the rest) and the one client that asks through it; this module is the layer ABOVE it
that only the routes use. The cover finder and the artist finder do NOT go through the cache: a stale "nothing there" served during an outage would let
them write a week-long miss, which is audit B-124 back again (they ask through the gate, at background priority, and nothing else).

**The cache** is a file of its own, `catalogue-cache.db` (never `encore.db`: it is not backed up, it can be deleted any time, its writes never queue
behind the library's). The unit is the OUTSIDE request, so a search of three kinds or an artist page of three parts is assembled from cached parts and a
part that could not be asked is simply missing from the answer, named in `unavailable`: **a catalogue that could not be asked is never stored** (B-124).
Keys are hashes (no typed text, no person); what is stored is the outside answer cut down to the fields we map (so a change of OUR shape never voids it).
An answer is believed for: a search 15 minutes, an artist or its popular songs 24 hours, its releases 6 hours, an album and its songs 7 days, a genre's
chart 6 hours, an empty answer (and a thing that is not there) 5 minutes. When the catalogue cannot be asked, an answer up to 30 days old that holds something
is served instead; an empty one never is.

**Single flight**: two people asking the same thing at once cause ONE outside request (the second waits for the first's answer).

**Shapes** (the contract, docs/17): an artist `{id, name, picture, fans, albumCount}`, an album `{id, title, artists, cover, trackCount, year,
releaseDate, recordType}`, a song `{id, title, artists, album, cover, durationMs, isrc, trackNo, discNo, description}` where `description` is the
object `POST refs/resolve` takes, made here and nowhere else (it carries `isrc` and `deezerId` and never a `videoId`: B-86). Ids are Deezer's, as text.
A picture field is never an address at api.deezer.com (those redirect and tell Deezer who asked), and never the silhouette Deezer gives an artist
without a picture: it is `None` then. No read here makes a ref, a row or a file.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from .deezer import (
    PLACEHOLDER_ARTIST_PICTURE,
    Budget,
    DeezerClient,
    LookupUnavailable,
    NotInCatalogue,
)

log = logging.getLogger("encore_server.catalogue")

# ------------------------------------------------------------------------------------------------------------------ the numbers

#: How long an answer is believed, by kind of outside request (seconds).
TTL_S = {
    "search": 15 * 60,
    "artist": 24 * 3600,
    "top": 24 * 3600,
    "releases": 6 * 3600,
    "album": 7 * 24 * 3600,
    "album-tracks": 7 * 24 * 3600,
    "chart": 6 * 3600,
}
#: A valid empty answer, and a thing that is not there: both are facts, both may stop being true within minutes (a release the catalogue lists late).
EMPTY_TTL_S = 5 * 60
#: When the catalogue cannot be asked, an answer this old is still better than none.
STALE_LIMIT_S = 30 * 24 * 3600
#: What one call of a phone may take in all (docs/17 section 7: search 3 s; the phone's own limit for these calls is 4 s).
CALL_TIMEOUT_S = 2.5
#: The most outside requests one call may make.
CEILING = {"search": 7, "artist": 3, "album": 2, "genre": 3}

ARTIST_SEARCH_LIMIT = 8
POPULAR_LIMIT = 10
RELEASES_LIMIT = 200
ALBUM_TRACKS_LIMIT = 100
CHART_LIMITS = {"tracks": 25, "artists": 15, "albums": 15}

KINDS = ("artists", "albums", "tracks")

#: The catalogue's genres (Deezer's ids), with English names: the catalogue names them in the language of its caller's country. The phone's own
#: list (`kCatalogueGenres`) moves here (slice 2): a server is one place to change it.
GENRES: tuple[tuple[int, str], ...] = (
    (132, "Pop"),
    (116, "Rap / Hip Hop"),
    (152, "Rock"),
    (113, "Dance"),
    (165, "R&B"),
    (85, "Alternative"),
    (106, "Electro"),
    (464, "Metal"),
    (129, "Jazz"),
    (98, "Classical"),
    (169, "Soul & Funk"),
    (153, "Blues"),
    (466, "Folk"),
    (144, "Reggae"),
    (197, "Latin"),
    (2, "African music"),
    (12, "Arabic music"),
    (16, "Asian music"),
    (75, "Brazilian music"),
    (81, "Indian music"),
    (52, "French chanson"),
    (173, "Films & games"),
    (95, "Kids"),
)

# ------------------------------------------------------------------------------------------------------------------ the cache file


class Entry(NamedTuple):
    body: Any
    stored_at: float
    expires_at: float
    #: A remembered "there is no such thing" (a fact), not an answer.
    absent: bool


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS answer ("
    " key TEXT PRIMARY KEY, kind TEXT NOT NULL, stored_at REAL NOT NULL, expires_at REAL NOT NULL,"
    " absent INTEGER NOT NULL DEFAULT 0, body TEXT NOT NULL, size INTEGER NOT NULL)"
)


def cache_key(kind: str, path: str, params: dict[str, Any]) -> str:
    """The hash an outside request is remembered under: its kind, path and sorted parameters. Nothing typed, nobody's id and no readable text is in it."""
    material = "\n".join([kind, path, *(f"{k}={params[k]}" for k in sorted(params))])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class Cache:
    """`catalogue-cache.db`: answers by key, in a file of its own. Thread-safe. It never raises: a file that cannot be opened is replaced by an empty
    one, and a place where no file can be made is no cache at all (every look-up then asks the catalogue, which is only slower)."""

    def __init__(self, path: Path | None, *, max_entries: int = 20_000, max_bytes: int = 50_000_000) -> None:
        self.path = path
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._inserts = 0
        if path is not None:
            self._open(path)

    def _connect(self, path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(_SCHEMA)
            conn.execute("SELECT COUNT(*) FROM answer").fetchone()  # a damaged file fails here and not at the first answer
        except sqlite3.Error:
            conn.close()
            raise
        return conn

    def _open(self, path: Path) -> None:
        try:
            self._conn = self._connect(path)
            return
        except (sqlite3.Error, OSError) as error:
            log.warning(
                "the catalogue cache %s could not be opened (%s); it is replaced by an empty one", path.name, type(error).__name__
            )
        for name in (path.name, path.name + "-wal", path.name + "-shm"):
            with contextlib.suppress(OSError):
                (path.parent / name).unlink(missing_ok=True)
        try:
            self._conn = self._connect(path)
        except (sqlite3.Error, OSError) as error:
            log.warning(
                "no catalogue cache can be made at %s (%s); every look-up asks the catalogue", path.name, type(error).__name__
            )
            self._conn = None

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                with contextlib.suppress(sqlite3.Error):
                    self._conn.close()
                self._conn = None

    def get(self, key: str) -> Entry | None:
        with self._lock:
            if self._conn is None:
                return None
            try:
                row = self._conn.execute(
                    "SELECT body, stored_at, expires_at, absent FROM answer WHERE key = ?", (key,)
                ).fetchone()
            except sqlite3.Error:
                log.debug("the catalogue cache could not be read", exc_info=True)
                return None
        if row is None:
            return None
        try:
            return Entry(json.loads(row[0]), row[1], row[2], bool(row[3]))
        except ValueError:
            return None

    def put(self, key: str, kind: str, body: Any, *, now: float, ttl_s: float, absent: bool = False) -> None:
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            if self._conn is None:
                return
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO answer (key, kind, stored_at, expires_at, absent, body, size) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (key, kind, now, now + ttl_s, 1 if absent else 0, text, len(text)),
                )
            except sqlite3.Error:
                log.debug("the catalogue cache could not be written", exc_info=True)
                return
            self._inserts += 1
            if self._inserts % 1000 == 0:
                self.prune(now)

    def count(self) -> int:
        with self._lock:
            if self._conn is None:
                return 0
            try:
                return int(self._conn.execute("SELECT COUNT(*) FROM answer").fetchone()[0])
            except sqlite3.Error:
                return 0

    def prune(self, now: float) -> None:
        """What is too old to be served even stale goes, then the oldest until the entries and the bytes are within their limits."""
        with self._lock:
            if self._conn is None:
                return
            try:
                self._conn.execute("DELETE FROM answer WHERE stored_at < ?", (now - STALE_LIMIT_S,))
                excess = self.count() - self._max_entries
                if excess > 0:
                    self._conn.execute(
                        "DELETE FROM answer WHERE key IN (SELECT key FROM answer ORDER BY stored_at ASC LIMIT ?)", (excess,)
                    )
                while True:
                    total, rows = self._conn.execute("SELECT COALESCE(SUM(size), 0), COUNT(*) FROM answer").fetchone()
                    if total <= self._max_bytes or rows == 0:
                        break
                    self._conn.execute(
                        "DELETE FROM answer WHERE key IN (SELECT key FROM answer ORDER BY stored_at ASC LIMIT ?)",
                        (max(1, rows // 10),),
                    )
            except sqlite3.Error:
                log.debug("the catalogue cache could not be pruned", exc_info=True)


# ------------------------------------------------------------------------------------------------------------------ mapping: Deezer's rows to ours


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _number(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _picture(row: dict[str, Any], *fields: str) -> str | None:
    """The first of [fields] that is a real picture: not the plain `picture` / `cover` field (an address at api.deezer.com that redirects and tells
    Deezer who asked), not the silhouette of an artist without a picture."""
    for field in fields:
        value = _text(row.get(field))
        if value and "api.deezer.com" not in value and PLACEHOLDER_ARTIST_PICTURE not in value:
            return value
    return None


def _id(value: object) -> str | None:
    return str(value) if isinstance(value, (int, str)) and not isinstance(value, bool) and str(value) else None


def _credit(row: object) -> dict[str, str] | None:
    if not isinstance(row, dict):
        return None
    ident, name = _id(row.get("id")), _text(row.get("name"))
    return {"id": ident, "name": name} if ident and name else None


def map_artist(row: object) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    ident, name = _id(row.get("id")), _text(row.get("name"))
    if ident is None or name is None:
        return None
    return {
        "id": ident,
        "name": name,
        "picture": _picture(row, "picture_xl", "picture_big"),
        "fans": _number(row.get("nb_fan")),
        "albumCount": _number(row.get("nb_album")),
    }


def map_album(row: object, fallback_artist: dict[str, str] | None = None) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    ident, title = _id(row.get("id")), _text(row.get("title"))
    if ident is None or title is None:
        return None
    credit = _credit(row.get("artist")) or fallback_artist
    date = _text(row.get("release_date"))
    return {
        "id": ident,
        "title": title,
        "artists": [credit] if credit else [],
        "cover": _picture(row, "cover_xl", "cover_big"),
        "trackCount": _number(row.get("nb_tracks")),
        "year": int(date[:4]) if date and re.fullmatch(r"\d{4}(-\d\d-\d\d)?", date) else None,
        "releaseDate": date,
        "recordType": _text(row.get("record_type")),
    }


def map_track(row: object, album: dict[str, Any] | None = None, *, album_artist: str | None = None) -> dict[str, Any] | None:
    """A song. [album] is the album object of the page the song was listed on, for the rows that come without one (an album's own song list)."""
    if not isinstance(row, dict):
        return None
    ident, title = _id(row.get("id")), _text(row.get("title"))
    if ident is None or title is None:
        return None
    credit = _credit(row.get("artist"))
    on: dict[str, Any] = row["album"] if isinstance(row.get("album"), dict) else {}
    album_id = _id(on.get("id")) or (album["id"] if album else None)
    album_title = _text(on.get("title")) or (album["title"] if album else None)
    cover = _picture(on, "cover_xl", "cover_big") or (album["cover"] if album else None)
    seconds = _number(row.get("duration"))
    duration = seconds * 1000 if seconds else None
    isrc = (_text(row.get("isrc")) or "").replace("-", "").upper() or None
    track_no, disc_no = _number(row.get("track_position")), _number(row.get("disk_number"))
    year = album["year"] if album else None
    song = {
        "id": ident,
        "title": title,
        "artists": [credit] if credit else [],
        "album": {"id": album_id, "title": album_title} if album_id and album_title else None,
        "cover": cover,
        "durationMs": duration,
        "isrc": isrc,
        "trackNo": track_no,
        "discNo": disc_no,
    }
    song["description"] = describe(song, album_artist=album_artist, year=year)
    return song


def describe(song: dict[str, Any], *, album_artist: str | None = None, year: int | None = None) -> dict[str, Any]:
    """The object `POST refs/resolve` takes for this song: the one description function (the phone no longer builds it). It carries `isrc` and
    `deezerId` and never a `videoId` (B-86: a video id a client names must not override the title and artist)."""
    names = [credit["name"] for credit in song["artists"]]
    wanted: dict[str, Any] = {
        "title": song["title"],
        "artists": names,
        "album": song["album"]["title"] if song["album"] else None,
        "albumArtist": album_artist,
        "trackNo": song["trackNo"],
        "discNo": song["discNo"],
        "year": year,
        "durationMs": song["durationMs"],
        "isrc": song["isrc"],
        "deezerId": song["id"],
        "coverUrl": song["cover"],
    }
    return {key: value for key, value in wanted.items() if value is not None}


# ------------------------------------------------------------------------------------------------------------------ what is kept of an outside answer


def _keep(row: object, *fields: str) -> dict[str, Any]:
    return {field: row[field] for field in fields if isinstance(row, dict) and field in row}


def trim_artist(row: object) -> dict[str, Any]:
    return _keep(row, "id", "name", "picture_xl", "picture_big", "nb_fan", "nb_album")


def trim_album(row: object) -> dict[str, Any]:
    kept = _keep(row, "id", "title", "cover_xl", "cover_big", "nb_tracks", "release_date", "record_type")
    if isinstance(row, dict) and isinstance(row.get("artist"), dict):
        kept["artist"] = _keep(row["artist"], "id", "name")
    return kept


def trim_track(row: object) -> dict[str, Any]:
    kept = _keep(row, "id", "title", "duration", "isrc", "track_position", "disk_number")
    if isinstance(row, dict):
        if isinstance(row.get("artist"), dict):
            kept["artist"] = _keep(row["artist"], "id", "name")
        if isinstance(row.get("album"), dict):
            kept["album"] = _keep(row["album"], "id", "title", "cover_xl", "cover_big")
    return kept


def _listing(trim: Callable[[object], dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def cut(body: dict[str, Any]) -> dict[str, Any]:
        data = body.get("data")
        return {"data": [trim(row) for row in data if isinstance(row, dict)] if isinstance(data, list) else []}

    return cut


def _is_empty(body: Any) -> bool:
    return isinstance(body, dict) and isinstance(body.get("data"), list) and not body["data"]


# ------------------------------------------------------------------------------------------------------------------ releases: editions folded

#: The phone's own folding of a title for "is it the same release" (`app/lib/domain/text_match.dart`, `normalizeForMatch`), ported letter for letter so
#: a list of releases folds as it did on the phone. It keeps every script (`\p{L}`, `\p{N}`): an Arabic or a Russian title is not folded to nothing
#: (B-37 is the server's `textnorm`, which this does NOT use), and a title that folds to nothing is never merged with another.
_FOLD = {
    **{c: "a" for c in "àáâãäåā"},
    **{c: "c" for c in "çćč"},
    **{c: "e" for c in "èéêëēęě"},
    **{c: "i" for c in "ìíîïī"},
    **{c: "n" for c in "ñńň"},
    **{c: "o" for c in "òóôõöøō"},
    **{c: "u" for c in "ùúûüūů"},
    **{c: "y" for c in "ýÿ"},
    **{c: "s" for c in "šś"},
    "ß": "ss",
    **{c: "z" for c in "žźż"},
    "ł": "l",
    "đ": "d",
    "ð": "d",
    "þ": "th",
    "æ": "ae",
    "œ": "oe",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
}
_EDITION_SUFFIX = re.compile(
    r"\s*[(\[]?\s*(?:\d{4}\s+)?(?:remaster(?:ed)?(?: (?:version|edition))?|"
    r"deluxe(?: edition)?|"
    r"expanded(?: edition)?|bonus tracks?|anniversary(?: edition)?|"
    r"special edition|standard edition|digital edition|"
    r"album version|single version|explicit(?: version)?|clean version)"
    r"(?:\s+\d{4})?\s*[)\]]?\s*$",
    re.IGNORECASE,
)


def release_key(title: str) -> str:
    """What two titles must share to be one release: no case, no edition suffix ("Deluxe Edition", "Remastered 2011"), the accents of the listed
    letters, no punctuation, no leading "the". Empty when the title holds no letter or digit at all (the caller never merges on an empty key)."""
    text = title.strip().lower()
    previous = None
    while previous != text:
        previous = text
        text = _EDITION_SUFFIX.sub("", text, count=1)
    text = "".join(_FOLD.get(ch, ch) for ch in text).replace("&", " and ")
    text = "".join(ch if unicodedata.category(ch)[0] in "LN" or ch.isspace() else " " for ch in text)
    text = " ".join(text.split())
    return text[4:] if text.startswith("the ") else text


def fold_releases(albums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Releases newest first, with the editions of one release (the explicit and the clean, the deluxe, the remaster) folded into the newest one."""
    newest_first = sorted(
        albums, key=lambda album: album.get("releaseDate") or (str(album["year"]) if album.get("year") else ""), reverse=True
    )
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for album in newest_first:
        key = release_key(album["title"])
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        kept.append(album)
    return kept


# ------------------------------------------------------------------------------------------------------------------ the service


class _Flight:
    """One outside request on its way: the people who asked for the same thing wait on it."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.body: Any = None
        self.error: BaseException | None = None
        #: The leader could not even ask (it was refused by the rate limit): whoever waited asks for itself.
        self.abandoned = False


class Gathered(NamedTuple):
    found: dict[str, Any]
    missing: set[str]
    unavailable: list[str]


class Catalogue:
    """What the routes ask. Every method returns the body of its answer (without `serverTime`); [LookupUnavailable] when nothing at all could be asked,
    [NotInCatalogue] when the thing asked for does not exist; `unavailable` names the parts that could not be asked when the others could."""

    def __init__(
        self,
        client: DeezerClient,
        cache: Cache | None = None,
        *,
        clock: Callable[[], float] = time.time,
        workers: int = 6,
    ) -> None:
        self.client = client
        self.cache = cache
        self._clock = clock
        self._flights: dict[str, _Flight] = {}
        self._flights_lock = threading.Lock()
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="catalogue")

    @property
    def enabled(self) -> bool:
        return self.client.gate.enabled

    def state(self) -> dict[str, Any]:
        return self.client.gate.state()

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        if self.cache is not None:
            self.cache.close()
        self.client.close()

    # ------------------------------------------------------------------ one outside request: cache, single flight, budget

    def _fetch(
        self,
        kind: str,
        path: str,
        params: dict[str, Any],
        trim: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        budget: Budget,
        charge: Callable[[], object] | None,
    ) -> dict[str, Any]:
        key = cache_key(kind, path, params)
        while True:
            now = self._clock()
            entry = self.cache.get(key) if self.cache is not None else None
            if entry is not None and entry.expires_at > now:
                if entry.absent:
                    raise NotInCatalogue(path)
                return entry.body  # type: ignore[no-any-return]
            with self._flights_lock:
                flight = self._flights.get(key)
                leader = flight is None
                if flight is None:
                    flight = self._flights[key] = _Flight()
            if not leader:
                flight.done.wait(timeout=2 * CALL_TIMEOUT_S)
                if flight.abandoned:
                    continue
                if flight.error is not None:
                    raise flight.error
                if not flight.done.is_set():
                    raise LookupUnavailable("the answer did not come in time")
                return flight.body  # type: ignore[no-any-return]
            return self._lead(flight, key, kind, path, params, trim, budget, charge, entry, now)

    def _lead(
        self,
        flight: _Flight,
        key: str,
        kind: str,
        path: str,
        params: dict[str, Any],
        trim: Callable[[dict[str, Any]], dict[str, Any]],
        budget: Budget,
        charge: Callable[[], object] | None,
        old: Entry | None,
        now: float,
    ) -> dict[str, Any]:
        try:
            if charge is not None:
                charge()
            body = trim(self.client.get(path, params, priority="interactive", budget=budget))
        except NotInCatalogue as error:
            if self.cache is not None:
                self.cache.put(key, kind, {}, now=now, ttl_s=EMPTY_TTL_S, absent=True)
            flight.error = error
            raise
        except LookupUnavailable as error:
            # Not stored, whatever happens (B-124). A stale answer that holds something is better than none.
            if old is not None and not old.absent and now - old.stored_at <= STALE_LIMIT_S and not _is_empty(old.body):
                flight.body = old.body
                return old.body  # type: ignore[no-any-return]
            flight.error = error
            raise
        except BaseException:
            flight.abandoned = True  # the rate limit said no, or something broke: those who waited ask for themselves
            raise
        else:
            if self.cache is not None:
                self.cache.put(key, kind, body, now=now, ttl_s=EMPTY_TTL_S if _is_empty(body) else TTL_S[kind])
            flight.body = body
            return body
        finally:
            with self._flights_lock:
                self._flights.pop(key, None)
            flight.done.set()

    # ------------------------------------------------------------------ parts of one call, asked together

    def _gather(self, jobs: dict[str, Callable[[], Any]], *, within: float | None = None) -> Gathered:
        """Runs the parts of a call at once, waiting at most [within] seconds in all. A part that could not be asked, or did not come in time, is in
        `unavailable` (it goes on and fills the cache when it comes); a part that is not there is in `missing`. Anything else that went wrong is raised."""
        futures = {name: self._pool.submit(job) for name, job in jobs.items()}
        concurrent.futures.wait(futures.values(), timeout=CALL_TIMEOUT_S if within is None else within)
        found: dict[str, Any] = {}
        missing: set[str] = set()
        unavailable: list[str] = []
        for name, future in futures.items():
            if not future.done():
                future.cancel()  # one that has not started is not wanted any more; one that has goes on and fills the cache when it comes
                unavailable.append(name)
                continue
            try:
                found[name] = future.result()
            except NotInCatalogue:
                missing.add(name)
            except LookupUnavailable:
                unavailable.append(name)
        return Gathered(found, missing, unavailable)

    def _listing(
        self,
        kind: str,
        path: str,
        params: dict[str, Any],
        trim: Callable[[object], dict[str, Any]],
        budget: Budget,
        charge: Callable[[], object] | None,
    ) -> list[dict[str, Any]]:
        body = self._fetch(kind, path, params, _listing(trim), budget=budget, charge=charge)
        return [row for row in body.get("data", []) if isinstance(row, dict)]

    # ------------------------------------------------------------------ what the routes ask

    def search(
        self, query: str, types: tuple[str, ...], limit: int, *, charge: Callable[[], object] | None = None
    ) -> dict[str, Any]:
        """`{query, artists, albums, tracks, unavailable?}`: the kinds asked for. At most 7 outside requests (3 now: one per kind)."""
        budget = Budget(CEILING["search"])
        asks: dict[str, tuple[str, dict[str, Any], Callable[[object], dict[str, Any]]]] = {
            "artists": ("/search/artist", {"q": query, "limit": ARTIST_SEARCH_LIMIT}, trim_artist),
            "albums": ("/search/album", {"q": query, "limit": limit}, trim_album),
            "tracks": ("/search/track", {"q": query, "limit": limit}, trim_track),
        }

        def part(kind: str) -> Callable[[], Any]:
            path, params, trim = asks[kind]
            return lambda: self._listing("search", path, params, trim, budget, charge)

        jobs = {kind: part(kind) for kind in KINDS if kind in types}
        got = self._gather(jobs)
        if not got.found and got.unavailable:
            raise LookupUnavailable("the catalogue could not be asked")
        mapping = {"artists": map_artist, "albums": map_album, "tracks": map_track}
        answer: dict[str, Any] = {"query": query}
        for kind in KINDS:
            if kind in types:
                rows = got.found.get(kind, [])
                answer[kind] = [item for item in (mapping[kind](row) for row in rows) if item is not None]
        if got.unavailable:
            answer["unavailable"] = [kind for kind in KINDS if kind in got.unavailable]
        return answer

    def artist_page(
        self, artist_id: str, parts: tuple[str, ...], *, charge: Callable[[], object] | None = None
    ) -> dict[str, Any]:
        """`{artist, popular?, releases?, unavailable?}`: who the artist is, and (by [parts]) its ten most popular songs and what it released, newest
        first with the editions folded. At most 3 outside requests."""
        budget = Budget(CEILING["artist"])

        def identity() -> dict[str, Any]:
            return self._fetch("artist", f"/artist/{artist_id}", {}, lambda body: trim_artist(body), budget=budget, charge=charge)

        jobs: dict[str, Callable[[], Any]] = {"artist": identity}
        if "popular" in parts:
            jobs["popular"] = lambda: self._listing(
                "top", f"/artist/{artist_id}/top", {"limit": POPULAR_LIMIT}, trim_track, budget, charge
            )
        if "releases" in parts:
            jobs["releases"] = lambda: self._listing(
                "releases", f"/artist/{artist_id}/albums", {"limit": RELEASES_LIMIT}, trim_album, budget, charge
            )
        got = self._gather(jobs)
        if "artist" in got.missing:
            raise NotInCatalogue(artist_id)
        artist = map_artist(got.found.get("artist"))
        if artist is None:
            raise LookupUnavailable("the artist could not be asked")
        answer: dict[str, Any] = {"artist": artist}
        credit = {"id": artist["id"], "name": artist["name"]}
        if "popular" in parts:
            answer["popular"] = [t for t in (map_track(row) for row in got.found.get("popular", [])) if t is not None]
        if "releases" in parts:
            albums = [a for a in (map_album(row, credit) for row in got.found.get("releases", [])) if a is not None]
            answer["releases"] = fold_releases(albums)
        if got.unavailable:
            answer["unavailable"] = [name for name in ("popular", "releases") if name in got.unavailable]
        return answer

    def album(self, album_id: str, *, charge: Callable[[], object] | None = None) -> dict[str, Any]:
        """`{album, tracks, unavailable?}`: the album, then its songs (a missing album asks for no songs). At most 2 outside requests."""
        budget = Budget(CEILING["album"])
        started = time.monotonic()
        first = self._gather(
            {
                "album": lambda: self._fetch(
                    "album", f"/album/{album_id}", {}, lambda body: trim_album(body), budget=budget, charge=charge
                )
            }
        )
        if first.missing:
            raise NotInCatalogue(album_id)
        album = map_album(first.found.get("album"))
        if album is None:
            raise LookupUnavailable("the album could not be asked")
        second = self._gather(
            {
                "tracks": lambda: self._listing(
                    "album-tracks", f"/album/{album_id}/tracks", {"limit": ALBUM_TRACKS_LIMIT}, trim_track, budget, charge
                )
            },
            within=max(0.1, CALL_TIMEOUT_S - (time.monotonic() - started)),
        )
        lead = album["artists"][0]["name"] if album["artists"] else None
        rows = second.found.get("tracks", [])
        answer: dict[str, Any] = {
            "album": album,
            "tracks": [t for t in (map_track(row, album, album_artist=lead) for row in rows) if t is not None],
        }
        if second.unavailable:
            answer["unavailable"] = ["tracks"]
        return answer

    @staticmethod
    def genres() -> dict[str, Any]:
        """The genre list: no outside request."""
        return {"genres": [{"id": str(ident), "name": name} for ident, name in GENRES]}

    def genre(self, genre_id: str, *, charge: Callable[[], object] | None = None) -> dict[str, Any]:
        """`{tracks, artists, albums, unavailable?}`: what is on top in one genre. At most 3 outside requests."""
        budget = Budget(CEILING["genre"])
        trims: dict[str, Callable[[object], dict[str, Any]]] = {
            "tracks": trim_track,
            "artists": trim_artist,
            "albums": trim_album,
        }

        def part(kind: str) -> Callable[[], Any]:
            return lambda: self._listing(
                "chart", f"/chart/{genre_id}/{kind}", {"limit": CHART_LIMITS[kind]}, trims[kind], budget, charge
            )

        jobs = {kind: part(kind) for kind in ("tracks", "artists", "albums")}
        got = self._gather(jobs)
        if not got.found and got.unavailable:
            raise LookupUnavailable("the catalogue could not be asked")
        mapping = {"tracks": map_track, "artists": map_artist, "albums": map_album}
        answer: dict[str, Any] = {
            kind: [item for item in (mapping[kind](row) for row in got.found.get(kind, [])) if item is not None]
            for kind in ("tracks", "artists", "albums")
        }
        if got.unavailable:
            answer["unavailable"] = [kind for kind in ("tracks", "artists", "albums") if kind in got.unavailable]
        return answer
