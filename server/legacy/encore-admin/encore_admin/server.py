"""The admin website: pages, and the JSON API behind them (docs/49).

Everything is owner-only: the owner signs in with the same name and password as in the app (the music server checks them, the
people service says whether this person may manage); a session cookie (random, memory only, HttpOnly, SameSite=Strict) follows.
State-changing calls need the header `X-Encore-Admin: 1` (a page of another site cannot add it). Nothing here is on the public
address: the stack's Funnel does not list this service.
"""
from __future__ import annotations

import http.cookies
import json
import logging
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from . import components, health
from .config import Config
from .docker_api import DockerError
from .sessions import Session, Sessions, Throttle
from .services import Services, token_login
from .signin import SigninWindows

log = logging.getLogger("encore_admin.server")

COOKIE = "encore_admin"
STATIC = Path(__file__).parent / "static"
#: The only files served as they are: name -> path below `static/`. Listed at start, so no path can reach anything else.
_FILES = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css",
          "/tokens.css": "tokens.css"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "Cache-Control": "no-store",
}


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)


def _json(status: int, payload: object, headers: dict[str, str] | None = None) -> Response:
    return Response(status, json.dumps(payload, separators=(",", ":")).encode("utf-8"), headers=headers or {})


def _error(status: int, code: str, message: str) -> Response:
    return _json(status, {"error": code, "message": message})


