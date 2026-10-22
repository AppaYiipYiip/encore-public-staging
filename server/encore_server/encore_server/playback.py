"""Playback state and the one device that plays (docs/13, docs/17 section 3, ADR-R9).

Per person: what is playing, where, the queue, and which device is the active one. A write carries the `rev` the writer last saw
(optimistic concurrency): an old `rev` gets `conflict` with the current state, so two devices never silently overwrite each other.
Starting to play on a device that is not the active one takes over: the previous device is told to stop.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .errors import ApiError
from .ids import is_id, now_ms

MAX_QUEUE = 2000
_REPEAT = {"off", "all", "one"}


def _json(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {
            "ref": None,
            "positionMs": 0,
            "queue": [],
            "index": 0,
            "context": None,
            "shuffle": False,
            "repeat": "off",
            "playing": False,
            "activeDevice": None,
            "rev": 0,
            "updatedAt": 0,
        }
    return {
        "ref": row["ref"],
        "positionMs": row["position_ms"],
        "queue": json.loads(row["queue"]),
        "index": row["idx"],
        "context": row["context"],
        "shuffle": bool(row["shuffle"]),
        "repeat": row["repeat"],
        "playing": bool(row["playing"]),
        "activeDevice": row["active_device"],
        "rev": row["rev"],
        "updatedAt": row["updated_at"],
    }


def get_state(conn: sqlite3.Connection, person: str) -> dict[str, Any]:
    return _json(conn.execute("SELECT * FROM playback_state WHERE person = ?", (person,)).fetchone())


def put_state(
    conn: sqlite3.Connection, person: str, body: dict[str, Any], device: str | None
) -> tuple[dict[str, Any], str | None]:
    """Writes the state. Returns it and the device that has just been taken over from (or `None`)."""
    current_row = conn.execute("SELECT * FROM playback_state WHERE person = ?", (person,)).fetchone()
    current = _json(current_row)
    rev = body.get("rev")
    if isinstance(rev, bool) or not isinstance(rev, int):
        raise ApiError("validation", "Say which revision of the playback state this is based on (rev).")
    if rev != current["rev"]:
        raise ApiError("conflict", details={"state": current})

    ref = body.get("ref")
    if ref is not None and not is_id(ref, "sr"):
        raise ApiError("validation", "The song must be a song ref.")
    queue = body.get("queue", current["queue"])
    if not isinstance(queue, list) or len(queue) > MAX_QUEUE or not all(is_id(item, "sr") for item in queue):
        raise ApiError("validation", f"The queue is a list of up to {MAX_QUEUE} song refs.")
    position = body.get("positionMs", current["positionMs"])
    index = body.get("index", current["index"])
    repeat = body.get("repeat", current["repeat"])
    if (
        isinstance(position, bool)
        or not isinstance(position, int)
        or position < 0
        or isinstance(index, bool)
        or not isinstance(index, int)
        or index < 0
        or repeat not in _REPEAT
    ):
        raise ApiError("validation", "The position, the index or the repeat mode is not valid.")
    playing = bool(body.get("playing", False))
    context = body.get("context")
    if context is not None and (not isinstance(context, str) or len(context) > 200):
        raise ApiError("validation", "The context is a short text.")

    active = current["activeDevice"]
    taken_from: str | None = None
    if device is not None and playing and active != device:
        taken_from = active  # starting to play here is taking over
        active = device
    elif active is None and device is not None:
        active = device

    conn.execute(
        "INSERT INTO playback_state (person, ref, position_ms, queue, idx, context, shuffle, repeat, playing, active_device, rev, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(person) DO UPDATE SET ref=excluded.ref, position_ms=excluded.position_ms,"
        " queue=excluded.queue, idx=excluded.idx, context=excluded.context, shuffle=excluded.shuffle, repeat=excluded.repeat,"
        " playing=excluded.playing, active_device=excluded.active_device, rev=excluded.rev, updated_at=excluded.updated_at",
        (
            person,
            ref,
            position,
            json.dumps(queue),
            index,
            context,
            1 if body.get("shuffle") else 0,
            repeat,
            1 if playing else 0,
            active,
            current["rev"] + 1,
            now_ms(),
        ),
    )
    return get_state(conn, person), taken_from


def claim(conn: sqlite3.Connection, person: str, device: str) -> tuple[dict[str, Any], str | None]:
    """This device becomes the one that plays (the others are told). Returns the state and the device that had it."""
    current = get_state(conn, person)
    previous = current["activeDevice"]
    if previous == device:
        return current, None
    conn.execute(
        "INSERT INTO playback_state (person, active_device, rev, updated_at) VALUES (?,?,1,?)"
        " ON CONFLICT(person) DO UPDATE SET active_device=excluded.active_device, rev=playback_state.rev + 1, updated_at=excluded.updated_at",
        (person, device, now_ms()),
    )
    return get_state(conn, person), previous
