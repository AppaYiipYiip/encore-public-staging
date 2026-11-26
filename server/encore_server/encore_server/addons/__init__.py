"""The add-ons of the server, in the order the pages list them (docs/35: one model, one manifest per add-on; the wizard, the admin pages, the `encore addon` command and the docs check read this list)."""

from __future__ import annotations

from . import (
    album_pass,
    auto_update,
    away,
    backups,
    catalogue,
    federation,
    lossless,
    lyrics,
    music_server,
    recommendations,
    youtube,
)
from .model import OFF, RUNS, STATES, YOURS, AddOn

ADDONS: tuple[AddOn, ...] = (
    youtube.ADDON,
    catalogue.ADDON,
    album_pass.ADDON,
    music_server.ADDON,
    lossless.ADDON,
    away.ADDON,
    backups.ADDON,
    federation.ADDON,
    auto_update.ADDON,
    lyrics.ADDON,
    recommendations.ADDON,
)


def by_id(addon_id: str) -> AddOn | None:
    return next((a for a in ADDONS if a.id == addon_id), None)


__all__ = ["ADDONS", "OFF", "RUNS", "STATES", "YOURS", "AddOn", "by_id"]
