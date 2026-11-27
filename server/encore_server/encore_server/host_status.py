"""What the computer tells the server (docs/36 section 2, "Facts the server cannot see").

The Encore container mounts only `/data` and `/music`, so it cannot see when the last backup was made, whether the away address's key is about to expire, or what a newer
version is. The `encore` command writes `host-status.json` into the data folder whenever it does something that changes one of those facts (a backup, a restore, the away
address on or off, an update, the keys) and the server only READS it. Nothing here gives the server any power over the computer, the file holds no secret and no path, and
what is read is checked as untrusted input: a file that is missing, too big, not JSON, of the wrong shape or too old is "this computer has not told Encore yet", never an
invented "all good".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HOST_STATUS_FILE = "host-status.json"
#: What is told by the computer is trusted for this long (the nightly backup rewrites it every night, so a day and a half is a missed night).
FRESH_FOR_MS = 36 * 3600 * 1000
#: A real file is a few hundred bytes.
MAX_BYTES = 16 * 1024


@dataclass(frozen=True)
class LastBackup:
    at: int
    bytes: int
    locked: bool


@dataclass(frozen=True)
class HostStatus:
    written_at: int
    last_backup: LastBackup | None
    away_address: str | None
    away_key_expires_at: int | None
    backup_key_made_at: int | None

    def fresh(self, now: int) -> bool:
        return 0 <= now - self.written_at <= FRESH_FOR_MS


def _ms(value: object) -> int | None:
    """A time in milliseconds since 1970 that is plausible (after 2020, before 2100), or None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1_577_836_800_000 <= value <= 4_102_444_800_000 else None


def read(data_dir: Path) -> HostStatus | None:
    """The status the computer wrote, or None when there is none that can be trusted at all (absent, unreadable, not an object, no write time)."""
    path = data_dir / HOST_STATUS_FILE
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    written = _ms(raw.get("writtenAt"))
    if written is None:
        return None
    backup = raw.get("lastBackup")
    last_backup = None
    if isinstance(backup, dict) and (at := _ms(backup.get("at"))) is not None:
        size = backup.get("bytes")
        last_backup = LastBackup(
            at, size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else 0, backup.get("locked") is True
        )
    away_raw, key_raw = raw.get("away"), raw.get("backupKey")
    away: dict[str, Any] = away_raw if isinstance(away_raw, dict) else {}
    key: dict[str, Any] = key_raw if isinstance(key_raw, dict) else {}
    address = away.get("address")
    return HostStatus(
        written_at=written,
        last_backup=last_backup,
        away_address=address
        if isinstance(address, str) and address.startswith(("http://", "https://")) and len(address) <= 300
        else None,
        away_key_expires_at=_ms(away.get("keyExpiresAt")),
        backup_key_made_at=_ms(key.get("madeAt")),
    )
