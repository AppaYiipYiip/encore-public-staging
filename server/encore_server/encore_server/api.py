"""The HTTP API (docs/17): `/encore/api/v1/...` and the live channel `/encore/live`.

One error shape (errors.py), ids with prefixes, idempotent writes, state-based `library/changes`. Handlers are plain functions run in
worker threads (SQLite and the music server's check block briefly); the live sockets stay on the event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import re
import secrets
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from . import API_VERSION, MIN_APP_VERSION, __version__, gateway, library, netaddr, playback, refs
from . import join_page as join_pages
from .accounts import Accounts, Limiter, LoginGuard
from .auth import (
    COVER_PASS_SCOPE,
    COVER_PASS_TTL_S,
    STREAM_URL_TTL_S,
    NavidromeVerifier,
    Principal,
    Verifier,
    bearer_token,
    forget_credentials,
    hash_token,
    issue_device,
    person_may_listen,
    sign_stream,
    stream_secret,
    subsonic_credentials,
    subsonic_token,
    valid_stream_signature,
)
from .bodylimit import BodyLimit
from .config import Settings
from .cover_finder import CoverFinder, deezer_lookup
from .db import Database
from .errors import ApiError
from .identity import NONCE_PATTERN, ServerIdentity, load_or_create
from .ids import is_id, now_ms
from .imports.service import ImportService
from .keep_progress import MAX_RELEASE_SONGS, parse_groups, progress
from .keep_watch import KeepWatch, fingerprint
from .keeper.keeper import Keeper, KeepSettings
from .keeper.triggers import want_kept as _want_kept
from .live import END, Hub
from .migration import SubsonicUser, migrate_from_navidrome
from .navidrome import NavidromeClient
from .navidrome_admin import NavidromeAdmin
from .notifications import DEFAULT_PAGE, MAX_PAGE, Notifications
from .quiet import InFlight, InFlightMiddleware
from .scanner import LibraryLinker
from .scheduler import Scheduler
from .sources.youtube.errors import DownloadError
from .sources.youtube.pace import Pacer
from .sources.youtube.rest import DbRestStore, Rest
from .sources.youtube.source import YoutubeSource, wanted_from_ref
from .sources.youtube.stream import StreamError
from .sources.youtube.tools import Active, ToolStore
from .sources.youtube.updater import Tools, create_tools

log = logging.getLogger("encore_server.api")

FEATURES = ["library", "playback", "live", "refs"]


@dataclass
class Services:
    settings: Settings
    db: Database
    hub: Hub
    verifier: Verifier
    youtube: YoutubeSource | None = None
    scheduler: Scheduler | None = None
    keeper: Keeper | None = None
    linker: LibraryLinker | None = None
    imports: ImportService | None = None
    accounts: Accounts | None = None
    notifications: Notifications | None = None
    limiter: Limiter | None = None
    music_as: Callable[[str, str, str], SubsonicUser] | None = None
    #: The yt-dlp updater and the restart that waits for a quiet moment (docs/11 ADR-R39); `None` when off.
    tools: Tools | None = None
    #: Who this server is: its key and the id made from it (docs/11 ADR-R40).
    identity: ServerIdentity | None = None
    #: The music server as this server's own account: kept songs and covers are passed on through it, so a phone needs no login of the music server.
    music: NavidromeClient | None = None
    #: Tells a device how its downloads are going (`PUT keep/watch`, the live event `keep.progress`); `None` when this server does not keep songs.
    keep_watch: KeepWatch | None = None


def services(request: Request) -> Services:
    return request.app.state.services  # type: ignore[no-any-return]


# ------------------------------------------------------------------------------------------------ who is asking


def get_principal(request: Request) -> Principal:
    svc = services(request)
    headers = dict(request.headers.items())
    token = bearer_token(headers.get("authorization"))
    if token is not None:
        with svc.db.tx() as conn:
            row = conn.execute(
                "SELECT d.id AS device, p.id AS person, p.navidrome_user AS user, p.role AS role, p.locked AS locked"
                " FROM device d JOIN person p ON p.id = d.person WHERE d.token_hash = ? AND d.revoked_at IS NULL",
                (hash_token(token),),
            ).fetchone()
            if row is None or row["locked"]:
                raise ApiError("unauthorized", "This device is not signed in any more. Sign in again.")
            conn.execute(
                "UPDATE device SET last_seen = ? WHERE id = ? AND (last_seen IS NULL OR last_seen < ?)",
                (now_ms(), row["device"], now_ms() - 60_000),
            )
            return Principal(row["person"], row["user"], row["role"], row["device"])

    creds = subsonic_credentials(dict(request.query_params.items()), headers)
    if creds is None:
        raise ApiError("unauthorized")
    user, subsonic, salt = creds
    check_music_login(request, user, subsonic, salt)
    with svc.db.tx() as conn:
        existing = conn.execute("SELECT * FROM person WHERE navidrome_user = ?", (user,)).fetchone()
        admin = existing is None and svc.verifier.is_admin(user, subsonic, salt)
        person = library.ensure_person(conn, user, admin=admin)
        if person["locked"]:
            raise ApiError("forbidden", "This account is locked.")
        device = request.headers.get("x-encore-device")
        return Principal(person["id"], user, person["role"], device if device and is_id(device, "dv") else None)


def check_music_login(request: Request, user: str, subsonic: str, salt: str) -> None:
    """The one place a music-server login (`u`, `t`, `s`) is checked, for the Encore API and for the Subsonic API that is open to the internet
    (AUDIT B12b: it used to be a second copy of nothing, i.e. no check at all). Raises an `ApiError` to refuse.

    Not a login the music server has already vouched for: a guesser is slowed before the music server is asked, a locked account says so
    whatever the password (so its answer never confirms a right one), and a wrong answer is counted (AUDIT B1, B2). A wrong answer is logged
    with the address it was counted against, never with the token; that is at most thirty lines an address a minute, because a refused guess is
    not counted again."""
    svc = services(request)
    known = getattr(svc.verifier, "known_good", None)
    if known is not None and known(user, subsonic, salt):
        return
    address = client_address(request)
    guard = LoginGuard(limiter_of(request))
    guard.refuse(user, address)
    _refuse_locked(svc, user)
    if not svc.verifier.verify(user, subsonic, salt):
        guard.failed(user, address)
        log.info("a wrong music-server login was refused: name %r, counted against address %s", user, address)
        raise ApiError("unauthorized", "The music server did not accept that login.")


async def authorize_public_subsonic(request: Request) -> None:
    """A call to the Subsonic API that comes from the internet is signed in like any other call to this server (AUDIT B12b). Only the token login
    (`u`, `t`, `s`) is understood: a plain password (`p=`, `p=enc:`) or an API key is refused, because a password a stranger can try without limit
    is exactly what this guard exists to stop (docs/21: Subsonic apps that send only `p=` cannot sign in through the public address)."""
    creds = subsonic_credentials(dict(request.query_params.items()), dict(request.headers.items()))
    if creds is None:
        raise ApiError(
            "unauthorized", "Sign in with a token login (u, t and s). A plain password is not accepted from the internet."
        )
    await run_in_threadpool(_check_public_subsonic, request, *creds)  # asking the music server is a blocking call


def _check_public_subsonic(request: Request, user: str, subsonic: str, salt: str) -> None:
    # A remembered yes must never open a locked account: the Encore API looks the person up after the check, this door has no such later step.
    _refuse_locked(services(request), user)
    check_music_login(request, user, subsonic, salt)


def _refuse_locked(svc: Services, user: str) -> None:
    """A locked account is refused before its password is looked at, so the answer never tells anybody whether a guess was right."""
    with svc.db.read() as conn:
        row = conn.execute("SELECT locked FROM person WHERE navidrome_user = ?", (user,)).fetchone()
    if row is not None and row["locked"]:
        raise ApiError("forbidden", "This account is locked. Ask the owner of this server to unlock it.")


async def json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except ValueError:
        raise ApiError("validation", "The request body must be JSON.") from None
    if not isinstance(data, dict):
        raise ApiError("validation", "The request body must be a JSON object.")
    return data


async def optional_body(request: Request) -> dict[str, Any]:
    """The JSON body when there is one (a like needs none); anything else is no body."""
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _server_time() -> int:
    return now_ms()


def _ok(payload: dict[str, Any] | None = None, status: int = 200) -> JSONResponse:
    return JSONResponse({**(payload or {}), "serverTime": _server_time()}, status_code=status)


# ------------------------------------------------------------------------------------------------ the routes

router = APIRouter(prefix="/encore/api/v1")


def _youtube_status(youtube: YoutubeSource | None) -> dict[str, Any]:
    """`{state: off|ok|resting, resumesInSec}`: whether YouTube is holding this server back, and for how long (the same in `info` and in the keep progress)."""
    if youtube is not None and hasattr(youtube, "status"):
        return youtube.status()
    return {"state": "off", "resumesInSec": 0}


@router.get("/info")
def info(request: Request, challenge: str | None = None) -> JSONResponse:
    """What this server is, without a login. With `?challenge=<nonce>` the answer is also signed, so a phone can tell this server from anything else
    that answers at the same address (docs/11 ADR-R40)."""
    svc = services(request)
    if challenge is not None and NONCE_PATTERN.fullmatch(challenge) is None:
        raise ApiError("validation")
    who = svc.identity
    who_fields: dict[str, str] = {}
    if who is not None:
        who_fields = who.answer(challenge) if challenge is not None else who.public_fields()
    return _ok(
        {
            **who_fields,
            "apiVersion": API_VERSION,
            "minAppVersion": MIN_APP_VERSION,
            "serverVersion": __version__,
            "name": svc.settings.server_name,
            "features": [*FEATURES, *(["keep"] if svc.keeper is not None else [])],
            "youtube": _youtube_status(svc.youtube),
            **({"tools": svc.tools.status()} if svc.tools is not None else {}),
        }
    )


@router.get("/server")
def server_addresses(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    """The server's own list of addresses, for a signed-in phone to keep fresh: the app never asks the person to type one (docs/11 ADR-R40)."""
    svc = services(request)
    who = svc.identity
    found = [
        {"kind": kind, "url": url} for kind, url in (("home", svc.settings.home_url), ("away", svc.settings.away_url)) if url
    ]
    return _ok({"serverId": who.server_id if who else None, "name": svc.settings.server_name, "addresses": found})


