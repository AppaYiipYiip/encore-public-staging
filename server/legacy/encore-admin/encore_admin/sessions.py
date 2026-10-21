"""Who is signed in to the website, in memory only (ADR-101: a login is never written down).

A session holds the owner's music login as the music server's token form (`user`, `token`, `salt`), not the password, so the
website can ask the other services for things as the owner. It lives in memory: restarting the website signs everybody out.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class Session:
    user: str
    token: str
    salt: str
    expires: float


class Sessions:
    def __init__(self, hours: float = 8.0, clock: Callable[[], float] = time.time) -> None:
        self._ttl = hours * 3600.0
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def create(self, user: str, token: str, salt: str) -> str:
        key = secrets.token_hex(24)
        with self._lock:
            self._sweep()
            self._sessions[key] = Session(user, token, salt, self._clock() + self._ttl)
        return key

    def get(self, key: str | None) -> Session | None:
        """The session behind a cookie, kept alive by use (sliding), or `None`."""
        if not key:
            return None
        with self._lock:
            found = self._sessions.get(key)
            if found is None:
                return None
            now = self._clock()
            if found.expires < now:
                del self._sessions[key]
                return None
            found.expires = now + self._ttl
            return found

    def drop(self, key: str | None) -> None:
        with self._lock:
            self._sessions.pop(key or "", None)

    def _sweep(self) -> None:
        now = self._clock()
        for key in [k for k, v in self._sessions.items() if v.expires < now]:
            del self._sessions[key]


class Throttle:
    """Five wrong tries from one address in ten minutes lock that address for ten minutes."""

    def __init__(self, tries: int = 5, window_s: float = 600.0, clock: Callable[[], float] = time.time) -> None:
        self._tries = tries
        self._window = window_s
        self._clock = clock
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    def allowed(self, who: str) -> bool:
        with self._lock:
            return len(self._recent(who)) < self._tries

    def failed(self, who: str) -> None:
        with self._lock:
            self._recent(who).append(self._clock())

    def succeeded(self, who: str) -> None:
        with self._lock:
            self._fails.pop(who, None)

    def _recent(self, who: str) -> list[float]:
        horizon = self._clock() - self._window
        kept = [t for t in self._fails.get(who, []) if t >= horizon]
        self._fails[who] = kept
        return kept
