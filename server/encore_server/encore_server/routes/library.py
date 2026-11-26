"""A person's library: the change feed, the files, likes, saved albums and followed artists (docs/17 section 4, docs/34)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from .. import (
    library,
    refs,
)
from ..auth import (
    Principal,
)
from ..errors import ApiError
from ..keep_progress import MAX_RELEASE_SONGS
from ..scheduler import PROMOTE_MANY
from .common import API_PREFIX, _changed, _keep_state, _ok, get_principal, optional_body, services, want_kept

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


# ------------------------------------------------------------------------------------------------ the library


@router.get("/library/changes")
def library_changes(request: Request, since: str = "0", p: Principal = Depends(get_principal)) -> JSONResponse:
    try:
        cursor = int(since)
    except ValueError:
        raise ApiError("validation", "The cursor is a number, as the server gave it.") from None
    with services(request).db.read() as conn:
        return _ok(library.changes(conn, p.person_id, max(0, cursor)))


@router.get("/library/files")
def library_files(
    request: Request,
    since: str = "0",
    limit: int = 500,
    merges_since: str | None = Query(None, alias="mergesSince"),
    gone_since: str | None = Query(None, alias="goneSince"),
    p: Principal = Depends(get_principal),
) -> JSONResponse:
    """The songs this server keeps, as they change: the app's browse index of the server's files (docs/18 section 2). With `mergesSince` (a cursor of
    its own) the answer also lists the songs that were merged into another since then, `merges: [{from, into, seq}]` (N-11, docs/17); with `goneSince` (a third
    cursor) the refs the server retired since then, `gone: [{id, seq}]` (N-27 slice 2c, feature `ref-gone`)."""
    try:
        cursor = max(0, int(since))
        merges_cursor = None if merges_since is None else max(0, int(merges_since))
        gone_cursor = None if gone_since is None else max(0, int(gone_since))
    except ValueError:
        raise ApiError("validation", "The cursor is a number, as the server gave it.") from None
    with services(request).db.read() as conn:
        return _ok(library.files_since(conn, cursor, max(1, min(limit, library.FILES_PAGE)), merges_cursor, gone_cursor))


def _item_route(
    kind: str, request: Request, target: str, p: Principal, *, add: bool, body: dict[str, Any] | None = None
) -> JSONResponse:
    svc = services(request)
    with svc.db.tx() as conn:
        if kind == "like":
            target = refs.canonical(
                conn, target
            )  # a song merged into another (N-11): the like, its feed row and the keep are the survivor's
        changed = (
            library.set_item(conn, p.person_id, kind, target, at=(body or {}).get("at"))
            if add
            else library.clear_item(conn, p.person_id, kind, target)
        )
        if changed and add and kind == "like":
            want_kept(svc, conn, p.person_id, [target])
        cursor = library.latest_cursor(conn, p.person_id)
    if changed:
        _changed(svc, p, cursor)
    return _ok({"changed": changed, "cursor": str(cursor)})


@router.put("/likes/{ref_id}")
def like(
    ref_id: str, request: Request, body: dict[str, Any] = Depends(optional_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    return _item_route("like", request, ref_id, p, add=True, body=body)


@router.delete("/likes/{ref_id}")
def unlike(ref_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _item_route("like", request, ref_id, p, add=False)


def _release_refs(body: dict[str, Any]) -> list[str]:
    """The songs a phone names with a saved release: a list of song ids, or nothing."""
    named = body.get("refs")
    if named is None:
        return []
    if not isinstance(named, list) or len(named) > MAX_RELEASE_SONGS or not all(isinstance(r, str) for r in named):
        raise ApiError("validation", f"A release names its songs as a list of at most {MAX_RELEASE_SONGS} song ids.")
    return list(dict.fromkeys(named))


@router.put("/saved-albums/{album_id}")
def save_album(
    album_id: str,
    request: Request,
    body: dict[str, Any] = Depends(optional_body),
    p: Principal = Depends(get_principal),
) -> JSONResponse:
    """Saves an album. A release the server does not hold yet names its songs (`refs`, the ones the phone resolved): one call saves it,
    and the server keeps those songs in the background, first in line, whether or not the phone stays (D-21). All or nothing: a song the
    server does not know refuses the whole call, in words. The answer says how each song goes; the change feed delivers the save."""
    ref_ids = _release_refs(body)
    svc = services(request)
    with svc.db.tx() as conn:
        # Songs merged into another (N-11) count as the survivor, once.
        ref_ids = list(dict.fromkeys(refs.canonical_many(conn, ref_ids).values()))
        for ref_id in ref_ids:
            if not refs.ref_exists(conn, ref_id):
                raise ApiError("not_found", "That song is not known to this server.", details={"ref": ref_id})
        changed = library.set_item(conn, p.person_id, "saved_album", album_id[:100], at=body.get("at"))
        library.add_album_refs(conn, p.person_id, album_id[:100], ref_ids)
        # Songs whose keep failed before are asked for again, like a download does (`keep_now`); the rest are kept once.
        want_kept(svc, conn, p.person_id, [r for r in ref_ids if _keep_state(svc, conn, r)["state"] in ("none", "failed")])
        cursor = library.latest_cursor(conn, p.person_id)
    if svc.scheduler is not None:
        svc.scheduler.promote_many(
            "keep", ref_ids, priority=PROMOTE_MANY
        )  # a whole release at once: ahead of imports, behind a single tap
    if changed:
        _changed(svc, p, cursor)
    with svc.db.read() as conn:
        keep = {ref_id: _keep_state(svc, conn, ref_id, host=p.role == "owner") for ref_id in ref_ids}
    return _ok({"changed": changed, "cursor": str(cursor), "keep": keep})


@router.delete("/saved-albums/{album_id}")
def unsave_album(album_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _item_route("saved_album", request, album_id[:100], p, add=False)


@router.put("/follows/{artist_id}")
def follow(artist_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _item_route("follow_artist", request, artist_id[:100], p, add=True)


@router.delete("/follows/{artist_id}")
def unfollow(artist_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _item_route("follow_artist", request, artist_id[:100], p, add=False)
