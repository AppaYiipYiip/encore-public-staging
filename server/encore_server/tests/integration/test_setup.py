"""The installer's first-run step against a real Navidrome (docs/tasks P3-05): the owner's account is made, can sign in, is not an
administrator, and a second run changes nothing. (The administrator itself is made by the `accounts` fixture's own first call to the
same endpoint, so here it is found again: "existing".)"""

from __future__ import annotations

import secrets
from typing import Any

import httpx
import pytest

from encore_server.config import Settings
from encore_server.setup import run_setup
from tests.integration.conftest import URL

pytestmark = pytest.mark.integration


def login(username: str, password: str) -> httpx.Response:
    return httpx.post(f"{URL}/auth/login", json={"username": username, "password": password}, timeout=15)


def test_the_owner_is_made_in_the_real_music_server_and_a_second_run_changes_nothing(accounts: dict[str, str]) -> None:
    settings = Settings(navidrome_url=URL, navidrome_admin_user=accounts["admin"], navidrome_admin_password=accounts["admin_pw"])
    owner: dict[str, Any] = {
        "username": f"owner-{secrets.token_hex(3)}",
        "password": secrets.token_urlsafe(12),
        "name": "The Owner",
    }

    first = run_setup(settings, owner)
    assert (first.administrator, first.owner) == ("existing", "created")

    signed_in = login(owner["username"], owner["password"])
    assert signed_in.status_code == 200, "the owner can sign in with the password that was chosen"
    assert signed_in.json().get("isAdmin") is False, "and is an ordinary account, not the music server's administrator"

    again = run_setup(settings, {**owner, "password": secrets.token_urlsafe(12)})
    assert (again.administrator, again.owner) == ("existing", "existing")
    assert login(owner["username"], owner["password"]).status_code == 200, (
        "the first password still works: a second run does not replace it"
    )
