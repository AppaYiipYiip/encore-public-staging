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
    login = guard.login_of({"u": "marwa", "t": "a" * 32, "s": "salt1234", "v": "1.16.1"})

    assert login == guard.HomeLogin("marwa", "a" * 32, "salt1234")


@pytest.mark.parametrize(
    "params",
    [
        {"u": "mar wa", "p": "x"},  # a name with a space (an attached music server may have them; this server makes none)
        {"u": "José Maria", "t": "a" * 32, "s": "salt1234"},
        {"u": "marwa", "t": "a" * 32, "s": "x"},  # a salt of one character: the music server takes any salt
        {"u": "marwa", "t": "a" * 32, "s": "a-b_c!"},
        {
            "u": "marwa",
            "t": "short",
            "s": "salt1234",
        },  # a token that can never be right is still a wrong answer the music server gives
        {"u": "marwa", "t": "a" * 32},
        {"u": "x" * 65, "p": "x"},
        {"u": "marwa", "p": "x" * 3000},
    ],
)
def test_whatever_the_music_server_checks_is_a_login_the_guard_counts(params: dict[str, str]) -> None:
    """The guard decides on what the music server READS, not on what an app of this server would send (P3-34 slice 2c): a login the guard did not recognise was a free guess."""
    login = guard.login_of(params)

    assert login is not None and login.user == params["u"]


@pytest.mark.parametrize("name", ["", "mar\x00wa", "mar\nwa", "x" * 257])
def test_a_name_with_a_control_character_or_far_too_long_is_not_a_login(name: str) -> None:
    assert guard.login_of({"u": name, "p": "x"}) is None


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
        {"u": "", "p": "x"},
        {"u": "marwa", "p": ""},
        {"u": "marwa", "t": "", "s": ""},
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


# ------------------------------------------------------------------------------------------------------------------------------ review of 2b (the advisor)

JSON_10 = JSON_40.replace(b'"code":40', b'"code":10').replace(b"Wrong username or password", b"Required parameter is missing")


@pytest.mark.parametrize(
    ("status", "content_type", "length", "chunked", "encoded", "expected"),
    [
        # a small sized json or xml answer, as sent: read it
        (200, "application/json", "194", False, False, "read"),
        (200, "application/xml", "241", False, False, "read"),
        # positive evidence the login passed WITHOUT reading: a song, a picture, a list far larger than any refusal
        (200, "audio/ogg", None, True, False, "accepted"),
        (206, "audio/mpeg", "9000", False, False, "accepted"),
        (200, "image/jpeg", None, True, False, "accepted"),
        (200, "application/json", "51234", False, False, "accepted"),
        (200, "application/xml", "9001", False, False, "accepted"),
        # compressed: a refusal cannot be read, a large body cannot be one
        (200, "application/json", "150", False, True, "unknown"),
        (200, "application/json", "51234", False, True, "accepted"),
        # no evidence either way: neither counted nor remembered
        (200, "application/json", None, False, False, "unknown"),
        (200, "application/json", "194", True, False, "unknown"),
        (200, "application/octet-stream", "194", False, False, "unknown"),
        (200, "text/html", "194", False, False, "unknown"),
        (200, "", "194", False, False, "unknown"),
        (500, "application/json", "194", False, False, "unknown"),
        (404, "audio/ogg", "194", False, False, "unknown"),
        (401, "image/jpeg", None, False, False, "unknown"),
        (200, "application/json", "nonsense", False, False, "unknown"),
    ],
)
def test_what_the_gateway_does_with_an_answer_is_decided_on_evidence_not_on_the_absence_of_a_refusal(
    status: int, content_type: str, length: str | None, chunked: bool, encoded: bool, expected: str
) -> None:
    assert guard.how_to_read(status, content_type, length, chunked, encoded) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (XML_40, "refused"),
        (JSON_40, "refused"),
        (JSONP_40, "refused"),
        (JSON_OK, "accepted"),
        (XML_OK, "accepted"),
        (JSON_70, "accepted"),
        (JSON_40.replace(b'"code":40', b'"code":50'), "accepted"),
        (JSON_40.replace(b'"code":40', b'"code":60'), "accepted"),
        # NOT evidence of a login that passed: a missing parameter (10), a version (20, 30), a generic error (0), a page, nothing
        (JSON_10, "unknown"),
        (JSON_40.replace(b'"code":40', b'"code":0'), "unknown"),
        (JSON_40.replace(b'"code":40', b'"code":20'), "unknown"),
        (JSON_40.replace(b'"code":40', b'"code":30'), "unknown"),
        (b"", "unknown"),
        (b"<html></html>", "unknown"),
    ],
)
def test_a_small_answer_is_a_refusal_an_acceptance_or_nothing_we_can_tell(body: bytes, expected: str) -> None:
    """Code 10 ("a parameter is missing") means the login was never checked: it must never make a login a known device."""
    assert guard.judge(body) == expected


@pytest.mark.parametrize(
    ("query", "form", "expected"),
    [
        ([("u", "marwa"), ("p", "x")], None, False),
        ([("u", "marwa"), ("t", "a" * 32), ("s", "salt1234")], None, False),
        ([("u", "marwa"), ("u", "decoy"), ("p", "x")], None, True),
        ([("u", "marwa"), ("p", "x"), ("p", "y")], None, True),
        ([("u", "marwa"), ("t", "a" * 32), ("t", "b" * 32), ("s", "salt1234")], None, True),
        ([("u", "marwa"), ("t", "a" * 32), ("s", "salt1234"), ("s", "salt5678")], None, True),
        ([("u", "marwa"), ("apiKey", "k"), ("apiKey", "j")], None, True),
        (
            [("u", "marwa"), ("p", "x")],
            [("u", "marwa"), ("p", "x")],
            True,
        ),  # the same name in the address AND the body: which does the music server read?
        ([("u", "marwa")], [("p", "x")], False),  # one name in each place, each once
        ([], [("u", "marwa"), ("u", "decoy")], True),
        (
            [("v", "1.16.1"), ("v", "1.15.0"), ("u", "marwa"), ("p", "x")],
            None,
            False,
        ),  # a repeated NAME that is not a login name is the music server's own business
        ([("id", "1"), ("id", "2"), ("u", "marwa"), ("p", "x")], None, False),
    ],
)
def test_a_login_named_twice_is_ambiguous_because_two_readers_could_pick_two_different_ones(
    query: list[tuple[str, str]], form: list[tuple[str, str]] | None, expected: bool
) -> None:
    """The guard counts one login; the music server checks one login; if the call names a part of it twice they may not be the same one (a decoy). Real apps never do this."""
    assert guard.is_ambiguous(query, form) is expected


def test_the_login_is_read_from_the_address_and_the_body_only_never_from_a_header() -> None:
    assert guard.read_login([("u", "marwa"), ("p", "x")], None) == guard.HomeLogin("marwa", "p:x", "")
    assert guard.read_login([], [("u", "marwa"), ("t", "c" * 32), ("s", "salt1234")]) == guard.HomeLogin(
        "marwa", "c" * 32, "salt1234"
    )
    assert guard.read_login([("u", "marwa")], [("p", "x")]) == guard.HomeLogin("marwa", "p:x", "")


def test_the_refusal_for_a_repeated_name_is_a_subsonic_answer_with_code_10() -> None:
    body, kind = guard.refusal_body("json", "", "Send your name and password once.", code=10)

    assert kind == "application/json" and guard.refusal_code(body) == 10
    assert guard.judge(body) == "unknown", "and it is never taken for a login that passed"
