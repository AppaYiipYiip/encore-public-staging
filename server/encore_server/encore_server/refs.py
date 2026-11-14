"""Song refs: one per real-world recording, shared by everybody on the server (docs/04 section 3, docs/19 section 2).

A ref exists the moment anyone sees a song (search, import, recommendation). It is the identity used for likes, playlists, queues,
playback state and history. Finding the ref a described song already has is the heart of "one copy, many people": ISRC, then the
catalogue and video ids, then the normalised artist + title (and which version it is), with the length within 3 seconds.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

from . import missing
from .errors import ApiError
from .ids import new_id, now_ms
from .keeper.covers import cover_url_ok
from .textnorm import norm_artist, norm_title, version_signature

#: Two recordings with the same normalised name are the same song when their lengths differ by no more than this.
DURATION_TOLERANCE_MS = 3000

_TEXT_LIMIT = 300
_MAX_ARTISTS = 20

#: The album the music server lists a file under when its tags name none. It says "no album", so it is never copied onto a ref that has a real one
#: or none (N-11: the doubled songs showed under "[unknown album]").
_PLACEHOLDER_ALBUM = re.compile(r"^\[?\s*unknown album\s*\]?$", re.IGNORECASE)


def is_placeholder_album(value: object) -> bool:
    """Whether an album is no album: nothing, blank, or the music server's `[Unknown Album]`."""
    return not isinstance(value, str) or not value.strip() or _PLACEHOLDER_ALBUM.match(value.strip()) is not None


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
        # A picture the SOURCE gave this song (an import's YouTube thumbnail): shown only while there is no real cover (P1-26).
        "thumb_url": _cover(raw.get("thumbnailUrl")),
        "explicit": 1 if raw.get("explicit") is True else 0,
    }


def video_thumbnail(video_id: object) -> str | None:
    """YouTube's thumbnail of a video: `mqdefault` is 320x180 with no black bars for ANY kind of upload (`hqdefault` is 480x360 and keeps bars
    on top and bottom of a widescreen video), and the app's cover crop (`BoxFit.cover`) keeps the middle square (for a song's own "Topic" upload,
    the art). Soft on a big album header, but never a bar and never a letter.
    Served only when a song has no other picture (P1-26): the 321 songs of the test server that have a video and no cover were letter tiles."""
    vid = _video_id(video_id)
    return f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else None


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
    ref: dict[str, Any] = {
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
        # The real cover wins; then the thumbnail the source gave the song; then, as the last resort, YouTube's own thumbnail of the video the song
        # plays from (derived, never stored: the cover finder still sees a song whose `cover_url` is empty and replaces all of these).
        "coverUrl": row["cover_url"] or row["thumb_url"] or video_thumbnail(row["ytm_video_id"]),
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
    # A song the server already knows it cannot get (N-13): only while the memory is believed, and never for a song the server has a file of (it plays).
    # Absent, not null, when there is none: an app from before this field reads nothing new, and the new app treats it as optional.
    unavailable = missing.public(missing.standing_of(row, now_ms())) if file_row is None else None
    if unavailable is not None:
        ref["unavailable"] = unavailable
    return ref


#: The longest chain of merges followed. The repair keeps `ref_merge.into_id` pointing at a live ref, so one hop is the norm; this only stops a damaged
#: table (a loop) from looping.
_MAX_HOPS = 16
#: How many ids one query asks about (SQLite's limit on the numbers in one statement is lower on older builds).
_ID_CHUNK = 400


def _merged_into(conn: sqlite3.Connection, ref_ids: Iterable[str]) -> dict[str, str]:
    """`{old id: the ref that took its place}` for those of these ids that were merged away."""
    wanted = list(dict.fromkeys(ref_ids))
    found: dict[str, str] = {}
    for start in range(0, len(wanted), _ID_CHUNK):
        chunk = wanted[start : start + _ID_CHUNK]
        marks = ",".join("?" * len(chunk))
        for row in conn.execute(f"SELECT old_id, into_id FROM ref_merge WHERE old_id IN ({marks})", chunk):  # noqa: S608 - placeholders only
            found[row["old_id"]] = row["into_id"]
    return found


def canonical_many(conn: sqlite3.Connection, ref_ids: Iterable[str]) -> dict[str, str]:
    """`{id: the id to use now}` for each of these song ids. A ref that was merged into another (N-11) no longer exists, but a client may still name
    it (an old app, an edit queued offline, a signed address handed out before the repair): its answer is the ref that took its place. An id that was
    never merged answers itself, so a made-up id still fails where it always did."""
    answer = {ref_id: ref_id for ref_id in ref_ids}
    for _ in range(_MAX_HOPS):
        step = _merged_into(conn, set(answer.values()))
        if not step:
            break
        answer = {asked: step.get(now, now) for asked, now in answer.items()}
    return answer


def canonical(conn: sqlite3.Connection, ref_id: str) -> str:
    """The id to use now for one song id (see [canonical_many]). Every place that takes a song id from a client calls this first."""
    return canonical_many(conn, [ref_id])[ref_id]


def get_ref(conn: sqlite3.Connection, ref_id: str) -> dict[str, Any]:
    """The song's ref. An id that was merged into another answers with the survivor (its `id` says which one)."""
    row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (canonical(conn, ref_id),)).fetchone()
    if row is None:
        raise ApiError("not_found", "That song is not known to this server.")
    return row_to_ref(conn, row)


