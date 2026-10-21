"""The other parts of the stack, asked what they can do, so the app gets ONE answer for the whole server (docs/45c item 1).

Each part already answers a public `GET /api/info` with a `features` list (the app hides what is missing, ADR-052). This asks them
together, gives each a short time, remembers the answer for a few seconds (a crowd of phones must not become a crowd of questions)
and keeps only plain feature names and the few facts a stranger may see: nothing about accounts, nothing secret.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

#: `(url, timeout seconds) -> parsed JSON or None`; the tests give a fake.
Get = Callable[[str, float], object]

_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}")


def http_get(url: str, timeout: float) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "encore-people/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - the stack's own network
            raw = response.read(200_000)
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and _NAME.fullmatch(v)]


def _version(text: object) -> str | None:
    """`0.64.2 (abc123)` -> `0.64.2`."""
    if not isinstance(text, str):
        return None
    found = re.match(r"v?(\d+(?:\.\d+){0,3})", text.strip())
    return found.group(1) if found else None


class Parts:
    #: How long what was learned is used again.
    FRESH_S = 20.0
    #: How long one part is given to answer.
    WAIT_S = 2.0
    #: The music server's own public ping (what every music app calls first): it answers without a login, says it is Navidrome and
    #: which version (the answer is "failed" for want of a login, which is exactly "it is there"). Its plain `/ping` answers a dot.
    MUSIC_PATH = "/rest/ping.view?f=json&v=1.16.1&c=encore-people"

    def __init__(self, *, music_url: str | None, fetch_url: str | None, hub_url: str | None, quality_url: str | None = None,
                 recs_url: str | None = None, get: Get = http_get, clock: Callable[[], float] = time.monotonic) -> None:
        self._urls = {"music": f"{music_url.rstrip('/')}{self.MUSIC_PATH}" if music_url else None,
                      "fetch": f"{fetch_url.rstrip('/')}/api/info" if fetch_url else None,
                      "hub": f"{hub_url.rstrip('/')}/api/info" if hub_url else None,
                      "quality": f"{quality_url.rstrip('/')}/api/info" if quality_url else None,
                      "recs": f"{recs_url.rstrip('/')}/api/info" if recs_url else None}
        self._get = get
        self._clock = clock
        self._seen: tuple[float, dict[str, dict]] | None = None
        self._lock = threading.Lock()

    def look(self) -> dict[str, dict]:
        """`{"music": {"up", "version"}, "fetch": {"up", "features", "youtubeSignedIn"}, "hub"|"quality"|"recs": {"up", "features"}}` for the parts this
        server was given; a part that was not given is not mentioned (it is not "down", it is not part of this server)."""
        with self._lock:
            now = self._clock()
            if self._seen is not None and now - self._seen[0] < self.FRESH_S:
                return self._seen[1]
            asking = {name: url for name, url in self._urls.items() if url}
            with ThreadPoolExecutor(max_workers=max(1, len(asking))) as pool:
                futures = {name: pool.submit(self._ask, url) for name, url in asking.items()}
                answers = {name: future.result() for name, future in futures.items()}
            looked = {name: self._shape(name, answer) for name, answer in answers.items()}
            self._seen = (now, looked)
            return looked

    def _ask(self, url: str) -> object:
        try:
            return self._get(url, self.WAIT_S)
        except Exception:  # noqa: BLE001 - a part that fails to answer is simply not up
            return None

    @staticmethod
    def _shape(name: str, answer: object) -> dict:
        if not isinstance(answer, dict):
            return {"up": False}
        if name == "music":
            reply = answer.get("subsonic-response")
            if not isinstance(reply, dict):
                return {"up": False}
            version = _version(reply.get("serverVersion"))
            return {"up": True, **({"version": version} if version else {})}
        shaped: dict = {"up": True, "features": _names(answer.get("features"))}
        if name == "fetch":
            shaped["youtubeSignedIn"] = answer.get("youtubeSignedIn") is True
        return shaped
