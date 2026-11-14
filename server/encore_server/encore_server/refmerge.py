"""Merging the song refs that hold one file (N-11 part B): the repair of what the library scan made twice before part A.

**What went wrong.** The keeper saves a file for the ref an import made (the artists as a list, the album, the cover). The library scan later met
the same file in the music server, described it from its TAGS (the artists as one joined string, a length seconds off, the album `[Unknown Album]`),
found no ref for that description and made a second one, and attached the same file to it. A person then saw the song twice (once under the
unknown album), and the phone downloaded it twice. Part A (`scanner.link_library`) stops new ones; this repairs the existing ones.

**The rule.** Refs that share a file of the music server (`song_file.navidrome_song_id`) are one song shown twice. The survivor is the ref whose
file row was attached FIRST (the keeper's, which carries the proper description). Never on the name alone: two recordings can share a name.

**Held, never merged** (logged at INFO on every start; expected, not a failure):

* the two refs name different source items (their `ytm_video_id` differ, or their ISRC or Deezer id): two recordings, and the keeper's habit of
  handing a file to a second ref (`keeper/keeper.py`, a separate fix) is what put them on one file;
* a playlist holds both: merging would put the song twice into that playlist, a visible change to a person's own list nobody asked for.

**Everything a person has follows the song**: likes (a person who liked both keeps the earlier date), playlist entries (removed ones too), plays,
import rows, the work the server still means to do, the songs of a saved release, the saved queue (its ids are rewritten in place: the index of
the song playing must not shift), and the two change feeds. The files merge key by key (a replaced `meta` would have lost the only picture id of
some survivors). The survivor takes only what it LACKS from the other ref, and never the placeholder album.

**Safety.** It runs once at start-up, right after the migrations and before any thread, as ONE transaction preceded by its own backup (kept, its
path logged). A failure rolls everything back, is logged, and never stops the server. A second run finds nothing to merge. It is not an admin
action: a person who upgrades needs it and must not have to know. What is left of a merged ref is a row of `ref_merge`: old ids keep working on
the server (`refs.canonical`), the same song described again finds the survivor (`refs.find`), and the phone learns the merge from the files feed.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import library, refs
from .db import Database
from .ids import now_ms

log = logging.getLogger("encore_server.refmerge")

#: The columns that name a song ref through a foreign key. A merge deletes the loser's row, so every one of these must be re-pointed or dropped first
#: (the foreign key refuses the delete otherwise, or cascades the rows away). `tests/test_ref_merge.py` compares this with the schema, so a table
#: added later cannot be forgotten.
FOREIGN_KEY_COLUMNS = frozenset(
    {
        ("song_file", "ref"),
        ("playlist_entry", "ref"),
        ("play_event", "ref"),
        ("import_entry", "ref"),
        ("work_item", "ref"),
        ("saved_album_ref", "ref"),
    }
)
#: The columns that name a song ref WITHOUT a foreign key (text): `library_item.target` and `change_log.target` of kind `like` (the other kinds hold
#: a catalogue id or a playlist id), `playback_state.ref` and the ids inside its `queue`, and `file_log.ref`.

_BACKUP_LABEL = "before-ref-merge"
#: How many held pairs are written out one by one at every start; the rest are counted.
_LOG_HELD = 30
#: What the survivor never takes from the other ref (its identity, or handled by its own rule below).
_NOT_COPIED = frozenset(
    {
        "id",
        "title",
        "artists",
        "norm_key",
        "created_at",
        "cover_tried_at",
        "album",
        "explicit",
        "isrc",
        "deezer_id",
        "ytm_video_id",
    }
)
#: What describes the RELEASE a song is on: taken from the other ref only when it is the same release (or the survivor has none).
_OF_THE_RELEASE = ("album_artist", "track_no", "disc_no", "year")


@dataclass(frozen=True)
class Merged:
    survivor: str
    loser: str


@dataclass(frozen=True)
class Held:
    survivor: str
    loser: str
    #: `different_source_video`, `different_isrc`, `different_deezer_id` or `same_playlist`.
    reason: str


@dataclass
class RepairReport:
    merged: list[Merged] = field(default_factory=list)
    held: list[Held] = field(default_factory=list)
    #: The copy taken before anything was changed; `None` when there was nothing to merge.
    backup: Path | None = None
    failed: bool = False


# ------------------------------------------------------------------------------------------------------------------ what to merge


def _components(conn: sqlite3.Connection) -> list[tuple[str, list[str]]]:
    """`[(survivor, [losers...])]`: the refs that share a file, as groups (a ref in two groups joins them). The survivor is the ref whose file row
    of the SHARED file was attached first (lowest `added_at`, then the row's place), the losers follow in that order."""
    rows = conn.execute(
        "SELECT ref, navidrome_song_id AS nd, added_at, rowid AS place FROM song_file WHERE navidrome_song_id IN"
        " (SELECT navidrome_song_id FROM song_file WHERE navidrome_song_id IS NOT NULL AND navidrome_song_id <> '' GROUP BY navidrome_song_id HAVING COUNT(DISTINCT ref) > 1)"
        " ORDER BY added_at, rowid"
    ).fetchall()
    parent: dict[str, str] = {}

    def root(ref: str) -> str:
        parent.setdefault(ref, ref)
        while parent[ref] != ref:
            parent[ref] = parent[parent[ref]]
            ref = parent[ref]
        return ref

    first: dict[str, tuple[int, int]] = {}
    by_file: dict[str, list[str]] = {}
    for row in rows:
        first.setdefault(row["ref"], (row["added_at"], row["place"]))
        by_file.setdefault(row["nd"], []).append(row["ref"])
    for holders in by_file.values():
        for other in holders[1:]:
            parent[root(other)] = root(holders[0])
    members: dict[str, list[str]] = {}
    for ref in first:
        members.setdefault(root(ref), []).append(ref)
    plan: list[tuple[str, list[str]]] = []
    for group in members.values():
        ordered = sorted(group, key=lambda ref: (first[ref], ref))
        plan.append((ordered[0], ordered[1:]))
    return sorted(plan)


def _hold_reason(conn: sqlite3.Connection, survivor: sqlite3.Row, loser: sqlite3.Row) -> str | None:
    """Why this loser is NOT merged into this survivor, or `None` when it may be."""
    for column, reason in (
        ("ytm_video_id", "different_source_video"),
        ("isrc", "different_isrc"),
        ("deezer_id", "different_deezer_id"),
    ):
        if survivor[column] and loser[column] and survivor[column] != loser[column]:
            return reason
    both = conn.execute(
        "SELECT 1 FROM playlist_entry a JOIN playlist_entry b ON b.playlist = a.playlist JOIN playlist p ON p.id = a.playlist"
        " WHERE a.ref = ? AND b.ref = ? AND a.deleted_at IS NULL AND b.deleted_at IS NULL AND p.deleted_at IS NULL LIMIT 1",
        (survivor["id"], loser["id"]),
    ).fetchone()
    return "same_playlist" if both is not None else None


def _row(conn: sqlite3.Connection, ref_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref_id,)).fetchone()
    assert row is not None, ref_id
    return row  # type: ignore[no-any-return]


