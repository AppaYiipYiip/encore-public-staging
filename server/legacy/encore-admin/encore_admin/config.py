"""Settings of the admin website, from environment variables (docs/45, docs/49)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 8800
    #: The services this one looks after, by their names on the stack's own network.
    navidrome_url: str = "http://navidrome:4533"
    people_url: str = "http://encore-people:8702"
    fetch_url: str = "http://encore-fetch:8701"
    quality_url: str = "http://encore-quality:8704"
    recs_url: str = "http://encore-recs:8705"
    #: Docker's control socket. The only things done with it are in docker_api.py: one image, one kind of container.
    docker_socket: str = "/var/run/docker.sock"
    #: The browser shown in the page for signing in to Google: a normal Firefox in a small image (about 330 MB to download), shown
    #: in the page through noVNC, which works on plain http too. Pinned.
    signin_image: str = "jlesage/firefox:v26.09.1"
    #: The stack's own Docker network, which the sign-in browser joins (it publishes no port).
    signin_network: str = "encore-server_default"
    signin_minutes: int = 15
    session_hours: int = 8
    server_name: str = "Encore"
    #: Where the website keeps its certificate (https is needed for the sign-in window to show), and extra names/addresses to put in it.
    tls_dir: Path = Path("/data/tls")
    tls_names: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        e = dict(os.environ if env is None else env)

        def number(key: str, default: int, low: int, high: int) -> int:
            try:
                return min(high, max(low, int(e.get(key, default))))
            except ValueError:
                return default

        return cls(
            host=e.get("ADMIN_HOST", "0.0.0.0"),
            port=number("ADMIN_PORT", 8800, 1, 65535),
            navidrome_url=e.get("NAVIDROME_URL", cls.navidrome_url).rstrip("/"),
            people_url=e.get("PEOPLE_URL", cls.people_url).rstrip("/"),
            fetch_url=e.get("FETCH_URL", cls.fetch_url).rstrip("/"),
            quality_url=e.get("QUALITY_URL", cls.quality_url).rstrip("/"),
            recs_url=e.get("RECS_URL", cls.recs_url).rstrip("/"),
            docker_socket=e.get("DOCKER_SOCKET", cls.docker_socket),
            signin_image=e.get("SIGNIN_IMAGE", cls.signin_image),
            signin_network=e.get("SIGNIN_NETWORK", cls.signin_network),
            signin_minutes=number("SIGNIN_MINUTES", 15, 1, 120),
            session_hours=number("SESSION_HOURS", 8, 1, 72),
            server_name=e.get("SERVER_NAME", "Encore")[:60],
            tls_dir=Path(e.get("TLS_DIR", "/data/tls")),
            tls_names=tuple(n.strip() for n in e.get("TLS_NAMES", "").split(",") if n.strip()),
        )
