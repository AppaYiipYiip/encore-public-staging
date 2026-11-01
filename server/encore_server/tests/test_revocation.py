"""Ending a device or a person has to end everything that person's phone holds (QA-BACKEND B4, B5, B13, batch S3).

B4: the music server's "yes" is remembered for ten minutes, so a person who was removed (or locked, or whose password changed) went on working for
ten minutes, and a removed name came back as a new person. B5: a live connection was checked only when it opened, so a device that signed out, was
revoked, locked or removed kept receiving every event. B13: a signed song address (6 hours) and a cover pass (7 days) were not checked against a
lock or a removal.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from encore_server.api import create_app
from encore_server.auth import NavidromeVerifier, subsonic_token
from encore_server.config import Settings
from tests.conftest import creds
from tests.test_accounts import FakeAdmin

V1 = "/encore/api/v1"


class MusicServer:
    """The music server as far as this server asks it: which users have which password. The real verifier talks to it over HTTP, so its own
    memory of a "yes" (the thing B4 is about) is in play, not a fake's."""

    def __init__(self) -> None:
        self.passwords = {"marwa": "pw-marwa", "nina": "pw-nina", "mia": "pw-mia"}
        self.pings = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        query = request.url.params
        user, token, salt = query.get("u", ""), query.get("t", ""), query.get("s", "")
        password = self.passwords.get(user)
        good = password is not None and subsonic_token(password, salt) == token
        if request.url.path.endswith("/ping"):
            self.pings += 1
        if not good:
            return httpx.Response(200, json={"subsonic-response": {"status": "failed", "error": {"code": 40}}})
        body: dict[str, Any] = {"status": "ok"}
        if request.url.path.endswith("/getUser"):
            body["user"] = {"username": user, "adminRole": user == "marwa"}
        return httpx.Response(200, json={"subsonic-response": body})

    def verifier(self) -> NavidromeVerifier:
        return NavidromeVerifier("http://music.invalid", client=httpx.Client(transport=httpx.MockTransport(self.handle)))


