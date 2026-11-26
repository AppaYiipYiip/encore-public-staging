"""The catalogue through this server: search, artist, album and genre pages (docs/17 section 3, P2-12)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..auth import (
    Principal,
)
from ..catalogue import KINDS, Catalogue
from ..deezer import LookupUnavailable, NotInCatalogue
from ..errors import ApiError
from .common import API_PREFIX, _ok, get_principal, limiter_of, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


# ------------------------------------------------------------------------------------------------ the catalogue (P2-12)

#: A catalogue id (Deezer's) is digits, and only digits ever reach the catalogue's address.
CATALOGUE_ID = re.compile(r"[0-9]{1,15}")
#: One person may cause this many outside requests a minute (a cached answer costs none): what one keeps typing cannot use the whole server's budget.
CATALOGUE_PER_MINUTE = 30
SEARCH_LIMIT_MAX = 25
ARTIST_PARTS = ("popular", "releases")


def _catalogue_of(request: Request) -> Catalogue:
    """The catalogue; or, on a server whose Host switched it off, the answer an app that asked anyway gets (the feature is not listed, so an app does not)."""
    catalogue = services(request).catalogue
    if catalogue is None or not catalogue.enabled:
        raise ApiError("not_found", "This server's catalogue is switched off.", details={"reason": "catalogue_off"})
    return catalogue


def _catalogue_id(value: str) -> str:
    if CATALOGUE_ID.fullmatch(value) is None:
        raise ApiError("validation", "That is not a catalogue id.")
    return value


def _catalogue_charge(request: Request, p: Principal) -> Callable[[], None]:
    """Called once for every outside request made for this person's call (never for a cached answer, never for a call that joined another's request)."""
    limiter = limiter_of(request)

    def charge() -> None:
        wait = limiter.allow(f"catalogue:{p.person_id}", CATALOGUE_PER_MINUTE, 60.0)
        if wait is not None:
            raise ApiError("rate_limited", "That is a lot of searching at once. Try again in a moment.", retry_after_ms=wait)

    return charge


def _catalogue_call(catalogue: Catalogue, work: Callable[[], dict[str, Any]]) -> JSONResponse:
    """Runs one call and answers: what the catalogue says, `not_found` for a thing it does not have, `source_busy` when it could not be asked at all (a
    catalogue that could not be asked is never an empty answer: audit B-124)."""
    try:
        return _ok(work())
    except NotInCatalogue:
        raise ApiError("not_found", "The catalogue has no such thing.", details={"reason": "not_in_catalogue"}) from None
    except LookupUnavailable:
        state = catalogue.state()
        wait = int(state["resumesInSec"]) * 1000 if state["state"] == "resting" else None
        raise ApiError(
            "source_busy", "The catalogue is not answering just now. Try again in a little while.", retry_after_ms=wait or None
        ) from None


@router.get("/catalogue/search")
def catalogue_search(
    request: Request,
    q: str = "",
    types: str = ",".join(KINDS),
    limit: int = 8,
    p: Principal = Depends(get_principal),
) -> JSONResponse:
    catalogue = _catalogue_of(request)
    text = " ".join(q.split())
    named = {t.strip() for t in types.split(",") if t.strip()}
    if not 2 <= len(text) <= 200 or not 1 <= limit <= SEARCH_LIMIT_MAX:
        raise ApiError("validation", "Search for 2 to 200 characters, and ask for 1 to 25 results.")
    if not named or named - set(KINDS):
        raise ApiError("validation", "types are artists, albums and tracks, separated by commas.")
    wanted = tuple(kind for kind in KINDS if kind in named)
    return _catalogue_call(catalogue, lambda: catalogue.search(text, wanted, limit, charge=_catalogue_charge(request, p)))


@router.get("/catalogue/artists/{artist_id}")
def catalogue_artist(
    artist_id: str, request: Request, parts: str = ",".join(ARTIST_PARTS), p: Principal = Depends(get_principal)
) -> JSONResponse:
    catalogue = _catalogue_of(request)
    ident = _catalogue_id(artist_id)
    asked = {part.strip() for part in parts.split(",") if part.strip()}
    if asked - set(ARTIST_PARTS):
        raise ApiError("validation", "parts are popular and releases, separated by commas.")
    chosen = tuple(part for part in ARTIST_PARTS if part in asked)
    return _catalogue_call(catalogue, lambda: catalogue.artist_page(ident, chosen, charge=_catalogue_charge(request, p)))


@router.get("/catalogue/albums/{album_id}")
def catalogue_album(album_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    catalogue = _catalogue_of(request)
    ident = _catalogue_id(album_id)
    return _catalogue_call(catalogue, lambda: catalogue.album(ident, charge=_catalogue_charge(request, p)))


@router.get("/catalogue/genres")
def catalogue_genres(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _ok(_catalogue_of(request).genres())


@router.get("/catalogue/genres/{genre_id}")
def catalogue_genre(genre_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    catalogue = _catalogue_of(request)
    ident = _catalogue_id(genre_id)
    return _catalogue_call(catalogue, lambda: catalogue.genre(ident, charge=_catalogue_charge(request, p)))
