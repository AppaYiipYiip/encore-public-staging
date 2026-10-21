"""Making everybody's lists, one person after another, politely (docs/47 section 4 step 6).

Nightly for everybody; and soon for a person who has just played enough to have something to show. A public service that says "slow down"
ends the run: the lists from last time stay (and say when they were built) and the next run tries again. Nothing here is shown to the
owner except how many people were done.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Callable

from .build import Result, build
from .library import LibraryUnavailable, open_snapshot
from .sources import Sources, Throttled
from .store import Store

log = logging.getLogger("encore_recs.builder")

HOUR = 3600.0
#: A list younger than this is not made again by the nightly run.
FRESH_S = 20 * HOUR
#: A person who has no list yet is tried at most this often (a person with too little listening would otherwise be asked about every pass).
RETRY_S = 1 * HOUR


class Builder:
    def __init__(self, *, store: Store, sources: Sources, database_dir: Path, scratch: Path | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._sources = sources
        self._dir = database_dir
        self._scratch = scratch
        self._clock = clock

    def enabled(self) -> bool:
        return self._store.setting("recs", "on") == "on"

    def run(self, *, everyone: bool, force: bool = False) -> dict:
        """Makes lists. [everyone]: the nightly pass (every person whose list is older than 20 hours, or every person at all when [force], which
        is what the owner's "rebuild now" means); otherwise only people who have none.
        Returns `{"people": n, "built": n, "empty": n, "throttled": bool, "unreadable": bool}` and remembers it as the last run."""
        summary = {"at": self._clock(), "people": 0, "built": 0, "empty": 0, "throttled": False, "unreadable": False, "everyone": everyone}
        try:
            with open_snapshot(self._dir, self._scratch) as reader:
                people = reader.people()
                summary["people"] = len(people)
                library = reader.library()
                for person in people:
                    existing = self._store.build_of(person)
                    now = self._clock()
                    if everyone:
                        if existing is not None and not force and now - existing["builtAt"] < FRESH_S:
                            continue
                    else:
                        # between nights: only people with no real list yet, and not more often than once an hour
                        first = existing is None or existing["state"] != "ready"
                        if not first or now - float(self._store.setting(f"tried:{person}", "0") or 0) < RETRY_S:
                            continue
                    self._store.set_setting(f"tried:{person}", str(now))
                    try:
                        result = build(person, reader.seeds(person, now), library, self._sources, self._store.hidden_for(person),
                                       self._store.seen_releases(person), now)
                    except Throttled as error:
                        log.warning("a public service said slow down (%s); the rest waits for the next run", error)
                        summary["throttled"] = True
                        break
                    self._keep(person, result, existing)
                    summary["built" if result.state == "ready" else "empty"] += 1
        except LibraryUnavailable as error:
            log.warning("cannot read the music server's database: %s", error)
            summary["unreadable"] = True
        self._store.set_setting("last_run", json.dumps(summary))
        return summary

    def _keep(self, person: str, result: Result, existing: dict | None) -> None:
        if result.state == "empty" and existing is not None and existing["state"] == "ready":
            return  # a person who stopped listening for a while keeps their last lists
        self._store.save_build(person, result, self._clock())

    def last_run(self) -> dict | None:
        raw = self._store.setting("last_run", "")
        return json.loads(raw) if raw else None
