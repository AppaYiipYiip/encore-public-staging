"""Making the next songs of a queue ready before the person presses Next (P1-04, audit B-107).

A song that YouTube has to be asked about costs 2.0 to 2.3 s before its first byte; the player only asks when the song is wanted, so a Next to a song
the server has not seen waited that long (the app's own span read 2424 and 2784 ms). The player now tells the server which songs are next
(`POST /refs/prepare`), and the server does what a play does up to the first byte: it finds the upload and asks for the stream's address, and keeps both
(the address for most of an hour). A tap that comes later finds them at once.

This is background work in the interactive pool (`scheduler.py`: kind `prepare`, one item per song however many people want it). It is polite on purpose,
because a burst of requests is what got the owner's home address refused for hours (22 Oct):

* it waits its turn at the background pacer like every other request nobody is waiting for (`sources/youtube/pace.py`);
* it asks nothing while YouTube is being given a rest;
* it asks nothing for a song the server already keeps or whose address it already has;
* at most [PER_HOUR] songs are prepared in an hour, so skipping through a long list cannot turn into a burst; the cap is the server's, not a person's.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

from . import refs
from .db import Database
from .scheduler import GiveUp, WorkItem
from .sources.youtube.errors import DownloadError
from .sources.youtube.source import Wanted, wanted_from_ref
from .sources.youtube.stream import StreamError

log = logging.getLogger("encore_server.prepare")

#: How many songs the server prepares in an hour. A person listening in order prepares about one song a song played (the second one ahead was prepared
#: when the one before it started); skipping fast prepares more, and the pacer already spaces the asking, so this is only the last stop.
PER_HOUR = 40


class Source(Protocol):
    def is_ready(self, wanted: Wanted) -> bool: ...

    def resting_for(self) -> float: ...

    def prepare(self, wanted: Wanted) -> bool: ...


class Preparer:
    def __init__(
        self,
        database: Database,
        source: Source,
        *,
        per_hour: int = PER_HOUR,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = database
        self._source = source
        self._per_hour = per_hour
        self._clock = clock
        self._started: deque[float] = deque()

    def _may_start(self) -> bool:
        now = self._clock()
        while self._started and now - self._started[0] >= 3600.0:
            self._started.popleft()
        if len(self._started) >= self._per_hour:
            return False
        self._started.append(now)
        return True

    def handle(self, item: WorkItem) -> None:
        """Prepares the song `item.ref`. What deliberately does nothing (the song is kept or ready, YouTube is resting, the hour's songs are done) returns
        normally: nothing failed. What went wrong raises [GiveUp]: a prepare that did not happen is not tried again (the person has pressed Next by then,
        and the song is looked up as before)."""
        with self._db.read() as conn:
            try:
                ref = refs.get_ref(conn, item.ref)
            except Exception as error:  # noqa: BLE001 - a song that is not known cannot be prepared
                raise GiveUp("the song is not known") from error
        if _kept(ref):
            return
        wanted = wanted_from_ref(ref)
        # A song that needs no asking costs no slot of the hour, and nothing is asked while YouTube rests (the slot is taken last).
        if self._source.is_ready(wanted):
            return
        if self._source.resting_for() > 0:
            log.info("prepare: YouTube is resting; %s is looked up when it is played", item.ref)
            return
        if not self._may_start():
            log.info(
                "prepare: %d songs were prepared in the last hour; %s is looked up when it is played", self._per_hour, item.ref
            )
            return
        try:
            found = self._source.prepare(wanted)
        except DownloadError as error:
            raise GiveUp(error.code) from error
        except StreamError as error:
            raise GiveUp(error.code) from error
        if not found:
            raise GiveUp("no upload found")


def _kept(ref: dict[str, Any]) -> bool:
    file = ref.get("file")
    return bool(file and file.get("navidromeSongId"))
