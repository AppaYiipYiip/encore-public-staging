"""The sign-in browser shown inside the admin page: who may see it, what is (not) passed on, the live stream, https."""
import http.client
import json
import shutil
import socket
import ssl
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from encore_admin.config import Config
from encore_admin.docker_api import Docker
from encore_admin.http_server import serve
from encore_admin.server import COOKIE, Api
from encore_admin.services import Services
from encore_admin.sessions import Sessions
from encore_admin.signin import SigninWindows
from encore_admin.tls import ensure_certificate

from tests.fakes import FakeDocker, Stack


class FakeBrowser:
    """What the browser container answers: a page that tries to forbid framing, and a WebSocket that echoes."""

    def __init__(self):
        self.seen = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})
                if self.headers.get("Upgrade", "").lower() == "websocket":
                    self.wfile.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
                    self.wfile.flush()
                    while True:
                        data = self.connection.recv(1024)
                        if not data:
                            return
                        self.connection.sendall(b"echo:" + data)
                page = b"<html>the window</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
                self.send_header("Set-Cookie", "browser=1")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)

            do_GET = do_POST = _answer

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class WindowTestBase(unittest.TestCase):
    TLS = False

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.browser = FakeBrowser()
        self.addCleanup(self.browser.close)
        self.stack = Stack()
        docker = FakeDocker()
        config = Config()
        services = Services(navidrome_url=Stack.ND, people_url=Stack.PEOPLE, fetch_url=Stack.FETCH, http=self.stack.http)
        self.signin = SigninWindows(Docker(docker, docker, config.signin_image), services.fetch_call, network="encore-server_default",
                                    minutes=15, background=lambda work: work(), new_id=lambda: "a1b2c3d4", probe=lambda host, port: True)
        self.signin.start()
        # the browser container is not reachable by its name here: point the proxy at the fake one
        original = self.signin.target

        def target(path):
            found = original(path)
            return ("127.0.0.1", self.browser.port, found[2]) if found else None

        self.signin.target = target
        sessions = Sessions(8)
        self.key = sessions.create("dana", "t" * 32, "salt")
        self.api = Api(config, services, self.signin, sessions=sessions)
        tls = None
        if self.TLS:
            tls = ensure_certificate(root / "tls")
            if tls is None:
                self.skipTest("openssl is not available here")
        self.httpd = serve(self.api, "127.0.0.1", 0, tls)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]
        self.context = ssl.create_default_context()
        self.context.check_hostname = False
        self.context.verify_mode = ssl.CERT_NONE

    def connect(self):
        if self.TLS:
            return http.client.HTTPSConnection("127.0.0.1", self.port, timeout=10, context=self.context)
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)

    def get(self, path, cookie=True, method="GET", body=None, headers=None):
        sent = dict(headers or {})
        if cookie:
            sent["Cookie"] = f"{COOKIE}={self.key}; other=1"
        c = self.connect()
        c.request(method, path, body=body, headers=sent)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data


