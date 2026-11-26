"""Signing in and out, who I am, and my devices (docs/17 section 2, docs/32)."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import (
    library,
)
from ..accounts import LoginGuard
from ..auth import (
    Principal,
    issue_device,
    subsonic_credentials,
    subsonic_token,
)
from ..errors import ApiError
from ..ids import now_ms
from .common import API_PREFIX, _ok, _refuse_locked, accounts_of, client_address, get_principal, json_body, limiter_of, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


@router.post("/auth/login")
def login(request: Request, body: dict[str, Any] = Depends(json_body)) -> JSONResponse:
    """Signs in with the music server's login, once: the password is turned into a Subsonic token, checked, and dropped. The app keeps
    the device token it gets back instead. Wrong passwords are slowed (five a minute for one name from one address, thirty for one address)
    and never lock anybody: a lock is only the owner's own act (AUDIT B2)."""
    return _sign_in(request, body)


def _sign_in(request: Request, body: dict[str, Any], *, status: int = 200) -> JSONResponse:
    """The sign-in itself, also what a join asked again after a lost answer comes to (B15): the music server's login is checked, wrong ones are
    slowed per name and address, and a device comes back."""
    svc = services(request)
    user = body.get("username")
    password = body.get("password")
    if not isinstance(user, str) or not isinstance(password, str) or not user or not password:
        raise ApiError("validation", "Enter your username and password.")
    address = client_address(request)
    guard = LoginGuard(limiter_of(request))
    guard.refuse(user, address)
    _refuse_locked(svc, user)
    salt = secrets.token_hex(6)
    token = subsonic_token(password, salt)
    if subsonic_credentials({"u": user, "t": token, "s": salt}, {}) is None or not svc.verifier.verify(user, token, salt):
        guard.failed(user, address)
        accounts_of(request).failed_login(user)
        raise ApiError("unauthorized", "The username or the password was not accepted.")
    name = body.get("deviceName") if isinstance(body.get("deviceName"), str) else "Phone"
    kind = body.get("deviceKind") if isinstance(body.get("deviceKind"), str) else "phone"
    version = body.get("appVersion") if isinstance(body.get("appVersion"), str) else None
    with svc.db.tx() as conn:
        existing = conn.execute("SELECT * FROM person WHERE navidrome_user = ?", (user,)).fetchone()
        admin = existing is None and svc.verifier.is_admin(user, token, salt)
        person = library.ensure_person(conn, user, admin=admin)
        if person["locked"]:
            raise ApiError("forbidden", "This account is locked. Ask the owner of this server to unlock it.")
        conn.execute("UPDATE person SET failed_logins = 0 WHERE id = ?", (person["id"],))
        device_id, device_token = issue_device(conn, person["id"], str(name), str(kind), version)
        return _ok(
            {
                "deviceToken": device_token,
                "device": {"id": device_id, "name": str(name)},
                "person": {"id": person["id"], "name": person["display_name"], "role": person["role"]},
            },
            status,
        )


@router.post("/auth/logout")
def logout(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    if p.device_id is not None:
        with services(request).db.tx() as conn:
            # The device id may come from a header sent with the music server's login: it only counts when it is this person's own device.
            conn.execute(
                "UPDATE device SET revoked_at = ? WHERE id = ? AND person = ? AND revoked_at IS NULL",
                (now_ms(), p.device_id, p.person_id),
            )
        services(request).hub.end(p.person_id, device=p.device_id)
    return _ok()


@router.get("/me")
def me(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    with services(request).db.read() as conn:
        row = conn.execute("SELECT * FROM person WHERE id = ?", (p.person_id,)).fetchone()
        return _ok(
            {
                "id": row["id"],
                "name": row["display_name"],
                "username": row["navidrome_user"],
                "role": row["role"],
                "explicitOk": bool(row["explicit_ok"]),
                "federationOk": bool(row["federation_ok"]),
            }
        )


@router.get("/me/devices")
def devices(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    with services(request).db.read() as conn:
        rows = conn.execute(
            "SELECT id, name, kind, app_version, created_at, last_seen FROM device WHERE person = ? AND revoked_at IS NULL ORDER BY created_at",
            (p.person_id,),
        )
        return _ok(
            {
                "items": [
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "kind": r["kind"],
                        "appVersion": r["app_version"],
                        "createdAt": r["created_at"],
                        "lastSeen": r["last_seen"],
                        "thisDevice": r["id"] == p.device_id,
                    }
                    for r in rows
                ]
            }
        )


@router.delete("/me/devices/{device_id}")
def revoke_device(device_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    with services(request).db.tx() as conn:
        conn.execute(
            "UPDATE device SET revoked_at = ? WHERE id = ? AND person = ? AND revoked_at IS NULL",
            (now_ms(), device_id, p.person_id),
        )
    services(request).hub.end(p.person_id, device=device_id)  # its live connection closes too (AUDIT B5)
    return _ok()