def _is_there_anything_to_merge(conn: sqlite3.Connection) -> tuple[bool, list[Held]]:
    """A look that changes nothing: whether any loser may be merged, and the pairs that are held (against the survivors as they are now)."""
    held: list[Held] = []
    mergeable = False
    for survivor, losers in _components(conn):
        for loser in losers:
            reason = _hold_reason(conn, _row(conn, survivor), _row(conn, loser))
            if reason is None:
                mergeable = True
            else:
                held.append(Held(survivor, loser, reason))
    return mergeable, held


# ------------------------------------------------------------------------------------------------------------------ the repair


def repair(db: Database) -> RepairReport:
    """Merges what can be merged; always returns, never raises (a server that cannot repair itself still has to start). See the module's docstring."""
    report = RepairReport()
    held: list[Held] = []
    try:
        with db.read() as conn:
            mergeable, held = _is_there_anything_to_merge(conn)
        report.held = held
        if not mergeable:
            _say_held(held)
            return report
        report.backup = db.backup(_BACKUP_LABEL)
        log.info("ref merge: a copy of the database before the repair is kept at %s", report.backup)
        with db.tx() as conn:
            report.held = []
            for survivor, losers in _components(conn):
                for loser in losers:
                    # Judged against the survivor as it is NOW: it may have taken an id from an earlier loser of this group.
                    reason = _hold_reason(conn, _row(conn, survivor), _row(conn, loser))
                    if reason is not None:
                        report.held.append(Held(survivor, loser, reason))
                        continue
                    _merge_pair(conn, survivor, loser)
                    report.merged.append(Merged(survivor, loser))
        log.info("ref merge: %d songs that held one file with another were merged into it", len(report.merged))
        _say_held(report.held)
    except Exception:  # noqa: BLE001 - the server must start whatever happens here; the transaction rolled back, the copy is kept
        report.merged = []
        report.held = held
        report.failed = True
        log.exception(
            "ref merge FAILED and changed nothing (the songs that share a file stay as they are; the repair is tried again at the next start)%s",
            f"; the copy taken before it is {report.backup}" if report.backup else "",
        )
    return report


