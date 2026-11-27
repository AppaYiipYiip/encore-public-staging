"""The add-on `auto-update` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="auto-update",
    title="Update by itself at night",
    summary="Takes new versions at a quiet moment and goes back by itself if something fails.",
    states=(RUNS, OFF),
    default=OFF,
    running=lambda settings: OFF,
    planned="P3-14",
)
