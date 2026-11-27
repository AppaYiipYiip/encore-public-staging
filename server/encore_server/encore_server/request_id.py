"""P1-19, the server's half: every request carries an id, so a failure can be followed from the phone to the server (docs/24 section 1; audit B-32).

* The phone sends `X-Request-Id` (a ULID) and `X-Device-Id`. The server reads them (**a value that is not plain is not believed**: a header can carry anything, and this one goes into the log and
  into an answer), makes an id of its own when there is none, **answers every request with `X-Request-Id`**, puts it in every log line written while the request is handled, in the `requestId` of
  every error body, and in the request it passes on to the music server (which logs it as its `requestId` too).
* One line is written for a request that failed (status 400 or more) or was slow: `event=request method=GET route=/encore/api/v1/... status=500 ms=12 device=...`. **The route is the
  route's own pattern, never the address as it was asked**: an address can hold a person's signed song address, a token or a name; no title, password, token or signed address reaches a line.
  Successful quick requests are written at DEBUG only (the Docker health check alone would fill the log).
"""

from __future__ import annotations

import contextvars
import logging
import re
import secrets
import time
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "x-request-id"
DEVICE_HEADER = "x-device-id"

#: What an id may look like: the phone's ULIDs (26 characters) and any plain token of 8 to 64 characters. Nothing else is believed (no space, no punctuation a log reader could misread).
PLAIN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
#: A request that took this long is written at INFO whatever its status.
SLOW_MS = 2000

log = logging.getLogger("encore_server.access")

#: The id of the request being handled; `-` outside one. Set once per request (each request is its own task, so it never reaches another).
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
device_var: contextvars.ContextVar[str] = contextvars.ContextVar("device", default="-")

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id(now_ms: int | None = None) -> str:
    """A ULID: 48 bits of time (milliseconds) and 80 random bits, in Crockford's base32, 26 characters. Sorts by time; nobody can guess the next."""
    stamp = int(time.time() * 1000) if now_ms is None else now_ms
    value = (stamp << 80) | secrets.randbits(80)
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def plain(value: str | None) -> str | None:
    """The value when it is a plain id, else `None`."""
    return value if value is not None and PLAIN.match(value) else None


def of(request: Request | Scope) -> str | None:
    """The id of a request, for a handler that has the request in hand (it works after the middleware's own work is done, which a context variable may not)."""
    scope = request.scope if isinstance(request, Request) else request
    state = scope.get("state") or {}
    found = state.get("request_id")
    return str(found) if found else None


class RequestIdFilter(logging.Filter):
    """Gives every log record a `rid` field: ` [<id>]` while a request is handled, nothing otherwise (the format string says `%(rid)s`)."""

    def filter(self, record: logging.LogRecord) -> bool:
        current = request_id_var.get()
        record.rid = f" [{current}]" if current != "-" else ""
        return True


class RequestIdMiddleware:
    """Pure ASGI (no response body is buffered: songs and pictures stream through it)."""

    def __init__(self, app: ASGIApp, *, slow_ms: int = SLOW_MS) -> None:
        self._app = app
        self._slow = slow_ms

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        rid = plain(headers.get(HEADER)) or new_id()
        device = plain(headers.get(DEVICE_HEADER)) or "-"
        scope.setdefault("state", {})["request_id"] = rid
        request_id_var.set(rid)
        device_var.set(device)
        began = time.monotonic()
        status = 0

        async def stamped(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() != HEADER.encode()]
                message = {**message, "headers": [*kept, (HEADER.encode(), rid.encode())]}
            await send(message)

        failed: BaseException | None = None
        try:
            await self._app(scope, receive, stamped)
        except BaseException as error:  # noqa: BLE001 - written down and raised again: the server's own handlers answer
            failed = error
            raise
        finally:
            took = int((time.monotonic() - began) * 1000)
            self._write(scope, status or (500 if failed is not None else 0), took, device)

    def _write(self, scope: Scope, status: int, took: int, device: str) -> None:
        route: Any = scope.get("route")
        pattern = (
            getattr(route, "path", None) or "unmatched"
        )  # the route's own pattern: never the address as it was asked, so no id, name or token of the address reaches a line
        level = logging.INFO if status >= 400 or took >= self._slow else logging.DEBUG
        if log.isEnabledFor(level):
            log.log(
                level,
                "event=request method=%s route=%s status=%s ms=%d device=%s",
                scope.get("method", "?"),
                pattern,
                status,
                took,
                device,
            )
