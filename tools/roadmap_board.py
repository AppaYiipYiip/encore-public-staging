#!/usr/bin/env python3
"""The roadmap board: the shared memory of the owner, the AI agents (any Claude account) and the developers, as a page on the owner's own computer.
No cloud, no account: it works the same whichever Claude account is signed in.

    roadmap.bat                              # Windows: opens the board in its own window (no address bar)
    python tools/roadmap_board.py            # the same
    python tools/roadmap_board.py --tab      # a normal browser tab;  --no-open: just serve;  --port N;  --root PATH (another checkout)

What it holds (each fact in ONE place, see tools/roadmap_plan.py, roadmap_notes.py, roadmap_work.py):
  * the plan: ONE flat list (no phases), its ORDER changed by dragging -> docs/roadmap/order.json
  * notes and details on every item, and a general thread        -> docs/roadmap/notes/<ITEM>/*.json  (one file per note; information, never commands)
  * ideas typed on the board (next N-id, straight into the list)  -> docs/roadmap/items.json, order.json
  * "Working now": the claims AI agents announce (inside .git, shared by all worktrees); the page only shows them
The page is for the owner only and always writes as the owner; AI agents and developers use `python tools/roadmap.py`.
Status and titles of existing items are read-only here: agents change them in their PRs.

Safe by construction: standard library only; bound to 127.0.0.1; refuses a request whose Host is not this server; a write needs the header `X-Roadmap: 1` (a web
page on another site cannot send it); a save with an old version is refused (409); every note is shown as plain text under a Content-Security-Policy that
allows only this page's own script (so a crafted note cannot run anything); one board at a time (see roadmap_launch.py); a page opened over OLD code says so.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roadmap_launch as launch  # noqa: E402
import roadmap_notes as rn  # noqa: E402
import roadmap_plan as rp  # noqa: E402
import roadmap_work as rw  # noqa: E402

TOOLS = Path(__file__).resolve().parent
PAGE = TOOLS / "roadmap_board.html"
CODE_FILES = ("roadmap_board.py", "roadmap_board.html", "roadmap_plan.py", "roadmap_notes.py", "roadmap_work.py", "roadmap_launch.py")
DEFAULT_PORT = 8765
HOSTS = ("127.0.0.1", "localhost", launch.NAME)
MAX_BODY = 1_000_000          # a plan of a hundred items is a few kilobytes
HTTP_ROLES = ("owner",)       # the page is the owner's; agents and developers write with `python tools/roadmap.py`


def code_hash() -> str:
    """A fingerprint of the code and the page, so a board can tell when the files changed after it started."""
    h = hashlib.sha256()
    for name in CODE_FILES:
        try:
            h.update(name.encode() + b"\0" + (TOOLS / name).read_bytes().replace(b"\r\n", b"\n"))
        except OSError:
            h.update(name.encode() + b"\0missing")
    return h.hexdigest()[:16]


RUNNING_CODE = code_hash()
STARTED = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
_STYLE = re.compile(r"<style>(.*?)</style>", re.S)
_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)


def page() -> tuple[bytes, str]:
    """The page and the Content-Security-Policy that goes with it: only the page's own inline script and style may run (by hash), nothing else, no network but this server."""
    text = PAGE.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")

    def hashes(rx: re.Pattern) -> str:
        found = rx.findall(text)
        return " ".join("'sha256-" + base64.b64encode(hashlib.sha256(b.encode("utf-8")).digest()).decode() + "'" for b in found) or "'none'"

    csp = ("default-src 'none'; script-src " + hashes(_SCRIPT) + "; style-src " + hashes(_STYLE) +
           "; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    return text.encode("utf-8"), csp


# ------------------------------------------------------------------------------------------------------------------ the state
def board_state(root: Path = rp.ROOT, wdir: Path | None = None, now: datetime | None = None, runner=subprocess.run) -> dict:
    p = rp.load(root)
    errors, warnings = rp.validate(p)
    est = rp.estimates(p)
    notes, note_problems = rn.read_all(root)
    note_problems += rn.cross_check(notes)
    nsum = rn.summary(notes)
    empty = {"count": 0, "details": 0, "waiting": [], "last": ""}
    items: dict[str, dict] = {}
    for t in set(p.tasks) | set(p.items):
        meta = p.items.get(t, {})
        items[t] = {
            "id": t,
            "title": rp.title_of(p, t),
            "kind": meta.get("kind", "feature"),
            "note": meta.get("note", ""),
            "proposal": bool(meta.get("proposal")),
            "pending": bool(meta.get("pending")),          # an idea typed on the board, its write-up not yet written
            "from": meta.get("from", ""),
            "size": rp.size_of(p, t),
            "days": rp.agent_days(rp.size_of(p, t)),
            "state": rp.state_of(p, t),                    # derived: todo, built, reopened (the owner reported a problem) or walked (proven, or his word on an item only he can finish)
            "evidence": rp.evidence_of(p, t),
            "owner_check": ({"at": p.owner_checks[t]["at"], "body": p.owner_checks[t]["body"]} if t in p.owner_checks else None),
            "problem": ({"at": p.problems[t]["at"], "body": p.problems[t]["body"]} if t in p.problems else None),
            "can_finish": meta.get("kind") == "owner" and rp.state_of(p, t) != "walked",        # "I did this": only for what only he can finish
            "can_judge": bool(meta.get("judge")),                                               # "I checked it": his own judgement is part of the acceptance
            "why": rp.why_of(p, t) or "",
            "needs": [{"id": n, "mark": m, "title": p.items.get(n, {}).get("title", n)} for n, m in rp.needs_of(p, t)],
            "est": est["items"].get(t),
            "notes": nsum.get(t, empty),
        }
    for t, it in items.items():                       # an item only the owner can do carries its pinned "what to do" (the latest detail note), shown in pink on its row
        if it["kind"] == "owner" and it["state"] != "walked":
            det = [n for n in rn.thread(notes, t) if n.get("type") == "detail"]
            it["what_to_do"] = det[-1]["body"] if det else ""
    claims = rw.list_claims(root, now=now, wdir=wdir)
    pending = rw.git_pending(root, runner=runner)
    state = {
        "board": "encore-roadmap",
        "code": RUNNING_CODE,
        "stale": code_hash() != RUNNING_CODE,
        "started": STARTED,
        "root": str(root),
        "branch": rw.git_branch(root, runner=runner),
        "pending": pending,
        "version": p.version,
        "order": p.order,
        "later": p.later,
        "items": items,
        "total": est["total"],
        "counts": est["counts"],
        "constants": {"S": rp.SIZE_DAYS["S"], "M": rp.SIZE_DAYS["M"], "L": rp.SIZE_DAYS["L"], "rate": rp.RATE, "slowdown": list(rp.SLOWDOWN), "builtRemaining": rp.BUILT_REMAINING},
        "errors": errors,
        "warnings": warnings,
        "board_thread": nsum.get(rn.BOARD, empty),
        "note_problems": note_problems,
        "working": {"claims": claims, "staleHours": rw.STALE_HOURS},
    }
    # one fingerprint of everything a person can see, so the page re-draws only when something changed (hours quiet tick on their own)
    watch = [state["version"], {k: (v["title"], v["state"], v["size"], v["pending"], v["notes"], v["evidence"]) for k, v in sorted(items.items())}, state["board_thread"],
             [(c["id"], c["updated"], c["status"]) for c in claims], pending, state["stale"], note_problems, errors, warnings]
    state["stamp"] = hashlib.sha256(json.dumps(watch, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return state


class BoardServer(ThreadingHTTPServer):
    daemon_threads = True
    # ONE board per port. Python's default (SO_REUSEADDR) is only about restarting quickly on Linux and macOS; on WINDOWS the same option lets a second server bind a port
    # that is already taken, so an old board and a new one would share it silently (proved by test_a_second_start_opens_the_running_board_but_never_starts_another).
    # There the port is taken exclusively instead, which also keeps another program from claiming it while the board runs.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    root: Path
    wdir: Path


def make_server(root: Path, port: int) -> BoardServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "EncoreRoadmap/2"
        server: BoardServer

        def log_message(self, fmt: str, *args: object) -> None:  # quiet
            pass

        def _host_ok(self) -> bool:
            host, _, port_s = (self.headers.get("Host") or "").lower().partition(":")
            if host not in HOSTS:
                return False
            return (port_s == str(self.server.server_address[1])) if port_s else self.server.server_address[1] == 80

        def _send(self, code: int, body: bytes, ctype: str, csp: str | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", csp or "default-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: object) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _state(self) -> dict:
            return board_state(root, wdir=self.server.wdir)

        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._json(403, {"error": "this server answers only on this computer"})
            url = urlsplit(self.path)          # a query string (a cache-buster, a bookmark) is ignored, except where an endpoint reads one
            try:
                if url.path in ("/", "/index.html"):
                    body, csp = page()
                    return self._send(200, body, "text/html; charset=utf-8", csp)
                if url.path == "/api/hello":
                    return self._json(200, {"board": "encore-roadmap", "code": RUNNING_CODE, "root": str(root), "pid": os.getpid(), "started": STARTED})
                if url.path == "/api/state":
                    return self._json(200, self._state())
                if url.path == "/api/notes":
                    item = (parse_qs(url.query).get("item") or [""])[0]
                    if not rn.ITEM_RE.match(item):
                        return self._json(400, {"error": "ask for one item: /api/notes?item=P3-12"})
                    notes, _ = rn.read_all(root)
                    view = rn.thread(notes, item)
                    waiting = {n["id"]: n["waiting_for"] for n in rn.waiting(notes, item)}
                    return self._json(200, {"item": item, "notes": [{**n, "waiting_for": waiting.get(n["id"], [])} for n in view]})
            except Exception:  # noqa: BLE001 - a broken file must not kill the board; the page says so
                return self._json(500, {"error": "the board could not read the plan files (details in the console window)"})
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            # Read the body FIRST, even when the request is about to be refused: answering without reading it makes some clients see a reset connection.
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n > MAX_BODY:
                self.close_connection = True
                return self._json(413, {"error": "too large"})
            raw = self.rfile.read(n) if n else b""
            if not self._host_ok():
                return self._json(403, {"error": "this server answers only on this computer"})
            if self.headers.get("X-Roadmap") != "1":
                return self._json(403, {"error": "missing the X-Roadmap header"})
            path = urlsplit(self.path).path
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._json(400, {"error": "not JSON"})
            if not isinstance(payload, dict):
                return self._json(400, {"error": "not an object"})
            try:
                if path == "/api/order":
                    code, body = rp.apply_order(root, payload)
                    return self._json(code, body)
                if path == "/api/move":                      # a drag: the item lands where it was dropped and what it needs (or what needs it) is carried along
                    code, body = rp.apply_move(root, payload)
                    return self._json(code, body)
                if path == "/api/notes":
                    return self._json(*self._note(payload))
                if path == "/api/ideas":
                    return self._json(*self._idea(payload))
                if path == "/api/check":
                    return self._json(*self._check(payload))
            except rn.NoteError as e:
                return self._json(400, {"error": str(e)})
            except Exception:  # noqa: BLE001
                return self._json(500, {"error": "the board could not write (details in the console window)"})
            self._json(404, {"error": "not found"})

        # -- writes from the page: always as the owner (the page is his); the label is not a login, see roadmap_notes.py
        def _who(self, payload: dict) -> tuple[str, str]:
            role, by = payload.get("role"), payload.get("by") or "Owner"
            if role not in HTTP_ROLES or not isinstance(by, str):
                raise rn.NoteError("this page writes only as the owner; AI agents and developers use `python tools/roadmap.py`")
            return role, by

        def _known(self) -> set[str]:
            p = rp.load(root)
            return set(p.tasks) | set(p.items)

        def _note(self, payload: dict) -> tuple[int, dict]:
            role, by = self._who(payload)
            to = payload.get("to") or []
            if not isinstance(to, list):
                raise rn.NoteError("`to` is a list of roles")
            for k in ("item", "body", "type"):
                if k in payload and not isinstance(payload[k], str):
                    raise rn.NoteError(f"`{k}` must be text")
            note = rn.add(root, payload.get("item", ""), role, by, payload.get("body", ""), payload.get("type", "note"), to,
                          payload.get("reply_to") or None, payload.get("replaces") or None, self._known())
            return 200, {"ok": True, "note": note}

        def _check(self, payload: dict) -> tuple[int, dict]:
            self._who(payload)
            vals = [payload.get(k, "") for k in ("item", "action", "body")]
            if not all(isinstance(v, str) for v in vals):
                raise rn.NoteError("item, action and body must be text")
            return 200, {"ok": True, **rp.owner_action(root, vals[0], vals[1], vals[2])}

        def _idea(self, payload: dict) -> tuple[int, dict]:
            _, by = self._who(payload)
            vals = [payload.get(k, "") for k in ("title", "note", "kind", "size")]
            position = payload.get("position", "end")
            if not all(isinstance(v, str) for v in vals) or not isinstance(position, str):
                raise rn.NoteError("title, note, kind, size and position must be text")
            return 200, {"ok": True, "idea": rp.add_idea(root, vals[0], vals[1], vals[2], vals[3], by, position)}

    srv = BoardServer(("127.0.0.1", port), Handler)
    srv.root, srv.wdir = root, rw.work_dir(root)
    return srv


def main(argv: list[str]) -> int:
    port = DEFAULT_PORT
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    root = Path(argv[argv.index("--root") + 1]).resolve() if "--root" in argv else rp.ROOT      # another checkout (a developer's clone, or a scratch copy to try things on)
    try:
        srv = make_server(root, port)
    except OSError:
        verdict, message = launch.decide_when_port_is_taken(launch.probe(port), str(root), code_hash(), port)
        print(message)
        if verdict == "open" and "--no-open" not in argv:
            launch.open_board(port, app_window="--tab" not in argv)
        return 0 if verdict == "open" else 1
    print("Encore roadmap board is running.")
    print("Leave this window open while you use the board; close it (or press Ctrl+C) when you are done.")
    print(f"For a bookmark: http://{launch.NAME}:{port}/    Reading and writing: {root}")
    if "--no-open" not in argv:
        threading.Timer(0.6, lambda: print("Opened as:", launch.open_board(port, app_window="--tab" not in argv))).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
