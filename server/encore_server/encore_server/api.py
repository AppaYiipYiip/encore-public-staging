"""The HTTP API (docs/17): `/encore/api/v1/...` and the live channel `/encore/live`.

One error shape (errors.py), ids with prefixes, idempotent writes, state-based `library/changes`. Handlers are plain functions run in
worker threads (SQLite and the music server's check block briefly); the live sockets stay on the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import API_VERSION, MIN_APP_VERSION, __version__, library, playback, refs
from .auth import (
    NavidromeVerifier,
    Principal,
    Verifier,
    bearer_token,
    hash_token,
    issue_device,
    subsonic_credentials,
    subsonic_token,
)
from .config import Settings
from .db import Database
from .errors import ApiError
from .ids import is_id, now_ms
from .live import Hub

log = logging.getLogger("encore_server.api")

FEATURES = ["library", "playback", "live", "refs"]


@dataclass
class Services:
    settings: Settings
    db: Database
    hub: Hub
    verifier: Verifier


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
            "features": FEATURES,
        }
    )


@router.post("/auth/login")
def login(request: Request, body: dict[str, Any] = Depends(json_body)) -> JSONResponse:
    """Signs in with the music server's login, once: the password is turned into a Subsonic token, checked, and dropped. The app keeps
    the device token it gets back instead."""
    svc = services(request)
    user = body.get("username")
    password = body.get("password")
    if not isinstance(user, str) or not isinstance(password, str) or not user or not password:
        raise ApiError("validation", "Enter your username and password.")
    salt = secrets.token_hex(6)
    token = subsonic_token(password, salt)
    if subsonic_credentials({"u": user, "t": token, "s": salt}, {}) is None or not svc.verifier.verify(user, token, salt):
        raise ApiError("unauthorized", "The username or the password was not accepted.")
    name = body.get("deviceName") if isinstance(body.get("deviceName"), str) else "Phone"
    kind = body.get("deviceKind") if isinstance(body.get("deviceKind"), str) else "phone"
    version = body.get("appVersion") if isinstance(body.get("appVersion"), str) else None
    with svc.db.tx() as conn:
        existing = conn.execute("SELECT * FROM person WHERE navidrome_user = ?", (user,)).fetchone()
        admin = existing is None and svc.verifier.is_admin(user, token, salt)
        person = library.ensure_person(conn, user, admin=admin)
        if person["locked"]:
            raise ApiError("forbidden", "This account is locked.")
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


def _item_route(kind: str, request: Request, target: str, p: Principal, *, add: bool) -> JSONResponse:
    svc = services(request)
    with svc.db.tx() as conn:
        changed = (
            library.set_item(conn, p.person_id, kind, target) if add else library.clear_item(conn, p.person_id, kind, target)
        )
        cursor = library.latest_cursor(conn, p.person_id)
    if changed:
        _changed(svc, p, cursor)
    return _ok({"changed": changed, "cursor": str(cursor)})


@router.put("/likes/{ref_id}")
def like(ref_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _item_route("like", request, ref_id, p, add=True)


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
    added, cursor = _write_playlist(
        request,
        p,
        lambda conn: library.add_entries(conn, p.person_id, playlist_id, songs, after=after if isinstance(after, str) else None),
    )
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
    return _ok({"stored": stored}, 201 if stored else 200)


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


def create_app(settings: Settings | None = None, *, verifier: Verifier | None = None, db: Database | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = db or Database(settings.db_path)
    database.migrate(version=__version__)
    app = FastAPI(title="Encore server", version=__version__, docs_url=None, redoc_url=None)
    app.state.services = Services(
        settings=settings,
        db=database,
        hub=Hub(),
        verifier=verifier or NavidromeVerifier(settings.navidrome_url),
    )
    app.include_router(router)
    app.add_api_websocket_route("/encore/live", live)

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