def ref_exists(conn: sqlite3.Connection, ref_id: str) -> bool:
    return conn.execute("SELECT 1 FROM song_ref WHERE id = ?", (ref_id,)).fetchone() is not None


def _compatible(row: sqlite3.Row, duration_ms: int | None) -> bool:
    known = row["duration_ms"]
    return known is None or duration_ms is None or abs(known - duration_ms) <= DURATION_TOLERANCE_MS


def _survivor(conn: sqlite3.Connection, into_id: str) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (canonical(conn, into_id),)).fetchone()
    return row  # type: ignore[no-any-return]


def _find_merged(conn: sqlite3.Connection, column: str, value: str) -> sqlite3.Row | None:
    """The survivor of a ref that was merged away and had this id."""
    for row in conn.execute(f"SELECT into_id FROM ref_merge WHERE {column} = ? ORDER BY seq DESC", (value,)):  # noqa: S608 - fixed column names
        survivor = _survivor(conn, row["into_id"])
        if survivor is not None:
            return survivor
    return None


def find(conn: sqlite3.Connection, item: dict[str, Any]) -> sqlite3.Row | None:
    """The ref a described song already has, or `None`.

    A ref that was merged into another (N-11) is still found, as the survivor: the same song described the way the deleted ref was (the music server's
    tags list the artists as one string and the length a few seconds off) must not make the duplicate again. The order is the strength of the
    evidence: the ids of live refs, the ids of merged ones, then the artist + title + length of live refs, then of merged ones."""
    ids = (("isrc", item["isrc"]), ("deezer_id", item["deezer_id"]), ("ytm_video_id", item["ytm_video_id"]))
    for column, value in ids:
        if value:
            row = conn.execute(f"SELECT * FROM song_ref WHERE {column} = ?", (value,)).fetchone()  # noqa: S608 - fixed column names
            if row is not None:
                return row  # type: ignore[no-any-return]
    for column, value in ids:
        if value:
            merged = _find_merged(conn, column, value)
            if merged is not None:
                return merged
    key = norm_key(item["artists"][0], item["title"])
    for row in conn.execute("SELECT * FROM song_ref WHERE norm_key = ? ORDER BY created_at", (key,)):
        if _compatible(row, item["duration_ms"]):
            return row  # type: ignore[no-any-return]
    # The length is compared with the DELETED ref's own (kept in `ref_merge`), not with the survivor's, which may be seconds off.
    for gone in conn.execute("SELECT into_id, duration_ms FROM ref_merge WHERE norm_key = ? ORDER BY seq", (key,)):
        if _compatible(gone, item["duration_ms"]):
            survivor = _survivor(conn, gone["into_id"])
            if survivor is not None:
                return survivor
    return None


def _enrich(conn: sqlite3.Connection, row: sqlite3.Row, item: dict[str, Any]) -> sqlite3.Row:
    """What the ref lacked and this description knows is added (an id another ref already owns is never taken from it)."""
    updates: dict[str, Any] = {}
    for column in ("album", "album_artist", "track_no", "disc_no", "year", "duration_ms", "mbid", "cover_url", "thumb_url"):
        if row[column] is None and item[column] is not None:
            if column == "album" and is_placeholder_album(item[column]):
                continue  # "[Unknown Album]" says there is no album: a ref without one stays without (N-11)
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
    if "ytm_video_id" in updates:
        clear_missing(conn, row["id"])  # somebody knows an upload of this song: what was remembered about its absence is void
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
            " ytm_video_id, cover_url, thumb_url, explicit, norm_key, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                item["thumb_url"],
                item["explicit"],
                norm_key(item["artists"][0], item["title"]),
                now_ms(),
            ),
        )
        row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref_id,)).fetchone()
    else:
        row = _enrich(conn, row, item)
    return row_to_ref(conn, row)


