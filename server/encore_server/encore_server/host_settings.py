"""The Host's own choices (docs/35 section 4): typed, allow-listed by the add-on manifest, in the `host_setting` table.

Order of truth: the Host's stored choice, else the environment variable, else the manifest's default. A choice is stored the moment it is made and **takes effect when
the server next starts** (`overlay`): nothing in the server reads these settings twice, and a setting that did would have to be changed in every place that reads it.
The table is not `setting` (the server's internal state: its identity private key and the key that signs song addresses); no route reads or writes that one.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .addons import ADDONS, RUNS
from .config import Settings
from .db import Database
from .ids import now_ms

KEY_PREFIX = "addon."
BOOT_PREFIX = "boot."


def addon_key(addon_id: str) -> str:
    return f"{KEY_PREFIX}{addon_id}"


class HostSettings:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str) -> str | None:
        with self._db.read() as conn:
            row = conn.execute("SELECT value FROM host_setting WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row is not None else None

    def put(self, key: str, value: str, by: str) -> None:
        with self._db.tx() as conn:
            conn.execute(
                "INSERT INTO host_setting (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (key, value, now_ms(), by),
            )

    def record_boot(self, settings: Settings) -> None:
        """What the server is doing, written when it starts (`boot.<id>`): the `encore addon` command is another process and cannot see it, and \"stored, not yet running\" is
        the difference between a choice and this."""
        with self._db.tx() as conn:
            for addon in ADDONS:
                conn.execute(
                    "INSERT INTO host_setting (key, value, updated_at, updated_by) VALUES (?, ?, ?, 'server')"
                    " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                    (f"{BOOT_PREFIX}{addon.id}", addon.running(settings), now_ms()),
                )

    def boot_states(self) -> dict[str, str]:
        with self._db.read() as conn:
            rows = conn.execute("SELECT key, value FROM host_setting WHERE key LIKE ?", (f"{BOOT_PREFIX}%",)).fetchall()
        return {str(r["key"])[len(BOOT_PREFIX) :]: str(r["value"]) for r in rows}

    def addon_states(self) -> dict[str, str]:
        """The stored state of every add-on the Host has chosen for (an add-on never chosen for is not in the answer)."""
        with self._db.read() as conn:
            rows = conn.execute("SELECT key, value FROM host_setting WHERE key LIKE ?", (f"{KEY_PREFIX}%",)).fetchall()
        return {str(r["key"])[len(KEY_PREFIX) :]: str(r["value"]) for r in rows}


def overlay(settings: Settings, db: Database) -> Settings:
    """The settings the server runs with: the environment's, with the Host's stored choices put over the add-ons that are built and that the server reads at start."""
    chosen = HostSettings(db).addon_states()
    changes: dict[str, Any] = {}
    for addon in ADDONS:
        if addon.setting is None or addon.planned or addon.host_managed:
            continue
        state = chosen.get(addon.id)
        if state in addon.states:
            changes[addon.setting] = state == RUNS
    return replace(settings, **changes) if changes else settings
