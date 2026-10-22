"""Keeping a song: fetch its audio once, tag it, put it in the shared folder, wait until the music server has it, attach it to the ref.

Why it can be repeated at any point: the folder is looked at first (a file placed by a run that died before the music server saw it is
linked, not downloaded again), and attaching a file that is already attached changes nothing. Why nothing a person has can break:
likes, playlists and history point at the *ref*; this only adds a row to `song_file`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .. import library, refs
from ..db import Database
from ..navidrome import NavidromeClient
from ..scheduler import GiveUp, Retry, WorkItem
from ..sources.youtube.errors import DownloadError
from ..sources.youtube.source import Wanted, wanted_from_ref
from .covers import fetch_cover
from .placement import AUDIO_SUFFIXES, find_existing, free_gb, inside, place_file, plan_placement
from .process import Runner, run_command
from .tagging import Tags, write_tags

log = logging.getLogger("encore_server.keeper")

#: The folder, inside the music folder, that holds everything the server keeps.
KEPT_FOLDER = "Encore"

#: Why a song was not kept, as `work_item.error` says it (the admin page turns these into sentences).
_GIVE_UP = {
    "not_found": "no upload of this song was found",
    "unavailable": "YouTube has no copy that can be fetched",
    "age_restricted": "the only copy needs an age check",
    "too_big": "the file is bigger than the limit for keeping",
}
_REST = {"blocked": 900.0, "timeout": 300.0, "slow": 300.0}


class Source(Protocol):
    def download(self, wanted: Wanted, stem: Path, *, max_bytes: int) -> Path: ...


@dataclass(frozen=True)
class KeepSettings:
    music_dir: Path
    #: Keeping stops when the music folder's disk has less than this free (docs/04: the free-space floor).
    min_free_gb: float = 10.0
    #: Only keeping is limited; playing any song, of any length, is never refused for it.
    max_file_mb: int = 80
    max_minutes: int = 45
    #: How long to wait for the music server to find a file it was just given.
    scan_wait_s: float = 45.0
    scan_poll_s: float = 0.5

    @property
    def root(self) -> Path:
        return self.music_dir / KEPT_FOLDER


class Keeper:
    def __init__(
        self,
        db: Database,
        source: Source,
        navidrome: NavidromeClient,
        settings: KeepSettings,
        work_dir: Path,
        *,
        runner: Runner | None = None,
        write_tags_: Callable[..., bool] = write_tags,
        fetch_cover_: Callable[[str | None], bytes | None] = fetch_cover,
        on_changed: Callable[[dict[str, int]], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = db
        self._source = source
        self._navidrome = navidrome
        self._settings = settings
        self._work = work_dir
        self._run = runner if runner is not None else run_command
        self._write_tags = write_tags_
        self._cover = fetch_cover_
        self._on_changed = on_changed
        self._sleep = sleep
        self._clock = clock

    # ------------------------------------------------------------------ the scheduler's handler

    def handle(self, item: WorkItem) -> None:
        """Keeps the song `item.ref`. Raises [GiveUp] or [Retry] as the scheduler understands them."""
        with self._db.read() as conn:
            ref = refs.get_ref(conn, item.ref)
        if self._linked(ref):
            return
        path = self._existing(ref) or self._fetch(ref, item)
        self._link(ref, path)

    @staticmethod
    def _linked(ref: dict[str, Any]) -> bool:
        file = ref.get("file")
        return bool(file and file.get("navidromeSongId"))

    # ------------------------------------------------------------------ the file

    def _placement(self, ref: dict[str, Any], suffix: str = ".opus") -> Any:
        artist = ref.get("albumArtist") or ref["artists"][0]
        return plan_placement(
            self._settings.root,
            artist=artist,
            album=ref.get("album"),
            title=ref["title"],
            track=ref.get("trackNo"),
            disc=ref.get("discNo"),
            suffix=suffix,
        )

    def _existing(self, ref: dict[str, Any]) -> Path | None:
        """A file for this song already in its folder (a run that died after placing it, or the same song put there by hand)."""
        return find_existing(self._placement(ref), ref["title"])

    def _fetch(self, ref: dict[str, Any], item: WorkItem) -> Path:
        s = self._settings
        duration_ms = ref.get("durationMs")
        if isinstance(duration_ms, int) and duration_ms > s.max_minutes * 60_000:
            raise GiveUp(f"longer than {s.max_minutes} minutes, so it is played but not kept")
        s.root.mkdir(parents=True, exist_ok=True)
        if free_gb(s.root) < s.min_free_gb:
            raise Retry(f"less than {s.min_free_gb:g} GB free, so nothing more is kept for now", after_s=1800)
        stem = self._work / f"keep-{item.id}"
        downloaded = self._download(ref, stem)
        try:
            return self._finish(ref, downloaded)
        finally:
            for leftover in stem.parent.glob(stem.name + ".*"):
                leftover.unlink(missing_ok=True)

    def _download(self, ref: dict[str, Any], stem: Path) -> Path:
        self._work.mkdir(parents=True, exist_ok=True)
        try:
            return self._source.download(wanted_from_ref(ref), stem, max_bytes=self._settings.max_file_mb * 1024 * 1024)
        except DownloadError as error:
            if error.code in _GIVE_UP:
                raise GiveUp(_GIVE_UP[error.code]) from error
            if error.code in _REST:
                raise Retry(f"YouTube is not answering ({error.code})", after_s=_REST[error.code]) from error
            raise

    def _finish(self, ref: dict[str, Any], downloaded: Path) -> Path:
        audio = self._as_opus(downloaded)
        cover = self._cover(ref.get("coverUrl"))
        tags = Tags(
            title=ref["title"],
            artist=", ".join(ref["artists"]),
            album=ref.get("album"),
            album_artist=ref.get("albumArtist") or ref["artists"][0],
            track=ref.get("trackNo"),
            disc=ref.get("discNo"),
            year=ref.get("year"),
            isrc=ref.get("isrc"),
            mbid=ref.get("mbid"),
        )
        if not self._write_tags(audio, tags, cover):
            log.info("could not write tags into %s; the file is kept with the names it has", audio.name)
        placement = self._placement(ref, audio.suffix.lower() or ".opus")
        already = find_existing(placement, ref["title"])
        if already is not None:
            return already  # the same song was put there while this ran: that one stays
        return place_file(audio, placement, self._settings.music_dir)

    def _as_opus(self, path: Path) -> Path:
        """YouTube's Opus arrives in a WebM container; the library's own format is the same Opus in Ogg (no re-encoding)."""
        if path.suffix.lower() != ".webm":
            return path
        out = path.with_suffix(".opus")
        result = self._run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn", "-c:a", "copy", str(out)], 60)
        if result.returncode != 0 or not out.exists():
            out.unlink(missing_ok=True)
            raise RuntimeError(f"could not repackage the download ({result.stderr.strip()[:200] or result.returncode})")
        return out

    # ------------------------------------------------------------------ the music server and the ref

    def _link(self, ref: dict[str, Any], path: Path) -> None:
        """Attach the file to the ref; then wait for the music server to know it, and attach its id."""
        if not inside(self._settings.music_dir, path) or path.suffix.lower() not in AUDIO_SUFFIXES:
            raise GiveUp("the file is not inside the music folder")
        relative = path.resolve().relative_to(self._settings.music_dir.resolve()).as_posix()
        size = path.stat().st_size
        seconds = (ref.get("durationMs") or 0) / 1000
        kbps = round(size * 8 / seconds / 1000) if seconds else None
        codec = {".opus": "opus", ".ogg": "opus", ".m4a": "aac", ".aac": "aac", ".mp3": "mp3", ".flac": "flac"}.get(
            path.suffix.lower(), path.suffix.lower().lstrip(".")
        )
        navidrome_id = self._wait_for_music_server(ref, relative, size)
        with self._db.tx() as conn:
            refs.attach_file(
                conn, ref["id"], navidrome_song_id=navidrome_id, path=relative, codec=codec, bitrate_kbps=kbps, source="youtube"
            )
            touched = library.touch_ref_holders(conn, ref["id"]) if navidrome_id else {}
        if navidrome_id is None:
            raise Retry("the music server has not found the file yet", after_s=30)
        if touched and self._on_changed is not None:
            self._on_changed(touched)

    def _wait_for_music_server(self, ref: dict[str, Any], relative: str, size: int) -> str | None:
        """Tells the music server there is a new file at once (it is told here, not left to its schedule), waits for its scan to end,
        and looks for the song; a second request for a scan goes out if it has not found it after a few seconds."""
        s = self._settings
        deadline = self._clock() + s.scan_wait_s
        self._navidrome.start_scan()
        asked_again = False
        while True:
            if not self._navidrome.scanning():
                found = self._navidrome.find_song(
                    artist=ref["artists"][0], title=ref["title"], album=ref.get("album"), relative_path=relative, size=size
                )
                if found is not None:
                    return found
            if self._clock() >= deadline:
                return None
            self._sleep(s.scan_poll_s)
            if not asked_again and self._clock() >= deadline - s.scan_wait_s * 0.7:
                self._navidrome.start_scan()
                asked_again = True