def _say_held(held: list[Held]) -> None:
    """The pairs left alone, written out at every start so nobody has to wonder (ids only: a line can be looked up, and carries no title)."""
    for pair in held[:_LOG_HELD]:
        log.info("ref merge: held back, not merged (%s): %s and %s hold the same file", pair.reason, pair.survivor, pair.loser)
    if len(held) > _LOG_HELD:
        log.info("ref merge: and %d more pairs held back", len(held) - _LOG_HELD)


# ------------------------------------------------------------------------------------------------------------------ one merge


def _merge_pair(conn: sqlite3.Connection, survivor: str, loser: str) -> None:
    """Everything the loser has goes to the survivor, then the loser is deleted. The order matters: all the rows that point at the loser are moved
    (or dropped on purpose) BEFORE it is deleted, because three of its tables cascade and the others refuse the delete."""
    kept = _row(conn, survivor)
    gone = _row(conn, loser)

    _move_likes(conn, survivor, loser)
    conn.execute(
        "UPDATE playlist_entry SET ref = ? WHERE ref = ?", (survivor, loser)
    )  # removed entries too: the key has no cascade
    conn.execute("UPDATE play_event SET ref = ? WHERE ref = ?", (survivor, loser))
    conn.execute("UPDATE import_entry SET ref = ? WHERE ref = ?", (survivor, loser))
    _move_work(conn, survivor, loser)
    conn.execute(
        "INSERT OR IGNORE INTO saved_album_ref (person, album, ref) SELECT person, album, ? FROM saved_album_ref WHERE ref = ?",
        (survivor, loser),
    )
    conn.execute("DELETE FROM saved_album_ref WHERE ref = ?", (loser,))
    _rewrite_playback_state(conn, survivor, loser)
    conn.execute("UPDATE file_log SET ref = ? WHERE ref = ?", (survivor, loser))
    _merge_files(conn, survivor, loser)
    conn.execute("DELETE FROM song_ref WHERE id = ?", (loser,))

    # Only now that the loser is gone may the survivor take an id of its (the unique indexes would have refused it before).
    updates = _enrichment(conn, kept, gone)
    for column in ("isrc", "deezer_id", "ytm_video_id"):
        if kept[column] is None and gone[column] is not None:
            updates[column] = gone[column]
    if updates:
        assignments = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(f"UPDATE song_ref SET {assignments} WHERE id = ?", (*updates.values(), survivor))  # noqa: S608 - column names from the schema

    # What is left of the loser: the way to find the survivor again (its id, and what it was called). A survivor merged away before takes its
    # tombstones along, so `into_id` always names a live ref.
    conn.execute(
        "INSERT INTO ref_merge (old_id, into_id, at, norm_key, isrc, deezer_id, ytm_video_id, duration_ms) VALUES (?,?,?,?,?,?,?,?)",
        (loser, survivor, now_ms(), gone["norm_key"], gone["isrc"], gone["deezer_id"], gone["ytm_video_id"], gone["duration_ms"]),
    )
    conn.execute("UPDATE ref_merge SET into_id = ? WHERE into_id = ?", (survivor, loser))

    # Every phone that has the song is told it changed: the file (the files feed) and the likes and entries that now point at the survivor.
    refs.touch_file(conn, survivor)
    library.touch_ref_holders(conn, survivor)


