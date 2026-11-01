"""The gateway (docs/04 section 2): one address for everything. `/encore/*` is this server's own API; every other path goes on to the music
server (Navidrome) unchanged - the Subsonic API, covers, streams of kept files, its web page for people who like to tinker. The phone and
the public tunnel therefore need one address, not two.

Bytes are passed on as they arrive and `Range` is passed through, so a kept song starts at once and can be jumped in. Navidrome checks its
own logins; nothing is added or removed here except what a proxy must (the hop-by-hop headers, the address of the music server).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .errors import ApiError

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


def _forward(headers: httpx.Headers | dict[str, str] | object) -> dict[str, str]:
    items = headers.items() if hasattr(headers, "items") else []
    return {k: v for k, v in items if k.lower() not in _HOP and k.lower() != "content-length"}


def mount(
    app: FastAPI,
    upstream: str,
    *,
    client: httpx.AsyncClient | None = None,
    public: Callable[[Request], bool] | None = None,
) -> None:
    """Adds the catch-all route that passes everything not handled by this server to [upstream]. Call it after every other route.

    A request that comes in from the public internet ([public] says so) is passed on only for the Subsonic API (`/rest/...`), which is all the app
    and the Subsonic apps people already use ask for. The music server's own web page, its sign-in and its `/api` stay on the home network: through
    Funnel they would put a second, unguarded front door on the internet (AUDIT B12).
    """
    base = upstream.rstrip("/")
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0), follow_redirects=False)

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
    async def pass_on(path: str, request: Request) -> Response:
        if path.startswith("encore/") or path == "encore":
            # An unknown route of our own is ours to say "not found" about, not Navidrome's.
            return JSONResponse(ApiError("not_found").body(), status_code=404)
        if public is not None and public(request) and path != "rest" and not path.startswith("rest/"):
            return JSONResponse(ApiError("not_found").body(), status_code=404)
        url = f"{base}/{path}" + (f"?{request.url.query}" if request.url.query else "")
        headers = _forward(request.headers)
        # httpx would ask for gzip when the phone did not; the phone's own choice is what the music server must see.
        headers.setdefault("accept-encoding", "identity")
        headers["x-forwarded-for"] = request.client.host if request.client else ""
        headers["x-forwarded-proto"] = request.url.scheme
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
