from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from encore_server import deezer
from encore_server.api import create_app
from encore_server.auth import subsonic_token
from encore_server.config import Settings
from encore_server.db import Database


class FakeVerifier:
    """The music server's side: knows a few users and their passwords; `admins` are its administrators."""

    def __init__(self) -> None:
        self.passwords = {"marwa": "pw-marwa", "nina": "pw-nina", "mia": "pw-mia"}
        self.admins = {"marwa"}
        self.checks = 0

    def verify(self, user: str, token: str, salt: str) -> bool:
        self.checks += 1
        password = self.passwords.get(user)
        return password is not None and subsonic_token(password, salt) == token

    def is_admin(self, user: str, token: str, salt: str) -> bool:
        return user in self.admins


def creds(user: str, password: str | None = None) -> dict[str, str]:
    """The Subsonic query a legacy app sends."""
    salt = "salt1234"
    return {"u": user, "t": subsonic_token(password or f"pw-{user}", salt), "s": salt}


@pytest.fixture()
def verifier() -> FakeVerifier:
    return FakeVerifier()


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "data" / "encore.db")
    database.migrate()
    return database


@pytest.fixture()
def client(tmp_path: Path, verifier: FakeVerifier) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as test_client:
        yield test_client


def song(title: str = "Weird Fishes / Arpeggi", artist: str = "Radiohead", **extra: object) -> dict[str, object]:
    return {"title": title, "artists": [artist], "album": "In Rainbows", "durationMs": 318000, **extra}


def resolve(client: TestClient, user: str, *songs: dict[str, object]) -> list[dict[str, object]]:
    response = client.post("/encore/api/v1/refs/resolve", params=creds(user), json={"songs": list(songs)})
    assert response.status_code == 200, response.text
    return response.json()["items"]  # type: ignore[no-any-return]


def allowed_hosts(music_server_url: str) -> set[str]:
    """The names a test may connect to besides this machine: the music server an integration test names (`IT_NAVIDROME_URL`, the tests marked
    `integration`, which `pytest` leaves out unless asked) and nothing else."""
    host = urlparse(music_server_url).hostname if music_server_url else None
    return {host} if host else set()


def _resolved(host: str) -> set[str]:
    try:
        return {str(info[4][0]) for info in socket.getaddrinfo(host, None)}
    except OSError:
        return set()


@pytest.fixture(autouse=True)
def _no_outside_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """No test, old or new, can reach anything outside this machine (P2-12: a test never makes a real request, and a test run that asked Deezer
    was the failure B27 already found once). Every `connect` to an address that is not loopback, not a local socket and not the music server of an
    integration run is refused and written down; and, because the code that asks swallows errors on purpose, the test fails at its end if it did.

    The check is on the address a socket connects to, below any client library, so a new library, a thread or a bad mock cannot step around it. A name
    is let through only when it is the host of `IT_NAVIDROME_URL` (resolved once, here: a socket sees addresses, not names)."""
    allowed = allowed_hosts(os.environ.get("IT_NAVIDROME_URL", ""))
    allowed_addresses = {address for host in allowed for address in _resolved(host)}
    refused: list[str] = []
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def outside(sock: socket.socket, address: object) -> bool:
        if sock.family == getattr(socket, "AF_UNIX", object()) or not isinstance(address, tuple) or not address:
            return False  # a local socket, or an address this guard does not understand: not an internet address
        host = str(address[0])
        if host in allowed or host in allowed_addresses or host in ("", "localhost"):
            return False
        try:
            return not ipaddress.ip_address(host.split("%")[0]).is_loopback
        except ValueError:
            return True  # a name that is not one of the above: it would be looked up on the internet

    def connect(self: socket.socket, address: Any) -> None:
        if outside(self, address):
            refused.append(f"{address[0]}:{address[1] if len(address) > 1 else ''}")
            raise OSError(f"a test may not connect outside this machine: {address[0]}")
        real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        if outside(self, address):
            refused.append(f"{address[0]}:{address[1] if len(address) > 1 else ''}")
            raise OSError(f"a test may not connect outside this machine: {address[0]}")
        return real_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    yield refused
    assert not refused, f"this test connected outside this machine {len(refused)} time(s): {refused[:3]}"


@pytest.fixture(autouse=True)
def _the_installed_catalogue_is_the_tests_own() -> Iterator[None]:
    """`create_app` installs the catalogue client every look-up goes through (`deezer.install`); it is one for the whole process, so a test that made an app
    must not leave its gate (resting, spent, switched off) to the next test."""
    yield
    deezer.install(None)


@pytest.fixture(autouse=True)
def _the_catalogue_is_never_really_asked(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """B27: seventeen tests asked the real api.deezer.com (a song kept through the app asks it for a picture, the cover finder asks it for
    every song without one), so a test run depended on somebody else's server and the internet, was slow offline, and sent real artist and
    title names out of a test. Any request to it is stopped and, because the code that asks swallows errors on purpose, written down and
    checked when the test ends, so the test that made it is the one that fails. A test about the catalogue gives its own client."""
    import httpx

    real = httpx.HTTPTransport.handle_request
    asked: list[str] = []

    def guarded(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        if request.url.host.endswith("deezer.com"):
            asked.append(str(request.url))
            raise httpx.ConnectError("a test may not ask the real catalogue", request=request)
        return real(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded)

    # What the app asks the catalogue with by default is nobody: no picture is found. (The guard above is the net under this.)
    def nobody(artist: str, title: str, album: str | None, *, client: object = None) -> None:
        return None

    monkeypatch.setattr("encore_server.cover_finder.deezer_lookup", nobody)
    monkeypatch.setattr("encore_server.api.deezer_lookup", nobody)
    monkeypatch.setattr("encore_server.artist_finder.deezer_artist_picture", nobody)
    yield
    assert not asked, f"this test asked the real catalogue {len(asked)} time(s): {asked[:2]}"
