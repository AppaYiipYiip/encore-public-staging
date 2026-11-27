"""The add-ons: list them, change one's state (docs/35, docs/36 section 4). Owner only, a 404 to a public request, and the operation is `ops/addon.py` (the `encore addon`
command is the other door onto it)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..addons import AddOn
from ..auth import Principal
from ..ops import addon as ops_addon
from .common import API_PREFIX, _ok, get_principal, json_body, refuse_public, require_owner, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


def running_by(request: Request) -> ops_addon.Running:
    settings = services(request).settings
    return lambda addon: addon.running(settings)


@router.get("/admin/addons")
def list_addons(request: Request, _: None = Depends(refuse_public), p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    return _ok({"items": ops_addon.list_addons(services(request).db, running_by(request))})


@router.put("/admin/addons/{addon_id}")
def put_addon(
    addon_id: str,
    request: Request,
    body: dict[str, Any] = Depends(json_body),
    _: None = Depends(refuse_public),
    p: Principal = Depends(get_principal),
) -> JSONResponse:
    require_owner(p)
    item = ops_addon.set_state(
        services(request).db,
        running_by(request),
        addon_id,
        body.get("state"),
        by=p.person_id,
        risk_text_version=body.get("riskTextVersion"),
    )
    log.info("add-on %s chosen as %s by %s", addon_id, item["state"], p.person_id)
    return _ok({"addon": item})


__all__: list[str] = ["AddOn", "router"]
