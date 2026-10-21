"""A person's own data, kept on their own server (docs/22 section 4, ADR-063).

Two kinds of thing, both small and both per Subsonic account:

* **documents** - named JSON objects (`settings`, `pins`, `friends`, ...) with
  a version number. A write says which version it was based on; if the
  stored one has moved on the write is refused with the current copy
  (`409`), so two devices never silently overwrite each other.
* **events** - an append-only log (the app's own listening history). Every
  event has an id chosen by the client; sending one twice is harmless.

Everything is plain files under `<root>/<user>/`: easy to read, to copy and to
back up. Writes are atomic (a temp file, then a rename).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable

NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
USER = re.compile(r"^[A-Za-z0-9._@+-]{1,64}$")
MAX_DOCS = 32

# 2000-01-01 and one day ahead: a play outside that is a broken clock.
_T_MIN = 946_684_800_000


class ProfileError(Exception):
    """A request that cannot be honoured; `status` is the HTTP code."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class Conflict(Exception):
    """The stored document moved on; carries its current state."""

    def __init__(self, version: int, data: dict) -> None:
        super().__init__("version conflict")
        self.version = version
        self.data = data


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = "".join(c for c in value if c >= " " and c != "\x7f").strip()
    return value[:limit] or None


def _int(value: object, lo: int, hi: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    n = int(value)
    return n if lo <= n <= hi else None


def clean_event(raw: object, now_ms: int) -> dict | None:
    """The stored shape of one event, or `None` if it is unusable."""
    if not isinstance(raw, dict):
        return None
    eid = _text(raw.get("id"), 64)
    t = _int(raw.get("t"), _T_MIN, now_ms + 86_400_000)
    if eid is None or t is None:
        return None
    out: dict[str, object] = {"id": eid, "t": t}
    for key, limit in (("song", 64), ("title", 200), ("artist", 200),
                       ("album", 200), ("genre", 100), ("src", 32),
                       ("dev", 32)):
        value = _text(raw.get(key), limit)
        if value is not None:
            out[key] = value
    for key, hi in (("dur", 86_400), ("ms", 86_400_000)):
        value = _int(raw.get(key), 0, hi)
        if value is not None:
            out[key] = value
    return out


class _User:
    """The state of one person's folder (loaded lazily, guarded by a lock)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = threading.RLock()
        self.ids: set[str] | None = None
        self.seq = 0
        self.per_day: dict[str, int] = {}


class ProfileStore:
    def __init__(
        self,
        root: Path,
        *,
        max_doc_bytes: int = 256 * 1024,
        max_total_bytes: int = 50 * 1024 * 1024,
        max_events_per_day: int = 5000,
        max_events_per_call: int = 500,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = root
        self._max_doc = max_doc_bytes
        self._max_total = max_total_bytes
        self._max_day = max_events_per_day
        self._max_call = max_events_per_call
        self._clock = clock
        self._users: dict[str, _User] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------ plumbing

    def _user(self, user: str) -> _User:
        if not USER.match(user):
            raise ProfileError(400, "bad user")
        with self._guard:
            state = self._users.get(user)
            if state is None:
                state = self._users[user] = _User(self._root / user)
            return state

    @staticmethod
    def _write_atomic(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _folder_bytes(self, state: _User) -> int:
        total = 0
        if state.root.is_dir():
            for p in state.root.rglob("*"):
                try:
                    if p.is_file():
                        total += p.stat().st_size
                except OSError:
                    pass
        return total

    # ------------------------------------------------------------ documents

    @staticmethod
    def _check_name(name: str) -> None:
        if not NAME.match(name):
            raise ProfileError(400, "bad document name")

    def _doc_path(self, state: _User, name: str) -> Path:
        return state.root / "docs" / f"{name}.json"

    def _read_doc(self, state: _User, name: str) -> dict | None:
        path = self._doc_path(state, name)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def list(self, user: str) -> dict:
        state = self._user(user)
        with state.lock:
            docs: dict[str, dict] = {}
            folder = state.root / "docs"
            if folder.is_dir():
                for p in sorted(folder.glob("*.json")):
                    doc = self._read_doc(state, p.stem)
                    if doc is not None:
                        docs[p.stem] = {"v": doc.get("v", 0),
                                        "at": doc.get("at", 0)}
            self._load_events(state)
            return {"docs": docs, "events": {"count": len(state.ids or ()),
                                             "last": state.seq}}

    def get_doc(self, user: str, name: str) -> dict | None:
        self._check_name(name)
        state = self._user(user)
        with state.lock:
            return self._read_doc(state, name)

    def put_doc(self, user: str, name: str, base_v: int, data: object) -> dict:
        """Stores [data] as the next version of [name]. Raises `Conflict`
        (with the stored copy) when [base_v] is not the stored version."""
        self._check_name(name)
        if not isinstance(data, dict):
            raise ProfileError(400, "a document is a JSON object")
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > self._max_doc:
            raise ProfileError(413, "document too large")
        state = self._user(user)
        with state.lock:
            current = self._read_doc(state, name)
            version = int(current.get("v", 0)) if current else 0
            if base_v != version:
                raise Conflict(version, (current or {}).get("data", {}))
            if current is None:
                existing = list((state.root / "docs").glob("*.json")) \
                    if (state.root / "docs").is_dir() else []
                if len(existing) >= MAX_DOCS:
                    raise ProfileError(400, "too many documents")
            if self._folder_bytes(state) + len(text) > self._max_total:
                raise ProfileError(413, "profile is full")
            now_ms = int(self._clock() * 1000)
            doc = {"v": version + 1, "at": now_ms, "data": data}
            self._write_atomic(
                self._doc_path(state, name),
                json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
            return {"v": doc["v"], "at": now_ms}

    # --------------------------------------------------------------- events

    def _events_dir(self, state: _User) -> Path:
        return state.root / "events"

    def _event_files(self, state: _User) -> list[Path]:
        """One file, in arrival order: the cursor is the sequence number,
        so reading from the top is always in `seq` order."""
        path = self._events_dir(state) / "events.jsonl"
        return [path] if path.is_file() else []

    def _load_events(self, state: _User) -> None:
        if state.ids is not None:
            return
        ids: set[str] = set()
        seq = 0
        for path in self._event_files(state):
            try:
                with path.open(encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue  # a half-written last line
                        ids.add(rec["id"])
                        seq = max(seq, int(rec.get("seq", 0)))
            except OSError:
                continue
        state.ids, state.seq = ids, seq

    def add_events(self, user: str, events: object) -> dict:
        if not isinstance(events, list):
            raise ProfileError(400, "events must be a list")
        if len(events) > self._max_call:
            raise ProfileError(413, "too many events in one call")
        state = self._user(user)
        now_ms = int(self._clock() * 1000)
        today = time.strftime("%Y-%m-%d", time.gmtime(now_ms / 1000))
        accepted = dupes = rejected = 0
        with state.lock:
            self._load_events(state)
            assert state.ids is not None
            fresh: list[dict] = []
            for raw in events:
                ev = clean_event(raw, now_ms)
                if ev is None:
                    rejected += 1
                elif ev["id"] in state.ids:
                    dupes += 1
                else:
                    fresh.append(ev)
            used = state.per_day.get(today, 0)
            if used + len(fresh) > self._max_day:
                raise ProfileError(429, "too many events today")
            if fresh and (self._folder_bytes(state)
                          + 200 * len(fresh)) > self._max_total:
                raise ProfileError(413, "profile is full")
            lines: list[str] = []
            for ev in fresh:
                state.seq += 1
                state.ids.add(ev["id"])
                lines.append(json.dumps({"seq": state.seq, **ev},
                                        ensure_ascii=False,
                                        separators=(",", ":")))
                accepted += 1
            if lines:
                folder = self._events_dir(state)
                folder.mkdir(parents=True, exist_ok=True)
                with (folder / "events.jsonl").open(
                        "a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            state.per_day[today] = used + accepted
        return {"accepted": accepted, "dupes": dupes, "rejected": rejected}

    def read_events(self, user: str, since: int = 0,
                    limit: int = 2000) -> dict:
        """Events with `seq > since`, oldest first; `next` is the cursor to
        continue from, or `None` when everything has been sent."""
        limit = max(1, min(limit, 5000))
        state = self._user(user)
        out: list[dict] = []
        with state.lock:
            self._load_events(state)
            last = state.seq
            for path in self._event_files(state):
                try:
                    with path.open(encoding="utf-8") as f:
                        for line in f:
                            try:
                                rec = json.loads(line)
                            except ValueError:
                                continue
                            if int(rec.get("seq", 0)) > since:
                                out.append(rec)
                                if len(out) >= limit:
                                    break
                except OSError:
                    continue
                if len(out) >= limit:
                    break
        cursor = out[-1]["seq"] if out else since
        return {"events": out, "next": cursor if cursor < last else None}
