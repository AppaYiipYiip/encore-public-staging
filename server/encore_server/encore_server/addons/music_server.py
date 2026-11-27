"""The add-on `music-server` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="music-server",
    title="Music server",
    summary="Scans your music, signs people in and streams your own files.",
    states=(RUNS, YOURS),
    default=RUNS,
    running=lambda settings: RUNS,
    planned="P3-11",
)
