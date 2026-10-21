"""What the service needs from the music server: who is asking (the Subsonic token the app already sends, so no password reaches this
service), what file a song really is (only the server's administrator may see paths), a rescan, and which song a file became.

Two kinds of login are involved and must not be confused: a **person's** token proves that person can see the song they ask about; the
**administrator's** login (given to the service by the person who installed it, like the people service) reads paths and asks for scans.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

#: `(method, url, json body or None, headers) -> (status, parsed JSON or None)`; status 0: not reachable. The tests give a fake.
Transport = Callable[[str, str, "dict | None", "dict | None"], "tuple[int, Any]"]


@dataclass(frozen=True)
class Auth:
    """Subsonic token authentication: `t = md5(password + salt)`."""

    user: str
    token: str
    salt: str

    def params(self) -> dict[str, str]:
        return {"u": self.user, "t": self.token, "s": self.salt}


def urllib_transport(method: str, url: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": "encore-quality/1", **({"Content-Type": "application/json"} if data is not None else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - the music server, by configuration
            raw, status = response.read(4_000_000), response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(200_000), error.code
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, None
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


@dataclass(frozen=True)
class SongFile:
    """What the administrator's view of a song says: where it is and what it is called."""

    id: str
    path: str              # relative to the music folder
    library_path: str      # the music folder as the music server sees it
    title: str
    artist: str
    album: str
    album_artist: str
    year: int | None
    track: int | None
    duration: float | None
    suffix: str
    bit_rate: int | None
    release_group: str     # MusicBrainz release group id when the file's tags carry one, else ''


class Navidrome:
    def __init__(self, base_url: str, *, admin_user: str | None = None, admin_password: str | None = None,
                 transport: Transport = urllib_transport, clock: Callable[[], float] = time.monotonic, verify_ttl: float = 300.0) -> None:
        self._base = base_url.rstrip("/")
        self._admin = (admin_user, admin_password)
        self._call = transport
        self._clock = clock
        self._ttl = verify_ttl
        self._verified: dict[Auth, float] = {}
        self._admins: dict[Auth, tuple[bool, float]] = {}
        self._jwt: tuple[str, float] | None = None

    # ------------------------------------------------------------------ a person's token

    def _subsonic(self, method: str, auth: Auth, **params: object) -> dict | None:
        query = {**auth.params(), "v": "1.16.1", "c": "encore-quality", "f": "json", **{k: str(v) for k, v in params.items()}}
        status, data = self._call("GET", f"{self._base}/rest/{method}.view?{urllib.parse.urlencode(query)}", None, None)
        response = (data or {}).get("subsonic-response") if isinstance(data, dict) else None
        return response if status == 200 and isinstance(response, dict) and response.get("status") == "ok" else None

    def verify(self, auth: Auth) -> bool:
        now = self._clock()
        seen = self._verified.get(auth)
        if seen is not None and now - seen < self._ttl:
            return True
        ok = self._subsonic("ping", auth) is not None
        if ok:
            self._verified[auth] = now
        return ok

    def forget(self, user: str) -> None:
        who = user.strip().lower()
        for cache in (self._verified, self._admins):
            for key in [k for k in cache if k.user.lower() == who]:
                del cache[key]

    def is_admin(self, auth: Auth) -> bool:
        now = self._clock()
        cached = self._admins.get(auth)
        if cached is not None and now - cached[1] < self._ttl:
            return cached[0]
        response = self._subsonic("getUser", auth, username=auth.user)
        admin = bool(((response or {}).get("user") or {}).get("adminRole"))
        if response is not None:
            self._admins[auth] = (admin, now)
        return admin

    def song_as(self, auth: Auth, song_id: str) -> dict | None:
        """The song as this person sees it; `None` when they cannot (it does not exist, or is not in a library they may read)."""
        response = self._subsonic("getSong", auth, id=song_id)
        song = (response or {}).get("song")
        return song if isinstance(song, dict) and str(song.get("id")) == song_id else None

    # ------------------------------------------------------------------ the administrator's login

    def _admin_token(self, fresh: bool = False) -> str | None:
        user, password = self._admin
        if not (user and password):
            return None
        if not fresh and self._jwt is not None and self._clock() - self._jwt[1] < 2400:
            return self._jwt[0]
        status, data = self._call("POST", f"{self._base}/auth/login", {"username": user, "password": password}, None)
        token = (data or {}).get("token") if status == 200 and isinstance(data, dict) else None
        self._jwt = (str(token), self._clock()) if token else None
        return self._jwt[0] if self._jwt else None

    def admin_ok(self) -> bool:
        """Whether the administrator login this service was given is accepted (without it, paths cannot be read)."""
        return self._admin_token() is not None

    def _native(self, path: str) -> Any:
        """GET on the music server's own API as the administrator; one fresh sign-in when the old one was refused."""
        for fresh in (False, True):
            token = self._admin_token(fresh)
            if token is None:
                return None
            status, data = self._call("GET", f"{self._base}/api/{path}", None, {"X-ND-Authorization": f"Bearer {token}"})
            if status == 200:
                return data
            if status not in (401, 403):
                return None
        return None

    @staticmethod
    def _file(record: Any) -> SongFile | None:
        if not isinstance(record, dict) or not record.get("id") or not record.get("path"):
            return None

        def number(key: str) -> int | None:
            value = record.get(key)
            return int(value) if isinstance(value, (int, float)) and value > 0 else None

        duration = record.get("duration")
        return SongFile(
            id=str(record["id"]), path=str(record["path"]).replace("\\", "/"), library_path=str(record.get("libraryPath") or ""),
            title=str(record.get("title") or ""), artist=str(record.get("artist") or ""), album=str(record.get("album") or ""),
            album_artist=str(record.get("albumArtist") or ""), year=number("year"), track=number("trackNumber"),
            duration=float(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
            suffix=str(record.get("suffix") or str(record["path"]).rsplit(".", 1)[-1]).lower(),
            bit_rate=number("bitRate"), release_group=str(record.get("mbzReleaseGroupId") or ""))

    def file_of(self, song_id: str) -> SongFile | None:
        return self._file(self._native(f"song/{urllib.parse.quote(song_id, safe='')}"))

    def find_by_path(self, relative_path: str) -> SongFile | None:
        """The song the music server made of the file at [relative_path] (after a scan), or `None`."""
        found = self._native("song?_start=0&_end=3&" + urllib.parse.urlencode({"path": relative_path}))
        for record in found if isinstance(found, list) else []:
            song = self._file(record)
            if song is not None and song.path == relative_path.replace("\\", "/") and not record.get("missing"):
                return song
        return None

    # ------------------------------------------------------------------ rescans

    def _admin_auth(self) -> Auth | None:
        user, password = self._admin
        if not (user and password):
            return None
        import hashlib
        import secrets
        salt = secrets.token_hex(6)
        return Auth(user, hashlib.md5((password + salt).encode("utf-8")).hexdigest(), salt)  # noqa: S324 - Subsonic's token scheme

    def start_scan(self) -> bool:
        auth = self._admin_auth()
        return auth is not None and self._subsonic("startScan", auth) is not None

    def scanning(self) -> bool:
        auth = self._admin_auth()
        response = self._subsonic("getScanStatus", auth) if auth else None
        return bool(((response or {}).get("scanStatus") or {}).get("scanning"))
