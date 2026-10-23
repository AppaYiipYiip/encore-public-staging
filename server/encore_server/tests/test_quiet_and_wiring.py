"""Is anything going through the server (docs/11 ADR-R39), and how the yt-dlp updater is wired into the app: `/info`, the off switch, the loader at start."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from encore_server import api
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.quiet import InFlight, InFlightMiddleware
from encore_server.scheduler import Scheduler, WorkItem
from encore_server.sources.youtube.source import YoutubeSource
from encore_server.sources.youtube.updater import Tools
from tests.conftest import FakeVerifier
from tests.test_scheduler import make_person, make_refs

# ------------------------------------------------------------------------------------------------ counting what is going through


def counting_app(tracker: InFlight) -> tuple[TestClient, list[tuple[str, int]]]:
    app = FastAPI()
    app.add_middleware(InFlightMiddleware, tracker=tracker)
    seen: list[tuple[str, int]] = []

    @app.get("/plain")
    def plain() -> dict[str, bool]:
        seen.append(("plain", tracker.count))
        return {"ok": True}

    @app.get("/info")
    def info() -> dict[str, bool]:
        seen.append(("info", tracker.count))
        return {"ok": True}

    @app.get("/stream")
    def stream() -> StreamingResponse:
        def body() -> Iterator[bytes]:
            for n in range(3):
                seen.append((f"chunk{n}", tracker.count))
                yield b"x"

        return StreamingResponse(body())

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    @app.websocket("/live")
    async def live(websocket: WebSocket) -> None:
        await websocket.accept()
        seen.append(("live", tracker.count))
        await websocket.send_json({"hello": 1})
        await websocket.close()

    return TestClient(app, raise_server_exceptions=False), seen


def test_a_request_counts_from_its_first_byte_to_its_last_and_a_streamed_body_counts_until_the_end() -> None:
    tracker = InFlight()
    client, seen = counting_app(tracker)

    client.get("/plain")
    client.get("/stream")

    assert seen == [("plain", 1), ("chunk0", 1), ("chunk1", 1), ("chunk2", 1)]
    assert tracker.count == 0


def test_a_request_that_fails_is_still_counted_out() -> None:
    tracker = InFlight()
    client, _ = counting_app(tracker)

    assert client.get("/boom").status_code == 500
    assert tracker.count == 0


def test_the_health_check_and_the_live_connection_do_not_count() -> None:
    tracker = InFlight(ignore=("/info",))
    client, seen = counting_app(tracker)

    client.get("/info")
    with client.websocket_connect("/live") as socket:
        socket.receive_json()

    assert seen == [("info", 0), ("live", 0)], (
        "a server with a phone connected, and a health check every 30 s, can still be quiet"
    )


def test_two_requests_at_once_count_two() -> None:
    tracker = InFlight()
    tracker.enter()
    tracker.enter()
    tracker.leave()

    assert tracker.count == 1
    tracker.leave()
    tracker.leave()  # a stray leave never goes below zero
    assert tracker.count == 0


def test_the_scheduler_says_how_many_pieces_of_work_are_being_done_this_moment(db: Database) -> None:
    (ref,) = make_refs(db, 1)
    who = make_person(db, "marwa")
    during: list[int] = []
    holder: dict[str, Scheduler] = {}

    def handler(item: WorkItem) -> None:
        during.append(holder["s"].running())

    scheduler = holder["s"] = Scheduler(db, {"keep": handler})
    assert scheduler.running() == 0

    scheduler.submit("keep", ref, who)
    scheduler.drain()

    assert during == [1] and scheduler.running() == 0


# ------------------------------------------------------------------------------------------------ the wiring


def settings(tmp_path: Path, **extra: Any) -> Settings:
    return Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "music", workers=False, youtube=False, **extra)


def test_the_updater_is_on_by_default_and_off_with_the_switch() -> None:
    assert Settings.from_env({}).auto_tools is True
    assert Settings.from_env({"ENCORE_AUTO_TOOLS": "1"}).auto_tools is True
    for off in ("0", "false", "No", " 0 "):
        assert Settings.from_env({"ENCORE_AUTO_TOOLS": off}).auto_tools is False


def real_source(tmp_path: Path) -> YoutubeSource:
    return YoutubeSource(tmp_path / "work")


def build(tmp_path: Path, **overrides: Any) -> Tools | None:
    options: dict[str, Any] = {"workers": True, "youtube": True, "auto_tools": True}
    options.update(overrides)
    s = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "music", **options)
    return api._default_tools(s, real_source(tmp_path), None, InFlight(), None)


def test_a_server_that_fetches_from_youtube_and_runs_its_background_work_gets_the_updater(tmp_path: Path) -> None:
    tools = build(tmp_path)

    assert tools is not None
    assert tools.status()["ytDlp"]["pending"] is None and tools.status()["ytDlp"]["state"] == "ok"


@pytest.mark.parametrize("overrides", [{"auto_tools": False}, {"workers": False}])
def test_the_switch_and_a_server_without_background_work_have_no_updater(tmp_path: Path, overrides: dict[str, Any]) -> None:
    assert build(tmp_path, **overrides) is None


def test_a_fake_youtube_source_has_no_updater(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "music", workers=True, auto_tools=True)

    assert api._default_tools(s, None, None, InFlight(), None) is None
    assert api._default_tools(s, object(), None, InFlight(), None) is None  # type: ignore[arg-type]


def test_info_names_the_running_and_the_waiting_version_only_when_there_is_an_updater(
    tmp_path: Path, verifier: FakeVerifier
) -> None:
    app = api.create_app(settings(tmp_path), verifier=verifier)
    client = TestClient(app)
    assert "tools" not in client.get("/encore/api/v1/info").json()

    class Stub:
        def status(self) -> dict[str, Any]:
            return {"ytDlp": {"running": "2026.10.01", "pending": "2026.10.02", "state": "ok"}}

    app.state.services.tools = Stub()

    body = client.get("/encore/api/v1/info").json()
    assert body["tools"] == {"ytDlp": {"running": "2026.10.01", "pending": "2026.10.02", "state": "ok"}}


def test_the_health_check_is_not_counted_but_other_requests_are(tmp_path: Path, verifier: FakeVerifier) -> None:
    app = api.create_app(settings(tmp_path), verifier=verifier)
    tracker = next(m for m in app.user_middleware if m.cls is InFlightMiddleware).kwargs["tracker"]

    assert tracker.ignore == frozenset({"/encore/api/v1/info"})


def run_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> list[tuple[str, Any]]:
    from encore_server import __main__ as entry

    calls: list[tuple[str, Any]] = []
    sentinel = object()
    monkeypatch.setenv("ENCORE_DATA_DIR", str(tmp_path))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(entry, "activate", lambda store: calls.append(("activate", store.root)) or sentinel)
    monkeypatch.setattr(
        entry, "create_app", lambda s, tools_active=None: calls.append(("create_app", tools_active is sentinel)) or "app"
    )
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kw: calls.append(("run", app)))

    entry.main([])
    return calls


def test_the_stored_copy_is_put_first_before_the_app_is_made_and_the_app_is_told(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert run_main(monkeypatch, tmp_path) == [
        ("activate", tmp_path / "tools" / "yt-dlp"),
        ("create_app", True),
        ("run", "app"),
    ]


@pytest.mark.parametrize("env", [{"ENCORE_AUTO_TOOLS": "0"}, {"ENCORE_YOUTUBE": "0"}])
def test_with_the_updater_off_or_no_youtube_the_stored_copy_is_not_even_looked_at(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env: dict[str, str]
) -> None:
    assert run_main(monkeypatch, tmp_path, **env) == [("create_app", False), ("run", "app")]
