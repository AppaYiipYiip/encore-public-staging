"""What the admin pages ask of the computer, through the helper (docs/36 sections 3 and 4): backups, the away address, a restart.

Owner only, and a 404 to a public request, like every admin route. The server never does these things itself (it has no way to): each route sends one of the helper's seven actions and
answers with the helper's own sentence. A helper that is not installed is a calm answer on the pages that only read (`installed: false`, and how to get it) and a 503 with the same sentence on the
ones that change something. A change leaves a line in `audit_log` (who asked, what the helper said, never a secret); a read does not.

Restore and update are NOT routes: a restore needs the backup key's secret half, which is kept nowhere and must not pass through this server (`36` section 3); the Backups page says so in words.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import audit, host_status
from ..auth import Principal
from ..errors import ApiError
from ..helper import NOT_INSTALLED, HelperAnswer, HelperClient, HelperUnavailable
from .common import API_PREFIX, Services, _ok, get_principal, refuse_public, require_owner, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)

NIGHTLY_AT = "03:30"


def _installed(svc: Services) -> HelperClient | None:
    helper = svc.helper
    return helper if helper is not None and helper.available() else None


def _ask(svc: Services, action: str) -> HelperAnswer:
    helper = _installed(svc)
    if helper is None:
        raise ApiError("server_busy", NOT_INSTALLED, status=503)
    try:
        return helper.call(action)
    except HelperUnavailable as error:
        raise ApiError("server_busy", error.message, status=503) from error


def _change(svc: Services, p: Principal, action: str) -> HelperAnswer:
    """A request that changes something: the helper's answer, a refusal as 409 in the helper's own sentence, and a line in `audit_log` either way."""
    answer = _ask(svc, action)
    outcome = "done" if answer.failed is None else f"refused: {answer.failed}"
    with svc.db.tx() as conn:
        audit.record(
            conn, "helper", p.navidrome_user, f"{action} was asked from the admin pages by {p.navidrome_user}: {outcome}"
        )
    if answer.failed is not None:
        raise ApiError("conflict", answer.failed)
    return answer


def _backups(answer: HelperAnswer) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for item in answer.items:
        if len(item) != 5 or not item[2].isdigit() or not item[3].isdigit():
            continue
        pool, name, size, at, lock = item
        found.append({"pool": pool, "name": name, "bytes": int(size), "madeAt": int(at) * 1000, "locked": lock == "locked"})
    found.sort(key=lambda b: b["madeAt"], reverse=True)
    return found


@router.get("/admin/helper")
def helper_state(request: Request, _: None = Depends(refuse_public), p: Principal = Depends(get_principal)) -> JSONResponse:
    """Is there a helper to ask (the socket is there)? Nothing is sent to it."""
    require_owner(p)
    return _ok({"installed": _installed(services(request)) is not None, "how": "sudo encore helper install"})


@router.get("/admin/backups")
def list_backups(request: Request, _: None = Depends(refuse_public), p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    svc = services(request)
    body: dict[str, Any] = {
        "installed": False,
        "items": [],
        "nightlyAt": NIGHTLY_AT,
        "how": "sudo encore helper install",
        "restore": "sudo encore restore FILE",
    }
    if _installed(svc) is None:
        return _ok(body)
    answer = _ask(svc, "backup.list")
    return _ok({**body, "installed": True, "items": _backups(answer)})


@router.post("/admin/backups")
def make_backup(request: Request, _: None = Depends(refuse_public), p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    answer = _change(services(request), p, "backup.make")
    return _ok({"done": answer.done})


@router.get("/admin/away")
def away(request: Request, _: None = Depends(refuse_public), p: Principal = Depends(get_principal)) -> JSONResponse:
    """The address, what Tailscale on the computer says (`missing`, `signedout`, `ready`; `unknown` without a helper) and how long the key lasts, when the computer has said."""
    require_owner(p)
    svc = services(request)
    installed = _installed(svc) is not None
    tailscale = "unknown"
    if installed:
        tailscale = _ask(svc, "away.status").results.get("tailscale", "unknown")
    status = host_status.read(svc.settings.data_dir)
    return _ok(
        {
            "installed": installed,
            "address": svc.settings.away_url,
            "tailscale": tailscale,
            "keyExpiresAt": status.away_key_expires_at if status is not None else None,
            "how": "sudo encore funnel on",
        }
    )


@router.post("/admin/away/on")
def away_on(request: Request, _: None = Depends(refuse_public), p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    answer = _change(services(request), p, "away.on")
    return _ok({"done": answer.done, "reconnects": True})


@router.post("/admin/away/off")
def away_off(request: Request, _: None = Depends(refuse_public), p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    answer = _change(services(request), p, "away.off")
    return _ok({"done": answer.done, "reconnects": True})


@router.post("/admin/restart")
def restart(request: Request, _: None = Depends(refuse_public), p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    answer = _change(services(request), p, "restart")
    return _ok({"done": answer.done, "reconnects": True})
