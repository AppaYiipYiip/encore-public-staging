"""The music server's own account API, driven as its administrator (the installer made one for the Encore server).

Passwords live only in the music server (docs/21 section 4): this module hands one over when an account is made or changed and keeps
nothing. A person is a Navidrome user who may use the one shared library; their likes, playlists and history are the Encore server's.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from .errors import ApiError

log = logging.getLogger("encore_server.navidrome_admin")

#: How long one sign-in as the administrator is used (the music server answers a flood of sign-ins with 429).
SESSION_S = 600.0


def post_login(
    client: httpx.Client, base_url: str, user: str, password: str, *, sleep: Callable[[float], None] = time.sleep, tries: int = 4
) -> httpx.Response:
    """Asks the music server to sign [user] in. It answers 429 when it has been asked too often (it counts every sign-in from this computer
    together, five in twenty seconds): wait the few seconds it asks for and ask again, instead of taking the refusal for a wrong password."""
    url = f"{base_url.rstrip('/')}/auth/login"
    response = client.post(url, json={"username": user, "password": password})
    for _ in range(max(0, tries - 1)):
        if response.status_code != 429:
            break
        try:
            wait = float(response.headers.get("Retry-After", ""))
        except ValueError:
            wait = 6.0
        sleep(min(max(wait, 0.0), 20.0))
        response = client.post(url, json={"username": user, "password": password})
    return response


class AdminUnavailable(ApiError):
    def __init__(self, message: str = "This server cannot add or change people right now.") -> None:
        super().__init__("server_busy", message)


class NameTaken(Exception):
    """The music server already has an account with that name."""


class NavidromeAdmin:
    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._sleep = sleep
        self._base = base_url.rstrip("/")
        self._user = user
        self._password = password
        self._client = client or httpx.Client(timeout=15.0)
        self._clock = clock
        self._lock = threading.Lock()
        self._session: tuple[float, str] | None = None

    @property
    def configured(self) -> bool:
        return bool(self._user and self._password)

    # ------------------------------------------------------------------ the sign-in

    def _token(self, *, fresh: bool = False) -> str:
        with self._lock:
            now = self._clock()
            if not fresh and self._session is not None and now - self._session[0] < SESSION_S:
                return self._session[1]
            try:
                response = post_login(self._client, self._base, self._user, self._password, sleep=self._sleep)
            except httpx.HTTPError as error:
                raise AdminUnavailable("The music server is not answering.") from error
            if response.status_code != 200:
                log.warning("the music server refused the Encore server's own account (HTTP %s)", response.status_code)
                raise AdminUnavailable("The music server did not accept this server's own account.")
            token = str(response.json().get("token") or "")
            if not token:
                raise AdminUnavailable()
            self._session = (now, token)
            return token

    def call(self, method: str, route: str, body: dict[str, Any] | None = None) -> Any:
        """One call to the music server's account API; a dropped sign-in is renewed once."""
        for fresh in (False, True):
            try:
                response = self._client.request(
                    method,
                    f"{self._base}{route}",
                    json=body,
                    headers={"X-ND-Authorization": f"Bearer {self._token(fresh=fresh)}"},
                )
            except httpx.HTTPError as error:
                raise AdminUnavailable("The music server is not answering.") from error
            if response.status_code in (401, 403) and not fresh:
                continue
            if response.status_code >= 400:
                log.info("the music server refused %s %s (HTTP %s)", method, route, response.status_code)
                raise AdminUnavailable(f"The music server could not do that (HTTP {response.status_code}).")
            return response.json() if response.content else {}
        raise AdminUnavailable()  # pragma: no cover - the loop always returns or raises

    # ------------------------------------------------------------------ people

    def users(self) -> list[dict[str, Any]]:
        found = self.call("GET", "/api/user?_start=0&_end=1000")
        return [u for u in found if isinstance(u, dict)] if isinstance(found, list) else []

    def find(self, username: str) -> dict[str, Any] | None:
        wanted = username.strip().lower()
        return next((u for u in self.users() if str(u.get("userName", "")).lower() == wanted), None)

    def libraries(self) -> list[int]:
        found = self.call("GET", "/api/library")
        return sorted(int(lib["id"]) for lib in found if isinstance(lib, dict) and "id" in lib) if isinstance(found, list) else []

    def create_user(self, username: str, display_name: str, password: str) -> str:
        """Makes an ordinary account that may use every library; returns its id. [NameTaken] when the name is in use."""
        if self.find(username) is not None:
            raise NameTaken(username)
        made = self.call(
            "POST", "/api/user", {"userName": username, "name": display_name, "email": "", "password": password, "isAdmin": False}
        )
        user_id = str(made.get("id") or "")
        if not user_id:
            raise AdminUnavailable()
        libraries = self.libraries()
        if libraries:
            self.call("PUT", f"/api/user/{user_id}/library", {"libraryIds": libraries})
        return user_id

    def give_libraries(self, usernames: list[str]) -> int:
        """Lets the named accounts use every library when they have none (made by hand, or before the first scan made a library); returns how many were fixed."""
        wanted = {name.lower() for name in usernames}
        libraries = self.libraries()
        fixed = 0
        for user in self.users() if libraries else []:
            if user.get("isAdmin") or user.get("libraries") or str(user.get("userName", "")).lower() not in wanted:
                continue
            self.call("PUT", f"/api/user/{user['id']}/library", {"libraryIds": libraries})
            fixed += 1
        return fixed

    def set_password(self, username: str, password: str) -> None:
        user = self.find(username)
        if user is None:
            raise ApiError("not_found", "There is nobody with that name.")
        self.call(
            "PUT",
            f"/api/user/{user['id']}",
            {
                "userName": user["userName"],
                "name": user.get("name") or user["userName"],
                "email": user.get("email") or "",
                "isAdmin": bool(user.get("isAdmin")),
                "password": password,
            },
        )

    def delete_user(self, username: str) -> None:
        user = self.find(username)
        if user is not None:
            self.call("DELETE", f"/api/user/{user['id']}")
