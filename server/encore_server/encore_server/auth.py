"""Who is asking (docs/04 `accounts`, docs/17 section 1, docs/21).

Two ways in:

* A **device token** (`Authorization: Bearer ...`): made once at sign-in, kept by the app instead of the password, revocable per device.
  Only its hash is stored here.
* The music server's **Subsonic token** (`u`, `t`, `s`, in the query or as `X-Encore-*` headers): what the apps send today. It is checked
  with the music server (which keeps the passwords) and the answer is remembered for ten minutes.

The password itself is never stored; at sign-in it is turned into a Subsonic token, checked once, and dropped.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx

from .errors import ApiError
from .ids import new_id, now_ms

_USER = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
_TOKEN = re.compile(r"^[0-9a-fA-F]{32}$")
_SALT = re.compile(r"^[A-Za-z0-9]{4,64}$")

VERIFY_TTL_S = 600.0


@dataclass(frozen=True)
class Principal:
    person_id: str
    navidrome_user: str
    role: str
    device_id: str | None = None


class Verifier(Protocol):
    def verify(self, user: str, token: str, salt: str) -> bool: ...

    def is_admin(self, user: str, token: str, salt: str) -> bool: ...


class NavidromeVerifier:
    """Asks the music server whether a Subsonic token is good; remembers a yes for [ttl] seconds."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        ttl: float = VERIFY_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=8.0)
        self._ttl = ttl
        self._clock = clock
        self._ok: dict[tuple[str, str, str], float] = {}

    def _call(self, method: str, user: str, token: str, salt: str, **extra: str) -> dict[str, object] | None:
        params = {"u": user, "t": token, "s": salt, "v": "1.16.1", "c": "encore-server", "f": "json", **extra}
        try:
            response = self._client.get(f"{self._base}/rest/{method}", params=params)
            body = response.json().get("subsonic-response")
        except (httpx.HTTPError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    def verify(self, user: str, token: str, salt: str) -> bool:
        key = (user, token, salt)
        seen = self._ok.get(key)
        if seen is not None and self._clock() - seen < self._ttl:
            return True
        body = self._call("ping", user, token, salt)
        if body is not None and body.get("status") == "ok":
            self._ok[key] = self._clock()
            if len(self._ok) > 2000:
                self._ok = {k: v for k, v in self._ok.items() if self._clock() - v < self._ttl}
            return True
        return False

    def is_admin(self, user: str, token: str, salt: str) -> bool:
        body = self._call("getUser", user, token, salt, username=user)
        found = body.get("user") if body else None
        return bool(isinstance(found, dict) and found.get("adminRole"))


def subsonic_token(password: str, salt: str) -> str:
    return hashlib.md5((password + salt).encode()).hexdigest()  # noqa: S324 - the Subsonic protocol's own token


def subsonic_credentials(query: dict[str, str], headers: dict[str, str]) -> tuple[str, str, str] | None:
    lower = {k.lower(): v for k, v in headers.items()}
    user = query.get("u") or lower.get("x-encore-user") or ""
    token = query.get("t") or lower.get("x-encore-token") or ""
    salt = query.get("s") or lower.get("x-encore-salt") or ""
    if _USER.match(user) and _TOKEN.match(token) and _SALT.match(salt):
        return user, token.lower(), salt
    return None


def new_device_token() -> str:
    return "ed_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_device(conn, person_id: str, name: str, kind: str = "phone", app_version: str | None = None) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """A new device for a person. Returns (device id, the token, shown once: only its hash is kept)."""
    device_id = new_id("dv")
    token = new_device_token()
    conn.execute(
        "INSERT INTO device (id, person, name, kind, token_hash, app_version, created_at, last_seen) VALUES (?,?,?,?,?,?,?,?)",
        (
            device_id,
            person_id,
            " ".join(name.split())[:80] or "Phone",
            kind if kind in {"phone", "tablet", "web", "pc", "other"} else "other",
            hash_token(token),
            app_version,
            now_ms(),
            now_ms(),
        ),
    )
    return device_id, token


def bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    return token if token.startswith("ed_") and len(token) < 200 else None


def require(principal: Principal | None) -> Principal:
    if principal is None:
        raise ApiError("unauthorized")
    return principal


# ---- signed stream addresses (docs/17 section 1): a player cannot always set headers, so the address carries a signature.

#: How long a stream address works. Long, because a player keeps using the same address for a whole listen (a two-hour recitation).
STREAM_URL_TTL_S = 6 * 3600


def stream_secret(conn) -> bytes:  # type: ignore[no-untyped-def]
    """The server's secret for signing addresses: made once, kept in the database."""
    row = conn.execute("SELECT value FROM setting WHERE key = 'stream_secret'").fetchone()
    if row is not None:
        return bytes.fromhex(row["value"])
    secret = secrets.token_bytes(32)
    conn.execute("INSERT OR IGNORE INTO setting (key, value) VALUES ('stream_secret', ?)", (secret.hex(),))
    row = conn.execute("SELECT value FROM setting WHERE key = 'stream_secret'").fetchone()
    return bytes.fromhex(row["value"])


def sign_stream(secret: bytes, person: str, ref: str, expires_s: int) -> str:
    return hmac.new(secret, f"{person}|{ref}|{expires_s}".encode(), hashlib.sha256).hexdigest()[:32]


def valid_stream_signature(secret: bytes, person: str, ref: str, expires_s: int, sig: str, *, now_s: float | None = None) -> bool:
    if expires_s < (now_s if now_s is not None else time.time()):
        return False
    return hmac.compare_digest(sign_stream(secret, person, ref, expires_s), sig)
