"""How far the server is with keeping what a person asked for, many things in one answer (P2-22 part 1, docs/17 "Keep progress").

A phone that downloads a 200-song playlist shows two numbers: how many songs are on the phone (its own table) and how many the server has
**ready** to hand over. This is the second number, for every pinned playlist, release and the liked songs at once, in one request: one query
per song would be hundreds of calls for one screen.

Rules (each has a test):

* Every song of a group lands in **exactly one** bucket, so the buckets add up to `total`: `ready` (the server has the file), `keeping` (being
  fetched now), `queued` (waiting, including a wait for YouTube's rest), `failed` (named, with whether trying again can help).
* A group the person cannot see is **left out of the answer**, the same as one that does not exist: no id can be probed.
* The sentence of a failure depends on who asks: the Host gets the cause, a member the plain fact (`keeper/failures.py`).
* Nothing is changed by asking.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .db import Database
from .errors import ApiError
from .keeper.failures import describe_failure, file_lost, not_fetched
from .scheduler import Scheduler

#: How many groups one request may ask about (a phone pins a few dozen at most).
MAX_GROUPS = 50
#: How many failed songs are named per group; `failed` always counts all of them.
MAX_NAMED = 20
#: How many songs one release may name (when it is saved, and as a hint here).
MAX_RELEASE_SONGS = 500
KINDS = ("playlist", "release", "liked")
_CHUNK = 400


@dataclass(frozen=True)
class Group:
    kind: str
    id: str
    #: For a release saved before the server stored its songs: the ones the phone knows. Used only when none are stored.
    refs: tuple[str, ...] = ()


def parse_groups(body: dict[str, Any], *, allow_empty: bool = False) -> list[Group]:
    """The groups a phone asks about, or a `validation` error in words. [allow_empty]: an empty list is a real answer (stop watching)."""
    raw = body.get("groups")
    if not isinstance(raw, list) or (not raw and not allow_empty) or len(raw) > MAX_GROUPS:
        raise ApiError("validation", f"Ask about between 1 and {MAX_GROUPS} downloads at a time.")
    groups: list[Group] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("kind") not in KINDS:
            raise ApiError("validation", f"A download is a playlist, a release or the liked songs ({', '.join(KINDS)}).")
        gid = item.get("id")
        if not isinstance(gid, str) or not gid or len(gid) > 100:
            raise ApiError("validation", "Every download needs its id.")
        named = item.get("refs")
        if named is None:
            named = []
        if not isinstance(named, list) or len(named) > MAX_RELEASE_SONGS or not all(isinstance(r, str) for r in named):
            raise ApiError("validation", f"A release names its songs as a list of at most {MAX_RELEASE_SONGS} song ids.")
        groups.append(Group(item["kind"], gid, tuple(dict.fromkeys(named))))
    return groups


def _chunks(items: list[str]) -> list[list[str]]:
    return [items[start : start + _CHUNK] for start in range(0, len(items), _CHUNK)]


def members(conn: sqlite3.Connection, person: str, group: Group) -> list[str] | None:
    """The songs of a group, in order, once each, or `None` when this person has no such group (it is then left out of the answer)."""
    if group.kind == "playlist":
        # Only the owner's own playlist: sharing one with other people is not built (docs/34), and a deleted one is gone.
        row = conn.execute(
            "SELECT 1 FROM playlist WHERE id = ? AND owner = ? AND deleted_at IS NULL", (group.id, person)
        ).fetchone()
        if row is None:
            return None
        rows = conn.execute(
            "SELECT ref FROM playlist_entry WHERE playlist = ? AND deleted_at IS NULL ORDER BY position, id", (group.id,)
        ).fetchall()
        return list(dict.fromkeys(r["ref"] for r in rows))
    if group.kind == "liked":
        rows = conn.execute(
            "SELECT target FROM library_item WHERE person = ? AND kind = 'like' ORDER BY at, target", (person,)
        ).fetchall()
        return list(dict.fromkeys(r["target"] for r in rows))
    album = group.id[:100]  # saved albums are stored under the first 100 characters of the id (api.save_album)
    saved = conn.execute(
        "SELECT 1 FROM library_item WHERE person = ? AND kind = 'saved_album' AND target = ?", (person, album)
    ).fetchone()
    if saved is None:
        return None
    stored = conn.execute(
        "SELECT ref FROM saved_album_ref WHERE person = ? AND album = ? ORDER BY rowid", (person, album)
    ).fetchall()
    if stored:
        return [r["ref"] for r in stored]
    # Saved before the server stored a release's songs: the phone says which they are; only songs this server knows count.
    known: set[str] = set()
    for chunk in _chunks(list(group.refs)):
        marks = ",".join("?" for _ in chunk)
        known.update(r["id"] for r in conn.execute(f"SELECT id FROM song_ref WHERE id IN ({marks})", chunk))  # noqa: S608 - placeholders only
    return [r for r in group.refs if r in known]


def _linked(conn: sqlite3.Connection, ref_ids: list[str]) -> set[str]:
    """The songs the music server holds a file of: what `ready` means."""
    found: set[str] = set()
    for chunk in _chunks(ref_ids):
        marks = ",".join("?" for _ in chunk)
        found.update(
            r["ref"]
            for r in conn.execute(
                f"SELECT DISTINCT ref FROM song_file WHERE navidrome_song_id IS NOT NULL AND ref IN ({marks})",  # noqa: S608 - placeholders only
                chunk,
            )
        )
    return found


def _named(conn: sqlite3.Connection, ref_ids: list[str]) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for chunk in _chunks(ref_ids):
        marks = ",".join("?" for _ in chunk)
        for r in conn.execute(f"SELECT id, title, artists FROM song_ref WHERE id IN ({marks})", chunk):  # noqa: S608 - placeholders only
            try:
                artists = json.loads(r["artists"])
            except ValueError:
                artists = []
            out[r["id"]] = (r["title"], str(artists[0]) if artists else "")
    return out


def progress(db: Database, scheduler: Scheduler, person: str, *, host: bool, groups: list[Group]) -> list[dict[str, Any]]:
    """The answer for these groups (those the person has), in the order asked. [host]: the person is the Host, who reads causes."""
    with db.read() as conn:
        found = [(g, m) for g in groups if (m := members(conn, person, g)) is not None]
    every = list(dict.fromkeys(r for _, m in found for r in m))
    # The queue is read BEFORE the files, never after: the keeper links the file first and marks the item done after, so a song seen "done"
    # here is already linked when the files are read next. The other order could call a song that just finished "lost" for one answer.
    items = scheduler.states_of("keep", every)
    with db.read() as conn:
        linked = _linked(conn, every)
        verdict: dict[str, tuple[str, str | None, bool]] = {}  # ref -> (bucket, reason, retry)
        for ref_id in every:
            verdict[ref_id] = _verdict(ref_id in linked, items.get(ref_id), host=host)
        out: list[dict[str, Any]] = []
        for group, ref_ids in found:
            buckets = {"ready": 0, "keeping": 0, "queued": 0, "failed": 0}
            failed: list[str] = []
            retryable = 0
            for ref_id in ref_ids:
                bucket, _, retry = verdict[ref_id]
                buckets[bucket] += 1
                if bucket == "failed":
                    failed.append(ref_id)
                    retryable += 1 if retry else 0
            names = _named(conn, failed[:MAX_NAMED])
            failures = [
                {
                    "ref": ref_id,
                    "title": names.get(ref_id, ("", ""))[0],
                    "artist": names.get(ref_id, ("", ""))[1],
                    "reason": verdict[ref_id][1],
                    "retry": verdict[ref_id][2],
                }
                for ref_id in failed[:MAX_NAMED]
            ]
            out.append(
                {
                    "kind": group.kind,
                    "id": group.id,
                    "total": len(ref_ids),
                    **buckets,
                    "retryable": retryable,
                    "failures": failures,
                }
            )
    return out


def _verdict(is_linked: bool, item: dict[str, object] | None, *, host: bool) -> tuple[str, str | None, bool]:
    """One song: which bucket, and for `failed` the sentence and whether trying again can help. Kept in step with `api._keep_state`:
    kept is ready, keeping is keeping, queued is queued, failed is failed, and `none` (finished without a file, cancelled, never tried) is failed for a
    wanted song. `test_the_buckets_agree_with_the_state_of_one_song_asked_alone_in_all_seven_situations` walks every situation through both."""
    if is_linked:
        return ("ready", None, False)
    state = item["state"] if item is not None else None
    if state == "running":
        return ("keeping", None, False)
    if state == "queued":
        return ("queued", None, False)
    if state == "failed":
        failure = describe_failure(str(item["error"]) if item is not None and item["error"] else None, host=host)
        return ("failed", failure.reason, failure.retry)
    # No item that is waiting or running and no file. Done means it was kept once and the file is gone; nothing at all (or a cancelled one)
    # means it was never fetched. Either way the song is wanted and the server does not have it: that is a failure to name, with a Retry.
    failure = file_lost() if state == "done" else not_fetched()
    return ("failed", failure.reason, failure.retry)
