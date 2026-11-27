"""People: invitations, joining, accounts, passwords, notifications, and the page an invitation link opens (docs/17 section 2, docs/32, W-05)."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import join_page as join_pages
from .. import (
    library,
)
from ..accounts import LoginGuard
from ..auth import (
    Principal,
    forget_credentials,
    subsonic_token,
)
from ..errors import ApiError
from ..ids import now_ms
from ..migration import SubsonicUser, migrate_from_navidrome
from ..notifications import DEFAULT_PAGE, MAX_PAGE
from .common import (
    API_PREFIX,
    _changed,
    _ok,
    accounts_of,
    client_address,
    get_principal,
    json_body,
    limiter_of,
    notifications_of,
    optional_body,
    require_owner,
    services,
)
from .session import _sign_in, me

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


# ------------------------------------------------------------------------------------------------ people


@router.get("/invites/check")
def check_invite(request: Request, code: str = "") -> JSONResponse:
    """What the join screen shows for a code before a name is chosen (no sign-in: the code is the key)."""
    limiter_of(request).refuse(f"join-address:{client_address(request)}", 20, 60)
    return _ok(accounts_of(request).check_invite(code))


@router.get("/notifications")
def list_notifications(
    request: Request, since: str = "0", limit: int = DEFAULT_PAGE, p: Principal = Depends(get_principal)
) -> JSONResponse:
    """The bell: the person's news, newest first (docs/tasks P2-15). `since` is the cursor the last answer gave."""
    if not since.isdigit():
        raise ApiError("validation", "The cursor is a number, as the server gave it.")
    if not 1 <= limit <= MAX_PAGE:
        raise ApiError("validation", f"Ask for between 1 and {MAX_PAGE} items.")
    return _ok(notifications_of(request).list(p.person_id, since=int(since), limit=limit))


