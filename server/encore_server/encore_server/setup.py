"""`python -m encore_server setup`: the steps of a first install that live inside the music server (docs/tasks P3-05).

The installer starts the two containers and then runs this inside the Encore one, with the owner's choices on standard input (never on
the command line, where `ps` and shell history would show a password). It makes, once:

* the music server's own administrator for the Encore server (the name and the generated password are in the install's `.env`), which the
  server uses to scan the library and to make accounts for the people the owner invites; and
* the owner's account, an ordinary account that nobody else knows the password of. The first person to sign in on a new server is its owner.

Running it again is safe: what exists is left as it is and said so. Nothing here prints or logs a password.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TextIO

import httpx

from .accounts import clean_password, clean_username
from .config import Settings
from .errors import ApiError
from .navidrome_admin import AdminUnavailable, NameTaken, NavidromeAdmin

log = logging.getLogger("encore_server.setup")


class SetupError(Exception):
    """A step of the first install that cannot go on. The message is a sentence for the person running the installer."""


@dataclass(frozen=True)
class SetupResult:
    #: "created" or "existing", for the Encore server's own account in the music server and for the owner's.
    administrator: str
    owner: str


def wait_for_music_server(
    base_url: str,
    *,
    seconds: float = 120.0,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Returns once the music server answers `/ping`; a sentence ([SetupError]) when it does not within [seconds]."""
    http = client or httpx.Client(timeout=5.0)
    end = clock() + seconds
    while True:
        try:
            if http.get(f"{base_url.rstrip('/')}/ping").status_code == 200:
                return
        except httpx.HTTPError as error:
            log.debug("the music server is not up yet: %s", type(error).__name__)
        if clock() >= end:
            raise SetupError("The music server did not start in time. Run `encore logs` to see why.")
        sleep(2.0)


def ensure_administrator(base_url: str, user: str, password: str, *, client: httpx.Client) -> str:
    """The music server's first account is its administrator, made by one call while it has no accounts at all (the call is refused after
    that). `"existing"` when this account already signs in; [SetupError] when the music server has other accounts and refuses this one."""
    base = base_url.rstrip("/")
    try:
        if client.post(f"{base}/auth/login", json={"username": user, "password": password}).status_code == 200:
            return "existing"
        made = client.post(f"{base}/auth/createAdmin", json={"username": user, "password": password})
    except httpx.HTTPError as error:
        raise SetupError("The music server is not answering.") from error
    if made.status_code in (200, 201):
        return "created"
    raise SetupError(
        "The music server already has accounts, and it does not accept the account this install made for it. "
        "This happens when an older install left its data behind: run `encore uninstall --everything` and install again."
    )


def run_setup(settings: Settings, owner: dict[str, Any], *, client: httpx.Client | None = None, wait: bool = True) -> SetupResult:
    """Makes the music server's administrator and the owner's account; see the module's text. [SetupError] says what to do when it cannot."""
    try:
        username = clean_username(owner.get("username"))
        password = clean_password(owner.get("password"), username)
    except ApiError as error:
        raise SetupError(error.message) from error
    shown = owner.get("name")
    display = shown.strip() if isinstance(shown, str) and shown.strip() else username
    if not (settings.navidrome_admin_user and settings.navidrome_admin_password):
        raise SetupError(
            "This install has no account for the music server (ENCORE_NAVIDROME_ADMIN_USER and _PASSWORD are not set)."
        )

    http = client or httpx.Client(timeout=15.0)
    if wait:
        wait_for_music_server(settings.navidrome_url, client=http)
    administrator = ensure_administrator(
        settings.navidrome_url, settings.navidrome_admin_user, settings.navidrome_admin_password, client=http
    )

    admin = NavidromeAdmin(settings.navidrome_url, settings.navidrome_admin_user, settings.navidrome_admin_password, client=http)
    try:
        admin.create_user(username, display, password)
        made = "created"
    except NameTaken:
        made = "existing"
    except AdminUnavailable as error:
        raise SetupError(error.message) from error
    return SetupResult(administrator=administrator, owner=made)


def command(
    stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr, settings: Settings | None = None
) -> int:
    """`setup` on the command line: the owner as JSON on [stdin] (`username`, `password`, optional `name`). 0 when done, 2 for a sentence."""
    try:
        owner = json.loads(stdin.read() or "{}")
        if not isinstance(owner, dict):
            raise ValueError
    except ValueError:
        stderr.write("setup: expected the owner's details as JSON on standard input.\n")
        return 2
    try:
        result = run_setup(settings or Settings.from_env(), owner)
    except SetupError as error:
        stderr.write(f"setup: {error}\n")
        return 2
    stdout.write(f"administrator={result.administrator}\nowner={result.owner}\n")
    return 0
