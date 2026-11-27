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
from collections.abc import Mapping, Sequence

from .auth import subsonic_credentials

#: The Subsonic error codes that say "that login is no good" (the same set the verifier uses): wrong name or password (40), token authentication not supported for this account (41), a
#: mechanism that is not supported (42, 43) and a wrong API key (44).
LOGIN_REFUSED = frozenset({40, 41, 42, 43, 44})

#: The Subsonic error codes that can only come AFTER the login passed: the user may not do that (50), the trial is over (60), there is no such thing (70). Code 10 ("a parameter is missing") is
#: NOT one of them: the login was never looked at.
POST_LOGIN_CODES = frozenset({50, 60, 70})

#: The names an app logs in with. One that is named twice in a call is ambiguous (see [is_ambiguous]).
LOGIN_NAMES = frozenset({"u", "p", "t", "s", "apiKey"})

#: The most bytes of an answer the gateway will read. A wrong-login answer is about two hundred.
READ_AT_MOST = 2048

_MEDIA = ("audio/", "image/", "video/")

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


def is_ambiguous(query: Sequence[tuple[str, str]], form: Sequence[tuple[str, str]] | None = None) -> bool:
    """Does the call name a part of its login (`u`, `p`, `t`, `s`, `apiKey`) more than once, in the address or in the form body or in both, or carry two kinds of secret (a token AND a plain
    password)? The guard counts ONE login and the music server checks ONE login; given two values of one name two readers may pick two different ones (measured on 0.64.2: the FIRST of a
    repeated name wins, and a value in the body beats one in the address; a Python reader takes the last), and a decoy in the one the guard reads would leave the real one unchecked and
    uncounted. Real apps never do it, so such a call is refused rather than guessed at."""
    seen: set[str] = set()
    for name, _ in [*query, *(form or [])]:
        if name in LOGIN_NAMES:
            if name in seen:
                return True
            seen.add(name)
    # Two KINDS of secret in one call (a token and a plain password, an API key and anything): the music server picks one, the guard may pick the other.
    return sum(1 for kind in (("t", "s"), ("p",), ("apiKey",)) if seen.intersection(kind)) > 1


def read_login(query: Sequence[tuple[str, str]], form: Sequence[tuple[str, str]] | None = None) -> HomeLogin | None:
    """The login of a call whose names are NOT ambiguous: from the address and the body, never from a header (the music server reads none)."""
    return login_of(dict(query), dict(form) if form is not None else None)


def how_to_read(status: int, content_type: str, content_length: str | None, chunked: bool, encoded: bool) -> str:
    """What the gateway does with the answer to a call that carried a login: `"read"` (a small sized json or xml answer: read it and judge it), `"accepted"` (positive evidence that the login
    passed, without reading: a song or a picture, or a json or xml answer far too large to be a refusal) or `"unknown"` (neither counted nor remembered). The absence of a refusal is NOT evidence:
    an answer that could not be read (compressed, unsized, chunked) may well have been one."""
    if status not in (200, 206):
        return "unknown"
    kind = content_type.split(";")[0].strip().lower()
    if kind.startswith(_MEDIA):
        return "accepted"
    if kind not in _READABLE_TYPES:
        return "unknown"
    try:
        size = int(content_length) if content_length is not None else -1
    except ValueError:
        size = -1
    if size > READ_AT_MOST:
        return "accepted"  # a wrong-login answer is about two hundred bytes, compressed or not (measured)
    if status == 200 and not encoded and not chunked and is_readable(status, content_type, content_length, chunked):
        return "read"
    return "unknown"


def judge(body: bytes) -> str:
    """What a small answer says about the login: `"refused"` (a code in 40 to 44), `"accepted"` (an ok, or a code that can only come after the login passed) or `"unknown"` (anything else,
    code 10 among it: a parameter was missing, the login was never looked at)."""
    code = refusal_code(body)
    if code in LOGIN_REFUSED:
        return "refused"
    if code in POST_LOGIN_CODES:
        return "accepted"
    if code is None and _is_ok(body):
        return "accepted"
    return "unknown"


def _is_ok(body: bytes) -> bool:
    if re.search(rb'<subsonic-response\b[^>]*\bstatus="ok"', body):
        return True
    text = body.decode("utf-8", "replace")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return False
    try:
        return bool(json.loads(text[start : end + 1])["subsonic-response"]["status"] == "ok")
    except (ValueError, KeyError, TypeError):
        return False


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


def refusal_body(fmt: str, callback: str, message: str, code: int = 0) -> tuple[bytes, str]:
    """The one answer this server writes itself at the home door: a Subsonic error of its own (code 0, or 10 for a call that names its login twice; never a login error) in the format the app
    asked for, and its content type."""
    safe = message.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    if fmt == "xml":
        text = (
            '<subsonic-response xmlns="http://subsonic.org/restapi" status="failed" version="1.16.1" type="encore">'
            f'<error code="{code}" message="{safe}"></error></subsonic-response>'
        )
        return text.encode(), "application/xml"
    inner = json.dumps(
        {
            "subsonic-response": {
                "status": "failed",
                "version": "1.16.1",
                "type": "encore",
                "error": {"code": code, "message": message},
            }
        },
        separators=(",", ":"),
    )
    if fmt == "jsonp":
        return f"{callback}({inner})".encode(), "application/javascript"
    return inner.encode(), "application/json"
