"""What an add-on is (docs/35 section 3): one value per optional thing, read by the admin routes, the `encore addon` command and the docs check alike."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..config import Settings

RUNS = "runs"
YOURS = "yours"
OFF = "off"
STATES = (RUNS, YOURS, OFF)


@dataclass(frozen=True)
class AddOn:
    #: kebab-case, never reused
    id: str
    title: str
    #: two plain sentences, no "Docker", "port", "container", "Funnel"
    summary: str
    #: which of runs / yours / off the add-on allows
    states: tuple[str, ...]
    default: str
    #: what the server is doing NOW, from the settings it started with
    running: Callable[[Settings], str]
    #: the board item that builds it, or None when it is built
    planned: str | None = None
    #: why only the computer can change it today (until the helper exists), or None
    host_managed: str | None = None
    #: other add-ons that must not be off
    needs: tuple[str, ...] = ()
    #: the sentence shown before it is switched on, and its version (a change of words raises it and the Host is asked again)
    risk_text: str | None = None
    risk_text_version: int = 1
    #: the boolean field of `Settings` a stored choice sets when the server starts (None: nothing the server reads yet)
    setting: str | None = None
    #: the word the app reads in `GET info` `features` while the add-on is on
    feature: str | None = None


def switch(setting: str) -> Callable[[Settings], str]:
    """The state of an add-on that is one true/false field of the settings."""
    return lambda settings: RUNS if getattr(settings, setting) else OFF
