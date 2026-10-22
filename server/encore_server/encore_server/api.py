"""The HTTP API (docs/17): `/encore/api/v1/...` and the live channel `/encore/live`.

One error shape (errors.py), ids with prefixes, idempotent writes, state-based `library/changes`. Handlers are plain functions run in
worker threads (SQLite and the music server's check block briefly); the live sockets stay on the event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import secrets
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import iterate_in_threadpool

from . import API_VERSION, MIN_APP_VERSION, __version__, gateway, library, playback, refs
from .accounts import Accounts, Limiter
from .auth import (
    STREAM_URL_TTL_S,
    NavidromeVerifier,
    Principal,
    Verifier,
    bearer_token,
    hash_token,
    issue_device,
    sign_stream,
    stream_secret,
    subsonic_credentials,
    subsonic_token,
    valid_stream_signature,
)
from .config import Settings
from .cover_finder import CoverFinder, deezer_lookup
from .db import Database
from .errors import ApiError
from .ids import is_id, now_ms
from .imports.service import ImportService
from .keeper.keeper import Keeper, KeepSettings
from .keeper.triggers import want_kept as _want_kept
from .live import Hub
from .migration import SubsonicUser, migrate_from_navidrome
from .navidrome import NavidromeClient
from .navidrome_admin import NavidromeAdmin
from .scanner import LibraryLinker
from .scheduler import Scheduler
from .sources.youtube.errors import DownloadError
from .sources.youtube.rest import DbRestStore, Rest
from .sources.youtube.source import YoutubeSource, wanted_from_ref
from .sources.youtube.stream import StreamError

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
    limiter: Limiter | None = None
    music_as: Callable[[str, str, str], SubsonicUser] | None = None


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
    if not svc.verifier.verify(user, subsonic, salt):
        raise ApiError("unauthorized", "The music server did not accept that login.")
    with svc.db.tx() as conn:
        existing = conn.execute("SELECT * FROM person WHERE navidrome_user = ?", (user,)).fetchone()
        admin = existing is None and svc.verifier.is_admin(user, subsonic, salt)
        person = library.ensure_person(conn, user, admin=admin)
        if person["locked"]:
            raise ApiError("forbidden", "This account is locked.")
        device = request.headers.get("x-encore-device")
        return Principal(person["id"], user, person["role"], device if device and is_id(device, "dv") else None)


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


@router.get("/info")
def info(request: Request) -> JSONResponse:
    svc = services(request)
    return _ok(
        {
            "apiVersion": API_VERSION,
            "minAppVersion": MIN_APP_VERSION,
            "serverVersion": __version__,
            "name": svc.settings.server_name,
            "features": [*FEATURES, *(["keep"] if svc.keeper is not None else [])],
            "youtube": svc.youtube.status()
            if svc.youtube is not None and hasattr(svc.youtube, "status")
            else {"state": "off", "resumesInSec": 0},
        }
    )


def client_address(request: Request) -> str:
    """Who is asking: the address of the connection, or - when that is the tunnel on this machine or home network - what the tunnel says."""
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    private = peer.startswith(("127.", "10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "::1", "fd", "fc"))
    return forwarded if forwarded and private else peer


def accounts_of(request: Request) -> Accounts:
    service = services(request).accounts
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
    the device token it gets back instead. Five tries a minute for one name and twenty for one address; twenty wrong passwords in all lock
    the account until the owner unlocks it."""
    svc = services(request)
    user = body.get("username")
    password = body.get("password")
    if not isinstance(user, str) or not isinstance(password, str) or not user or not password:
        raise ApiError("validation", "Enter your username and password.")
    limiter_of(request).refuse(f"login:{user.lower()}", 5, 60)
    limiter_of(request).refuse(f"login-address:{client_address(request)}", 20, 60)
    salt = secrets.token_hex(6)
    token = subsonic_token(password, salt)
    if subsonic_credentials({"u": user, "t": token, "s": salt}, {}) is None or not svc.verifier.verify(user, token, salt):
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
            }
        )


