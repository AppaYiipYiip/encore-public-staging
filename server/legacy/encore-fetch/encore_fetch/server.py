"""The HTTP face: three routes, JSON in and out, the music server's own
token for authentication. Routing is a pure function ([Api.handle]) so it can
be tested without sockets.

    GET  /api/info            -> what this service is (no authentication)
    POST /api/prepare         -> look one song up ahead of a tap  (202 | 200)
    POST /api/playlist        -> the songs in a pasted playlist link (docs/39 F1, F9)
    POST /api/import          -> hand over a whole list; the server fetches it in the background (ADR-100)
    GET  /api/import[/<id>]   -> how far an import is        POST /api/import/<id>/cancel  -> stop it
    GET|PUT /api/profile/...  -> the person's own documents and events
                                 (docs/22 section 4)
    POST /api/play            -> start fetching one song          (202 | 200)
    GET  /api/play/<id>       -> where that job is
    GET  /api/play/<id>/audio -> the song itself (Range requests supported)
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Mapping

from . import __version__
from .imports import ImportQueue, RefusedImport
from .jobs import Job, JobManager, Limits, Request, MESSAGES
from . import cookies as youtube_login
from .accounts import PACES, Accounts
from .navidrome import Auth, Navidrome
from .playlists import Playlist, PlaylistError, Track
from .profile import Conflict, ProfileError, ProfileStore

_USER = re.compile(r"^[A-Za-z0-9._@+-]{1,64}$")
_TOKEN = re.compile(r"^[0-9a-fA-F]{32}$")
_SALT = re.compile(r"^[A-Za-z0-9]{4,64}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


class BadRequest(Exception):
    pass


@dataclass(frozen=True)
class FileBody:
    """A response that is a file, not JSON."""

    path: Path
    mime: str


@dataclass(frozen=True)
class LiveBody:
    """A song that is still arriving: sent as it is written, so a player
    starts after the first seconds instead of after the whole download."""

    job: Job


def iter_live(job: Job, *, sleep=time.sleep, chunk: int = 64 * 1024,
              idle_limit: float = 60.0, clock=time.monotonic):
    """Yields the bytes of the song as they appear. Ends when the download
    is over and everything was sent, or nothing has come for [idle_limit]."""
    offset = 0
    last_progress = clock()
    while True:
        path, more = job.stream_snapshot()
        data = b""
        if path is not None:
            try:
                size = path.stat().st_size
                if size > offset:
                    with path.open("rb") as f:
                        f.seek(offset)
                        data = f.read(min(chunk, size - offset))
            except OSError:
                data = b""  # renamed between the stat and the open: retry
        if data:
            offset += len(data)
            last_progress = clock()
            yield data
            continue
        if not more or job.state == "failed":
            return
        if clock() - last_progress > idle_limit:
            return
        sleep(0.1)


MIME = {".opus": "audio/ogg", ".ogg": "audio/ogg", ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg", ".flac": "audio/flac", ".wav": "audio/wav",
        ".aac": "audio/aac"}


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """`bytes=a-b` / `bytes=a-` / `bytes=-n` -> inclusive (start, end), or
    `None` for no (or an unusable) range. Only a single range is supported."""
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    spec = header[6:].strip()
    start_s, _, end_s = spec.partition("-")
    try:
        if start_s == "":
            n = int(end_s)
            if n <= 0:
                return None
            return max(0, size - n), size - 1
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size or end < start:
        return None
    return start, min(end, size - 1)


def _text(body: Mapping[str, object], key: str, *, required: bool,
          limit: int = 200) -> str | None:
    value = body.get(key)
    if value is None or value == "":
        if required:
            raise BadRequest(f"{key} is required")
        return None
    if not isinstance(value, str):
        raise BadRequest(f"{key} must be text")
    value = value.strip()
    if not value or len(value) > limit or _CTRL.search(value):
        raise BadRequest(f"{key} is not valid")
    return value


def _int(body: Mapping[str, object], key: str, lo: int, hi: int) -> int | None:
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BadRequest(f"{key} must be a number")
    n = int(value)
    if n < lo or n > hi:
        raise BadRequest(f"{key} is out of range")
    return n


_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def _track_json(track: Track) -> dict:
    out: dict = {"title": track.title, "artist": track.artist, "artists": list(track.artists)}
    if track.album:
        out["album"] = track.album
    if track.duration_s:
        out["durationSec"] = track.duration_s
    if track.video_id:
        out["videoId"] = track.video_id
    if track.official:
        out["official"] = True
    return out


def _video_id(body: Mapping[str, object]) -> str | None:
    value = _text(body, "videoId", required=False, limit=11)
    if value is not None and not _VIDEO_ID.fullmatch(value):
        raise BadRequest("videoId is not valid")
    return value


def parse_request(body: Mapping[str, object]) -> Request:
    return Request(
        artist=_text(body, "artist", required=True) or "",
        title=_text(body, "title", required=True) or "",
        album=_text(body, "album", required=False),
        track=_int(body, "trackNumber", 1, 999),
        disc=_int(body, "discNumber", 1, 99),
        disc_total=_int(body, "discTotal", 1, 99),
        year=_int(body, "year", 1900, 2100),
        duration_s=_int(body, "durationSec", 5, 7200),
        cover_url=_text(body, "coverUrl", required=False, limit=500),
        bulk=_text(body, "priority", required=False, limit=10) == "bulk",
        video_id=_video_id(body),
        # A song tapped in an imported playlist: the app knows which official upload it came from.
        video_first=body.get("official") is True and _video_id(body) is not None,
    )


def auth_from(query: Mapping[str, str], headers: Mapping[str, str]) -> Auth | None:
    lower = {k.lower(): v for k, v in headers.items()}
    user = query.get("u") or lower.get("x-encore-user") or ""
    token = query.get("t") or lower.get("x-encore-token") or ""
    salt = query.get("s") or lower.get("x-encore-salt") or ""
    if not (_USER.match(user) and _TOKEN.match(token) and _SALT.match(salt)):
        return None
    return Auth(user, token.lower(), salt)


def _too_much(limit: Limits) -> tuple[int, dict]:
    """429 for a person who asks for too much. "Too many at once" passes in seconds (the app waits and asks again by
    itself); the day's limit does not, and saying "try again in a minute" for it would send the app round in circles."""
    key = "daily_limit" if str(limit) == "daily" else "rate_limited"
    return 429, {"error": key, "message": MESSAGES[key]}


