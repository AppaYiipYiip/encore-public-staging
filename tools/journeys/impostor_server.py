#!/usr/bin/env python3
"""A server that is not your server (docs/evidence/b03): it answers at an address as if it were, copies the id and public key of the real server, cannot
sign the challenge, and writes down what a phone sends it - **only the names** of the query parameters and of the headers that could carry a login, never their
values (a Subsonic token is made from the password and must not be written anywhere).

    python -I impostor_server.py REAL_SERVER_ID REAL_PUBLIC_KEY PORT LOGFILE

Both values are public (`GET /encore/api/v1/info`). From an Android emulator the PC is `10.0.2.2`. Each line of LOGFILE is JSON:
`{"t", "method", "path", "query": [names], "headers": [names], "credential": true|false}`; `credential` is true when a login, a token or a signed address came with the request.
"""
import base64
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

REAL_ID, REAL_KEY, PORT, LOG = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
CREDENTIAL_QUERY = {"u", "t", "s", "p", "token", "sig"}
CREDENTIAL_HEADERS = {"authorization", "cookie", "x-nd-authorization"}


def note(line):
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


class Impostor(BaseHTTPRequestHandler):
    def log_message(self, *args):  # the access log would print query values
        pass

    def _answer(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        headers = sorted(h.lower() for h in self.headers.keys() if h.lower() in CREDENTIAL_HEADERS)
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)  # read and forget: never kept
        credential = bool(CREDENTIAL_QUERY & set(query)) or bool(headers) or length > 0
        note({"t": round(time.time(), 1), "method": self.command, "path": parts.path, "query": sorted(query), "headers": headers,
              "body": length > 0, "credential": credential})
        if parts.path == "/encore/api/v1/info":
            self._answer(200, {"serverId": REAL_ID, "publicKey": REAL_KEY, "signature": base64.urlsafe_b64encode(os.urandom(64)).decode().rstrip("="),
                               "apiVersion": "1.0", "minAppVersion": "0.1.0", "serverVersion": "0.1.0", "name": "Not your server", "features": ["library"]})
        elif parts.path.startswith("/encore/"):
            self._answer(404, {"error": {"code": "not_found", "message": "no"}})
        else:  # a Subsonic server that says yes to everything
            self._answer(200, {"subsonic-response": {"status": "ok", "version": "1.16.1", "type": "impostor", "openSubsonic": True}})

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _handle


if __name__ == "__main__":
    open(LOG, "w").close()
    print(f"impostor on port {PORT}, copying {REAL_ID}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Impostor).serve_forever()
