"""What this server is and where it can be reached: `GET info` (no login) and `GET server` (docs/17 section 2, docs/11 ADR-R40)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import (
    API_VERSION,
    MIN_APP_VERSION,
    __version__,
)
from ..auth import (
    Principal,
)
from ..errors import ApiError
from ..identity import NONCE_PATTERN
from .common import API_PREFIX, CATALOGUE_FEATURES, FEATURES, KEEP_FEATURES, _ok, _youtube_status, get_principal, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


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
            "features": [
                *FEATURES,
                *(KEEP_FEATURES if svc.keeper is not None else []),
                *(CATALOGUE_FEATURES if svc.catalogue is not None and svc.catalogue.enabled else []),
            ],
            "youtube": _youtube_status(svc.youtube),
            "catalogue": svc.catalogue.state() if svc.catalogue is not None else {"state": "off", "resumesInSec": 0},
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
