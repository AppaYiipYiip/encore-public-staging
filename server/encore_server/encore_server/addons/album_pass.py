"""The add-on `album-pass` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="album-pass",
    title="Real albums",
    summary='Files each song under the album it is on, so albums stop losing songs to "Songs without an album".',
    states=(RUNS, OFF),
    default=RUNS,
    running=switch("album_pass"),
    setting="album_pass",
    needs=("catalogue",),
    risk_text="A song's album is written into the file on your disk the next time it is kept, and that is permanent: switching this off later stops new stamps but removes none.",
)
