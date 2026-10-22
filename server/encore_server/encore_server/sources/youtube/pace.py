"""Background work asks YouTube one thing at a time, a few seconds apart (docs/04 section 5, ADR-R6).

An import of a hundred songs is a hundred look-ups and a hundred downloads from one address. Done at the speed of the machine that is a burst
no person makes, and a burst is what gets a home address refused for hours (2026-10-22: refused after about 35 look-ups in a few minutes). So
the matching and the keeping take turns: every background request reserves the next slot, a random few seconds after the previous one, and
waits for it. A person's tap is never paced: they asked, and one song is not a burst.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable


class Pacer:
    def __init__(
        self,
        mean_s: float = 12.0,
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
