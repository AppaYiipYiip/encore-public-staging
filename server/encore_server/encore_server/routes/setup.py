"""The first run in the browser (docs/36 section 2, "The first run is a takeover risk"; docs/17 group "setup").

Two routes and two addresses:

* `GET setup/state` (needs the setup code in `X-Setup-Code`) says whether the server is waiting for its owner and what it is called;
* `POST setup/owner` (the same code) makes the owner and answers with a browser session, exactly what signing in would have given;
* `GET /encore/setup` is the page, and `GET /setup` the short address a Host is told to type: it goes to the page and keeps the query, which carries the code.

All of it answers **404, the very answer an unknown route of ours gets**, to a public request and to every request once the server has an owner (or never had a code): the pages are
closed for ever by being finished, and a stranger learns nothing about them. A wrong code answers 403 and is counted: five a minute from one address and thirty in all, then a wait that
says how long. The address is the one the rest of the server trusts (`client_address`: the connection's own, and a forwarded one only from a proxy of ours), never a header a client wrote.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import owner_setup, setup_code, web
from ..errors import ApiError
from .common import API_PREFIX, _ok, client_address, json_body, limiter_of, refuse_public, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)

#: Wrong codes: from one address, and from everywhere (a guesser with many addresses on the house network still meets a wall).
PER_ADDRESS = (5, 60.0)
IN_ALL = (30, 60.0)


def gate(request: Request) -> None:
    """Everything a first-run call must pass, in this order: not from the internet, only while the server waits for its owner, not from an address that has guessed too often, and
    with the right code. Each refusal before the last tells a stranger nothing."""
    refuse_public(request)
    svc = services(request)
    if not owner_setup.is_open(svc):
        raise ApiError("not_found")
    limiter = limiter_of(request)
    address = client_address(request)
    waits = [limiter.peek(f"setup-code:{address}", *PER_ADDRESS), limiter.peek("setup-code:all", *IN_ALL)]
    wait = max((w for w in waits if w is not None), default=None)
    if wait is not None:
        raise ApiError("rate_limited", "Too many wrong setup codes. Wait a moment, then try again.", retry_after_ms=wait)
    if not setup_code.matches(svc.settings.setup_code, request.headers.get("x-setup-code")):
        limiter.hit(f"setup-code:{address}", PER_ADDRESS[1])
        limiter.hit("setup-code:all", IN_ALL[1])
        raise ApiError(
            "forbidden", "That setup code is not right. Use the link shown on the computer where you installed Encore."
        )


@router.get("/setup/state")
def setup_state(request: Request, _: None = Depends(gate)) -> JSONResponse:
    """The first-run page asks this once with its code: it is open, and the server's name for the page's heading."""
    return _ok({"needsOwner": True, "serverName": services(request).settings.server_name})


@router.post("/setup/owner")
def setup_owner(request: Request, _: None = Depends(gate), body: dict[str, Any] = Depends(json_body)) -> JSONResponse:
    """Makes the owner (name, password, optional shown name) and a browser session for them. After this every first-run route is a 404."""
    return _ok(owner_setup.create_owner(services(request), body), 201)


def setup_page(request: Request) -> Response:
    """`GET /encore/setup`: the page. It holds no data and no code: the code is in the address it was opened by, which the page reads and removes. A server that has no owner to
    make (finished, or made by the command) sends the Host to the sign-in page instead."""
    refuse_public(request)
    if not owner_setup.is_open(services(request)):
        return RedirectResponse("/encore/admin", status_code=302, headers={"Cache-Control": "no-store"})
    body = web.page("setup")
    assert body is not None
    return HTMLResponse(body if request.method != "HEAD" else b"", headers=web.PAGE_HEADERS)


def short_setup(request: Request) -> Response:
    """`GET /setup`: the address a Host types. To the page, the query (the code) kept."""
    refuse_public(request)
    query = request.url.query
    target = "/encore/setup" + (f"?{quote(query, safe='=&-_.~%')}" if query else "")
    return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
