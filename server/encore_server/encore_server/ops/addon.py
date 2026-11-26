"""The add-ons as an operation: list them, change one's state (docs/35). The answer is counts, states and sentences: never a key, a password or a path."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..addons import ADDONS, OFF, RUNS, AddOn, by_id
from ..db import Database
from ..errors import ApiError
from ..host_settings import HostSettings, addon_key

#: What the server is doing now, for an add-on: the route knows it from the settings it runs with, the command from what the server recorded when it started.
Running = Callable[[AddOn], str]


def describe(addon: AddOn, running_of: Running, chosen: dict[str, str]) -> dict[str, Any]:
    running = running_of(addon)
    stored = chosen.get(addon.id)
    state = stored if stored in addon.states else running
    return {
        "id": addon.id,
        "title": addon.title,
        "summary": addon.summary,
        "state": state,
        "running": running,
        # a choice that is stored but not yet what the server is doing: it takes effect when the server next starts
        "restartNeeded": state != running and not addon.planned and not addon.host_managed,
        "states": list(addon.states),
        "default": addon.default,
        "planned": addon.planned,
        "hostManaged": addon.host_managed,
        "needs": list(addon.needs),
        "riskText": addon.risk_text,
        "riskTextVersion": addon.risk_text_version if addon.risk_text else None,
    }


def list_addons(db: Database, running_of: Running) -> list[dict[str, Any]]:
    chosen = HostSettings(db).addon_states()
    return [describe(a, running_of, chosen) for a in ADDONS]


def set_state(
    db: Database, running_of: Running, addon_id: str, state: object, *, by: str, risk_text_version: object = None
) -> dict[str, Any]:
    """Stores the Host's choice for one add-on. Refuses, in a sentence, what cannot be: an add-on that does not exist, one that is not built yet, one only the computer can
    change today, a state it does not have, one whose need is off, and a switch-on whose risk text the Host has not been shown in its present words."""
    addon = by_id(addon_id)
    if addon is None:
        raise ApiError("not_found", "There is no such add-on.")
    if addon.planned:
        raise ApiError("conflict", f"{addon.title} is not built yet ({addon.planned}).")
    if addon.host_managed:
        raise ApiError("conflict", addon.host_managed)
    if not isinstance(state, str) or state not in addon.states:
        raise ApiError("validation", f"{addon.title} can be: {', '.join(addon.states)}.")
    chosen = HostSettings(db).addon_states()
    describe_before = describe(addon, running_of, chosen)
    if state == OFF:
        # what needs this one must not be left running without it
        for other in ADDONS:
            if addon.id in other.needs and describe(other, running_of, chosen)["state"] != OFF:
                raise ApiError(
                    "conflict", f"Turn off “{other.title}” first: it needs {addon.title}.", details={"neededBy": other.id}
                )
    if state != OFF:
        for need in addon.needs:
            needed = by_id(need)
            if needed is not None and describe(needed, running_of, chosen)["state"] == OFF:
                raise ApiError("conflict", f"Turn on “{needed.title}” first: {addon.title} needs it.", details={"needs": need})
        # The risk is shown before it is switched on, in the words of this version; a change of the words asks again (docs/35 rule 1).
        if addon.risk_text and describe_before["state"] != state and risk_text_version != addon.risk_text_version:
            raise ApiError(
                "validation",
                "Read the warning for this one before switching it on.",
                details={"riskText": addon.risk_text, "riskTextVersion": addon.risk_text_version},
            )
    HostSettings(db).put(addon_key(addon.id), state, by)
    chosen[addon.id] = state
    return describe(addon, running_of, chosen)


__all__ = ["RUNS", "describe", "list_addons", "set_state"]