def remember_video(conn: sqlite3.Connection, ref_id: str, video_id: str, *, replacing: str | None = None) -> bool:
    """A play found the upload of this song: the next play needs no search. An upload another ref already owns is never taken from it.

    With [replacing] (N-13) the ref's own upload turned out to be gone and a search found another: that dead id is replaced, and only that one. The dead
    id stays in the column until a live one replaces it, on purpose: a phone's description of an imported song carries the same dead id, and writing it
    into an empty column would void what the server remembers about the song."""
    cursor = conn.execute(
        "UPDATE song_ref SET ytm_video_id = ? WHERE id = ? AND (ytm_video_id IS NULL OR ytm_video_id = ?)"
        " AND NOT EXISTS (SELECT 1 FROM song_ref WHERE ytm_video_id = ?)",
        (video_id, ref_id, replacing, video_id),
    )
    if cursor.rowcount:
        clear_missing(conn, ref_id)  # an upload was found: the song is not missing
    return bool(cursor.rowcount)


_MISSING_COLUMNS = "missing_reason, missing_at, missing_tried_at, missing_rev"


def remember_missing(conn: sqlite3.Connection, ref_id: str, reason: str, *, now: int | None = None) -> None:
    """The source ANSWERED no about this song (N-13, `missing.py`): remembered for a window. `missing_at` is when it was first learned and stays across
    later tries; `missing_tried_at` is this try. **The files feed is not told**: it is the phone's index of what the server KEEPS, a ref that has no file
    is not its business (300 songs of an import that were not found would be 300 rows to write and retire on every phone), and the phone reads the mark
    from the ref it resolves and from `POST refs/unavailable`."""
    if reason not in missing.REASONS:
        raise ValueError(f"not a reason a song is missing: {reason!r}")
    at = now_ms() if now is None else now
    conn.execute(
        "UPDATE song_ref SET missing_reason = ?, missing_at = COALESCE(missing_at, ?), missing_tried_at = ?, missing_rev = ? WHERE id = ?",
        (reason, at, at, missing.MATCHER_REVISION, ref_id),
    )


def clear_missing(conn: sqlite3.Connection, ref_id: str) -> bool:
    """The song was found (an upload, a file): what was remembered about its absence is void."""
    cursor = conn.execute(
        "UPDATE song_ref SET missing_reason = NULL, missing_at = NULL, missing_tried_at = NULL, missing_rev = NULL"
        " WHERE id = ? AND missing_reason IS NOT NULL",
        (ref_id,),
    )
    return bool(cursor.rowcount)


def _verdict_of(conn: sqlite3.Connection, row: sqlite3.Row | None, at: int) -> dict[str, Any] | None:
    """What this ref remembers about being impossible to get, as the API shows it (`missing.public`): `None` for no row, a song the server keeps (it has a
    file: it plays, whatever an old memory says) and a memory that is no longer believed."""
    if row is None or conn.execute("SELECT 1 FROM song_file WHERE ref = ? LIMIT 1", (row["id"],)).fetchone() is not None:
        return None
    return missing.public(missing.standing_of(row, at))


def unavailable_for(
    conn: sqlite3.Connection, raw_songs: Sequence[object], *, now: int | None = None
) -> list[dict[str, Any] | None]:
    """For each described song, in order: what the server remembers about it being impossible to get (`missing.public`), or `None`. A read: no ref is made
    for a song the server has not seen, and a song the server keeps (it has a file) is never unavailable. A description that cannot be read answers
    `None`, as one that matches nothing does: the question is about songs, not about the asker's mistakes."""
    at = now_ms() if now is None else now
    answers: list[dict[str, Any] | None] = []
    for raw in raw_songs:
        try:
            row = find(conn, parse_item(raw))
        except ApiError:
            answers.append(None)
            continue
        answers.append(_verdict_of(conn, row, at))
    return answers


def unavailable_for_ids(
    conn: sqlite3.Connection, raw_ids: Sequence[object], *, now: int | None = None
) -> list[dict[str, Any] | None]:
    """The same answer for songs the asker names by ref id: the rows of a phone's own library are refs, so it has the exact identity and needs no
    description of the song (B-128: a library row, a playlist entry, a liked song). An id that was merged into another (N-11) answers for the survivor,
    as every route that takes a song id from a client does; an id that is not one, or that no ref has, answers `None`. A read, like [unavailable_for]."""
    at = now_ms() if now is None else now
    texts = [raw for raw in raw_ids if isinstance(raw, str)]
    live = canonical_many(conn, texts)
    answers: list[dict[str, Any] | None] = []
    for raw in raw_ids:
        row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (live[raw],)).fetchone() if isinstance(raw, str) else None
        answers.append(_verdict_of(conn, row, at))
    return answers


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
    clear_missing(conn, ref_id)  # the server has a file of this song now: whatever was remembered about its absence is void
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
