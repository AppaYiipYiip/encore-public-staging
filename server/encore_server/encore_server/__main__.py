"""`python -m encore_server`: runs the server (the container's command)."""

from __future__ import annotations

import logging

import uvicorn

from .api import create_app
from .config import Settings


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # The music server is asked with the person's login token in the address, and httpx logs every address at INFO: that would put
    # a value anyone could guess the password from (token = md5 of password and salt) into the log. Warnings and errors only.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    uvicorn.run(
        create_app(settings), host=settings.host, port=settings.port, log_level=settings.log_level.lower(), access_log=False
    )


if __name__ == "__main__":
    main()
