"""Keeping songs on the server, how it is going, and the signed addresses of a song's audio and a cover (docs/17 section 3, docs/33)."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import (
    refs,
)
from ..auth import (
    COVER_PASS_SCOPE,
    COVER_PASS_TTL_S,
    STREAM_URL_TTL_S,
    Principal,
    sign_stream,
)
from ..errors import ApiError
from ..keep_progress import askable_refs, parse_group, parse_groups, progress, retryable_refs
from ..keep_watch import fingerprint
from ..scheduler import PROMOTE_MANY, Scheduler
from .common import (
    _COVER_ID,
    API_PREFIX,
    Services,
    _keep_state,
    _ok,
    _youtube_status,
    get_principal,
    json_body,
    services,
    want_kept,
)

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


# ------------------------------------------------------------------------------------------------ the audio of a ref


@router.post("/refs/{ref_id}/keep")
def keep_now(ref_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    """Somebody asked for this song to be on the server now (a download of a song the server does not keep yet): it is kept first in line."""
    svc = services(request)
    with svc.db.tx() as conn:
        ref_id = refs.canonical(conn, ref_id)  # an old id of a song merged into another (N-11) asks for the survivor
        if not refs.ref_exists(conn, ref_id):
            raise ApiError("not_found", "That song is not known to this server.")
        if _keep_state(svc, conn, ref_id)["state"] in ("none", "failed"):
            want_kept(svc, conn, p.person_id, [ref_id])
    if svc.scheduler is not None:
        svc.scheduler.promote("keep", ref_id)
    with svc.db.read() as conn:
        return _ok(_keep_state(svc, conn, ref_id, host=p.role == "owner"))


@router.post("/keep/progress")
def keep_progress(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    """How far the server is with keeping what this person has pinned for download, for many playlists, releases and the liked songs in one
    answer (P2-22 part 1, docs/17 "Keep progress"). A group the person does not have is left out. Asking changes nothing."""
    svc = services(request)
    if svc.scheduler is None or not svc.scheduler.handles("keep"):
        raise ApiError("not_found", "This server does not keep songs.")
    groups = parse_groups(body)
    answer = progress(svc.db, svc.scheduler, p.person_id, host=p.role == "owner", groups=groups)
    return _ok({"groups": answer, "youtube": _youtube_status(svc.youtube)})


def _ask_for(svc: Services, scheduler: Scheduler, person: str, ref_ids: list[str]) -> None:
    """A whole download is asked for: the songs the server does not have are wanted for this person (queued, or queued again after a failure) and move
    ahead of the background work, behind a single tap (`scheduler.PROMOTE_MANY`). Safe to repeat."""
    if not ref_ids:
        return
    with svc.db.tx() as conn:
        want_kept(svc, conn, person, ref_ids)
    scheduler.promote_many("keep", ref_ids, priority=PROMOTE_MANY)


@router.post("/keep/ask")
def keep_ask(request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)) -> JSONResponse:
    """The person pressed Download on playlists, releases or the liked songs (P2-22, B-62): ask the server for the songs it does not have yet, first in line
    behind a single tap, for as long as the person's pins last. The batched sibling of `POST refs/{id}/keep`, in the groups of `keep/progress`: a group the
    person does not have is left out of the answer, like one that does not exist, and nothing is started for it. The answer is those downloads as
    `keep/progress` gives them now, and how many songs were asked for. Safe to repeat. (`keep/watch` never does this: telling a phone how it goes asks for nothing.)"""
    svc = services(request)
    if svc.scheduler is None or not svc.scheduler.handles("keep"):
        raise ApiError("not_found", "This server does not keep songs.")
    groups = parse_groups(body)
    again = askable_refs(svc.db, svc.scheduler, p.person_id, groups)
    _ask_for(svc, svc.scheduler, p.person_id, again)
    answer = progress(svc.db, svc.scheduler, p.person_id, host=p.role == "owner", groups=groups)
    return _ok({"asked": len(again), "groups": answer, "youtube": _youtube_status(svc.youtube)})


@router.post("/keep/retry")
def keep_retry(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    """Asks the server again for the songs of ONE download that it could not get (the Retry button under "3 songs did not come"): the failed ones
    that asking again can help, first in line, the way `keep/ask` asks. A song YouTube does not have is left alone.
    The answer is that download as `keep/progress` would give it now, and how many songs were asked for. A download the person does not have is
    `not_found`, exactly as one that does not exist."""
    svc = services(request)
    if svc.scheduler is None or not svc.scheduler.handles("keep"):
        raise ApiError("not_found", "This server does not keep songs.")
    group = parse_group(body)
    again = retryable_refs(svc.db, svc.scheduler, p.person_id, group)
    if again is None:
        raise ApiError("not_found", "That download does not exist (any more).")
    _ask_for(svc, svc.scheduler, p.person_id, again)
    answer = progress(svc.db, svc.scheduler, p.person_id, host=p.role == "owner", groups=[group])
    return _ok({"retried": len(again), "group": answer[0] if answer else None, "youtube": _youtube_status(svc.youtube)})


@router.put("/keep/watch")
def keep_watch(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    """This device says which pinned downloads it is watching (the same groups as `POST keep/progress`; an empty list stops watching). The reply is the
    current answer, so a phone that has just connected needs no second call; from then on the server pushes `keep.progress` to this device when
    the answer changes. Only a signed-in device (it has a live connection to be told on)."""
    svc = services(request)
    if svc.scheduler is None or svc.keep_watch is None or not svc.scheduler.handles("keep"):
        raise ApiError("not_found", "This server does not keep songs.")
    if p.device_id is None:
        raise ApiError("validation", "Only a signed-in device can ask to be told.")
    groups = parse_groups(body, allow_empty=True)
    answer = progress(svc.db, svc.scheduler, p.person_id, host=p.role == "owner", groups=groups) if groups else []
    youtube = _youtube_status(svc.youtube)
    svc.keep_watch.watch(p.person_id, p.device_id, groups, fingerprint(answer, youtube))
    return _ok({"groups": answer, "youtube": youtube})


@router.get("/refs/{ref_id}/keep")
def keep_state(ref_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    svc = services(request)
    with svc.db.read() as conn:
        ref_id = refs.canonical(conn, ref_id)
        if not refs.ref_exists(conn, ref_id):
            raise ApiError("not_found", "That song is not known to this server.")
        return _ok(_keep_state(svc, conn, ref_id, host=p.role == "owner"))


@router.get("/refs/{ref_id}/stream-url")
def stream_url(ref_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    """The address to play a song from when the server has no file of it (or the app prefers it): signed, so a player that cannot set
    headers can use it, and valid for as long as a listen can last."""
    svc = services(request)
    with svc.db.read() as conn:
        # Signed for the survivor of a song merged into another (N-11): the address a player gets is the live one.
        ref_id = refs.canonical(conn, ref_id)
        if not refs.ref_exists(conn, ref_id):
            raise ApiError("not_found", "That song is not known to this server.")
    expires = int(time.time()) + STREAM_URL_TTL_S
    sig = sign_stream(svc.stream_key, p.person_id, ref_id, expires)
    return _ok({"url": f"/encore/stream/{ref_id}?p={p.person_id}&e={expires}&sig={sig}", "expiresAt": expires * 1000})


@router.get("/covers/pass")
def cover_pass(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    """One ticket that opens every picture for a week: a screen shows thirty covers, and a phone should not ask thirty times. It opens pictures
    and nothing else (it is signed over its own scope, never over a song)."""
    expires = int(time.time()) + COVER_PASS_TTL_S
    sig = sign_stream(services(request).stream_key, p.person_id, COVER_PASS_SCOPE, expires)
    return _ok({"pass": {"p": p.person_id, "e": expires, "sig": sig}, "expiresAt": expires * 1000})


@router.get("/covers/{cover_id}/url")
def cover_url(cover_id: str, request: Request, size: int | None = None, p: Principal = Depends(get_principal)) -> JSONResponse:
    """The address of a picture the server has (a cover), signed like a stream so an image view that cannot set headers can load it, and so a phone
    needs no login of the music server (docs/tasks P2-20)."""
    if not _COVER_ID.match(cover_id):
        raise ApiError("not_found", "There is no such picture.")
    if size is not None and not 16 <= size <= 2000:
        raise ApiError("validation", "A picture is asked for between 16 and 2000 pixels.")
    expires = int(time.time()) + STREAM_URL_TTL_S
    sig = sign_stream(services(request).stream_key, p.person_id, f"cover:{cover_id}", expires)
    tail = f"&size={size}" if size else ""
    return _ok({"url": f"/encore/cover/{cover_id}?p={p.person_id}&e={expires}&sig={sig}{tail}", "expiresAt": expires * 1000})
