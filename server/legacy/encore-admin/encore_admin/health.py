"""Is everything working? One plain line per part of the server (docs/49 P1).

A part is **working** when it answers; **off** when it was never switched on (no container: not an alarm); **starting** while it
has only just started; **down** when it is switched on and does not answer (this is what needs the owner); **unknown** when nothing
can tell (Docker cannot be asked and the part has no answer of its own).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Part:
    key: str
    name: str
    container: str
    #: What is said when it is down ("is not answering" for a service, "is not working" for something that has no answer of its own).
    trouble: str = "is not answering"


PARTS = (
    Part("music", "Music server", "navidrome"),
    Part("people", "People and invitations", "encore-people"),
    Part("fetch", "Songs from YouTube", "encore-fetch"),
    Part("quality", "Best quality (Lidarr and Soulseek)", "encore-quality"),
    Part("recs", "Suggestions for each person", "encore-recs"),
    Part("hub", "Jam (listening together)", "encore-hub"),
    Part("remote", "Reaching it from outside", "encore-tailscale", "is not working"),
)

OFF_NOTE = "Not switched on."
NOTES = {"working": "", "starting": "Starting up…", "down": "Not answering.", "off": OFF_NOTE, "unknown": "Cannot tell from here."}


def state_of(answers: bool | None, container: str | None, docker_known: bool) -> str:
    """`answers`: True it answered, False it did not, None it has no answer of its own. `container`: what Docker says of it, or
    None when it was never created. `docker_known`: whether Docker could be asked at all."""
    if answers is True:
        return "working"
    if not docker_known:
        return "down" if answers is False else "unknown"
    if container is None:
        return "off"
    if container == "starting":
        return "starting"
    if answers is None and container == "running":
        return "working"
    return "down"


def judge(answers: dict[str, bool | None], containers: dict[str, str] | None, versions: dict[str, str] | None = None) -> list[dict]:
    """The list the front page shows: `{"key", "name", "state", "note"}` per part, in a fixed order."""
    versions = versions or {}
    out = []
    for part in PARTS:
        state = state_of(answers.get(part.key), (containers or {}).get(part.container), containers is not None)
        note = NOTES[state]
        if state == "working" and versions.get(part.key):
            note = f"Version {versions[part.key]}."
        out.append({"key": part.key, "name": part.name, "state": state, "note": note})
    return out


def trouble(part: dict) -> str | None:
    """The sentence for the owner's "needs you" list, or None when this part does not need anyone."""
    if part["state"] != "down":
        return None
    spec = next(p for p in PARTS if p.key == part["key"])
    return f"{spec.name} {spec.trouble}. It usually comes back by itself; if it does not, restart it."
