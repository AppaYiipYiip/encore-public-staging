"""Looks at the admin website with fake services, so its pages can be seen (and photographed) without a stack.

    python -m tests.preview --state signed --port 8899        # then open http://127.0.0.1:8899/#/youtube

Every request is treated as signed in (the harness fakes the session). States: empty, signed, trouble, two, preparing, waiting,
signed_in, failed. Not a test: nothing here is used by the real service.
"""
from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from encore_admin import server as admin_server
from encore_admin.config import Config
from encore_admin.docker_api import Docker
from encore_admin.http_server import serve
from encore_admin.server import Api
from encore_admin.services import Services
from encore_admin.sessions import Sessions
from encore_admin.signin import SigninWindows

from tests.fakes import FakeDocker, Stack

NOW = int(time.time())


def card(label, state, **extra):
    base = {"id": label.lower().replace(" ", "")[:8].ljust(8, "0"), "label": label, "state": state, "pace": "gentle",
            "perHourAllowed": 400, "signedInSince": NOW - 3 * 86400, "thisHour": 38, "day": 612, "refusalsDay": 0}
    base.update(extra)
    return base


STATES = {
    "empty": ([], False, None),
    "signed": ([card("Spare account", "working")], True, 400),
    "trouble": ([card("Spare account", "resting", restUntil=NOW + 600, refusalsDay=1, perHourAllowed=280,
                      message="YouTube asked this account to slow down. It carries on by itself."),
                 card("Second account", "needs_you", message="YouTube keeps refusing this account. Sign in again.", refusalsDay=3)], True, None),
    "two": ([card("Spare account", "working", thisHour=212, email="okeyo@example.com", name="Okeyo Oyeko"),
             card("okeyo.second@example.com", "working", pace="normal", perHourAllowed=800, thisHour=190, email="okeyo.second@example.com")], True, 1200),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", default="signed", choices=sorted(STATES) + ["preparing", "waiting", "signed_in", "failed"])
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--logged-out", action="store_true")
    parser.add_argument("--https", action="store_true")
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp())
    stack = Stack()
    stack.passwords["dana"] = "x"
    stack._valid = lambda query: True  # the fake session has no real music login
    cards, signed, per_hour = STATES.get(args.state, STATES["empty"])
    stack.summary = {"accounts": cards, "signedIn": signed, "perHour": per_hour, "visitorPerHour": 200,
                     "paces": {"gentle": 400, "normal": 800, "fast": 1500}}
    now = time.time()
    stack.people_replies[("GET", "/api/people")] = (200, {"people": [
        {"user": "dana", "role": "owner", "fixed": True, "invitedBy": None, "joinedAt": None, "createdAt": now - 90 * 86400, "lastAccess": now - 60,
         "paused": False, "mustChange": False, "resetAsked": None},
        {"user": "nina", "role": "inviter", "fixed": False, "invitedBy": "dana", "joinedAt": now - 20 * 86400, "createdAt": now - 20 * 86400,
         "lastAccess": now - 3600, "paused": False, "mustChange": False, "resetAsked": None},
        {"user": "sam", "role": "guest", "fixed": False, "invitedBy": "nina", "joinedAt": now - 5 * 86400, "createdAt": now - 5 * 86400,
         "lastAccess": now - 3 * 86400, "paused": False, "mustChange": True, "resetAsked": now - 1200},
        {"user": "mia", "role": "guest", "fixed": False, "invitedBy": "nina", "joinedAt": now - 2 * 86400, "createdAt": now - 2 * 86400,
         "lastAccess": None, "paused": True, "mustChange": False, "resetAsked": None}]})
    stack.people_replies[("GET", "/api/resets")] = (200, {"requests": [{"user": "sam", "askedAt": now - 1200}]})
    stack.people_replies[("GET", "/api/invites")] = (200, {"invites": [{"id": 7, "state": "open", "role": "guest", "createdAt": now - 3600}]})
    docker = FakeDocker()
    # The quality tier: not installed in "empty", on and busy in "two", in trouble in "trouble", off otherwise.
    q = stack.quality_summary
    if args.state == "empty":
        del docker.stack_containers["encore-quality"]
        stack.quality_up = False
    if args.state in ("signed", "two", "trouble", "waiting", "signed_in", "preparing", "failed"):
        q["settings"]["soulseek"] = args.state in ("two", "trouble")
        q["health"]["slskd"]["connected"] = args.state == "two"
    if args.state in ("two", "trouble"):
        q["counts"] = {"queued": 2, "getting_ready": 1, "searching": 4, "downloading": 1, "ready": 17, "not_found": 3, "no_match": 2,
                       **({"failed": 1} if args.state == "trouble" else {})}
        q["today"] = {"started": 12, "limit": 40}
        q["trouble"] = [
            {"id": 4, "title": "Silvera", "artist": "Gojira", "state": "no_match", "message": "The music catalogue has no album by that name for this artist."},
            {"id": 9, "title": "Schism", "artist": "Tool", "state": "not_found", "message": "Nobody is sharing it right now. Encore will look again in a week."}]
        q["lastSelfTest"] = {"at": time.time() - 600, "ok": args.state == "two", "checks": [
            {"key": "lidarr", "name": "Lidarr (finds and files the albums)", "state": "ok", "note": "Version 3.1.0.4875."},
            {"key": "soulseek", "name": "Soulseek network", "state": "ok" if args.state == "two" else "problem",
             "note": "Connected." if args.state == "two" else "Not connected yet. This is tried again every few minutes."},
            {"key": "folders", "name": "Folders for the better copies", "state": "ok", "note": "Files can be shared between the downloads and the library without a second copy."}]}
    docker.log_text["encore-fetch"] = "2026-10-18 22:15:05 INFO encore_fetch: songs service on 8701\n2026-10-18 22:20:41 INFO encore_fetch.jobs: Gojira - Silvera: done in 14 s\n"
    if args.state == "trouble":
        docker.stack_containers["encore-fetch"] = ("restarting", "Restarting (1) 3 seconds ago")
        docker.stack_containers["encore-slskd"] = ("running", "Up 2 hours (unhealthy)")
    # Suggestions: not installed in "empty", on and busy in "two", switched off in "trouble".
    if args.state == "empty":
        del docker.stack_containers["encore-recs"]
        stack.recs_up = False
    if args.state == "trouble":
        stack.recs_summary["enabled"] = False
    if args.state in ("two", "signed"):
        stack.recs_summary["surfaces"] = {"made-for-you": {"shown": 140, "played": 38, "starred": 9}, "pool": {"shown": 60, "played": 21},
                                          "because": {"shown": 80, "played": 12}}
    config = Config()
    services = Services(navidrome_url=Stack.ND, people_url=Stack.PEOPLE, fetch_url=Stack.FETCH, quality_url=Stack.QUALITY, recs_url=Stack.RECS,
                         http=stack.http)
    ids = iter(["a1b2c3d4"] * 3)
    background = (lambda work: None) if args.state == "preparing" else (lambda work: work())
    signin = SigninWindows(Docker(docker, docker, config.signin_image), services.fetch_call, network="encore-server_default", minutes=15,
                           background=background, new_id=lambda: next(ids), probe=lambda host, port: True)
    # a stand-in for the browser container, so the frame has something to show
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Stand(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            page = b"<body style='margin:0;font-family:sans-serif;background:#202124;color:#e8eaed'><div style='padding:40px'><h2>Sign in</h2><p>Google's own page would be here, in a private browser on your server.</p></div></body>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    stand = ThreadingHTTPServer(("127.0.0.1", 0), Stand)
    threading.Thread(target=stand.serve_forever, daemon=True).start()
    original_target = signin.target
    signin.target = lambda path: (("127.0.0.1", stand.server_address[1]) if original_target(path) else None)
    if args.state in ("waiting", "signed_in"):
        from tests.fakes import NOTHING_YET, SIGNED_IN, firefox_cookies
        docker.files = firefox_cookies(SIGNED_IN if args.state == "signed_in" else NOTHING_YET)
        signin.start()
    elif args.state == "preparing":
        signin.start()
    elif args.state == "failed":
        docker.create_status = 500
        signin.start()
    sessions = Sessions(8)
    key = sessions.create("dana", "t" * 32, "salt")

    admin_server.SECURITY_HEADERS.clear()  # the preview frames the page at phone width; a real service never does this

    class Preview(Api):
        @staticmethod
        def _cookie(header):  # every request is signed in
            return key

        def handle(self, method, raw_path, headers, body, ip="-"):
            if raw_path.startswith("/__frame"):
                route = raw_path.split("route=")[-1] if "route=" in raw_path else "youtube"
                page = ("<!doctype html><body style='margin:0;background:#444'><iframe src='/#/" + route +
                        "' style='width:390px;height:1100px;border:0;display:block;margin:0 auto;background:#000'></iframe></body>")
                return admin_server.Response(200, page.encode(), "text/html; charset=utf-8", {})
            return super().handle(method, raw_path, headers, body, ip)

    class LoggedOut(Preview):
        @staticmethod
        def _cookie(header):
            return None

    api = (LoggedOut if args.logged_out else Preview)(config, services, signin, sessions=sessions)
    tls = None
    if args.https:
        from encore_admin.tls import ensure_certificate
        tls = ensure_certificate(tmp / "tls")
    httpd = serve(api, "127.0.0.1", args.port, tls)
    print(f"{'https' if tls else 'http'}://127.0.0.1:{args.port}/#/youtube  ({args.state})", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
