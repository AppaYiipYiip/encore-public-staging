"""Song refs: one per real-world recording, shared by everybody on the server (docs/04 section 3, docs/19 section 2).

A ref exists the moment anyone sees a song (search, import, recommendation). It is the identity used for likes, playlists, queues,
playback state and history. Finding the ref a described song already has is the heart of "one copy, many people": ISRC, then the
catalogue and video ids, then the normalised artist + title (and which version it is), with the length within 3 seconds.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from typing import Any

from .errors import ApiError
from .ids import new_id, now_ms
from .keeper.covers import cover_url_ok
from .textnorm import norm_artist, norm_title, version_signature

#: Two recordings with the same normalised name are the same song when their lengths differ by no more than this.
DURATION_TOLERANCE_MS = 3000

_TEXT_LIMIT = 300
_MAX_ARTISTS = 20


def norm_key(artist: str, title: str) -> str:
    """The artist and the title as people would compare them, and *which version it is*: "Fade Into You" and
    "Fade Into You (The Avener Rework)" are two songs even though only a bracket tells them apart."""
    version = " ".join(sorted(version_signature(title)))
    return f"{norm_artist(artist)}|{norm_title(title)}|{version}"


def _clean(value: object, limit: int = _TEXT_LIMIT) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:limit] if text else None


def _int(value: object, lo: int, hi: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    return number if lo <= number <= hi else None


def parse_item(raw: object) -> dict[str, Any]:
    """What a client may send to describe a song; raises `validation` for what cannot be a song at all."""
    if not isinstance(raw, dict):
        raise ApiError("validation", "A song needs a title and an artist.")
    title = _clean(raw.get("title"))
    artists_raw = raw.get("artists")
    artists = [a for a in (_clean(x, 200) for x in (artists_raw if isinstance(artists_raw, list) else [])) if a][:_MAX_ARTISTS]
    if not artists and _clean(raw.get("artist"), 200):
        artists = [_clean(raw.get("artist"), 200) or ""]
    if title is None or not artists:
        raise ApiError("validation", "A song needs a title and an artist.")
    return {
        "title": title,
        "artists": artists,
        "album": _clean(raw.get("album")),
        "album_artist": _clean(raw.get("albumArtist"), 200),
        "track_no": _int(raw.get("trackNo"), 1, 999),
        "disc_no": _int(raw.get("discNo"), 1, 99),
        "year": _int(raw.get("year"), 1900, 2100),
        "duration_ms": _int(raw.get("durationMs"), 1000, 24 * 3600 * 1000),
        "isrc": (_clean(raw.get("isrc"), 20) or "").replace("-", "").upper() or None,
        "mbid": _clean(raw.get("mbid"), 40),
        "deezer_id": _clean(str(raw["deezerId"]), 30) if raw.get("deezerId") is not None else None,
        "ytm_video_id": _video_id(raw.get("videoId")),
        "cover_url": _cover(raw.get("coverUrl")),
        "explicit": 1 if raw.get("explicit") is True else 0,
    }


def _video_id(value: object) -> str | None:
    text = _clean(value, 11)
    return text if text is not None and len(text) == 11 and all(c.isalnum() or c in "-_" for c in text) else None


def _cover(value: object) -> str | None:
    """A picture address a phone describes a song with: kept only from the hosts the keeper itself fetches pictures from. Every phone that shows
    the song loads this address, so "any https address" let a member pick the host every phone asks (AUDIT B6)."""
    text = _clean(value, 500)
    return text if text is not None and cover_url_ok(text) and "@" not in text.split("/", 3)[2] else None


def row_to_ref(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """The API's shape of a ref, with the server's copy of the song when there is one."""
    file_row = conn.execute(
        "SELECT id, navidrome_song_id, codec, bitrate_kbps, meta FROM song_file WHERE ref = ? ORDER BY preferred DESC, added_at DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    return {
        "id": row["id"],
        "title": row["title"],
        "artists": json.loads(row["artists"]),
        "album": row["album"],
        "albumArtist": row["album_artist"],
        "trackNo": row["track_no"],
        "discNo": row["disc_no"],
        "year": row["year"],
        "durationMs": row["duration_ms"],
        "isrc": row["isrc"],
        "mbid": row["mbid"],
        "deezerId": row["deezer_id"],
        "videoId": row["ytm_video_id"],
        "coverUrl": row["cover_url"],
        "explicit": bool(row["explicit"]),
        "file": None
        if file_row is None
        else {
            "id": file_row["id"],
            "navidromeSongId": file_row["navidrome_song_id"],
            "codec": file_row["codec"],
            "bitrateKbps": file_row["bitrate_kbps"],
            "meta": json.loads(file_row["meta"]) if file_row["meta"] else {},
        },
    }


def get_ref(conn: sqlite3.Connection, ref_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref_id,)).fetchone()
    if row is None:
        raise ApiError("not_found", "That song is not known to this server.")
    return row_to_ref(conn, row)


def ref_exists(conn: sqlite3.Connection, ref_id: str) -> bool:
    return conn.execute("SELECT 1 FROM song_ref WHERE id = ?", (ref_id,)).fetchone() is not None


def _compatible(row: sqlite3.Row, duration_ms: int | None) -> bool:
    known = row["duration_ms"]
    return known is None or duration_ms is None or abs(known - duration_ms) <= DURATION_TOLERANCE_MS


def find(conn: sqlite3.Connection, item: dict[str, Any]) -> sqlite3.Row | None:
    """The ref a described song already has, or `None`."""
    for column, value in (("isrc", item["isrc"]), ("deezer_id", item["deezer_id"]), ("ytm_video_id", item["ytm_video_id"])):
        if value:
            row = conn.execute(f"SELECT * FROM song_ref WHERE {column} = ?", (value,)).fetchone()  # noqa: S608 - fixed column names
            if row is not None:
                return row  # type: ignore[no-any-return]
    key = norm_key(item["artists"][0], item["title"])
    for row in conn.execute("SELECT * FROM song_ref WHERE norm_key = ? ORDER BY created_at", (key,)):
        if _compatible(row, item["duration_ms"]):
            return row  # type: ignore[no-any-return]
    return None


def _enrich(conn: sqlite3.Connection, row: sqlite3.Row, item: dict[str, Any]) -> sqlite3.Row:
    """What the ref lacked and this description knows is added (an id another ref already owns is never taken from it)."""
    updates: dict[str, Any] = {}
    for column in ("album", "album_artist", "track_no", "disc_no", "year", "duration_ms", "mbid", "cover_url"):
        if row[column] is None and item[column] is not None:
            updates[column] = item[column]
    for column in ("isrc", "deezer_id", "ytm_video_id"):
        value = item[column]
        if value and row[column] is None:
            taken = conn.execute(f"SELECT 1 FROM song_ref WHERE {column} = ?", (value,)).fetchone()  # noqa: S608 - fixed column names
            if taken is None:
                updates[column] = value
    if item["explicit"] and not row["explicit"]:
        updates["explicit"] = 1
    if not updates:
        return row
    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn.execute(f"UPDATE song_ref SET {assignments} WHERE id = ?", (*updates.values(), row["id"]))  # noqa: S608 - fixed column names
    return conn.execute("SELECT * FROM song_ref WHERE id = ?", (row["id"],)).fetchone()  # type: ignore[no-any-return]


def resolve(conn: sqlite3.Connection, raw: object) -> dict[str, Any]:
    """Finds or makes the ref for a described song; the same song described twice (or by two people) is one ref."""
    item = parse_item(raw)
    row = find(conn, item)
    if row is None:
        ref_id = new_id("sr")
        for column in ("isrc", "deezer_id", "ytm_video_id"):
            # A description that carries an id some other ref owns has been matched above; this only guards a race.
            if item[column] and conn.execute(f"SELECT 1 FROM song_ref WHERE {column} = ?", (item[column],)).fetchone():  # noqa: S608
                item[column] = None
        conn.execute(
            "INSERT INTO song_ref (id, title, artists, album, album_artist, track_no, disc_no, year, duration_ms, isrc, mbid, deezer_id,"
            " ytm_video_id, cover_url, explicit, norm_key, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ref_id,
                item["title"],
                json.dumps(item["artists"], ensure_ascii=False),
                item["album"],
                item["album_artist"],
                item["track_no"],
                item["disc_no"],
                item["year"],
                item["duration_ms"],
                item["isrc"],
                item["mbid"],
                item["deezer_id"],
                item["ytm_video_id"],
                item["cover_url"],
                item["explicit"],
                norm_key(item["artists"][0], item["title"]),
                now_ms(),
            ),
        )
        row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref_id,)).fetchone()
    else:
        row = _enrich(conn, row, item)
    return row_to_ref(conn, row)


def remember_video(conn: sqlite3.Connection, ref_id: str, video_id: str) -> bool:
    """A play found the upload of this song: the next play needs no search. An upload another ref already owns is never taken from it."""
    cursor = conn.execute(
        "UPDATE song_ref SET ytm_video_id = ? WHERE id = ? AND ytm_video_id IS NULL"
        " AND NOT EXISTS (SELECT 1 FROM song_ref WHERE ytm_video_id = ?)",
        (video_id, ref_id, video_id),
    )
    return bool(cursor.rowcount)


#: How many music-server ids one query asks about (SQLite's limit on the numbers in one statement is lower on older builds).
_ID_CHUNK = 400


def file_holders(conn: sqlite3.Connection, song_ids: Sequence[str]) -> dict[str, sqlite3.Row]:
    """The row of `song_file` that holds each of these ids of the music server, whichever ref it is attached to. A file belongs to ONE ref, and
    the row says which: it was attached on purpose (the keeper saved it for that ref), so it is more reliable than what the file's tags say.
    An id several refs hold (what the scan made before N-11) answers with the oldest row, the one that was attached first.

    Only the id is used, never the path: the music server lists a file at a path it builds from the tags (`JAY-Z/[Unknown Album]/Empire State Of
    Mind.opus`), the keeper saved it at its own (`Encore/JAY-Z/Singles/Empire State Of Mind.opus`), so the two never compare equal (N-11)."""
    holders: dict[str, sqlite3.Row] = {}
    wanted = [i for i in dict.fromkeys(song_ids) if i]
    for start in range(0, len(wanted), _ID_CHUNK):
        chunk = wanted[start : start + _ID_CHUNK]
        marks = ",".join("?" * len(chunk))
        for row in conn.execute(
            f"SELECT id, ref, navidrome_song_id, path FROM song_file WHERE navidrome_song_id IN ({marks}) ORDER BY added_at, rowid",  # noqa: S608
            chunk,
        ):
            holders.setdefault(row["navidrome_song_id"], row)
    return holders


def touch_file(conn: sqlite3.Connection, ref_id: str) -> int:
    """The song's file changed: the feed of the server's files (`GET /library/files`) will say so."""
    cursor = conn.execute("INSERT INTO file_log (ref, at) VALUES (?, ?)", (ref_id, now_ms()))
    return int(cursor.lastrowid or 0)


def attach_file(
    conn: sqlite3.Connection,
    ref_id: str,
    *,
    navidrome_song_id: str | None,
    path: str | None,
    codec: str | None,
    bitrate_kbps: int | None,
    source: str = "library",
    meta: dict[str, Any] | None = None,
) -> str:
    """The server has (or now keeps) a copy of this song. Replacing a file changes only this: likes and playlists never move.
    Attaching what is already attached changes nothing (and writes nothing to the feed), so a scan can run as often as it likes."""
    if not ref_exists(conn, ref_id):
        raise ApiError("not_found", "That song is not known to this server.")
    meta_json = json.dumps(meta, separators=(",", ":"), sort_keys=True) if meta else None
    existing = conn.execute(
        "SELECT id, navidrome_song_id, path, codec, bitrate_kbps, meta FROM song_file WHERE ref = ?"
        " AND ((navidrome_song_id IS NOT NULL AND navidrome_song_id = ?) OR (path IS NOT NULL AND path = ?))",
        (ref_id, navidrome_song_id, path),
    ).fetchone()
    if existing is not None:
        merged = (
            navidrome_song_id or existing["navidrome_song_id"],
            existing["path"] or path,
            codec or existing["codec"],
            bitrate_kbps if bitrate_kbps is not None else existing["bitrate_kbps"],
            meta_json or existing["meta"],
        )
        if merged != (
            existing["navidrome_song_id"],
            existing["path"],
            existing["codec"],
            existing["bitrate_kbps"],
            existing["meta"],
        ):
            conn.execute(
                "UPDATE song_file SET navidrome_song_id = ?, path = ?, codec = ?, bitrate_kbps = ?, meta = ? WHERE id = ?",
                (*merged, existing["id"]),
            )
            touch_file(conn, ref_id)
        return str(existing["id"])
    file_id = new_id("sf")
    conn.execute("UPDATE song_file SET preferred = 0 WHERE ref = ?", (ref_id,))
    conn.execute(
        "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, bitrate_kbps, source, preferred, added_at, meta)"
        " VALUES (?,?,?,?,?,?,?,1,?,?)",
        (file_id, ref_id, navidrome_song_id, path, codec, bitrate_kbps, source, now_ms(), meta_json),
    )
    touch_file(conn, ref_id)
    return file_id