@router.post("/auth/logout")
def logout(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    if p.device_id is not None:
        with services(request).db.tx() as conn:
            conn.execute("UPDATE device SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (now_ms(), p.device_id))
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
    return _ok()


# ------------------------------------------------------------------------------------------------ people


@router.get("/invites/check")
def check_invite(request: Request, code: str = "") -> JSONResponse:
    """What the join screen shows for a code before a name is chosen (no sign-in: the code is the key)."""
    limiter_of(request).refuse(f"join-address:{client_address(request)}", 20, 60)
    return _ok(accounts_of(request).check_invite(code))


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
    made = accounts_of(request).join(
        str(body.get("code", "")), body.get("username"), body.get("password"), body.get("displayName"), str(name), version
    )
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
    limiter_of(request).refuse(f"login:{p.navidrome_user.lower()}", 5, 60)
    salt = secrets.token_hex(6)
    if not services(request).verifier.verify(p.navidrome_user, subsonic_token(old, salt), salt):
        accounts_of(request).failed_login(p.navidrome_user)
        raise ApiError("unauthorized", "The current password was not accepted.")
    accounts_of(request).change_password(p.navidrome_user, body.get("newPassword"))
    with services(request).db.tx() as conn:
        conn.execute(
            "UPDATE device SET revoked_at = ? WHERE person = ? AND id IS NOT ? AND revoked_at IS NULL",
            (now_ms(), p.person_id, p.device_id),
        )
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
        if not valid_stream_signature(secret, person, ref_id, expires, query.get("sig", "")):
            raise ApiError("unauthorized", "This song address has expired. Ask the app to play it again.")
        ref = refs.get_ref(conn, ref_id)
    if svc.youtube is None:
        raise ApiError("source_unreachable", "This server cannot fetch songs from YouTube.")
    try:
        upstream = svc.youtube.open(wanted_from_ref(ref), request.headers.get("range"))
    except StreamError as error:
        raise _stream_error(error, svc.youtube) from error
    except DownloadError as error:
        raise _stream_error(StreamError(error.code), svc.youtube) from error
    headers = {**upstream.headers, "Cache-Control": "no-store"}
    body = iterate_in_threadpool(upstream.body) if request.method != "HEAD" else iter(())
    return StreamingResponse(
        body, status_code=upstream.status, headers=headers, media_type=headers.pop("Content-Type", None), background=None
    )


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


@router.put("/saved-albums/{album_id}")
def save_album(album_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _item_route("saved_album", request, album_id[:100], p, add=True)


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
    )


def _background(
    settings: Settings, database: Database, hub: Hub, youtube: YoutubeSource | None, client: NavidromeClient
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
    imports = ImportService(database, hub, youtube)
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
    scheduler, keeper, imports = _background(settings, database, hub, youtube, client)
    accounts = Accounts(
        database,
        navidrome_admin
        or NavidromeAdmin(settings.navidrome_url, settings.navidrome_admin_user, settings.navidrome_admin_password),
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

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.workers:
            if scheduler is not None:
                scheduler.start()
            if linker is not None:
                linker.start()
        try:
            yield
        finally:
            if linker is not None:
                linker.stop()
            if scheduler is not None:
                scheduler.stop()

    app = FastAPI(title="Encore server", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.services = Services(
        settings=settings,
        db=database,
        hub=hub,
        verifier=verifier or NavidromeVerifier(settings.navidrome_url),
        youtube=youtube,
        scheduler=scheduler,
        keeper=keeper,
        linker=linker,
        imports=imports,
        accounts=accounts,
        limiter=Limiter(),
    )
    app.include_router(router)
    app.add_api_route("/encore/stream/{ref_id}", stream, methods=["GET", "HEAD"])
    app.add_api_websocket_route("/encore/live", live)
    gateway.mount(app, settings.navidrome_url, client=gateway_client)

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
