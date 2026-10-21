"""`python -m encore_admin` - run the admin website from environment settings."""
from __future__ import annotations

import logging
import threading
import time

from . import __version__
from .config import Config
from .docker_api import Docker, DockerError, unix_transport
from .http_server import serve
from .server import Api
from .tls import ensure_certificate
from .services import Services
from .signin import SigninWindows


def build(config: Config) -> tuple[Api, SigninWindows]:
    docker = Docker(unix_transport(config.docker_socket), unix_transport(config.docker_socket, timeout=None), config.signin_image)
    services = Services(navidrome_url=config.navidrome_url, people_url=config.people_url, fetch_url=config.fetch_url,
                        quality_url=config.quality_url, recs_url=config.recs_url)
    signin = SigninWindows(docker, services.fetch_call, network=config.signin_network, minutes=config.signin_minutes)
    return Api(config, services, signin, stack=docker.stack, details=docker.details, logs=docker.logs, restart=docker.restart), signin


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("encore_admin")
    config = Config.from_env()
    api, signin = build(config)
    try:
        signin.clean_leftovers()
    except (DockerError, OSError) as error:
        log.warning("Docker is not available (%s): the sign-in window cannot be opened", error)

    def janitor() -> None:
        while True:
            time.sleep(5)
            try:
                signin.sweep()
            except Exception:  # noqa: BLE001 - housekeeping never stops the website
                log.exception("sweep failed")

    threading.Thread(target=janitor, daemon=True, name="janitor").start()
    tls = ensure_certificate(config.tls_dir, config.tls_names)
    if tls is None:
        log.warning("serving plain http: the sign-in window needs https and will not show")
    httpd = serve(api, config.host, config.port, tls)
    log.info("encore-admin %s on %s:%d (%s)", __version__, config.host, config.port, "https" if tls else "http")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
