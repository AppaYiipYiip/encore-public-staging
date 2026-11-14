"""AUDIT B-41: a music server that does not answer is not a wrong password.

`NavidromeVerifier.verify` used to return False for a wrong password, a timeout and garbage alike. Sign-in then answered 401 "not accepted" and counted
the try against the person and the address (five a minute), and a phone whose saved login met the outage was told "Sign in again" (401) although
nothing was wrong with its password: a restart of the music server (`encore update` does one) made honest people look like guessers.

Now a REFUSAL (the music server answered "wrong username or password") is False, and no answer at all (down, restarting, an error page, a 5xx) is
`MusicServerUnavailable`, answered as a retryable 503 that is not counted and does not sign anybody out."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.auth import MusicServerUnavailable, NavidromeVerifier, subsonic_token
from encore_server.config import Settings
from tests.conftest import creds
from tests.test_accounts import FakeAdmin

V1 = "/encore/api/v1"


class Music:
    """A music server that can be switched between answering, refusing and not answering."""

    def __init__(self) -> None:
        self.password = "pw-marwa"
        self.mode = "up"  # up | down | error_page | server_error
        self.pings = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.mode == "down":
            raise httpx.ConnectError("the music server is not there")
        if self.mode == "error_page":
            return httpx.Response(200, text="<html>Bad gateway</html>")
        if self.mode == "server_error":
            return httpx.Response(502, text="bad gateway")
        query = request.url.params
        if request.url.path.endswith("/ping"):
            self.pings += 1
        good = query.get("u") == "marwa" and subsonic_token(self.password, query.get("s", "")) == query.get("t")
        if not good:
            return httpx.Response(200, json={"subsonic-response": {"status": "failed", "error": {"code": 40}}})
        body: dict[str, Any] = {"status": "ok"}
        if request.url.path.endswith("/getUser"):
            body["user"] = {"username": "marwa", "adminRole": True}
        return httpx.Response(200, json={"subsonic-response": body})

    def verifier(self) -> NavidromeVerifier:
        return NavidromeVerifier("http://music.invalid", client=httpx.Client(transport=httpx.MockTransport(self.handle)))


@pytest.fixture()
def music() -> Music:
    return Music()


@pytest.fixture()
def client(tmp_path: Path, music: Music) -> Iterator[TestClient]:
    admin = FakeAdmin(music)  # type: ignore[arg-type]
    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.invalid", youtube=False)
    with TestClient(create_app(settings, verifier=music.verifier(), navidrome_admin=admin)) as c:  # type: ignore[arg-type]
        assert c.get(f"{V1}/me", params=creds("marwa")).status_code == 200
        yield c


@pytest.mark.parametrize("mode", ["down", "error_page", "server_error"])
def test_no_answer_from_the_music_server_is_not_a_refusal(music: Music, mode: str) -> None:
    verifier = music.verifier()
    music.mode = mode

    with pytest.raises(MusicServerUnavailable):
        verifier.verify("marwa", subsonic_token("pw-marwa", "abc123"), "abc123")


def test_a_wrong_password_is_still_a_plain_no_and_the_right_one_a_yes(music: Music) -> None:
    verifier = music.verifier()

    assert verifier.verify("marwa", subsonic_token("wrong", "abc123"), "abc123") is False
    assert verifier.verify("marwa", subsonic_token("pw-marwa", "abc123"), "abc123") is True


@pytest.mark.parametrize("mode", ["down", "error_page", "server_error"])
def test_signing_in_while_the_music_server_is_away_is_a_retryable_503_and_is_not_counted(
    client: TestClient, music: Music, mode: str
) -> None:
    music.mode = mode
    body = {"username": "marwa", "password": "pw-marwa"}

    for _ in range(8):  # more than the five a minute that slow a guesser
        answer = client.post(f"{V1}/auth/login", json=body)
        assert answer.status_code == 503, answer.text
        assert answer.json()["error"]["retryable"] is True
        assert "music server" in answer.json()["error"]["message"].lower()

    music.mode = "up"
    assert client.post(f"{V1}/auth/login", json=body).status_code == 200, "the honest person was never slowed"


def test_a_saved_login_that_meets_the_outage_is_not_told_to_sign_in_again(client: TestClient, music: Music) -> None:
    saved = {
        "u": "marwa",
        "t": subsonic_token("pw-other", "zzzz1111"),
        "s": "zzzz1111",
    }  # a login the music server has not vouched for yet
    music.mode = "down"

    answer = client.get(f"{V1}/me", params=saved)

    assert answer.status_code == 503, "401 would make the phone ask for the password again"
    assert answer.json()["error"]["retryable"] is True


def test_a_real_wrong_password_is_still_401_and_still_counted(client: TestClient) -> None:
    for _ in range(5):
        answer = client.post(f"{V1}/auth/login", json={"username": "marwa", "password": "nope"})
        assert answer.status_code == 401
    assert client.post(f"{V1}/auth/login", json={"username": "marwa", "password": "nope"}).status_code == 429
