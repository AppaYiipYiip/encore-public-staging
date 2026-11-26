"""The live channel: one websocket per device (docs/17 section 5)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .. import (
    library,
)
from ..auth import (
    hash_token,
    web_session_over,
)
from ..ids import now_ms
from ..live import END
from .common import Services

log = logging.getLogger("encore_server.api")


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
                "SELECT d.id AS device, d.person AS person, d.kind AS kind, d.created_at AS created, d.last_seen AS seen"
                " FROM device d JOIN person p ON p.id = d.person"
                " WHERE d.token_hash = ? AND d.revoked_at IS NULL AND p.locked = 0",
                (hash_token(token),),
            ).fetchone()
            cursor = library.latest_cursor(conn, row["person"]) if row else 0
        if row is None or (row["kind"] == "web" and web_session_over(row["created"], row["seen"], now_ms())):
            await websocket.close(code=4401)
            return
    except (TimeoutError, ValueError, WebSocketDisconnect):
        await websocket.close(code=4400)
        return

    connection = svc.hub.attach(row["person"], row["device"])
    # The device's side is listened to as well as the queue: a phone that goes away, and uvicorn's own "this connection is ending" when the server is
    # asked to stop, arrive as a disconnect message, and the handler must end THEN, not at the next ping (B-129: a stop with one phone connected waited
    # for the 25 s ping, past Docker's 10 s grace, and ended in SIGKILL; a device that had gone stayed on the hub as "listening").
    closed = asyncio.create_task(_until_closed(websocket))
    waiting: asyncio.Task[dict[str, Any]] | None = None
    try:
        await websocket.send_json({"type": "hello", "serverTime": now_ms(), "cursor": str(cursor)})
        while True:
            if waiting is None:
                waiting = asyncio.create_task(connection.queue.get())
            await asyncio.wait({waiting, closed}, timeout=PING_EVERY_S, return_when=asyncio.FIRST_COMPLETED)
            if closed.done():
                return  # an event that came with it is not lost: the device asks for what it missed by its cursor when it connects again
            if waiting.done():
                event = waiting.result()
                waiting = None
            else:
                event = {"type": "ping", "serverTime": now_ms()}
            if connection.ended or event is END:
                await websocket.close(code=4401)  # the device was signed out, revoked, locked or removed (AUDIT B5)
                return
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        closed.cancel()
        if waiting is not None:
            waiting.cancel()
        svc.hub.detach(connection)


async def _until_closed(websocket: WebSocket) -> None:
    """Returns when the device's side closes the socket or the connection ends. Whatever the device sends after its first message is read and ignored."""
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
    except (RuntimeError, WebSocketDisconnect):
        return  # the socket is already closed
