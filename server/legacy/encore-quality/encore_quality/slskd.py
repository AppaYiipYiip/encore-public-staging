"""What the quality tier asks of slskd, the program that is on the Soulseek network. It is **off until the owner switches it on**: slskd is
started without connecting (`SLSKD_NO_CONNECT`) and this service connects it, or disconnects it, to match the owner's choice.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .textnorm import norm_album

#: `(method, path below /api/v0, json body or None) -> (status, parsed JSON or None)`; status 0: not reachable. The tests give a fake.
Http = Callable[[str, str, Any], "tuple[int, Any]"]


def http_for(base_url: str, api_key: str, timeout: float = 30.0) -> Http:
    base = base_url.rstrip("/") + "/api/v0"

    def call(method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(base + path, data=data, method=method, headers={
            "X-API-Key": api_key, "User-Agent": "encore-quality/1", **({"Content-Type": "application/json"} if data is not None else {})})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - the stack's own network
                raw, status = response.read(8_000_000), response.status
        except urllib.error.HTTPError as error:
            raw, status = error.read(200_000), error.code
        except (urllib.error.URLError, OSError, TimeoutError):
            return 0, None
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, None

    return call


class Slskd:
    def __init__(self, http: Http) -> None:
        self._http = http

    def state(self) -> dict | None:
        """`{"up": True, "connected": bool, "loggedIn": bool, "version": str}`, or `None` when slskd does not answer."""
        status, data = self._http("GET", "/application", None)
        if status != 200 or not isinstance(data, dict):
            return None
        server = data.get("server") or {}
        version = data.get("version") or {}
        return {"up": True, "connected": bool(server.get("isConnected")), "loggedIn": bool(server.get("isLoggedIn")),
                "version": str(version.get("current") or "")}

    def connect(self) -> bool:
        status, _ = self._http("PUT", "/server", None)
        return status == 200

    def disconnect(self) -> bool:
        status, _ = self._http("DELETE", "/server", None)
        return status == 200

    def shares(self) -> int | None:
        """How many files are shared with the network (nothing by default: a download folder is not a share), or `None`."""
        status, data = self._http("GET", "/shares", None)
        if status != 200 or not isinstance(data, dict):
            return None
        return sum(int(share.get("files") or 0) for share in data.get("local") or [] if isinstance(share, dict))

    def downloading(self, album: str) -> bool:
        """Whether peers are sending (or about to send) a folder that looks like [album]."""
        status, data = self._http("GET", "/transfers/downloads", None)
        wanted = norm_album(album)
        if status != 200 or not isinstance(data, list) or not wanted:
            return False
        for user in data:
            for directory in (user or {}).get("directories") or []:
                folder = str((directory or {}).get("directory") or "").replace("\\", "/").rsplit("/", 1)[-1]
                if wanted not in norm_album(folder):
                    continue
                for file in directory.get("files") or []:
                    if any(word in str(file.get("state") or "") for word in ("InProgress", "Queued", "Requested", "Initializing")):
                        return True
        return False

    def search_answers(self, text: str, wait_s: float = 12.0, *, sleep: Callable[[float], None] = time.sleep) -> int | None:
        """How many peers answer a harmless search: proof that the network can be reached. Nothing is downloaded."""
        status, data = self._http("POST", "/searches", {"searchText": text, "searchTimeout": int(wait_s * 1000), "responseLimit": 20,
                                                          "fileLimit": 200})
        if status not in (200, 201) or not isinstance(data, dict) or not data.get("id"):
            return None
        search_id = data["id"]
        deadline = time.monotonic() + wait_s + 8
        while time.monotonic() < deadline:
            status, found = self._http("GET", f"/searches/{search_id}", None)
            if status == 200 and isinstance(found, dict) and found.get("isComplete"):
                break
            sleep(1.5)
        status, responses = self._http("GET", f"/searches/{search_id}/responses", None)
        self._http("DELETE", f"/searches/{search_id}", None)
        return len(responses) if status == 200 and isinstance(responses, list) else None
