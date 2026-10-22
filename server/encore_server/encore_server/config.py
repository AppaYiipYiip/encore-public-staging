"""Settings, read from the environment (the container sets them; defaults suit a development machine)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("/data")
    music_dir: Path = Path("/music")
    navidrome_url: str = "http://navidrome:4533"
    host: str = "0.0.0.0"  # noqa: S104 - a container: the published port is the only way in
    port: int = 4533
    server_name: str = "My music server"
    log_level: str = "INFO"
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "encore.db"

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> Settings:
        e = dict(os.environ) if env is None else env
        return Settings(
            data_dir=Path(e.get("ENCORE_DATA_DIR", "/data")),
            music_dir=Path(e.get("ENCORE_MUSIC_DIR", "/music")),
            navidrome_url=e.get("ENCORE_NAVIDROME_URL", "http://navidrome:4533").rstrip("/"),
            host=e.get("ENCORE_HOST", "0.0.0.0"),  # noqa: S104
            port=int(e.get("ENCORE_PORT", "4533")),
            server_name=e.get("ENCORE_SERVER_NAME", "My music server"),
            log_level=e.get("ENCORE_LOG_LEVEL", "INFO").upper(),
        )
