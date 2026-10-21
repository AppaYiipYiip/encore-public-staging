"""The HTTP surface of the people service (docs/35). `Api.handle` is a pure function of a request, so it is tested without sockets;
`serve` puts it behind the standard library's HTTP server.

Public (no login): the invitation page and its redeem, rate limited per address. Everything else needs the same Subsonic token the app
sends to the music server, checked with the music server itself; the administrator routes also need the music server to say "admin".
"""
from __future__ import annotations

import html
import json
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from .activity import Activity
from .invites import NOT_VALID, InviteError, Invites, ProvisionError, check_password, check_username
from .navidrome import Auth, Navidrome
from .parts import Parts
from .people import GUEST, INVITER, OWNER, ROLES, Directory, DirectoryUnavailable, Roles, normalize
from .phrase import temporary_password
from .standing import Standing

log = logging.getLogger("encore_people.server")

PREFIX = "/people"
MAX_BODY = 8 * 1024
JOIN_PER_MINUTE = 20  # per address: guessing codes must be slow, a friend needs a handful of tries at most
API_PER_MINUTE = 600  # per person
ASK_PER_MINUTE = 6  # "I forgot my password" per address: it is public, and every answer costs a look at the music server
#: What the person is told after "I forgot my password", whether or not the name is an account (nobody can learn who has one).
ASK_ANSWER = "If that is an account on this server, its owner has been told. Ask them for a link."


@dataclass(frozen=True)
class Settings:
    public_url: str  # what a friend types into the app, and the base of an invitation link
    server_name: str = "Encore"
    owners: frozenset[str] = frozenset()  # founding owners (lower case) besides the music server's administrators (ADR-092)


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


def _json(status: int, obj: object | None = None) -> Response:
    body = b"" if obj is None else json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return Response(status, {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}, body)


class _Limiter:
    """A sliding one-minute window per key."""

    def __init__(self, limit: int, clock: Callable[[], float]) -> None:
        self._limit = limit
        self._clock = clock
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
            if len(self._hits) > 5000:  # forget addresses that went quiet
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 60]:
                    self._hits.pop(k, None)
            return True


