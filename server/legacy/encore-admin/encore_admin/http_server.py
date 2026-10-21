"""The HTTP(S) server of the admin website (docs/49), and the window through it.

One port serves both: a first byte of 0x16 is a browser starting a TLS conversation (https); anything else is plain http, which
is answered with a redirect to https on the same port, so typing `http://address:8800` still ends up in the right place.

The sign-in browser is shown in the page: requests under `/window-<id>/` are passed to that one container (inside the stack's own
network), after the session cookie has been checked, and the cookie is *not* passed on. The browser's live stream is a WebSocket,
so an `Upgrade` request is turned into a plain two-way pipe once the container has answered it.
"""
from __future__ import annotations

import http.client
import logging
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .server import SECURITY_HEADERS, Api, Response, _error

log = logging.getLogger("encore_admin.http")

_HOP = frozenset({"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding",
                  "upgrade", "proxy-connection"})
_STRIPPED_BACK = frozenset({"content-length", "x-frame-options", "content-security-policy", "set-cookie"} | _HOP)


def serve(api: Api, host: str, port: int, tls: tuple[Path, Path] | None = None) -> ThreadingHTTPServer:
    context = None
    if tls is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(tls[0]), str(tls[1]))

    class Handler(BaseHTTPRequestHandler):
        server_version = "encore-admin"
        sys_version = ""
        protocol_version = "HTTP/1.1"
        plain_on_tls_port = False

        def setup(self) -> None:
            # Runs in the request's own thread, so a slow handshake holds nobody else up.
            self.request.settimeout(15)
            if context is not None:
                try:
                    first = self.request.recv(1, socket.MSG_PEEK)
                except OSError:
                    first = b""
                if first == b"\x16":
                    self.request = context.wrap_socket(self.request, server_side=True)
                else:
                    self.plain_on_tls_port = True
            super().setup()

        def handle(self) -> None:
            try:
                super().handle()
            except (ssl.SSLError, ConnectionError, TimeoutError, OSError):
                self.close_connection = True

        # ------------------------------------------------------------------ requests

        def _do(self) -> None:
            if self.plain_on_tls_port:
                where = (self.headers.get("Host") or f"localhost:{port}").split(",")[0]
                if ":" not in where.rsplit("]", 1)[-1]:
                    where = f"{where}:{port}"
                self.send_response(308)
                self.send_header("Location", f"https://{where}{self.path}")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                return
            if self.path.startswith("/window-"):
                self._window()
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > 600_000:
                self._send(Response(413, b'{"error":"too_big","message":"That is too big."}'))
                return
            body = self.rfile.read(length) if length else b""
            ip = self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.client_address[0]
            try:
                response = api.handle(self.command, self.path, dict(self.headers), body, ip)
            except Exception:  # noqa: BLE001 - a request never crashes the server
                log.exception("request failed: %s %s", self.command, self.path.split("?")[0])
                response = _error(500, "internal", "Something went wrong. Try again.")
            self._send(response)

        do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _do

        def _send(self, r: Response) -> None:
            self.send_response(r.status)
            self.send_header("Content-Type", r.content_type)
            self.send_header("Content-Length", str(len(r.body)))
            for key, value in {**SECURITY_HEADERS, **r.headers}.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(r.body)

        # ------------------------------------------------------------------ the sign-in window

        def _window(self) -> None:
            found = api.proxy_target(self.path, dict(self.headers))
            if isinstance(found, Response):
                self._send(found)
                return
            upstream_host, upstream_port, upstream_path = found
            if self.headers.get("Upgrade", "").lower() == "websocket":
                origin = self.headers.get("Origin")
                if origin and origin.split("://", 1)[-1] != self.headers.get("Host"):
                    self._send(_error(403, "forbidden", "That request did not come from this website."))
                    return
                self._tunnel(upstream_host, upstream_port, upstream_path)
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP | {"cookie", "content-length"}}
            headers["X-Forwarded-Proto"] = "https" if context is not None else "http"
            try:
                connection = http.client.HTTPConnection(upstream_host, upstream_port, timeout=30)
                try:
                    connection.request(self.command, upstream_path, body=body, headers=headers)
                    answer = connection.getresponse()
                    data = answer.read()
                finally:
                    connection.close()
            except OSError:
                self._send(_error(502, "starting", "The sign-in window is still starting. Give it a few seconds."))
                return
            self.send_response(answer.status)
            for key, value in answer.getheaders():
                if key.lower() not in _STRIPPED_BACK:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Frame-Options", "SAMEORIGIN")  # the window is shown in our own page, nowhere else
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _tunnel(self, upstream_host: str, upstream_port: int, upstream_path: str) -> None:
            try:
                upstream = socket.create_connection((upstream_host, upstream_port), timeout=10)
            except OSError:
                self._send(_error(502, "starting", "The sign-in window is still starting. Give it a few seconds."))
                return
            lines = [f"{self.command} {upstream_path} {self.request_version}"]
            lines += [f"{k}: {v}" for k, v in self.headers.items() if k.lower() != "cookie"]
            upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
            upstream.settimeout(None)
            self.connection.settimeout(None)

            def pipe(source: socket.socket, target: socket.socket) -> None:
                try:
                    while True:
                        chunk = source.recv(65536)
                        if not chunk:
                            break
                        target.sendall(chunk)
                except (OSError, ssl.SSLError):
                    pass
                finally:
                    for end in (source, target):
                        try:
                            end.shutdown(socket.SHUT_RDWR)
                        except (OSError, ssl.SSLError):
                            pass

            back = threading.Thread(target=pipe, args=(upstream, self.connection), daemon=True)
            back.start()
            pipe(self.connection, upstream)
            back.join(5)
            upstream.close()
            self.close_connection = True

        def log_message(self, fmt: str, *args: object) -> None:  # the access log never has a query string (it has logins)
            log.info("%s %s", self.command, self.path.split("?")[0])

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd
