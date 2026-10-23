"""Is anything going through the server right now? (docs/11 ADR-R39: the server restarts for a newer yt-dlp only when nothing is.)

Counts the HTTP requests being answered, from the first byte in to the last byte out, so a song streaming to a phone, a song from the music server
passing through the gateway and a playlist download all count while they last. The live connection (a WebSocket that stays open for days) and the
Docker health check do not, or the server would never be quiet.
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable, Collection
from typing import Any

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]


class InFlight:
    def __init__(self, ignore: Collection[str] = ()) -> None:
        self.ignore = frozenset(ignore)
        self._lock = threading.Lock()
        self._count = 0

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def enter(self) -> None:
        with self._lock:
            self._count += 1

    def leave(self) -> None:
        with self._lock:
            self._count = max(0, self._count - 1)


class InFlightMiddleware:
    """A plain ASGI middleware (not Starlette's `BaseHTTPMiddleware`, which would buffer a streamed body)."""

    def __init__(self, app: App, tracker: InFlight) -> None:
        self.app = app
        self.tracker = tracker

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") in self.tracker.ignore:
            await self.app(scope, receive, send)
            return
        self.tracker.enter()
        try:
            await self.app(scope, receive, send)
        finally:
            self.tracker.leave()
