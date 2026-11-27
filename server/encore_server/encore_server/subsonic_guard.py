"""Counting wrong logins at HOME on `/rest`, from the music server's own answer (P3-34 slice 2b, audit B-56). The pure half: no services, no network.

At home the music server, not this server, checks a Subsonic login: the gateway passes the call on. The audit measured sixty wrong logins in 0.3 s, none refused. They cannot be checked here
without breaking the apps that send `p=` (a plain password, the only thing some third-party apps can send), so they are COUNTED from what the music server answers, and a guesser who has had
too many wrong answers is refused BEFORE the call is passed on, in the format the app asked for.

What the gateway reads is exactly what was measured on the real music server (Navidrome 0.64.2, `tests/integration/test_subsonic_login_answers.py`): a wrong login is ALWAYS HTTP 200, a small
`application/xml`, `application/json` or `application/javascript` answer (194 to 241 bytes) with a `Content-Length` and never chunked, carrying the error code 40, whatever the form of the
credential (token and salt, `p=`, `p=enc:`), the format and the endpoint. So only a small, sized answer of those types is ever read; a song, a picture, a large list or an answer without a
length streams untouched and counts as ACCEPTED. A right login that asks for something that is not there is code 70, which is not a login error and is never counted.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from .auth import subsonic_credentials

#: The Subsonic error codes that say "that login is no good" (the same set the verifier uses): wrong name or password (40), token authentication not supported for this account (41), a
#: mechanism that is not supported (42, 43) and a wrong API key (44).
LOGIN_REFUSED = frozenset({40, 41, 42, 43, 44})

#: The most bytes of an answer the gateway will read. A wrong-login answer is about two hundred.
READ_AT_MOST = 2048

_READABLE_TYPES = frozenset({"application/json", "application/xml", "text/xml", "application/javascript", "text/javascript"})
_USER = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
_CALLBACK = re.compile(r"^[A-Za-z0-9_.$]{1,64}$")
_XML_CODE = re.compile(rb'<error\b[^>]*\bcode="(\d+)"')


class HomeLogin:
    """What an app sent to say who it is, reduced to what the guard needs: the name, and a `token` and `salt` that identify the credential without being it (a token login is its own `t`
    and `s`; a plain password is `p:` and the password as written, which only ever goes into a keyed digest and is never stored)."""

    __slots__ = ("salt", "token", "user")

    def __init__(self, user: str, token: str, salt: str) -> None:
        self.user, self.token, self.salt = user, token, salt

    def __eq__(self, other: object) -> bool:
        return isinstance(other, HomeLogin) and (self.user, self.token, self.salt) == (other.user, other.token, other.salt)

    def __hash__(self) -> int:
        return hash((self.user, self.token, self.salt))

    def __repr__(self) -> str:  # never the credential
        return f"HomeLogin(user={self.user!r})"


def login_of(query: Mapping[str, str], form: Mapping[str, str] | None = None) -> HomeLogin | None:
    """The login an app sent, or `None` for a call that carries none the guard can count (no name, no secret, an API key: this music server takes none): such a call is passed on untouched.
    The query wins over a form body; a token login wins over a plain password."""
    params = {**(form or {}), **query}
    token_login = subsonic_credentials(params, {})
    if token_login is not None:
        user, token, salt = token_login
        return HomeLogin(user, token, salt)
    user = params.get("u", "")
    plain = params.get("p", "")
    if _USER.match(user) and plain and len(plain) <= 256:
        return HomeLogin(user, "p:" + plain, "")
    return None


def is_readable(status: int, content_type: str, content_length: str | None, chunked: bool) -> bool:
    """May the gateway read this answer? Only a 200 of a json or xml type with a small `Content-Length` that is not chunked: anything else is not what a wrong login looks like."""
    if status != 200 or chunked or content_length is None:
        return False
    try:
        size = int(content_length)
    except ValueError:
        return False
    return 0 <= size <= READ_AT_MOST and content_type.split(";")[0].strip().lower() in _READABLE_TYPES


def refusal_code(body: bytes) -> int | None:
    """The error code of a Subsonic answer in xml, json or jsonp, or `None` when it carries none (an ok, a page, anything else)."""
    found = _XML_CODE.search(body)
    if found:
        return int(found.group(1))
    text = body.decode("utf-8", "replace")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        code = json.loads(text[start : end + 1])["subsonic-response"]["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def is_login_refusal(body: bytes) -> bool:
    return refusal_code(body) in LOGIN_REFUSED


def format_of(params: Mapping[str, str]) -> tuple[str, str]:
    """How the app wants answers: `("xml", "")` (the default), `("json", "")` or `("jsonp", callback)`."""
    wanted = params.get("f", "")
    if wanted == "json":
        return "json", ""
    if wanted == "jsonp":
        callback = params.get("callback", "")
        return "jsonp", callback if _CALLBACK.match(callback) else "callback"
    return "xml", ""


def refusal_body(fmt: str, callback: str, message: str) -> tuple[bytes, str]:
    """The one answer this server writes itself at the home door: a Subsonic error of its own (code 0, never a login error) in the format the app asked for, and its content type."""
    safe = message.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    if fmt == "xml":
        text = (
            '<subsonic-response xmlns="http://subsonic.org/restapi" status="failed" version="1.16.1" type="encore">'
            f'<error code="0" message="{safe}"></error></subsonic-response>'
        )
        return text.encode(), "application/xml"
    inner = json.dumps(
        {
            "subsonic-response": {
                "status": "failed",
                "version": "1.16.1",
                "type": "encore",
                "error": {"code": 0, "message": message},
            }
        },
        separators=(",", ":"),
    )
    if fmt == "jsonp":
        return f"{callback}({inner})".encode(), "application/javascript"
    return inner.encode(), "application/json"
