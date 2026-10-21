"""Settings, all from environment variables (a container's natural configuration)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    navidrome_url: str = "http://navidrome:4533"
    music_dir: Path = Path("/music")  # where each person's folder is made (the same folder the music server reads)
    music_root: str = "/music"  # the same place as the MUSIC SERVER sees it
    data_dir: Path = Path("/data")  # the invitations and who chose to share (nothing about what anyone played)
    port: int = 8702
    host: str = "0.0.0.0"  # noqa: S104 - reached by the sidecar and the app over the stack's own network
    public_url: str = ""  # https://music.<tailnet>.ts.net : what a friend types into the app, and the base of an invitation
    server_name: str = "Encore"
    # The other parts of the stack, asked for the one "what can this server do?" answer (empty = not part of this server).
    fetch_url: str = ""
    hub_url: str = ""
    quality_url: str = ""
    recs_url: str = ""
    admin_user: str | None = None
    admin_password: str | None = None
    # Founding owners besides the music server's administrators (lower case; ADR-092): always owners, never changed from the app.
    # The owner's day-to-day account is an ordinary one (an administrator sees every library), so the person who runs the server names it.
    owners: frozenset[str] = frozenset()

    @staticmethod
    def from_env() -> "Config":
        e = os.environ
        return Config(
            navidrome_url=e.get("NAVIDROME_URL", "http://navidrome:4533"),
            music_dir=Path(e.get("MUSIC_DIR", "/music")),
            music_root=e.get("MUSIC_ROOT", e.get("MUSIC_DIR", "/music")),
            data_dir=Path(e.get("DATA_DIR", "/data")),
            port=_int("PORT", 8702),
            host=e.get("HOST", "0.0.0.0"),  # noqa: S104
            public_url=(e.get("PUBLIC_URL") or "").strip().rstrip("/"),
            server_name=(e.get("SERVER_NAME") or "Encore").strip()[:60] or "Encore",
            fetch_url=(e.get("FETCH_URL") or "").strip().rstrip("/"),
            hub_url=(e.get("HUB_URL") or "").strip().rstrip("/"),
            quality_url=(e.get("QUALITY_URL") or "").strip().rstrip("/"),
            recs_url=(e.get("RECS_URL") or "").strip().rstrip("/"),
            admin_user=e.get("NAVIDROME_ADMIN_USER") or None,
            admin_password=e.get("NAVIDROME_ADMIN_PASSWORD") or None,
            # PEOPLE_INVITERS is the name this setting had in ADR-090; it keeps working.
            owners=frozenset(n.strip().lower() for n in (e.get("PEOPLE_OWNERS") or e.get("PEOPLE_INVITERS") or "").split(",") if n.strip()),
        )
