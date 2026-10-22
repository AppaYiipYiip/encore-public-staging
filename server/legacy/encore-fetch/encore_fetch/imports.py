"""Importing a whole playlist: a background queue on the server (docs/03 ADR-100, ADR-101).

The app reads a pasted Spotify or YouTube link (`playlists.py`), shows the list, and hands the whole list over once. From
then on the server does the work, at a pace it chooses, and the person can close the app, lock the phone or sleep:

    POST /api/import              the list (name, kind, tracks)  -> an import with an id
    GET  /api/import              this person's imports, newest first
    GET  /api/import/<id>         one import: how far, what is missing, the playlist
    POST /api/import/<id>/cancel  stop (what arrived stays)

What it does, song by song, in the playlist's order:

* every song goes through the same pipeline as "play any song" (`jobs.py`), as a *bulk* job so that a song somebody
  just tapped is always served first; a song the library already has costs nothing;
* the songs arrive in the person's own folder; a playlist (or, for "liked songs", the person's stars) is built
  on the music server **as the person**, in the original order, as the songs become known to it, so the list fills up while
  the import runs and the first songs can be played at once;
* the pace is the line's and YouTube's, not a count: a few songs at a time with a small gap, a pause with back-off
  whenever YouTube refuses, a longer pause when the disk is low, and a song that failed for a passing reason goes back in
  the queue (three tries) before it is called missing;
* a person's login is kept **in memory only**; the queue itself is a file, so a restart loses nothing, but the import waits
  for the person's app to speak once (it does, on start) before it continues (ADR-101).
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .jobs import Job, JobManager, Limits, Request
from .navidrome import Auth, Navidrome

log = logging.getLogger("encore_fetch.imports")

#: Most songs one import may hold, and most that wait for one person at a time.
MAX_TRACKS = 5000
MAX_WAITING_PER_PERSON = 10000
MAX_ACTIVE_IMPORTS = 12

#: The ways a song can end up not in the library, in words a person can read (the app shows them under "not found").
REASONS = {
    "not_found": "Nothing matching was found on YouTube.",
    "unavailable": "YouTube has no copy that can be fetched.",
    "age_restricted": "Needs an age check, so it was skipped.",
    "too_big": "The file was bigger than the server allows.",
    "blocked": "YouTube kept refusing the server.",
    "timeout": "The download kept timing out.",
    "download_failed": "The download kept failing.",
    "not_listed": "Downloaded, but the music server has not listed it yet. It will appear after its next scan.",
    "unreadable": "The playlist did not say who made this song.",
    "skipped": "You chose not to import this song.",
    "too_long": "Too long to be treated as a song (a concert, a mix or a long video).",
    "internal": "Something went wrong on the server.",
}

#: Why a running import is resting, for the person.
PAUSES = {
    "waiting_for_app": "Waiting for the app to open once, so the server can carry on in your name.",
    "cooling_off": "YouTube is refusing the server for a while. Resting, then carrying on by itself.",
    "disk_full": "The server is low on disk space. Waiting for room.",
    "pacing": "Going slowly on purpose: YouTube lets only so many songs through an hour. Carrying on by itself.",
}

#: Said after a pause that a YouTube sign-in would shorten (docs/50): a friend reads it in the app and knows who can fix it.
OWNER_HINT = " Imports go faster when the server's owner signs it in to YouTube."

#: An answer that asking again will not change.
_FINAL = frozenset({"not_found", "unavailable", "age_restricted", "too_big", "bad_request"})
#: A passing trouble: back in the queue, a few tries.
_PASSING = frozenset({"blocked", "timeout", "download_failed", "internal"})
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")

#: What people see: `waiting` songs have not started, `working` is in the pipeline, `ready` is in the library, `missing`
#: will not be (and `reason` says why).
WAITING, WORKING, READY, MISSING = "waiting", "working", "ready", "missing"
RUNNING, DONE, CANCELLED, FAILED = "running", "done", "cancelled", "failed"
TERMINAL = (DONE, CANCELLED, FAILED)


class RefusedImport(Exception):
    """A request the queue refuses; `status` and `code` go to the app, `message` is a sentence for the person."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Item:
    title: str
    artist: str
    album: str | None = None
    duration_s: int | None = None
    video_id: str | None = None
    #: [video_id] is YouTube's own official upload of this song: use it, do not search.
    official: bool = False
    state: str = WAITING
    song_id: str | None = None
    reason: str | None = None
    tries: int = 0
    ready_at: float | None = None
    #: When the music server was last asked for this song's id (not saved).
    checked: float = field(default=0.0, repr=False, compare=False)
    #: Not before this time (a song that was just refused waits behind the others; not saved).
    not_before: float = field(default=0.0, repr=False, compare=False)
    #: How many songs had arrived overall when this one was first refused (not saved): see [ImportQueue._settle].
    refused_at: int | None = field(default=None, repr=False, compare=False)
    #: The job that fetched it, kept only until the music server has listed the song (not saved).
    job: Job | None = field(default=None, repr=False, compare=False)

    def to_json(self) -> dict:
        out: dict = {"title": self.title, "artist": self.artist, "state": self.state}
        for key, value in (("album", self.album), ("durationSec", self.duration_s), ("videoId", self.video_id),
                           ("official", self.official),
                           ("songId", self.song_id), ("reason", self.reason)):
            if value:
                out[key] = value
        if self.tries:
            out["tries"] = self.tries
        return out

    @staticmethod
    def from_json(data: dict) -> "Item":
        state = data.get("state") if data.get("state") in (WAITING, READY, MISSING) else WAITING
        return Item(
            title=str(data.get("title") or ""), artist=str(data.get("artist") or ""),
            album=data.get("album") or None, duration_s=data.get("durationSec") or None,
            video_id=data.get("videoId") or None, official=bool(data.get("official")), state=state, song_id=data.get("songId") or None,
            reason=data.get("reason") or None, tries=int(data.get("tries") or 0))