class Api:
    def __init__(self, manager: JobManager, navidrome: Navidrome,
                 profile: ProfileStore | None = None,
                 playlist_reader: Callable[[str], Playlist] | None = None,
                 playlist_limit: int = 20,
                 clock: Callable[[], float] = time.monotonic,
                 imports: ImportQueue | None = None,
                 owner_check: Callable[[Auth], bool] | None = None,
                 accounts: Accounts | None = None,
                 account_tester: Callable[[Path], dict] | None = None,
                 visitor_per_hour: int = 200) -> None:
        self._manager = manager
        self._nd = navidrome
        self._profile = profile
        self._read_playlist = playlist_reader
        self._playlist_limit = playlist_limit
        self._clock = clock
        self._playlist_calls: dict[str, list[float]] = {}
        self._imports = imports
        self._owner_check = owner_check
        self._accounts = accounts
        self._account_tester = account_tester
        self._visitor_per_hour = visitor_per_hour

    #: Reading a playlist is cheap for us and not free for the services we ask: a few a minute, not a loop.
    _PLAYLIST_WINDOW_S = 600

    def _playlist(self, method: str, query: Mapping[str, str], headers: Mapping[str, str],
                  body: bytes) -> tuple[int, dict]:
        if method != "POST":
            return 405, {"error": "method not allowed"}
        auth = auth_from(query, headers)
        if auth is None or not self._nd.verify(auth):
            return 401, {"error": "sign in with your music login"}
        if self._read_playlist is None:
            return 501, {"error": "unsupported", "message": "This server cannot read playlist links."}
        try:
            data = json.loads(body or b"{}")
            if not isinstance(data, dict):
                raise BadRequest("an object is expected")
            url = _text(data, "url", required=True, limit=500)
        except (ValueError, BadRequest) as error:
            return 400, {"error": str(error) or "bad request"}
        now = self._clock()
        who = auth.user.strip().lower()
        recent = [t for t in self._playlist_calls.get(who, []) if now - t < self._PLAYLIST_WINDOW_S]
        if len(recent) >= self._playlist_limit:
            self._playlist_calls[who] = recent
            return 429, {"error": "rate_limited",
                         "message": "That is a lot of playlists in a short time. Try again in a few minutes."}
        self._playlist_calls[who] = [*recent, now]
        try:
            playlist = self._read_playlist(url or "")
        except PlaylistError as error:
            status = {"unsupported": 400, "not_found": 404, "unreadable": 422, "empty": 422}.get(error.code, 502)
            return status, {"error": error.code, "message": error.message}
        return 200, {
            "name": playlist.name, "source": playlist.source, "kind": playlist.kind,
            "count": len(playlist.tracks), "truncated": playlist.truncated,
            "tracks": [_track_json(t) for t in playlist.tracks],
        }

    def _admin_route(self, method: str, path: str, query: Mapping[str, str], headers: Mapping[str, str],
                     body: bytes) -> tuple[int, dict]:
        """The owner's controls: the YouTube accounts (docs/50). All owner-only.

        `GET /api/admin/youtube` the accounts, what each did, what the server is allowed an hour;
        `POST /api/admin/youtube/accounts {"label", "cookies"}` add an account from a cookies file (the Advanced way);
        `POST /api/admin/youtube/accounts/<id> {"label"?, "pace"?}` rename, change the pace;
        `POST /api/admin/youtube/accounts/<id>/signout` sign out;
        `POST /api/admin/youtube/accounts/<id>/login {"cookies"}` the account's sign-in again (the admin's sign-in window made a new one);
        `POST /api/admin/youtube/accounts/<id>/test` does YouTube accept it, and can the server fetch as it."""
        if self._owner_check is None or self._accounts is None:
            return 501, {"error": "unsupported", "message": "This server has no owner controls."}
        auth = auth_from(query, headers)
        if auth is None or not self._nd.verify(auth):
            return 401, {"error": "sign in with your music login"}
        if not self._owner_check(auth):
            return 403, {"error": "owner_only", "message": "Only the owner of this server can do that."}
        parts = path.split("/")[4:] if path.startswith("/api/admin/youtube") else None
        if parts is None:
            return 404, {"error": "not found"}
        accounts = self._accounts

        def summary() -> tuple[int, dict]:
            out = accounts.summary()
            out["visitorPerHour"] = self._visitor_per_hour
            out["paces"] = dict(PACES)
            return 200, out

        def json_body() -> dict:
            data = json.loads(body or b"{}")
            if not isinstance(data, dict):
                raise BadRequest("the request must be an object")
            return data

        def text_field(data: dict, key: str, default: str = "") -> str:
            value = data.get(key, default)
            if not isinstance(value, str):
                raise BadRequest(f"{key} must be text")
            return value

        try:
            if not parts or parts == [""]:
                return summary() if method == "GET" else (405, {"error": "method not allowed"})
            if parts == ["accounts"]:
                if method != "POST":
                    return 405, {"error": "method not allowed"}
                data = json_body()
                if not isinstance(data.get("cookies"), str):
                    raise BadRequest("the cookies are missing")
                accounts.add(text_field(data, "label", "YouTube account") or "YouTube account", data["cookies"])
                return summary()
            if parts[0] == "accounts" and len(parts) in (2, 3):
                account_id = parts[1]
                if not accounts.has(account_id):
                    return 404, {"error": "not_found", "message": "There is no such account."}
                if len(parts) == 3 and parts[2] == "login":
                    if method != "POST":
                        return 405, {"error": "method not allowed"}
                    data = json_body()
                    if not isinstance(data.get("cookies"), str):
                        raise BadRequest("the cookies are missing")
                    accounts.replace_login(account_id, data["cookies"])
                    return summary()
                if len(parts) == 3 and parts[2] == "test":
                    if method != "POST":
                        return 405, {"error": "method not allowed"}
                    if self._account_tester is None:
                        return 501, {"error": "unsupported", "message": "This server cannot check accounts."}
                    return 200, self._account_tester(accounts.path_of(account_id))
                if len(parts) == 2:
                    if method != "POST":
                        return 405, {"error": "method not allowed"}
                    data = json_body()
                    if "label" in data:
                        accounts.rename(account_id, text_field(data, "label"))
                    if "pace" in data:
                        accounts.set_pace(account_id, text_field(data, "pace"))
                    return summary()
                if parts[2] == "signout":
                    if method != "POST":
                        return 405, {"error": "method not allowed"}
                    accounts.sign_out(account_id)
                    return summary()
                return 404, {"error": "not found"}
        except youtube_login.CookieProblem as problem:
            return 422, {"error": "unusable", "message": problem.message}
        except (ValueError, BadRequest) as error:
            return 400, {"error": "bad_request", "message": str(error) or "bad request"}
        return 404, {"error": "not found"}

    def _import_route(self, method: str, path: str, query: Mapping[str, str], headers: Mapping[str, str],
                      body: bytes) -> tuple[int, dict]:
        queue = self._imports
        if queue is None:
            return 501, {"error": "unsupported", "message": "This server cannot import playlists."}
        auth = auth_from(query, headers)
        if auth is None or not self._nd.verify(auth):
            return 401, {"error": "sign in with your music login"}
        # Every call from the person's app tells the queue their login is here (it is kept in memory only, ADR-101).
        queue.touch(auth)
        who = auth.user
        found = re.fullmatch(r"/api/import(?:/([0-9a-f]{12})(/cancel|/skip)?)?", path)
        if not found:
            return 404, {"error": "not found"}
        import_id, cancel = found.group(1), found.group(2)
        if import_id is None:
            if method == "GET":
                return 200, {"imports": [queue.view(i, full=False) for i in queue.list(who)]}
            if method != "POST":
                return 405, {"error": "method not allowed"}
            try:
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    raise BadRequest("an object is expected")
                imp = queue.create(
                    auth, name=data.get("name") if isinstance(data.get("name"), str) else "",
                    kind=data.get("kind") if isinstance(data.get("kind"), str) else "playlist",
                    source=data.get("source") if isinstance(data.get("source"), str) else "",
                    tracks=data.get("tracks"))
            except (ValueError, BadRequest) as error:
                return 400, {"error": "bad_request", "message": str(error) or "bad request"}
            except RefusedImport as refused:
                return refused.status, {"error": refused.code, "message": refused.message}
            return 202, queue.view(imp)
        if cancel == "/skip":
            if method != "POST":
                return 405, {"error": "method not allowed"}
            try:
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    raise BadRequest("an object is expected")
                imp = queue.skip(who, import_id, data.get("indexes"))
            except (ValueError, BadRequest) as error:
                return 400, {"error": "bad_request", "message": str(error) or "bad request"}
            except RefusedImport as refused:
                return refused.status, {"error": refused.code, "message": refused.message}
        elif cancel:
            if method != "POST":
                return 405, {"error": "method not allowed"}
            imp = queue.cancel(who, import_id)
        elif method == "GET":
            imp = queue.get(who, import_id)
        else:
            return 405, {"error": "method not allowed"}
        if imp is None:
            return 404, {"error": "not_found", "message": "No such import."}
        return 200, queue.view(imp, songs=query.get("songs") == "1")

    def _profile_route(
        self, method: str, path: str, query: Mapping[str, str],
        headers: Mapping[str, str], body: bytes,
    ) -> tuple[int, dict]:
        if self._profile is None:
            return 404, {"error": "not found"}
        auth = auth_from(query, headers)
        if auth is None or not self._nd.verify(auth):
            return 401, {"error": "sign in with your music login"}
        user = auth.user
        try:
            if path == "/api/profile":
                if method != "GET":
                    return 405, {"error": "method not allowed"}
                return 200, self._profile.list(user)

            doc = re.fullmatch(r"/api/profile/doc/([a-z][a-z0-9_-]{0,31})", path)
            if doc:
                name = doc.group(1)
                if method == "GET":
                    found = self._profile.get_doc(user, name)
                    if found is None:
                        return 404, {"error": "no such document"}
                    return 200, found
                if method == "PUT":
                    sent = json.loads(body or b"{}")
                    base = sent.get("baseV", 0) if isinstance(sent, dict) else None
                    if (not isinstance(sent, dict)
                            or not isinstance(sent.get("data"), dict)
                            or isinstance(base, bool)
                            or not isinstance(base, int) or base < 0):
                        return 400, {"error": "expected {baseV, data}"}
                    try:
                        return 200, self._profile.put_doc(
                            user, name, base, sent["data"])
                    except Conflict as stale:
                        return 409, {"error": "conflict", "v": stale.version,
                                     "data": stale.data}
                return 405, {"error": "method not allowed"}

            if path == "/api/profile/events":
                if method == "POST":
                    sent = json.loads(body or b"{}")
                    if not isinstance(sent, dict):
                        return 400, {"error": "an object is expected"}
                    return 200, self._profile.add_events(
                        user, sent.get("events"))
                if method == "GET":
                    return 200, self._profile.read_events(
                        user, int(query.get("since") or 0),
                        int(query.get("limit") or 2000))
                return 405, {"error": "method not allowed"}
        except ProfileError as error:
            return error.status, {"error": str(error)}
        except ValueError:
            return 400, {"error": "bad request"}
        return 404, {"error": "not found"}

    def handle(
        self,
        method: str,
        raw_path: str,
        headers: Mapping[str, str],
        body: bytes = b"",
    ) -> tuple[int, dict | FileBody | LiveBody]:
        url = urllib.parse.urlparse(raw_path)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        path = url.path.rstrip("/") or "/"

        if path == "/api/info":
            if method != "GET":
                return 405, {"error": "method not allowed"}
            return 200, {
                "service": "encore-fetch", "version": 1,
                "build": __version__,
                "features": ["play-now", "prepare"]
                + (["playlist"] if self._read_playlist is not None else [])
                + (["import"] if self._imports is not None else [])
                + (["youtube-login"] if self._owner_check is not None and self._accounts is not None else [])
                + (["profile"] if self._profile is not None else []),
                "formats": ["opus", "m4a"],
                # Whether the server fetches as a signed-in YouTube account (faster, age-restricted songs): a friend's app
                # says so when an import is slow. Nothing about which account, nothing secret.
                "youtubeSignedIn": bool(self._accounts is not None and self._accounts.capacity() is not None),
            }

        if path == "/api/profile" or path.startswith("/api/profile/"):
            return self._profile_route(method, path, query, headers, body)

        if path == "/api/playlist":
            return self._playlist(method, query, headers, body)

        if path == "/api/import" or path.startswith("/api/import/"):
            return self._import_route(method, path, query, headers, body)

        if path.startswith("/api/admin/"):
            return self._admin_route(method, path, query, headers, body)

        if path == "/api/prepare":
            if method != "POST":
                return 405, {"error": "method not allowed"}
            auth = auth_from(query, headers)
            if auth is None or not self._nd.verify(auth):
                return 401, {"error": "sign in with your music login"}
            try:
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    raise BadRequest("an object is expected")
                request = parse_request(data)
            except (ValueError, BadRequest) as error:
                return 400, {"error": str(error) or "bad request"}
            try:
                job = self._manager.prepare(auth, request)
            except Limits as limit:
                return _too_much(limit)
            return (200 if job.state == "ready" else 202), job.view()

        match = re.fullmatch(
            r"/api/play(?:/([0-9a-f]{16})(/audio)?)?", path)
        if not match:
            return 404, {"error": "not found"}

        auth = auth_from(query, headers)
        if auth is None or not self._nd.verify(auth):
            return 401, {"error": "sign in with your music login"}

        job_id, audio = match.group(1), match.group(2)
        if method == "GET" and job_id and audio:
            job = self._manager.get(job_id)
            if job is None or job.state == "failed":
                return 404, {"error": "no such song"}
            if job.downloading or (job.stem is not None and job.stream_snapshot()[1]):
                return 200, LiveBody(job)
            path, _ = job.stream_snapshot()
            if path is None:
                return 404, {"error": "no such song"}
            return 200, FileBody(path, MIME.get(
                path.suffix.lower().replace(".part", ""),
                "application/octet-stream"))
        if method == "GET" and job_id:
            job = self._manager.get(job_id)
            if job is None:
                return 404, {"error": "no such job"}
            return 200, job.view()

        if method == "POST" and job_id is None:
            try:
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    raise BadRequest("an object is expected")
                request = parse_request(data)
            except (ValueError, BadRequest) as error:
                return 400, {"error": str(error) or "bad request"}
            try:
                job = self._manager.submit(auth, request)
            except Limits as limit:
                return _too_much(limit)
            return (200 if job.state == "ready" else 202), job.view()

        return 405, {"error": "method not allowed"}


