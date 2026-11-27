"""The add-on `backups` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="backups",
    title="Where backups go",
    summary="A locked copy of your accounts, playlists and likes, made every night.",
    states=(RUNS, YOURS, OFF),
    default=RUNS,
    running=lambda settings: RUNS,
    host_managed="Changed on the computer with encore autobackup, until the helper of the admin pages exists (P3-25).",
)
