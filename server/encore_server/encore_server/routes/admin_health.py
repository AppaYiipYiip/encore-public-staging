"""The Home page's route (W-02): `GET admin/health`. Owner only, a 404 to the internet. It collects the facts and `health.build` turns them into words."""

from __future__ import annotations

import logging
import shutil
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import __version__, host_status
from ..auth import Principal
from ..health import Facts, build
from ..ids import now_ms
from .common import API_PREFIX, Services, _ok, _youtube_status, get_principal, refuse_public, require_owner, services

log = logging.getLogger("encore_server.api")

router = APIRouter(prefix=API_PREFIX)


def local_midnight_ms(now: float | None = None) -> int:
    """The start of today by the server's own clock (the Host's computer's: counts of "today" are the Host's today)."""
    t = time.localtime(now)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)


def free_bytes(svc: Services) -> int | None:
    """The room left where Encore keeps songs and where it keeps its database: the smaller of the two (they are often one disk)."""
    left: list[int] = []
    for folder in (svc.settings.music_dir, svc.settings.data_dir):
        try:
            left.append(shutil.disk_usage(folder).free)
        except OSError:
            continue
    return min(left) if left else None


def collect(svc: Services) -> Facts:
    now = now_ms()
    music = svc.music
    status = _youtube_status(svc.youtube)
    with svc.db.read() as conn:
        people = conn.execute("SELECT COUNT(*) FROM person").fetchone()[0]
        devices = conn.execute("SELECT COUNT(*) FROM device WHERE revoked_at IS NULL").fetchone()[0]
        last = conn.execute("SELECT MAX(last_seen) FROM device").fetchone()[0]
        midnight = local_midnight_ms()
        plays = conn.execute("SELECT COUNT(*) FROM play_event WHERE at >= ?", (midnight,)).fetchone()[0]
        imports = conn.execute("SELECT COUNT(*) FROM import WHERE state = 'done' AND updated_at >= ?", (midnight,)).fetchone()[0]
    tools_state = (svc.tools.status().get("ytDlp") or {}).get("state") if svc.tools is not None else None
    resting = status.get("state") == "resting"
    return Facts(
        now=now,
        music_answers=music.ping() if music is not None and music.configured else None,
        youtube_state=str(status.get("state", "off")),
        youtube_resumes_at=now + int(status.get("resumesInSec", 0)) * 1000 if resting else None,
        tools_degraded=tools_state == "degraded",
        away_url=svc.settings.away_url,
        free_bytes=free_bytes(svc),
        floor_bytes=int(svc.settings.min_free_gb * 1_000_000_000),
        version=__version__,
        people=int(people),
        devices=int(devices),
        last_sign_in=int(last) if last is not None else None,
        plays_today=int(plays),
        imports_today=int(imports),
        host=host_status.read(svc.settings.data_dir),
    )


@router.get("/admin/health")
def health(request: Request, _: None = Depends(refuse_public), p: Principal = Depends(get_principal)) -> JSONResponse:
    require_owner(p)
    answer: dict[str, Any] = build(collect(services(request)))
    return _ok(answer)
