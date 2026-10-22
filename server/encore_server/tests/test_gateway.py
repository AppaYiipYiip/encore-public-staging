"""The gateway: one address. `/encore/*` is ours, everything else is passed on to the music server unchanged, with Range, as it arrives."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from tests.conftest import FakeVerifier

AUDIO = bytes(range(256)) * 400


def music_server() -> FastAPI:
    """Stands in for Navidrome: the pieces of its surface the app uses."""
    app = FastAPI()
    seen: list[dict[str, str]] = []
    app.state.seen = seen

    @app.get("/rest/ping.view")
    def ping(request: Request) -> dict[str, object]:
        seen.append(dict(request.headers) | {"query": request.url.query})
        return {"subsonic-response": {"status": "ok", "version": "1.16.1"}}

    @app.api_route("/rest/stream.view", methods=["GET", "HEAD"])
    def stream(request: Request) -> Response:
        header = request.headers.get("range")
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", header or "")
        if not match:
            return Response(AUDIO, media_type="audio/ogg", headers={"Accept-Ranges": "bytes"})
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else len(AUDIO) - 1
        return Response(
            AUDIO[start : end + 1],
            status_code=206,
            media_type="audio/ogg",
            headers={"Content-Range": f"bytes {start}-{end}/{len(AUDIO)}", "Accept-Ranges": "bytes"},
        )

    @app.post("/api/user/echo")
    async def echo(request: Request) -> dict[str, object]:
        return {"got": (await request.body()).decode(), "type": request.headers.get("content-type")}

    @app.get("/rest/gone.view")
    def gone() -> Response:
        return Response("nope", status_code=404)

    return app


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier) -> Iterator[tuple[TestClient, FastAPI]]:
    upstream = music_server()
    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.test", youtube=False)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream), timeout=5)
    with TestClient(create_app(settings, verifier=verifier, gateway_client=client)) as test_client:
        yield test_client, upstream


def test_a_subsonic_call_reaches_the_music_server_with_its_query_untouched(rig: tuple[TestClient, FastAPI]) -> None:
    client, upstream = rig

    response = client.get("/rest/ping.view?u=marwa&t=abc&s=def&v=1.16.1&c=encore&f=json")

    assert response.status_code == 200 and response.json()["subsonic-response"]["status"] == "ok"
    assert upstream.state.seen[0]["query"] == "u=marwa&t=abc&s=def&v=1.16.1&c=encore&f=json"
    assert upstream.state.seen[0]["x-forwarded-proto"] == "http"


def test_a_kept_song_is_passed_on_whole_with_its_headers(rig: tuple[TestClient, FastAPI]) -> None:
    client, _ = rig

    response = client.get("/rest/stream.view?id=nd-1")

    assert response.content == AUDIO
    assert response.headers["content-type"] == "audio/ogg" and response.headers["accept-ranges"] == "bytes"


def test_a_jump_inside_a_song_is_a_range_request_all_the_way(rig: tuple[TestClient, FastAPI]) -> None:
    client, _ = rig

    response = client.get("/rest/stream.view?id=nd-1", headers={"Range": "bytes=1000-1999"})

    assert response.status_code == 206 and response.content == AUDIO[1000:2000]
    assert response.headers["content-range"] == f"bytes 1000-1999/{len(AUDIO)}"


def test_a_head_request_has_headers_and_no_body(rig: tuple[TestClient, FastAPI]) -> None:
    client, _ = rig

    response = client.head("/rest/stream.view?id=nd-1")

    assert response.status_code == 200 and response.content == b""


def test_a_post_body_and_its_type_arrive(rig: tuple[TestClient, FastAPI]) -> None:
    client, _ = rig

    response = client.post("/api/user/echo", content='{"a": 1}', headers={"content-type": "application/json"})

    assert response.json() == {"got": '{"a": 1}', "type": "application/json"}


def test_what_the_music_server_refuses_is_refused_the_same_way(rig: tuple[TestClient, FastAPI]) -> None:
    client, _ = rig
    assert client.get("/rest/gone.view").status_code == 404


def test_our_own_routes_are_not_passed_on_and_an_unknown_one_of_ours_is_ours_to_refuse(rig: tuple[TestClient, FastAPI]) -> None:
    client, upstream = rig

    assert client.get("/encore/api/v1/info").json()["apiVersion"]
    unknown = client.get("/encore/api/v1/nothing-here")

    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "not_found"
    assert upstream.state.seen == []


def test_a_music_server_that_is_down_is_a_sentence_not_a_crash(tmp_path: Path, verifier: FakeVerifier) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.test", youtube=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    with TestClient(create_app(settings, verifier=verifier, gateway_client=client)) as test_client:
        response = test_client.get("/rest/ping.view")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "server_busy" and "not answering" in response.json()["error"]["message"]


def test_the_phones_own_choice_of_compression_is_what_the_music_server_sees(rig: tuple[TestClient, FastAPI]) -> None:
    client, upstream = rig

    client.get("/rest/ping.view", headers={"accept-encoding": "br"})

    assert upstream.state.seen[0]["accept-encoding"] == "br"
