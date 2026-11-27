"""The gateway (docs/04 section 2): one address for everything. `/encore/*` is this server's own API; every other path goes on to the music
server (Navidrome) unchanged - the Subsonic API, covers, streams of kept files, its web page for people who like to tinker. The phone and
the public tunnel therefore need one address, not two.

Bytes are passed on as they arrive and `Range` is passed through, so a kept song starts at once and can be jumped in. Navidrome checks its
own logins; nothing is added or removed here except what a proxy must (the hop-by-hop headers, the address of the music server).
"""

from __future__ import annotations

import logging
import posixpath
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .errors import ApiError
from .request_id import of as request_id_of

log = logging.getLogger("encore_server.gateway")

#: Headers that describe one hop, not the message (RFC 9110 section 7.6.1), plus the ones the proxy sets itself.
_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
    }
)
_CHUNK = 64 * 1024


def resolved(path: str) -> str:
    """The path as the music server's own router will read it: every percent-escape decoded as often as it changes (an address written twice-encoded), backslashes as slashes,
    dot segments and doubled slashes resolved, a trailing slash dropped; case is kept. **What the gateway decides on, and what it passes on for the Subsonic API**: the upstream
    URL builder resolves `/rest/%2e%2e/app/` to `/app/`, so a decision made on how the path STARTS would let the music server's shut doors be opened through `/rest/`."""
    text = path
    for _ in range(4):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    # normpath keeps a doubled leading slash ("//x" stays "//x"), so every leading slash goes first
    return posixpath.normpath("/" + text.replace("\\", "/").lstrip("/"))


#: A Subsonic address as the gateway passes it on: `/rest` and plain names under it. Anything else that resolves under `/rest` (an escaped `?` or `#`, a space, a control character) is
#: not a name the music server's API has, and is not passed on: decoded text put back into an address could change what the address means.
_SUBSONIC = re.compile(r"/rest(?:/[A-Za-z0-9._~-]+)*")


def _not_found(request: Request) -> JSONResponse:
    """The one answer for every address the gateway will not pass on, whichever rule refused it: an unknown route of ours, the first-account address, a shut door."""
    return JSONResponse(ApiError("not_found").body(request_id_of(request)), status_code=404)


def is_first_account_request(path: str) -> bool:
    """Is this the music server's "make the first administrator" address (`/auth/createAdmin`), however it is written? A music server with no accounts hands its first one to
    whoever asks, so the gateway **never passes that address on, to anybody, from any network** (a second layer: the install makes the administrator before it ever lets the
    server be reached, and Encore's own calls to the music server go to its internal address, never through here). The path is decoded as often as it changes (an address
    written twice-encoded), its dots and doubled slashes resolved, and compared without regard to case or a trailing slash, so no spelling of it gets by."""
    return resolved(path).lower().rstrip("/") == "/auth/createadmin"


def _forward(headers: httpx.Headers | dict[str, str] | object) -> dict[str, str]:
    items = headers.items() if hasattr(headers, "items") else []
    return {k: v for k, v in items if k.lower() not in _HOP and k.lower() != "content-length"}


def mount(
    app: FastAPI,
    upstream: str,
    *,
    client: httpx.AsyncClient | None = None,
    public: Callable[[Request], bool] | None = None,
    authorize_public: Callable[[Request], Awaitable[None]] | None = None,
    web_page_open: Callable[[Request], bool] | None = None,
) -> None:
    """Adds the catch-all route that passes everything not handled by this server to [upstream]. Call it after every other route.

    **The music server's own web page, its sign-in and its `/api` are shut by default, for everybody** (P3-34, audit B-56): they answer the 404 of an unknown route of ours, unless
    [web_page_open] says the visitor may (the Host switched the page on and the server can PROVE the visitor is at home: a private address is not proof where Docker hides the
    visitor's address). Without [web_page_open] they are always shut. Everything else a client of the music server asks for is the Subsonic API (`/rest/...`), which is all the
    app and the Subsonic apps people already use ask for. Before, they were passed to anything that looked private: through a port forward to a Docker Desktop host they would
    have put a second, unguarded front door on the internet (AUDIT B12, B-56).

    The Subsonic API that is left is guarded as well (AUDIT B12b): [authorize_public] is awaited for such a request before anything is passed on,
    and raises an `ApiError` to refuse it. Without it the music server would be the only door where wrong passwords are not slowed (measured:
    40 wrong sign-ins in 0.6 s, none refused). A request from the home network is never asked.
    """
    base = upstream.rstrip("/")
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0), follow_redirects=False)

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
    async def pass_on(path: str, request: Request) -> Response:
        if path.startswith("encore/") or path == "encore":
            # An unknown route of our own is ours to say "not found" about, not Navidrome's.
            return _not_found(request)
        if is_first_account_request(path):
            return _not_found(request)
        where = resolved(path)
        if where == "/rest" or where.startswith("/rest/"):
            if not _SUBSONIC.fullmatch(where):
                return _not_found(request)
            if public is not None and public(request) and authorize_public is not None:
                await authorize_public(request)  # raises ApiError: the app's handler answers in the usual envelope
            path = where[1:]  # what was judged is what the music server is asked
        elif web_page_open is None or not web_page_open(request):
            return _not_found(request)
        url = f"{base}/{path}" + (f"?{request.url.query}" if request.url.query else "")
        headers = _forward(request.headers)
        # httpx would ask for gzip when the phone did not; the phone's own choice is what the music server must see.
        headers.setdefault("accept-encoding", "identity")
        headers["x-forwarded-for"] = request.client.host if request.client else ""
        headers["x-forwarded-proto"] = request.url.scheme
        # The request's id goes to the music server too (it logs it as its `requestId`): what the phone sent when it was a plain id, else the one this server made (P1-19).
        if (rid := request_id_of(request)) is not None:
            headers["x-request-id"] = rid
        body = await request.body() if request.method in ("POST", "PUT", "PATCH", "DELETE") else None
        try:
            built = http.build_request(request.method, url, headers=headers, content=body)
            answer = await http.send(built, stream=True)
        except httpx.HTTPError as error:
            log.info("the music server did not answer %s %s: %s", request.method, path, type(error).__name__)
            return JSONResponse(
                ApiError("server_busy", "The music server is not answering. Try again in a moment.").body(), status_code=503
            )

        async def chunks() -> AsyncIterator[bytes]:
            try:
                async for piece in answer.aiter_raw(_CHUNK):
                    yield piece
            except httpx.HTTPError as error:  # the music server went away half-way: the client sees a short body and asks again
                log.info("the music server stopped sending %s: %s", path, type(error).__name__)
            finally:
                await answer.aclose()

        out = _forward(answer.headers)
        # The body is passed on as it came (still compressed if it was), so its length and encoding headers stay true.
        for keep in ("content-length", "content-encoding"):
            if keep in answer.headers:
                out[keep] = answer.headers[keep]
        if request.method == "HEAD":
            await answer.aclose()
            return Response(status_code=answer.status_code, headers=out)
        return StreamingResponse(chunks(), status_code=answer.status_code, headers=out)
