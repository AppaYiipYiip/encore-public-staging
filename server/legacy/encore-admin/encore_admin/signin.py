"""The sign-in window: a real browser, shown inside the admin page, where the owner signs in to Google (docs/50 section 4).

Nobody hands a cookie to a program, and nobody types a second password. The owner presses "Sign in to YouTube"; this starts a fresh
Firefox container that publishes no port: the admin website shows it, in the same page, only to the signed-in owner (http_server.py
passes `/window-<id>/` on after checking the session). The owner types the account into Google's own page in it. When YouTube itself
has the login (read out of the browser's cookie file through Docker: browser_cookies.py), the page keeps it by itself: the browser is
stopped cleanly (so its latest cookies are on disk and nothing rotates them any more), the sign-in is handed to the songs service as an
account, and the window is deleted with everything in it. A window nobody finishes is deleted after a few minutes. One window at a time.

Nothing is shared with the host (the browser's profile stays inside its own container), so the same code runs on any system that runs
Docker.

States: `preparing` (the browser is downloaded the first time, about 330 MB), `starting`, `waiting` (nobody signed in yet),
`signed_in`, `failed`. A window that is not there any more (finished, cancelled, ran out) is `gone`.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .browser_cookies import login_state, session_text
from .docker_api import Docker, DockerError

log = logging.getLogger("encore_admin.signin")

#: Where the browser's page listens inside its container (plain http; noVNC).
INTERNAL_PORT = 5800
#: The browser's cookie file inside its container, with the log and index Firefox keeps beside it while it runs.
COOKIE_FILE = "/config/profile/cookies.sqlite"


@dataclass
class Window:
    id: str
    created: float
    expires: float
    replace: str | None
    state: str = "preparing"
    message: str = ""
    ready: bool = False

    @property
    def container(self) -> str:
        return f"encore-signin-{self.id}"

    @property
    def path(self) -> str:
        return f"/window-{self.id}/"


class SigninWindows:
    def __init__(self, docker: Docker, fetch_call: Callable[..., "tuple[int, dict]"], *, network: str, minutes: int = 15,
                 clock: Callable[[], float] = time.time, background: Callable[[Callable[[], None]], None] | None = None,
                 new_id: Callable[[], str] = lambda: secrets.token_hex(4),
                 probe: Callable[[str, int], bool] | None = None) -> None:
        self._docker = docker
        self._fetch = fetch_call
        self._network = network
        self._ttl = minutes * 60.0
        self._clock = clock
        self._background = background or self._thread
        self._new_id = new_id
        self._probe = probe or _probe_http
        self._lock = threading.RLock()
        self._window: Window | None = None

    @staticmethod
    def _thread(work: Callable[[], None]) -> None:
        threading.Thread(target=work, daemon=True, name="signin-window").start()

    # ------------------------------------------------------------------ the person's side

    def start(self, replace: str | None = None) -> dict:
        """Opens a sign-in window (or says which one is open). [replace] is an account that is being signed in again."""
        with self._lock:
            self._expire()
            if self._window is not None:
                return self._view(self._window)
            now = self._clock()
            window = Window(self._new_id(), now, now + self._ttl, replace)
            self._window = window
        self._background(lambda: self._prepare(window))
        return self._view(window)

    def current(self) -> dict | None:
        with self._lock:
            self._expire()
            return self._view(self._window) if self._window is not None else None

    def status(self, window_id: str) -> dict:
        with self._lock:
            self._expire()
            window = self._window
            if window is None or window.id != window_id:
                return {"state": "gone"}
            if window.state != "waiting":
                return self._view(window)
        if not self._docker.running(window.container):
            self._fail(window, "The sign-in window closed. Start it again.")
            return self._view(window)
        if not window.ready:
            if not self._probe(window.container, INTERNAL_PORT):
                return self._view(window)
            window.ready = True
        view = self._view(window)
        state = login_state(self._cookies(window))
        if state == "youtube":
            view["state"] = "signed_in"
        elif state == "google":
            view["detail"] = "Almost there: YouTube is still loading in the window. Give it a few seconds."
        return view

    def finish(self, window_id: str, label: str, user: str, token: str, salt: str) -> tuple[int, dict]:
        """Keeps the sign-in made in the window as an account, then deletes the window. Returns the songs service's answer (the
        accounts) or the sentence that says why not."""
        with self._lock:
            self._expire()
            window = self._window
            if window is None or window.id != window_id:
                return 404, {"error": "gone", "message": "That sign-in window is not open any more."}
            if window.state not in ("waiting", "signed_in"):
                return 409, {"error": "not_ready", "message": "The sign-in window is not ready yet."}
        if login_state(self._cookies(window)) != "youtube":
            return 422, {"error": "not_signed_in", "message": "Nobody has signed in in that window yet."}
        # Signed in: end the browser cleanly *before* reading its cookies for good. A running browser keeps changing the sign-in's
        # cookies (YouTube rotates them in an open tab) and only writes them to disk now and then, so a copy taken while it runs can
        # be out of date by the time it is used; a clean stop writes the latest ones and nothing changes them afterwards.
        self._docker.stop(window.container)
        text = self._cookies(window)
        if login_state(text) != "youtube":
            return self._give_back(window, 422, "Nobody has signed in in that window yet.")
        body: dict = {"cookies": text}
        if label and not window.replace:
            body["label"] = label
        route = f"/accounts/{window.replace}/login" if window.replace else "/accounts"
        status, data = self._fetch("POST", route, user, token, salt, body)
        if status == 200:
            self._close(window)
            return 200, data
        if status == 422:
            return self._give_back(window, 422, data.get("message") or "That sign-in could not be used.")
        return self._give_back(window, 502, "The songs service did not answer. Try again in a moment.")

    def cancel(self, window_id: str) -> bool:
        with self._lock:
            window = self._window
            if window is None or window.id != window_id:
                return False
        self._close(window)
        return True

    # ------------------------------------------------------------------ the proxy asks

    def target(self, path: str) -> tuple[str, int, str] | None:
        """Where `/window-<id>/rest?query` goes: `(container, port, "/rest?query")`, the browser's container inside the stack's
        network with the window's own prefix taken off (the browser's page lives at its root), or `None` when no such window is
        open. Only the one open window's own path is ever answered."""
        with self._lock:
            self._expire()
            window = self._window
            if window is None or window.state not in ("waiting", "signed_in") or not path.startswith(window.path):
                return None
            return window.container, INTERNAL_PORT, "/" + path[len(window.path):]

    # ------------------------------------------------------------------ housekeeping

    def sweep(self) -> None:
        """Called every few seconds: a window that has been open too long is closed."""
        with self._lock:
            self._expire()

    def clean_leftovers(self) -> None:
        """At start: windows that an earlier run forgot."""
        for name in self._docker.leftovers():
            try:
                self._docker.remove(name)
            except DockerError:
                log.warning("could not remove %s", name)

    # ------------------------------------------------------------------ inside

    def _cookies(self, window: Window) -> str | None:
        """The browser's YouTube/Google cookies as a cookies.txt, or `None` when it has none that can be read yet."""
        try:
            database = self._docker.read_file(window.container, COOKIE_FILE)
            if database is None:
                return None
            wal = self._docker.read_file(window.container, COOKIE_FILE + "-wal")
            shm = self._docker.read_file(window.container, COOKIE_FILE + "-shm")
        except DockerError as error:
            log.info("could not read the window's cookies (%s)", error)
            return None
        return session_text(database, wal, shm)

    def _give_back(self, window: Window, status: int, message: str) -> tuple[int, dict]:
        """The sign-in could not be kept: give the person their window back (it was stopped to read it)."""
        try:
            self._docker.start(window.container)
        except DockerError:
            self._fail(window, "The sign-in window closed before it could be saved. Start it again.")
        return status, {"error": "not_signed_in" if status == 422 else "unreachable", "message": message}

    def _view(self, window: Window) -> dict:
        return {"window": window.id, "state": window.state, "message": window.message, "path": window.path,
                "ready": window.ready, "expiresAt": int(window.expires), "replace": window.replace}

    def _expire(self) -> None:
        window = self._window
        if window is not None and self._clock() >= window.expires:
            self._close(window)

    def _prepare(self, window: Window) -> None:
        try:
            if not self._docker.image_present():
                log.info("downloading the sign-in browser (first time only)")
                self._docker.pull()
            with self._lock:
                if self._window is not window:
                    return
                window.state = "starting"
            self._docker.create(window.container, network=self._network)
            self._docker.start(window.container)
            with self._lock:
                if self._window is window:
                    window.state = "waiting"
        except (DockerError, OSError) as error:
            log.warning("the sign-in window could not be started: %s", error)
            self._fail(window, "The sign-in window could not be started. Try again; if it keeps failing, see the server's log.")

    def _fail(self, window: Window, message: str) -> None:
        with self._lock:
            if self._window is window:
                window.state = "failed"
                window.message = message
        self._remove_container(window)
        # The failed window stays visible until the owner closes it, so the sentence can be read; it still expires.

    def _remove_container(self, window: Window) -> None:
        try:
            self._docker.remove(window.container)
        except DockerError:
            log.warning("could not remove %s", window.container)

    def _close(self, window: Window) -> None:
        with self._lock:
            if self._window is window:
                self._window = None
        self._remove_container(window)


def _probe_http(host: str, port: int) -> bool:
    """Whether the browser's page answers yet (it takes a few seconds after the container starts)."""
    import http.client
    try:
        connection = http.client.HTTPConnection(host, port, timeout=2)
        try:
            connection.request("HEAD", "/")
            return connection.getresponse().status < 500
        finally:
            connection.close()
    except OSError:
        return False