def make_handler(api: Api, max_body: int = 8192):
    class Handler(BaseHTTPRequestHandler):
        server_version = "encore-fetch"

        def log_message(self, *args: object) -> None:  # no access log:
            pass                                       # tokens are in URLs

        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _send_file(self, body: FileBody) -> None:
            size = body.path.stat().st_size
            rng = parse_range(self.headers.get("Range"), size)
            start, end = rng if rng else (0, size - 1)
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", body.mime)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                with body.path.open("rb") as f:
                    f.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        chunk = f.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (ConnectionResetError, BrokenPipeError):
                # A player stops reading when it has what it wants (or the
                # phone left the network): not an error.
                self.close_connection = True

        def _send_live(self, body: LiveBody) -> None:
            path, _ = body.job.stream_snapshot()
            suffix = path.suffix.lower() if path else ".webm"
            if suffix == ".part":
                suffix = Path(path.stem).suffix.lower()
            mime = {".webm": "audio/webm", ".m4a": "audio/mp4",
                    ".mp4": "audio/mp4"}.get(suffix, MIME.get(
                        suffix, "application/octet-stream"))
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            if self.command == "HEAD":
                return
            try:
                for piece in iter_live(body.job):
                    self.wfile.write(piece)
            except (ConnectionResetError, BrokenPipeError):
                pass

        def _handle(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            # A document may be a few hundred KB; a play request never is.
            limit = (320 * 1024 if self.path.startswith("/api/profile")
                     else 2 * 1024 * 1024 if self.path.startswith("/api/import")
                     else 512 * 1024 if self.path.startswith("/api/admin")
                     else max_body)
            if length > limit:
                self.close_connection = True
                self._send(413, {"error": "too large"})
                return
            body = self.rfile.read(length) if length else b""
            status, payload = api.handle(
                method, self.path, dict(self.headers.items()), body)
            if isinstance(payload, LiveBody):
                self._send_live(payload)
            elif isinstance(payload, FileBody):
                self._send_file(payload)
            else:
                self._send(status, payload)

        def do_GET(self) -> None:  # noqa: N802
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

        def do_PUT(self) -> None:  # noqa: N802
            self._handle("PUT")

        def do_HEAD(self) -> None:  # noqa: N802
            self._handle("GET")

    return Handler


def serve(api: Api, host: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(api))
    httpd.daemon_threads = True
    return httpd
