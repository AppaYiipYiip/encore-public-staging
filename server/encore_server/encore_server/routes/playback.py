"""The one playback state a person's devices share, and taking it over (docs/17 section 5)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import (
    playback,
)
from ..auth import (
    Principal,
)
from ..errors import ApiError
from .common import API_PREFIX, _ok, get_principal, json_body, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


# ------------------------------------------------------------------------------------------------ playback


@router.get("/playback")
def get_playback(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    with services(request).db.read() as conn:
        return _ok({"state": playback.get_state(conn, p.person_id)})


@router.put("/playback")
def put_playback(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    svc = services(request)
    with svc.db.tx() as conn:
        state, taken_from = playback.put_state(conn, p.person_id, body, p.device_id)
    svc.hub.publish(p.person_id, {"type": "playback.changed", "state": state}, except_device=p.device_id)
    if taken_from is not None:
        svc.hub.publish(p.person_id, {"type": "device.takeover", "by": p.device_id}, only_device=taken_from)
    return _ok({"state": state})


@router.post("/playback/claim")
def claim_playback(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    if p.device_id is None:
        raise ApiError("validation", "Only a signed-in device can take over playback.")
    svc = services(request)
    with svc.db.tx() as conn:
        state, previous = playback.claim(conn, p.person_id, p.device_id)
    svc.hub.publish(p.person_id, {"type": "playback.changed", "state": state}, except_device=p.device_id)
    if previous is not None:
        svc.hub.publish(p.person_id, {"type": "device.takeover", "by": p.device_id}, only_device=previous)
    return _ok({"state": state})
