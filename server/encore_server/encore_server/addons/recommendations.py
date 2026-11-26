"""The add-on `recommendations` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="recommendations",
    title="Suggestions",
    summary="Made for you, song radio and Smart Shuffle.",
    states=(RUNS, OFF),
    default=RUNS,
    running=lambda settings: OFF,
    planned="P4-05",
)
