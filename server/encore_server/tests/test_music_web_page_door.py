"""The music server's own web page, `/api` and sign-in are shut by default (P3-34 slice 1, audit B-56).

Where Docker hides the visitor's address every visitor, from the house or from the internet, arrives from the network's own gateway, a private address. The gateway used to
believe "private" and passed the music server's web page, its sign-in and its `/api` to such a visitor: a router's port forward then put a second front door on the internet,
with no throttle. Now they answer **404 to everybody** (the answer of an unknown route of ours) unless the Host switched `music-web-page` on AND the server can PROVE the
visitor is on the home network (`netaddr.provably_home`). `/rest` is unchanged (slice 2 guards it per account), and every page and route of Encore's own keeps answering.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.netaddr import OwnNetwork
from tests.conftest import FakeVerifier, says
from tests.test_gateway import music_server

GATEWAY = "172.19.0.1"  # where Docker hides the visitor: the network's own gateway
LAN = "192.168.1.50"
INTERNET = "203.0.113.9"
OWN = OwnNetwork(gateways=frozenset({ipaddress.ip_address(GATEWAY)}), addresses=frozenset({ipaddress.ip_address("172.19.0.3")}))

# What the music server serves that a Host or a stranger may ask for through the gateway. `/rest` is its Subsonic API; the rest is its web page, sign-in and native API.
SHUT_PATHS = [
    ("GET", "/"),
    ("GET", "/app/"),
    ("GET", "/app/index.html"),
    ("POST", "/auth/login"),
    ("GET", "/api/user"),
    ("POST", "/api/user/echo"),
    ("GET", "/api/scrobble"),
    ("GET", "/share/abc"),
    ("GET", "/ping"),
]


def recording_upstream() -> FastAPI:
    """Stands in for the music server and writes down every path that reaches it, whatever it is: what must never reach it is what the tests below look for."""
    app = FastAPI()
    app.state.paths = []

    @app.api_route("/{p:path}", methods=["GET", "POST", "HEAD"])
    async def anything(p: str, request: Request) -> Response:
        app.state.paths.append(request.url.path)
        return Response("UPSTREAM", media_type="text/plain")

    return app


def app_with(
    tmp_path: Path,
    verifier: FakeVerifier,
    *,
    on: bool,
    trusted: tuple[str, ...] = (),
    own: OwnNetwork | None = OWN,
    upstream: FastAPI | None = None,
) -> tuple[FastAPI, FastAPI]:
    upstream = upstream or music_server()
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "m",
        navidrome_url="http://music.test",
        youtube=False,
        music_web_page=on,
        trusted_proxies=trusted,
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream), timeout=5)
    app = create_app(settings, verifier=verifier, gateway_client=client)
    app.state.services.own_network = own  # what the server read of its own network at start
    return app, upstream


@pytest.fixture()
def door(tmp_path: Path, verifier: FakeVerifier) -> Iterator[Callable[..., TestClient]]:
    """`door(on=..., peer=...)`: a client whose connection comes from `peer`, against a server whose switch is `on`."""
    opened: list[TestClient] = []

    def make(
        *,
        on: bool,
        peer: str,
        trusted: tuple[str, ...] = (),
        own: OwnNetwork | None = OWN,
        sub: str = "a",
        upstream: FastAPI | None = None,
    ) -> TestClient:
        app, used = app_with(tmp_path / sub, verifier, on=on, trusted=trusted, own=own, upstream=upstream)
        client = TestClient(app, client=(peer, 50000))
        client.upstream = used  # type: ignore[attr-defined]
        client.__enter__()
        opened.append(client)
        return client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def refused(response: httpx.Response) -> bool:
    return response.status_code == 404 and response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("peer", [LAN, GATEWAY, INTERNET, "127.0.0.1"])
@pytest.mark.parametrize(("method", "path"), SHUT_PATHS)
def test_the_music_servers_own_doors_answer_404_to_everybody_by_default(door, peer: str, method: str, path: str) -> None:  # type: ignore[no-untyped-def]
    """Shut from a private address, from the hidden-address gateway, from the internet and from this machine: no address detection stands between them and the internet."""
    client = door(on=False, peer=peer)

    assert refused(client.request(method, path, content=b"{}"))


def test_what_is_shut_looks_exactly_like_an_unknown_route_of_ours(door) -> None:  # type: ignore[no-untyped-def]
    client = door(on=False, peer=LAN)

    shut = client.get("/app/")
    unknown = client.get("/encore/api/v1/no-such-route")

    assert shut.status_code == unknown.status_code == 404
    assert says(shut.json()) == says(unknown.json()), "the same body, the same fields"
    assert says(client.post("/auth/createAdmin", json={}).json()) == says(shut.json()), (
        "the three 404s of the gateway are one answer"
    )
    assert says(client.get("/encore/no-such-thing").json()) == says(shut.json())
    assert "navidrome" not in shut.text.lower() and "music server" not in shut.text.lower()


def test_the_subsonic_api_is_not_touched_by_the_switch(door) -> None:  # type: ignore[no-untyped-def]
    for peer in (LAN, GATEWAY):
        client = door(on=False, peer=peer, sub=peer)
        assert client.get("/rest/ping.view?u=marwa&t=a&s=b&v=1.16.1&c=x&f=json").status_code == 200, peer


@pytest.mark.parametrize(
    "path", ["/admin", "/setup", "/encore/admin", "/encore/setup", "/encore/api/v1/info", "/encore/join/ABCDEFGH"]
)
def test_encores_own_pages_and_routes_keep_answering_with_the_switch_off(door, path: str) -> None:  # type: ignore[no-untyped-def]
    """A route-order mistake would let the shut catch-all swallow them: each answers with what it is, never with the gateway's 404 of the music server's doors."""
    client = door(on=False, peer=LAN)

    response = client.get(path, follow_redirects=False)

    assert response.status_code in (200, 301, 302, 303, 307, 308) or path.startswith("/encore/join/"), (
        path,
        response.status_code,
        response.text[:120],
    )
    assert (
        "text/html" in response.headers.get("content-type", "")
        or path == "/encore/api/v1/info"
        or response.status_code in (301, 302, 303, 307, 308)
    ), path


def test_with_the_switch_on_a_visitor_the_server_can_prove_is_home_reaches_the_web_page(door) -> None:  # type: ignore[no-untyped-def]
    client = door(on=True, peer=LAN)

    assert (
        client.post("/api/user/echo", content='{"a": 1}', headers={"content-type": "application/json"}).json()["got"]
        == '{"a": 1}'
    )
    assert client.post("/auth/login", json={}).json() == {"token": "t"}


@pytest.mark.parametrize("peer", [GATEWAY, INTERNET, "127.0.0.1", "172.19.0.3", "100.64.1.5", "169.254.9.9", "fd00::7"])
def test_with_the_switch_on_everybody_the_server_cannot_prove_is_home_is_still_shut(door, peer: str) -> None:  # type: ignore[no-untyped-def]
    """The hidden-address gateway, the internet, this machine, the server's own address, Tailscale's range, link-local and IPv6: the page stays shut."""
    client = door(on=True, peer=peer)

    assert refused(client.get("/app/"))
    assert refused(client.post("/auth/login", json={}))
    assert refused(client.get("/api/user"))


def test_with_the_switch_on_a_forged_forwarded_address_from_the_gateway_opens_nothing(door) -> None:  # type: ignore[no-untyped-def]
    client = door(on=True, peer=GATEWAY)

    response = client.get("/app/", headers={"X-Forwarded-For": LAN})

    assert refused(response)
    assert refused(client.get("/app/", headers={"X-Forwarded-For": f"{INTERNET}, {LAN}"}))


def test_a_proxy_the_host_listed_can_say_who_it_forwarded(door) -> None:  # type: ignore[no-untyped-def]
    """A proxy of its own: another container on the server's network (172.19.0.9), not the gateway that hides the visitors."""
    client = door(on=True, peer="172.19.0.9", trusted=("172.19.0.9",))

    assert client.post("/auth/login", json={}, headers={"X-Forwarded-For": LAN}).status_code == 200
    assert refused(client.post("/auth/login", json={}, headers={"X-Forwarded-For": INTERNET}))
    assert refused(client.post("/auth/login", json={}))


