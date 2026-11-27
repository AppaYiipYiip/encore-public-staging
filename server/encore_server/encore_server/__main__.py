"""`python -m encore_server`: runs the server (the container's command); `python -m encore_server setup` does the first-install steps;
`python -m encore_server backup` copies the databases (`encore backup` uses it); any other word prints the commands and exits (B-57)."""

from __future__ import annotations

import logging
import sys

import uvicorn

from . import textnorm
from .api import create_app
from .config import Settings
from .db import MigrationFailed
from .request_id import RequestIdFilter
from .sources.youtube.tools import ToolStore, activate
from .stopping import UVICORN_GRACE_S


def configure_logging(level: str) -> None:
    # `%(rid)s` is ` [<request id>]` while a request is handled (P1-19: a failure is followed from the phone to this log by that id), nothing otherwise.
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s%(rid)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(RequestIdFilter())
    # The music server is asked with the person's login token in the address, and httpx logs every address at INFO: that would put
    # a value anyone could guess the password from (token = md5 of password and salt) into the log. Warnings and errors only.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


USAGE = """usage: python -m encore_server [command]

  (no command)   run the server (what the container does)
  setup          the first-install steps (reads its details from standard input); `setup --administrator-only` makes only the music server's own account
  backup         copy the databases (`encore backup` uses it)
  op             a Host's operation, the command door (`encore addon` uses it)
"""


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    # Only NO word runs the server. A word this program does not know (`--help`, `restore`, a typo) used to fall through to it: typed in the
    # container of a live install it ran the migrations and the scheduler on the live database before failing to bind the port (AUDIT B-57).
    if args[:1] in (["--help"], ["-h"], ["help"]):
        sys.stdout.write(USAGE)
        raise SystemExit(0)
    if args and args[0] not in ("setup", "backup", "op"):
        sys.stderr.write(f"encore_server: do not understand {args[0]!r}\n\n{USAGE}")
        raise SystemExit(2)
    if args[:1] == ["setup"]:
        from .setup import command

        raise SystemExit(command(administrator_only=args[1:] == ["--administrator-only"]))
    if args[:1] == ["op"]:
        from .ops.cli import command as op_command

        raise SystemExit(op_command(args[1:]))
    if args[:1] == ["backup"]:
        from .backup import command as backup_command

        raise SystemExit(backup_command(args[1:]))
    try:
        # Before the settings, the tools folder or a database: a Python whose Unicode is not the pin does not start the server, and says which Python to use (P2-25).
        textnorm.require_pinned_unicode()
    except textnorm.UnicodeVersionError as refusal:
        sys.stderr.write(f"encore_server: {refusal}\n")
        raise SystemExit(1) from None
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    # A newer yt-dlp the server fetched and checked earlier (docs/11 ADR-R39) must be first on the import path before anything imports yt_dlp.
    active = activate(ToolStore(settings.data_dir / "tools" / "yt-dlp")) if settings.auto_tools and settings.youtube else None
    try:
        app = create_app(settings, tools_active=active)
    except MigrationFailed as refusal:
        # A server that must not start on its data says why in one sentence (what `encore logs` shows), not in a stack trace.
        sys.stderr.write(f"encore_server: {refusal}\n")
        raise SystemExit(1) from None
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
        # `docker stop` (so `encore update` and `encore stop`) kills the container ten seconds after SIGTERM. Uvicorn waits for every running request
        # on a stop and, with no limit of its own, was killed in the middle of its shutdown (exit code 137, AUDIT B-129). The live connections end at
        # once now (api.live); this is the bound for whatever else holds a stop, such as a long stream. The whole stop is bounded by stopping.py:
        # this grace + the lifespan's one shared budget, worst case 8.8 s of Docker's 10.
        timeout_graceful_shutdown=int(UVICORN_GRACE_S),
    )


if __name__ == "__main__":
    main()
