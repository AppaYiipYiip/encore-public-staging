from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
        if request.url.host.endswith(("deezer.com", "lrclib.net")):
            asked.append(str(request.url))
            raise httpx.ConnectError("a test may not ask the real catalogue", request=request)
        return real(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded)

    # What the app asks the catalogue with by default is nobody: no picture is found. (The guard above is the net under this.)
    def nobody(artist: str, title: str, album: str | None, *, client: object = None) -> None:
        return None

    monkeypatch.setattr("encore_server.cover_finder.deezer_lookup", nobody)
    monkeypatch.setattr("encore_server.api.deezer_lookup", nobody)
    yield
    assert not asked, f"this test asked the real catalogue {len(asked)} time(s): {asked[:2]}"
