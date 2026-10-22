"""Settings, all from environment variables (a container's natural
configuration)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _pairs(text: str) -> dict:
    """"owner=owner-added,sara=sara2" -> {"owner": "owner-added", "sara": "sara2"}; anything malformed is skipped."""
    out = {}
    for part in text.split(","):
        name, sep, folder = part.partition("=")
        if sep and name.strip() and folder.strip():
            out[name.strip()] = folder.strip()
    return out


@dataclass(frozen=True)
class Config:
    navidrome_url: str = "http://navidrome:4533"
    music_dir: Path = Path("/music")
    work_dir: Path = Path("/work")
    port: int = 8701
    host: str = "0.0.0.0"  # noqa: S104 - a LAN service behind the host firewall
    ytdlp: str = "yt-dlp"
    #: "lean" (YouTube Music search + in-process extraction) or "legacy" (one yt-dlp program per step).
    resolver: str = "lean"
    #: Fetch a found stream with plain ranged requests instead of starting yt-dlp again (`DIRECT_DOWNLOAD=0` turns it off).
    direct_download: bool = True
    cookies_file: str | None = None
    min_free_gb: int = 20
    #: Longest song, in seconds. 45 minutes: real songs run 25 and 35 minutes (the owner, 2026-10-18); an hour-long video is not one.
    max_duration_s: int = 2700
    max_file_mb: int = 80
    #: Taps per person per day (a runaway guard). Imports are paced by the queue, not counted (ADR-100).
    user_daily_limit: int = 1000
    user_active_limit: int = 3
    #: Finished downloads kept by upload id so the next person asking for the same song waits for nothing (0 = keep none).
    cache_mb: int = 1500
    workers: int = 3
    #: Songs the import queue fetches at once (for everybody together) and the pause after each.
    import_workers: int = 2
    import_gap_s: float = 2.0
    #: Songs an hour the import queue lets itself fetch, taps included (YouTube allows a visitor about 300 an hour; 120 leaves room and keeps the home address out of trouble, docs/tasks P1-03).
    import_max_per_hour: int = 120
    #: How long the music server's own file watcher gets to list a new song before a scan is asked for (every scan moves the
    #: scan time all open phones watch, H38).
    watcher_wait_s: float = 6.0
    #: YouTube clients tried first for a visitor (comma separated; empty = yt-dlp's own choice): `visionos` extracts in 1.3 s, not 3.7 s.
    youtube_fast_clients: tuple = ("visionos",)
    #: Fault injection for tests of the app against a misbehaving YouTube (youtube_refuse | slow_extract:<ms> | no_results). Empty in real use.
    fault: str = ""
    #: Where the YouTube accounts live (docs/50): one private file each, their list, what each did.
    accounts_dir: Path | None = None
    #: Look up the album, cover, number and year of a song that came without them (Deezer's public catalogue).
    lookup_albums: bool = True
    #: The people service, which knows who the owner is (it answers /api/me); `None` = the music server's administrators.
    people_url: str | None = "http://encore-people:8702"
    profile_dir: Path | None = None  # None = work_dir/profile
    profile: bool = True
    admin_user: str | None = None
    admin_password: str | None = None
    fake: bool = False
    dev_local: bool = False
    # One library per person (docs/26): a fetched song goes to the requester's own folder under MUSIC_DIR.
    people: bool = False
    person_folders: dict = field(default_factory=dict)  # {"owner": "owner-added"}: a person whose folder is called differently

    @staticmethod
    def from_env() -> "Config":
        e = os.environ
        return Config(
            navidrome_url=e.get("NAVIDROME_URL", "http://navidrome:4533"),
            music_dir=Path(e.get("MUSIC_DIR", "/music")),
            work_dir=Path(e.get("WORK_DIR", "/work")),
            port=_int("PORT", 8701),
            host=e.get("HOST", "0.0.0.0"),  # noqa: S104
            ytdlp=e.get("YTDLP", "yt-dlp"),
            resolver=e.get("RESOLVER", "lean").strip().lower(),
            direct_download=e.get("DIRECT_DOWNLOAD", "1").strip() not in ("0", "false", "no"),
            # The file does not have to exist: when the owner puts one there, the next song uses it.
            cookies_file=e.get("YT_COOKIES_FILE") or str(Path(e.get("WORK_DIR", "/work")) / "youtube-cookies.txt"),
            min_free_gb=_int("MIN_FREE_GB", 20),
            max_duration_s=_int("MAX_DURATION_S", 2700),
            max_file_mb=_int("MAX_FILE_MB", 80),
            user_daily_limit=_int("USER_DAILY_LIMIT", 1000),
            user_active_limit=_int("USER_ACTIVE_LIMIT", 3),
            cache_mb=max(0, _int("CACHE_MB", 1500)),
            workers=max(1, min(4, _int("WORKERS", 3))),
            import_workers=max(1, min(3, _int("IMPORT_WORKERS", 2))),
            import_gap_s=max(0.0, _int("IMPORT_GAP_S", 2)),
            import_max_per_hour=max(10, _int("IMPORT_MAX_PER_HOUR", 120)),
            watcher_wait_s=max(0.0, _int("WATCHER_WAIT_S", 6)),
            youtube_fast_clients=tuple(c.strip() for c in e.get("YT_FAST_CLIENTS", "visionos").split(",") if c.strip()),
            fault=e.get("ENCORE_FAULT", "").strip(),
            accounts_dir=Path(e["ACCOUNTS_DIR"]) if e.get("ACCOUNTS_DIR") else None,
            lookup_albums=e.get("LOOKUP_ALBUMS", "1") not in ("0", "false", "no"),
            people_url=(e.get("PEOPLE_URL", "http://encore-people:8702") or None),
            profile_dir=Path(e["PROFILE_DIR"]) if e.get("PROFILE_DIR") else None,
            profile=e.get("PROFILE", "1") not in ("0", "false", "no"),
            admin_user=e.get("NAVIDROME_ADMIN_USER") or None,
            admin_password=e.get("NAVIDROME_ADMIN_PASSWORD") or None,
            fake=e.get("FAKE_MODE", "") in ("1", "true", "yes"),
            dev_local=e.get("DEV_LOCAL", "") in ("1", "true", "yes"),
            people=e.get("PEOPLE", "") in ("1", "true", "yes"),
            person_folders=_pairs(e.get("PERSON_FOLDERS", "")),
        )
