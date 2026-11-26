"""The add-on `federation` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="federation",
    title="Friends on other servers",
    summary="People on your server can add friends who run their own Encore, listen together in a Jam, and share songs. Nothing is shared until two people both agree.",
    states=(RUNS, OFF),
    default=RUNS,
    running=lambda settings: OFF,
    planned="P4-09",
    needs=("away",),
)
