"""A limit on how much a request may send (AUDIT B9).

Before this, a 30 MB body sent to `/auth/login` by somebody who was not signed in was read and parsed in full, and the gateway read any request body into
memory: one request from the internet could make the server run out of memory and stop the music for everybody. Every body here is small JSON, so a
generous limit costs nothing: [API_LIMIT] for this server's own API (the largest is a file import of at most 5,000 songs), [PASS_ON_LIMIT] for what is
passed on to the music server (a Subsonic call).

It is an ASGI wrapper, not a header check: a declared `Content-Length` above the limit is refused at once, and a body that arrives without one (or lies
about its length) is counted as it comes and cut off when it passes the limit.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]

API_LIMIT = 4 * 1024 * 1024
PASS_ON_LIMIT = 1024 * 1024

_TOO_BIG = b'{"error":{"code":"payload_too_large","message":"That request is far bigger than anything the app sends."}}'


class _TooBig(Exception):
    pass


class BodyLimit:
    def __init__(self, app: App) -> None:
        self._app = app

    @staticmethod
    def limit_for(path: str) -> int:
        return API_LIMIT if path.startswith("/encore/") else PASS_ON_LIMIT

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        limit = self.limit_for(scope.get("path", ""))
        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._refuse(send)
            return
        seen = 0
        started = False

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _TooBig
            return message

        async def watched(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self._app(scope, counted, watched)
        except _TooBig:
            if not started:
                await self._refuse(send)

    @staticmethod
    async def _refuse(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(_TOO_BIG)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": _TOO_BIG})
