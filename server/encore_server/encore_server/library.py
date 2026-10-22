"""A person's library: likes, playlists, plays and the change feed (docs/17 sections 3 and 5, docs/18).

Every operation is meaningful on its own and idempotent, so two devices' offline edits merge: adds from both survive, a removed entry
stays removed, a move of a removed entry is dropped, renames are last-writer-wins by arrival. The change log says *what was touched*;
`changes()` reads the current state of those things, so a client that misses an event or asks twice still ends up right.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import refs
from .errors import ApiError
from .ids import is_id, new_id, now_ms

#: Positions are fractional; below this gap between neighbours the playlist is renumbered.
_MIN_GAP = 1e-6

MAX_PLAYLIST_NAME = 200
MAX_ENTRIES_PER_CALL = 500
CHANGES_PAGE = 500


# ----------------------------------------------------------------------------------------------- people


def ensure_person(conn: sqlite3.Connection, navidrome_user: str, *, admin: bool = False) -> sqlite3.Row:
    """The person for a music-server user: made the first time they are seen. The first person on a server, or a music-server
    administrator, is the owner."""
    row = conn.execute("SELECT * FROM person WHERE navidrome_user = ?", (navidrome_user,)).fetchone()
    if row is not None:
        return row  # type: ignore[no-any-return]
    first = conn.execute("SELECT 1 FROM person LIMIT 1").fetchone() is None
    person_id = new_id("pn")
    conn.execute(
        "INSERT INTO person (id, navidrome_user, display_name, role, created_at) VALUES (?,?,?,?,?)",
        (person_id, navidrome_user, navidrome_user, "owner" if first or admin else "member", now_ms()),
    )
    return conn.execute("SELECT * FROM person WHERE id = ?", (person_id,)).fetchone()  # type: ignore[no-any-return]


def _touch(conn: sqlite3.Connection, person: str, kind: str, target: str) -> int:
    cursor = conn.execute("INSERT INTO change_log (person, kind, target, at) VALUES (?,?,?,?)", (person, kind, target, now_ms()))
    return int(cursor.lastrowid or 0)


def latest_cursor(conn: sqlite3.Connection, person: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(seq), 0) AS seq FROM change_log WHERE person = ?", (person,)).fetchone()
    return int(row["seq"])


def touch_ref_holders(conn: sqlite3.Connection, ref_id: str) -> dict[str, int]:
    """The song's file changed (kept, replaced, linked): everybody who has it liked or in a playlist is told it changed, so their
    apps learn the song can now be played from the server's copy. Returns each such person's new cursor."""
    touched: dict[str, int] = {}
    for row in conn.execute("SELECT person FROM library_item WHERE kind = 'like' AND target = ?", (ref_id,)).fetchall():
        touched[row["person"]] = _touch(conn, row["person"], "like", ref_id)
    for row in conn.execute(
        "SELECT e.id AS entry, p.owner AS owner FROM playlist_entry e JOIN playlist p ON p.id = e.playlist"
        " WHERE e.ref = ? AND e.deleted_at IS NULL AND p.deleted_at IS NULL",
        (ref_id,),
    ).fetchall():
        touched[row["owner"]] = _touch(conn, row["owner"], "entry", row["entry"])
    return touched


# ----------------------------------------------------------------------------------------------- likes and the other sets


def set_item(conn: sqlite3.Connection, person: str, kind: str, target: str, *, at: object = None) -> bool:
    """Adds to a person's set (like, saved album, followed artist). `True` when it was not there before.

    [at] is when the person did it, when that is earlier than now (a phone bringing over the likes it already had keeps their order, so Liked
    Songs reads the way it did); anything else is now."""
    if kind == "like" and not refs.ref_exists(conn, target):
        raise ApiError("not_found", "That song is not known to this server.")
    now = now_ms()
    when = at if isinstance(at, int) and not isinstance(at, bool) and 0 < at <= now else now
    cursor = conn.execute(
        "INSERT OR IGNORE INTO library_item (person, kind, target, at) VALUES (?,?,?,?)", (person, kind, target, when)
    )
    if cursor.rowcount:
        _touch(conn, person, kind, target)
        return True
    return False


def clear_item(conn: sqlite3.Connection, person: str, kind: str, target: str) -> bool:
    cursor = conn.execute("DELETE FROM library_item WHERE person = ? AND kind = ? AND target = ?", (person, kind, target))
    if cursor.rowcount:
        _touch(conn, person, kind, target)
        return True
    return False


# ----------------------------------------------------------------------------------------------- playlists


def _clean_name(name: object) -> str:
    text = " ".join(name.split()) if isinstance(name, str) else ""
    if not text:
        raise ApiError("validation", "A playlist needs a name.")
    return text[:MAX_PLAYLIST_NAME]


def _own_playlist(conn: sqlite3.Connection, person: str, playlist_id: str, *, include_deleted: bool = False) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM playlist WHERE id = ?", (playlist_id,)).fetchone()
    if row is None or row["owner"] != person or (row["deleted_at"] is not None and not include_deleted):
        raise ApiError("not_found", "That playlist does not exist (any more).")
    return row  # type: ignore[no-any-return]


def create_playlist(conn: sqlite3.Connection, person: str, playlist_id: str, name: object, cover: object = None) -> sqlite3.Row:
    """Makes a playlist with the id the client chose (so a create that was retried is one playlist)."""
    if not is_id(playlist_id, "pl"):
        raise ApiError("validation", "A playlist id looks like pl_ followed by 26 characters.")
    existing = conn.execute("SELECT * FROM playlist WHERE id = ?", (playlist_id,)).fetchone()
    if existing is not None:
        if existing["owner"] != person:
            raise ApiError("conflict", "That playlist id is taken.")
        return existing  # type: ignore[no-any-return]
    now = now_ms()
    conn.execute(
        "INSERT INTO playlist (id, owner, name, cover, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (playlist_id, person, _clean_name(name), cover if isinstance(cover, str) else None, now, now),
    )
    _touch(conn, person, "playlist", playlist_id)
    return conn.execute("SELECT * FROM playlist WHERE id = ?", (playlist_id,)).fetchone()  # type: ignore[no-any-return]


def patch_playlist(conn: sqlite3.Connection, person: str, playlist_id: str, body: dict[str, Any]) -> sqlite3.Row:
    row = _own_playlist(conn, person, playlist_id)
    name = _clean_name(body["name"]) if "name" in body else row["name"]
    cover = body["cover"] if "cover" in body and (body["cover"] is None or isinstance(body["cover"], str)) else row["cover"]
    conn.execute("UPDATE playlist SET name = ?, cover = ?, updated_at = ? WHERE id = ?", (name, cover, now_ms(), playlist_id))
    _touch(conn, person, "playlist", playlist_id)
    return conn.execute("SELECT * FROM playlist WHERE id = ?", (playlist_id,)).fetchone()  # type: ignore[no-any-return]


def delete_playlist(conn: sqlite3.Connection, person: str, playlist_id: str) -> bool:
    row = conn.execute("SELECT * FROM playlist WHERE id = ?", (playlist_id,)).fetchone()
    if row is None or row["owner"] != person:
        return False  # deleting what is not there is a success: the answer is the same either way
    if row["deleted_at"] is not None:
        return False
    conn.execute("UPDATE playlist SET deleted_at = ?, updated_at = ? WHERE id = ?", (now_ms(), now_ms(), playlist_id))
    _touch(conn, person, "playlist", playlist_id)
    return True


def _entries(conn: sqlite3.Connection, playlist_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM playlist_entry WHERE playlist = ? AND deleted_at IS NULL ORDER BY position, id", (playlist_id,)
        )
    )


def _renumber(conn: sqlite3.Connection, playlist_id: str) -> None:
    for index, row in enumerate(_entries(conn, playlist_id), start=1):
        conn.execute("UPDATE playlist_entry SET position = ? WHERE id = ?", (float(index), row["id"]))


def add_entries(
    conn: sqlite3.Connection, person: str, playlist_id: str, items: list[dict[str, str]], *, after: str | None = None
) -> list[str]:
    """Adds songs ([items]: `{ref, id?}`; the client's own `pe_` ids make a retry harmless) at the end, or after the entry [after].
    Returns the ids of the entries that were added now."""
    _own_playlist(conn, person, playlist_id)
    if not items or len(items) > MAX_ENTRIES_PER_CALL:
        raise ApiError("validation", f"Add between 1 and {MAX_ENTRIES_PER_CALL} songs at a time.")
    for item in items:
        if not refs.ref_exists(conn, item.get("ref", "")):
            raise ApiError("not_found", "A song in that list is not known to this server.", details={"ref": item.get("ref")})
        if "id" in item and not is_id(item["id"], "pe"):
            raise ApiError("validation", "An entry id looks like pe_ followed by 26 characters.")

    current = _entries(conn, playlist_id)
    if after is not None:
        anchor = next((i for i, row in enumerate(current) if row["id"] == after), None)
        if anchor is None:
            after = None  # the entry it was to follow is gone (removed elsewhere): the end is the next best place
    if after is None:
        low = current[-1]["position"] if current else 0.0
        high = None
    else:
        index = next(i for i, row in enumerate(current) if row["id"] == after)
        low = current[index]["position"]
        high = current[index + 1]["position"] if index + 1 < len(current) else None

    added: list[str] = []
    fresh = [
        item for item in items if not conn.execute("SELECT 1 FROM playlist_entry WHERE id = ?", (item.get("id", ""),)).fetchone()
    ]
    count = len(fresh)
    if count and high is not None and (high - low) / (count + 1) < _MIN_GAP:
        _renumber(conn, playlist_id)
        return add_entries(conn, person, playlist_id, items, after=after)
    now = now_ms()
    for offset, item in enumerate(fresh, start=1):
        entry_id = item.get("id") or new_id("pe")
        position = low + offset * ((high - low) / (count + 1)) if high is not None else low + offset
        conn.execute(
            "INSERT INTO playlist_entry (id, playlist, position, ref, added_by, at) VALUES (?,?,?,?,?,?)",
            (entry_id, playlist_id, position, item["ref"], person, now),
        )
        _touch(conn, person, "entry", entry_id)
        added.append(entry_id)
    if added:
        conn.execute("UPDATE playlist SET updated_at = ? WHERE id = ?", (now, playlist_id))
        _touch(conn, person, "playlist", playlist_id)
    return added


def remove_entries(conn: sqlite3.Connection, person: str, playlist_id: str, entry_ids: list[str]) -> list[str]:
    _own_playlist(conn, person, playlist_id)
    removed: list[str] = []
    for entry_id in entry_ids:
        cursor = conn.execute(
            "UPDATE playlist_entry SET deleted_at = ? WHERE id = ? AND playlist = ? AND deleted_at IS NULL",
            (now_ms(), entry_id, playlist_id),
        )
        if cursor.rowcount:
            _touch(conn, person, "entry", entry_id)
            removed.append(entry_id)
    if removed:
        conn.execute("UPDATE playlist SET updated_at = ? WHERE id = ?", (now_ms(), playlist_id))
        _touch(conn, person, "playlist", playlist_id)
    return removed


def reorder(conn: sqlite3.Connection, person: str, playlist_id: str, entry_ids: list[str]) -> None:
    """Puts the listed entries in this order, in the places they occupy now: an entry another device added meanwhile, or one that
    is not listed, stays where it is, and an entry that was removed elsewhere is simply left out."""
    _own_playlist(conn, person, playlist_id)
    live = {row["id"]: row for row in _entries(conn, playlist_id)}
    wanted = [entry_id for entry_id in entry_ids if entry_id in live]
    slots = sorted(live[entry_id]["position"] for entry_id in wanted)
    for entry_id, position in zip(wanted, slots, strict=True):
        if live[entry_id]["position"] != position:
            conn.execute("UPDATE playlist_entry SET position = ? WHERE id = ?", (position, entry_id))
            _touch(conn, person, "entry", entry_id)


def playlist_json(conn: sqlite3.Connection, row: sqlite3.Row, *, with_entries: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "cover": row["cover"],
        "collaborative": bool(row["collaborative"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "deleted": row["deleted_at"] is not None,
    }
    if with_entries:
        out["entries"] = [entry_json(e) for e in _entries(conn, row["id"])]
    return out


def entry_json(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "playlist": row["playlist"],
        "ref": row["ref"],
        "position": row["position"],
        "addedAt": row["at"],
        "deleted": row["deleted_at"] is not None,
    }


def list_playlists(conn: sqlite3.Connection, person: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM playlist WHERE owner = ? AND deleted_at IS NULL ORDER BY created_at", (person,))
    return [playlist_json(conn, row) for row in rows]


def get_playlist(conn: sqlite3.Connection, person: str, playlist_id: str) -> dict[str, Any]:
    return playlist_json(conn, _own_playlist(conn, person, playlist_id), with_entries=True)


# ----------------------------------------------------------------------------------------------- plays


def record_play(
    conn: sqlite3.Connection,
    person: str,
    *,
    play_id: object,
    ref: str,
    at: object,
    ms_played: object,
    device: str | None,
    context: object,
) -> bool:
    """One listening, for history, "recently played", Year in Music and recommendations. A retried report (the same id) is one play."""
    if not isinstance(play_id, str) or not play_id or len(play_id) > 64:
        raise ApiError("validation", "A play needs an id of its own.")
    if not refs.ref_exists(conn, ref):
        raise ApiError("not_found", "That song is not known to this server.")
    played = (
        ms_played
        if isinstance(ms_played, int) and not isinstance(ms_played, bool) and 0 <= ms_played <= 48 * 3600 * 1000
        else None
    )
    if played is None:
        raise ApiError("validation", "How long it was played is missing.")
    stamp = at if isinstance(at, int) and not isinstance(at, bool) and at > 0 else now_ms()
    cursor = conn.execute(
        "INSERT OR IGNORE INTO play_event (id, person, ref, at, ms_played, device, context) VALUES (?,?,?,?,?,?,?)",
        (play_id, person, ref, stamp, played, device, context if isinstance(context, str) else None),
    )
    return bool(cursor.rowcount)


#: A play shorter than this is a skip, not a listen: it does not count towards keeping a song nobody saved.
MIN_COUNTED_PLAY_MS = 30_000


def played_on_days(conn: sqlite3.Connection, ref_id: str) -> int:
    """On how many different days (UTC) the song was really listened to, by anybody: the rule that keeps a song after the second one."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT date(at / 1000, 'unixepoch')) AS days FROM play_event WHERE ref = ? AND ms_played >= ?",
        (ref_id, MIN_COUNTED_PLAY_MS),
    ).fetchone()
    return int(row["days"])


