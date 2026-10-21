"""What was already found and fetched, kept so that the next request for the same song costs nothing (`docs/39` F16).

Measured on the reference server: search 2.1 s, the streams 2.5 s, download 9.6 s for one song, on a line that carries 450 KB/s. Two
small memories remove what a person would wait for twice:

* **what was found**: `(artist, title)` -> which upload it was (kept 30 days, across restarts): no search;
* **the audio itself**: the finished download, untouched, by upload id (kept while it fits a size limit, oldest first): no streams
  request and no download. A person's copy is made from it, so each person tags their own file; a link would let one person's tags
  change another's song.

Both are service-internal: nobody can list or fetch them.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger("encore_fetch")

_ID = re.compile(r"[A-Za-z0-9_-]{6,20}")


def song_key(artist: str, title: str, duration_s: int | None) -> str:
    """The same song asked for in slightly different words is one key; a different length (a live cut) is another."""
    def words(s: str) -> str:
        return re.sub(r"[^0-9a-z]+", " ", s.casefold()).strip()
    return f"{words(artist)}|{words(title)}|{(duration_s or 0) // 8}"


class ResolveCache:
    """`song_key` -> `{video_id, title, duration_s, at}`, in one small JSON file."""

    def __init__(self, path: Path, clock: Callable[[], float], ttl_s: float = 30 * 86400.0,
                 max_entries: int = 5000) -> None:
        self._path = path
        self._clock = clock
        self._ttl = ttl_s
        self._max = max_entries
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".part")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            log.warning("could not save %s", self._path)

    def get(self, key: str) -> dict | None:
        with self._lock:
            entry = self._load().get(key)
        if not isinstance(entry, dict) or not _ID.fullmatch(str(entry.get("video_id", ""))):
            return None
        if self._clock() - float(entry.get("at", 0)) > self._ttl:
            return None
        return entry

    def put(self, key: str, video_id: str, title: str, duration_s: int | None) -> None:
        with self._lock:
            data = self._load()
            data[key] = {"video_id": video_id, "title": title, "duration_s": duration_s, "at": self._clock()}
            if len(data) > self._max:  # the oldest go
                for old in sorted(data, key=lambda k: data[k].get("at", 0))[: len(data) - self._max]:
                    del data[old]
            self._save(data)

    def drop(self, key: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(key, None) is not None:
                self._save(data)


class FileCache:
    """Finished, untouched downloads by upload id, with a note beside each (codec, bitrate, last use)."""

    def __init__(self, directory: Path, max_bytes: int, clock: Callable[[], float]) -> None:
        self._dir = directory
        self._max = max_bytes
        self._clock = clock
        self._lock = threading.Lock()

    def _note(self, video_id: str) -> Path:
        return self._dir / f"{video_id}.json"

    def get(self, video_id: str) -> tuple[Path, str, int | None] | None:
        """The cached file with its codec and bitrate, or `None`. Counts as a use."""
        if not _ID.fullmatch(video_id or ""):
            return None
        with self._lock:
            try:
                note = json.loads(self._note(video_id).read_text(encoding="utf-8"))
                path = self._dir / str(note["file"])
                if not path.is_file() or path.parent != self._dir:
                    return None
                note["at"] = self._clock()
                self._note(video_id).write_text(json.dumps(note), encoding="utf-8")
                return path, str(note["codec"]), note.get("kbps")
            except (OSError, ValueError, KeyError):
                return None

    def put(self, video_id: str, source: Path, codec: str, kbps: int | None) -> None:
        """Keeps a copy of [source] (the original goes on to be tagged and placed)."""
        if self._max <= 0 or not _ID.fullmatch(video_id or ""):
            return
        with self._lock:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                target = self._dir / f"{video_id}{source.suffix.lower()}"
                tmp = target.with_name(target.name + ".part")
                shutil.copyfile(source, tmp)
                os.replace(tmp, target)
                self._note(video_id).write_text(json.dumps(
                    {"file": target.name, "codec": codec, "kbps": kbps, "at": self._clock()}), encoding="utf-8")
                self._prune()
            except OSError:
                log.warning("could not keep a copy of %s", video_id)

    def _prune(self) -> None:
        """Oldest use first, until what is kept fits."""
        entries = []
        for note in self._dir.glob("*.json"):
            try:
                data = json.loads(note.read_text(encoding="utf-8"))
                audio = self._dir / str(data["file"])
                entries.append((float(data.get("at", 0)), note, audio))
            except (OSError, ValueError, KeyError):
                note.unlink(missing_ok=True)
        total = sum(a.stat().st_size for _, _, a in entries if a.is_file())
        for _, note, audio in sorted(entries, key=lambda e: e[0]):
            if total <= self._max:
                break
            size = audio.stat().st_size if audio.is_file() else 0
            audio.unlink(missing_ok=True)
            note.unlink(missing_ok=True)
            total -= size
