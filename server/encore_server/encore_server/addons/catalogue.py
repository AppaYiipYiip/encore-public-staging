"""The add-on `catalogue` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="catalogue",
    title="Pictures, search and artist pages",
    summary="Asks a public catalogue for pictures and for the artist and album pages, always through this server and never from the phones.",
    states=(RUNS, OFF),
    default=RUNS,
    running=switch("catalogue"),
    setting="catalogue",
    feature="catalogue",
)
