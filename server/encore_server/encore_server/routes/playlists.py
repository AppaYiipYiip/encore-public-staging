"""Playlists, and the log of what was played (docs/17 section 4)."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import (
    library,
    refs,
)
from ..auth import (
    Principal,
)
from ..errors import ApiError
from .common import API_PREFIX, _changed, _ok, get_principal, json_body, services, want_kept

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


# ------------------------------------------------------------------------------------------------ playlists


def _write_playlist(request: Request, p: Principal, work) -> Any:  # type: ignore[no-untyped-def]
    svc = services(request)
    with svc.db.tx() as conn:
        result = work(conn)
        cursor = library.latest_cursor(conn, p.person_id)
    _changed(svc, p, cursor)
    return result, cursor


@router.get("/playlists")
def playlists(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    with services(request).db.read() as conn:
        return _ok({"items": library.list_playlists(conn, p.person_id)})


@router.post("/playlists")
def create_playlist(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    from ..ids import new_id

    playlist_id = body.get("id") or new_id("pl")

    def work(conn):  # type: ignore[no-untyped-def]
        row = library.create_playlist(conn, p.person_id, playlist_id, body.get("name"), body.get("cover"))
        return library.playlist_json(conn, row)

    result, cursor = _write_playlist(request, p, work)
    return _ok({**result, "cursor": str(cursor)}, 201)


@router.get("/playlists/{playlist_id}")
def get_playlist(playlist_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    with services(request).db.read() as conn:
        return _ok(library.get_playlist(conn, p.person_id, playlist_id))


@router.patch("/playlists/{playlist_id}")
def patch_playlist(
    playlist_id: str, request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    def work(conn):  # type: ignore[no-untyped-def]
        return library.playlist_json(conn, library.patch_playlist(conn, p.person_id, playlist_id, body))

    result, cursor = _write_playlist(request, p, work)
    return _ok({**result, "cursor": str(cursor)})


@router.delete("/playlists/{playlist_id}")
def delete_playlist(playlist_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    changed, cursor = _write_playlist(request, p, lambda conn: library.delete_playlist(conn, p.person_id, playlist_id))
    return _ok({"changed": changed, "cursor": str(cursor)})


@router.post("/playlists/{playlist_id}/entries")
def add_entries(
    playlist_id: str, request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    songs = body.get("songs")
    if not isinstance(songs, list) or not all(isinstance(s, dict) for s in songs):
        raise ApiError("validation", "Send the songs as a list of {ref, id?}.")
    after = body.get("after")
    svc = services(request)

    def add(conn: sqlite3.Connection) -> Any:
        made = library.add_entries(conn, p.person_id, playlist_id, songs, after=after if isinstance(after, str) else None)
        # The songs to keep are the survivors of any that were merged into another (N-11).
        wanted = refs.canonical_many(conn, [str(s.get("ref")) for s in songs])
        want_kept(svc, conn, p.person_id, list(wanted.values()))
        return made

    added, cursor = _write_playlist(request, p, add)
    return _ok({"added": added, "cursor": str(cursor)}, 201)


@router.delete("/playlists/{playlist_id}/entries")
def remove_entries(
    playlist_id: str, request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    ids = body.get("entryIds")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ApiError("validation", "Send entryIds as a list.")
    removed, cursor = _write_playlist(request, p, lambda conn: library.remove_entries(conn, p.person_id, playlist_id, ids))
    return _ok({"removed": removed, "cursor": str(cursor)})


@router.put("/playlists/{playlist_id}/order")
def reorder_playlist(
    playlist_id: str, request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    ids = body.get("entryIds")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ApiError("validation", "Send entryIds as a list.")
    _, cursor = _write_playlist(request, p, lambda conn: library.reorder(conn, p.person_id, playlist_id, ids))
    return _ok({"cursor": str(cursor)})


@router.get("/me/plays")
def my_plays(
    request: Request, limit: int = 500, cursor: str | None = None, p: Principal = Depends(get_principal)
) -> JSONResponse:
    """The person's own plays, newest first, in pages (`{items, nextCursor}`): the history Year in Music counts (P3-34 slice 0, docs/17). The person is the token's,
    never a parameter."""
    with services(request).db.read() as conn:
        return _ok(library.my_plays(conn, p.person_id, limit=limit, cursor=cursor))


@router.post("/plays")
def post_play(request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)) -> JSONResponse:
    with services(request).db.tx() as conn:
        ref_id = refs.canonical(conn, str(body.get("ref", "")))  # a song merged into another (N-11) is played as the survivor
        stored = library.record_play(
            conn,
            p.person_id,
            play_id=body.get("id"),
            ref=ref_id,
            at=body.get("at"),
            ms_played=body.get("msPlayed"),
            device=p.device_id,
            context=body.get("context"),
        )
        svc = services(request)
        listened = body.get("msPlayed")
        counted = stored and svc.scheduler is not None and isinstance(listened, int) and listened >= library.MIN_COUNTED_PLAY_MS
        if counted and library.played_on_days(conn, ref_id) >= svc.settings.keep_after_play_days:
            want_kept(svc, conn, p.person_id, [ref_id])
    return _ok({"stored": stored}, 201 if stored else 200)
