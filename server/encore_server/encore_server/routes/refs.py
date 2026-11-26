"""Song references: resolve, prepare, mark unavailable, read one (docs/17 section 3, docs/04)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import (
    refs,
)
from ..auth import (
    Principal,
)
from ..errors import ApiError
from .common import API_PREFIX, _ok, get_principal, json_body, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


# ------------------------------------------------------------------------------------------------ song refs


@router.post("/refs/resolve")
def resolve_refs(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    items = body.get("songs")
    if not isinstance(items, list) or not items or len(items) > 500:
        raise ApiError("validation", "Send between 1 and 500 songs.")
    with services(request).db.tx() as conn:
        return _ok({"items": [refs.resolve(conn, item) for item in items]})


@router.post("/refs/prepare")
def prepare_refs(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    """The player says which songs are next in its queue; the server makes them ready (the song's upload and its stream's address, no bytes) so that a
    Next finds them at once (P1-04, audit B-107). Background work: it answers at once with how many songs it took, the asking is paced, and a server
    that cannot fetch songs from YouTube takes none."""
    ids = body.get("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 3 or not all(isinstance(i, str) for i in ids):
        raise ApiError("validation", "Send between 1 and 3 songs.")
    svc = services(request)
    if svc.scheduler is None or not svc.scheduler.handles("prepare"):
        return _ok({"accepted": 0})
    accepted = 0
    with svc.db.tx() as conn:
        # Songs merged into another (N-11) are prepared as the survivor, once.
        for ref_id in dict.fromkeys(refs.canonical_many(conn, ids).values()):
            if refs.ref_exists(conn, ref_id):
                svc.scheduler.submit("prepare", ref_id, p.person_id, conn=conn)
                accepted += 1
    return _ok({"accepted": accepted})


#: How many songs one `POST refs/unavailable` may ask about (a page of results, an album, an artist's popular songs).
MAX_UNAVAILABLE_ASKED = 100


@router.post("/refs/unavailable")
def unavailable_refs(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    """Which of these songs the server already knows it cannot get (N-13), answered in the order asked: `null` (no known problem, a song the server has never
    seen, or one it could not read) or `{reason, message, since, retryAfter}`. A read: it makes no ref and asks YouTube nothing, so a phone can ask about every
    song of a list it is showing. The songs are named one of two ways, never both: `songs` (described as `POST refs/resolve` takes them: a Search is all
    catalogue songs, no ref yet) or `ids` (ref ids: the rows of the phone's own library, B-128; the server lists the feature `unavailable-ids`)."""
    songs, ids = body.get("songs"), body.get("ids")
    if (songs is None) == (ids is None):
        raise ApiError("validation", "Send either songs or ids, not both.")
    named = ids if ids is not None else songs
    if not isinstance(named, list) or not named or len(named) > MAX_UNAVAILABLE_ASKED:
        raise ApiError("validation", f"Send between 1 and {MAX_UNAVAILABLE_ASKED} songs.")
    if ids is not None and not all(isinstance(i, str) for i in named):
        raise ApiError("validation", "Ids are texts.")
    with services(request).db.read() as conn:
        return _ok({"items": refs.unavailable_for_ids(conn, named) if ids is not None else refs.unavailable_for(conn, named)})


@router.get("/refs/{ref_id}")
def get_ref(ref_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    with services(request).db.read() as conn:
        return _ok(refs.get_ref(conn, ref_id))
