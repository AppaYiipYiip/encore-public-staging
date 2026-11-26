"""`python -m encore_server op ...`: the command door onto the operations (docs/36 section 1). `encore addon` runs this inside the Encore container, so the Host's terminal and the
admin page run the same function on the same database.

    python -m encore_server op addon list [--json]
    python -m encore_server op addon set ID STATE [--risk-version N] [--json]

The answer is a few readable lines on standard output (`--json`: the very JSON the admin route answers with); a refusal is the same sentence the page shows, on standard
error, with exit status 1.
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
from . import addon as ops_addon

USAGE = "usage: op addon list [--json] | op addon set ID STATE [--risk-version N] [--json]"


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
    argv: Sequence[str], *, settings: Settings | None = None, out: TextIO | None = None, err: TextIO | None = None
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if len(argv) < 2 or argv[0] != "addon" or argv[1] not in ("list", "set"):
        print(USAGE, file=err)
        return 2
    settings = settings or Settings.from_env()
    if not settings.db_path.exists():
        print("The server has not started yet, so there is nothing to change: start it first.", file=err)
        return 1
    db = Database(settings.db_path)
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
