"""One "play this now" request, from asking to a song in the library.

Pipeline (each step is a state the app shows):

    queued -> searching -> downloading -> tagging -> indexing -> ready
                                  \\-> failed (with a short code)

A song can also be *prepared* ahead of the tap (`POST /api/prepare`): the
search and the YouTube extraction run, the job parks as `prepared`, and the
tap that follows starts straight at `downloading`.

A song the library already has is `ready` at once; two people asking for the
same song share one job. Credentials live only in memory, only while the job
runs.
"""
from __future__ import annotations

import logging
import secrets
import shutil
import threading
import time
from collections import deque
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from .cache import FileCache, ResolveCache, song_key
from .catalogue import Meta
from .download import Downloaded, DownloadError, fetch_cover, live_source
from .library import (PersonLayout, find_existing, free_gb, place_file,
                      plan_placement)
from .navidrome import Auth, Navidrome
from .resolve import Resolver, Want
from .tagging import Tags, write_tags

log = logging.getLogger("encore_fetch")

TERMINAL = ("ready", "failed")

#: A remembered upload that answers like this is gone (taken down, made private): search again, once.
_GONE = frozenset({"unavailable", "not_found", "age_restricted"})

MESSAGES = {
    "not_found": "Could not find that song on YouTube.",
    "unavailable": "YouTube does not have a copy that can be fetched.",
    "age_restricted": "That upload needs an age check, so it was skipped.",
    # The cause is in the server's log, with the source's own words; the person is not told a cause nobody proved.
    "blocked": "The server could not get this song just now. Try again in a few minutes.",
    "download_failed": "The download failed.",
    "too_big": "That file is bigger than the server allows.",
    "timeout": "The download took too long.",
    "disk_full": "The server is low on disk space.",
    "no_library": "Your account has no library to add songs to yet. Ask "
                  "whoever runs the server to set one up for you.",
    "rate_limited": "Too many songs at once. Try again in a minute.",
    "daily_limit": "That is all the songs for today. It starts again tomorrow.",
    "bad_request": "That request was not understood.",
    "internal": "Something went wrong on the server.",
}


class Dispatcher(Executor):
    """Runs jobs on a few threads, *what a person is waiting for first*.

    Three kinds of job, in this order: `now` (a song someone just tapped),
    `prep` (looking a song up ahead of a tap: one at a time) and `bulk` (the
    rest of an album being added: at most [bulk_slots] at a time). A tapped
    song therefore never waits behind a lookup or an album."""

    def __init__(self, workers: int = 2, bulk_slots: int = 1,
                 prep_slots: int = 1) -> None:
        self._queues: dict[str, list[tuple]] = {
            "now": [], "prep": [], "bulk": []}
        self._cond = threading.Condition()
        self._active = {"prep": 0, "bulk": 0}
        self._slots = {"prep": max(1, min(prep_slots, workers)),
                       "bulk": max(1, min(bulk_slots, workers))}
        self._closed = False
        self._threads = [
            threading.Thread(target=self._loop, name=f"fetch-{i}", daemon=True)
            for i in range(max(1, workers))
        ]
        for t in self._threads:
            t.start()

    def submit(self, fn, /, *args, **kwargs):
        from concurrent.futures import Future

        future: Future = Future()
        job = args[0] if args else None
        kind = getattr(job, "kind", None)
        if kind not in self._queues:
            kind = ("bulk" if getattr(getattr(job, "request", None),
                                      "bulk", False) else "now")
        with self._cond:
            self._queues[kind].append((fn, args, kwargs, future, kind))
            self._cond.notify()
        return future

    def _next(self):
        if self._queues["now"]:
            return self._queues["now"].pop(0)
        for kind in ("prep", "bulk"):
            if self._queues[kind] and self._active[kind] < self._slots[kind]:
                self._active[kind] += 1
                return self._queues[kind].pop(0)
        return None

    def _loop(self) -> None:
        while True:
            with self._cond:
                item = self._next()
                while item is None:
                    if self._closed:
                        return
                    self._cond.wait()
                    item = self._next()
            fn, args, kwargs, future, kind = item
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as error:  # noqa: BLE001
                future.set_exception(error)
            finally:
                if kind in self._active:
                    with self._cond:
                        self._active[kind] -= 1
                        self._cond.notify_all()

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False):
        with self._cond:
            self._closed = True
            self._cond.notify_all()


