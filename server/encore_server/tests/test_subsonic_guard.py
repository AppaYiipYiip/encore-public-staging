"""The pure half of counting wrong logins at HOME on `/rest` from the music server's own answer (P3-34 slice 2b; `subsonic_guard.py`).

The shapes below are the ones MEASURED on the real music server (Navidrome 0.64.2, `tests/integration/test_subsonic_login_answers.py`, the log of CI run on PR 186): a wrong login in the
token form, as `p=` and as `p=enc:` is HTTP 200, `application/xml` (241 bytes), `application/json` (194) or `application/javascript` (198), with a `Content-Length`, never chunked, error code 40;
a right login on a missing song is code 70 (NOT a login error); no credential is code 10; an API key is code 10 (this music server takes none, so there is nothing to guess through it).
"""

from __future__ import annotations

import pytest

from encore_server import subsonic_guard as guard

XML_40 = (
    b'<subsonic-response xmlns="http://subsonic.org/restapi" status="failed" version="1.16.1" type="navidrome" serverVersion="0.64.2 (10114574)" openSubsonic="true">'
    b'<error code="40" message="Wrong username or password"></error></subsonic-response>'
)
JSON_40 = (
    b'{"subsonic-response":{"status":"failed","version":"1.16.1","type":"navidrome","serverVersion":"0.64.2 (10114574)","openSubsonic":true,'
    b'"error":{"code":40,"message":"Wrong username or password"}}}'
)
JSONP_40 = b"cb(" + JSON_40 + b")"
JSON_70 = JSON_40.replace(b'"code":40', b'"code":70').replace(b"Wrong username or password", b"Song not found")
JSON_OK = b'{"subsonic-response":{"status":"ok","version":"1.16.1","type":"navidrome","serverVersion":"0.64.2 (10114574)","openSubsonic":true}}'
XML_OK = b'<subsonic-response xmlns="http://subsonic.org/restapi" status="ok" version="1.16.1"></subsonic-response>'


@pytest.mark.parametrize("body", [XML_40, JSON_40, JSONP_40])
def test_a_wrong_login_answer_is_recognised_in_xml_json_and_jsonp(body: bytes) -> None:
    assert guard.refusal_code(body) == 40
    assert guard.is_login_refusal(body) is True


@pytest.mark.parametrize("code", [41, 42, 43, 44])
def test_the_other_login_refusals_count_too(code: int) -> None:
    assert guard.is_login_refusal(JSON_40.replace(b'"code":40', f'"code":{code}'.encode())) is True


@pytest.mark.parametrize(
    "body",
    [
        JSON_70,
        JSON_OK,
        XML_OK,
        b"",
        b"not an answer at all",
        b'{"subsonic-response":{"status":"failed","error":{"code":"x"}}}',
        b"{}",
        b"<html></html>",
    ],
)
def test_an_answer_that_is_not_a_login_refusal_is_not_counted(body: bytes) -> None:
    """A right login that asks for a song that is not there (70), an ok, an answer that is not an answer: none of them is a wrong guess."""
    assert guard.is_login_refusal(body) is False


@pytest.mark.parametrize(
    ("status", "content_type", "length", "chunked", "readable"),
    [
        (200, "application/xml", "241", False, True),
        (200, "application/json", "194", False, True),
        (200, "application/javascript", "198", False, True),
        (200, "application/json; charset=utf-8", "194", False, True),
        (200, "application/json", "2048", False, True),
        (200, "application/json", "2049", False, False),
        (200, "application/json", None, False, False),
        (200, "application/json", "194", True, False),
        (200, "audio/ogg", "194", False, False),
        (200, "image/jpeg", "194", False, False),
        (200, "application/octet-stream", "194", False, False),
        (206, "application/json", "194", False, False),
        (401, "application/json", "194", False, False),
        (200, "application/json", "nonsense", False, False),
        (200, "", "194", False, False),
    ],
)
def test_only_a_small_sized_json_or_xml_answer_is_ever_read(
    status: int, content_type: str, length: str | None, chunked: bool, readable: bool
) -> None:
    """Everything else (a song, a picture, a large list, an answer without a length) streams untouched and counts as accepted: a wrong login is never any of those (measured)."""
    assert guard.is_readable(status, content_type, length, chunked) is readable