def test_listing_the_servers_own_gateway_as_a_proxy_does_not_open_the_page_to_everybody(door) -> None:  # type: ignore[no-untyped-def]
    """Where the address is hidden every visitor arrives as the gateway: believing its header would let any visitor write a LAN address and be home."""
    client = door(on=True, peer=GATEWAY, trusted=(GATEWAY,))

    assert refused(client.post("/auth/login", json={}, headers={"X-Forwarded-For": LAN}))
    assert refused(client.get("/app/", headers={"X-Forwarded-For": f"{INTERNET}, {LAN}"}))


def test_a_listed_proxy_is_not_believed_when_the_server_cannot_read_its_own_network(door) -> None:  # type: ignore[no-untyped-def]
    client = door(on=True, peer="172.19.0.9", trusted=("172.19.0.9",), own=None)

    assert refused(client.post("/auth/login", json={}, headers={"X-Forwarded-For": LAN}))


# A path that starts with /rest and climbs out of it: the gateway decides "Subsonic" on what the path means once its dot segments are resolved (the way the music server's own
# router will read it), not on how it starts. Before, `/rest/%2e%2e/app/` was passed on as Subsonic and the upstream URL builder resolved it to `/app/`.
DOT_PATHS = [
    "/rest/%2e%2e/app/",
    "/rest/%2E%2E/app/",
    "/rest/%2e%2e/auth/login",
    "/rest/%2e%2e/api/user",
    "/rest/%2e%2e/%2e%2e/auth/login",
    "/rest/./%2e%2e/app/",
    "/rest%2f..%2fapp",
    "/rest/..%2fapp/",
    "/rest/%2e%2e%2fapp/",
    "/rest/..%5capp/",
    "/rest/%2e%2e%5cauth%5clogin",
    "//rest/%2e%2e/app/",
    "/rest/%252e%252e/app/",
    "/rest/ping.view/%2e%2e/%2e%2e/app/",
]


