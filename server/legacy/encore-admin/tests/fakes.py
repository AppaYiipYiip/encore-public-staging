"""Fakes of the three services and of Docker, so the website is tested as an owner would use it."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
import time
import urllib.parse
from pathlib import Path

from encore_admin.signin import COOKIE_FILE

IN_A_YEAR = int(time.time()) + 365 * 86400


def firefox_cookies(rows, *, in_log: bool = True) -> dict[str, bytes]:
    """The files of a Firefox cookie store as bytes, keyed by their path in the browser's container. `rows` are
    `(host, name, expiry, http_only)`. With [in_log] the cookies are only in the write-ahead log (as while Firefox runs)."""
    with tempfile.TemporaryDirectory() as tmp:
        database = Path(tmp) / "cookies.sqlite"
        connection = sqlite3.connect(str(database))
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, name TEXT, value TEXT, host TEXT, path TEXT, "
                           "expiry INTEGER, isSecure INTEGER, isHttpOnly INTEGER)")
        connection.commit()
        if not in_log:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for host, name, expiry, http_only in rows:
            connection.execute("INSERT INTO moz_cookies (name, value, host, path, expiry, isSecure, isHttpOnly) VALUES (?, 'v', ?, '/', ?, 1, ?)",
                               (name, host, expiry, http_only))
        connection.commit()
        files = {COOKIE_FILE: database.read_bytes()}
        for suffix in ("-wal", "-shm"):
            part = Path(str(database) + suffix)
            if part.is_file() and part.stat().st_size:
                files[COOKIE_FILE + suffix] = part.read_bytes()
        connection.close()
    return files


#: What a Firefox that is signed in to YouTube holds, and one that has only reached Google, and one that has nothing yet.
SIGNED_IN = [(".youtube.com", "__Secure-3PSID", IN_A_YEAR, 1), (".youtube.com", "VISITOR_INFO1_LIVE", IN_A_YEAR, 0),
             (".google.com", "SID", IN_A_YEAR, 1)]
GOOGLE_ONLY = [(".google.com", "SID", IN_A_YEAR, 1), (".google.com", "NID", IN_A_YEAR, 0)]
NOTHING_YET = [(".google.com", "NID", IN_A_YEAR, 0)]


class Stack:
    """Navidrome, the people service and the fetch service, answering the way the real ones do."""

    ND = "http://nd"
    PEOPLE = "http://people"
    FETCH = "http://fetch"
    QUALITY = "http://quality"
    RECS = "http://recs"

    def __init__(self):
        self.passwords = {"dana": "correct horse", "sam": "guest pw"}
        self.owners = {"dana"}
        self.fetch_up = True
        #: what GET /api/admin/youtube answers, and what the owner's calls to it were
        self.summary = {"accounts": [], "signedIn": False, "perHour": None}
        self.calls: list[tuple[str, str, dict, dict | None]] = []
        self.finish_status = 200
        self.fetch_status_override: int | None = None
        #: called when a sign-in is handed to the songs service (to see what had happened by then)
        self.on_import = None
        #: the people service: what it was asked (method, path, query, body) and what it answers for a (method, path), 200 {} otherwise
        self.people_calls: list[tuple[str, str, dict, dict | None]] = []
        self.people_replies: dict[tuple[str, str], tuple[int, dict]] = {}
        self.people_up = True
        #: the quality service: whether it answers, what its owner summary says, what the owner's calls to it were and what it answers
        #: for a (method, path) (200 with the summary otherwise)
        self.quality_up = True
        self.quality_summary = {
            "health": {"lidarr": {"up": True, "version": "3.1.0.4875"}, "slskd": {"up": True, "version": "0.26.1.0", "connected": False},
                       "soulseek": "off", "wired": True, "problem": ""},
            "counts": {}, "today": {"started": 0, "limit": 40}, "settings": {"soulseek": False, "dailyCap": 40, "minFreeGb": 5.0},
            "freeGb": 40.0, "trouble": [], "lastSelfTest": None}
        self.quality_calls: list[tuple[str, str, dict, dict | None]] = []
        self.quality_replies: dict[tuple[str, str], tuple[int, dict]] = {}
        #: the suggestions service: the same four things
        self.recs_up = True
        self.recs_summary = {"enabled": True, "lastRun": {"at": 1_760_000_000, "people": 3, "built": 2, "empty": 1, "throttled": False, "unreadable": False},
                             "peopleWithLists": 2, "rebuilding": False, "surfaces": {}, "sentence": "Each person's suggestions are made from that person's own plays."}
        self.recs_calls: list[tuple[str, str, dict, dict | None]] = []
        self.recs_replies: dict[tuple[str, str], tuple[int, dict]] = {}
        #: what the people service says about the whole server (GET /api/server): the parts it can see and their features
        self.server_parts = {"music": {"up": True, "version": "0.64.2"}, "fetch": {"up": True, "features": ["play-now", "import"], "youtubeSignedIn": False},
                             "hub": {"up": True, "features": ["jam"]}}

    def http(self, method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
        parsed = urllib.parse.urlparse(url)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        base = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path
        if base == self.ND:
            return self._navidrome(path, query)
        if base == self.PEOPLE:
            return self._people(method, path, query, body)
        if base == self.FETCH:
            return self._fetch(method, path, query, body)
        if base == self.QUALITY:
            return self._quality(method, path, query, body)
        if base == self.RECS:
            return self._recs(method, path, query, body)
        return 0, {}

    def _valid(self, query: dict) -> bool:
        password = self.passwords.get(query.get("u", ""))
        return password is not None and hashlib.md5((password + query.get("s", "")).encode()).hexdigest() == query.get("t")

    def _navidrome(self, path: str, query: dict) -> tuple[int, dict]:
        if path == "/rest/ping.view":
            return 200, {"subsonic-response": {"status": "ok" if self._valid(query) else "failed"}}
        if path == "/rest/getUser.view":
            return 200, {"subsonic-response": {"status": "ok", "user": {"adminRole": query.get("u") in self.owners}}}
        return 404, {}

    def _people(self, method: str, path: str, query: dict, body: dict | None) -> tuple[int, dict]:
        if path == "/api/me":
            return 200, {"canManage": query.get("u") in self.owners}
        if not self.people_up:
            return 0, {}
        if path == "/api/info":
            return self.people_replies.get((method, path), (200, {"service": "encore-people", "inviteLinks": True}))
        if path == "/api/server":
            return 200, {"service": "encore", "apiVersion": 1, "name": "Home music", "address": "https://music.example.ts.net",
                         "features": ["music"], "parts": self.server_parts}
        if not self._valid(query):
            return 401, {"error": "Sign in again."}
        self.people_calls.append((method, path, dict(query), body))
        return self.people_replies.get((method, path), (200, {}))

    def _recs(self, method: str, path: str, query: dict, body: dict | None) -> tuple[int, dict]:
        if not self.recs_up:
            return 0, {}
        if path == "/api/info":
            return 200, {"service": "encore-recs", "version": 1}
        if not path.startswith("/api/admin/recs"):
            return 404, {}
        if not self._valid(query):
            return 401, {"error": "Sign in again."}
        if query.get("u") not in self.owners:
            return 403, {"error": "Only owners can manage this."}
        rest = path[len("/api/admin/recs"):]
        self.recs_calls.append((method, rest, dict(query), body))
        return self.recs_replies.get((method, rest), (200, self.recs_summary))

    def _quality(self, method: str, path: str, query: dict, body: dict | None) -> tuple[int, dict]:
        if not self.quality_up:
            return 0, {}
        if path == "/api/info":
            return 200, {"service": "encore-quality", "version": 1}
        if not path.startswith("/api/admin/quality"):
            return 404, {}
        if not self._valid(query):
            return 401, {"error": "Sign in again."}
        if query.get("u") not in self.owners:
            return 403, {"error": "Only owners can manage this."}
        rest = path[len("/api/admin/quality"):]
        self.quality_calls.append((method, rest, dict(query), body))
        return self.quality_replies.get((method, rest), (200, self.quality_summary))

    def _fetch(self, method: str, path: str, query: dict, body: dict | None) -> tuple[int, dict]:
        if path == "/api/info":
            return (200, {"service": "encore-fetch"}) if self.fetch_up else (0, {})
        if not path.startswith("/api/admin/youtube"):
            return 404, {}
        if not self.fetch_up:
            return 0, {}
        if not self._valid(query):
            return 401, {"error": "sign in with your music login"}
        rest = path[len("/api/admin/youtube"):]
        self.calls.append((method, rest, dict(query), body))
        if self.fetch_status_override:
            return self.fetch_status_override, {"error": "unusable", "message": "That is not a cookies.txt file."}
        if method == "POST" and (rest == "/accounts" or rest.endswith("/login")):
            if self.on_import:
                self.on_import()
            return self.finish_status, self.summary
        return 200, self.summary


def _tar(name: str, data: bytes) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        info = tarfile.TarInfo(name.rsplit("/", 1)[-1])
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


class FakeDocker:
    """Docker's socket: records every call and answers like the real daemon."""

    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []
        self.image_present = True
        self.running = True
        self.create_status = 201
        self.leftover: list[str] = []
        self.pull_error: str | None = None
        #: the files inside the browser's container: path -> bytes (what `docker cp` would give)
        self.files: dict[str, bytes] = {}
        #: what each container has said (the messages), and what Docker answers to a restart
        self.log_text: dict[str, str] = {}
        self.restart_status = 204
        #: the stack's containers as `docker ps -a` shows them: name -> (state, status text); None = Docker cannot be reached
        self.stack_containers: dict[str, tuple[str, str]] | None = {
            "navidrome": ("running", "Up 3 hours (healthy)"), "encore-people": ("running", "Up 3 hours"),
            "encore-fetch": ("running", "Up 3 hours"), "encore-hub": ("running", "Up 3 hours"), "encore-quality": ("running", "Up 3 hours"),
            "encore-recs": ("running", "Up 3 hours"),
            "encore-tailscale": ("running", "Up 3 hours (healthy)"), "encore-admin": ("running", "Up 3 hours")}

    def __call__(self, method: str, path: str, body: object = None) -> tuple[int, bytes]:
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("/containers/json") and "filters=" not in path:
            if self.stack_containers is None:
                return 500, b"{}"
            return 200, json.dumps([{"Names": ["/" + n], "State": st, "Status": text, "Image": f"example/{n}:1.0"}
                                    for n, (st, text) in self.stack_containers.items()]).encode()
        if method == "POST" and path.startswith("/containers/") and "/restart" in path:
            return self.restart_status, b"{}"
        if method == "GET" and path.startswith("/containers/") and "/logs" in path:
            import struct
            name = path.split("/")[2]
            body = self.log_text.get(name, "").encode()
            return 200, (bytes([1, 0, 0, 0]) + struct.pack(">I", len(body)) + body) if body else b""
        if method == "GET" and path.startswith("/containers/json"):
            return 200, json.dumps([{"Names": ["/" + name]} for name in self.leftover]).encode()
        if method == "GET" and "/archive?path=" in path:
            wanted = urllib.parse.unquote(path.split("path=", 1)[1])
            if wanted in self.files:
                return 200, _tar(wanted, self.files[wanted])
            return 404, b"{}"
        if method == "GET" and path.startswith("/images/"):
            return (200 if self.image_present else 404), b"{}"
        if method == "POST" and path.startswith("/images/create"):
            if self.pull_error:
                return 200, json.dumps({"error": self.pull_error}).encode() + b"\n"
            self.image_present = True
            return 200, b'{"status":"Pulling fs layer"}\n{"status":"Download complete"}\n'
        if method == "POST" and path.startswith("/containers/create"):
            return self.create_status, b'{"Id":"abc"}' if self.create_status == 201 else b'{"message":"no"}'
        if method == "POST" and path.endswith("/start"):
            return 204, b""
        if method == "GET" and path.startswith("/containers/") and path.endswith("/json"):
            return 200, json.dumps({"State": {"Running": self.running}}).encode()
        return 204, b""

    def verbs(self) -> list[str]:
        return [f"{m} {p.split('?')[0]}" for m, p, _ in self.calls]