def test_a_token_login_is_read_from_the_query() -> None:
    login = guard.login_of({"u": "marwa", "t": "A" * 32, "s": "salt1234", "v": "1.16.1"})

    assert login == guard.HomeLogin("marwa", "a" * 32, "salt1234")


def test_a_plain_password_login_is_read_as_p_whatever_its_spelling() -> None:
    plain = guard.login_of({"u": "marwa", "p": "hunter2"})
    hexed = guard.login_of({"u": "marwa", "p": "enc:68756e74657232"})

    assert plain is not None and hexed is not None
    assert plain.user == "marwa" and plain.salt == "" and plain.token.startswith("p:")
    assert plain.token != hexed.token, "the two spellings are two credentials; neither is stored anywhere readable"


def test_a_token_login_wins_when_an_app_sends_both() -> None:
    login = guard.login_of({"u": "marwa", "t": "b" * 32, "s": "salt1234", "p": "hunter2"})

    assert login is not None and login.salt == "salt1234"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"u": "marwa"},
        {"p": "hunter2"},
        {"u": "marwa", "apiKey": "ndk-abcdef"},
        {"u": "mar wa", "p": "x"},
        {"u": "", "p": "x"},
        {"u": "marwa", "t": "short", "s": "salt1234"},
        {"u": "marwa", "t": "a" * 32},
        {"u": "marwa", "p": ""},
        {"u": "x" * 65, "p": "x"},
        {"u": "marwa", "p": "x" * 300},
    ],
)
def test_what_is_not_a_login_is_none_and_left_alone(params: dict[str, str]) -> None:
    assert guard.login_of(params) is None


def test_the_form_body_of_a_post_is_read_too_and_the_query_wins() -> None:
    """The OpenSubsonic form post: the credential is in the body, not in the address."""
    assert guard.login_of({}, {"u": "marwa", "p": "hunter2"}) is not None
    login = guard.login_of({"u": "nina", "p": "q"}, {"u": "marwa", "p": "hunter2"})
    assert login is not None and login.user == "nina"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, ("xml", "")),
        ({"f": "xml"}, ("xml", "")),
        ({"f": "json"}, ("json", "")),
        ({"f": "jsonp", "callback": "cb"}, ("jsonp", "cb")),
        ({"f": "jsonp"}, ("jsonp", "callback")),
        ({"f": "jsonp", "callback": "a b<script>"}, ("jsonp", "callback")),
        ({"f": "something else"}, ("xml", "")),
    ],
)
def test_the_format_an_app_asked_for(params: dict[str, str], expected: tuple[str, str]) -> None:
    assert guard.format_of(params) == expected


@pytest.mark.parametrize(
    ("fmt", "callback", "content_type", "marker"),
    [
        ("xml", "", "application/xml", b"<subsonic-response"),
        ("json", "", "application/json", b'{"subsonic-response"'),
        ("jsonp", "cb", "application/javascript", b'cb({"subsonic-response"'),
    ],
)
def test_the_refusal_is_a_small_subsonic_answer_in_the_format_asked_for(
    fmt: str, callback: str, content_type: str, marker: bytes
) -> None:
    body, kind = guard.refusal_body(fmt, callback, "Too many wrong tries. Wait a moment.")

    assert kind == content_type and body.startswith(marker) and len(body) < guard.READ_AT_MOST
    assert b"Too many wrong tries" in body
    assert guard.refusal_code(body) == 0, (
        "an error answer of its own (code 0), never a login error: it is not counted when it comes back through a client's retry"
    )
    assert guard.is_login_refusal(body) is False