@dataclass
class Import:
    id: str
    user: str
    name: str
    #: "playlist" (make a playlist) or "liked" (star every song).
    kind: str
    source: str
    created: float
    updated: float
    items: list[Item]
    state: str = RUNNING
    #: The playlist on the music server, once it exists.
    playlist_id: str | None = None
    #: Items before this index are already in the playlist (or starred).
    pushed: int = 0
    message: str | None = None
    #: How long the songs that needed a download took (seconds each, the last twenty): the estimate's basis.
    took: list[float] = field(default_factory=list)
    #: Which turn this import last had a song fetched in (the round robin between people uses it).
    served: int = 0

    def counts(self) -> dict[str, int]:
        out = {WAITING: 0, WORKING: 0, READY: 0, MISSING: 0}
        for item in self.items:
            out[item.state] += 1
        return out

    def to_json(self) -> dict:
        return {
            "id": self.id, "user": self.user, "name": self.name, "kind": self.kind, "source": self.source,
            "created": self.created, "updated": self.updated, "state": self.state,
            "playlistId": self.playlist_id, "pushed": self.pushed, "message": self.message,
            "took": self.took, "items": [i.to_json() for i in self.items],
        }

    @staticmethod
    def from_json(data: dict) -> "Import":
        return Import(
            id=str(data["id"]), user=str(data["user"]), name=str(data.get("name") or ""),
            kind=str(data.get("kind") or "playlist"), source=str(data.get("source") or ""),
            created=float(data.get("created") or 0), updated=float(data.get("updated") or 0),
            items=[Item.from_json(i) for i in data.get("items") or [] if isinstance(i, dict)],
            state=str(data.get("state") or RUNNING), playlist_id=data.get("playlistId") or None,
            pushed=int(data.get("pushed") or 0), message=data.get("message") or None,
            took=[float(t) for t in data.get("took") or []][-20:])


