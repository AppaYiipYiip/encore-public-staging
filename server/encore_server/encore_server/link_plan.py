"""When the library link runs (P3-35, audit B-60).

The link (`scanner.link_library`) used to run on an hourly timer and nothing else: music added to the folder was seen by the music server within
seconds and by Encore at the next tick, anywhere from none to sixty minutes later (47 in the audit, which is where the tick happened to fall). The
music server says when it has finished a scan (`getScanStatus`: `scanning`, `count`, `lastScan`), so the link follows that, and the tick stays as the
safety net for what a scan status cannot say (a renamed tag, a music server that cannot answer).

This module is only the decision, with no thread and no clock of its own: the time and the music server's scan status go in, a [Step] comes out.
Every rule below has a test with a made-up clock (`tests/test_link_plan.py`); `scanner.LibraryLinker` is the thin loop that asks and acts.

* **The tick** (errands, then the whole pass, prune included) runs `every_s` after the end of the last tick, and `first_after_s` after the start.
  A tick never begins while the music server is scanning (the answer of a scan in progress is partial): it waits, looking every `busy_s`, and runs
  anyway after `scan_wait_max_s` so that a scan which never ends cannot stop it for ever.
* **A pass after a scan** (the link alone: no errands, which ask the catalogue and themselves start scans) runs when the music server is not scanning
  and its status is not the one the last complete pass began with. It is looked for every `watch_s` (one small request).
* **The floor.** Not sooner than `min_gap_s` after the last pass ended, and not sooner than `spread` times the length of that pass (so a pass of 100 s
  is followed by one no sooner than 900 s later: a tenth of the time at the most; the tick comes before a longer floor ends). A person copying an album makes a
  scan finish every few seconds: they are one pass after the floor, and the last status is the one it records. A library of 200,000 songs, whose pass
  is long, throttles itself.
* **A poke** (a person asked) runs at once, floor or not, but not during a scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Kind = Literal["tick", "scan", "poke"]


@dataclass(frozen=True)
class Signature:
    """What a finished scan leaves in the status: how many songs the music server has, and when it last finished. Either moving means the files changed
    (`count` for added and removed files, `lastScan` also for a swapped album or a retag)."""

    count: int | None
    last_scan: str | None


@dataclass(frozen=True)
class Step:
    """What to do now: run a pass of this [run] kind, or (`None`) look again in [wait_s] seconds. [seen] is the status the decision was made on."""

    run: Kind | None
    wait_s: float
    seen: Signature | None = None


def signature_of(status: dict[str, Any] | None) -> Signature | None:
    """The status as a signature; `None` when the music server could not say, or says neither a count nor a time (then nothing can be compared)."""
    if status is None:
        return None
    count = status.get("count")
    last = status.get("lastScan")
    found = Signature(count if isinstance(count, int) else None, str(last) if last else None)
    return None if found.count is None and found.last_scan is None else found


class LinkPlan:
    def __init__(
        self,
        *,
        first_after_s: float = 20.0,
        every_s: float = 3600.0,
        min_gap_s: float = 60.0,
        spread: float = 9.0,
        watch_s: float = 30.0,
        busy_s: float = 5.0,
        scan_wait_max_s: float = 3 * 3600.0,
    ) -> None:
        self._first = first_after_s
        self._every = every_s
        self._min_gap = min_gap_s
        self._spread = spread
        self._watch = max(0.001, watch_s)
        self._busy = max(0.001, busy_s)
        self._scan_wait_max = scan_wait_max_s
        self._next_tick = first_after_s
        self._ticked = False
        self._linked: Signature | None = None
        self._last_end: float | None = None
        self._last_took = 0.0
        self._poked = False

    def poke(self) -> None:
        """A person asked for a pass: it is kept until one has run (a scan in progress delays it, never loses it)."""
        self._poked = True

    def begin(self, now: float) -> None:
        """The loop starts: the first tick is [first_after_s] away."""
        self._next_tick = now + self._first

    def next(self, now: float, status: dict[str, Any] | None) -> Step:
        """The decision at [now], given the music server's scan [status] (`None`: it could not say)."""
        scanning = bool(status.get("scanning")) if status is not None else False
        seen = signature_of(status)
        until_tick = max(0.0, self._next_tick - now)

        if now >= self._next_tick and (not scanning or now - self._next_tick >= self._scan_wait_max):
            self._poked = False  # the tick links everything a poke would
            return Step("tick", 0.0, seen)
        if scanning:
            return Step(None, min(self._busy, until_tick) if until_tick else self._busy)
        if self._poked:
            self._poked = False
            return Step("poke", 0.0, seen)
        if self._ticked and seen is not None and seen != self._linked:
            ready_in = self._ready_at() - now
            if ready_in <= 0:
                return Step("scan", 0.0, seen)
            return Step(None, min(ready_in, until_tick or ready_in, self._watch))
        return Step(None, min(self._watch, until_tick) if until_tick else self._watch)

    def finished(self, step: Step, *, started: float, ended: float, complete: bool) -> None:
        """The pass the [step] asked for has ended. A complete pass has linked everything the music server said before it began."""
        self._last_end = ended
        self._last_took = max(0.0, ended - started)
        if step.run == "tick":
            self._ticked = True
            self._next_tick = ended + (self._every if complete else min(self._every, 120.0))
        if complete and step.seen is not None:
            self._linked = step.seen

    def failed(self, step: Step, *, at: float) -> None:
        """The pass raised: the tick tries again soon, a pass after a scan after the floor."""
        self._last_end = at
        self._last_took = 0.0
        if step.run == "tick":
            self._ticked = True
            self._next_tick = at + min(self._every, 300.0)

    def _ready_at(self) -> float:
        if self._last_end is None:
            return 0.0
        gap = max(self._min_gap, self._spread * self._last_took)
        return self._last_end + gap
