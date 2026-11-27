"""The add-on `lyrics` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="lyrics",
    title="Lyrics",
    summary="Words that follow the song, asked of one outside source once for everybody.",
    states=(RUNS, OFF),
    default=RUNS,
    running=lambda settings: OFF,
    planned="P2-14",
)
