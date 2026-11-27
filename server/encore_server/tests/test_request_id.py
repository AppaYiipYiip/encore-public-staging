"""P1-19, the server's half: every request carries an id (`request_id.py`).

A failure is followed from the phone to the server's log by one id. These tests pin: what is believed from the phone (only a plain id), that every answer carries the id, that the id is in the
error body and in the log line of a request that failed, that **no query string, token or signed address reaches a line**, and that the id goes on to the music server.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.errors import ApiError
from encore_server.request_id import PLAIN, RequestIdFilter, RequestIdMiddleware, new_id, plain, request_id_var
from tests.conftest import FakeVerifier
from tests.test_gateway import music_server

ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


# ---------------------------------------------------------------------------------------------------------------------- the id


def test_a_made_id_is_a_ulid_that_sorts_by_time_and_is_never_the_same_twice() -> None:
    first, later = new_id(1_000_000), new_id(2_000_000)
    assert ULID.match(first) and ULID.match(later)
    assert first < later, "the time comes first"
    assert len({new_id() for _ in range(2000)}) == 2000
    assert PLAIN.match(new_id())


@pytest.mark.parametrize("good", ["01JD5Q8Y2K7X9M4N6P1R3S5T7V", "abc12345", "a-b_c-d_e", "x" * 64])
def test_a_plain_id_is_believed(good: str) -> None:
    assert plain(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "short",
        "x" * 65,
        "has space in it",
        "semi;colon-xx",
        "new\nline-xxxx",
        'quo"te-xxxx',
        "<script>xx",
        "tab\tabcdefg",
        "ünïcode-idxx",
        None,
    ],
)
def test_anything_else_is_not_believed(bad: str | None) -> None:
    assert plain(bad) is None


# ---------------------------------------------------------------------------------------------------------------------- the middleware


def tiny(slow_ms: int = 2000) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware, slow_ms=slow_ms)

    @app.get("/fine/{name}")
    def fine(name: str) -> dict[str, str]:
        logging.getLogger("encore_server.test").warning("inside %s", request_id_var.get())
        return {"id": request_id_var.get()}

    @app.get("/missing")
    def missing() -> None:
        raise HTTPException(status_code=404)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("no")

    return app


def test_every_answer_carries_the_id_of_its_request() -> None:
    client = TestClient(tiny(), raise_server_exceptions=False)
    mine = "01JD5Q8Y2K7X9M4N6P1R3S5T7V"

    given = client.get("/fine/x", headers={"X-Request-Id": mine})
    made = client.get("/fine/x")
    refused = client.get("/missing")

    assert given.headers["x-request-id"] == mine and given.json() == {"id": mine}, "a plain id from the phone is the id"
    assert ULID.match(made.headers["x-request-id"]) and made.json()["id"] == made.headers["x-request-id"], "none: one is made"
    assert refused.status_code == 404 and ULID.match(refused.headers["x-request-id"]), "also on a refusal"


@pytest.mark.parametrize("bad", ["short", "has space in it", "x" * 200, "semi;colon-xx"])
def test_an_id_that_is_not_plain_is_replaced_not_echoed(bad: str) -> None:
    answer = TestClient(tiny()).get("/fine/x", headers={"X-Request-Id": bad})
    assert answer.headers["x-request-id"] != bad and ULID.match(answer.headers["x-request-id"])


def test_the_id_is_in_the_log_line_of_a_failed_request_and_in_the_lines_written_while_it_was_handled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logging.getLogger().handlers  # noqa: B018 - the capture handler is on the root logger
    handler = caplog.handler
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter("%(name)s%(rid)s: %(message)s"))
    client = TestClient(tiny(), raise_server_exceptions=False)
    mine = "01JD5Q8Y2K7X9M4N6P1R3S5T7V"
    with caplog.at_level(logging.INFO):
        client.get("/fine/x", headers={"X-Request-Id": mine})
        client.get("/missing", headers={"X-Request-Id": mine, "X-Device-Id": "device-123456"})

    lines = [handler.format(r) for r in caplog.records]
    assert f"encore_server.test [{mine}]: inside {mine}" in lines, "a line written while the request was handled has its id"
    failed = [line for line in lines if line.startswith(f"encore_server.access [{mine}]") and "status=404" in line]
    assert failed and "route=/missing" in failed[0] and "device=device-123456" in failed[0] and "event=request" in failed[0]
    assert not any("status=200" in line for line in lines), "a quick success is not written at INFO"


def test_a_line_never_holds_the_address_as_it_was_asked_so_no_token_or_name_reaches_it(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(tiny(slow_ms=0), raise_server_exceptions=False)  # every request is "slow": written at INFO
    secret = "SECRET-TOKEN-0123456789"
    with caplog.at_level(logging.INFO, logger="encore_server.access"):
        client.get(f"/fine/{secret}?t={secret}&sig={secret}&e=999", headers={"Authorization": f"Bearer {secret}"})

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "route=/fine/{name}" in text, "the route's own pattern is what is written"
    assert secret not in text and "sig=" not in text and "Bearer" not in text


def test_a_request_that_blew_up_is_written_as_a_500_and_the_error_still_reaches_the_server_handlers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(tiny(), raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="encore_server.access"):
        answer = client.get("/boom")

    assert answer.status_code == 500
    assert any("status=500" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------------------------------------------------- the real app


@pytest.fixture()
def app_client(tmp_path: Path, verifier: FakeVerifier) -> Iterator[TestClient]:
    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.test", youtube=False)
    with TestClient(create_app(settings, verifier=verifier)) as client:
        yield client


def test_an_error_body_names_the_request_that_failed_and_the_header_says_the_same(app_client: TestClient) -> None:
    mine = "01JD5Q8Y2K7X9M4N6P1R3S5T7V"

    answer = app_client.get("/encore/api/v1/me", headers={"X-Request-Id": mine})

    assert answer.status_code == 401
    assert answer.headers["x-request-id"] == mine
    assert answer.json()["error"]["requestId"] == mine, "the phone shows this id; `encore logs` holds the same one"


def test_an_error_body_of_a_request_with_no_id_carries_the_one_the_server_made(app_client: TestClient) -> None:
    answer = app_client.get("/encore/api/v1/me")

    assert answer.json()["error"]["requestId"] == answer.headers["x-request-id"] and ULID.match(answer.headers["x-request-id"])


def test_the_other_error_answers_carry_it_too(app_client: TestClient) -> None:
    unknown = app_client.get("/encore/api/v1/no-such-route")
    invalid = app_client.post("/encore/api/v1/auth/sign-in", content=b"not json", headers={"content-type": "application/json"})

    for answer in (unknown, invalid):
        assert answer.status_code in (400, 404, 422), answer.status_code
        assert answer.json()["error"]["requestId"] == answer.headers["x-request-id"]


def test_an_error_made_outside_a_request_has_no_id() -> None:
    assert "requestId" not in ApiError("not_found").body()["error"]
    assert ApiError("not_found").body("01JD5Q8Y2K7X9M4N6P1R3S5T7V")["error"]["requestId"] == "01JD5Q8Y2K7X9M4N6P1R3S5T7V"


# ---------------------------------------------------------------------------------------------------------------------- the music server


@pytest.fixture()
def gateway_rig(tmp_path: Path, verifier: FakeVerifier) -> Iterator[tuple[TestClient, FastAPI]]:
    upstream = music_server()
    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.test", youtube=False)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream), timeout=5)
    with TestClient(create_app(settings, verifier=verifier, gateway_client=http)) as client:
        yield client, upstream


def test_the_phones_id_goes_on_to_the_music_server_and_comes_back_on_the_answer(gateway_rig: tuple[TestClient, FastAPI]) -> None:
    client, upstream = gateway_rig
    mine = "01JD5Q8Y2K7X9M4N6P1R3S5T7V"

    answer = client.get("/rest/ping.view?u=a&t=b&s=c&v=1.16.1&c=encore&f=json", headers={"X-Request-Id": mine})

    assert upstream.state.seen[-1]["x-request-id"] == mine
    assert answer.headers["x-request-id"] == mine


def test_a_request_with_no_plain_id_is_given_one_before_it_reaches_the_music_server(
    gateway_rig: tuple[TestClient, FastAPI],
) -> None:
    client, upstream = gateway_rig

    client.get("/rest/ping.view?u=a&t=b&s=c&v=1.16.1&c=encore&f=json", headers={"X-Request-Id": "not plain!"})
    client.get("/rest/ping.view?u=a&t=b&s=c&v=1.16.1&c=encore&f=json")

    assert [ULID.match(seen["x-request-id"]) is not None for seen in upstream.state.seen[-2:]] == [True, True]
    assert upstream.state.seen[-1]["x-request-id"] != upstream.state.seen[-2]["x-request-id"]
