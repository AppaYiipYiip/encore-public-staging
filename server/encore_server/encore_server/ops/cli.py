"""`python -m encore_server op ...`: the command door onto the operations (docs/36 section 1). `encore addon`, `encore reset-password` and `encore recovery-key` run this inside the Encore
container, so the Host's terminal and (where there is one) the admin page run the same function on the same database.

    python -m encore_server op addon list [--json]
    python -m encore_server op addon set ID STATE [--risk-version N] [--json]
    python -m encore_server op reset-password NAME --info          what the command must ask: owner-with-key | owner | member
    python -m encore_server op reset-password NAME                 {"password": "...", "recoveryKey": "..."} on standard input; never on the command line
    python -m encore_server op recovery-key [NAME]                 a new recovery key for an owner

The answer is a few readable lines on standard output (`--json`: the very JSON the admin route answers with; the password operations answer `name=value` lines, which the shell reads); a
refusal is the same sentence the page shows, on standard error, with exit status 1.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any, TextIO

from ..addons import AddOn
from ..config import Settings
from ..db import Database
from ..errors import ApiError
from ..host_settings import HostSettings
from ..navidrome_admin import NavidromeAdmin
from . import addon as ops_addon
from . import reset as ops_reset

USAGE = (
    "usage: op addon list [--json] | op addon set ID STATE [--risk-version N] [--json]"
    " | op reset-password NAME [--info] | op recovery-key [NAME]"
)


def line(item: dict[str, Any]) -> str:
    """One add-on as one readable line: its id, its state, and what stands in its way."""
    if item["planned"]:
        note = f" (not built yet: {item['planned']})"
    elif item["hostManaged"]:
        note = " (changed on the computer: encore funnel / autobackup)"
    else:
        note = ""
    wait = " (waits for a restart)" if item["restartNeeded"] else ""
    return f"{item['id']:<16} {item['state']:<6} {item['title']}{note}{wait}"


def command(
    argv: Sequence[str],
    *,
    settings: Settings | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    stdin: TextIO | None = None,
    admin: NavidromeAdmin | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    head = argv[0] if argv else ""
    if head not in ("addon", "reset-password", "recovery-key"):
        print(USAGE, file=err)
        return 2
    settings = settings or Settings.from_env()
    if not settings.db_path.exists():
        print("The server has not started yet, so there is nothing to change: start it first.", file=err)
        return 1
    db = Database(settings.db_path)
    if head == "addon":
        return _addon(argv, db, settings, as_json, out, err)
    the_admin = admin or NavidromeAdmin(settings.navidrome_url, settings.navidrome_admin_user, settings.navidrome_admin_password)
    try:
        if head == "reset-password":
            return _reset_password(argv, db, the_admin, stdin or sys.stdin, out, err)
        return _recovery_key(argv, db, out)
    except ApiError as refusal:
        print(refusal.message, file=err)
        return 1


def _reset_password(argv: Sequence[str], db: Database, admin: NavidromeAdmin, stdin: TextIO, out: TextIO, err: TextIO) -> int:
    rest = [a for a in argv[1:] if a != "--info"]
    if len(rest) != 1:
        print(USAGE, file=err)
        return 2
    if "--info" in argv:
        print(ops_reset.person_state(db, rest[0]), file=out)
        return 0
    try:
        details = json.loads(stdin.read() or "{}")
        if not isinstance(details, dict):
            raise ValueError
    except ValueError:
        print("Expected the new password as JSON on standard input.", file=err)
        return 2
    done = ops_reset.reset_password(db, admin, rest[0], details.get("password"), details.get("recoveryKey"))
    print(f"name={done['name']}", file=out)
    print(f"devicesEnded={done['devicesEnded']}", file=out)
    print(f"usedKey={'true' if done['usedKey'] else 'false'}", file=out)
    if done["recoveryKey"]:
        print(f"recovery-key={done['recoveryKey']}", file=out)
    return 0


def _recovery_key(argv: Sequence[str], db: Database, out: TextIO) -> int:
    made = ops_reset.new_recovery_key(db, argv[1] if len(argv) > 1 else None)
    print(f"name={made['name']}", file=out)
    print(f"recovery-key={made['recoveryKey']}", file=out)
    return 0


def _addon(argv: Sequence[str], db: Database, settings: Settings, as_json: bool, out: TextIO, err: TextIO) -> int:
    if len(argv) < 2 or argv[1] not in ("list", "set"):
        print(USAGE, file=err)
        return 2
    store = HostSettings(db)
    try:
        boot = store.boot_states()
    except Exception:  # noqa: BLE001 - a database from before the table: the server has not been started since it was added
        print("The server has not started since this version was installed: start it first.", file=err)
        return 1

    def running_of(addon: AddOn) -> str:
        return boot.get(addon.id) or addon.running(settings)

    try:
        if argv[1] == "list":
            found = ops_addon.list_addons(db, running_of)
            print(json.dumps({"items": found}) if as_json else "\n".join(line(i) for i in found), file=out)
            return 0
        if len(argv) < 4:
            print(USAGE, file=err)
            return 2
        version: object = None
        if "--risk-version" in argv:
            at = argv.index("--risk-version")
            version = int(argv[at + 1]) if at + 1 < len(argv) and argv[at + 1].isdigit() else None
        item = ops_addon.set_state(db, running_of, argv[2], argv[3], by="command", risk_text_version=version)
        if as_json:
            print(json.dumps({"addon": item}), file=out)
        else:
            print(
                line(item)
                + ("  (it takes effect when the server restarts: sudo encore restart)" if item["restartNeeded"] else ""),
                file=out,
            )
        return 0
    except ApiError as refusal:
        print(refusal.message, file=err)
        return 1
