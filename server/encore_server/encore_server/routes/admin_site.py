"""The admin site: its pages, its files and the first admin route (docs/36 section 2; `15` section 4).

Everything here answers **404 to a public request** (the same answer an unknown route of ours gets), is registered before the music server's catch-all, and lives under
`/encore/` (the namespace the gateway keeps for Encore). Two short addresses, `/admin` and `/setup`, are explicit redirects so that what a Host is told to type works.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import web
from ..auth import WEB_SESSION_IDLE_MS, WEB_SESSION_LIFETIME_MS, Principal
from ..errors import ApiError
from .common import API_PREFIX, _ok, get_principal, refuse_public, require_owner, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


@router.get("/admin/session")
def admin_session(request: Request, _: None = Depends(refuse_public), p: Principal = Depends(get_principal)) -> JSONResponse:
    """Who the admin page is signed in as, and how long this browser stays signed in. Owner only. A device that is not a browser (a phone that signed in to the
    page by a pairing, later) has no end: `session` says so."""
    require_owner(p)
    session: dict[str, Any] = {"kind": "device", "idleMs": None, "expiresAt": None}
    with services(request).db.read() as conn:
        row = (
            conn.execute("SELECT kind, created_at, last_seen FROM device WHERE id = ?", (p.device_id,)).fetchone()
            if p.device_id
            else None
        )
        person = conn.execute("SELECT display_name FROM person WHERE id = ?", (p.person_id,)).fetchone()
    if row is not None and row["kind"] == "web":
        seen = row["last_seen"] if row["last_seen"] is not None else row["created_at"]
        session = {
            "kind": "browser",
            "idleMs": WEB_SESSION_IDLE_MS,
            "expiresAt": min(row["created_at"] + WEB_SESSION_LIFETIME_MS, seen + WEB_SESSION_IDLE_MS),
        }
    return _ok(
        {
            "person": {"id": p.person_id, "name": person["display_name"] if person else p.navidrome_user, "role": p.role},
            "session": session,
        }
    )


def admin_page(request: Request) -> Response:
    """`GET /encore/admin`: the page of the admin site. It holds no data: everything it shows it asks the admin routes for, signed in."""
    refuse_public(request)
    body = web.page("admin")
    assert body is not None
    return HTMLResponse(body if request.method != "HEAD" else b"", headers=web.PAGE_HEADERS)


def web_file(path: str, request: Request) -> Response:
    """`GET /encore/web/{path}`: a script, a stylesheet or a font of the site (a path that is not one is the same 404 as any unknown route)."""
    refuse_public(request)
    found = web.asset(path)
    if found is None:
        raise ApiError("not_found")
    body, kind = found
    return Response(content=body if request.method != "HEAD" else b"", media_type=kind, headers=web.ASSET_HEADERS)


def short_admin(request: Request) -> Response:
    """`GET /admin`: the address a Host types. To the page, which is the same for a public request as any unknown path: 404."""
    refuse_public(request)
    return RedirectResponse("/encore/admin", status_code=302, headers={"Cache-Control": "no-store"})