class Rig:
    def __init__(self, client: TestClient, music: MusicServer, admin: FakeAdmin) -> None:
        self.client = client
        self.music = music
        self.admin = admin

    def sign_in(self, user: str, device: str = "phone") -> dict[str, Any]:
        response = self.client.post(
            f"{V1}/auth/login", json={"username": user, "password": f"pw-{user}", "deviceName": f"{user}'s {device}"}
        )
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]

    def bearer(self, signed_in: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {signed_in['deviceToken']}"}

    def person_id(self, user: str) -> str:
        items = self.client.get(f"{V1}/people", params=creds("marwa")).json()["items"]
        return str(next(p["id"] for p in items if p["username"] == user))

    def lock(self, user: str, locked: bool = True) -> None:
        response = self.client.patch(f"{V1}/people/{self.person_id(user)}", params=creds("marwa"), json={"locked": locked})
        assert response.status_code == 200, response.text


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[Rig]:
    music = MusicServer()
    admin = FakeAdmin(music)  # type: ignore[arg-type]
    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.invalid", youtube=False)
    with TestClient(create_app(settings, verifier=music.verifier(), navidrome_admin=admin)) as client:  # type: ignore[arg-type]
        for user in ("marwa", "nina", "mia"):
            client.get(f"{V1}/me", params=creds(user))
        yield Rig(client, music, admin)


# ---------------------------------------------------------------------------------------------------------- B4


def test_a_removed_person_stops_working_at_once_and_does_not_come_back_as_a_new_person(rig: Rig) -> None:
    assert rig.client.get(f"{V1}/me", params=creds("nina")).status_code == 200  # the music server's yes is remembered now
    nina = rig.person_id("nina")

    removed = rig.client.delete(f"{V1}/people/{nina}", params=creds("marwa"))
    assert removed.status_code == 200
    rig.music.passwords.pop("nina", None)  # the music server's account goes with the person

    assert rig.client.get(f"{V1}/me", params=creds("nina")).status_code == 401, "not ten minutes later: now"
    people = rig.client.get(f"{V1}/people", params=creds("marwa")).json()["items"]
    assert "nina" not in [p["username"] for p in people], "and no new, empty person is made for the removed name"


def test_a_changed_password_ends_the_old_login_at_once(rig: Rig) -> None:
    assert rig.client.get(f"{V1}/me", params=creds("mia")).status_code == 200
    old = creds("mia")

    rig.music.passwords["mia"] = "a-new-password"  # what a change of password does at the music server
    rig.client.post(f"{V1}/auth/login", json={"username": "mia", "password": "a-new-password"})  # a new sign-in elsewhere
    # the server itself changing a password forgets the old yes too:
    verifier = rig.client.app.state.services.verifier  # type: ignore[attr-defined]
    verifier.forget("mia")

    assert rig.client.get(f"{V1}/me", params=old).status_code == 401


def test_forgetting_a_person_makes_the_verifier_ask_the_music_server_again() -> None:
    music = MusicServer()
    verifier = music.verifier()
    salt = "salt1234"
    token = subsonic_token("pw-nina", salt)
    assert verifier.verify("nina", token, salt) and verifier.verify("nina", token, salt)
    assert music.pings == 1, "the second yes came from memory"

    verifier.forget("nina")
    music.passwords.pop("nina")

    assert verifier.verify("nina", token, salt) is False and music.pings == 2


# ---------------------------------------------------------------------------------------------------------- B5


def _open(rig: Rig, signed_in: dict[str, Any]) -> Any:
    ws = rig.client.websocket_connect("/encore/live")
    session = ws.__enter__()
    session.send_json({"type": "auth", "token": signed_in["deviceToken"]})
    assert session.receive_json()["type"] == "hello"
    return ws, session


def _closed_with_4401(session: Any) -> bool:
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            session.receive_json()
        except WebSocketDisconnect as gone:
            return bool(gone.code == 4401)
    return False


def test_signing_out_closes_that_devices_live_connection(rig: Rig) -> None:
    phone, tablet = rig.sign_in("nina", "phone"), rig.sign_in("nina", "tablet")
    ws_phone, phone_socket = _open(rig, phone)
    ws_tablet, tablet_socket = _open(rig, tablet)
    try:
        assert rig.client.post(f"{V1}/auth/logout", headers=rig.bearer(phone)).status_code == 200

        assert _closed_with_4401(phone_socket), "the phone that signed out hears nothing more"
        assert rig.client.app.state.services.hub.count(phone["person"]["id"]) == 1, "the tablet is still connected"  # type: ignore[attr-defined]
    finally:
        ws_phone.__exit__(None, None, None)
        ws_tablet.__exit__(None, None, None)


def test_revoking_a_device_from_another_closes_only_that_one(rig: Rig) -> None:
    phone, tablet = rig.sign_in("nina", "phone"), rig.sign_in("nina", "tablet")
    ws_phone, phone_socket = _open(rig, phone)
    ws_tablet, _ = _open(rig, tablet)
    try:
        response = rig.client.delete(f"{V1}/me/devices/{phone['device']['id']}", headers=rig.bearer(tablet))
        assert response.status_code == 200

        assert _closed_with_4401(phone_socket)
    finally:
        ws_phone.__exit__(None, None, None)
        ws_tablet.__exit__(None, None, None)


def test_locking_a_person_closes_every_live_connection_of_theirs_and_nobody_elses(rig: Rig) -> None:
    nina, mia = rig.sign_in("nina"), rig.sign_in("mia")
    ws_nina, nina_socket = _open(rig, nina)
    ws_mia, _ = _open(rig, mia)
    try:
        rig.lock("nina")

        assert _closed_with_4401(nina_socket)
        assert rig.client.app.state.services.hub.count(mia["person"]["id"]) == 1  # type: ignore[attr-defined]
    finally:
        ws_nina.__exit__(None, None, None)
        ws_mia.__exit__(None, None, None)


def test_removing_a_person_closes_their_live_connection(rig: Rig) -> None:
    nina = rig.sign_in("nina")
    ws, socket = _open(rig, nina)
    try:
        assert rig.client.delete(f"{V1}/people/{rig.person_id('nina')}", params=creds("marwa")).status_code == 200

        assert _closed_with_4401(socket)
    finally:
        ws.__exit__(None, None, None)


# --------------------------------------------------------------------------------------------------------- B13


def _signed(rig: Rig, user: str) -> tuple[str, str]:
    """A person's song address and cover pass, signed by the server for them."""
    from encore_server.auth import COVER_PASS_SCOPE, sign_stream, stream_secret

    signed_in = rig.sign_in(user)
    person = signed_in["person"]["id"]
    expires = int(time.time()) + 3600
    with rig.client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        secret = stream_secret(conn)
    song = f"/encore/stream/sr_{'0' * 26}?p={person}&e={expires}&sig={sign_stream(secret, person, 'sr_' + '0' * 26, expires)}"
    cover = f"/encore/cover/al-1?p={person}&e={expires}&sig={sign_stream(secret, person, COVER_PASS_SCOPE, expires)}"
    return song, cover


def test_a_locked_persons_signed_addresses_stop_working_while_the_others_go_on(rig: Rig) -> None:
    nina_song, nina_cover = _signed(rig, "nina")
    mia_song, mia_cover = _signed(rig, "mia")
    assert rig.client.get(nina_song).status_code != 401 and rig.client.get(nina_cover).status_code != 401

    rig.lock("nina")

    assert rig.client.get(nina_song).status_code == 401, "an address that was signed for her is not a way in after the lock"
    assert rig.client.get(nina_cover).status_code == 401
    assert rig.client.get(mia_song).status_code != 401 and rig.client.get(mia_cover).status_code != 401


def test_a_removed_persons_signed_addresses_stop_working(rig: Rig) -> None:
    song, cover = _signed(rig, "nina")

    rig.client.delete(f"{V1}/people/{rig.person_id('nina')}", params=creds("marwa"))

    assert rig.client.get(song).status_code == 401 and rig.client.get(cover).status_code == 401
