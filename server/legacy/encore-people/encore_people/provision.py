"""Creating a person for an invitation, and looking after the accounts afterwards (their list, a new password): the proven account tool
(`encore_user.py`, docs/26) driven with the administrator's login.

Two kinds of server (the layout is read from the music server itself):

* **private** (`SHARED_LIBRARY_PATH` was set before the first start): the music server has a shared library beside one library per person;
  a new person gets their own folder and library plus the shared one, and sees nobody else's music.
* **shared** (the default, one music folder): everybody is given that one library; each person still has their own playlists, likes and
  play counts. No folder is made, so a person may be called anything that is a valid name.

The account tool is idempotent ("running it again repairs the libraries and keeps the account"), which is exactly wrong for a stranger's
chosen name: if the name already belongs to somebody, it would reconfigure THEIR account. So a taken name is refused here first, before the
tool is ever called, and so is a folder that already exists under that name (private layout).
"""
from __future__ import annotations

import importlib
import logging
import sys
import time
from typing import Callable
from datetime import datetime, timezone
from pathlib import Path

from .invites import ProvisionError
from .people import DirectoryUnavailable

log = logging.getLogger("encore_people.provision")

TAKEN = "That name is already taken. Choose another."
FAILED = "That account could not be set up on this server. Try another name; if it keeps failing, see the server's log."


def load_account_tool(extra_path: str | None = None):
    """`encore_user` from this image (copied next to the package) or from a path (tests use the reference kit's)."""
    if extra_path and extra_path not in sys.path:
        sys.path.insert(0, extra_path)
    return importlib.import_module("encore_user")


class NavidromeProvisioner:
    def __init__(self, base_url: str, admin_user: str, admin_password: str, music_dir: Path, *, music_root: str = "/music",
                 account_tool=None, clock: Callable[[], float] = time.monotonic) -> None:
        self._base = base_url
        self._user = admin_user
        self._password = admin_password
        self._music_dir = music_dir
        self._music_root = music_root
        self._tool = account_tool or load_account_tool()
        self._layout: tuple[float, str] | None = None
        self._clock = clock
        self._session: tuple[float, object] | None = None

    #: How long one administrator sign-in is used before the next one. The music server refuses a flood of sign-ins (HTTP 429 after a
    #: handful in a few seconds), and every look at the People page or every reset would have been one.
    SESSION_S = 600.0

    def _admin(self):
        now = self._clock()
        if self._session is not None and now - self._session[0] < self.SESSION_S:
            return self._session[1]
        try:
            admin = self._tool.Admin(self._base, self._user, self._password)
        except self._tool.ToolError as error:
            log.warning("could not sign in to the music server: %s", error)
            raise DirectoryUnavailable(str(error)) from None
        self._session = (now, admin)
        return admin

    def _run(self, work: Callable[[object], object]):
        """`work(admin)` with the shared sign-in; if the music server has dropped it (it ran out), sign in again once."""
        try:
            return work(self._admin())
        except self._tool.ToolError as error:
            if "HTTP 401" not in str(error) and "HTTP 403" not in str(error):
                raise
            self._session = None
            return work(self._admin())

    def _layout_of(self, admin) -> str:
        """`"private"` when the music server has a shared library beside per-person ones, else `"shared"`."""
        layout = "private" if any(self._tool.is_shared(lib.get("path", "")) for lib in admin.libraries()) else "shared"
        self._layout = (time.monotonic(), layout)
        return layout

    def layout(self) -> str:
        """What the owner is told about the libraries (looked at again at most once a minute)."""
        if self._layout is not None and time.monotonic() - self._layout[0] < 60:
            return self._layout[1]
        return self._run(self._layout_of)

    def add_person(self, username: str, password: str) -> None:
        self._run(lambda admin: self._add_person(admin, username, password))

    def _add_person(self, admin, username: str, password: str) -> None:
        if any(str(u.get("userName", "")).lower() == username.lower() for u in admin.users()):
            raise ProvisionError(TAKEN)
        if self._layout_of(admin) == "shared":
            self._add_to_shared(admin, username, password)
            return
        folder = self._music_dir / username
        if folder.exists():
            raise ProvisionError(TAKEN)
        try:
            result = self._tool.add_person(admin, username, music_root=self._music_root, shared=True, password=password,
                                           create_dir=str(self._music_dir))
        except self._tool.ToolError as error:
            log.warning("could not set up %s: %s", username, error)
            try:
                folder.rmdir()  # the tool makes the folder first; an empty one left behind would block the name for good
            except OSError:
                pass
            raise ProvisionError(FAILED) from None
        log.info("created %s with libraries %s", username, result.get("libraries"))

    def _add_to_shared(self, admin, username: str, password: str) -> None:
        try:
            made = admin.call("POST", "/api/user", {"userName": username, "name": username.capitalize(), "email": "",
                                                    "password": password, "isAdmin": False})
            ids = sorted(lib["id"] for lib in admin.libraries())
            admin.call("PUT", f"/api/user/{made['id']}/library", {"libraryIds": ids})
        except self._tool.ToolError as error:
            log.warning("could not set up %s: %s", username, error)
            raise ProvisionError(FAILED) from None
        log.info("created %s on a server where everybody shares one library", username)

    def listing(self) -> list[dict]:
        """Every account on the music server: `{"name", "admin", "lastAccess", "createdAt"}` (the times in seconds, `None` when unknown)."""
        return [{"name": u.get("userName", ""), "admin": bool(u.get("isAdmin")), "lastAccess": _epoch(u.get("lastAccessAt")),
                 "createdAt": _epoch(u.get("createdAt"))} for u in self._run(lambda admin: admin.users()) if u.get("userName")]

    def set_password(self, name: str, password: str) -> None:
        """Gives the account a new password through the music server's own user API, as its administrator."""
        self._run(lambda admin: self._set_password(admin, name, password))

    def _set_password(self, admin, name: str, password: str) -> None:
        user = next((u for u in admin.users() if str(u.get("userName", "")).lower() == name.lower()), None)
        if user is None:
            raise ProvisionError("There is nobody with that name.")
        admin.call("PUT", f"/api/user/{user['id']}", {
            "userName": user["userName"], "name": user.get("name") or user["userName"], "email": user.get("email") or "",
            "isAdmin": bool(user.get("isAdmin")), "password": password})
        log.info("a new password was set for %s", user["userName"])

    def remove_person(self, name: str) -> None:
        """Deletes the account (and its library entry). The folder and the music files are never deleted."""
        self._run(lambda admin: self._tool.remove_person(admin, name, delete_library=False))
        log.info("removed the account %s (their music was left where it is)", name)


def _epoch(value) -> float | None:
    """`2026-10-18T18:05:52.502475328Z` (the music server's time) as seconds since 1970; `None` when it is not a time."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