# ----------------------------------------------------------------------------------------------- the server's files


FILES_PAGE = 500


def files_since(conn: sqlite3.Connection, since: int, limit: int = FILES_PAGE) -> dict[str, Any]:
    """The songs whose file changed after cursor [since], as they are now (`file` is null when the server no longer has one). This is the
    app's browse index of what the server keeps: one first pass, then only what changed."""
    rows = conn.execute(
        "SELECT ref, MAX(seq) AS seq FROM file_log WHERE seq > ? GROUP BY ref ORDER BY seq LIMIT ?", (since, limit)
    ).fetchall()
    cursor = rows[-1]["seq"] if rows else since
    more = len(rows) == limit and conn.execute("SELECT 1 FROM file_log WHERE seq > ?", (cursor,)).fetchone() is not None
    return {
        "refs": [refs.get_ref(conn, row["ref"]) for row in rows if refs.ref_exists(conn, row["ref"])],
        "cursor": str(cursor),
        "more": more,
    }


# ----------------------------------------------------------------------------------------------- the change feed


def changes(conn: sqlite3.Connection, person: str, since: int) -> dict[str, Any]:
    """Everything that changed for [person] after cursor [since], as the state it is in now (docs/17: `library/changes`)."""
    rows = list(
        conn.execute(
            "SELECT seq, kind, target FROM change_log WHERE person = ? AND seq > ? ORDER BY seq LIMIT ?",
            (person, since, CHANGES_PAGE),
        )
    )
    cursor = rows[-1]["seq"] if rows else since
    more = (
        len(rows) == CHANGES_PAGE
        and conn.execute("SELECT 1 FROM change_log WHERE person = ? AND seq > ?", (person, cursor)).fetchone() is not None
    )

    touched: dict[str, set[str]] = {}
    for row in rows:
        touched.setdefault(row["kind"], set()).add(row["target"])

    likes: list[dict[str, Any]] = []
    for target in sorted(touched.get("like", ())):
        item = conn.execute(
            "SELECT at FROM library_item WHERE person = ? AND kind = 'like' AND target = ?", (person, target)
        ).fetchone()
        likes.append({"ref": target, "at": item["at"] if item else None, "removed": item is None})
    albums = [_set_state(conn, person, "saved_album", t) for t in sorted(touched.get("saved_album", ()))]
    follows = [_set_state(conn, person, "follow_artist", t) for t in sorted(touched.get("follow_artist", ()))]

    playlists: list[dict[str, Any]] = []
    for target in sorted(touched.get("playlist", ())):
        row = conn.execute("SELECT * FROM playlist WHERE id = ? AND owner = ?", (target, person)).fetchone()
        if row is not None:
            playlists.append(playlist_json(conn, row))
    entries: list[dict[str, Any]] = []
    for target in sorted(touched.get("entry", ())):
        row = conn.execute(
            "SELECT e.* FROM playlist_entry e JOIN playlist p ON p.id = e.playlist WHERE e.id = ? AND p.owner = ?",
            (target, person),
        ).fetchone()
        if row is not None:
            entries.append(entry_json(row))

    wanted = {like["ref"] for like in likes if not like["removed"]} | {e["ref"] for e in entries if not e["deleted"]}
    ref_list = [refs.get_ref(conn, ref_id) for ref_id in sorted(wanted) if refs.ref_exists(conn, ref_id)]
    return {
        "refs": ref_list,
        "likes": likes,
        "savedAlbums": albums,
        "follows": follows,
        "playlists": playlists,
        "entries": entries,
        "cursor": str(cursor),
        "more": more,
    }


def _set_state(conn: sqlite3.Connection, person: str, kind: str, target: str) -> dict[str, Any]:
    item = conn.execute(
        "SELECT at FROM library_item WHERE person = ? AND kind = ? AND target = ?", (person, kind, target)
    ).fetchone()
    return {"id": target, "at": item["at"] if item else None, "removed": item is None}
