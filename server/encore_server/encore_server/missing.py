"""What the server remembers about songs it cannot get (N-13; docs/17 "Songs the server cannot get", docs/18 `song_ref.missing_*`).

A song that the source answered "no" about is remembered on its ref for a window, so that

* the next tap, anybody's, is refused at once: no look-up at YouTube and no nine seconds of waiting (the owner's "Lofi For Focus", 7 Nov 2026);
* the app can mark the song before it is tapped: a ref carries it (`unavailable`), and `POST /refs/unavailable` answers for songs a phone has no ref
  for yet (every row of a Search is a catalogue song).

**Only a "no" that was ANSWERED is remembered.** The reasons are `not_found` (the search answered and nothing acceptable matched), `removed` (the upload is
gone, and one search for another came back empty) and `age_restricted` (the only copy needs an age check; its own reason so that a sign-in option can
clear those without voiding the others, D-67). Everything that may pass is never remembered: YouTube refusing or resting, a timeout, the network, a search
that could not be made (`search_failed`, B-122), a file too big.

There is no background sweep (the rule is at most ten look-ups at YouTube in a test run, and a stranger's server is not made to spend them): the only retry
is a person's tap after the window, which does one real search and either clears the memory or starts a new window.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .sources.youtube.scoring import MATCHER_REVISION as MATCHER_REVISION  # re-exported: `refs` stamps it on a memory
from .sources.youtube.stream import MESSAGES

#: How long a "no" is believed, counted from the LAST try: a catalogue gains uploads (a new release is on YouTube a few days later) and the matcher
#: improves, so a song a source does not have today is tried again in a week. One window for every reason: a retry is one search, once a week, and only
#: when somebody taps the song.
WINDOW_MS = 7 * 24 * 3600 * 1000

REASONS = ("not_found", "removed", "age_restricted")
#: The reason -> the code of the stream's error (`sources/youtube/stream.py`), so a remembered refusal is answered exactly as a fresh one is.
CODE_OF = {"not_found": "not_found", "removed": "unavailable", "age_restricted": "age_restricted"}
REASON_OF = {code: reason for reason, code in CODE_OF.items()}


@dataclass(frozen=True)
class Standing:
    """What the ref remembers. `live` is whether it is still believed: inside the window, and made by the matcher that is running (an older matcher's
    "not found" says nothing about what this one would find)."""

    reason: str
    since: int
    tried_at: int
    live: bool

    @property
    def retry_after(self) -> int:
        return self.tried_at + WINDOW_MS

    @property
    def code(self) -> str:
        return CODE_OF[self.reason]

    @property
    def message(self) -> str:
        return MESSAGES[self.code]


def standing_of(row: sqlite3.Row | dict[str, Any], now_ms: int) -> Standing | None:
    """The memory of a `song_ref` row (it must carry the `missing_*` columns), or `None` when it remembers nothing."""
    reason = row["missing_reason"]
    if reason not in REASONS:
        return None
    tried = int(row["missing_tried_at"] or 0)
    live = row["missing_rev"] == MATCHER_REVISION and now_ms < tried + WINDOW_MS
    return Standing(reason=reason, since=int(row["missing_at"] or tried), tried_at=tried, live=live)


def public(standing: Standing | None) -> dict[str, Any] | None:
    """The API's shape of a live memory (`None` for none, or for one that is no longer believed). The sentence is the server's own, the one the stream
    answers with, so that a phone never has to know the words."""
    if standing is None or not standing.live:
        return None
    return {
        "reason": standing.reason,
        "message": standing.message,
        "since": standing.since,
        "retryAfter": standing.retry_after,
    }
