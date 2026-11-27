"""The Home page's answer (W-02, docs/15 section 4): one plain row per part, "needs you" first, in words, with counts only and never a title or what anybody plays (docs/21).

This module only turns facts into words; the route collects the facts. A fact the server cannot know is said so ("this computer has not told Encore yet"): nothing here ever
shows an invented "all good". An amber row that needs somebody comes first and counts in the sentence at the top; a row that only informs, or resting that comes back by
itself, never does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .helper import CANNOT_OPEN
from .host_status import HostStatus

DAY_MS = 24 * 3600 * 1000
#: A song takes about this much room (a 4-minute song at the quality the server keeps), for the plain "room for about N songs".
SONG_BYTES = 5_500_000
#: The key of the away address is a warning this many days before it ends (docs/22 section 5).
KEY_WARNING_DAYS = 14
#: A backup is nightly: three days without one is a missed week-end, and says so.
BACKUP_WARNING_DAYS = 3


@dataclass(frozen=True)
class Facts:
    now: int
    #: True: the music server answered; False: it did not; None: it is not configured
    music_answers: bool | None
    #: `off | ok | resting` and when the rest ends (milliseconds), from the source itself
    youtube_state: str
    youtube_resumes_at: int | None
    tools_degraded: bool
    away_url: str
    #: None: the folders could not be measured
    free_bytes: int | None
    floor_bytes: int
    version: str
    people: int
    devices: int
    last_sign_in: int | None
    plays_today: int
    imports_today: int
    host: HostStatus | None
    #: the name of the clock whose midnight starts "today" (the container's; the Host's own time zone is a later setting)
    clock_zone: str = "UTC"
    #: The helper the admin pages ask for a backup or the away address: `ready`, `missing` (not installed: not a failure, the row says how to get it) or `cannot-open` (it is there and this
    #: server may not open it: the Host must act).
    helper: str = "missing"


def _row(row_id: str, title: str, state: str, words: str, detail: str = "", **more: Any) -> dict[str, Any]:
    return {"id": row_id, "title": title, "state": state, "words": words, "detail": detail, **more}


def _need(need_id: str, words: str, detail: str, page: str | None = None) -> dict[str, Any]:
    return {"id": need_id, "words": words, "detail": detail, "page": page}


def _gb(n: int) -> str:
    gb = n / 1_000_000_000
    return f"{gb:,.0f} GB" if gb >= 10 else f"{gb:,.1f} GB"


def _size(n: int) -> str:
    return f"{n / 1_000_000:,.0f} MB" if n >= 1_000_000 else f"{max(1, n // 1000):,} KB"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def build(f: Facts) -> dict[str, Any]:
    needs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    host = f.host
    told = host is not None
    # A status the computer has not rewritten for a while is STILL USED: when the last backup was made and when the key ends are absolute times, so an old file can only
    # make a warning come early, never late. Hiding them behind "has not told Encore yet" would turn a failing backup into "Everything is working." It says how old it is.
    quiet = ""
    if host is not None and not host.fresh(f.now):
        quiet = f" The computer last reported {_plural(max(1, int((f.now - host.written_at) // DAY_MS)), 'day', 'days')} ago."
    not_told = "This computer has not told Encore yet."

    # -- the music server
    if f.music_answers is False:
        rows.append(_row("music-server", "Music server", "down", "Not answering", "It usually comes back by itself."))
        needs.append(
            _need(
                "music-server",
                "Music server is not answering.",
                "It usually comes back by itself; if it does not, restart it on the server computer: sudo encore restart.",
            )
        )
    elif f.music_answers is True:
        rows.append(_row("music-server", "Music server", "ok", "Working"))
    else:
        rows.append(_row("music-server", "Music server", "unknown", "Not set up", "Encore has no music server to ask."))

    # -- songs from YouTube
    if f.youtube_state == "off":
        rows.append(_row("youtube", "Songs from YouTube", "off", "Off", "Songs you don't have are not fetched."))
    elif f.youtube_state == "resting":
        rows.append(
            _row(
                "youtube",
                "Songs from YouTube",
                "resting",
                "Resting",
                "YouTube asked this server to slow down. Songs you already have still play; the rest waits and starts again by itself.",
                restingUntil=f.youtube_resumes_at,
            )
        )
    else:
        rows.append(
            _row(
                "youtube",
                "Songs from YouTube",
                "ok" if not f.tools_degraded else "warn",
                "Working" if not f.tools_degraded else "Working, the fetching tool is out of date",
                "" if not f.tools_degraded else "The fetching tool could not be updated yet; it tries again by itself.",
            )
        )

    # -- away from home
    if not f.away_url:
        rows.append(
            _row(
                "away",
                "Away from home",
                "off",
                "Not set up",
                "So you and your people can listen outside your home, with no router settings.",
            )
        )
    else:
        days = None
        renewed = (quiet + " If you have made a new key since, this goes away at the next backup.") if quiet else ""
        if host is not None and host.away_key_expires_at is not None:
            days = (host.away_key_expires_at - f.now) // DAY_MS
        if days is not None and days < 0:
            rows.append(_row("away", "Away from home", "warn", "The key has expired", f.away_url, address=f.away_url))
            needs.append(
                _need(
                    "away-key",
                    "The away-from-home key has expired.",
                    "Phones outside your home stopped working. Make a new key at Tailscale and put it in Away from home."
                    + renewed,
                    "away",
                )
            )
        elif days is not None and days <= KEY_WARNING_DAYS:
            rows.append(
                _row(
                    "away",
                    "Away from home",
                    "warn",
                    f"The key expires in {_plural(int(days), 'day', 'days')}",
                    f.away_url,
                    address=f.away_url,
                )
            )
            needs.append(
                _need(
                    "away-key",
                    f"The away-from-home key expires in {_plural(int(days), 'day', 'days')}.",
                    "Make a new key at Tailscale and put it in Away from home. Until then phones outside your home keep working; after that day they stop."
                    + renewed,
                    "away",
                )
            )
        else:
            detail = (
                f.away_url
                + (f" · the key lasts another {_plural(int(days), 'day', 'days')}." if days is not None else "")
                + quiet
            )
            rows.append(_row("away", "Away from home", "ok", "On", detail, address=f.away_url))

    # -- the disk
    if f.free_bytes is None:
        rows.append(_row("disk", "Disk", "unknown", "Not measured", "Encore could not read how much room is left."))
    elif f.free_bytes < f.floor_bytes:
        rows.append(
            _row(
                "disk",
                "Disk",
                "warn",
                f"{_gb(f.free_bytes)} free",
                f"Encore stops keeping songs below {_gb(f.floor_bytes)} free.",
            )
        )
        needs.append(
            _need(
                "disk",
                "The disk is almost full.",
                f"Encore stops keeping songs when less than {_gb(f.floor_bytes)} is free. Free some space on the computer, or move the music.",
            )
        )
    else:
        rows.append(
            _row("disk", "Disk", "ok", f"{_gb(f.free_bytes)} free", f"Room for about {f.free_bytes // SONG_BYTES:,} songs.")
        )

    # -- the last backup (a fact only the computer knows)
    backup = host.last_backup if host is not None else None
    if not told:
        rows.append(
            _row("backup", "Last backup", "unknown", not_told, "A backup is made every night, and now with: sudo encore backup.")
        )
    elif backup is None:
        rows.append(_row("backup", "Last backup", "warn", "No backup yet", "Make one now with: sudo encore backup."))
        needs.append(
            _need(
                "backup",
                "There is no backup yet.",
                "A backup keeps your accounts, playlists and likes safe. Make one now with: sudo encore backup.",
                "backups",
            )
        )
    else:
        age_days = (f.now - backup.at) // DAY_MS
        detail = f"{_size(backup.bytes)}. " + ("Locked." if backup.locked else "Not locked: run sudo encore secure.") + quiet
        if age_days >= BACKUP_WARNING_DAYS:
            rows.append(
                _row(
                    "backup",
                    "Last backup",
                    "warn",
                    f"{_plural(int(age_days), 'day', 'days')} ago",
                    detail,
                    at=backup.at,
                    locked=backup.locked,
                )
            )
            needs.append(
                _need(
                    "backup",
                    f"The last backup is {_plural(int(age_days), 'day', 'days')} old.",
                    "A backup should be made every night. Check that the computer was on, or make one now with: sudo encore backup.",
                    "backups",
                )
            )
        else:
            rows.append(_row("backup", "Last backup", "ok", "Made", detail, at=backup.at, locked=backup.locked))

    # -- the helper (what the Backups and Away pages need)
    if f.helper == "ready":
        rows.append(
            _row("helper", "Admin buttons", "ok", "Ready", "The admin pages can make a backup and switch the away address.")
        )
    elif f.helper == "cannot-open":
        rows.append(_row("helper", "Admin buttons", "warn", "Cannot be opened", CANNOT_OPEN))
        needs.append(_need("helper", "The admin pages cannot reach the helper.", CANNOT_OPEN))
    else:
        rows.append(
            _row(
                "helper",
                "Admin buttons",
                "off",
                "Not installed",
                "Until it is, the admin pages cannot make a backup or switch the away address. On the server computer run: sudo encore helper install",
            )
        )

    # -- this program
    rows.append(_row("encore", "Encore", "ok", f"Version {f.version}"))

    # -- the people (counts only)
    seen = "Nobody has signed in yet." if f.last_sign_in is None else f"The last sign-in was {_when(f.now, f.last_sign_in)}."
    rows.append(
        _row(
            "people", "People", "ok", _plural(f.people, "person", "people"), f"{_plural(f.devices, 'device', 'devices')}. {seen}"
        )
    )

    # -- today (counts only, never titles)
    imports = f" {_plural(f.imports_today, 'import', 'imports')} finished." if f.imports_today else ""
    rows.append(
        _row(
            "today",
            "Today",
            "ok",
            f"{_plural(f.plays_today, 'song', 'songs')} played",
            f"{imports.strip()} Counts only, never titles. Since midnight {f.clock_zone}.".strip(),
        )
    )

    summary = (
        {"state": "good", "words": "Everything is working."}
        if not needs
        else {"state": "needs", "words": "One thing needs you." if len(needs) == 1 else f"{len(needs)} things need you."}
    )
    return {"summary": {**summary, "checkedAt": f.now}, "needsYou": needs, "rows": rows}


def _when(now: int, at: int) -> str:
    days = max(0, (now - at) // DAY_MS)
    return "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"