@router.post("/notifications/read")
def read_notifications(
    request: Request, body: dict[str, Any] = Depends(optional_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    """Marks the news read, all of it or up to an id (`upTo`); safe to repeat."""
    up_to = body.get("upTo")
    if up_to is not None and (not isinstance(up_to, int) or isinstance(up_to, bool) or up_to < 0):
        raise ApiError("validation", "`upTo` is the id of an item.")
    return _ok({"unread": notifications_of(request).mark_read(p.person_id, up_to)})


@router.post("/invites")
def create_invite(
    request: Request, body: dict[str, Any] = Depends(optional_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    require_owner(p)
    return _ok({"invite": accounts_of(request).create_invite(p.person_id, role=body.get("role"), note=body.get("note"))}, 201)


@router.get("/invites")
def list_invites(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    return _ok({"items": accounts_of(request).list_invites()})


@router.delete("/invites/{invite_id}")
def revoke_invite(invite_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    return _ok({"revoked": accounts_of(request).revoke_invite(invite_id)})


@router.post("/auth/join")
def join(request: Request, body: dict[str, Any] = Depends(json_body)) -> JSONResponse:
    """The invited person's first sign-in: a name and a password of their own, an account on the music server, a device token back."""
    limiter_of(request).refuse(f"join-address:{client_address(request)}", 10, 60)
    name = body.get("deviceName") if isinstance(body.get("deviceName"), str) else "Phone"
    version = body.get("appVersion") if isinstance(body.get("appVersion"), str) else None
    code = str(body.get("code", ""))
    accounts = accounts_of(request)
    try:
        made = accounts.join(code, body.get("username"), body.get("password"), body.get("displayName"), str(name), version)
    except ApiError as error:
        # The answer to a join can be lost on the way (B15): the account was made and the invitation used. The same name asking again within a
        # few minutes is a sign-in, which still needs the password; anything else, and a wrong password, is the same answer as any dead code.
        if error.code != "not_found" or accounts.rejoin_person(code, body.get("username")) is None:
            raise
        try:
            return _sign_in(request, body, status=201)
        except ApiError as refused:
            if refused.code == "rate_limited":
                raise
            raise error from None
    return _ok(made, 201)


@router.get("/people")
def list_people(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    return _ok({"items": accounts_of(request).people()})


@router.patch("/people/{person_id}")
def update_person(
    person_id: str, request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    require_owner(p)
    return _ok({"person": accounts_of(request).update_person(p.person_id, person_id, body)})


@router.delete("/people/{person_id}")
def remove_person(person_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    accounts_of(request).remove_person(p.person_id, person_id)
    return _ok()


@router.post("/people/{person_id}/reset")
def start_reset(person_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    return _ok({"reset": accounts_of(request).create_reset(person_id)}, 201)


@router.post("/auth/reset")
def reset_password(request: Request, body: dict[str, Any] = Depends(json_body)) -> JSONResponse:
    """A forgotten password: the one-hour link the owner sent, and a new password; signs in on this device."""
    limiter_of(request).refuse(f"join-address:{client_address(request)}", 10, 60)
    name = body.get("deviceName") if isinstance(body.get("deviceName"), str) else "Phone"
    version = body.get("appVersion") if isinstance(body.get("appVersion"), str) else None
    return _ok(accounts_of(request).reset_password(str(body.get("code", "")), body.get("password"), str(name), version))


@router.post("/me/password")
def change_password(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    """A new password for the person signed in: the old one is checked first, and the other devices are signed out."""
    old = body.get("oldPassword")
    if not isinstance(old, str) or not old:
        raise ApiError("validation", "Enter your current password.")
    address = client_address(request)
    guard = LoginGuard(limiter_of(request))
    salt = secrets.token_hex(6)
    with guard.begin(p.navidrome_user, address):  # a slot while the music server is asked (P3-34 slice 2d)
        if not services(request).verifier.verify(p.navidrome_user, subsonic_token(old, salt), salt):
            guard.failed(p.navidrome_user, address)
            accounts_of(request).failed_login(p.navidrome_user)
            raise ApiError("unauthorized", "The current password was not accepted.")
    accounts_of(request).change_password(p.navidrome_user, body.get("newPassword"))
    with services(request).db.tx() as conn:
        conn.execute(
            "UPDATE device SET revoked_at = ? WHERE person = ? AND id IS NOT ? AND revoked_at IS NULL",
            (now_ms(), p.person_id, p.device_id),
        )
    # The old password's remembered yes is forgotten, and the other devices' live connections are closed (AUDIT B4, B5).
    forget_credentials(services(request).verifier, p.navidrome_user)
    services(request).hub.end(p.person_id, except_device=p.device_id)
    return _ok()


@router.patch("/me")
def update_me(request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)) -> JSONResponse:
    sets: list[str] = []
    values: list[Any] = []
    if "name" in body:
        shown = " ".join(str(body["name"]).split())[:60]
        if not shown:
            raise ApiError("validation", "A name cannot be empty.")
        sets.append("display_name = ?")
        values.append(shown)
    if "explicitOk" in body:
        if not isinstance(body["explicitOk"], bool):
            raise ApiError("validation", "explicitOk is true or false.")
        sets.append("explicit_ok = ?")
        values.append(1 if body["explicitOk"] else 0)
    if sets:
        with services(request).db.tx() as conn:
            conn.execute(f"UPDATE person SET {', '.join(sets)} WHERE id = ?", (*values, p.person_id))  # noqa: S608 - column names are fixed above
    return me(request, p)


@router.post("/migrate/navidrome")
def migrate_navidrome(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    """Brings the person's likes, saved albums, followed artists and playlists over from the music server, asked as them with the sign-in the
    phone sends in the body (`u`, `t`, `s`). Safe to run again, and from a second phone."""
    svc = services(request)
    user, token, salt = str(body.get("u", "")), str(body.get("t", "")), str(body.get("s", ""))
    if user.lower() != p.navidrome_user.lower() or not svc.verifier.verify(user, token, salt):
        raise ApiError("unauthorized", "The music server did not accept that login.")
    make = svc.music_as or (lambda u, t, s: SubsonicUser(svc.settings.navidrome_url, u, t, s))
    report = migrate_from_navidrome(svc.db, p.person_id, p.navidrome_user, make(user, token, salt))
    with svc.db.read() as conn:
        _changed(svc, p, library.latest_cursor(conn, p.person_id))
    return _ok({"report": report})


def join_page(code: str, request: Request, key: str | None = Query(None, alias="id")) -> Response:
    """`GET /encore/join/{code}`: what a person sees who taps an invitation link on a phone that opens it in the browser (docs/design W-05, D-39).
    Public, so it is built to leak nothing: a live invitation gets one page, and every other code (used, expired, revoked, unknown, malformed) gets one
    identical page with one status. It shares the invitation check's rate limit."""
    limiter_of(request).refuse(f"join-address:{client_address(request)}", 20, 60)
    svc = services(request)
    dead = HTMLResponse(join_pages.DEAD_PAGE, status_code=404, headers=join_pages.HEADERS)
    if svc.accounts is None or not join_pages.CODE_SHAPE.match(code):
        return dead
    try:
        invite = svc.accounts.check_invite(code)
    except ApiError:
        return dead
    origin = join_pages.public_origin(request.headers.get("host"), request.headers.get("x-forwarded-proto"), request.url.scheme)
    page = join_pages.valid_page(
        server_name=svc.settings.server_name,
        invited_by=invite.get("invitedBy"),
        code=code,
        origin=origin,
        key=key,
        expires_at_ms=invite.get("expiresAt"),
        app_url=svc.settings.app_url,
    )
    return HTMLResponse(page, headers=join_pages.HEADERS)