class Api:
    def __init__(self, config: Config, services: Services, signin: SigninWindows, *,
                 sessions: Sessions | None = None, throttle: Throttle | None = None,
                 stack: Callable[[], dict[str, str]] | None = None, details: Callable[[], dict[str, dict]] | None = None,
                 logs: Callable[[str], list[str]] | None = None, restart: Callable[[str], None] | None = None) -> None:
        self._stack = stack
        self._details = details
        self._logs = logs or (lambda name: [])
        self._restart = restart or (lambda name: None)
        self._config = config
        self._services = services
        self._signin = signin
        self._sessions = sessions or Sessions(config.session_hours)
        self._throttle = throttle or Throttle()
        self._fonts = {f"/fonts/{p.name}": p for p in (STATIC / "fonts").glob("*") if p.suffix in (".ttf", ".txt")}

    # ------------------------------------------------------------------ entry point

    def handle(self, method: str, raw_path: str, headers: Mapping[str, str], body: bytes, ip: str = "-") -> Response:
        path = raw_path.split("?", 1)[0].rstrip("/") or "/"
        if path.startswith("/admin/api/"):
            return self._api(method, path[len("/admin/api"):], headers, body, ip)
        if method not in ("GET", "HEAD"):
            return _error(405, "method_not_allowed", "That is not allowed here.")
        return self._static(path)

    # ------------------------------------------------------------------ pages

    def _static(self, path: str) -> Response:
        if path in self._fonts:
            file = self._fonts[path]
            kind = "font/ttf" if file.suffix == ".ttf" else "text/plain; charset=utf-8"
            return Response(200, file.read_bytes(), kind, {"Cache-Control": "public, max-age=86400"})
        name = _FILES.get(path)
        if name is None:
            return _error(404, "not_found", "There is nothing here.")
        file = STATIC / name
        kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript", "text/javascript"):
            kind += "; charset=utf-8"
        return Response(200, file.read_bytes(), kind)

    # ------------------------------------------------------------------ the API

    def _api(self, method: str, path: str, headers: Mapping[str, str], body: bytes, ip: str) -> Response:
        lowered = {k.lower(): v for k, v in headers.items()}
        if method != "GET" and lowered.get("x-encore-admin") != "1":
            return _error(403, "forbidden", "That request did not come from this website.")
        try:
            data = json.loads(body) if body else {}
        except ValueError:
            return _error(400, "bad_request", "That request could not be read.")
        if not isinstance(data, dict):
            return _error(400, "bad_request", "That request could not be read.")

        if path == "/login":
            return self._login(method, data, lowered, ip)
        session_key = self._cookie(lowered.get("cookie", ""))
        session = self._sessions.get(session_key)
        if path == "/logout":
            self._sessions.drop(session_key)
            return _json(200, {"ok": True}, {"Set-Cookie": self._cookie_header("", 0, lowered)})
        if session is None:
            return _error(401, "sign_in", "Sign in to continue.")
        if path == "/me" and method == "GET":
            return _json(200, {"user": session.user, "server": self._config.server_name})
        if path == "/today" and method == "GET":
            return self._today(session)
        if path == "/components" or path.startswith("/components/"):
            return self._components(method, path[len("/components"):])
        if path == "/recs" or path.startswith("/recs/"):
            return self._recs(method, path[len("/recs"):], data, session)
        if path == "/quality" or path.startswith("/quality/"):
            return self._quality(method, path[len("/quality"):], data, session)
        if path == "/youtube" or path.startswith("/youtube/"):
            return self._youtube(method, path[len("/youtube"):], data, session)
        if path == "/people" or path.startswith("/people/") or path.startswith("/invites") or path.startswith("/resets/"):
            return self._people(method, path, data, session)
        return _error(404, "not_found", "There is nothing here.")

    @staticmethod
    def _cookie(header: str) -> str | None:
        try:
            jar = http.cookies.SimpleCookie(header)
        except http.cookies.CookieError:
            return None
        return jar[COOKIE].value if COOKIE in jar else None

    def _cookie_header(self, value: str, max_age: int, lowered: Mapping[str, str]) -> str:
        secure = "; Secure" if lowered.get("x-forwarded-proto") == "https" else ""
        return f"{COOKIE}={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}{secure}"

    def _login(self, method: str, data: dict, lowered: Mapping[str, str], ip: str) -> Response:
        if method != "POST":
            return _error(405, "method_not_allowed", "That is not allowed here.")
        if not self._throttle.allowed(ip):
            return _error(429, "too_many_tries", "Too many wrong tries. Wait ten minutes and try again.")
        user, password = data.get("user"), data.get("password")
        if not isinstance(user, str) or not isinstance(password, str) or not 0 < len(user) <= 64 or not 0 < len(password) <= 256:
            return _error(400, "bad_request", "Type your name and password.")
        token, salt = token_login(password)
        user = user.strip()
        if not self._services.music_login_ok(user, token, salt):
            self._throttle.failed(ip)
            return _error(401, "wrong_login", "That name and password did not work.")
        if not self._services.is_owner(user, token, salt):
            return _error(403, "owner_only", "Only owners can manage this server.")
        self._throttle.succeeded(ip)
        key = self._sessions.create(user, token, salt)
        return _json(200, {"user": user, "server": self._config.server_name},
                     {"Set-Cookie": self._cookie_header(key, self._config.session_hours * 3600, lowered)})

    def proxy_target(self, path: str, headers: Mapping[str, str]) -> "tuple[str, int, str] | Response":
        """Where a request for the sign-in window goes, or the answer to give instead. Only the signed-in owner is let through."""
        lowered = {k.lower(): v for k, v in headers.items()}
        if self._sessions.get(self._cookie(lowered.get("cookie", ""))) is None:
            return _error(401, "sign_in", "Sign in to continue.")
        found = self._signin.target(path)
        if found is None:
            return _error(404, "gone", "That sign-in window is not open any more.")
        return found

    # ------------------------------------------------------------------ Today

    def _today(self, s: Session) -> Response:
        up = self._services.fetch_up()
        youtube = None
        needs: list[dict] = []
        if up:
            status, summary = self._services.fetch_call("GET", "", s.user, s.token, s.salt)
            if status == 200:
                youtube = summary
                for card in summary.get("accounts", []):
                    if card.get("state") == "needs_you":
                        needs.append({"text": f"{card.get('label', 'An account')}: {card.get('message', 'Sign in again.')}",
                                      "link": "#/youtube"})
        people = None
        status, listing = self._services.people_call("GET", "/api/people", s.user, s.token, s.salt)
        if status == 200:
            status_asks, asks = self._services.people_call("GET", "/api/resets", s.user, s.token, s.salt)
            requests = asks.get("requests", []) if status_asks == 200 else []
            for request in requests:
                needs.append({"text": f"{request.get('user', 'Somebody')} asked for a new password", "link": "#/people"})
            people = {"count": len(listing.get("people", [])), "asking": len(requests)}
        info = self._services.server_info()
        containers = None
        if self._stack is not None:
            try:
                containers = self._stack()
            except (DockerError, OSError):
                containers = None  # not knowing is not an alarm
        seen = (info or {}).get("parts", {})
        quality_up = self._services.quality_up()
        parts = health.judge(
            {"music": True, "people": info is not None, "fetch": up, "quality": quality_up,
             "hub": seen["hub"].get("up") if isinstance(seen.get("hub"), dict) else None, "remote": None,
             "recs": self._services.recs_up()},
            containers, {"music": seen["music"].get("version")} if isinstance(seen.get("music"), dict) else None)
        needs.extend({"text": sentence, "link": "#/today"} for sentence in map(health.trouble, parts) if sentence)
        quality = None
        if quality_up:
            status, summary = self._services.quality_call("GET", "", s.user, s.token, s.salt)
            if status == 200:
                quality = {"soulseek": (summary.get("settings") or {}).get("soulseek") is True, "counts": summary.get("counts") or {},
                           "today": summary.get("today") or {}}
                bits = summary.get("health") or {}
                slskd = bits.get("slskd") or {}
                if bits.get("problem"):
                    needs.append({"text": f"Best quality: {bits['problem']}", "link": "#/quality"})
                elif quality["soulseek"] and slskd.get("up") and not slskd.get("connected"):
                    needs.append({"text": "Best quality: Soulseek is switched on but not connected yet.", "link": "#/quality"})
                failed = quality["counts"].get("failed", 0)
                if failed:
                    needs.append({"text": f"Best quality: {failed} {'song' if failed == 1 else 'songs'} could not be finished.",
                                  "link": "#/quality"})
        return _json(200, {"songsServiceUp": up, "youtube": youtube, "needsYou": needs, "people": people, "parts": parts, "quality": quality,
                           "address": (info or {}).get("address") or "", "server": self._config.server_name})

    # ------------------------------------------------------------------ People

    _NAME = re.compile(r"[a-z][a-z0-9._-]{2,31}")  # how the people service names accounts

    @staticmethod
    def _relay(status: int, answer: dict) -> Response:
        if status == 0:
            return _error(502, "unreachable", "The people service did not answer. Try again in a moment.")
        if status == 204:
            return Response(204, b"")
        return _json(status, answer)

    def _people(self, method: str, path: str, data: dict, s: Session) -> Response:
        """The People page: everything is the people service's, asked as the signed-in owner (its own rules decide who may do what)."""
        parts = [p for p in path.split("/") if p]
        creds = (s.user, s.token, s.salt)
        ask = lambda m, p, body=None: self._services.people_call(m, p, *creds, body)  # noqa: E731
        if parts == ["people"]:
            if method == "POST":
                return self._relay(*ask("POST", "/api/people", {k: data[k] for k in ("name", "role") if k in data}))
            if method != "GET":
                return _error(405, "method_not_allowed", "That is not allowed here.")
            status, people = ask("GET", "/api/people")
            if status != 200:
                return self._relay(status, people)
            _, resets = ask("GET", "/api/resets")
            _, invites = ask("GET", "/api/invites")
            _, info = ask("GET", "/api/info")
            return _json(200, {"people": people.get("people", []), "library": people.get("library"), "requests": resets.get("requests", []),
                               "invites": [i for i in invites.get("invites", []) if i.get("state") == "open"],
                               "inviteLinks": bool(info.get("inviteLinks"))})
        if method != "POST":
            return _error(405, "method_not_allowed", "That is not allowed here.")
        if len(parts) == 3 and parts[0] == "people" and self._NAME.fullmatch(parts[1]):
            name, action = parts[1], parts[2]
            if action in ("password", "lock", "unlock"):
                body = {"mode": data["mode"]} if action == "password" and "mode" in data else None
                return self._relay(*ask("POST", f"/api/people/{name}/{action}", body))
            if action == "role":
                return self._relay(*ask("PUT", f"/api/people/{name}", {"role": data.get("role")}))
            if action == "remove":
                return self._relay(*ask("DELETE", f"/api/people/{name}"))
        if parts == ["invites"]:
            return self._relay(*ask("POST", "/api/invites", {"role": data["role"]} if "role" in data else {}))
        if len(parts) == 3 and parts[0] == "invites" and parts[1].isdigit() and parts[2] == "revoke":
            return self._relay(*ask("DELETE", f"/api/invites/{parts[1]}"))
        if len(parts) == 3 and parts[0] == "resets" and self._NAME.fullmatch(parts[1]) and parts[2] == "dismiss":
            return self._relay(*ask("DELETE", f"/api/resets/{parts[1]}"))
        return _error(404, "not_found", "There is nothing here.")

    # ------------------------------------------------------------------ Parts: what the server is made of

    def _components(self, method: str, path: str) -> Response:
        """The Parts page: how each part is doing, its recent messages, and a restart. Parts are added with the setup command, not here."""
        parts = [p for p in path.split("/") if p]
        if self._details is None:
            return _json(200, {"dockerOk": False, "parts": []})
        if parts == []:
            if method != "GET":
                return _error(405, "method_not_allowed", "That is not allowed here.")
            try:
                return _json(200, {"dockerOk": True, "parts": components.describe(self._details())})
            except (DockerError, OSError):
                return _json(200, {"dockerOk": False, "parts": []})
        if len(parts) == 2 and parts[0] in components.NAMES:
            container = parts[0]
            try:
                if parts[1] == "logs" and method == "GET":
                    return _json(200, {"lines": self._logs(container)})
                if parts[1] == "restart" and method == "POST":
                    if container in components.CANNOT_RESTART:
                        return _error(400, "cannot_restart", "This website cannot restart itself. Restart it from the machine it runs on.")
                    self._restart(container)
                    return Response(204, b"")
            except (DockerError, OSError) as error:
                log.warning("%s on %s: %s", parts[1], container, error)
                return _error(502, "docker", "That could not be done just now. Docker did not accept it.")
            return _error(405, "method_not_allowed", "That is not allowed here.")
        return _error(404, "not_found", "There is no such part.")

    # ------------------------------------------------------------------ Suggestions

    def _recs(self, method: str, path: str, data: dict, s: Session) -> Response:
        """The Suggestions page: on or off, when it last ran, how many people have lists. The service never tells the owner what a list holds."""
        parts = [p for p in path.split("/") if p]
        not_allowed = _error(405, "method_not_allowed", "That is not allowed here.")
        if not self._installed("encore-recs", self._services.recs_up):
            return _json(200, {"installed": False})
        ask = lambda m, p, body=None: self._relay_service("The suggestions service", self._services.recs_call(m, p, s.user, s.token, s.salt, body))  # noqa: E731
        if parts == []:
            return ask("GET", "") if method == "GET" else not_allowed
        if parts == ["settings"]:
            if method != "PUT":
                return not_allowed
            return ask("PUT", "/settings", {"enabled": data.get("enabled")})
        if parts == ["rebuild"]:
            return ask("POST", "/rebuild", {}) if method == "POST" else not_allowed
        return _error(404, "not_found", "There is nothing here.")

    def _installed(self, container: str, answers: "Callable[[], bool]") -> bool:
        """Whether a part is part of this server: its container exists (not answering is not the same as not installed)."""
        if self._stack is not None:
            try:
                return container in self._stack()
            except (DockerError, OSError):
                pass
        return answers()

    # ------------------------------------------------------------------ Best quality

    def _quality(self, method: str, path: str, data: dict, s: Session) -> Response:
        """The Music quality page: everything is the quality service's, asked as the signed-in owner (it checks who may manage)."""
        parts = [p for p in path.split("/") if p]
        not_allowed = _error(405, "method_not_allowed", "That is not allowed here.")
        if not self._installed("encore-quality", self._services.quality_up):
            return _json(200, {"installed": False})
        ask = lambda m, p, body=None: self._relay_service("The quality service", self._services.quality_call(m, p, s.user, s.token, s.salt, body))  # noqa: E731
        if parts == []:
            return ask("GET", "") if method == "GET" else not_allowed
        if parts == ["settings"]:
            if method != "PUT":
                return not_allowed
            return ask("PUT", "/settings", {k: data[k] for k in ("soulseek", "dailyCap", "minFreeGb") if k in data})
        if parts == ["selftest"]:
            return ask("POST", "/selftest", {}) if method == "POST" else not_allowed
        if len(parts) == 3 and parts[0] == "requests" and parts[1].isdigit() and parts[2] == "retry":
            return ask("POST", f"/requests/{parts[1]}/retry", {}) if method == "POST" else not_allowed
        return _error(404, "not_found", "There is nothing here.")

    @staticmethod
    def _relay_service(name: str, result: "tuple[int, dict]") -> Response:
        status, answer = result
        if status == 0:
            return _error(502, "unreachable", f"{name} did not answer. Try again in a moment.")
        if status == 204:
            return Response(204, b"")
        return _json(status, answer)

    # ------------------------------------------------------------------ YouTube

    def _youtube(self, method: str, path: str, data: dict, s: Session) -> Response:
        parts = [p for p in path.split("/") if p]
        creds = (s.user, s.token, s.salt)
        if not parts:
            return self._pass(method, "GET", "", None, creds) if method == "GET" else _error(405, "method_not_allowed", "That is not allowed here.")
        if parts[0] == "accounts":
            return self._pass(method, "POST", "/" + "/".join(parts), data, creds)
        if parts[0] != "signin":
            return _error(404, "not_found", "There is nothing here.")
        if len(parts) == 1:
            if method == "GET":
                current = self._signin.current()
                return _json(200, current or {"state": "gone"})
            if method == "POST":
                replace = data.get("replace")
                if replace is not None and (not isinstance(replace, str) or not re.fullmatch(r"[a-f0-9]{8}", replace)):
                    return _error(400, "bad_request", "That account is not known.")
                return _json(200, self._signin.start(replace))
            return _error(405, "method_not_allowed", "That is not allowed here.")
        window = parts[1]
        if not re.fullmatch(r"[a-f0-9]{8}", window):
            return _error(404, "not_found", "That sign-in window is not open any more.")
        if len(parts) == 2 and method == "GET":
            return _json(200, self._signin.status(window))
        if len(parts) == 3 and method == "POST" and parts[2] == "finish":
            label = data.get("label", "")
            if not isinstance(label, str):
                return _error(400, "bad_request", "The name must be text.")
            status, answer = self._signin.finish(window, label.strip()[:40], *creds)
            return _json(status, answer)
        if len(parts) == 3 and method == "POST" and parts[2] == "cancel":
            return _json(200, {"closed": self._signin.cancel(window)})
        return _error(405, "method_not_allowed", "That is not allowed here.")

    def _pass(self, method: str, want: str, path: str, body: dict | None, creds: tuple[str, str, str]) -> Response:
        if method != want:
            return _error(405, "method_not_allowed", "That is not allowed here.")
        status, answer = self._services.fetch_call(method, path, *creds, body if want == "POST" else None)
        if status == 0:
            return _error(502, "unreachable", "The songs service did not answer. Try again in a moment.")
        return _json(status, answer)
