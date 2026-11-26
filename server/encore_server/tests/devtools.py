"""A small Chrome DevTools client: runs a page in a headless Chromium-family browser (Chrome, Edge, Brave, Chromium) so that the admin pages' own JavaScript is tested as
it runs. It needs no package beyond `websockets`, which the server already uses. Tests skip when no such browser is installed (`ENCORE_BROWSER` names one)."""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from websockets.sync.client import connect

WINDOWS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
]
NAMES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
    "msedge",
    "microsoft-edge",
    "brave",
    "brave-browser",
]


def find_browser() -> str | None:
    chosen = os.environ.get("ENCORE_BROWSER")
    if chosen and Path(chosen).exists():
        return chosen
    for name in NAMES:
        found = shutil.which(name)
        if found:
            return found
    return next((p for p in WINDOWS if Path(p).exists()), None)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Browser:
    def __init__(self, executable: str, size: tuple[int, int] = (1180, 800)) -> None:
        self.executable = executable
        self.size = size
        self.logs: list[str] = []
        self._id = 0
        self.port = free_port()
        self.profile = tempfile.mkdtemp(prefix="encore-browser-")

    def __enter__(self) -> Browser:
        flags = [
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
        ]
        if os.environ.get("CI"):
            flags.append("--no-sandbox")  # a container's user may not be allowed the sandbox
        self.proc = subprocess.Popen(
            [
                self.executable,
                *flags,
                f"--user-data-dir={self.profile}",
                f"--remote-debugging-port={self.port}",
                f"--window-size={self.size[0]},{self.size[1]}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        target: dict[str, Any] | None = None
        for _ in range(80):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=2))
                target = next(p for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.25)
        assert target is not None, "the browser did not start"
        self.ws = connect(target["webSocketDebuggerUrl"], max_size=50_000_000)
        for method in ("Page.enable", "Runtime.enable", "Log.enable"):
            self.call(method)
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            self.ws.close()
        finally:
            self.proc.kill()
            shutil.rmtree(self.profile, ignore_errors=True)

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        self._id += 1
        mine = self._id
        self.ws.send(json.dumps({"id": mine, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv(timeout=30))
            self._note(message)
            if message.get("id") == mine:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return dict(message.get("result", {}))

    def _note(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method == "Log.entryAdded":
            entry = message["params"]["entry"]
            self.logs.append(f"[{entry.get('level')}] {entry.get('text')} {entry.get('url', '')}")
        elif method == "Runtime.consoleAPICalled":
            args = " ".join(str(a.get("value", a.get("description", ""))) for a in message["params"]["args"])
            self.logs.append(f"[console.{message['params']['type']}] {args}")
        elif method == "Runtime.exceptionThrown":
            details = message["params"]["exceptionDetails"]
            self.logs.append(f"[exception] {details.get('text')} {details.get('exception', {}).get('description', '')}")

    def pump(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            try:
                self._note(json.loads(self.ws.recv(timeout=max(0.05, end - time.time()))))
            except TimeoutError:
                break

    def go(self, url: str) -> None:
        self.call("Page.navigate", url=url)
        self.wait("document.readyState === 'complete'")

    def js(self, expression: str) -> Any:
        result = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(
                f"in the page: {result['exceptionDetails'].get('exception', {}).get('description', result['exceptionDetails'])}"
            )
        return result.get("result", {}).get("value")

    def wait(self, condition: str, seconds: float = 10.0) -> None:
        """Waits until the JavaScript [condition] is true in the page; says what the page showed when it never is."""
        end = time.time() + seconds
        while time.time() < end:
            if self.js(f"Boolean({condition})"):
                return
            self.pump(0.1)
        raise AssertionError(
            f"the page never reached: {condition}\nit showed: {self.js('document.body.innerText')[:600]!r}\nlog: {self.logs[-5:]}"
        )

    def text(self, selector: str = "body") -> str:
        return str(self.js(f"(document.querySelector({json.dumps(selector)}) || {{innerText: ''}}).innerText"))

    def click(self, selector: str, containing: str | None = None) -> None:
        pick = f"[...document.querySelectorAll({json.dumps(selector)})].find(e => e.innerText.toLowerCase().includes({json.dumps((containing or '').lower())}))"
        self.wait(pick)
        self.js(f"{pick}.click()")

    def shot(self, path: str) -> None:
        Path(path).write_bytes(base64.b64decode(self.call("Page.captureScreenshot", format="png")["data"]))
