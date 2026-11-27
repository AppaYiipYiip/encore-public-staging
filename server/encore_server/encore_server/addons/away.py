"""The add-on `away` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="away",
    title="Away from home",
    summary="An address that works outside your house, so you and your people can listen away from home with no router settings.",
    states=(RUNS, YOURS, OFF),
    default=OFF,
    running=lambda settings: RUNS if settings.away_url else OFF,
    host_managed="Switched on and off on the computer with encore funnel on or off, until the helper of the admin pages exists (P3-25).",
)
