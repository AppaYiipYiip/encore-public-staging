"""The recommendations service's HTTP interface (docs/47, docs/45c item 4): the phone asks for its person's lists and only draws them.

    GET    /api/info                       what this is (no login)
    GET    /api/recs/home                  my rows: Made for you, Because you play ..., Deeper cuts, New from artists you love
    GET    /api/recs/pool                  my suggestion pool for smart shuffle (about a hundred songs, each with its reason)
    POST   /api/recs/hide                  "not for me"  {"artist": ..., "title": ...optional}
    GET    /api/recs/hidden                what I said no to
    DELETE /api/recs/hidden/<id>           undo one
    POST   /api/recs/feedback              how a suggestion did  {"surface": "made-for-you", "event": "shown|played|starred"}
    GET    /api/admin/recs                 the owner's view: on or off, last run, how many people have lists. Never what anybody's list holds.
    PUT    /api/admin/recs/settings        {"enabled": true|false}
    POST   /api/admin/recs/rebuild         make everybody's lists again now

A person is known by the music login they already have (the Subsonic token the app sends); no password reaches this service. The owner's
view has no list, no reason and no seed of any person (docs/47 section 0, rule 3). The `/recs` prefix of the public address is optional.
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

from .builder import Builder
from .navidrome import Auth, Navidrome
from .store import EVENTS, SURFACES, Store
from .textnorm import norm_artist, norm_title

log = logging.getLogger("encore_recs.server")

MAX_BODY = 8 * 1024
API_PER_MINUTE = 120
EMPTY_SENTENCE = "Play a few songs and Encore will start suggesting more of what you like."
WAITING_SENTENCE = "Your first lists are being made. Come back in a few minutes."
OFF_SENTENCE = "Suggestions are switched off on this server."


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
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "encore-recs/1"}), timeout=8) as response:  # noqa: S310
            return response.status, json.loads(response.read(200_000) or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, {}
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return 0, {}


class Api:
    def __init__(self, *, store: Store, navidrome: Navidrome, builder: Builder, people_url: str = "",
                 http_get: Callable[[str], "tuple[int, dict]"] = _http_json, clock: Callable[[], float] = time.time,
                 run_in_background: Callable[[Callable[[], None]], None] | None = None) -> None:
        self._store = store
        self._nd = navidrome
        self._builder = builder
        self._people_url = people_url.rstrip("/")
        self._get = http_get
        self._clock = clock
        self._limit = _Limiter(API_PER_MINUTE, clock)
        self._background = run_in_background or (lambda work: threading.Thread(target=work, daemon=True, name="rebuild").start())
        self._rebuilding = False

    # ------------------------------------------------------------------ entry

    def handle(self, method: str, target: str, headers: dict, body: bytes, ip: str = "-") -> Response:
        split = urllib.parse.urlsplit(target)
        path = split.path.rstrip("/") or "/"
        if path.startswith("/recs/"):
            path = path[len("/recs"):]
        query = {k: v[0] for k, v in urllib.parse.parse_qs(split.query).items()}
        if path == "/api/info":
            if method != "GET":
                return _error(405, "That is not allowed here.")
            return _json(200, {"service": "encore-recs", "version": 1, "features": ["recs-home", "recs-pool", "recs-hide"]})
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
        parts = [p for p in path.split("/") if p][1:]
        if parts[:1] == ["recs"]:
            return self._person(method, parts[1:], data, auth.user.lower())
        if parts[:2] == ["admin", "recs"]:
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
        if self._people_url:
            status, data = self._get(f"{self._people_url}/api/me?" + urllib.parse.urlencode(auth.params()))
            if status == 200:
                return data.get("canManage") is True
        return self._nd.is_admin(auth)

    # ------------------------------------------------------------------ a person's own lists

    def _person(self, method: str, parts: list[str], data: dict, who: str) -> Response:
        if parts == ["home"] and method == "GET":
            return _json(200, self._home(who))
        if parts == ["pool"] and method == "GET":
            built = self._store.build_of(who)
            songs = self._visible(built["pool"], who) if built and self._builder.enabled() else []
            return _json(200, {"songs": songs, "builtAt": built["builtAt"] if built else None})
        if parts == ["hide"] and method == "POST":
            artist, title = data.get("artist"), data.get("title")
            if not isinstance(artist, str) or not 0 < len(artist.strip()) <= 200 or (title is not None and (not isinstance(title, str) or len(title) > 200)):
                return _error(400, "Say which artist (and which song) is not for you.")
            return _json(201, {"id": self._store.hide(who, artist.strip(), title.strip() if isinstance(title, str) and title.strip() else None)})
        if parts == ["hidden"] and method == "GET":
            return _json(200, {"hidden": self._store.hidden_list(who)})
        if len(parts) == 2 and parts[0] == "hidden" and parts[1].isdigit() and method == "DELETE":
            return Response(204) if self._store.unhide(who, int(parts[1])) else _error(404, "There is no such entry.")
        if parts == ["feedback"] and method == "POST":
            surface, event = str(data.get("surface", "")).split(":")[0], data.get("event")
            if surface not in SURFACES or event not in EVENTS:
                return _error(400, "That is not a surface or an event.")
            self._store.count(surface, event)
            return Response(204)
        if parts in (["home"], ["pool"], ["hide"], ["hidden"], ["feedback"]):
            return _error(405, "That is not allowed here.")
        return _error(404, "There is nothing here.")

    def _home(self, who: str) -> dict:
        if not self._builder.enabled():
            return {"state": "off", "message": OFF_SENTENCE, "rows": [], "builtAt": None}
        built = self._store.build_of(who)
        if built is None:
            return {"state": "waiting", "message": WAITING_SENTENCE, "rows": [], "builtAt": None}
        if built["state"] != "ready":
            return {"state": "empty", "message": EMPTY_SENTENCE, "rows": [], "builtAt": built["builtAt"]}
        rows = []
        for row in built["rows"]:
            items = self._visible(row["items"], who) if row["kind"] == "songs" else self._visible_artists(row["items"], who)
            if items:
                rows.append({**row, "items": items})
        return {"state": "ready", "message": "", "rows": rows, "builtAt": built["builtAt"]}

    def _visible(self, songs: list[dict], who: str) -> list[dict]:
        """What is left after what the person has said no to since the lists were made (a hidden song disappears at once, not tomorrow)."""
        hidden = self._store.hidden_for(who)
        return [s for s in songs if not hidden.blocks(str(s.get("artist", "")), str(s.get("title", "")))]

    def _visible_artists(self, items: list[dict], who: str) -> list[dict]:
        hidden = self._store.hidden_for(who)
        out = []
        for item in items:
            if hidden.blocks(str(item.get("artist", ""))):
                continue
            top = item.get("topSong")
            if isinstance(top, dict) and hidden.blocks(str(top.get("artist", "")), str(top.get("title", ""))):
                item = {**item, "topSong": None}
            out.append(item)
        return out

    # ------------------------------------------------------------------ the owner: switch and counts, nothing about anybody

    def _owner(self, method: str, parts: list[str], data: dict, auth: Auth) -> Response:
        if not self._is_owner(auth):
            return _error(403, "Only owners can manage this.")
        if parts == [] and method == "GET":
            return _json(200, self._summary())
        if parts == ["settings"] and method == "PUT":
            if not isinstance(data.get("enabled"), bool):
                return _error(400, "Suggestions are on or off.")
            self._store.set_setting("recs", "on" if data["enabled"] else "off")
            return _json(200, self._summary())
        if parts == ["rebuild"] and method == "POST":
            if self._rebuilding:
                return _json(202, {"running": True})
            self._rebuilding = True

            def work() -> None:
                try:
                    self._builder.run(everyone=True, force=True)
                finally:
                    self._rebuilding = False

            self._background(work)
            return _json(202, {"running": True})
        return _error(404, "There is nothing here.")

    def _summary(self) -> dict:
        last = self._builder.last_run()
        return {"enabled": self._builder.enabled(), "lastRun": last, "peopleWithLists": self._store.built_count(), "rebuilding": self._rebuilding,
                "surfaces": self._store.totals(),
                "sentence": "Each person's suggestions are made from that person's own plays and likes, and shown only to them. Only artist and song "
                            "names go to the public music catalogues (MusicBrainz, ListenBrainz, Deezer); nothing about anyone does."}


# ---------------------------------------------------------------------- the real server
def serve(api: Api, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "encore-recs"
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