class Api:
    def __init__(self, *, invites: Invites, activity: Activity, navidrome: Navidrome, settings: Settings,
                 roles: Roles | None = None, directory: Directory | None = None, standing: Standing | None = None,
                 clock: Callable[[], float] = time.time, parts: Parts | None = None) -> None:
        self._parts = parts
        self._roles = roles or Roles()  # kept in memory when none is given (tests)
        self._directory = directory
        self._standing = standing or Standing(clock=clock)
        self._invites = invites
        self._activity = activity
        self._nd = navidrome
        self._settings = settings
        self._clock = clock
        self._join_limit = _Limiter(JOIN_PER_MINUTE, clock)
        self._api_limit = _Limiter(API_PER_MINUTE, clock)
        self._ask_limit = _Limiter(ASK_PER_MINUTE, clock)

    # ------------------------------------------------------------------ entry
    def handle(self, method: str, target: str, headers: dict, body: bytes, client_ip: str) -> Response:
        try:
            return self._handle(method, target, headers, body, client_ip)
        except DirectoryUnavailable:
            return _json(503, {"error": "The music server is busy or not answering just now. Try again in a moment."})

    def _handle(self, method: str, target: str, headers: dict, body: bytes, client_ip: str) -> Response:
        split = urlsplit(target)
        path = split.path
        if path == PREFIX or path.startswith(PREFIX + "/"):
            path = path[len(PREFIX):] or "/"  # whether the front door strips the prefix is not known until the real Funnel
        query = {k: v[0] for k, v in parse_qs(split.query).items()}
        if path.startswith("/join/"):
            return self._join(method, path[len("/join/"):].split("/"), body, client_ip)
        if path.startswith("/reset/"):
            return self._reset(method, path[len("/reset/"):].strip("/").split("/"), body, client_ip)
        if path.startswith("/api/"):
            return self._api(method, path[len("/api/"):].strip("/").split("/"), query, headers, body, client_ip)
        return _json(404, {"error": "not found"})

    # ------------------------------------------------------------------ the friend's side (public)
    def _join(self, method: str, parts: list[str], body: bytes, ip: str) -> Response:
        if not self._join_limit.allow(ip):
            return _json(429, {"error": "Too many tries. Wait a minute and try again."})
        code, rest = parts[0], parts[1:]
        if method == "GET" and not rest:
            info = self._invites.lookup(code)
            return self._landing(info.inviter) if info else self._landing_gone()
        if method == "GET" and rest == ["info"]:
            info = self._invites.lookup(code)
            if not info:
                return _json(404, {"valid": False})
            return _json(200, {"valid": True, "inviter": info.inviter, "server": self._settings.server_name,
                               "address": self._settings.public_url, "expiresAt": info.expires_at})
        if method == "POST" and rest == ["redeem"]:
            return self._redeem(code, body)
        return _json(404, {"error": "not found"}) if not (method in ("GET", "POST") and rest in ([], ["info"], ["redeem"])) \
            else _json(405, {"error": "method not allowed"})

    def _redeem(self, code: str, body: bytes) -> Response:
        if len(body) > MAX_BODY:
            return _json(413, {"error": "That is too much data."})
        try:
            data = json.loads(body or b"null")
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return _json(400, {"error": "Send a name and a password."})
        username, password = data.get("username"), data.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return _json(400, {"error": "Send a name and a password."})
        info = self._invites.lookup(code)
        try:
            who = self._invites.redeem(code, username, password)
        except InviteError as error:
            if str(error) == NOT_VALID:
                return _json(404, {"error": NOT_VALID})
            return _json(400, {"error": str(error)})
        if info is not None:
            self._roles.joined(who, info.role, info.inviter)  # their role, who invited them and when: the People list shows it
        return _json(201, {"username": who, "address": self._settings.public_url})

    # ------------------------------------------------------------------ signed-in routes
    def _auth(self, query: dict, headers: dict) -> Auth | None:
        lower = {k.lower(): v for k, v in headers.items()}
        user = query.get("u") or lower.get("x-encore-user")
        token = query.get("t") or lower.get("x-encore-token")
        salt = query.get("s") or lower.get("x-encore-salt")
        if not (user and token and salt) or len(user) > 100 or len(token) > 100 or len(salt) > 100:
            return None
        auth = Auth(user, token, salt)
        return auth if self._nd.verify(auth) else None

    def _api(self, method: str, parts: list[str], query: dict, headers: dict, body: bytes, ip: str = "-") -> Response:
        if parts == ["info"]:
            # Public on purpose: the app asks every address it knows this before it sends anybody's token anywhere.
            if method != "GET":
                return _json(405, {"error": "method not allowed"})
            return _json(200, {"service": "encore-people", "version": 1, "features": ["invites", "activity", "manage"],
                               "inviteLinks": bool(self._settings.public_url)})
        if parts == ["server"]:
            # Public on purpose, like `info`: one answer to "what can this server do?" so the app can hide what is missing.
            if method != "GET":
                return _json(405, {"error": "method not allowed"})
            return _json(200, self._server_answer())
        if parts == ["reset", "ask"]:
            # Public on purpose: a person who forgot their password cannot sign in to ask. Same answer for everybody.
            return self._ask(method, body, ip)
        auth = self._auth(query, headers)
        if auth is None:
            return _json(401, {"error": "Sign in again."})
        if not self._api_limit.allow(auth.user):
            return _json(429, {"error": "Slow down."})
        head = parts[0] if parts else ""
        if head == "me":
            if parts[1:] == ["password"]:
                return self._my_password(method, auth, body)
            if method != "GET":
                return _json(405, {"error": "method not allowed"})
            role = self._role(auth)
            return _json(200, {"user": auth.user, "admin": self._nd.is_admin(auth), "role": role,
                               "canInvite": role in (OWNER, INVITER), "canManage": role == OWNER,
                               "sharing": self._activity.is_sharing(auth.user),
                               "mustChangePassword": self._standing.flags(auth.user)[1]})
        if head == "invites":
            return self._invites_api(method, parts[1:], auth, body)
        if head == "people":
            return self._people_api(method, parts[1:], auth, body)
        if head == "resets":
            return self._resets_api(method, parts[1:], auth)
        if head == "activity":
            return self._activity_api(method, parts[1:], auth, body)
        return _json(404, {"error": "not found"})

    # ------------------------------------------------------------------ who may do what (ADR-092)
    def _role(self, auth: Auth) -> str:
        """Owner for the music server's administrators and the founding owners; else what an owner decided; else guest."""
        if self._nd.is_admin(auth) or normalize(auth.user) in self._settings.owners:
            return OWNER
        record = self._roles.get(auth.user)
        return record.role if record else GUEST

    def _founding(self, name: str, admin_names: set[str]) -> bool:
        return normalize(name) in self._settings.owners or normalize(name) in admin_names

    def _invites_api(self, method: str, rest: list[str], auth: Auth, body: bytes) -> Response:
        role = self._role(auth)
        if role not in (OWNER, INVITER):
            return _json(403, {"error": "You may not invite people on this server. Ask an owner."})
        mine_only = auth.user if role != OWNER else None  # a person who may invite sees and cancels only their own
        if not rest and method == "POST":
            data = self._small_json(body)
            wanted = data.get("role") if isinstance(data, dict) else None
            if wanted is not None and wanted not in (GUEST, INVITER):
                return _json(400, {"error": "An invitation makes a guest or someone who can invite."})
            # Only an owner may hand out the right to invite.
            made_role = wanted if (wanted == INVITER and role == OWNER) else GUEST
            if not self._settings.public_url:
                # An invitation is a link; without a public address nobody outside could open it. Say so instead of handing out a broken one.
                return _json(409, {"error": "Switch on remote access first: an invitation needs the server's public address."})
            made = self._invites.create(auth.user, made_role)
            url = f"{self._settings.public_url.rstrip('/')}{PREFIX}/join/{made.code}"
            return _json(201, {"id": made.id, "url": url, "expiresAt": made.expires_at, "role": made_role})
        if not rest and method == "GET":
            return _json(200, {"invites": [
                {"id": r.id, "inviter": r.inviter, "createdAt": r.created_at, "expiresAt": r.expires_at, "state": r.state,
                 "redeemedBy": r.redeemed_by, "redeemedAt": r.redeemed_at, "role": r.role}
                for r in self._invites.list(inviter=mine_only)]})
        if len(rest) == 1 and rest[0].isdigit() and method == "DELETE":
            done = self._invites.revoke(int(rest[0]), inviter=mine_only)
            return Response(204) if done else _json(404, {"error": "No such open invitation."})
        return _json(405, {"error": "method not allowed"})

    def _people_api(self, method: str, rest: list[str], auth: Auth, body: bytes) -> Response:
        if self._role(auth) != OWNER:
            return _json(403, {"error": "Only an owner can do that."})
        if self._directory is None:
            return _json(501, {"error": "This server cannot list its people."})
        accounts = self._directory.listing()
        admins = {normalize(a["name"]) for a in accounts if a.get("admin")}
        if not rest and method == "GET":
            stored = self._roles.all()
            flags = self._standing.all_flags()
            asks = self._standing.asks()
            people = []
            for account in accounts:
                name = normalize(account["name"])
                founding = self._founding(name, admins)
                record = stored.get(name)
                paused, must_change = flags.get(name, (False, False))
                people.append({
                    "user": account["name"],
                    "role": OWNER if founding else (record.role if record else GUEST),
                    "fixed": founding,
                    "invitedBy": record.invited_by if record else None,
                    "joinedAt": record.joined_at if record else None,
                    "createdAt": account.get("createdAt"),
                    "lastAccess": account.get("lastAccess"),
                    "paused": paused,
                    "mustChange": must_change,
                    "resetAsked": asks.get(name),
                })
            people.sort(key=lambda p: ({OWNER: 0, INVITER: 1, GUEST: 2}[p["role"]], p["user"].lower()))
            answer: dict = {"people": people}
            layout = getattr(self._directory, "layout", None)
            if callable(layout):
                try:
                    answer["library"] = layout()  # "shared": everybody has the one library; "private": each person has their own
                except Exception:  # noqa: BLE001 - the list is worth showing without it
                    pass
            return _json(200, answer)
        if not rest and method == "POST":
            return self._add_person(auth, body)
        if len(rest) not in (1, 2):
            return _json(404, {"error": "not found"})
        name = normalize(rest[0])
        if name not in {normalize(a["name"]) for a in accounts}:
            return _json(404, {"error": "There is nobody with that name on this server."})
        if len(rest) == 2:
            return self._person_action(method, name, rest[1], auth, body, admins)
        if method == "PUT":
            data = self._small_json(body)
            wanted = data.get("role") if isinstance(data, dict) else None
            if wanted not in ROLES:
                return _json(400, {"error": "Choose owner, can invite or guest."})
            if self._founding(name, admins):
                return _json(403, {"error": "A founding owner (an administrator of the music server, or named in the server's settings) "
                                            "cannot be changed here."})
            self._roles.set_role(name, wanted)
            return Response(204)
        if method == "DELETE":
            if name == normalize(auth.user):
                return _json(403, {"error": "You cannot remove yourself from your own server."})
            if self._founding(name, admins):
                return _json(403, {"error": "A founding owner cannot be removed here."})
            self._directory.remove_person(name)
            self._invites.revoke_all_from(name)  # what they had handed out stops working with them
            self._roles.forget(name)
            self._standing.forget(name)
            self._activity.clear(name)
            self._activity.set_sharing(name, False)
            self._nd.forget(name)  # their login must stop working now, not when the service next forgets it
            return Response(204)
        return _json(405, {"error": "method not allowed"})

    # ------------------------------------------------------------------ looking after people (docs/48)
    def _add_person(self, auth: Auth, body: bytes) -> Response:
        """The owner makes an account directly (no invitation, no public address needed): a name, and a temporary password to read out."""
        data = self._small_json(body)
        if not isinstance(data, dict):
            return _json(400, {"error": "Send a name."})
        name = data.get("name")
        name = name.strip().lower() if isinstance(name, str) else ""
        problem = check_username(name)
        if problem:
            return _json(400, {"error": problem})
        role = data.get("role", GUEST)
        if role not in (GUEST, INVITER):
            return _json(400, {"error": "A new person is a guest or someone who can invite."})
        password = temporary_password()
        try:
            self._directory.add_person(name, password)
        except ProvisionError as error:
            return _json(409, {"error": str(error)})
        self._roles.joined(name, role, auth.user)
        self._standing.set_flags(name, must_change=True)
        return _json(201, {"user": name, "temporaryPassword": password})

    def _person_action(self, method: str, name: str, action: str, auth: Auth, body: bytes, admins: set[str]) -> Response:
        if method != "POST" or action not in ("password", "lock", "unlock"):
            return _json(405 if action in ("password", "lock", "unlock") else 404, {"error": "method not allowed"})
        if name == normalize(auth.user):
            return _json(403, {"error": "Change your own password in your own settings."})
        if self._founding(name, admins):
            return _json(403, {"error": "A founding owner's password is changed in the music server itself."})
        if action == "lock":
            self._directory.set_password(name, secrets.token_urlsafe(24))  # nobody knows it: the account cannot be signed in to
            self._standing.set_flags(name, paused=True, must_change=False)
            self._invites.revoke_all_from(name)
            self._nd.forget(name)
            return Response(204)
        mode = "temporary"
        if action == "password":
            data = self._small_json(body)
            mode = data.get("mode") if isinstance(data, dict) else None
            if mode not in ("temporary", "link"):
                return _json(400, {"error": "Choose a temporary password or a one-time link."})
        if mode == "link":
            code, expires = self._standing.make_code(name)
            self._standing.dismiss(name)
            base = self._settings.public_url.rstrip("/")
            return _json(200, {"code": code, "url": f"{base}{PREFIX}/reset/{code}" if base else None, "expiresAt": expires})
        password = temporary_password()
        self._directory.set_password(name, password)
        self._standing.set_flags(name, paused=False, must_change=True)
        self._standing.dismiss(name)
        self._nd.forget(name)
        return _json(200, {"temporaryPassword": password})

    def _resets_api(self, method: str, rest: list[str], auth: Auth) -> Response:
        if self._role(auth) != OWNER:
            return _json(403, {"error": "Only an owner can do that."})
        if not rest and method == "GET":
            asks = sorted(self._standing.asks().items(), key=lambda kv: kv[1])
            return _json(200, {"requests": [{"user": name, "askedAt": at} for name, at in asks]})
        if len(rest) == 1 and method == "DELETE":
            self._standing.dismiss(rest[0])
            return Response(204)
        return _json(405, {"error": "method not allowed"})

    def _ask(self, method: str, body: bytes, ip: str) -> Response:
        if method != "POST":
            return _json(405, {"error": "method not allowed"})
        if not self._ask_limit.allow(ip):
            return _json(429, {"error": "Too many tries. Wait a minute and try again."})
        data = self._small_json(body)
        user = data.get("user") if isinstance(data, dict) else None
        if not isinstance(user, str) or not 1 <= len(user.strip()) <= 100:
            return _json(400, {"error": "Type your name."})
        name = normalize(user)
        if self._directory is not None:
            try:
                known = name in {normalize(a["name"]) for a in self._directory.listing()}
            except Exception:  # noqa: BLE001 - the music server not answering must not tell a stranger anything either
                known = False
            if known:
                self._standing.ask(name)
        return _json(202, {"ok": True, "message": ASK_ANSWER})

    def _my_password(self, method: str, auth: Auth, body: bytes) -> Response:
        if method != "POST":
            return _json(405, {"error": "method not allowed"})
        if self._directory is None:
            return _json(501, {"error": "This server cannot change passwords."})
        data = self._small_json(body)
        password = data.get("password") if isinstance(data, dict) else None
        problem = check_password(password)
        if problem:
            return _json(400, {"error": problem})
        self._directory.set_password(auth.user, password)
        self._standing.set_flags(auth.user, paused=False, must_change=False)
        self._nd.forget(auth.user)  # the old token is no good any more: the app signs in again with the new password
        return Response(204)

    #: The version of this contract (the shape of `/api/server`). It grows only when an old app would be broken by a change.
    API_VERSION = 1

    def _server_answer(self) -> dict:
        looked = self._parts.look() if self._parts is not None else {}
        features = {"invites", "activity"}
        if self._settings.public_url:
            features.add("invite-links")
        if self._directory is not None:
            features.update(("manage", "forgot-password"))
        for name, part in looked.items():
            if not part.get("up"):
                continue
            features.update(part.get("features", ()))
            if name == "music":
                features.add("music")
        return {"service": "encore", "apiVersion": self.API_VERSION, "name": self._settings.server_name,
                "address": self._settings.public_url, "features": sorted(features), "parts": looked}

    def _reset(self, method: str, parts: list[str], body: bytes, ip: str) -> Response:
        """The page a person opens from a one-time link, and what it calls."""
        if not self._join_limit.allow(ip):
            return _json(429, {"error": "Too many tries. Wait a minute and try again."})
        code, rest = parts[0], parts[1:]
        if method == "GET" and not rest:
            who = self._standing.peek(code)
            return self._reset_page(who) if who else self._landing_gone()
        if method == "GET" and rest == ["info"]:
            who = self._standing.peek(code)
            return _json(200, {"valid": True, "user": who, "server": self._settings.server_name}) if who else _json(404, {"valid": False})
        if method == "POST" and rest == ["redeem"]:
            data = self._small_json(body)
            password = data.get("password") if isinstance(data, dict) else None
            problem = check_password(password)
            if problem:
                return _json(400, {"error": problem})  # before the code is used up: a typo must not cost the link
            if self._directory is None:
                return _json(501, {"error": "This server cannot change passwords."})
            who = self._standing.redeem(code)
            if who is None:
                return _json(404, {"error": NOT_VALID})
            self._directory.set_password(who, password)
            self._standing.set_flags(who, paused=False, must_change=False)
            self._standing.dismiss(who)
            self._nd.forget(who)
            return _json(200, {"user": who, "address": self._settings.public_url})
        return _json(404, {"error": "not found"})

    def _activity_api(self, method: str, rest: list[str], auth: Auth, body: bytes) -> Response:
        if not rest:
            if method == "GET":
                return _json(200, {"friends": [
                    {"user": e.username, "title": e.title, "artist": e.artist, "album": e.album, "coverUrl": e.cover_url,
                     "state": e.state, "since": e.since} for e in self._activity.others(auth.user)]})
            if method == "PUT":
                self._activity.report(auth.user, self._small_json(body))  # ignored unless the person opted in: no answer either way
                return Response(204)
            if method == "DELETE":
                self._activity.clear(auth.user)
                return Response(204)
            return _json(405, {"error": "method not allowed"})
        if rest == ["sharing"] and method == "PUT":
            data = self._small_json(body)
            if not isinstance(data, dict) or not isinstance(data.get("on"), bool):
                return _json(400, {"error": "Send {\"on\": true} or {\"on\": false}."})
            self._activity.set_sharing(auth.user, data["on"])
            return Response(204)
        return _json(404, {"error": "not found"})

    @staticmethod
    def _small_json(body: bytes) -> object:
        if len(body) > MAX_BODY:
            return None
        try:
            return json.loads(body or b"null")
        except ValueError:
            return None

    # ------------------------------------------------------------------ the page a friend opens
    def _landing(self, inviter: str) -> Response:
        s = self._settings
        name, who, address = html.escape(s.server_name), html.escape(inviter), html.escape(s.public_url)
        # The server's name as a JavaScript string; "<" is escaped so a name can never close the script element.
        js_name = json.dumps(s.server_name).replace("<", "\\u003c")
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}: you are invited</title>
<style>
 body{{margin:0;background:#0d0f12;color:#f2f4f7;font:16px/1.5 system-ui,sans-serif}}
 main{{max-width:30rem;margin:0 auto;padding:2rem 1.25rem 4rem}}
 h1{{font-size:1.6rem;margin:.2rem 0 .4rem}} .sub{{color:#9aa3ad}}
 label{{display:block;margin:1rem 0 .25rem}} input{{width:100%;box-sizing:border-box;padding:.75rem;border-radius:.5rem;border:1px solid #2b323a;background:#161a1f;color:inherit;font:inherit}}
 button{{margin-top:1.25rem;width:100%;padding:.85rem;border:0;border-radius:999px;background:#1ed78a;color:#04130b;font:inherit;font-weight:700}}
 .card{{background:#161a1f;border-radius:.75rem;padding:1rem;margin-top:1.25rem}} code{{background:#0d0f12;padding:.1rem .35rem;border-radius:.3rem}}
 #err{{color:#ff8a80;min-height:1.5rem}} ol{{padding-left:1.2rem}} #copied{{overflow-wrap:anywhere}}
</style></head><body><main>
<h1>{who} invited you to {name}</h1>
<p class="sub">Your own music, from a server run by someone you know. Choose a name and a password to create your account.</p>
<form id="f"><label for="u">Your name (lower case letters and digits)</label><input id="u" autocomplete="username" autocapitalize="none" required>
<label for="p">A password (at least 8 characters)</label><input id="p" type="password" autocomplete="new-password" required>
<p id="err" role="alert"></p><button type="submit">Create my account</button></form>
<div class="card" id="done" hidden><p><b>Your account is ready.</b></p>
<ol><li>Install the <b>Encore</b> app (the person who invited you will send it).</li>
<li>Press <b>Copy setup link</b> below, open the app and tap <b>Got a setup link? Paste it</b>, then type your password.</li></ol>
<button id="copy" type="button">Copy setup link</button><p id="copied" class="sub" role="status"></p>
<p class="sub">Or type the server address <code>{address}</code>, your name and your password.</p></div>
<script>
const code=location.pathname.split('/').filter(Boolean).pop();
const NAME={js_name};
let setup='';
document.getElementById('f').addEventListener('submit',async e=>{{e.preventDefault();
 const err=document.getElementById('err');err.textContent='';
 const r=await fetch(location.pathname.replace(/\\/$/,'')+'/redeem',{{method:'POST',headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify({{username:document.getElementById('u').value.trim(),password:document.getElementById('p').value}})}});
 const d=await r.json().catch(()=>({{}}));
 if(r.status===201){{setup='encore://connect?server='+encodeURIComponent(d.address)+'&name='+encodeURIComponent(NAME)+'&user='+encodeURIComponent(d.username);document.getElementById('f').hidden=true;document.getElementById('done').hidden=false}}
 else err.textContent=d.error||'Something went wrong. Try again.';}});
document.getElementById('copy').addEventListener('click',async()=>{{const note=document.getElementById('copied');
 try{{await navigator.clipboard.writeText(setup);note.textContent='Copied. Open Encore and tap "Got a setup link? Paste it".'}}catch(_){{note.textContent=setup}}}});
</script></main></body></html>"""
        return Response(200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
                              "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}, page.encode("utf-8"))

    def _reset_page(self, user: str) -> Response:
        s = self._settings
        name, who = html.escape(s.server_name), html.escape(user)
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}: choose a new password</title>
<style>
 body{{margin:0;background:#0d0f12;color:#f2f4f7;font:16px/1.5 system-ui,sans-serif}}
 main{{max-width:30rem;margin:0 auto;padding:2rem 1.25rem 4rem}}
 h1{{font-size:1.6rem;margin:.2rem 0 .4rem}} .sub{{color:#9aa3ad}}
 label{{display:block;margin:1rem 0 .25rem}} input{{width:100%;box-sizing:border-box;padding:.75rem;border-radius:.5rem;border:1px solid #2b323a;background:#161a1f;color:#f2f4f7;font:inherit}}
 button{{margin-top:1.25rem;width:100%;padding:.85rem;border:0;border-radius:999px;background:#1ed78a;color:#04130b;font:inherit;font-weight:700}}
 #err{{color:#ff8a80;min-height:1.5rem}} .card{{background:#161a1f;border-radius:.75rem;padding:1rem;margin-top:1.25rem}}
</style></head><body><main>
<h1>Choose a new password</h1>
<p class="sub">For <b>{who}</b> on {name}.</p>
<form id="f"><label for="p">A new password (at least 8 characters)</label><input id="p" type="password" autocomplete="new-password" required>
<p id="err" role="alert"></p><button type="submit">Save my new password</button></form>
<div class="card" id="done" hidden><p><b>Your password is changed.</b></p><p class="sub">Open the Encore app and sign in with it.</p></div>
<script>
document.getElementById('f').addEventListener('submit',async e=>{{e.preventDefault();
 const err=document.getElementById('err');err.textContent='';
 const r=await fetch(location.pathname.replace(/\\/$/,'')+'/redeem',{{method:'POST',headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify({{password:document.getElementById('p').value}})}});
 const d=await r.json().catch(()=>({{}}));
 if(r.status===200){{document.getElementById('f').hidden=true;document.getElementById('done').hidden=false;}}
 else err.textContent=d.error||'Something went wrong. Try again.';}});
</script></main></body></html>"""
        return Response(200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
                              "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}, page.encode("utf-8"))

    def _landing_gone(self) -> Response:
        page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<body style='font:16px system-ui;background:#0d0f12;color:#f2f4f7;padding:2rem'>"
                f"<h1>This invitation is not valid any more</h1><p>{html.escape(NOT_VALID)}</p></body>")
        return Response(404, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}, page.encode("utf-8"))


# ---------------------------------------------------------------------- the real server
def serve(api: Api, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "encore-people"
        sys_version = ""

        def _run(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(length, MAX_BODY + 1)) if length else b""
            ip = (self.headers.get("X-Forwarded-For") or "").split(",")[-1].strip() or self.client_address[0]
            try:
                response = api.handle(self.command, self.path, dict(self.headers), body, ip)
            except Exception:  # noqa: BLE001 - never a stack trace to the caller
                log.exception("unhandled error")
                response = _json(500, {"error": "Something went wrong."})
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