class Downloader(Protocol):
    def extract(self, video_id: str, info: Path) -> None: ...

    def download(self, video_id: str, stem: Path,
                 duration_s: int | None = None,
                 info: Path | None = None) -> Downloaded: ...


@dataclass
class Request:
    artist: str
    title: str
    album: str | None = None
    track: int | None = None
    disc: int | None = None
    disc_total: int | None = None
    year: int | None = None
    duration_s: int | None = None
    cover_url: str | None = None
    #: Part of adding a whole album, not a song someone is waiting for.
    bulk: bool = False
    #: The YouTube video a playlist pointed at: used only when searching by name finds nothing...
    video_id: str | None = None
    #: ...unless it is YouTube's own official upload of the song (an "Artist - Topic" channel): then it is used at once,
    #: with no search (2-12 s saved a song, and no risk of a different version being chosen).
    video_first: bool = False

    def key(self) -> str:
        return "|".join((self.artist.strip().lower(), self.title.strip().lower(),
                         (self.album or "").strip().lower()))


def _job_key(auth: Auth, request: Request) -> str:
    """One job per person and song. The same song asked by two people is two jobs: each person's copy goes to their own library, and
    a person must never be handed somebody else's job (a friend streamed the owner's copy and could not like it: 2026-10-17)."""
    return f"{auth.user.strip().lower()}|{request.key()}"


@dataclass
class Job:
    id: str
    key: str
    user: str
    request: Request
    state: str = "queued"
    detail: str = ""
    error: str | None = None
    song_id: str | None = None
    path: str | None = None
    codec: str | None = None
    bitrate_kbps: int | None = None
    created: float = 0.0
    updated: float = 0.0
    #: The file in the library (never sent to a client; served by
    #: `GET /api/play/<id>/audio`).
    file: Path | None = field(default=None, repr=False)
    #: Where the download is written (a live reader tails it).
    stem: Path | None = field(default=None, repr=False)
    #: Which upload was chosen, and what YouTube said about its streams.
    video_id: str | None = field(default=None, repr=False)
    #: The next best uploads of a fresh search (id, title, length), tried when the chosen one cannot be fetched.
    alternates: list = field(default_factory=list, repr=False)
    video_title: str = field(default="", repr=False)
    video_duration_s: int | None = field(default=None, repr=False)
    info: Path | None = field(default=None, repr=False)
    #: Only looking the song up ahead of a tap: park when that is done.
    prepare_only: bool = False
    _auth: Auth | None = field(default=None, repr=False)

    @property
    def done(self) -> bool:
        return self.state in TERMINAL

    @property
    def kind(self) -> str:
        if self.prepare_only:
            return "prep"
        return "bulk" if self.request.bulk else "now"

    @property
    def downloading(self) -> bool:
        """The audio is still arriving (or about to)."""
        return self.state in ("queued", "searching", "downloading")

    def stream_snapshot(self) -> tuple[Path | None, bool]:
        """`(file to read, more bytes may still arrive)`.

        While the song downloads this is the file being written; afterwards
        the downloaded file if it is still there, else the library copy."""
        if self.stem is not None:
            found = live_source(self.stem)
            if found is not None:
                return found[0], found[1] or self.downloading
        if self.file is not None and self.file.is_file():
            return self.file, False
        return None, self.downloading

    def streamable(self) -> bool:
        """Enough has arrived for a player to start (about two seconds)."""
        if (self.state == "ready" and self.file is not None
                and self.file.is_file()):
            return True
        path, _ = self.stream_snapshot()
        if path is None:
            return False
        try:
            return path.stat().st_size >= 24 * 1024
        except OSError:
            return False

    def view(self) -> dict:
        out: dict[str, object] = {"id": self.id, "state": self.state}
        if self.detail:
            out["detail"] = self.detail
        if self.error:
            out["error"] = self.error
            out["message"] = MESSAGES.get(self.error, MESSAGES["internal"])
        if self.song_id:
            out["songId"] = self.song_id
        if self.path:
            out["path"] = self.path
        if self.state != "failed" and self.streamable():
            out["stream"] = f"/api/play/{self.id}/audio"
        if self.codec:
            out["codec"] = self.codec
        if self.bitrate_kbps:
            out["bitrateKbps"] = self.bitrate_kbps
        return out


