"""A real Navidrome, a real ffmpeg, real tags: what the unit tests can only pretend (docs/tasks P2-01 acceptance)."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.navidrome import NavidromeClient
from encore_server.sources.youtube.source import Wanted

pytestmark = pytest.mark.integration

URL = os.environ.get("IT_NAVIDROME_URL", "")
MUSIC = Path(os.environ.get("IT_MUSIC_DIR", "/music"))

V1 = "/encore/api/v1"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in str(item.path):
            item.add_marker(pytest.mark.integration)


def ffmpeg(*args: str) -> None:
    done = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True, check=False)  # noqa: S603, S607
    assert done.returncode == 0, done.stderr


def make_audio(path: Path, *, seconds: int = 3, **tags: str) -> Path:
    """A real file with real tags (a sine tone): `.opus`, `.flac` or `.webm`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    codec = {".opus": "libopus", ".flac": "flac", ".webm": "libopus"}[path.suffix]
    meta = [arg for key, value in tags.items() for arg in ("-metadata", f"{key}={value}")]
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency={300 + len(tags) * 50}:duration={seconds}", "-c:a", codec, *meta, str(path))
    return path


class Native:
    """Navidrome's own admin API: only to set the throwaway server up."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.token = ""

    def call(self, method: str, route: str, body: dict[str, Any] | None = None) -> Any:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-ND-Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.base + route, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            raise AssertionError(f"{method} {route}: {error.code} {error.read()[:200]!r}") from error


@pytest.fixture(scope="session")
def accounts() -> dict[str, str]:
    """An administrator for the server's own work and an ordinary user for a person; passwords made for this run."""
    if not URL:
        pytest.skip("IT_NAVIDROME_URL is not set: these tests need the compose file in tests/integration")
    admin, person = f"admin-{secrets.token_hex(3)}", f"tester-{secrets.token_hex(3)}"
    admin_pw, person_pw = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
    native = Native(URL)
    made = native.call("POST", "/auth/createAdmin", {"username": admin, "password": admin_pw})
    native.token = made["token"]
    made_person = native.call("POST", "/api/user", {"userName": person, "name": person, "password": person_pw, "isAdmin": False})
    libraries = [lib["id"] for lib in native.call("GET", "/api/library")]
    if libraries:  # an ordinary account is given the library, as the Encore server does for the people it makes
        native.call("PUT", f"/api/user/{made_person['id']}/library", {"libraryIds": libraries})
    return {"admin": admin, "admin_pw": admin_pw, "person": person, "person_pw": person_pw}


@pytest.fixture(scope="session")
def navidrome(accounts: dict[str, str]) -> NavidromeClient:
    client = NavidromeClient(URL, accounts["admin"], accounts["admin_pw"])
    assert client.ping(), "the throwaway music server did not accept its own administrator"
    return client


def scan_and_wait(navidrome: NavidromeClient, *, seconds: float = 60) -> None:
    """Asks for a scan and returns once the music server's scanner has run it to the end (its `lastScan` moved on)."""
    before = (navidrome.scan_status() or {}).get("lastScan")
    navidrome.start_scan()
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(0.5)
        status = navidrome.scan_status() or {}
        if not status.get("scanning") and status.get("lastScan") != before:
            return
    raise AssertionError("the music server's scan did not finish in time")


class SourceOfRealAudio:
    """YouTube's place in these tests: hands over a real WebM/Opus file made on the spot (no network)."""

    def __init__(self) -> None:
        self.asked: list[Wanted] = []

    def download(self, wanted: Wanted, stem: Path, *, max_bytes: int) -> Path:
        self.asked.append(wanted)
        return make_audio(stem.with_name(stem.name + ".webm"), title="From YouTube", artist="Someone Else")

    def resting_for(self) -> float:
        return 0.0

    def open(self, *_: Any) -> Any:  # pragma: no cover - not used here
        raise NotImplementedError


class Rig:
    def __init__(self, client: TestClient, accounts: dict[str, str], source: SourceOfRealAudio) -> None:
        self.client = client
        self.accounts = accounts
        self.source = source
        self.svc = client.app.state.services  # type: ignore[attr-defined]

    def creds(self) -> dict[str, str]:
        from encore_server.auth import subsonic_token

        salt = secrets.token_hex(6)
        return {"u": self.accounts["person"], "t": subsonic_token(self.accounts["person_pw"], salt), "s": salt}

    def get(self, route: str, **params: str) -> Any:
        response = self.client.get(V1 + route, params={**self.creds(), **params})
        assert response.status_code == 200, response.text
        return response.json()

    def post(self, route: str, body: dict[str, Any]) -> Any:
        response = self.client.post(V1 + route, params=self.creds(), json=body)
        assert response.status_code in (200, 201), response.text
        return response.json()

    def put(self, route: str) -> Any:
        response = self.client.put(V1 + route, params=self.creds())
        assert response.status_code == 200, response.text
        return response.json()

    def resolve(self, **song: Any) -> dict[str, Any]:
        return self.post("/refs/resolve", {"songs": [song]})["items"][0]  # type: ignore[no-any-return]


@pytest.fixture()
def rig(tmp_path: Path, accounts: dict[str, str], navidrome: NavidromeClient) -> Iterator[Rig]:
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=MUSIC,
        navidrome_url=URL,
        navidrome_admin_user=accounts["admin"],
        navidrome_admin_password=accounts["admin_pw"],
        youtube=False,
        workers=False,
        min_free_gb=0.0,
        scan_every_min=0,
    )
    source = SourceOfRealAudio()
    with TestClient(create_app(settings, youtube=source, navidrome=navidrome)) as client:  # type: ignore[arg-type]
        yield Rig(client, accounts, source)
