"""The quality service's HTTP interface (docs/46 section 9, docs/49).

    GET    /api/info                              what this is (no login)
    GET    /api/quality/status                    may people ask for better quality on this server, and is it ready?
    GET    /api/quality/requests                  my requests, newest first
    POST   /api/quality/requests                  ask for the better copy of a song  {"songId": ...}  (or {"songIds": [...]})
    GET    /api/quality/requests/<id>             one of mine
    DELETE /api/quality/requests/<id>             stop looking
    GET    /api/quality/upgrades?after=<n>        which song ids became which (the phone moves its likes, playlist places, downloads)
    GET    /api/admin/quality                     the owner's view: parts, counts, trouble
    PUT    /api/admin/quality/settings            the owner's choices (Soulseek on or off, the daily limit, the free-space floor)
    POST   /api/admin/quality/selftest            ask every question out loud
    POST   /api/admin/quality/requests/<id>/retry look again now

A person is known by the music login they already have (the Subsonic token the app sends); no password reaches this service. The
`/quality` prefix of the public address is optional, as for the other services.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from . import delivery, store
from .config import Config
from .engine import Limits
from .maintenance import Maintenance
from .navidrome import Auth, Navidrome
from .store import Store, Want

log = logging.getLogger("encore_quality.server")

MAX_BODY = 64 * 1024
API_PER_MINUTE = 120
MAX_ACTIVE_PER_PERSON = 400
MAX_PER_REQUEST = 200
#: What a person is told, in plain words, for each state (the sentence a want carries in `detail` is more specific; this is the short name).
LABELS = {
    store.QUEUED: "Waiting", store.GETTING_READY: "Getting ready", store.SEARCHING: "Looking", store.DOWNLOADING: "Downloading",
    store.DELIVERING: "Putting it in place", store.READY: "Done", store.NOT_FOUND: "Not found yet", store.NO_MATCH: "No match",
    store.CANCELLED: "Stopped", store.FAILED: "Could not finish",
}


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


def _json(status: int, payload: object) -> Response:
    return Response(status, {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
                    json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _error(status: int, message: str) -> Response:
    return _json(status, {"error": message})


class _Limiter:
    def __init__(self, limit: int, clock: Callable[[], float]) -> None:
        self._limit, self._clock = limit, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True


def _http_json(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "encore-quality/1"}), timeout=8) as response:  # noqa: S310
            return response.status, json.loads(response.read(200_000) or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, {}
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return 0, {}


class Api:
    def __init__(self, *, config: Config, store: Store, navidrome: Navidrome, maintenance: Maintenance,
                 http_get: Callable[[str], "tuple[int, dict]"] = _http_json, clock: Callable[[], float] = time.time) -> None:
        self._config = config
        self._store = store
        self._nd = navidrome
        self._m = maintenance
        self._get = http_get
        self._clock = clock
        self._limit = _Limiter(API_PER_MINUTE, clock)
        self._last_selftest: dict | None = None

    # ------------------------------------------------------------------ settings the owner can change

    def limits(self) -> Limits:
        """The engine's limits: the configured ones, unless the owner changed them here (kept in the store)."""
        c = self._config
        try:
            cap = int(self._store.setting("daily_cap", "") or c.daily_cap)
            floor = float(self._store.setting("min_free_gb", "") or c.min_free_gb)
        except ValueError:
            cap, floor = c.daily_cap, c.min_free_gb
        return Limits(give_up_days=c.give_up_days, daily_cap=cap, min_free_gb=floor, duration_tolerance_s=c.duration_tolerance_s)

    # ------------------------------------------------------------------ entry

    def handle(self, method: str, target: str, headers: dict, body: bytes, ip: str = "-") -> Response:
        split = urllib.parse.urlsplit(target)
        path = split.path.rstrip("/") or "/"
        if path.startswith("/quality/"):
            path = path[len("/quality"):]
        query = {k: v[0] for k, v in urllib.parse.parse_qs(split.query).items()}
        if path == "/api/info":
            if method != "GET":
                return _error(405, "That is not allowed here.")
            return _json(200, {"service": "encore-quality", "version": 1, "features": ["quality-requests", "upgrade-map"]})
        if not path.startswith("/api/"):
            return _error(404, "There is nothing here.")
        auth = self._auth(query, {k.lower(): v for k, v in headers.items()})
        if auth is None:
            return _error(401, "Sign in again.")
        if not self._limit.allow(auth.user.lower()):
            return _error(429, "Slow down.")
        if len(body) > MAX_BODY:
            return _error(413, "That request is too big.")
        try:
            data = json.loads(body) if body else {}
        except ValueError:
            return _error(400, "That request could not be read.")
        if not isinstance(data, dict):
            return _error(400, "That request could not be read.")
        parts = [p for p in path.split("/") if p][1:]  # below /api
        if parts[:1] == ["quality"]:
            return self._person(method, parts[1:], query, data, auth)
        if parts[:2] == ["admin", "quality"]:
            return self._owner(method, parts[2:], data, auth)
        return _error(404, "There is nothing here.")

    def _auth(self, query: dict, lower: dict) -> Auth | None:
        user = query.get("u") or lower.get("x-encore-user")
        token = query.get("t") or lower.get("x-encore-token")
        salt = query.get("s") or lower.get("x-encore-salt")
        if not (user and token and salt) or max(len(user), len(token), len(salt)) > 100:
            return None
        auth = Auth(user, token, salt)
        return auth if self._nd.verify(auth) else None

    def _is_owner(self, auth: Auth) -> bool:
        """The people service's word first (it knows the roles), a music-server administrator when it does not answer."""
        if self._config.people_url:
            status, data = self._get(f"{self._config.people_url}/api/me?" + urllib.parse.urlencode(auth.params()))
            if status == 200:
                return data.get("canManage") is True
        return self._nd.is_admin(auth)

    # ------------------------------------------------------------------ a person's own requests

    def _person(self, method: str, parts: list[str], query: dict, data: dict, auth: Auth) -> Response:
        who = auth.user.lower()
        if parts == ["status"] and method == "GET":
            return _json(200, self._status())
        if parts == ["requests"]:
            if method == "GET":
                return _json(200, {"requests": [self._view(w) for w in self._store.of_person(who)]})
            if method == "POST":
                return self._create(who, auth, data)
            return _error(405, "That is not allowed here.")
        if parts == ["upgrades"] and method == "GET":
            try:
                after = max(0, int(query.get("after", "0")))
            except ValueError:
                return _error(400, "That number is not a number.")
            upgrades = self._store.upgrades_after(after)
            return _json(200, {"upgrades": upgrades, "last": upgrades[-1]["n"] if upgrades else after})
        if len(parts) == 2 and parts[0] == "requests" and parts[1].isdigit():
            want = self._store.get(int(parts[1]))
            if want is None or want.person != who:
                return _error(404, "There is no such request.")
            if method == "GET":
                return _json(200, self._view(want))
            if method == "DELETE":
                return self._cancel(want)
        return _error(404, "There is nothing here.")

    def _status(self) -> dict:
        health = self._m.health()
        on = self._m.soulseek_on()
        ready = on and self._m.wiring is not None and health["lidarr"]["up"] and health["slskd"]["connected"]
        if not on:
            message = "High quality is not switched on for this server."
        elif not ready:
            message = "High quality is starting up or not answering. Requests wait until it is."
        else:
            message = "Ready."
        return {"enabled": on, "ready": bool(ready), "message": message}

    def _view(self, want: Want) -> dict:
        return {"id": want.id, "songId": want.song_id, "title": want.title, "artist": want.artist, "album": want.album,
                "state": want.state, "label": LABELS.get(want.state, want.state), "message": want.detail,
                "newSongId": want.new_song_id or None, "createdAt": want.created, "updatedAt": want.updated}

    def _create(self, who: str, auth: Auth, data: dict) -> Response:
        ids = data.get("songIds") if "songIds" in data else [data.get("songId")]
        if not isinstance(ids, list) or not ids or len(ids) > MAX_PER_REQUEST or not all(isinstance(i, str) and 0 < len(i) <= 64 for i in ids):
            return _error(400, "Say which song (or up to 200 songs) you want in better quality.")
        active = len(self._store.in_state(*store.ACTIVE))
        mine = sum(1 for w in self._store.of_person(who) if w.state in store.ACTIVE)
        if mine + len(ids) > MAX_ACTIVE_PER_PERSON:
            return _error(429, "That is a lot of songs at once. Wait until some are done, then ask for more.")
        made: list[Want] = []
        for song_id in dict.fromkeys(ids):
            if self._nd.song_as(auth, song_id) is None:
                return _error(404, "One of those songs is not in your library.")
            file = self._nd.file_of(song_id)
            if file is None:
                return _error(503, "Encore cannot see where that song is kept yet. Ask the owner to check the server.")
            if any(part.startswith(".") for part in file.path.split("/")):
                return _error(400, "That song cannot be upgraded.")
            want, _ = self._store.add_want(person=who, song_id=song_id, artist=file.album_artist or file.artist, album=file.album,
                                           title=file.title, year=file.year, track=file.track, duration=file.duration, quick_path=file.path)
            made.append(want)
        views = [self._view(w) for w in made]
        log.info("%s asked for better quality on %d song(s); %d in progress", who, len(made), active)
        return _json(202, {"requests": views} if "songIds" in data else {"request": views[0]})

    def _cancel(self, want: Want) -> Response:
        if want.state not in store.ACTIVE and want.state != store.NOT_FOUND:
            return _error(409, "That request is already finished.")
        self._store.update(want.id, state=store.CANCELLED, detail="You stopped this.", next_try=None)
        return Response(204)

    # ------------------------------------------------------------------ the owner

    def _owner(self, method: str, parts: list[str], data: dict, auth: Auth) -> Response:
        if not self._is_owner(auth):
            return _error(403, "Only owners can manage this.")
        if parts == [] and method == "GET":
            return _json(200, self._summary())
        if parts == ["settings"] and method == "PUT":
            return self._settings(data)
        if parts == ["selftest"] and method == "POST":
            checks = self._m.selftest()
            self._last_selftest = {"at": self._clock(), "checks": checks, "ok": all(c["state"] != "problem" for c in checks)}
            return _json(200, self._last_selftest)
        if len(parts) == 3 and parts[0] == "requests" and parts[1].isdigit() and parts[2] == "retry" and method == "POST":
            want = self._store.get(int(parts[1]))
            if want is None:
                return _error(404, "There is no such request.")
            if want.state not in (store.NOT_FOUND, store.NO_MATCH, store.FAILED):
                return _error(409, "That request is still being worked on.")
            self._store.update(want.id, state=store.QUEUED, detail="Looking again.", next_try=None, attempts=0)
            return Response(204)
        return _error(404, "There is nothing here.")

    def _settings(self, data: dict) -> Response:
        if "soulseek" in data:
            if not isinstance(data["soulseek"], bool):
                return _error(400, "Soulseek is on or off.")
            self._m.set_soulseek(data["soulseek"])
        if "dailyCap" in data:
            cap = data["dailyCap"]
            if not isinstance(cap, int) or isinstance(cap, bool) or not 1 <= cap <= 500:
                return _error(400, "The daily limit is between 1 and 500 albums.")
            self._store.set_setting("daily_cap", str(cap))
        if "minFreeGb" in data:
            floor = data["minFreeGb"]
            if not isinstance(floor, (int, float)) or isinstance(floor, bool) or not 0 <= floor <= 5000:
                return _error(400, "The free-space floor is between 0 and 5000 GB.")
            self._store.set_setting("min_free_gb", str(floor))
        return _json(200, self._summary())

    def _summary(self) -> dict:
        limits = self.limits()
        started = int(self._store.setting(f"started:{time.strftime('%Y-%m-%d', time.gmtime(self._clock()))}", "0") or 0)
        trouble = [w for w in self._store.recent(200) if w.state in (store.FAILED, store.NO_MATCH, store.NOT_FOUND)][:20]
        return {
            "health": self._m.health(), "counts": self._store.counts(),
            "today": {"started": started, "limit": limits.daily_cap},
            "settings": {"soulseek": self._m.soulseek_on(), "dailyCap": limits.daily_cap, "minFreeGb": limits.min_free_gb},
            "freeGb": round(delivery.free_bytes(self._config.music_dir) / 1024 ** 3, 1) if self._config.music_dir.exists() else None,
            # What went wrong, by song and sentence; who asked is their own business.
            "trouble": [{"id": w.id, "title": w.title, "artist": w.artist, "state": w.state, "message": w.detail} for w in trouble],
            "lastSelfTest": self._last_selftest,
        }


# ---------------------------------------------------------------------- the real server
def serve(api: Api, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "encore-quality"
        sys_version = ""

        def _run(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(length, MAX_BODY + 1)) if length else b""
            ip = (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip() or self.client_address[0]
            try:
                response = api.handle(self.command, self.path, dict(self.headers), body, ip)
            except Exception:  # noqa: BLE001 - never a stack trace to the caller
                log.exception("unhandled error")
                response = _error(500, "Something went wrong.")
            self.send_response(response.status)
            for key, value in response.headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)

        do_GET = do_POST = do_PUT = do_DELETE = _run

        def log_message(self, fmt: str, *args: object) -> None:  # no access log: tokens travel in the query string
            pass

    return ThreadingHTTPServer((host, port), Handler)

