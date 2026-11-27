"""P3-34 slice 2b: how the REAL music server (0.64.2) answers a Subsonic login, right and wrong, in every form an app sends it.

Counting wrong logins at HOME on `/rest` has to be done from the music server's own ANSWER (it, not this server, checks them there, and `p=` must keep working for third-party apps), so the
design rests on facts about those answers: that a wrong login is a SMALL json or xml body with a known error code and a `Content-Length`, whatever the form of the credential, the format and the
endpoint, so that the gateway can read exactly those and stream everything else (a song, a picture, a large list) untouched. This measures them, prints the table into the log of the run, and
asserts only the properties the design depends on; if any of them flips, the failure says which and the design is to be revisited.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pytest

from tests.integration.conftest import URL

pytestmark = pytest.mark.integration

#: The Subsonic error codes that say "that login is no good" (`auth._REFUSED`): wrong name or password (40), token authentication not supported for this account (41), mechanism not
#: supported (42, 43), wrong API key (44).
LOGIN_REFUSED = {40, 41, 42, 43, 44}

#: What the gateway will read: no more than this many bytes of a small json or xml body. A wrong-login answer is about a hundred and fifty.
SMALL = 2048


def token(password: str, salt: str) -> str:
    return hashlib.md5((password + salt).encode()).hexdigest()  # noqa: S324 - the Subsonic protocol's own token


def ask(endpoint: str, **params: str) -> dict[str, Any]:
    """One GET of `/rest/<endpoint>`: what came back, as the gateway would see it (status, content type, content length, the first bytes of the body, the error code if there is one)."""
    url = f"{URL}/rest/{endpoint}?{urllib.parse.urlencode({'v': '1.16.1', 'c': 'encore-measure', **params})}"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - the throwaway music server of the test rig
            status, headers, body = response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        status, headers, body = error.code, error.headers, error.read()
    text = body[:600].decode("utf-8", "replace")
    code = None
    found = re.search(r'"code"\s*:\s*(\d+)', text) or re.search(r'code="(\d+)"', text)
    if found:
        code = int(found.group(1))
    return {
        "status": status,
        "type": (headers.get("content-type") or "").split(";")[0].strip(),
        "length": headers.get("content-length"),
        "chunked": "chunked" in (headers.get("transfer-encoding") or ""),
        "size": len(body),
        "code": code,
        "ok": '"status":"ok"' in text.replace(" ", "") or 'status="ok"' in text,
        "body": text[:120].replace("\n", " "),
    }


def forms(user: str, password: str, *, wrong: bool) -> dict[str, dict[str, str]]:
    """Every way an app sends a credential: a token and a salt, the plain password, the password in hex, an API key."""
    salt = secrets.token_hex(6)
    guess = "not-the-password-" + secrets.token_hex(2) if wrong else password
    return {
        "t/s": {"u": user, "t": token(guess, salt), "s": salt},
        "p=plain": {"u": user, "p": guess},
        "p=enc:hex": {"u": user, "p": "enc:" + guess.encode().hex()},
        "apiKey": {"apiKey": "ndk-" + secrets.token_hex(12)},
    }


ENDPOINTS = {
    "ping": ("ping.view", {}),
    "getAlbumList2": ("getAlbumList2.view", {"type": "newest", "size": "1"}),
    "stream": ("stream.view", {"id": "no-such-song"}),
    "getCoverArt": ("getCoverArt.view", {"id": "no-such-cover"}),
}

FORMATS = {"xml (the default)": {}, "f=json": {"f": "json"}, "f=jsonp": {"f": "jsonp", "callback": "cb"}}


def test_a_wrong_login_is_a_small_json_or_xml_answer_with_a_length_and_an_error_code_in_every_form(
    accounts: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    person, password = accounts["person"], accounts["person_pw"]
    table: list[str] = []
    problems: list[str] = []

    for kind, credential in forms(person, password, wrong=True).items():
        for endpoint, (path, extra) in ENDPOINTS.items():
            for fmt, fmt_params in FORMATS.items():
                got = ask(path, **credential, **extra, **fmt_params)
                table.append(
                    f"WRONG {kind:10} {endpoint:14} {fmt:18} -> {got['status']} {got['type']:24} length={got['length']} chunked={got['chunked']} size={got['size']:4} code={got['code']} {got['body'][:70]}"
                )
                small = got["length"] is not None and int(got["length"]) <= SMALL and not got["chunked"]
                json_or_xml = got["type"] in (
                    "application/json",
                    "text/xml",
                    "application/xml",
                    "text/javascript",
                    "application/javascript",
                )
                # Measured on 0.64.2: a bogus API key is not a login attempt at all (code 10, a parameter is missing): this music server takes no API keys, so there is nothing to guess through it.
                refused = LOGIN_REFUSED | ({10} if kind == "apiKey" else set())
                if not (got["status"] == 200 and small and json_or_xml and got["code"] in refused):
                    problems.append(f"{kind} / {endpoint} / {fmt}: {got}")

    with capsys.disabled():
        print("\n=== P3-34 2b: how the music server (0.64.2) answers a WRONG login")
        print("\n".join(table))
    assert not problems, (
        "a wrong-login answer is not a small, sized json or xml body with a login-refused code; the design of 2b is to be revisited:\n"
        + "\n".join(problems)
    )


def test_a_right_login_and_a_missing_login_are_told_apart_from_a_wrong_one(
    accounts: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    person, password = accounts["person"], accounts["person_pw"]
    table: list[str] = []
    right_forms = forms(person, password, wrong=False)

    for kind in ("t/s", "p=plain", "p=enc:hex"):
        for fmt, fmt_params in FORMATS.items():
            got = ask("ping.view", **right_forms[kind], **fmt_params)
            table.append(
                f"RIGHT {kind:10} ping           {fmt:18} -> {got['status']} {got['type']:24} length={got['length']} size={got['size']:4} ok={got['ok']} code={got['code']}"
            )
            assert got["status"] == 200 and got["ok"] and got["code"] is None, (
                f"a right login ({kind}, {fmt}) was not an ok answer: {got}"
            )

    for endpoint, (path, extra) in ENDPOINTS.items():
        got = ask(path, **right_forms["t/s"], **extra, f="json")
        table.append(
            f"RIGHT t/s        {endpoint:14} f=json             -> {got['status']} {got['type']:24} length={got['length']} size={got['size']:4} code={got['code']} {got['body'][:60]}"
        )
        assert got["code"] not in LOGIN_REFUSED, f"a RIGHT login on {endpoint} was told it is a wrong login: {got}"

    missing = ask("ping.view", f="json")
    table.append(
        f"NONE  (no credential)  ping           f=json             -> {missing['status']} {missing['type']:24} length={missing['length']} size={missing['size']:4} code={missing['code']} {missing['body'][:60]}"
    )
    with capsys.disabled():
        print("\n=== P3-34 2b: how the music server answers a RIGHT login, and none")
        print("\n".join(table))
    assert missing["code"] is not None, f"a call with no credential at all was not an error answer: {missing}"
