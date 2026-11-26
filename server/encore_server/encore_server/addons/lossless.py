"""The add-on `lossless` (docs/35 section 2)."""

from __future__ import annotations

from .model import OFF, RUNS, YOURS, AddOn, switch  # noqa: F401

ADDON = AddOn(
    id="lossless",
    title="Higher-quality songs",
    summary="Also looks for lossless copies of the songs people play. This asks the Soulseek network.",
    states=(RUNS, YOURS, OFF),
    default=OFF,
    running=lambda settings: OFF,
    planned="P4-04",
    risk_text="This asks the Soulseek network for lossless copies of songs people play. It shares files with other people there, and the people you download from can see this server's internet address. In some countries downloading or sharing music you do not own is against the law. You are responsible for using it lawfully where you live. Turn it on only if you are sure it is allowed where you live.",
)
