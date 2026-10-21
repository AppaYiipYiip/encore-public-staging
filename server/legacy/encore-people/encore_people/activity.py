"""Friend activity (docs/35 section 4, ADR-087): what the people on this server who chose to share are playing right now.

* **Opt-in.** Nobody is shared until they say so; the choice is the only thing kept on disk (a few names in a small file).
* **Last song only, memory only.** One entry per person, replaced by the next, gone after a restart. Nothing about what was played is ever
  written to disk, so there is no listening history to leak.
* **Expires.** A playing entry after 30 minutes, a paused one after 10.
* **Small.** Title, artist, album, a cover address and the time it started. No song id, no path, nothing that points into a private library.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

EXPIRY_PLAYING_S = 30 * 60
EXPIRY_PAUSED_S = 10 * 60
MAX_PEOPLE = 200
_MAX_TEXT = 200
_MAX_URL = 500
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Entry:
    username: str
    title: str
    artist: str
    album: str
    cover_url: str | None
    state: str  # playing | paused
    since: float  # when it started (or was last reported)


def _clean(value: object, limit: int = _MAX_TEXT) -> str:
    """Text a person typed or a file's tags hold: control characters become spaces, runs of spaces collapse, length is bounded."""
    if not isinstance(value, str):
        return ""
    return " ".join(_CONTROL.sub(" ", value).split())[:limit]


def _clean_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) > _MAX_URL or not re.match(r"^https?://[^\s]+$", value, re.IGNORECASE):
        return None
    return value


class Activity:
    def __init__(self, sharing_file: Path, *, clock: Callable[[], float] = time.time) -> None:
        self._file = sharing_file
        self._clock = clock
        self._lock = threading.Lock()
        self._sharing: set[str] = set(self._load())
        self._entries: dict[str, Entry] = {}
        # When each person's app last spoke to us: it keeps a long song alive without moving the time it started.
        self._touched: dict[str, float] = {}

    # ------------------------------------------------------------------ the one thing on disk: who chose to share
    def _load(self) -> list[str]:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            names = data.get("sharing", []) if isinstance(data, dict) else []
            return [n for n in names if isinstance(n, str)]
        except (OSError, ValueError):
            return []  # missing or damaged: nobody shares (the safe answer)

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"sharing": sorted(self._sharing)}), encoding="utf-8")
        tmp.replace(self._file)

    def is_sharing(self, user: str) -> bool:
        with self._lock:
            return user in self._sharing

    def set_sharing(self, user: str, on: bool) -> None:
        with self._lock:
            if on:
                self._sharing.add(user)
            else:
                self._sharing.discard(user)
                self._entries.pop(user, None)  # off means gone, at once
            self._save()

    # ------------------------------------------------------------------ memory only
    def report(self, user: str, song: object) -> bool:
        """`True` when the entry was kept. Ignored (and `False`) for a person who has not opted in, or a report without a title."""
        if not isinstance(song, dict):
            return False
        title = _clean(song.get("title"))
        if not title:
            return False
        state = song.get("state")
        entry = Entry(
            username=user,
            title=title,
            artist=_clean(song.get("artist")),
            album=_clean(song.get("album")),
            cover_url=_clean_url(song.get("coverUrl")),
            state=state if state in ("playing", "paused") else "paused",
            since=self._clock(),
        )
        with self._lock:
            if user not in self._sharing:
                return False
            previous = self._entries.get(user)
            if previous and (previous.title, previous.artist, previous.state) == (entry.title, entry.artist, entry.state):
                # The same song reported again: it is still alive, and it started when it started.
                entry = Entry(user, entry.title, entry.artist, entry.album, entry.cover_url, entry.state, previous.since)
            self._touched[user] = self._clock()
            self._entries[user] = entry
            if len(self._entries) > MAX_PEOPLE:
                oldest = min(self._entries, key=lambda name: self._touched.get(name, 0.0))
                self._entries.pop(oldest, None)
                self._touched.pop(oldest, None)
        return True

    def clear(self, user: str) -> None:
        with self._lock:
            self._entries.pop(user, None)
            self._touched.pop(user, None)

    def others(self, viewer: str) -> list[Entry]:
        now = self._clock()
        with self._lock:
            alive = []
            for name, entry in list(self._entries.items()):
                age = now - self._touched.get(name, entry.since)
                limit = EXPIRY_PLAYING_S if entry.state == "playing" else EXPIRY_PAUSED_S
                if age > limit:
                    self._entries.pop(name, None)
                    self._touched.pop(name, None)
                elif name != viewer and name in self._sharing:
                    alive.append(entry)
        return sorted(alive, key=lambda e: e.since, reverse=True)