class TheWindowInThePageTest(WindowTestBase):
    def test_only_the_signed_in_owner_sees_the_window(self):
        r, data = self.get("/window-a1b2c3d4/", cookie=False)
        self.assertEqual(r.status, 401)
        self.assertEqual(json.loads(data)["error"], "sign_in")
        self.assertEqual(self.browser.seen, [], "nothing reached the browser")

    def test_the_owner_gets_the_browsers_page_without_the_websites_cookie_reaching_the_browser(self):
        r, data = self.get("/window-a1b2c3d4/")
        self.assertEqual((r.status, data), (200, b"<html>the window</html>"))
        seen = self.browser.seen[0]
        self.assertEqual(seen["path"], "/", "the window's own prefix is taken off: the browser's page lives at its root")
        self.assertNotIn("Cookie", seen["headers"], "the admin session must never be handed to another program")
        self.assertNotIn("encore_admin", json.dumps(seen["headers"]))

    def test_the_page_may_be_shown_inside_our_own_page_and_nowhere_else_and_the_browsers_cookies_are_not_kept(self):
        r, _ = self.get("/window-a1b2c3d4/")
        self.assertEqual(r.getheader("X-Frame-Options"), "SAMEORIGIN")
        self.assertIsNone(r.getheader("Content-Security-Policy"), "the browser's own policy would not fit the page it is shown in")
        self.assertIsNone(r.getheader("Set-Cookie"), "the browser container sets no cookie on the admin's address")
        self.assertEqual(r.getheader("Cache-Control"), "no-store")

    def test_a_request_with_a_body_is_passed_on(self):
        r, _ = self.get("/window-a1b2c3d4/input?x=1", method="POST", body=b"keys", headers={"Content-Type": "text/plain"})
        self.assertEqual(r.status, 200)
        self.assertEqual((self.browser.seen[0]["method"], self.browser.seen[0]["path"], self.browser.seen[0]["body"]),
                         ("POST", "/input?x=1", b"keys"))

    def test_another_windows_path_and_other_paths_are_not_passed_on(self):
        self.assertEqual(self.get("/window-ffffffff/")[0].status, 404)
        self.assertEqual(self.get("/window-a1b2c3d4evil/")[0].status, 404)
        self.assertEqual(self.browser.seen, [])

    def test_a_window_that_is_closed_is_gone(self):
        self.signin.cancel("a1b2c3d4")
        self.signin.target = lambda path: None
        self.assertEqual(self.get("/window-a1b2c3d4/")[0].status, 404)

    def test_a_browser_that_is_not_up_yet_is_a_sentence_not_an_error_page(self):
        self.browser.close()
        r, data = self.get("/window-a1b2c3d4/")
        self.assertEqual(r.status, 502)
        self.assertIn("still starting", json.loads(data)["message"])

    def test_the_live_stream_passes_both_ways_and_the_cookie_stays_behind(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        sock.sendall((f"GET /window-a1b2c3d4/websockify HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: x\r\nSec-WebSocket-Version: 13\r\n"
                      f"Cookie: {COOKIE}={self.key}\r\n\r\n").encode())
        got = b""
        while b"\r\n\r\n" not in got:
            got += sock.recv(1024)
        self.assertTrue(got.startswith(b"HTTP/1.1 101"), got[:40])
        sock.sendall(b"hello")
        echoed = b""
        while len(echoed) < len(b"echo:hello"):
            echoed += sock.recv(1024)
        self.assertEqual(echoed, b"echo:hello")
        sock.close()
        self.assertNotIn("Cookie", self.browser.seen[0]["headers"])
        self.assertEqual(self.browser.seen[0]["path"], "/websockify")

    def test_a_stream_without_the_owners_session_is_refused(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        sock.sendall((f"GET /window-a1b2c3d4/websocket HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\n\r\n").encode())
        self.assertTrue(sock.recv(1024).startswith(b"HTTP/1.1 401"))
        sock.close()
        self.assertEqual(self.browser.seen, [])

    def test_a_stream_started_from_another_website_is_refused(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        sock.sendall((f"GET /window-a1b2c3d4/websocket HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nOrigin: https://evil.example\r\nCookie: {COOKIE}={self.key}\r\n\r\n").encode())
        self.assertTrue(sock.recv(1024).startswith(b"HTTP/1.1 403"))
        sock.close()
        self.assertEqual(self.browser.seen, [])

    def test_the_admin_pages_themselves_still_work_beside_the_window(self):
        r, data = self.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"Encore admin", data)
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY", "the admin's own pages can never be framed")


class OverHttpsTest(WindowTestBase):
    TLS = True

    def test_the_site_answers_over_https_and_an_http_visit_is_sent_to_https(self):
        r, data = self.get("/")
        self.assertEqual(r.status, 200)
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        sock.sendall(f"GET /admin/api/me?x=1 HTTP/1.1\r\nHost: 192.168.1.5:{self.port}\r\n\r\n".encode())
        answer = sock.recv(2048).decode("latin-1")
        sock.close()
        self.assertTrue(answer.startswith("HTTP/1.1 308"), answer[:40])
        self.assertIn(f"Location: https://192.168.1.5:{self.port}/admin/api/me?x=1", answer)

    def test_the_window_works_through_https_too(self):
        r, data = self.get("/window-a1b2c3d4/")
        self.assertEqual((r.status, data), (200, b"<html>the window</html>"))


class CertificateTest(unittest.TestCase):
    def test_it_is_made_once_kept_private_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            made = ensure_certificate(Path(tmp) / "tls", ("encore.local", "192.168.1.5"))
            if made is None:
                self.skipTest("openssl is not available here")
            certificate, key = made
            first = certificate.read_bytes()
            self.assertIn(b"BEGIN CERTIFICATE", first)
            self.assertEqual(ensure_certificate(Path(tmp) / "tls"), made)
            self.assertEqual(certificate.read_bytes(), first, "the same certificate every time")

    def test_no_openssl_means_plain_http_not_a_crash(self):
        import subprocess

        def missing(*args, **kwargs):
            raise FileNotFoundError("openssl")

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(ensure_certificate(Path(tmp) / "tls", run=missing))
            failed = lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom")
            self.assertIsNone(ensure_certificate(Path(tmp) / "tls2", run=failed))


if __name__ == "__main__":
    unittest.main()
