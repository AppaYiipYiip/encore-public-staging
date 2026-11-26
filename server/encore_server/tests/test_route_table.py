"""The table of routes (docs/17 section 3) is checked against the routes the application really registers, on every build (P3-31, register B-68).

Every route is one line of `fixtures/route_table.txt`: its methods, its path, the name of its handler and the module the handler lives in. A route added,
removed, renamed or moved to another module fails this test until the table is changed in the same pull request, and docs/17 says which table it is: so the
document cannot drift from the code again, and the admin routes of P3-06 cannot appear without a line here.

To change the table after a deliberate change of routes: `ENCORE_WRITE_ROUTE_TABLE=1 pytest tests/test_route_table.py`, read the difference, commit it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

TABLE = Path(__file__).parent / "fixtures" / "route_table.txt"


def flat(routes: list[Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Every route with its full path. Newer FastAPI keeps an included router as one entry that holds its own routes; older ones copy them into the app."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from flat(inner.routes, prefix + route.include_context.prefix)
        else:
            yield prefix, route


def lines_of(app: FastAPI) -> list[str]:
    out = []
    for prefix, route in flat(app.routes):
        methods = ",".join(sorted(getattr(route, "methods", None) or [])) or "WS"
        endpoint = getattr(route, "endpoint", None)
        module = getattr(endpoint, "__module__", "?").removeprefix("encore_server.")
        out.append(f"{methods} {prefix}{getattr(route, 'path', '')} {getattr(route, 'name', '?')} {module}")
    return out


def test_the_routes_are_the_routes_of_the_table(client: TestClient) -> None:
    found = lines_of(client.app)  # type: ignore[arg-type]
    if os.environ.get("ENCORE_WRITE_ROUTE_TABLE") == "1":
        TABLE.write_text("\n".join(found) + "\n", encoding="utf-8")
    expected = TABLE.read_text(encoding="utf-8").splitlines()
    assert found == expected, (
        "the registered routes differ from tests/fixtures/route_table.txt: if the change is deliberate, rewrite the table and docs/17 with it"
    )


def test_every_api_route_lives_in_a_route_module_and_the_assembly_has_none(client: TestClient) -> None:
    """P3-31: a handler is written in `routes/<area>.py`, never in `api.py`, which only assembles (the file would grow back into one big file)."""
    for line in lines_of(client.app):  # type: ignore[arg-type]
        _, path, name, module = line.split(" ")
        if path.startswith(("/encore/", "/encore/api/")):
            assert module.startswith("routes."), f"{path} ({name}) is handled in {module}, not in a module of routes/"
