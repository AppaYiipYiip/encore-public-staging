"""Imports of a person's lists from other services (docs/17 section 6)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..auth import (
    Principal,
)
from ..imports.service import ImportService
from .common import API_PREFIX, _ok, get_principal, json_body, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


# ------------------------------------------------------------------------------------------------ imports


def imports_of(request: Request) -> ImportService:
    service = services(request).imports
    assert service is not None
    return service


@router.post("/imports")
def create_import(
    request: Request, body: dict[str, Any] = Depends(json_body), p: Principal = Depends(get_principal)
) -> JSONResponse:
    """A link or a list of songs becomes a playlist at once; matching and keeping go on in the background (docs/tasks P2-04)."""
    return _ok(imports_of(request).create(p.person_id, body), 201)


@router.get("/imports")
def list_imports(request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _ok({"imports": imports_of(request).listing(p.person_id)})


@router.get("/imports/{import_id}")
def get_import(import_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _ok({"import": imports_of(request).get(p.person_id, import_id)})


@router.get("/imports/{import_id}/entries")
def get_import_entries(import_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _ok({"entries": imports_of(request).entries(p.person_id, import_id)})


@router.post("/imports/{import_id}/stop")
def stop_import(import_id: str, request: Request, p: Principal = Depends(get_principal)) -> JSONResponse:
    return _ok({"import": imports_of(request).stop(p.person_id, import_id)})
