"""Who may change how the server behaves (the YouTube login): the owner, as the people service knows it.

The people service holds the roles (owner, inviter, guest); the music server's administrators are owners there. This asks
it, over the services' own network, with the person's own music login. When the people service is not there (a server
without it) a music-server administrator counts.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Callable

from .navidrome import Auth, Navidrome

log = logging.getLogger("encore_fetch.owners")


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "encore-fetch/1"})
    with urllib.request.urlopen(request, timeout=6) as response:  # noqa: S310 - the service's own network
        return json.loads(response.read(200_000))


class OwnerCheck:
    def __init__(self, people_url: str | None, navidrome: Navidrome,
                 http: Callable[[str], dict] = _get_json) -> None:
        self._people = (people_url or "").rstrip("/") or None
        self._nd = navidrome
        self._http = http

    def __call__(self, auth: Auth) -> bool:
        if self._people:
            try:
                answer = self._http(f"{self._people}/api/me?{urllib.parse.urlencode(auth.params())}")
                return answer.get("canManage") is True
            except Exception as error:  # noqa: BLE001 - the people service not answering is not "no"
                log.info("the people service did not answer (%s); asking the music server", type(error).__name__)
        return self._nd.is_admin(auth)
