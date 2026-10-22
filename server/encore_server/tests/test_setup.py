"""The first-install steps inside the music server (docs/tasks P3-05): its administrator, the owner's account, safe to run twice, and no
password anywhere it should not be."""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import httpx
import pytest

from encore_server.config import Settings
from encore_server.setup import SetupError, command, ensure_administrator, run_setup, wait_for_music_server

URL = "http://navidrome.test:4533"
ADMIN, ADMIN_PW = "encore-admin", "generated-admin-secret-123"


class FakeMusicServer:
    """What the real music server does with these calls: accounts, the one-time first administrator, the account API with a login token."""

    def __init__(self, *, up_after: int = 0, existing: dict[str, tuple[str, bool]] | None = None) -> None:
        self.users: dict[str, tuple[str, bool]] = dict(existing or {})  # name -> (password, is_admin)
        self.pings = 0
        self.up_after = up_after
        self.libraries = [1]
        self.library_grants: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle), timeout=5.0)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        if path == "/ping":
            self.pings += 1
            return httpx.Response(200 if self.pings > self.up_after else 503)
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        if path == "/auth/login":
            known = self.users.get(body.get("username", ""))
            if known and known[0] == body.get("password"):
                return httpx.Response(200, json={"token": "t-" + body["username"], "isAdmin": known[1]})
            return httpx.Response(401, json={"error": "Invalid username or password"})
        if path == "/auth/createAdmin":
            if self.users:
                return httpx.Response(403)
            self.users[body["username"]] = (body["password"], True)
            return httpx.Response(200, json={"token": "t-" + body["username"]})
        token = request.headers.get("X-ND-Authorization", "")
        if not token.startswith("Bearer t-"):
            return httpx.Response(401)
        if path == "/api/user" and method == "GET":
            return httpx.Response(200, json=[{"id": f"id-{n}", "userName": n, "isAdmin": a} for n, (_, a) in self.users.items()])
        if path == "/api/user" and method == "POST":
            self.users[body["userName"]] = (body["password"], bool(body.get("isAdmin")))
            return httpx.Response(200, json={"id": f"id-{body['userName']}"})
        if path == "/api/library":
            return httpx.Response(200, json=[{"id": i} for i in self.libraries])
        if path.startswith("/api/user/") and path.endswith("/library") and method == "PUT":
            self.library_grants.append(path.split("/")[3])
            return httpx.Response(200, json={})
        return httpx.Response(404)


def settings(**override: Any) -> Settings:
    base: dict[str, Any] = {"navidrome_url": URL, "navidrome_admin_user": ADMIN, "navidrome_admin_password": ADMIN_PW}
    return Settings(**{**base, **override})


OWNER = {"username": "riley", "password": "a long enough password", "name": "Riley"}


def test_a_new_music_server_gets_its_administrator_and_the_owners_account() -> None:
    server = FakeMusicServer()

    result = run_setup(settings(), OWNER, client=server.client, wait=False)

    assert (result.administrator, result.owner) == ("created", "created")
    assert server.users[ADMIN] == (ADMIN_PW, True)
    assert server.users["riley"] == ("a long enough password", False), "the owner is an ordinary account, not an administrator"
    assert server.library_grants == ["id-riley"], "and may use the library"


def test_running_it_again_changes_nothing_and_says_so() -> None:
    server = FakeMusicServer()
    run_setup(settings(), OWNER, client=server.client, wait=False)
    before = dict(server.users)

    again = run_setup(settings(), {**OWNER, "password": "a different password!"}, client=server.client, wait=False)

    assert (again.administrator, again.owner) == ("existing", "existing")
    assert server.users == before, "the owner's password is not replaced by a second run"


def test_a_music_server_with_other_accounts_that_refuses_ours_says_what_to_do() -> None:
    server = FakeMusicServer(existing={"somebody": ("their password", True)})

    with pytest.raises(SetupError, match="encore uninstall --everything"):
        run_setup(settings(), OWNER, client=server.client, wait=False)


def test_the_installers_own_account_name_is_not_available_to_the_owner() -> None:
    server = FakeMusicServer()

    with pytest.raises(SetupError, match="not available"):
        run_setup(settings(), {**OWNER, "username": "encore-admin"}, client=server.client, wait=False)
    assert server.users == {}, "nothing was made when the details were refused"


@pytest.mark.parametrize(
    ("owner", "fragment"),
    [
        ({"username": "ab", "password": "a long enough password"}, "3 to 32"),
        ({"username": "riley", "password": "short"}, "8 to 128"),
        ({"username": "riley", "password": "riley"}, "8 to 128"),
        ({"username": "Riley Man", "password": "a long enough password"}, "3 to 32"),
        ({"password": "a long enough password"}, "3 to 32"),
    ],
)
def test_details_that_cannot_be_used_are_refused_in_words(owner: dict[str, Any], fragment: str) -> None:
    with pytest.raises(SetupError, match=fragment):
        run_setup(settings(), owner, client=FakeMusicServer().client, wait=False)


def test_an_install_without_the_music_servers_account_is_refused() -> None:
    with pytest.raises(SetupError, match="no account for the music server"):
        run_setup(settings(navidrome_admin_password=""), OWNER, client=FakeMusicServer().client, wait=False)


def test_it_waits_for_the_music_server_to_start() -> None:
    server = FakeMusicServer(up_after=3)
    slept: list[float] = []

    wait_for_music_server(URL, client=server.client, sleep=slept.append, clock=lambda: len(slept) * 2.0)

    assert server.pings == 4
    assert slept == [2.0, 2.0, 2.0]


def test_it_gives_up_with_a_sentence_when_the_music_server_never_starts() -> None:
    server = FakeMusicServer(up_after=10**9)
    ticks = iter(range(0, 1000, 10))

    with pytest.raises(SetupError, match="did not start in time"):
        wait_for_music_server(URL, seconds=30, client=server.client, sleep=lambda _s: None, clock=lambda: float(next(ticks)))


def test_a_music_server_that_does_not_answer_is_a_sentence() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(SetupError, match="not answering"):
        ensure_administrator(URL, ADMIN, ADMIN_PW, client=httpx.Client(transport=httpx.MockTransport(down)))


# ------------------------------------------------------------------------------------------------ the command


def test_the_command_reads_the_owner_from_standard_input_and_reports_without_the_password(
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = FakeMusicServer()
    out, err = io.StringIO(), io.StringIO()
    caplog.set_level(logging.DEBUG)

    import encore_server.setup as setup_module

    original = setup_module.httpx.Client
    setup_module.httpx.Client = lambda *a, **k: server.client  # type: ignore[assignment, misc]
    try:
        code = command(io.StringIO(json.dumps(OWNER)), out, err, settings())
    finally:
        setup_module.httpx.Client = original  # type: ignore[misc]

    assert code == 0, err.getvalue()
    assert out.getvalue() == "administrator=created\nowner=created\n"
    everything = out.getvalue() + err.getvalue() + caplog.text
    assert OWNER["password"] not in everything
    assert ADMIN_PW not in everything


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]"])
def test_the_command_asks_for_json_when_it_gets_something_else(text: str) -> None:
    out, err = io.StringIO(), io.StringIO()

    assert command(io.StringIO(text), out, err, settings()) == 2
    assert "JSON" in err.getvalue() or "3 to 32" in err.getvalue()
    assert out.getvalue() == ""