def _move_likes(conn: sqlite3.Connection, survivor: str, loser: str) -> None:
    """A like is a set member: a person who liked both ends with one like of the song, dated by the earlier of the two (Liked Songs keeps its order)."""
    for like in conn.execute("SELECT person, at FROM library_item WHERE kind = 'like' AND target = ?", (loser,)).fetchall():
        have = conn.execute(
            "SELECT at FROM library_item WHERE person = ? AND kind = 'like' AND target = ?", (like["person"], survivor)
        ).fetchone()
        if have is None:
            conn.execute(
                "UPDATE library_item SET target = ? WHERE person = ? AND kind = 'like' AND target = ?",
                (survivor, like["person"], loser),
            )
            continue
        if like["at"] < have["at"]:
            conn.execute(
                "UPDATE library_item SET at = ? WHERE person = ? AND kind = 'like' AND target = ?",
                (like["at"], like["person"], survivor),
            )
        conn.execute("DELETE FROM library_item WHERE person = ? AND kind = 'like' AND target = ?", (like["person"], loser))
    # The feed of likes names the song a like was about: a phone that reads those rows later must meet the survivor, not an id that is gone.
    conn.execute("UPDATE change_log SET target = ? WHERE kind = 'like' AND target = ?", (survivor, loser))


def _move_work(conn: sqlite3.Connection, survivor: str, loser: str) -> None:
    """Work the server still means to do for the loser moves to the survivor, or joins the survivor's identical item (one active item per kind and
    song: it is wanted by everybody who wanted either). What is finished or failed was about the loser and is dropped: put on the survivor it would
    be taken for the survivor's newest news."""
    for item in conn.execute("SELECT id, kind, state FROM work_item WHERE ref = ?", (loser,)).fetchall():
        if item["state"] not in ("queued", "running"):
            conn.execute("DELETE FROM work_item WHERE id = ?", (item["id"],))
            continue
        twin = conn.execute(
            "SELECT id FROM work_item WHERE kind = ? AND ref = ? AND state IN ('queued', 'running')", (item["kind"], survivor)
        ).fetchone()
        if twin is None:
            conn.execute("UPDATE work_item SET ref = ? WHERE id = ?", (survivor, item["id"]))
        else:
            conn.execute(
                "INSERT OR IGNORE INTO work_item_person (item, person) SELECT ?, person FROM work_item_person WHERE item = ?",
                (twin["id"], item["id"]),
            )
            conn.execute("DELETE FROM work_item WHERE id = ?", (item["id"],))


