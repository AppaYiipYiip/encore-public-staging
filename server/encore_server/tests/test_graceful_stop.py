"""A stop of the server must not wait for a phone's live connection to notice by itself (audit B-129).

`docker stop` (and so `encore update` and `encore stop`) sends SIGTERM and kills the container after ten seconds. The server's `/encore/live` handler only
ever looked at its own queue: after the first message it never listened to the socket, so when the server was asked to stop (uvicorn tells the app the
connection is going away) or the phone went away, the handler noticed only when its next ping was due (25 s). Uvicorn waits for every running request to
end before it shuts down, so a stop with one phone connected took longer than Docker's grace and ended in SIGKILL (exit code 137).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient
from websockets.sync.client import connect

from encore_server import api
from encore_server.api import create_app
from encore_server.config import Settings
from tests.conftest import creds
from tests.test_accounts import FakeAdmin
from tests.test_revocation import MusicServer

V1 = "/encore/api/v1"
#: Docker's grace before SIGKILL is 10 s: a stop must be well inside it.
STOP_BUDGET_S = 5.0


class Running:
    """The application served by a real uvicorn on a free port (the websocket handler and uvicorn's shutdown are what is under test)."""

    def __init__(self, server: uvicorn.Server, thread: threading.Thread, port: int, hub: Any) -> None:
        self.server = server
        self.thread = thread
        self.port = port
        self.hub = hub

    def stop(self) -> float:
        """Asks uvicorn to stop (what its SIGTERM handler does) and says how long it took, or [math.inf]-like (the timeout) when it did not."""
        began = time.monotonic()
        self.server.should_exit = True
        self.thread.join(timeout=STOP_BUDGET_S + 5)
        return time.monotonic() - began if not self.thread.is_alive() else 999.0


@pytest.fixture()
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Running, dict[str, Any]]]:
    # The real ping is 25 s. Made longer here so that a stop which waits for the next ping can never look fast by luck.
    monkeypatch.setattr(api, "PING_EVERY_S", 60.0)
    music = MusicServer()
    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.invalid", youtube=False)
    app = create_app(settings, verifier=music.verifier(), navidrome_admin=FakeAdmin(music))  # type: ignore[arg-type]
    with TestClient(app) as client:
        client.get(f"{V1}/me", params=creds("nina"))
        response = client.post(f"{V1}/auth/login", json={"username": "nina", "password": "pw-nina", "deviceName": "phone"})
        assert response.status_code == 200, response.text
        signed_in = response.json()
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "the test server did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        running = Running(server, thread, port, app.state.services.hub)
        try:
            yield running, signed_in
        finally:
            server.should_exit = True
            server.force_exit = True
            thread.join(timeout=5)


def _connect(running: Running, signed_in: dict[str, Any]) -> Any:
    socket = connect(f"ws://127.0.0.1:{running.port}/encore/live", open_timeout=5)
    socket.send(json.dumps({"type": "auth", "token": signed_in["deviceToken"]}))
    assert json.loads(socket.recv(timeout=5))["type"] == "hello"
    return socket


def test_a_stop_does_not_wait_for_a_phone_that_is_connected(served: tuple[Running, dict[str, Any]]) -> None:
    running, signed_in = served
    socket = _connect(running, signed_in)
    try:
        took = running.stop()
    finally:
        socket.close()

    assert took < STOP_BUDGET_S, f"the stop took {took:.1f} s with one phone connected: Docker kills the server at 10 s (B-129)"


def test_a_phone_that_goes_away_is_forgotten_at_once_not_at_the_next_ping(served: tuple[Running, dict[str, Any]]) -> None:
    running, signed_in = served
    hub = running.hub
    socket = _connect(running, signed_in)
    assert hub.count() == 1
    socket.close()

    deadline = time.monotonic() + 3
    while hub.count() and time.monotonic() < deadline:
        time.sleep(0.05)

    assert hub.count() == 0, "a closed socket stays on the hub until the next ping would fail to send"


def test_a_connected_phone_still_receives_what_is_published_to_it(served: tuple[Running, dict[str, Any]]) -> None:
    """The listener that notices a closed socket must not eat or delay the events."""
    running, signed_in = served
    hub = running.hub
    socket = _connect(running, signed_in)
    try:
        hub.publish(signed_in["person"]["id"], {"type": "probe", "n": 1})
        got = json.loads(socket.recv(timeout=5))
        hub.publish(signed_in["person"]["id"], {"type": "probe", "n": 2})
        got_next = json.loads(socket.recv(timeout=5))
    finally:
        socket.close()

    assert (got["n"], got_next["n"]) == (1, 2)
