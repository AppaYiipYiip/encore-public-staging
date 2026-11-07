"""Background work asks YouTube one thing at a time, a few seconds apart (docs/04 section 5, ADR-R6).

An import of a hundred songs is a hundred look-ups and a hundred downloads from one address. Done at the speed of the machine that is a burst
no person makes, and a burst is what gets a home address refused for hours (2026-10-22: refused after about 35 look-ups in a few minutes). So
the matching and the keeping take turns: every background request reserves the next slot, a random few seconds after the previous one, and
waits for it. A person's tap is never paced: they asked, and one song is not a burst.

The gap is 3 to 9 s (6 s on average) since 7 Nov 2026, when the owner asked for 6 instead of 12 (it was 6 to 18 s, 12 on average, after the refusal of 22 Oct): about 600 requests an hour at most,
so a 200-song import saves in about 20 minutes. `ENCORE_YOUTUBE_PACE_S` changes the average (0 switches pacing off). The risk is the owner's to carry: the refusal of 22 Oct came after about
35 look-ups in a few minutes, which is what 6 s apart looks like; if YouTube refuses the address again, the pacer's rest (`rest.py`) already stops background work and a larger average is the way back.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable


class Pacer:
    def __init__(
        self,
        mean_s: float = 6.0,
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
