"""Background work asks YouTube one thing at a time, a few seconds apart (docs/04 section 5, ADR-R6).

An import of a hundred songs is a hundred look-ups and a hundred downloads from one address. Done at the speed of the machine that is a burst
no person makes, and a burst is what gets a home address refused for hours (2026-10-22: refused after about 35 look-ups in a few minutes). So
the matching and the keeping take turns: every background request reserves the next slot, a random few seconds after the previous one, and
waits for it. A person's tap is never paced: they asked, and one song is not a burst.

The Host picks the average, 3 to 8 s, in `.env` (`ENCORE_YOUTUBE_PACE_S`, `config.pace_from`); 4 s unless they say otherwise (D-67, 7 Nov 2026; it was 12, then 6 the same day). Each gap is random between half and one and a half
times the average. A 200-song import saves in about 10 minutes at 3, 13 at 4 and 27 at 8 (measured at 1.5 s with two workers: 24 songs a minute, so from 3 s on the pace is what limits the speed, not the workers). The risk is
the owner's to carry: the refusal of 22 Oct came after about 35 look-ups in a few minutes (anonymous); if YouTube refuses the address again, the rest (`rest.py`) stops background work for 30 minutes and doubles it on every further
refusal, and a larger average is the way back.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable


class Pacer:
    def __init__(
        self,
        mean_s: float = 4.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._low = max(0.0, mean_s * 0.5)
        self._high = max(self._low, mean_s * 1.5)
        self._clock = clock
        self._sleep = sleep
        self._uniform = uniform
        self._lock = threading.Lock()
        self._next = 0.0

    def wait_turn(self) -> float:
        """Blocks until this caller's slot; returns how long it waited. Slots are handed out in the order callers arrive."""
        with self._lock:
            now = self._clock()
            start = max(now, self._next)
            self._next = start + self._uniform(self._low, self._high)
        delay = start - now
        if delay > 0:
            self._sleep(delay)
        return max(0.0, delay)