def replace_ids(value: Any, mapping: dict[str, str]) -> Any:
    """[value] with every string that is a key of [mapping] replaced, wherever it sits in lists and objects: the saved queue is JSON, and nothing
    about its shape is assumed (a later version may keep more than ids in it). Lists keep their length and order."""
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [replace_ids(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: replace_ids(item, mapping) for key, item in value.items()}
    return value


def _rewrite_playback_state(conn: sqlite3.Connection, survivor: str, loser: str) -> None:
    """The server's copy of what a person was playing: the song and the queue. The revision goes up, so a device that wrote from the old state gets
    `conflict` with the new one and does not put the old ids back."""
    for state in conn.execute(
        "SELECT person, ref, queue FROM playback_state WHERE ref = ? OR instr(queue, ?) > 0", (loser, loser)
    ).fetchall():
        queue = state["queue"]
        try:
            queue = json.dumps(replace_ids(json.loads(queue), {loser: survivor}))
        except ValueError:
            # A queue that is not JSON cannot be read by anything else either (`playback.get_state`); it must not stop the repair of every other song.
            log.warning("ref merge: the saved queue of one person is not readable and was left as it was")
        conn.execute(
            "UPDATE playback_state SET ref = ?, queue = ?, rev = rev + 1 WHERE person = ?",
            (survivor if state["ref"] == loser else state["ref"], queue, state["person"]),
        )


# ------------------------------------------------------------------------------------------------------------------ the files


def _merge_files(conn: sqlite3.Connection, survivor: str, loser: str) -> None:
    """The loser's file rows go to the survivor. The row of the SAME file (same id in the music server, or same path) is one row: the survivor keeps
    its own (its id, its path, its source: where the keeper saved it), takes what describes the file from the newer of the two, and the two `meta`
    are merged key by key (a missing key never erases a known one: the survivor's only `coverArt` stays). Any other file simply moves over."""
    for theirs in conn.execute("SELECT * FROM song_file WHERE ref = ? ORDER BY added_at, rowid", (loser,)).fetchall():
        ours = conn.execute(
            "SELECT * FROM song_file WHERE ref = ? AND ((navidrome_song_id IS NOT NULL AND navidrome_song_id = ?) OR (path IS NOT NULL AND path = ?))",
            (survivor, theirs["navidrome_song_id"], theirs["path"]),
        ).fetchone()
        if ours is None:
            conn.execute("UPDATE song_file SET ref = ?, preferred = 0 WHERE id = ?", (survivor, theirs["id"]))
            continue
        newer, older = (theirs, ours) if theirs["added_at"] > ours["added_at"] else (ours, theirs)
        updates: dict[str, Any] = {}
        for column in ("navidrome_song_id", "codec", "bitrate_kbps", "loudness_lufs"):
            value = newer[column] if newer[column] is not None else older[column]
            if value != ours[column]:
                updates[column] = value
        meta = _merge_meta(older["meta"], newer["meta"])
        if meta != ours["meta"]:
            updates["meta"] = meta
        if updates:
            assignments = ", ".join(f"{column} = ?" for column in updates)
            conn.execute(f"UPDATE song_file SET {assignments} WHERE id = ?", (*updates.values(), ours["id"]))  # noqa: S608 - column names from the schema
        conn.execute("DELETE FROM song_file WHERE id = ?", (theirs["id"],))
    # One copy is the preferred one: the survivor's own, or the newest when it had none.
    rows = conn.execute(
        "SELECT id, preferred FROM song_file WHERE ref = ? ORDER BY preferred DESC, added_at DESC, rowid DESC", (survivor,)
    ).fetchall()
    if rows and sum(row["preferred"] for row in rows) != 1:
        conn.execute("UPDATE song_file SET preferred = (id = ?) WHERE ref = ?", (rows[0]["id"], survivor))


def _load_meta(text: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(text) if text else {}
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _merge_meta(older: str | None, newer: str | None) -> str | None:
    """The music server's facts about a file, key by key: the newer row's value where it has one, the older row's where it does not."""
    old = _load_meta(older)
    new = _load_meta(newer)
    merged = {key: value for key, value in {**old, **new}.items() if value is not None}
    return json.dumps(merged, separators=(",", ":"), sort_keys=True) if merged else None


# ------------------------------------------------------------------------------------------------------------------ the survivor's description


def _enrichment(conn: sqlite3.Connection, survivor: sqlite3.Row, loser: sqlite3.Row) -> dict[str, Any]:
    """What the survivor lacks and the loser knows. Never the placeholder album, never a second description of the same fact: the survivor's own
    title, artists and album stay. Facts about the release (album artist, track, disc, year) come along only when it is the same release or the
    survivor has none; `explicit` is true if either says so. A column added to `song_ref` later is copied when empty, unless listed in [_NOT_COPIED]."""
    updates: dict[str, Any] = {}
    ours_real = not refs.is_placeholder_album(survivor["album"])
    theirs_real = not refs.is_placeholder_album(loser["album"])
    if not ours_real and theirs_real:
        updates["album"] = loser["album"]
    same_release = ours_real and theirs_real and survivor["album"].strip().lower() == loser["album"].strip().lower()
    of_the_release = not ours_real or not theirs_real or same_release
    for column in (r["name"] for r in conn.execute("PRAGMA table_info(song_ref)")):
        if column in _NOT_COPIED:
            continue
        if survivor[column] is None and loser[column] is not None and (of_the_release or column not in _OF_THE_RELEASE):
            updates[column] = loser[column]
    if loser["explicit"] and not survivor["explicit"]:
        updates["explicit"] = 1
    return updates