def client_address(request: Request) -> str:
    """Who is asking, for every limit: the address of the connection; and only when that connection is a proxy of ours (this machine, the home or
    Docker network, Tailscale, or one the owner listed) the address it says it forwarded: the right-most one that is not itself a proxy, never the
    client-written first one (AUDIT B11, `netaddr`)."""
    peer = request.client.host if request.client else ""
    extra = netaddr.networks(services(request).settings.trusted_proxies)
    return netaddr.client_address(peer, request.headers.get("x-forwarded-for"), extra)


def is_public_request(request: Request) -> bool:
    """Did this request come in from the public internet (through the away address, or from an address that is not ours)? The gateway lets such a
    request reach only the Subsonic API of the music server (AUDIT B12)."""
    away = services(request).settings.away_url
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower() if "]" not in (request.headers.get("host") or "") else ""
    if away and host and host == (urlparse(away).hostname or "").lower():
        return True
    return netaddr.is_public(client_address(request))


def accounts_of(request: Request) -> Accounts:
    service = services(request).accounts
    assert service is not None
    return service


def notifications_of(request: Request) -> Notifications:
    service = services(request).notifications
    assert service is not None
    return service


def limiter_of(request: Request) -> Limiter:
    limiter = services(request).limiter
    assert limiter is not None
    return limiter