class Limits(Exception):
    """Raised by `submit` when a person asks for too much."""


class JobManager:
    def __init__(
        self,
        *,
        music_dir: Path,
        work_dir: Path,
        resolver: Resolver,
        downloader: Downloader,
        navidrome: Navidrome,
        executor: Executor | None = None,
        cover: Callable[[str | None], bytes | None] = fetch_cover,
        tagger: Callable[[Path, Tags, bytes | None], bool] = write_tags,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        min_free_gb: int = 20,
        max_duration_s: int = 2700,
        daily_limit: int = 80,
        active_limit: int = 3,
        index_wait_s: float = 40.0,
        watcher_wait_s: float = 0.0,
        keep_s: float = 3600.0,
        prepare_ttl_s: float = 1200.0,
        prepare_limit: int = 40,
        indexer: Executor | None = None,
        skip_index: bool = False,
        people: PersonLayout | None = None,
        retry_delay_s: float = 6.0,
        cache_dir: Path | None = None,
        cache_max_mb: int = 1500,
        cache_max_bytes: int | None = None,
        resolve_ttl_s: float = 30 * 86400.0,
        enricher: Callable[[str, str, int | None], Meta | None] | None = None,
    ) -> None:
        self._retry_delay = retry_delay_s
        # What a playlist does not say (album, cover, number, year): looked up in the background while the audio downloads.
        self._enricher = enricher
        self._meta_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="meta") if enricher else None
        #: Told when YouTube refuses (the import queue rests too: a person's tap and a playlist share one address).
        #: Told when YouTube refuses a run, with the account the run used (or `None`: the visitor's)
        self.refusal_listener: Callable[[str | None], None] | None = None
        #: When each song that needed YouTube finished (taps, imports, everybody): YouTube counts per address, about
        #: 300 videos an hour for a visitor without a login (yt-dlp wiki), so the import queue paces itself by this.
        self._downloads: deque[float] = deque()
        # What was found and fetched before (cache.py): the next person asking for the same song waits for nothing.
        self._resolutions = ResolveCache(work_dir / "resolve-cache.json", clock, resolve_ttl_s)
        self._files = FileCache(
            cache_dir if cache_dir is not None else work_dir / "cache",
            cache_max_bytes if cache_max_bytes is not None else cache_max_mb * 1024 * 1024, clock)
        self._music = music_dir
        # None = one shared library (the old layout); a layout = each person's songs go to their own folder.
        self._people = people
        self._work = work_dir
        self._resolver = resolver
        self._downloader = downloader
        self._nd = navidrome
        self._executor = executor or Dispatcher(workers=3, bulk_slots=2)
        self._cover = cover
        self._tagger = tagger
        self._clock = clock
        self._sleep = sleep
        self._min_free_gb = min_free_gb
        self._max_duration = max_duration_s
        self._daily = daily_limit
        self._active_limit = active_limit
        self._index_wait = index_wait_s
        self._watcher_wait = watcher_wait_s
        self._keep = keep_s
        self._prepare_ttl = prepare_ttl_s
        self._prepare_limit = prepare_limit
        # Telling the music server about a new file is slow and nobody waits
        # for it, so it has a thread of its own: a song is playable (from the
        # service) the moment it is in the library.
        self._indexer = indexer or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="index")
        self._skip_index = skip_index
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}
        self._counts: dict[tuple[str, str], int] = {}
        self._prepares: dict[tuple[str, int], int] = {}

    # ---------------------------------------------------------------- API

    def _check_limits(self, auth: Auth, now: float) -> str:
        """Raises `Limits` when [auth]'s person asks for too much; otherwise
        counts one more song for today (caller holds the lock)."""
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        if self._counts.get((auth.user, day), 0) >= self._daily:
            raise Limits("daily")
        active = sum(1 for j in self._jobs.values()
                     if j.user == auth.user and not j.done
                     and j.state != "prepared")
        if active >= self._active_limit:
            raise Limits("active")
        self._counts[(auth.user, day)] = (
            self._counts.get((auth.user, day), 0) + 1)
        return day

    def submit(self, auth: Auth, request: Request, *, internal: bool = False) -> Job:
        """Starts (or joins) the job for a song. [internal] is the import queue, which paces itself (imports.py) and so is
        not counted against the person's taps."""
        now = self._clock()
        resubmit = False
        with self._lock:
            self._forget_old(now)
            existing = self._by_key.get(_job_key(auth, request))
            if existing is not None:
                job = self._jobs.get(existing)
                if job is not None and (not job.done or job.state == "ready"):
                    if job.prepare_only:
                        # Somebody now wants what was only being prepared.
                        if not internal:
                            self._check_limits(auth, now)
                        job.prepare_only = False
                        job.request.bulk = request.bulk
                        job.user = auth.user
                        job._auth = auth
                        if job.state == "prepared":
                            job.state = "queued"
                            job.updated = now
                            resubmit = True
                    if not resubmit:
                        return job
            if not resubmit:
                if not internal:
                    self._check_limits(auth, now)
                job = Job(
                    id=secrets.token_hex(8), key=_job_key(auth, request),
                    user=auth.user, request=request, created=now, updated=now,
                    _auth=auth)
                self._jobs[job.id] = job
                self._by_key[job.key] = job.id
        self._executor.submit(self._run, job)
        return job

    def prepare(self, auth: Auth, request: Request) -> Job:
        """Looks the song up (search, YouTube streams) without downloading
        it, so the tap that probably follows starts at once. Cheap, limited
        per person and per hour, and forgotten after [prepare_ttl_s]."""
        now = self._clock()
        with self._lock:
            self._forget_old(now)
            existing = self._by_key.get(_job_key(auth, request))
            if existing is not None:
                job = self._jobs.get(existing)
                if job is not None and (not job.done or job.state == "ready"):
                    return job
            hour = int(now // 3600)
            used = self._prepares.get((auth.user, hour), 0)
            if used >= self._prepare_limit:
                raise Limits("prepare")
            self._prepares[(auth.user, hour)] = used + 1
            job = Job(
                id=secrets.token_hex(8), key=_job_key(auth, request), user=auth.user,
                request=request, created=now, updated=now, _auth=auth,
                prepare_only=True)
            self._jobs[job.id] = job
            self._by_key[job.key] = job.id
        self._executor.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def downloads_since(self, seconds: float) -> int:
        """How many songs that needed YouTube finished (or failed) in the last [seconds]."""
        with self._lock:
            cutoff = self._clock() - seconds
            while self._downloads and self._downloads[0] < cutoff:
                self._downloads.popleft()
            return len(self._downloads)

    def download_times(self) -> list[float]:
        """When the songs of the last hour that needed YouTube finished (saved by the import queue, so a restart does
        not make the server forget that it has just fetched two hundred)."""
        with self._lock:
            cutoff = self._clock() - 3600  # not downloads_since(): this lock is not re-entrant
            while self._downloads and self._downloads[0] < cutoff:
                self._downloads.popleft()
            return list(self._downloads)

    def restore_downloads(self, times: list[float]) -> None:
        with self._lock:
            now = self._clock()
            self._downloads = deque(sorted(t for t in times if isinstance(t, (int, float)) and now - 3600 <= t <= now))

    def _count_download(self, job: Job) -> None:
        if job.video_id is not None:
            with self._lock:
                self._downloads.append(self._clock())

    # ----------------------------------------------------------- internals

    def _forget_old(self, now: float) -> None:
        for jid in [j.id for j in self._jobs.values()
                    if (j.done and now - j.updated > self._keep)
                    or (j.state == "prepared"
                        and now - j.updated > self._prepare_ttl)]:
            job = self._jobs.pop(jid)
            if self._by_key.get(job.key) == jid:
                del self._by_key[job.key]
            self._sweep(job)
        hour = int(now // 3600)
        for key in [k for k in self._prepares if k[1] < hour]:
            del self._prepares[key]

    def _sweep(self, job: Job) -> None:
        """Removes what a forgotten job left in the work folder."""
        base = job.stem if job.stem is not None else self._work / job.id
        try:
            for p in base.parent.glob(base.name + ".*"):
                p.unlink(missing_ok=True)
        except OSError:
            pass

    def _set(self, job: Job, state: str, detail: str = "") -> None:
        with self._lock:
            job.state = state
            job.detail = detail
            job.updated = self._clock()
        log.info("job %s %-11s +%.1fs  %s - %s", job.id, state,
                 job.updated - job.created, job.request.artist,
                 job.request.title)

    #: Failures that are an ordinary answer ("YouTube has no such song"), not something to look into.
    _ORDINARY = frozenset({"not_found", "unavailable", "age_restricted", "no_library", "rate_limited", "daily_limit", "too_big", "bad_request"})

    def _fail(self, job: Job, code: str, detail: str = "", account: str | None = None) -> None:
        with self._lock:
            job.state = "failed"
            job.error = code
            job.detail = detail
            job.updated = self._clock()
            job._auth = None
        # A failure used to leave no trace: a temporary block by YouTube showed up as "not answering" in the app and nothing here.
        # One line, with YouTube's own reason; never the login (the detail is yt-dlp's text about the video).
        self._count_download(job)
        if code == "blocked" and self.refusal_listener is not None:
            try:
                self.refusal_listener(account)
            except Exception:  # noqa: BLE001 - a listener never breaks a job
                log.exception("the refusal listener failed")
        why = " ".join(detail.split())[:160]
        log.log(logging.INFO if code in self._ORDINARY else logging.WARNING,
                "job %s failed       +%.1fs  %s - %s: %s%s", job.id, job.updated - job.created,
                job.request.artist, job.request.title, code, f" ({why})" if why and why != code else "")

    def _finish(self, job: Job) -> None:
        with self._lock:
            job.state = "ready"
            job.updated = self._clock()
            job._auth = None
        self._count_download(job)
        log.info("job %s ready       +%.1fs  %s - %s (%s %s kbps)", job.id,
                 job.updated - job.created, job.request.artist,
                 job.request.title, job.codec, job.bitrate_kbps)

    #: A try that may work a moment later (the source was busy, the line dropped); one more try, then the failure is shown.
    #: "Not there", "age check" and the like are answers: asking again changes nothing.
    _TRANSIENT = frozenset({"blocked", "timeout", "download_failed"})

    def _run(self, job: Job) -> None:
        tried = False
        while True:
            try:
                self._pipeline(job)
            except DownloadError as error:
                if error.code in self._TRANSIENT and not tried:
                    tried = True
                    why = " ".join(str(error).split())[:160]
                    log.info("job %s %s, trying again in %.0fs  %s - %s (%s)", job.id, error.code,
                             self._retry_delay, job.request.artist, job.request.title, why)
                    self._sleep(self._retry_delay)
                    continue
                self._fail(job, error.code, str(error)[:200], account=getattr(error, "account", None))
            except Limits:
                self._fail(job, "rate_limited")
            except Exception as error:  # noqa: BLE001 - a job never crashes a worker
                log.exception("job %s (%s - %s) failed", job.id,
                              job.request.artist, job.request.title)
                self._fail(job, "internal", f"{type(error).__name__}")
            return

    def _pipeline(self, job: Job) -> None:
        r = job.request
        auth = job._auth
        assert auth is not None

        # 1. Already there? Then it is just a song to play.
        have = self._nd.find_song(
            auth, artist=r.artist, title=r.title, album=r.album)
        if have:
            job.song_id = have
            self._finish(job)
            return

        # Whose library does it go into? Asked before anything is downloaded: somebody with nowhere to put it is told at once.
        root = self._music
        if self._people is not None:
            root = self._people.root_for(auth.user)
            if root is None:
                raise DownloadError("no_library")

        if free_gb(root) < self._min_free_gb:
            raise DownloadError("disk_full")

        # 2. Which upload is it? (Already known for a prepared song, or for a song somebody asked for in the last month.)
        key = song_key(r.artist, r.title, r.duration_s)
        from_memory = False
        if job.video_id is None and r.video_first and r.video_id:
            job.video_id = r.video_id
            job.video_title = f"{r.artist} - {r.title}"
            job.video_duration_s = r.duration_s
            # Treated like a remembered upload: if it has gone, the song is searched for after all.
            from_memory = True
        if job.video_id is None:
            remembered = self._resolutions.get(key)
            if remembered is not None:
                job.video_id = remembered["video_id"]
                job.video_title = remembered.get("title", "")
                job.video_duration_s = remembered.get("duration_s")
                from_memory = True
            else:
                self._find_upload(job, key)

        # 2b. What YouTube says about its streams: the slow part, so it is kept (and can be done before anybody taps).
        #     Not needed at all when the audio itself is already here.
        kept = self._files.get(job.video_id)
        if kept is None and (job.info is None or not job.info.is_file()):
            self._set(job, "searching", "streams")
            info = self._work / f"{job.id}.info.json"
            try:
                self._downloader.extract(job.video_id, info)
            except DownloadError as error:
                if error.code in _GONE and job.alternates and not from_memory:
                    # The best upload cannot be fetched (an age gate, taken down): the next best one, and remember that one.
                    self._extract_alternate(job, key, info, error)
                elif not (from_memory and error.code in _GONE):
                    raise
                else:
                    # The upload that was remembered has gone: ask again, once (and the new search's next best uploads are
                    # there as well when its first choice cannot be fetched either).
                    self._resolutions.drop(key)
                    self._find_upload(job, key)
                    kept = self._files.get(job.video_id)
                    if kept is None:
                        self._extract_choosing(job, key, info)
            job.info = info if info.is_file() else None

        with self._lock:
            if job.prepare_only:
                job.state = "prepared"
                job.detail = ""
                job.updated = self._clock()
                job._auth = None
                parked = True
            else:
                parked = False
        if parked:
            log.info("job %s prepared    +%.1fs  %s - %s", job.id,
                     job.updated - job.created, r.artist, r.title)
            return
        auth = job._auth
        assert auth is not None

        # 3. The audio, untouched: from the copy kept for the last person who asked, or downloaded. Meanwhile the
        #    album, cover, number and year are looked up (a playlist gives only a title and an artist).
        meta_wait = self._start_lookup(r)
        stem = self._work / f"{job.id}"
        job.stem = stem
        got = self._audio_from_cache(job, stem)
        if got is None:
            self._set(job, "downloading", job.video_title[:80])
            try:
                got = self._downloader.download(
                    job.video_id, stem, job.video_duration_s or r.duration_s,
                    info=job.info)
            except DownloadError as error:
                if not (from_memory and error.code in _GONE):
                    raise
                self._resolutions.drop(key)
                self._find_upload(job, key)
                self._downloader.extract(job.video_id, self._work / f"{job.id}.info.json")
                job.info = self._work / f"{job.id}.info.json"
                got = self._downloader.download(
                    job.video_id, stem, job.video_duration_s or r.duration_s,
                    info=job.info)
            self._files.put(job.video_id, got.path, got.codec, got.bitrate_kbps)
        job.codec, job.bitrate_kbps = got.codec, got.bitrate_kbps

        # 4. Tags and cover, so it looks like the rest of the library.
        self._apply_lookup(r, meta_wait)
        self._set(job, "tagging")
        # No album is a single, and a single's album is its own name: an empty album tag shows up as "[Unknown Album]" in every app.
        tags = Tags(title=r.title, artist=r.artist, album=r.album or r.title,
                    track=r.track, disc=r.disc, year=r.year)
        self._tagger(got.path, tags, self._cover_bytes(r.cover_url, job.video_id))

        # 5. Into the library, next to the album's other songs.
        placement = plan_placement(
            root, artist=r.artist, album=r.album, title=r.title,
            track=r.track, disc=r.disc, total_discs=r.disc_total,
            suffix=got.path.suffix.lower())
        existing = find_existing(placement, r.title)
        if existing is not None:
            got.path.unlink(missing_ok=True)
            target = existing
        else:
            target = place_file(got.path, placement, root)
        job.path = str(target.relative_to(root)).replace("\\", "/")
        job.file = target

        # 6. Playable now. The music server is told in the background; the
        #    app plays the library copy when it knows the id and this stream
        #    when it does not (a scan can take minutes, a song should not).
        self._finish(job)
        if not self._skip_index:
            self._indexer.submit(self._index, job, auth)

    def _cover_bytes(self, cover_url: str | None, video_id: str | None) -> bytes | None:
        """The picture for the file: the catalogue's cover when there is one, else the video's own picture (for a
        YouTube Music "Topic" upload that is the album art; for a music video a frame). A letter on a tile is the last
        resort, not the first (the owner, 2026-10-18)."""
        urls = [cover_url] if cover_url else []
        if video_id:
            urls += [f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg", f"https://i.ytimg.com/vi/{video_id}/hq720.jpg"]
        for url in urls:
            picture = self._cover(url)
            if picture:
                return picture
        return None

    def _start_lookup(self, r: Request):
        """Starts looking up what [r] lacks; the result is waited for just before tagging."""
        if self._enricher is None or self._meta_pool is None or (r.album and r.cover_url):
            return None
        return self._meta_pool.submit(self._enricher, r.artist, r.title, r.duration_s)

    @staticmethod
    def _apply_lookup(r: Request, pending) -> None:
        """Fills what the request lacks from the lookup, never replacing what the caller knew."""
        if pending is None:
            return
        try:
            meta = pending.result(timeout=12)
        except Exception:  # noqa: BLE001 - a slow or failed lookup leaves the song as it was
            return
        if meta is None:
            return
        r.album = r.album or meta.album
        r.cover_url = r.cover_url or meta.cover_url
        r.track = r.track or meta.track
        r.disc = r.disc or meta.disc
        r.year = r.year or meta.year

    def _extract_choosing(self, job: Job, key: str, info: Path) -> None:
        """Asks for the chosen upload's streams; when it is refused as gone or age-gated, the next best uploads are tried."""
        try:
            self._downloader.extract(job.video_id, info)
        except DownloadError as error:
            if error.code in _GONE and job.alternates:
                self._extract_alternate(job, key, info, error)
            else:
                raise

    def _extract_alternate(self, job: Job, key: str, info: Path, first: DownloadError) -> None:
        """The chosen upload could not be fetched: try the next best ones in turn; the failure of the last one is the answer."""
        error = first
        while job.alternates:
            job.video_id, job.video_title, job.video_duration_s = job.alternates.pop(0)
            log.info("job %s: %s for the first choice; trying %s", job.id, error.code, job.video_id)
            try:
                self._downloader.extract(job.video_id, info)
            except DownloadError as again:
                if again.code not in _GONE:
                    raise
                error = again
                continue
            self._resolutions.put(key, job.video_id, job.video_title, job.video_duration_s)
            return
        raise error

    def stream_candidates(self, request: Request) -> list[tuple[str, str, int | None]]:
        """The uploads that may be the song, best first (video id, title, length): for playing it by streaming (stream.py). The upload
        a person was last given, or the one a playlist pointed at, comes first; otherwise a search."""
        if request.video_id and (request.video_first or not request.artist):
            return [(request.video_id, "", request.duration_s)]
        key = song_key(request.artist, request.title, request.duration_s)
        remembered = self._resolutions.get(key)
        found: list[tuple[str, str, int | None]] = []
        if remembered is not None:
            found.append((remembered["video_id"], remembered.get("title", ""), remembered.get("duration_s")))
        else:
            want = Want(request.artist, request.title, request.album, request.duration_s)
            ranked_search = getattr(self._resolver, "resolve_ranked", None)
            if ranked_search is not None:
                found = [(s.candidate.video_id, s.candidate.title, s.candidate.duration_s) for s in ranked_search(want)[:3]]
            else:
                one = self._resolver.resolve(want)
                found = [(one.candidate.video_id, one.candidate.title, one.candidate.duration_s)] if one else []
            if found:
                self._resolutions.put(key, *found[0])
        if not found and request.video_id:
            found = [(request.video_id, "", request.duration_s)]
        return found

    def extract_streams(self, video_id: str, info: Path) -> None:
        """What YouTube says about a video's streams, written to [info] (the same file a download starts from)."""
        self._downloader.extract(video_id, info)

    def _find_upload(self, job: Job, key: str) -> None:
        """Searches for the upload and remembers the answer."""
        r = job.request
        self._set(job, "searching")
        want = Want(r.artist, r.title, r.album, r.duration_s)
        ranked_search = getattr(self._resolver, "resolve_ranked", None)
        job.alternates = []
        if ranked_search is not None:
            ranked = ranked_search(want)
            found = ranked[0] if ranked else None
            job.alternates = [(s.candidate.video_id, s.candidate.title, s.candidate.duration_s) for s in ranked[1:3]]
        else:
            found = self._resolver.resolve(want)
        if found is None:
            if r.video_id is None:
                raise DownloadError("not_found")
            # A playlist saved this very video: it is the song when the name leads nowhere.
            job.video_id = r.video_id
            job.video_title = f"{r.artist} - {r.title}"
            job.video_duration_s = r.duration_s
            return
        job.video_id = found.candidate.video_id
        job.video_title = found.candidate.title
        job.video_duration_s = found.candidate.duration_s
        self._resolutions.put(key, job.video_id, job.video_title, job.video_duration_s)

    def _audio_from_cache(self, job: Job, stem: Path) -> Downloaded | None:
        """A copy of the audio kept from an earlier request, as if it had just been downloaded."""
        kept = self._files.get(job.video_id)
        if kept is None:
            return None
        path, codec, kbps = kept
        try:
            stem.parent.mkdir(parents=True, exist_ok=True)
            target = stem.with_suffix(path.suffix)
            shutil.copyfile(path, target)
        except OSError:
            return None
        log.info("job %s from the copy of %s kept earlier", job.id, job.video_id)
        return Downloaded(target, codec, kbps)

    def _index(self, job: Job, auth: Auth) -> None:
        r = job.request
        try:
            # The music server's own file watcher lists a new file within seconds. A scan asked for per song moves the scan time that
            # every open phone watches (each move made a phone re-download the library, H38): only a song the watcher has not listed
            # after a few seconds gets one.
            now = self._clock()
            deadline = now + self._index_wait
            scan_after = now + self._watcher_wait
            asked = False
            while True:
                song = self._nd.find_song(
                    auth, artist=r.artist, title=r.title, album=r.album,
                    relative_path=job.path)
                if song:
                    with self._lock:
                        job.song_id = song
                        job.updated = self._clock()
                    return
                now = self._clock()
                if now >= deadline:
                    return
                if not asked and now >= scan_after:
                    asked = True
                    self._nd.start_scan(auth)
                self._sleep(2.0)
        except Exception:  # noqa: BLE001 - never let indexing crash a thread
            log.exception("indexing %s failed", job.id)
