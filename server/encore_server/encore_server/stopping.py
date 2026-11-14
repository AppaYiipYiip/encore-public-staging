"""How long a stop of the server takes, in one place (audit B-129).

`docker stop` (so `encore update`, `encore stop` and a reboot of the host) sends SIGTERM and kills the container [DOCKER_GRACE_S] seconds later. A stop is
two phases that run one after the other, and the sum of their bounds is what has to stay under Docker's grace:

1. uvicorn lets the running requests finish ([UVICORN_GRACE_S]): live connections end at once (`api.live` listens to its socket), a stream or a download
   in flight is cut at the bound;
2. the lifespan shutdown stops the background threads (keep-watch, the yt-dlp updater, the library link, the scheduler's workers) with ONE shared
   budget ([LIFESPAN_STOP_S]) however many threads there are. Every one of them is told to stop first and only then waited for, and they are all daemon
   threads: a thread that is in the middle of a long look-up or download does not hold the stop, the process leaves without it (the work is picked up
   again at the next start, as after any crash).

Worst case: [UVICORN_GRACE_S] + [LIFESPAN_STOP_S] + the 0.2 s that each of the four stops is always given = 8.8 s, inside the 10 s with margin.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable

DOCKER_GRACE_S = 10.0
UVICORN_GRACE_S = 5.0
LIFESPAN_STOP_S = 3.0
#: What each stop is given at least, however little of the shared budget is left: enough to notice a thread that is already finishing.
MIN_JOIN_S = 0.2


def join_within(threads: Iterable[threading.Thread], budget_s: float) -> None:
    """Waits for [threads] to end, all of them together for at most [budget_s] (not [budget_s] each)."""
    deadline = time.monotonic() + budget_s
    for thread in threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))


def worst_case_stop_s(stops: int = 4) -> float:
    """The longest a stop can take by the bounds above: uvicorn's grace, the lifespan budget and the minimum each of [stops] stops is always given."""
    return UVICORN_GRACE_S + LIFESPAN_STOP_S + stops * MIN_JOIN_S
