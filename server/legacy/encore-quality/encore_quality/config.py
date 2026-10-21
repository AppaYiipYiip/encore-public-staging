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


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"  # noqa: S104 - reached by the Tailscale sidecar and the admin website over the stack's own network
    port: int = 8704
    navidrome_url: str = "http://navidrome:4533"
    navidrome_admin_user: str = ""
    navidrome_admin_password: str = ""
    #: The people service tells who may manage the server (owners are not always music-server administrators).
    people_url: str = "http://encore-people:8702"
    lidarr_url: str = "http://lidarr:8686"
    lidarr_api_key: str = ""
    slskd_url: str = "http://slskd:5030"
    slskd_api_key: str = ""
    #: The one shared mount: the music folder. The pool, the downloads and the way back live inside it, in dot-folders.
    music_dir: Path = Path("/music")
    data_dir: Path = Path("/data")
    #: Where Soularr reads its settings (a folder shared with the Soularr container).
    soularr_config: Path = Path("/soularr/config.ini")
    daily_cap: int = 40
    min_free_gb: float = 5.0
    duration_tolerance_s: float = 3.0
    give_up_days: float = 7.0

    @staticmethod
    def from_env() -> "Config":
        e = os.environ
        return Config(
            host=e.get("HOST", "0.0.0.0"),  # noqa: S104
            port=_int("PORT", 8704),
            navidrome_url=e.get("NAVIDROME_URL", "http://navidrome:4533").rstrip("/"),
            navidrome_admin_user=e.get("NAVIDROME_ADMIN_USER", ""),
            navidrome_admin_password=e.get("NAVIDROME_ADMIN_PASSWORD", ""),
            people_url=(e.get("PEOPLE_URL", "http://encore-people:8702") or "").rstrip("/"),
            lidarr_url=e.get("LIDARR_URL", "http://lidarr:8686").rstrip("/"),
            lidarr_api_key=e.get("LIDARR_API_KEY", ""),
            slskd_url=e.get("SLSKD_URL", "http://slskd:5030").rstrip("/"),
            slskd_api_key=e.get("SLSKD_API_KEY", ""),
            music_dir=Path(e.get("MUSIC_DIR", "/music")),
            data_dir=Path(e.get("DATA_DIR", "/data")),
            soularr_config=Path(e.get("SOULARR_CONFIG", "/soularr/config.ini")),
            daily_cap=max(1, _int("DAILY_CAP", 40)),
            min_free_gb=max(0.0, _float("MIN_FREE_GB", 5.0)),
            duration_tolerance_s=max(0.5, _float("DURATION_TOLERANCE_S", 3.0)),
            give_up_days=max(1.0, _float("GIVE_UP_DAYS", 7.0)),
        )
