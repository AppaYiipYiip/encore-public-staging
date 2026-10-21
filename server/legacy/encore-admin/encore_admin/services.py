"""The other services, asked as the signed-in owner: the music server (is this login right, is it an administrator), the people
service (may this person manage), and the fetch service (the YouTube accounts, the sign-in window's profile)."""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

log = logging.getLogger("encore_admin.services")

#: `(method, url, json body or None) -> (status, parsed JSON or {})`; the tests give a fake.
Http = Callable[[str, str, "dict | None"], "tuple[int, dict]"]


def http_json(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": "encore-admin/1", **({"Content-Type": "application/json"} if data is not None else {})})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - the stack's own network
            raw = response.read(2_000_000)
            status = response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(2_000_000), error.code
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, {}
    try:
        parsed = json.loads(raw or b"{}")
    except ValueError:
        parsed = {}
    return status, parsed if isinstance(parsed, dict) else {}


def token_login(password: str) -> tuple[str, str]:
    """The music server's token form of a password: `(token, salt)`. The password itself is not kept."""
    salt = secrets.token_hex(6)
    return hashlib.md5((password + salt).encode("utf-8")).hexdigest(), salt  # noqa: S324 - Subsonic's token scheme


class Services:
    def __init__(self, *, navidrome_url: str, people_url: str, fetch_url: str, quality_url: str = "", recs_url: str = "",
                 http: Http = http_json) -> None:
        self._nd = navidrome_url.rstrip("/")
        self._people = people_url.rstrip("/")
        self._fetch = fetch_url.rstrip("/")
        self._quality = quality_url.rstrip("/")
        self._recs = recs_url.rstrip("/")
        self._http = http

    @staticmethod
    def _creds(user: str, token: str, salt: str) -> dict[str, str]:
        return {"u": user, "t": token, "s": salt}

    # ------------------------------------------------------------------ who is this

    def music_login_ok(self, user: str, token: str, salt: str) -> bool:
        query = urllib.parse.urlencode({**self._creds(user, token, salt), "v": "1.16.1", "c": "encore-admin", "f": "json"})
        status, data = self._http("GET", f"{self._nd}/rest/ping.view?{query}", None)
        return status == 200 and data.get("subsonic-response", {}).get("status") == "ok"

    def is_owner(self, user: str, token: str, salt: str) -> bool:
        """The people service's word first (it knows the roles); a music-server administrator counts when it does not answer."""
        query = urllib.parse.urlencode(self._creds(user, token, salt))
        status, data = self._http("GET", f"{self._people}/api/me?{query}", None)
        if status == 200:
            return data.get("canManage") is True
        full = urllib.parse.urlencode({**self._creds(user, token, salt), "username": user, "v": "1.16.1",
                                       "c": "encore-admin", "f": "json"})
        status, data = self._http("GET", f"{self._nd}/rest/getUser.view?{full}", None)
        return status == 200 and bool(data.get("subsonic-response", {}).get("user", {}).get("adminRole"))

    # ------------------------------------------------------------------ the fetch service's owner routes

    def fetch_call(self, method: str, path: str, user: str, token: str, salt: str,
                   body: dict | None = None) -> tuple[int, dict]:
        """`path` is below `/fetch/api/admin/youtube` (starts with `/` or is empty)."""
        query = urllib.parse.urlencode(self._creds(user, token, salt))
        return self._http(method, f"{self._fetch}/api/admin/youtube{path}?{query}", body)

    def people_call(self, method: str, path: str, user: str, token: str, salt: str, body: dict | None = None) -> tuple[int, dict]:
        """`path` is below the people service's root (`/api/people`, ...). The owner's own login is passed on, as for the songs service."""
        query = urllib.parse.urlencode(self._creds(user, token, salt))
        return self._http(method, f"{self._people}{path}?{query}", body)

    def quality_call(self, method: str, path: str, user: str, token: str, salt: str, body: dict | None = None) -> tuple[int, dict]:
        """`path` is below the quality service's `/api/admin/quality` (empty, or starts with `/`). The owner's own login is passed on."""
        query = urllib.parse.urlencode(self._creds(user, token, salt))
        return self._http(method, f"{self._quality}/api/admin/quality{path}?{query}", body)

    def quality_up(self) -> bool:
        if not self._quality:
            return False
        status, _ = self._http("GET", f"{self._quality}/api/info", None)
        return status == 200

    def recs_call(self, method: str, path: str, user: str, token: str, salt: str, body: dict | None = None) -> tuple[int, dict]:
        """`path` is below the suggestions service's `/api/admin/recs` (empty, or starts with `/`). The owner's own login is passed on."""
        query = urllib.parse.urlencode(self._creds(user, token, salt))
        return self._http(method, f"{self._recs}/api/admin/recs{path}?{query}", body)

    def recs_up(self) -> bool:
        if not self._recs:
            return False
        status, _ = self._http("GET", f"{self._recs}/api/info", None)
        return status == 200

    def server_info(self) -> dict | None:
        """What the people service says about the whole server (its public `GET /api/server`), or None when it does not answer."""
        status, data = self._http("GET", f"{self._people}/api/server", None)
        return data if status == 200 and data else None

    def fetch_up(self) -> bool:
        status, _ = self._http("GET", f"{self._fetch}/api/info", None)
        return status == 200
