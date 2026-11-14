"""A stop of the server must not wait for a phone's live connection to notice by itself (audit B-129).

`docker stop` (and so `encore update` and `encore stop`) sends SIGTERM and kills the container after ten seconds. The server's `/encore/live` handler only
ever looked at its own queue: after the first message it never listened to the socket, so when the server was asked to stop (uvicorn tells the app the
connection is going away) or the phone went away, the handler noticed only when its next ping was due (25 s). Uvicorn waits for every running request to
end before it shuts down, so a stop with one phone connected took longer than Docker's grace and ended in SIGKILL (exit code 137).
"""

from __future__ import annotations

import inspect
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
from encore_server.db import Database
from encore_server.scheduler import Scheduler
from encore_server.stopping import DOCKER_GRACE_S, UVICORN_GRACE_S, join_within, worst_case_stop_s
from tests.conftest import creds
from tests.test_accounts import FakeAdmin
from tests.test_revocation import MusicServer
from tests.test_scheduler import make_person, make_refs

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


# ------------------------------------------------------------------------------------------------ the whole stop adds up


def test_the_two_phases_of_a_stop_add_up_to_less_than_dockers_grace() -> None:
    """uvicorn's grace + the lifespan's one budget + the least each stop is always given: the number in stopping.py's docstring."""
    assert worst_case_stop_s() <= DOCKER_GRACE_S - 1.0, "a stop that can take the whole grace ends in SIGKILL (B-129)"


def test_threads_are_waited_for_together_not_one_after_another() -> None:
    release = threading.Event()
    stuck = [threading.Thread(target=release.wait, args=(30,), daemon=True) for _ in range(4)]
    for thread in stuck:
        thread.start()
    began = time.monotonic()
    try:
        join_within(stuck, 0.5)
        took = time.monotonic() - began
    finally:
        release.set()

    assert took < 1.2, f"four stuck threads took {took:.1f} s: they were waited for one after another (0.5 s each would be 2 s)"


def test_stopping_busy_workers_takes_one_budget_not_one_per_worker(tmp_path: Path) -> None:
    """The scheduler used to join each of its workers for 5 s: with four of them in the middle of a long look-up a stop took 20 s."""
    db = Database(tmp_path / "e.db")
    db.migrate(version="test")
    refs = make_refs(db, 4)
    who = make_person(db, "marwa")
    started, release = threading.Semaphore(0), threading.Event()

    def stuck(item: Any) -> None:
        started.release()
        release.wait(30)

    scheduler = Scheduler(db, {"keep": stuck}, workers={"background": 4, "interactive": 1})
    scheduler.start()
    try:
        for ref in refs:
            scheduler.submit("keep", ref, who)
        for _ in refs:
            assert started.acquire(timeout=5), "a worker never took its item"
        began = time.monotonic()
        scheduler.stop(timeout=0.5)
        took = time.monotonic() - began
    finally:
        release.set()

    assert took < 1.2, f"stopping four busy workers took {took:.1f} s: each was waited for on its own"


def test_the_installed_uvicorn_takes_the_grace_the_server_passes_it() -> None:
    """The entry point test replaces `uvicorn.run`; this one asks the real one, so an image whose uvicorn refused the argument cannot slip through."""
    assert "timeout_graceful_shutdown" in inspect.signature(uvicorn.run).parameters
    config = uvicorn.Config(lambda scope, receive, send: None, timeout_graceful_shutdown=int(UVICORN_GRACE_S))  # type: ignore[arg-type]
    assert config.timeout_graceful_shutdown == int(UVICORN_GRACE_S)