def require_owner(p: Principal) -> None:
    if p.role != "owner":
        raise ApiError("forbidden", "Only the owner of this server can do that.")


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
    guard.refuse(p.navidrome_user, address)
    salt = secrets.token_hex(6)
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


@router.get("/refs/{ref_id}")
def get_ref(ref_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    with services(request).db.read() as conn:
        return _ok(refs.get_ref(conn, ref_id))


# ------------------------------------------------------------------------------------------------ the audio of a ref


def _keep_state(svc: Services, conn: Any, ref_id: str) -> dict[str, Any]:
    linked = conn.execute("SELECT 1 FROM song_file WHERE ref = ? AND navidrome_song_id IS NOT NULL LIMIT 1", (ref_id,)).fetchone()
    if linked is not None:
        return {"state": "kept"}
    if svc.scheduler is None or not svc.scheduler.handles("keep"):
        return {"state": "unavailable", "reason": "This server does not keep songs."}
    item = svc.scheduler.state_of("keep", ref_id)
    if item is None or item["state"] in ("cancelled", "done"):
        return {"state": "none"}
    state = {"queued": "queued", "running": "keeping", "failed": "failed"}.get(str(item["state"]), "queued")
    return {"state": state, **({"reason": item["error"]} if item["error"] else {})}


@router.post("/refs/{ref_id}/keep")
def keep_now(ref_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    """Somebody asked for this song to be on the server now (a download of a song the server does not keep yet): it is kept first in line."""
    svc = services(request)
    with svc.db.tx() as conn:
        if not refs.ref_exists(conn, ref_id):
            raise ApiError("not_found", "That song is not known to this server.")
        if _keep_state(svc, conn, ref_id)["state"] in ("none", "failed"):
            want_kept(svc, conn, p.person_id, [ref_id])
    if svc.scheduler is not None:
        svc.scheduler.promote("keep", ref_id)
    with svc.db.read() as conn:
        return _ok(_keep_state(svc, conn, ref_id))


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
        if not refs.ref_exists(conn, ref_id):
            raise ApiError("not_found", "That song is not known to this server.")
        return _ok(_keep_state(svc, conn, ref_id))


@router.get("/refs/{ref_id}/stream-url")
def stream_url(ref_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    """The address to play a song from when the server has no file of it (or the app prefers it): signed, so a player that cannot set
    headers can use it, and valid for as long as a listen can last."""
    svc = services(request)
    with svc.db.tx() as conn:
        if not refs.ref_exists(conn, ref_id):
            raise ApiError("not_found", "That song is not known to this server.")
        secret = stream_secret(conn)
    expires = int(time.time()) + STREAM_URL_TTL_S
    sig = sign_stream(secret, p.person_id, ref_id, expires)
    return _ok({"url": f"/encore/stream/{ref_id}?p={p.person_id}&e={expires}&sig={sig}", "expiresAt": expires * 1000})


_COVER_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


@router.get("/covers/pass")
def cover_pass(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    """One ticket that opens every picture for a week: a screen shows thirty covers, and a phone should not ask thirty times. It opens pictures
    and nothing else (it is signed over its own scope, never over a song)."""
    with services(request).db.tx() as conn:
        secret = stream_secret(conn)
    expires = int(time.time()) + COVER_PASS_TTL_S
    sig = sign_stream(secret, p.person_id, COVER_PASS_SCOPE, expires)
    return _ok({"pass": {"p": p.person_id, "e": expires, "sig": sig}, "expiresAt": expires * 1000})


@router.get("/covers/{cover_id}/url")
def cover_url(cover_id: str, request: Request, size: int | None = None, p: Principal = Depends(get_principal)) -> JSONResponse:
    """The address of a picture the server has (a cover), signed like a stream so an image view that cannot set headers can load it, and so a phone
    needs no login of the music server (docs/tasks P2-20)."""
    if not _COVER_ID.match(cover_id):
        raise ApiError("not_found", "There is no such picture.")
    if size is not None and not 16 <= size <= 2000:
        raise ApiError("validation", "A picture is asked for between 16 and 2000 pixels.")
    with services(request).db.tx() as conn:
        secret = stream_secret(conn)
    expires = int(time.time()) + STREAM_URL_TTL_S
    sig = sign_stream(secret, p.person_id, f"cover:{cover_id}", expires)
    tail = f"&size={size}" if size else ""
    return _ok({"url": f"/encore/cover/{cover_id}?p={p.person_id}&e={expires}&sig={sig}{tail}", "expiresAt": expires * 1000})


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


def cover(cover_id: str, request: Request) -> Response:
    """`GET /encore/cover/{id}`: a picture from the music server, behind a signed address."""
    svc = services(request)
    query = request.query_params
    with svc.db.tx() as conn:
        secret = stream_secret(conn)
    try:
        expires = int(query.get("e", "0"))
        size = int(query["size"]) if query.get("size") else None
    except ValueError:
        raise ApiError("validation", "That address is not right.") from None
    person, sig = query.get("p", ""), query.get("sig", "")
    with svc.db.read() as conn:
        still_here = person_may_listen(conn, person)
    if (
        not still_here
        or not _COVER_ID.match(cover_id)
        or not (
            valid_stream_signature(secret, person, f"cover:{cover_id}", expires, sig)
            or valid_stream_signature(secret, person, COVER_PASS_SCOPE, expires, sig)
        )
    ):
        raise ApiError("unauthorized", "This picture address has expired. Ask the app for it again.")
    if size is not None and not 16 <= size <= 2000:
        raise ApiError("validation", "A picture is asked for between 16 and 2000 pixels.")
    found = svc.music.cover(cover_id, size) if svc.music is not None and svc.music.configured else None
    if found is None:
        raise ApiError("not_found", "There is no such picture.")
    content, kind = found
    return Response(
        content=content if request.method != "HEAD" else b"", media_type=kind, headers={"Cache-Control": "private, max-age=86400"}
    )


_UNAVAILABLE_REASON = {"not_found": "not_found", "unavailable": "removed", "age_restricted": "age_restricted"}


def _stream_error(error: StreamError, youtube: Any = None) -> ApiError:
    if error.code in _UNAVAILABLE_REASON:
        return ApiError("song_unavailable", error.message, details={"reason": _UNAVAILABLE_REASON[error.code]})
    if error.code == "blocked":
        left = youtube.resting_for() if youtube is not None and hasattr(youtube, "resting_for") else 0
        return ApiError("source_busy", error.message, retry_after_ms=int(left * 1000) or None)
    if error.code == "slow":
        return ApiError("upstream_timeout", error.message)
    return ApiError("source_unreachable", error.message)


def stream(ref_id: str, request: Request) -> StreamingResponse:
    """`GET /encore/stream/{ref}`: the song's audio from YouTube, passed on as it arrives, with Range (docs/04 section 4)."""
    svc = services(request)
    query = request.query_params
    with svc.db.tx() as conn:
        secret = stream_secret(conn)
        person = query.get("p", "")
        try:
            expires = int(query.get("e", "0"))
        except ValueError:
            expires = 0
        if not valid_stream_signature(secret, person, ref_id, expires, query.get("sig", "")) or not person_may_listen(
            conn, person
        ):
            raise ApiError("unauthorized", "This song address has expired. Ask the app to play it again.")
        ref = refs.get_ref(conn, ref_id)
    # The server decides where the audio comes from: its own copy when it keeps one (as its own account at the music server, `Range` and all),
    # YouTube otherwise. The phone asks for the same address either way (docs/tasks P2-20).
    kept = (ref.get("file") or {}).get("navidromeSongId")
    if kept and svc.music is not None and svc.music.configured:
        own = svc.music.open_stream(
            str(kept),
            request.headers.get("range"),
            max_bit_rate=_bit_rate(query.get("maxBitRate")),
            fmt=_audio_format(query.get("format")),
            estimate_length=_flag(query.get("estimateContentLength")),
        )
        if own is not None:
            return _pass_on(own, request)
    if svc.youtube is None:
        raise ApiError("source_unreachable", "This server cannot fetch songs from YouTube.")
    try:
        upstream = svc.youtube.open(wanted_from_ref(ref), request.headers.get("range"))
    except StreamError as error:
        raise _stream_error(error, svc.youtube) from error
    except DownloadError as error:
        raise _stream_error(StreamError(error.code), svc.youtube) from error
    return _pass_on(upstream, request)


def _pass_on(upstream: Any, request: Request) -> StreamingResponse:
    headers = {**upstream.headers, "Cache-Control": "no-store"}
    body = iterate_in_threadpool(upstream.body) if request.method != "HEAD" else iter(())
    if request.method == "HEAD":
        upstream.close()
    return StreamingResponse(
        body, status_code=upstream.status, headers=headers, media_type=headers.pop("Content-Type", None), background=None
    )


_BIT_RATES = frozenset({0, 32, 48, 64, 96, 112, 128, 160, 192, 224, 256, 320})
_FORMATS = frozenset({"mp3", "opus", "aac", "raw"})


def _bit_rate(value: str | None) -> int | None:
    """The quality cap a phone asks for (the setting for its network): one of the usual rates, or an error in words."""
    if value is None or value == "":
        return None
    if not value.isdigit() or int(value) not in _BIT_RATES:
        raise ApiError("validation", "That is not a quality this server offers.")
    return int(value) or None


def _flag(value: str | None) -> bool:
    """A download asking for the length of a transcoded song up front (so its progress can be shown): `true`, or nothing."""
    if value is None or value == "":
        return False
    if value != "true":
        raise ApiError("validation", "That is not something this server understands.")
    return True


def _audio_format(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if value not in _FORMATS:
        raise ApiError("validation", "That is not an audio format this server offers.")
    return None if value == "raw" else value


# ------------------------------------------------------------------------------------------------ the library


def _changed(svc: Services, p: Principal, conn_cursor: int) -> None:
    svc.hub.publish(p.person_id, {"type": "library.changed", "cursor": str(conn_cursor)}, except_device=p.device_id)


@router.get("/library/changes")
def library_changes(request: Request, since: str = "0", p: Principal = Depends(get_principal)) -> JSONResponse:
    try:
        cursor = int(since)
    except ValueError:
        raise ApiError("validation", "The cursor is a number, as the server gave it.") from None
    with services(request).db.read() as conn:
        return _ok(library.changes(conn, p.person_id, max(0, cursor)))


@router.get("/library/files")
def library_files(request: Request, since: str = "0", limit: int = 500, p: Principal = Depends(get_principal)) -> JSONResponse:
    """The songs this server keeps, as they change: the app's browse index of the server's files (docs/18 section 2)."""
    try:
        cursor = max(0, int(since))
    except ValueError:
        raise ApiError("validation", "The cursor is a number, as the server gave it.") from None
    with services(request).db.read() as conn:
        return _ok(library.files_since(conn, cursor, max(1, min(limit, library.FILES_PAGE))))


def want_kept(svc: Services, conn: sqlite3.Connection, person: str, ref_ids: list[str]) -> None:
    _want_kept(svc.scheduler, conn, person, ref_ids)


def _item_route(
    kind: str, request: Request, target: str, p: Principal, *, add: bool, body: dict[str, Any] | None = None
) -> JSONResponse:
    svc = services(request)
    with svc.db.tx() as conn:
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
        for ref_id in ref_ids:
            if not refs.ref_exists(conn, ref_id):
                raise ApiError("not_found", "That song is not known to this server.", details={"ref": ref_id})
        changed = library.set_item(conn, p.person_id, "saved_album", album_id[:100], at=body.get("at"))
        library.add_album_refs(conn, p.person_id, album_id[:100], ref_ids)
        # Songs whose keep failed before are asked for again, like a download does (`keep_now`); the rest are kept once.
        want_kept(svc, conn, p.person_id, [r for r in ref_ids if _keep_state(svc, conn, r)["state"] in ("none", "failed")])
        cursor = library.latest_cursor(conn, p.person_id)
    if svc.scheduler is not None:
        for ref_id in ref_ids:
            svc.scheduler.promote("keep", ref_id)
    if changed:
        _changed(svc, p, cursor)
    with svc.db.read() as conn:
        keep = {ref_id: _keep_state(svc, conn, ref_id) for ref_id in ref_ids}
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
    from .ids import new_id

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
        want_kept(svc, conn, p.person_id, [str(s.get("ref")) for s in songs])
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


@router.post("/plays")
def post_play(request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)) -> JSONResponse:
    with services(request).db.tx() as conn:
        stored = library.record_play(
            conn,
            p.person_id,
            play_id=body.get("id"),
            ref=str(body.get("ref", "")),
            at=body.get("at"),
            ms_played=body.get("msPlayed"),
            device=p.device_id,
            context=body.get("context"),
        )
        svc = services(request)
        listened = body.get("msPlayed")
        if stored and svc.scheduler is not None and isinstance(listened, int) and listened >= library.MIN_COUNTED_PLAY_MS:
            ref_id = str(body.get("ref", ""))
            if library.played_on_days(conn, ref_id) >= svc.settings.keep_after_play_days:
                want_kept(svc, conn, p.person_id, [ref_id])
    return _ok({"stored": stored}, 201 if stored else 200)


# ------------------------------------------------------------------------------------------------ imports


def imports_of(request: Request) -> ImportService:
    service = services(request).imports
    assert service is not None
    return service


@router.post("/imports")
def create_import(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    """A link or a list of songs becomes a playlist at once; matching and keeping go on in the background (docs/tasks P2-04)."""
    return _ok(imports_of(request).create(p.person_id, body), 201)


@router.get("/imports")
def list_imports(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _ok({"imports": imports_of(request).listing(p.person_id)})


@router.get("/imports/{import_id}")
def get_import(import_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _ok({"import": imports_of(request).get(p.person_id, import_id)})


@router.get("/imports/{import_id}/entries")
def get_import_entries(import_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _ok({"entries": imports_of(request).entries(p.person_id, import_id)})


@router.post("/imports/{import_id}/stop")
def stop_import(import_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _ok({"import": imports_of(request).stop(p.person_id, import_id)})


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


# ------------------------------------------------------------------------------------------------ the live channel

PING_EVERY_S = 25.0


async def live(websocket: WebSocket) -> None:
    """`/encore/live`: the first message is `{"type": "auth", "token": "ed_..."}` (a device token); then the server sends events."""
    svc: Services = websocket.app.state.services
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        token = first.get("token") if isinstance(first, dict) and first.get("type") == "auth" else None
        if not isinstance(token, str):
            await websocket.close(code=4401)
            return
        with svc.db.read() as conn:
            row = conn.execute(
                "SELECT d.id AS device, d.person AS person FROM device d JOIN person p ON p.id = d.person"
                " WHERE d.token_hash = ? AND d.revoked_at IS NULL AND p.locked = 0",
                (hash_token(token),),
            ).fetchone()
            cursor = library.latest_cursor(conn, row["person"]) if row else 0
        if row is None:
            await websocket.close(code=4401)
            return
    except (TimeoutError, ValueError, WebSocketDisconnect):
        await websocket.close(code=4400)
        return

    connection = svc.hub.attach(row["person"], row["device"])
    try:
        await websocket.send_json({"type": "hello", "serverTime": now_ms(), "cursor": str(cursor)})
        while True:
            try:
                event = await asyncio.wait_for(connection.queue.get(), timeout=PING_EVERY_S)
            except TimeoutError:
                event = {"type": "ping", "serverTime": now_ms()}
            if connection.ended or event is END:
                await websocket.close(code=4401)  # the device was signed out, revoked, locked or removed (AUDIT B5)
                return
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        svc.hub.detach(connection)


# ------------------------------------------------------------------------------------------------ the application


def _default_youtube(settings: Settings, database: Database) -> YoutubeSource | None:
    """The real YouTube source, when its libraries are installed (a server without them still runs: songs it keeps still play)."""

    def remember(ref_id: str, video_id: str) -> None:
        with database.tx() as conn:
            refs.remember_video(conn, ref_id, video_id)

    if importlib.util.find_spec("yt_dlp") is None or importlib.util.find_spec("ytmusicapi") is None:
        log.warning("yt-dlp or ytmusicapi is not installed: songs that are not kept cannot be streamed")
        return None
    return YoutubeSource(
        settings.data_dir / "work",
        fast_clients=("visionos",),
        fault=settings.fault,
        remember_video=remember,
        rest=Rest(store=DbRestStore(database)),
        pace=Pacer(settings.youtube_pace_s) if settings.youtube_pace_s > 0 else None,
    )


def _default_tools(
    settings: Settings,
    youtube: YoutubeSource | None,
    scheduler: Scheduler | None,
    in_flight: InFlight,
    active: Active | None,
) -> Tools | None:
    """The yt-dlp updater, for a server that really fetches from YouTube, runs its background work and has not switched it off."""
    if not (settings.auto_tools and settings.workers and isinstance(youtube, YoutubeSource)):
        return None
    pacer = youtube.pacer
    return create_tools(
        ToolStore(settings.data_dir / "tools" / "yt-dlp"),
        active,
        rest=youtube.rest,
        lookups=youtube.lookups,
        wait_turn=pacer.wait_turn if pacer is not None else None,
        busy=lambda: in_flight.count > 0 or (scheduler is not None and scheduler.running() > 0),
    )


def _background(
    settings: Settings,
    database: Database,
    hub: Hub,
    youtube: YoutubeSource | None,
    client: NavidromeClient,
    notifications: Notifications,
) -> tuple[Scheduler | None, Keeper | None, ImportService]:
    """The background work: matching the songs of imports to uploads, and the keeper. Without a way to fetch songs nothing is queued,
    and without a music-server account that can find what was kept the keeper is off: every song still plays by streaming, and the
    server says in its log why it keeps nothing."""
    handlers: dict[str, Any] = {}
    keeper: Keeper | None = None
    if not settings.keep:
        pass
    elif youtube is None or not client.configured:
        log.warning(
            "keeping is off: %s",
            "no way to fetch songs (yt-dlp is not installed or YouTube is off)"
            if youtube is None
            else "ENCORE_NAVIDROME_ADMIN_USER / ENCORE_NAVIDROME_ADMIN_PASSWORD are not set",
        )
    else:

        def tell(touched: dict[str, int]) -> None:
            for person, cursor in touched.items():
                hub.publish(person, {"type": "library.changed", "cursor": str(cursor)})

        keeper = Keeper(
            database,
            youtube,
            client,
            KeepSettings(music_dir=settings.music_dir, min_free_gb=settings.min_free_gb),
            settings.data_dir / "work",
            on_changed=tell,
            find_cover_=deezer_lookup,
        )
        handlers["keep"] = keeper.handle
    imports = ImportService(database, hub, youtube, notifications=notifications)
    if youtube is not None:
        handlers["match"] = imports.match
    scheduler = Scheduler(database, handlers, workers={"interactive": 1, "background": 2}) if handlers else None
    imports.use(scheduler)
    return scheduler, keeper, imports


def create_app(
    settings: Settings | None = None,
    *,
    verifier: Verifier | None = None,
    db: Database | None = None,
    youtube: YoutubeSource | None = None,
    navidrome: NavidromeClient | None = None,
    gateway_client: httpx.AsyncClient | None = None,
    navidrome_admin: NavidromeAdmin | None = None,
    tools_active: Active | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    database = db or Database(settings.db_path)
    database.migrate(version=__version__)
    if youtube is None and settings.youtube:
        youtube = _default_youtube(settings, database)
    hub = Hub()
    client = navidrome or NavidromeClient(
        settings.navidrome_url, settings.navidrome_admin_user, settings.navidrome_admin_password
    )
    with database.tx() as conn:
        identity = load_or_create(conn)
    notifications = Notifications(database, hub)
    scheduler, keeper, imports = _background(settings, database, hub, youtube, client, notifications)
    keep_watch = (
        KeepWatch(database, scheduler, hub, lambda: _youtube_status(youtube))
        if scheduler is not None and scheduler.handles("keep")
        else None
    )
    the_verifier = verifier or NavidromeVerifier(settings.navidrome_url)

    def ended(person_id: str, user: str | None) -> None:
        # Locked, removed or given a new password: the live connections of the person close and the music server's remembered yes is forgotten.
        hub.end(person_id)
        forget_credentials(the_verifier, user)

    accounts = Accounts(
        database,
        navidrome_admin
        or NavidromeAdmin(settings.navidrome_url, settings.navidrome_admin_user, settings.navidrome_admin_password),
        notifications=notifications,
        server_name=settings.server_name,
        on_ended=ended,
    )
    finder = CoverFinder(database, music_dir=settings.music_dir, after=client.start_scan if client.configured else None)

    def errands() -> None:
        for errand in (accounts.heal_libraries, finder.run_once):
            try:
                errand()
            except Exception:  # noqa: BLE001 - one errand failing must not stop the next, nor the library link
                log.exception("a background errand failed")

    linker = (
        LibraryLinker(database, client, every_s=settings.scan_every_min * 60.0, before=errands)
        if client.configured and settings.scan_every_min > 0
        else None
    )

    # Not counted: the Docker health check, which would break every quiet moment.
    in_flight = InFlight(ignore=(f"{router.prefix}/info",))
    tools = _default_tools(settings, youtube, scheduler, in_flight, tools_active)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.workers:
            if scheduler is not None:
                scheduler.start()
            if linker is not None:
                linker.start()
            if tools is not None:
                tools.start()
            if keep_watch is not None:
                keep_watch.start()
        try:
            yield
        finally:
            if keep_watch is not None:
                keep_watch.stop()
            if tools is not None:
                tools.stop()
            if linker is not None:
                linker.stop()
            if scheduler is not None:
                scheduler.stop()

    app = FastAPI(title="Encore server", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.services = Services(
        settings=settings,
        db=database,
        hub=hub,
        verifier=the_verifier,
        youtube=youtube,
        scheduler=scheduler,
        keeper=keeper,
        linker=linker,
        imports=imports,
        accounts=accounts,
        notifications=notifications,
        limiter=Limiter(),
        tools=tools,
        identity=identity,
        music=client,
        keep_watch=keep_watch,
    )
    app.add_middleware(InFlightMiddleware, tracker=in_flight)
    app.add_middleware(BodyLimit)
    app.include_router(router)
    app.add_api_route("/encore/stream/{ref_id}", stream, methods=["GET", "HEAD"])
    app.add_api_route("/encore/cover/{cover_id}", cover, methods=["GET", "HEAD"])
    # Before the music server's catch-all below: an invitation link must never reach it (D-39).
    app.add_api_route("/encore/join/{code}", join_page, methods=["GET", "HEAD"], include_in_schema=False)
    app.add_api_websocket_route("/encore/live", live)
    gateway.mount(
        app, settings.navidrome_url, client=gateway_client, public=is_public_request, authorize_public=authorize_public_subsonic
    )

    @app.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(error.body(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(ApiError("validation").body(), status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, error: Exception) -> JSONResponse:
        log.exception("unexpected error: %s", error)
        return JSONResponse(ApiError("internal").body(), status_code=500)

    return app