def _clean(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    if not value or len(value) > limit or _CTRL.search(value):
        return None
    return value


def parse_tracks(raw: object) -> tuple[list[Item], int]:
    """The songs of a request as items, and how many entries could not be read (they are not silently lost: the app is told)."""
    if not isinstance(raw, list):
        raise RefusedImport(400, "bad_request", "The list of songs is missing.")
    if len(raw) > MAX_TRACKS:
        raise RefusedImport(413, "too_many", f"That is more than {MAX_TRACKS} songs in one import. Split it in two.")
    items: list[Item] = []
    skipped = 0
    for entry in raw:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        title = _clean(entry.get("title"), 200)
        artist = _clean(entry.get("artist"), 200)
        if title is None or artist is None:
            skipped += 1
            continue
        duration = entry.get("durationSec")
        video = entry.get("videoId")
        items.append(Item(
            title=title, artist=artist, album=_clean(entry.get("album"), 200),
            duration_s=int(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool)
            and 5 <= duration <= 7200 else None,
            video_id=video if isinstance(video, str) and _VIDEO_ID.match(video) else None,
            official=entry.get("official") is True and isinstance(video, str) and bool(_VIDEO_ID.match(video))))
    return items, skipped


class ImportQueue:
    def __init__(
        self,
        manager: JobManager,
        navidrome: Navidrome,
        directory: Path,
        *,
        workers: int = 2,
        gap_s: float = 2.0,
        cool_base_s: float = 90.0,
        cool_max_s: float = 1800.0,
        disk_wait_s: float = 600.0,
        max_tries: int = 3,
        job_timeout_s: float = 900.0,
        listed_wait_s: float = 180.0,
        max_per_hour: int = 200,
        account_ceiling: Callable[[], int | None] | None = None,
        max_song_s: int = 2700,
        keep_s: float = 14 * 86400.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        start: bool = True,
    ) -> None:
        self._manager = manager
        self._nd = navidrome
        self._dir = directory
        self._workers = max(1, workers)
        self._gap = gap_s
        self._cool_base = cool_base_s
        self._cool_max = cool_max_s
        self._disk_wait = disk_wait_s
        self._max_tries = max_tries
        self._job_timeout = job_timeout_s
        self._listed_wait = listed_wait_s
        # YouTube lets a visitor without a login fetch about 300 videos an hour from one address (yt-dlp wiki; the
        # owner's 683-song list was refused after about 100 songs in 20 minutes). Stay well under it, and go slower
        # for a while after every refusal.
        self._max_per_hour = max(1, max_per_hour)
        # Signed-in YouTube accounts have their own, much larger allowance (about 2,000 an hour each, yt-dlp wiki):
        # [account_ceiling] says what the usable accounts allow together (accounts.py), `None` when there is none and
        # the visitor's [max_per_hour] applies.
        self._account_ceiling = account_ceiling or (lambda: None)
        self._last_ceiling = self._ceiling_now()
        # A YouTube Music "liked" list holds whole concerts and hour-long videos; they are not songs, they cost a
        # slot of the hourly allowance and the downloader refuses them anyway (after minutes).
        self._max_song_s = max_song_s
        self._cap = self._ceiling()
        self._last_refusal = 0.0
        self._last_shrink = 0.0
        self._keep = keep_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._imports: dict[str, Import] = {}
        #: A person's login, in memory only (ADR-101).
        self._auth: dict[str, Auth] = {}
        self._turn = 0
        self._arrived = 0
        self._cool_until = 0.0
        self._cool_reason: str | None = None
        self._blocks = 0
        self._closed = False
        self._threads: list[threading.Thread] = []
        if hasattr(manager, "refusal_listener"):
            manager.refusal_listener = self._note_refusal
        self._load()
        self._load_pace()
        if start:
            for n in range(self._workers):
                t = threading.Thread(target=self._loop, name=f"import-{n}", daemon=True)
                t.start()
                self._threads.append(t)

    # ------------------------------------------------------------------ the routes

    def touch(self, auth: Auth) -> None:
        """The person's app spoke: their login is known again (after a restart this is what lets the import go on)."""
        with self._lock:
            who = auth.user.strip().lower()
            known = self._auth.get(who)
            self._auth[who] = auth
            if known != auth:
                self._wake.notify_all()

    def create(self, auth: Auth, *, name: str, kind: str, source: str, tracks: object) -> Import:
        if kind not in ("playlist", "liked"):
            raise RefusedImport(400, "bad_request", "kind must be playlist or liked.")
        items, skipped = parse_tracks(tracks)
        if not items:
            raise RefusedImport(422, "empty", "There were no songs to import.")
        who = auth.user.strip().lower()
        title = _clean(name, 120) or ("Liked songs" if kind == "liked" else "Imported playlist")
        now = self._clock()
        with self._lock:
            self.touch(auth)
            mine = [i for i in self._imports.values() if i.user == who and i.state == RUNNING]
            if len(mine) >= MAX_ACTIVE_IMPORTS:
                raise RefusedImport(429, "too_many_imports", "That is a lot of imports at once. Let some finish first.")
            waiting = sum(i.counts()[WAITING] for i in mine)
            if waiting + len(items) > MAX_WAITING_PER_PERSON:
                raise RefusedImport(429, "too_many_imports", "That is a lot of songs waiting already. Let them arrive first.")
            for item in items:
                if item.duration_s is not None and item.duration_s > self._max_song_s:
                    item.state, item.reason = MISSING, "too_long"
            imp = Import(id=secrets.token_hex(6), user=who, name=title, kind=kind,
                         source=_clean(source, 20) or "link", created=now, updated=now, items=items)
            if skipped:
                imp.message = (f"{skipped} entr{'y' if skipped == 1 else 'ies'} in the list could not be read and "
                               "were left out.")
            self._imports[imp.id] = imp
            self._save(imp)
            self._wake.notify_all()
        log.info("import %s started for %s: %s, %d songs", imp.id, who, kind, len(items))
        return imp

    def get(self, user: str, import_id: str) -> Import | None:
        with self._lock:
            imp = self._imports.get(import_id)
            return imp if imp is not None and imp.user == user.strip().lower() else None

    def list(self, user: str) -> list[Import]:
        with self._lock:
            mine = [i for i in self._imports.values() if i.user == user.strip().lower()]
        return sorted(mine, key=lambda i: i.created, reverse=True)

    def skip(self, user: str, import_id: str, indexes: object) -> Import | None:
        """The person does not want these songs (a 683-song list has some): the ones not fetched yet are never fetched.
        A song already working, or already in the library, is left alone (the library's own playlist is where it goes)."""
        with self._lock:
            imp = self.get(user, import_id)
            if imp is None:
                return None
            if not isinstance(indexes, list) or len(indexes) > 5000:
                raise RefusedImport(400, "bad_request", "indexes must be a list of song numbers.")
            for i in indexes:
                if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(imp.items):
                    raise RefusedImport(400, "bad_request", "That song number is not in this import.")
            for i in indexes:
                item = imp.items[i]
                if item.state == WAITING:
                    item.state, item.reason = MISSING, "skipped"
            imp.updated = self._clock()
            self._push(imp)
            if imp.state == RUNNING:
                self._finish_if_over(imp, self._clock())
            self._save(imp)
            return imp

    def cancel(self, user: str, import_id: str) -> Import | None:
        with self._lock:
            imp = self.get(user, import_id)
            if imp is None:
                return None
            if imp.state == RUNNING:
                imp.state = CANCELLED
                imp.updated = self._clock()
                imp.message = "Stopped. The songs that had arrived are in your library."
                self._push(imp)
                self._save(imp)
            return imp

    def view(self, imp: Import, *, full: bool = True, songs: bool = False) -> dict:
        with self._lock:
            counts = imp.counts()
            now = self._clock()
            total = len(imp.items)
            settled = counts[READY] + counts[MISSING]
            skipped = sum(1 for i in imp.items if i.state == MISSING and i.reason == "skipped")
            out: dict = {
                "id": imp.id, "name": imp.name, "kind": imp.kind, "source": imp.source, "state": imp.state,
                "total": total, "done": settled, "added": counts[READY], "missing": counts[MISSING] - skipped,
                "skipped": skipped,
                "waiting": counts[WAITING] + counts[WORKING],
                "playlistReady": imp.playlist_id is not None or imp.kind == "liked" and imp.pushed > 0,
                "created": imp.created, "updated": imp.updated,
                "missingSongs": [{"title": i.title, "artist": i.artist, "reason": i.reason,
                                  "message": REASONS.get(i.reason or "", "")}
                                 for i in imp.items if i.state == MISSING and i.reason != "skipped"][:300],
            }
            if imp.playlist_id:
                out["playlistId"] = imp.playlist_id
            if imp.message:
                out["message"] = imp.message
            if imp.state == RUNNING:
                pause = self._pause(imp, now)
                if pause:
                    out["paused"] = pause
                    out["pausedMessage"] = PAUSES[pause] + (OWNER_HINT if pause in ("pacing", "cooling_off") and self._last_ceiling is None else "")
                out["etaSec"] = self._eta(imp)
            if not full:
                del out["missingSongs"]
            if songs:
                # Every song with where it is, in the playlist's order: what lets the app show the whole list at once and
                # play any of them (a song not here yet is fetched when it is tapped).
                out["songs"] = [self._song_view(i) for i in imp.items]
            return out

    @staticmethod
    def _song_view(item: Item) -> dict:
        out: dict = {"title": item.title, "artist": item.artist, "state": item.state}
        for key, value in (("album", item.album), ("durationSec", item.duration_s), ("videoId", item.video_id),
                           ("reason", item.reason), ("message", REASONS.get(item.reason or ""))):
            if value:
                out[key] = value
        if item.official:
            out["official"] = True
        return out

    # -------------------------------------------------------------- the work

    def _pause(self, imp: Import, now: float) -> str | None:
        self._sync_ceiling()
        if imp.user not in self._auth:
            return "waiting_for_app"
        if now < self._cool_until and imp.counts()[WAITING]:
            return self._cool_reason or "cooling_off"
        if imp.counts()[WAITING] and self._at_the_limit(now):
            return "pacing"
        return None

    def _ceiling_now(self) -> int | None:
        try:
            value = self._account_ceiling()
        except Exception:  # noqa: BLE001 - accounts that cannot be looked at are no accounts
            return None
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    def _ceiling(self) -> int:
        """The most songs an hour this queue ever allows itself: the usable accounts' with any, the visitor's without."""
        return self._last_ceiling if self._last_ceiling is not None else self._max_per_hour

    def _sync_ceiling(self) -> None:
        """Accounts arriving, resting, coming back or going change the allowance at once. The first one arriving is a
        fresh start: the rests and cuts made against the visitor's limit say nothing about an account's."""
        now_ceiling = self._ceiling_now()
        if now_ceiling == self._last_ceiling:
            return
        with self._lock:
            before = self._last_ceiling
            self._last_ceiling = now_ceiling
            if now_ceiling is None:
                self._cap = min(self._cap, self._max_per_hour)
            elif before is None:
                self._cap = now_ceiling
                self._cool_until = 0.0
                self._cool_reason = None
                self._blocks = 0
            elif now_ceiling > before:
                self._cap = min(now_ceiling, self._cap + (now_ceiling - before))
            else:
                self._cap = min(self._cap, now_ceiling)
            log.info("%d songs an hour allowed (%s)", self._cap, "YouTube accounts" if now_ceiling else "the visitor's limit")
            self._save_pace()
            self._wake.notify_all()

    def _effective_cap(self, now: float) -> int:
        """The songs an hour this queue allows itself: less after a refusal, creeping back an hour at a time."""
        self._sync_ceiling()
        if self._cap < self._ceiling() and now - self._last_refusal >= 3600:
            self._cap = min(self._ceiling(), int(self._cap * 1.3) + 1)
            self._last_refusal = now  # the next step back is an hour later
        return self._cap

    def _at_the_limit(self, now: float) -> bool:
        return self._manager.downloads_since(3600) >= self._effective_cap(now)

    def youtube_state(self) -> dict:
        """What the server can say about YouTube right now, in plain words: `ok`, or `resting` after YouTube refused the server (the
        import queue rests, longer each time, and carries on by itself)."""
        now = self._clock()
        if now < self._cool_until and self._cool_reason == "cooling_off":
            return {"state": "resting", "message": PAUSES["cooling_off"], "resumesInSec": int(self._cool_until - now)}
        return {"state": "ok"}

    def _eta(self, imp: Import) -> int:
        left = imp.counts()[WAITING] + imp.counts()[WORKING]
        if left == 0:
            return 0
        average = sum(imp.took) / len(imp.took) if imp.took else 14.0
        extra = self._gap
        # Never faster than the hourly allowance, however quick the songs are.
        return int(left * max((average + extra) / self._workers, 3600 / self._effective_cap(self._clock())))

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._wake.notify_all()

    def _loop(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    return
            if self.step():
                self._sleep(self._gap)
                continue
            with self._lock:
                if self._closed:
                    return
                self._wake.wait(timeout=2.0)

    def step(self) -> bool:
        """One unit of work: pump the playlists, then fetch the next song in line. `True` when a song was fetched."""
        self.pump()
        claimed = self._claim()
        if claimed is None:
            return False
        imp, item, auth = claimed
        self._process(imp, item, auth)
        return True

    def _claim(self) -> tuple[Import, Item, Auth] | None:
        self._sync_ceiling()
        with self._lock:
            now = self._clock()
            if now < self._cool_until or self._at_the_limit(now):
                return None
            # Each person's oldest import with songs left goes first (so the first playlist is finished and playable
            # before the second is started); people take turns.
            front: dict[str, Import] = {}
            for imp in self._imports.values():
                if imp.state != RUNNING or imp.user not in self._auth:
                    continue
                if not any(i.state == WAITING for i in imp.items):
                    continue
                if imp.user not in front or imp.created < front[imp.user].created:
                    front[imp.user] = imp
            best: Import | None = None
            for imp in front.values():
                if best is None or self._busy(imp.user) < self._busy(best.user) or (
                        self._busy(imp.user) == self._busy(best.user) and imp.served < best.served):
                    best = imp
            if best is None:
                return None
            # A song that was just refused goes behind the others, but never holds the line when it is all that is left.
            for i in best.items:  # an import made before this rule (or loaded from a file) is held to it too
                too_long = i.duration_s is not None and i.duration_s > self._max_song_s
                if i.state == WAITING and too_long:
                    i.state, i.reason = MISSING, "too_long"
                elif i.state == MISSING and i.reason == "too_long" and not too_long:
                    i.state, i.reason = WAITING, None  # the limit was raised since: it is a song after all
            waiting = [i for i in best.items if i.state == WAITING]
            if not waiting:
                self._finish_if_over(best, now)
                return None
            item = next((i for i in waiting if i.not_before <= now), None) or min(waiting, key=lambda i: i.not_before)
            item.state = WORKING
            self._turn += 1
            for imp in self._imports.values():
                if imp.user == best.user:
                    imp.served = self._turn
            return best, item, self._auth[best.user]

    def _busy(self, user: str) -> int:
        return sum(1 for i in self._imports.values() if i.user == user for it in i.items if it.state == WORKING)

    def _process(self, imp: Import, item: Item, auth: Auth) -> None:
        started = self._clock()
        request = Request(artist=item.artist, title=item.title, album=item.album, duration_s=item.duration_s,
                          bulk=True, video_id=item.video_id, video_first=item.official)
        try:
            job = self._manager.submit(auth, request, internal=True)
            deadline = started + self._job_timeout
            while not job.done and self._clock() < deadline:
                self._sleep(0.5)
        except Limits:
            job = None
        except Exception:  # noqa: BLE001 - one song never stops the queue
            log.exception("import %s: %s - %s", imp.id, item.artist, item.title)
            job = None
        with self._lock:
            self._settle(imp, item, job, self._clock() - started)
            self._save_pace()
            imp.updated = self._clock()
            self._push(imp)
            if imp.state == RUNNING:
                self._finish_if_over(imp, self._clock())
            self._save(imp)

    def _settle(self, imp: Import, item: Item, job: Job | None, seconds: float) -> None:
        if job is not None and job.state == "ready":
            item.state, item.job, item.song_id = READY, job, job.song_id
            item.ready_at = self._clock()
            self._blocks = 0
            self._arrived += 1
            if seconds > 3:  # a song the library already had says nothing about the line
                imp.took = [*imp.took, seconds][-20:]
            return
        if job is not None and not job.done:
            code = "timeout"
        else:
            code = (job.error if job is not None and job.state == "failed" else "internal") or "internal"
        if code == "no_library":
            imp.state, imp.message = FAILED, "Your account has no library to put songs in yet. Ask whoever runs the server."
            item.state = WAITING
            return
        if code == "disk_full":
            item.state = WAITING
            self._cool(self._disk_wait, "disk_full")
            return
        if code in _FINAL or code not in _PASSING:
            item.state, item.reason = MISSING, code if code in REASONS else "internal"
            return
        item.state = WAITING
        if code == "blocked":
            # YouTube refusing the server says nothing about this song: the whole queue rests (the job told us at once,
            # [_note_refusal], longer each time), and the song goes behind the others. But a song refused again after
            # other songs have arrived is a problem of that song (the server proved it can fetch): each such refusal
            # counts as one of its tries.
            item.not_before = max(self._cool_until, self._clock()) + 30  # long enough for the songs behind it to have their turn
            if item.refused_at is None:
                item.refused_at = self._arrived
            elif self._arrived > item.refused_at:
                item.tries += 1
                if item.tries >= self._max_tries:
                    item.state, item.reason = MISSING, code
            return
        item.tries += 1
        if item.tries >= self._max_tries:
            item.state, item.reason = MISSING, code

    def _note_refusal(self, account: str | None = None) -> None:
        """YouTube refused a song (this queue's or somebody's tap): everything rests, longer each time, and the hourly
        allowance shrinks for a while. A refused *account* rests by itself (accounts.py) and the others carry on, so the
        queue only rests when no account is left to use."""
        if account is not None and self._ceiling_now() is not None:
            return
        with self._lock:
            now = self._clock()
            self._cool(min(self._cool_base * 2 ** self._blocks, self._cool_max), "cooling_off")
            self._blocks += 1
            # One refusal after another within minutes is one event (YouTube refused six songs in two minutes and a
            # per-refusal cut took 200 an hour to the floor of 60): the allowance shrinks once per ten minutes.
            cap = self._effective_cap(now)
            if now - self._last_shrink >= 600:
                self._cap = max(min(60, self._ceiling()), int(cap * 0.7))  # never below 60 an hour, never above the setting
                self._last_shrink = now
            self._last_refusal = now
            self._save_pace()

    def _pace_path(self) -> Path:
        return self._dir / "_pace.json"

    def _save_pace(self) -> None:
        """The allowance and the recent downloads, kept in a file: a restart (a new version, a reboot) must not wipe
        what the server knows about YouTube's mood, or the next burst follows the last one at once."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._pace_path().with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "cap": self._cap, "lastRefusal": self._last_refusal, "lastShrink": self._last_shrink,
                "blocks": self._blocks, "coolUntil": self._cool_until, "coolReason": self._cool_reason,
                "downloads": self._manager.download_times()}, separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self._pace_path())
        except OSError:
            log.warning("the pace could not be saved")

    def _load_pace(self) -> None:
        try:
            data = json.loads(self._pace_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        cap = data.get("cap")
        if isinstance(cap, int) and 1 <= cap <= self._ceiling():
            self._cap = cap
        for name, key in (("_last_refusal", "lastRefusal"), ("_last_shrink", "lastShrink"), ("_cool_until", "coolUntil")):
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                setattr(self, name, float(value))
        blocks = data.get("blocks")
        self._blocks = blocks if isinstance(blocks, int) and 0 <= blocks < 20 else 0
        reason = data.get("coolReason")
        self._cool_reason = reason if reason in PAUSES else None
        if isinstance(data.get("downloads"), list) and hasattr(self._manager, "restore_downloads"):
            self._manager.restore_downloads(data["downloads"])
        log.info("pace loaded: %d songs an hour allowed, %d fetched in the last hour", self._cap,
                 self._manager.downloads_since(3600) if hasattr(self._manager, "downloads_since") else 0)

    def _cool(self, seconds: float, why: str) -> None:
        self._cool_until = max(self._cool_until, self._clock() + seconds)
        self._cool_reason = why
        log.warning("imports paused for %.0fs (%s)", seconds, why)

    # ------------------------------------------------------- the playlist

    def pump(self) -> None:
        """Hands the songs that are in the library to the playlist, in order; finishes imports that are over."""
        with self._lock:
            now = self._clock()
            for imp in list(self._imports.values()):
                if imp.state != RUNNING:
                    continue
                self._push(imp)
                self._finish_if_over(imp, now)

    def _finish_if_over(self, imp: Import, now: float) -> None:
        counts = imp.counts()
        # Songs that arrived but are not listed by the music server yet keep the import open (for [listed_wait_s] at most,
        # after which _push calls them not listed).
        if counts[WAITING] or counts[WORKING] or imp.pushed < len(imp.items):
            return
        imp.state = DONE
        imp.updated = now
        imp.message = imp.message or self._summary(imp)
        self._save(imp)
        log.info("import %s done: %d added, %d missing", imp.id, counts[READY], counts[MISSING])

    @staticmethod
    def _summary(imp: Import) -> str:
        counts = imp.counts()
        added = counts[READY]
        missing = sum(1 for i in imp.items if i.state == MISSING and i.reason != "skipped")
        if imp.kind == "liked":
            text = f"{added} song{'s' if added != 1 else ''} liked"
        else:
            text = f"{added} song{'s' if added != 1 else ''} in the playlist"
        if missing:
            text += f", {missing} could not be added"
        return text + "."

    def _resolve(self, item: Item, auth: Auth, now: float) -> None:
        """The music server's id for a song that arrived: from its job; else by asking, now and then (the job stops
        looking after a while, and after a restart there is no job)."""
        if item.song_id is not None:
            return
        job = item.job
        if job is not None and job.song_id:
            item.song_id = job.song_id
            return
        waited = now - (item.ready_at if item.ready_at is not None else now)
        if job is not None and waited < 30:
            return  # the job's own look at the music server is still going on
        if now - item.checked < 15:
            return
        item.checked = now
        item.song_id = self._nd.find_song(auth, artist=item.artist, title=item.title, album=item.album,
                                          relative_path=job.path if job is not None else None)

    def _push(self, imp: Import) -> None:
        """Moves the front of the import, as far as every song is known, into the playlist or the stars."""
        auth = self._auth.get(imp.user)
        if auth is None:
            return
        ids: list[str] = []
        index = imp.pushed
        now = self._clock()
        while index < len(imp.items):
            item = imp.items[index]
            if item.state == MISSING:
                index += 1
                continue
            if item.state != READY:
                break
            self._resolve(item, auth, now)
            if item.song_id is None:
                if item.ready_at is not None and now - item.ready_at >= self._listed_wait:
                    item.state, item.reason = MISSING, "not_listed"
                    index += 1
                    continue
                break
            ids.append(item.song_id)
            index += 1
        if index == imp.pushed:
            return
        try:
            if imp.kind == "liked":
                if ids and not self._nd.star(auth, ids):
                    return
            elif ids:
                if imp.playlist_id is None:
                    name = self._free_name(auth, imp.name)
                    imp.playlist_id = self._nd.create_playlist(auth, name, ids[:100])
                    if imp.playlist_id is None:
                        return
                    imp.name = name
                    rest = ids[100:]
                else:
                    rest = ids
                for start in range(0, len(rest), 100):
                    if not self._nd.add_to_playlist(auth, imp.playlist_id, rest[start:start + 100]):
                        return
        except Exception:  # noqa: BLE001 - the music server being busy is not the end of an import
            log.exception("import %s: the playlist could not be updated", imp.id)
            return
        imp.pushed = index
        for item in imp.items[:index]:
            item.job = None
        imp.updated = self._clock()
        self._save(imp)

    def _free_name(self, auth: Auth, wanted: str) -> str:
        """A playlist name the person does not have yet: "Evening", then "Evening (2)" (nothing is merged by surprise)."""
        taken = {n.lower() for n in self._nd.playlist_names(auth)}
        if wanted.lower() not in taken:
            return wanted
        n = 2
        while f"{wanted} ({n})".lower() in taken:
            n += 1
        return f"{wanted} ({n})"

    # ------------------------------------------------------------- the files

    def _path(self, import_id: str) -> Path:
        return self._dir / f"{import_id}.json"

    def _save(self, imp: Import) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path(imp.id).with_suffix(".tmp")
            tmp.write_text(json.dumps(imp.to_json(), separators=(",", ":")), encoding="utf-8")
            os.replace(tmp, self._path(imp.id))
        except OSError:
            log.exception("import %s could not be saved", imp.id)

    def _load(self) -> None:
        if not self._dir.is_dir():
            return
        now = self._clock()
        for path in sorted(self._dir.glob("*.json")):
            try:
                imp = Import.from_json(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError):
                log.warning("import file %s is not readable; left alone", path.name)
                continue
            if imp.state in TERMINAL and now - imp.updated > self._keep:
                path.unlink(missing_ok=True)
                continue
            for item in imp.items:
                if item.state == WORKING:
                    item.state = WAITING
            self._imports[imp.id] = imp
        if self._imports:
            log.info("%d imports loaded; they continue when their owners' apps speak", len(self._imports))