@pytest.mark.parametrize("peer", [INTERNET, GATEWAY, LAN])
@pytest.mark.parametrize("path", DOT_PATHS)
def test_a_path_that_climbs_out_of_rest_is_not_a_way_to_the_shut_doors(door, peer: str, path: str) -> None:  # type: ignore[no-untyped-def]
    client = door(on=False, peer=peer, upstream=recording_upstream())

    response = client.get(path)

    assert refused(response), (path, response.status_code, response.text[:80])
    assert client.upstream.state.paths == [], f"{path} reached the music server as {client.upstream.state.paths}"  # type: ignore[attr-defined]


def test_what_is_passed_on_as_subsonic_is_what_was_decided_on_not_what_was_written(door) -> None:  # type: ignore[no-untyped-def]
    """A harmless dot segment inside /rest is resolved BEFORE it is passed on, so what the gateway judged is what the music server sees."""
    client = door(on=False, peer=LAN, upstream=recording_upstream())

    assert client.get("/rest/%2e/ping.view").text == "UPSTREAM"
    assert client.get("/rest/getCoverArt.view/%2e%2e/ping.view").text == "UPSTREAM"
    assert client.upstream.state.paths == ["/rest/ping.view", "/rest/ping.view"]  # type: ignore[attr-defined]


def test_when_the_server_cannot_read_its_own_network_the_page_stays_shut_even_from_a_lan_address(door) -> None:  # type: ignore[no-untyped-def]
    client = door(on=True, peer=LAN, own=None)

    assert refused(client.get("/app/"))


def test_the_first_account_address_stays_blocked_for_everybody_whatever_the_switch_says(door) -> None:  # type: ignore[no-untyped-def]
    client = door(on=True, peer=LAN)

    assert refused(client.post("/auth/createAdmin", json={}))


def test_a_request_that_comes_through_the_away_address_is_never_home(tmp_path: Path, verifier: FakeVerifier) -> None:
    """The Funnel path: the visitor is the internet whatever address the connection shows, and the page is shut to it even with the switch on."""
    upstream = music_server()
    settings = Settings(
        data_dir=tmp_path / "d",
        music_dir=tmp_path / "m",
        navidrome_url="http://music.test",
        youtube=False,
        music_web_page=True,
        away_url="https://away.example",
    )
    app = create_app(
        settings, verifier=verifier, gateway_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream), timeout=5)
    )
    app.state.services.own_network = OWN
    with TestClient(app, client=(LAN, 50000)) as client:
        assert refused(client.get("/app/", headers={"Host": "away.example"}))
        assert client.get(
            "/rest/ping.view?u=marwa&t=a&s=b&v=1.16.1&c=x&f=json", headers={"Host": "away.example"}
        ).status_code in (200, 401, 403)
