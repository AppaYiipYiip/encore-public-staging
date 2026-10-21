#!/usr/bin/env python3
"""Rehearses the public path of the people service (docs/35) on this PC, before the real Funnel exists.

   python people_rehearsal.py [--music=http://192.168.50.132:4533] [--stub-accounts]

Starts the people service (checking logins against the REAL music server) and a "front door" that behaves like the Tailscale
Funnel will:  /people/*  goes to the people service, everything else to the music server. Both listen on loopback only; the
Android emulator reaches the door as http://10.0.2.2:8712 (add that as an address in the app: Your server > Add an address).
The administrator login is read from encore-admin-login.txt next to the bat files and handed to the service's environment;
nothing is printed. With --stub-accounts an invitation can be redeemed in a browser without any account being made
on the music server. Stop with Ctrl-C. Data lives in a temporary folder and is removed."""
import http.client
import os
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "server" / "encore-people"
KIT = REPO / "server" / "reference"  # encore_user.py lives here (the Docker image copies it next to the service)
LOGIN = REPO.parent / "encore-admin-login.txt"
DOOR_PORT, PEOPLE_PORT = 8712, 8713
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization", "proxy-authenticate", "host"}

STUB_ACCOUNTS = "--stub-accounts" in sys.argv
music_url = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--music=")), None)
login = {}
for line in LOGIN.read_text(encoding="utf-8").splitlines():
    if ":" in line and not line.startswith(" "):
        key, value = line.split(":", 1)
        login[key.strip()] = value.strip()
music = urllib.parse.urlsplit(music_url or login["address"])


class Door(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self):
        host, port = ("127.0.0.1", PEOPLE_PORT) if self.path.startswith("/people") else (music.hostname, music.port or 80)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers["X-Forwarded-For"] = self.client_address[0]
        conn = http.client.HTTPConnection(host, port, timeout=60)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            r = conn.getresponse()
            data = r.read()
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() not in HOP and k.lower() != "content-length":
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except OSError:
            self.send_error(502)
        finally:
            conn.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _forward

    def log_message(self, *args):  # no access log: tokens travel in the query string
        pass


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="encore-people-rehearsal-") as scratch:
        env = dict(
            os.environ,
            NAVIDROME_URL=f"{music.scheme}://{music.netloc}",
            NAVIDROME_ADMIN_USER=login["user"],
            NAVIDROME_ADMIN_PASSWORD=login["password"],
            DATA_DIR=str(Path(scratch) / "data"),
            MUSIC_DIR=str(Path(scratch) / "music-unused"),  # an invitation would make a folder here: do not redeem one in a rehearsal
            HOST="127.0.0.1",
            PORT=str(PEOPLE_PORT),
            PEOPLE_INVITERS="owner",
            PUBLIC_URL=f"http://10.0.2.2:{DOOR_PORT}",
            SERVER_NAME="Rehearsal",
            PYTHONPATH=str(KIT),
        )
        service = None
        if STUB_ACCOUNTS:
            # In this process, with an account creator that creates nothing: the whole invitation page (including the
            # "your account is ready" step) can be tried in a browser without a real account being made on the music server.
            sys.path[:0] = [str(SERVICE), str(KIT)]
            from encore_people.activity import Activity
            from encore_people.invites import Invites
            from encore_people.navidrome import Navidrome
            from encore_people.server import Api, Settings, serve

            class Stub:
                def add_person(self, username: str, password: str) -> None:
                    print(f"(stub) an account called {username!r} would be made now; nothing was created")

            api = Api(invites=Invites(Path(scratch) / "people.db", provisioner=Stub()),
                      activity=Activity(Path(scratch) / "sharing.json"),
                      navidrome=Navidrome(f"{music.scheme}://{music.netloc}"),
                      settings=Settings(public_url=env["PUBLIC_URL"], server_name="Rehearsal", inviters=frozenset({"owner"})))
            people = serve(api, "127.0.0.1", PEOPLE_PORT)
            threading.Thread(target=people.serve_forever, daemon=True).start()
        else:
            service = subprocess.Popen([sys.executable, "-m", "encore_people"], cwd=SERVICE, env=env)
        door = ThreadingHTTPServer(("127.0.0.1", DOOR_PORT), Door)
        threading.Thread(target=door.serve_forever, daemon=True).start()
        print(f"The door is on http://127.0.0.1:{DOOR_PORT}  (the emulator: http://10.0.2.2:{DOOR_PORT}); Ctrl-C stops it.")
        try:
            if service is not None:
                return service.wait()
            threading.Event().wait()
            return 0
        except KeyboardInterrupt:
            return 0
        finally:
            door.shutdown()
            if service is not None:
                service.terminate()


if __name__ == "__main__":
    sys.exit(main())
