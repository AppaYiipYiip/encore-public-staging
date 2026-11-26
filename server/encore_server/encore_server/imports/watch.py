"""Telling a phone that a song of its import was STORED (N-43, docs/17 "Imports", the event `import.progress`).

The matching of an import tells its own numbers (`ImportService.match`) and so does Stop, but the keeper that STORES the songs is a different worker and said nothing:
`kept` moved silently, so a phone asked `GET imports` every 10 seconds for as long as an import was saving. This watch closes that. It does what `keep_watch.py`
does for a download, for the person's imports:

* **It reads the same world.** The feed of file changes (the keeper writes a row to it when it stores a song, and so does the Host's library scan when it finds a
  file for one) and the keep queue. Nothing is recounted while neither moved.
* **It works only for people who can hear it** (`Hub.persons`) **and only for imports that can still change** (`ImportService.following`): made in the last day, running,
  or with a matched song not stored yet, or with numbers the phone was not told yet.
* **It says only what is new.** The service remembers what it last told each person of each import, whoever told it (the matching, Stop, this watch), and a recount that
  gives the same numbers says nothing. The payload is the very `import.progress` the matching sends.
* **An event is never needed to be correct** (docs/17 section 4): a phone reads `GET imports` when it connects and when the app comes to the front; a push that is lost
  costs a few seconds. A server that does this says so in `info.features` (`import-kept`); a phone that finds the word missing keeps asking by itself.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from ..db import Database
from ..live import Hub
from ..scheduler import Scheduler

if TYPE_CHECKING:
    from .service import ImportService

log = logging.getLogger("encore_server.import_watch")


class ImportWatch:
    def __init__(self, db: Database, scheduler: Scheduler, hub: Hub, imports: ImportService, *, interval_s: float = 2.5) -> None:
        self._db = db
        self._scheduler = scheduler
        self._hub = hub
        self._imports = imports
        self._interval = interval_s
        self._token: tuple[object, ...] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _world(self) -> tuple[object, ...]:
        """Two small numbers that differ whenever a recount could give another answer: the feed of file changes and the keep queue."""
        with self._db.read() as conn:
            file_seq = conn.execute("SELECT COALESCE(MAX(seq), 0) AS seq FROM file_log").fetchone()["seq"]
        return (file_seq, self._scheduler.activity("keep"))

    def tick(self) -> int:
        """Recounts what may have moved for the people who are listening and tells what is new. Returns how many pushes were made."""
        people = self._hub.persons()
        if not people:
            return 0
        world = self._world()
        if world == self._token:
            return 0
        pushed = 0
        for person in people:
            for record in self._imports.following(person):
                if self._imports.publish_if_changed(person, record):
                    pushed += 1
        # Only after every person was recounted: a recount that raised is tried again on the next tick (the token stays the old one).
        self._token = world
        return pushed

    # ------------------------------------------------------------------ the clock

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="import-watch", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the clock must keep running
                log.exception("import watch tick failed")
