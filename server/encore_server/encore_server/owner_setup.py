"""Making the owner in the browser (docs/36 section 2, "The first run is a takeover risk"): the one place where a server with no people gets its first one.

The rules, each of them proved by a test:

* The step is open only while **a setup code is configured and no person exists**. The check is made on every call, not at start: once the owner exists, the first-run routes
  answer 404 for ever, whatever `.env` still says.
* The whole step runs under **one lock**, and its last part is one write transaction that checks again that nobody exists and makes the owner in the same breath: two browsers that
  post at the same moment (the one who holds the code and anybody who watched it go by) make ONE owner; the loser is told the server is already set up.
* The music server's account is made first (the same function the command door uses, `setup.run_setup`), so a half-made install is finished by trying again with the same name and
  password; nothing is ever made twice.
* The owner's **recovery key** (`recovery.py`) is made in that same transaction and returned once in the answer; only its hash is kept.
* What comes back is a **browser session** (a device of kind `web`, which the server ends after 12 hours unused), exactly what signing in would have made.
* When the owner exists, a marker file (`setup-complete`) is left in the data folder: the `encore` command on the computer sees it and takes the code out of `.env` (the server cannot
  write that file, and ignores the line once a person exists, so a line that lingers is harmless).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from . import library, recovery
from .accounts import clean_password, clean_username
from .auth import issue_device
from .errors import ApiError
from .routes.common import Services
from .setup import SetupError

log = logging.getLogger("encore_server.setup")

#: One owner is made by one request at a time (the server is one process; the transaction below also holds across processes).
_LOCK = threading.Lock()

MARKER = "setup-complete"
DEVICE_NAME = "Browser (first setup)"


def is_open(svc: Services) -> bool:
    """Does this server take its first owner right now: a well formed setup code is configured and nobody exists yet."""
    if not svc.settings.setup_code:
        return False
    with svc.db.read() as conn:
        return conn.execute("SELECT 1 FROM person LIMIT 1").fetchone() is None


def create_owner(svc: Services, body: dict[str, Any]) -> dict[str, Any]:
    """Makes the owner and a browser session for them. [ApiError] says what is wrong, in words a person can act on."""
    if svc.make_owner_account is None:
        raise ApiError("server_busy", "This server cannot make accounts yet. Try again in a minute.")
    # What a person typed is checked before anything is made: the same rules as an invitation's (`accounts.clean_username`, `clean_password`), in the same sentences.
    username = clean_username(body.get("username"))
    password = clean_password(body.get("password"), username)
    shown = body.get("name")
    display = shown.strip() if isinstance(shown, str) and shown.strip() else username
    with _LOCK:
        if not is_open(svc):
            raise ApiError("not_found")
        try:
            svc.make_owner_account(svc.settings, {"username": username, "password": password, "name": display})
        except SetupError as error:
            # The sentences of the setup command are plain words that say what to do, so the page shows them as they are.
            raise ApiError("validation", str(error)) from error
        with svc.db.tx() as conn:
            if conn.execute("SELECT 1 FROM person LIMIT 1").fetchone() is not None:
                raise ApiError("not_found")
            person = library.ensure_person(conn, username, admin=True)
            conn.execute("UPDATE person SET display_name = ? WHERE id = ?", (display[:80], person["id"]))
            device_id, token = issue_device(conn, person["id"], DEVICE_NAME, "web", None)
            # The recovery key is made in the same breath (docs/36 section 6): shown once, in this answer, and kept only as a hash. An owner is never made without one.
            key = recovery.store(conn, person["id"])
            answer = {
                "deviceToken": token,
                "device": {"id": device_id, "name": DEVICE_NAME},
                "person": {"id": person["id"], "name": display[:80], "role": "owner"},
                "recoveryKey": key,
            }
        _leave_marker(svc)
        log.info("the owner of this server was made in the browser")
        return answer


def _leave_marker(svc: Services) -> None:
    try:
        (svc.settings.data_dir / MARKER).write_text("done\n", encoding="utf-8")
    except OSError as error:
        # Not fatal: the server ignores the code once a person exists; the marker only lets the command door tidy `.env`.
        log.warning("could not leave the setup marker: %s", type(error).__name__)
