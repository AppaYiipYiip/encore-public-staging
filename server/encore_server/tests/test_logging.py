"""The server's log must not hold anything a login can be guessed from."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server.__main__ import configure_logging
from encore_server.api import create_app
from encore_server.config import Settings
from tests.conftest import FakeVerifier
from tests.test_gateway import music_server


def test_the_requests_to_the_music_server_are_not_logged_with_their_login_tokens() -> None:
    configure_logging("INFO")

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


# ---------------------------------------------------------------------------------------------------------------------- P1-19 and the review of #174: no secret reaches any line


def test_the_server_is_started_with_uvicorns_own_access_log_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Uvicorn's access log writes every request with its FULL query string, and on `/rest/*` that holds the music server's login token (`t`, `s`) and on a song's address the signed `e` and `sig`. The
    server writes its own line instead (`event=request`, the route's pattern only). This pins that the access log stays off."""
    from encore_server.__main__ import main

    started: dict[str, Any] = {}
    monkeypatch.setattr("encore_server.__main__.uvicorn.run", lambda app, **kwargs: started.update(kwargs))
    monkeypatch.setattr("encore_server.__main__.create_app", lambda *args, **kwargs: object())
    monkeypatch.setattr("encore_server.__main__.configure_logging", lambda level: None)
    monkeypatch.setattr(
        "encore_server.__main__.Settings.from_env", staticmethod(lambda env=None: Settings(data_dir=tmp_path, youtube=False))
    )

    main([])

    assert started["access_log"] is False


def test_a_secret_in_the_address_or_a_header_reaches_no_log_line_of_the_real_app(
    tmp_path: Path, verifier: FakeVerifier, caplog: pytest.LogCaptureFixture
) -> None:
    configure_logging(
        "DEBUG"
    )  # the one place the server decides which loggers are quiet (httpx logs every address it asks for at INFO)
    canary = "canary-canary-canary-canary"  # a marker that must appear nowhere: not key-shaped, so the secret scanner has nothing to flag
    upstream = music_server()
    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.test", youtube=False)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream), timeout=5)
    with caplog.at_level(logging.DEBUG), TestClient(create_app(settings, verifier=verifier, gateway_client=http)) as client:
        client.get(
            f"/rest/ping.view?u=marwa&t={canary}&s={canary}&v=1.16.1&c=encore&f=json",
            headers={"Authorization": f"Bearer {canary}"},
        )
        client.get(f"/encore/api/v1/refs/sr_x/stream?e=9999999999&sig={canary}", headers={"Authorization": f"Bearer {canary}"})
        client.get(
            f"/encore/api/v1/me?token={canary}",
            headers={"Authorization": f"Bearer {canary}", "X-Request-Id": "01JD5Q8Y2K7X9M4N6P1R3S5T7V"},
        )
        client.get(f"/rest/no-such.view?t={canary}")

    text = "\n".join(f"{r.name}: {r.getMessage()}" for r in caplog.records)
    assert "event=request" in text, "the server did write its own lines"
    assert canary not in text, "a token, a signature or a header value is in a log line"
