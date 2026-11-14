"""Telling a phone how its downloads are going without being asked (P2-22 part 1b, docs/17 "Keep progress").

A phone that is downloading a playlist says which pinned groups it wants to watch (`PUT /keep/watch`). From then on this module recounts them when
something may have changed and pushes `keep.progress {groups, youtube, serverTime}` to **that device only**, at most once every few seconds, and only
when the answer is different from the one the device already has.

* **The pushed answer is `keep_progress.progress()` itself**, called for that person: every rule of that answer (what the person can see, the
  buckets that add up, the Host's or the member's sentence) is the same here and cannot drift. A group the person does not have never appears.
* **An event is never needed to be correct** (docs/17 section 4). A watch lives in memory; when the device reconnects it says what it watches again
  and gets the current answer back in the reply. A lost event costs a few seconds, never a wrong number.
* **Nothing is recounted when nothing moved.** Each tick reads four small numbers (the keep queue, the change log, the feed of file changes, YouTube's
  rest); only when one of them differs are the watching devices recounted. The file feed is there because a song can become ready (or lose its file)
  without the keeper: the Host's library scan attaches a file the same way, and every such change writes one row to it.
* **A watch is "due" until it has been recounted successfully.** A recount that failed, or a watch that was replaced while it was being recounted, is
  tried again on the next tick even if nothing else moved; a device is never left on a number the server has not checked.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .db import Database
from .ids import now_ms
from .keep_progress import Group, progress
from .live import Hub
from .scheduler import Scheduler

log = logging.getLogger("encore_server.keep_watch")

#: How long a device that is not connected keeps its watch before it is forgotten (it says again what it watches when it reconnects).
GONE_FOREVER_S = 300.0
#: YouTube's rest is a count-down; it is only news when its END moves by more than this.
_REST_STEP_S = 30


def _now() -> float:
    """The wall clock; a function so that a test can hold it still."""
    return time.time()


def _rest_ends(youtube: dict[str, Any]) -> int:
    """When YouTube's rest ends, to the half minute (0 when it is not resting), so the count-down itself is not news."""
    if youtube.get("state") != "resting":
        return 0
    return round((_now() + float(youtube.get("resumesInSec") or 0)) / _REST_STEP_S)


def fingerprint(groups: list[dict[str, Any]], youtube: dict[str, Any]) -> str:
    """What a device would see change: the groups, YouTube's state, and when a rest ends."""
    text = json.dumps([groups, youtube.get("state"), _rest_ends(youtube)], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(eq=False)
class _Watch:
    groups: list[Group]
    #: The fingerprint of the last answer the device was given (in a reply or in a push).
    shown: str
    #: To be recounted on the next tick. A new watch starts due (the world may have moved between its reply and its registration, and one extra recount
    #: that finds the same answer pushes nothing); the flag is cleared only by a recount that succeeded.
    due: bool = True
    gone_since: float | None = None


class KeepWatch:
    def __init__(
        self,
        db: Database,
        scheduler: Scheduler,
        hub: Hub,
        youtube_status: Callable[[], dict[str, Any]],
        *,
        interval_s: float = 2.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = db
        self._scheduler = scheduler
        self._hub = hub
        self._youtube = youtube_status
        self._interval = interval_s
        self._clock = clock
        self._watches: dict[tuple[str, str], _Watch] = {}
        self._lock = threading.Lock()
        self._token: tuple[object, ...] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ what a device asks for

    def watch(self, person: str, device: str, groups: list[Group], shown: str) -> None:
        """This device now watches exactly these groups (an empty list stops watching). [shown] is the fingerprint of the answer it was just given."""
        with self._lock:
            if groups:
                self._watches[(person, device)] = _Watch(list(groups), shown)
            else:
                self._watches.pop((person, device), None)

    def watching(self) -> int:
        with self._lock:
            return len(self._watches)

    # ------------------------------------------------------------------ the recount

    def _world(self) -> tuple[object, ...]:
        """Three small numbers that differ whenever a recount could give a different answer."""
        with self._db.read() as conn:
            log_seq = conn.execute("SELECT COALESCE(MAX(seq), 0) AS seq FROM change_log").fetchone()["seq"]
            file_seq = conn.execute("SELECT COALESCE(MAX(seq), 0) AS seq FROM file_log").fetchone()["seq"]
        youtube = self._youtube()
        return (self._scheduler.activity("keep"), log_seq, file_seq, youtube.get("state"), _rest_ends(youtube))

    def _is_host(self, person: str) -> bool:
        with self._db.read() as conn:
            row = conn.execute("SELECT role FROM person WHERE id = ?", (person,)).fetchone()
        return row is not None and row["role"] == "owner"

    def tick(self) -> int:
        """Recounts what may have moved and pushes it to the devices it changes for. Returns how many pushes were made."""
        with self._lock:
            items = list(self._watches.items())
        if not items:
            return 0
        world = self._world()
        if world != self._token:
            self._token = world
            with self._lock:
                for watch in self._watches.values():
                    watch.due = True
        now = self._clock()
        pushed = 0
        for (person, device), watch in items:
            if not self._hub.connected(person, device):
                if watch.gone_since is None:
                    watch.gone_since = now
                elif now - watch.gone_since > GONE_FOREVER_S:
                    with self._lock:
                        if self._watches.get((person, device)) is watch:
                            del self._watches[(person, device)]
                continue
            watch.gone_since = None
            if not watch.due:
                continue
            try:
                answer = progress(self._db, self._scheduler, person, host=self._is_host(person), groups=watch.groups)
            except Exception:  # noqa: BLE001 - one device's recount failing must not stop the others, nor the next tick; it stays due
                log.exception("could not recount the downloads of a device")
                continue
            youtube = self._youtube()
            shown = fingerprint(answer, youtube)
            with self._lock:
                if self._watches.get((person, device)) is not watch:
                    continue  # replaced (or stopped) while it was counted: those groups are not the device's any more; the new watch is due
                watch.due = False
                if shown == watch.shown:
                    continue
                watch.shown = shown
                self._hub.publish(
                    person,
                    {"type": "keep.progress", "groups": answer, "youtube": youtube, "serverTime": now_ms()},
                    only_device=device,
                )
            pushed += 1
        return pushed

    # ------------------------------------------------------------------ the clock

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="keep-watch", daemon=True)
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
                log.exception("keep watch tick failed")
