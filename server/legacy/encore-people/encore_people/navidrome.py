"""The little the people service needs from the music server: who is asking (the same Subsonic token the app already sends) and whether that
person is an administrator. The music server is the only judge of passwords; this service never sees one."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Auth:
    """Subsonic token authentication: `t = md5(password + salt)`."""

    user: str
    token: str
    salt: str

    def params(self) -> dict[str, str]:
        return {"u": self.user, "t": self.token, "s": self.salt}


# (url) -> the `subsonic-response` object; raises on network trouble.
Http = Callable[[str], dict]


def urllib_http(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "encore-people/1"})
    with urllib.request.urlopen(request, timeout=12) as response:  # noqa: S310 - the music server, by configuration
        body = json.load(response)
    return body.get("subsonic-response", {})


class Navidrome:
    def __init__(self, base_url: str, *, http: Http = urllib_http, clock: Callable[[], float] = time.monotonic,
                 verify_ttl: float = 300.0) -> None:
        self._base = base_url.rstrip("/")
        self._http = http
        self._clock = clock
        self._ttl = verify_ttl
        self._verified: dict[Auth, float] = {}
        self._admins: dict[Auth, tuple[bool, float]] = {}

    def _url(self, method: str, auth: Auth, **params: object) -> str:
        query = {**auth.params(), "v": "1.16.1", "c": "encore-people", "f": "json"}
        query.update({k: str(v) for k, v in params.items()})
        return f"{self._base}/rest/{method}.view?{urllib.parse.urlencode(query)}"

    def verify(self, auth: Auth) -> bool:
        """`True` when the music server accepts these credentials. Remembered briefly so a polling app does not hammer it."""
        now = self._clock()
        seen = self._verified.get(auth)
        if seen is not None and now - seen < self._ttl:
            return True
        try:
            ok = self._http(self._url("ping", auth)).get("status") == "ok"
        except Exception:  # noqa: BLE001 - an unreachable music server means "not verified"
            return False
        if ok:
            self._verified[auth] = now
        return ok

    def forget(self, user: str) -> None:
        """Drops what was remembered about [user]'s login: a person who was just removed must be refused at once, not in five minutes."""
        who = user.strip().lower()
        for cache in (self._verified, self._admins):
            for key in [k for k in cache if k.user.lower() == who]:
                del cache[key]

    def is_admin(self, auth: Auth) -> bool:
        """Whether this (already verified) person is an administrator, asked of the music server as themselves."""
        now = self._clock()
        cached = self._admins.get(auth)
        if cached is not None and now - cached[1] < self._ttl:
            return cached[0]
        try:
            answer = self._http(self._url("getUser", auth, username=auth.user))
            admin = answer.get("status") == "ok" and bool((answer.get("user") or {}).get("adminRole"))
        except Exception:  # noqa: BLE001
            return False
        self._admins[auth] = (admin, now)
        return admin
