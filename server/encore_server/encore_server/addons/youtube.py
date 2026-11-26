"""The add-on `youtube` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="youtube",
    title="Songs you don't have",
    summary="Plays songs from YouTube and keeps them here if somebody saves them. No YouTube account is needed.",
    states=(RUNS, OFF),
    default=RUNS,
    running=switch("youtube"),
    setting="youtube",
)
