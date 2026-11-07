"""Settings, read from the environment (the container sets them; defaults suit a development machine)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def clean_url(text: str) -> str:
    """An address as phones should be told it: `http(s)://host[:port]` with nothing after it; anything else is "unknown"."""
    text = text.strip().rstrip("/")
    return text if re.fullmatch(r"https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?", text) else ""


#: The Host's choice of the pace at YouTube (D-67, owner 7 Nov 2026): 3 to 8 seconds on average between background requests, 4 unless the Host says otherwise.
#: 3 saves 200 songs in about 10 minutes, 4 in about 13, 8 in about 27. Outside the range the nearest end is used, so a typo cannot switch pacing off.
MIN_PACE_S = 3.0
MAX_PACE_S = 8.0
DEFAULT_PACE_S = 4.0


def pace_from(value: str) -> float:
    """The pace a Host wrote in `ENCORE_YOUTUBE_PACE_S`: nothing or something that is not a number is the default, anything else is held to 3 to 8."""
    try:
        wanted = float(value.strip())
    except ValueError:
        return DEFAULT_PACE_S
    if wanted != wanted:  # NaN
        return DEFAULT_PACE_S
    return min(MAX_PACE_S, max(MIN_PACE_S, wanted))


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("/data")
    music_dir: Path = Path("/music")
    navidrome_url: str = "http://navidrome:4533"
    host: str = "0.0.0.0"  # noqa: S104 - a container: the published port is the only way in
    port: int = 4533
    server_name: str = "My music server"
    #: Addresses (or networks, `10.0.0.0/8`) of the proxies in front of this server whose `X-Forwarded-For` is believed, besides this machine, the
    #: home and Docker networks and Tailscale, which always are (AUDIT B11). Empty is right for the guided install.
    trusted_proxies: tuple[str, ...] = ()
    #: Where a friend gets the Android app, when the owner has somewhere to send them (an address; docs/10 D-40 is open: there is no store). The join page shows
    #: "Get Encore" only when this is set; otherwise it says to ask the person who invited them.
    app_url: str = ""
    log_level: str = "INFO"
    youtube: bool = True
    #: The server fetches, checks and switches to a newer yt-dlp by itself (docs/11 ADR-R39). Off for a Host who pins versions or has no outside access.
    auto_tools: bool = True
    #: The addresses this server tells its phones about (docs/11 ADR-R40): the installer writes the home one, `encore funnel on` the away one. Empty: unknown.
    home_url: str = ""
    away_url: str = ""
    #: Mean seconds between the background look-ups and downloads at YouTube (D-67): the Host picks 3 to 8 in `.env`, 4 by default; a test may set 0 (no pacing).
    youtube_pace_s: float = DEFAULT_PACE_S
    fault: str = ""
    #: Keeping (docs/04 D-3): saved songs are copied into the music folder. Off, everything still plays by streaming.
    keep: bool = True
    #: The worker threads that do background work; off in tests, which run the scheduler by hand.
    workers: bool = True
    #: The administrator the installer made in the music server, for scans and looking songs up. Nobody else's login.
    navidrome_admin_user: str = ""
    navidrome_admin_password: str = ""
    min_free_gb: float = 10.0
    #: A song nobody saved is kept once it was played on this many different days.
    keep_after_play_days: int = 2
    #: How often the server looks at the music server's songs to give them refs (0 turns it off).
    scan_every_min: int = 60
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
            trusted_proxies=tuple(p.strip() for p in e.get("ENCORE_TRUSTED_PROXIES", "").split(",") if p.strip()),
            app_url=e.get("ENCORE_APP_URL", "").strip(),
            log_level=e.get("ENCORE_LOG_LEVEL", "INFO").upper(),
            youtube=e.get("ENCORE_YOUTUBE", "1").strip().lower() not in ("0", "false", "no"),
            auto_tools=e.get("ENCORE_AUTO_TOOLS", "1").strip().lower() not in ("0", "false", "no"),
            home_url=clean_url(e.get("ENCORE_HOME_URL", "")),
            away_url=clean_url(e.get("ENCORE_AWAY_URL", "")),
            youtube_pace_s=pace_from(e.get("ENCORE_YOUTUBE_PACE_S", "")),
            fault=e.get("ENCORE_FAULT", "").strip(),
            keep=e.get("ENCORE_KEEP", "1").strip().lower() not in ("0", "false", "no"),
            workers=e.get("ENCORE_WORKERS", "1").strip().lower() not in ("0", "false", "no"),
            navidrome_admin_user=e.get("ENCORE_NAVIDROME_ADMIN_USER", "").strip(),
            navidrome_admin_password=e.get("ENCORE_NAVIDROME_ADMIN_PASSWORD", ""),
            min_free_gb=float(e.get("ENCORE_MIN_FREE_GB", "10")),
            keep_after_play_days=int(e.get("ENCORE_KEEP_AFTER_PLAY_DAYS", "2")),
            scan_every_min=int(e.get("ENCORE_SCAN_EVERY_MIN", "60")),
        )
