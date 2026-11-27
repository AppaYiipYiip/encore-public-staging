"""Keeping a song: fetch its audio once, tag it, put it in the shared folder, wait until the music server has it, attach it to the ref.

Why it can be repeated at any point: the folder is looked at first (a file placed by a run that died before the music server saw it is
linked, not downloaded again), and attaching a file that is already attached changes nothing. Why nothing a person has can break:
likes, playlists and history point at the *ref*; this only adds a row to `song_file`.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .. import library, refs
from ..album_pass import KeepAnswer, file_or_listing_length
from ..artist_basis import is_performer
from ..audio_key import Unreadable, audio_key_of
from ..db import Database
from ..deezer import LookupUnavailable
from ..errors import ApiError
from ..navidrome import NavidromeClient, file_meta
from ..scheduler import GiveUp, Retry, WorkItem
from ..sources.youtube.errors import DownloadError
from ..sources.youtube.source import Wanted, wanted_from_ref
from ..textnorm import is_unknown_artist
from .covers import fetch_cover, write_folder_picture
from .placement import AUDIO_SUFFIXES, Placement, find_existing, free_gb, inside, place_file, plan_for_ref
from .process import Runner, run_command
from .tagging import tags_of, write_tags

log = logging.getLogger("encore_server.keeper")

#: The folder, inside the music folder, that holds everything the server keeps.
KEPT_FOLDER = "Encore"


class Reservations:
    """The files a keep has placed or taken and not yet linked, process-wide (audit B-110's window, found by the review of PR 129).

    A file is the song's own from the moment a keep places it, but the row that says so (`song_file`) is written only after the music server has found the file (up to
    `scan_wait_s`, 45 s). In between, a second keep of another ref of the same song (the owner's Creature pair, two workers) looked in the same folder, found no row, and took
    the file: two refs held one path. So a keep RESERVES the file in the same step that places or takes it, and releases it when its link is done (or failed): `claim` is
    the only way a keep takes a file at the place it would choose, and a file reserved by another ref is not taken. Keyed by the resolved path without regard to case, like the
    music server compares them."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._owner: dict[str, str] = {}

    @staticmethod
    def _key(path: Path) -> str:
        return str(path.resolve()).lower()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """The lock a keep holds while it places a file and reserves it, so that nobody can look between the two."""
        with self._lock:
            yield

    def claim(self, path: Path, ref_id: str) -> bool:
        """Reserves [path] for [ref_id]. `False` (nothing changed) when ANOTHER ref has it reserved."""
        with self._lock:
            key = self._key(path)
            if self._owner.get(key, ref_id) != ref_id:
                return False
            self._owner[key] = ref_id
            return True

    def release(self, ref_id: str) -> None:
        """Everything [ref_id] reserved: its link is done, or it failed (the file has a row now, or the next try finds it)."""
        with self._lock:
            for key in [key for key, owner in self._owner.items() if owner == ref_id]:
                del self._owner[key]

    def reserved(self) -> dict[str, str]:
        with self._lock:
            return dict(self._owner)


#: The one record of the process: two keepers (a test makes many apps) never share a path, and two workers of one keeper must.
RESERVATIONS = Reservations()

#: Why a song was not kept, as `work_item.error` says it. `failures.py` turns these into the sentences a person reads (a test keeps the two in step).
GIVE_UP = {
    "not_found": "no upload of this song was found",
    "unavailable": "YouTube has no copy that can be fetched",
    "age_restricted": "the only copy needs an age check",
    "too_big": "the file is bigger than the limit for keeping",
}
_REST = {"blocked": 900.0, "timeout": 300.0, "slow": 300.0, "search_failed": 300.0}

#: The other reasons a keep ends with, named so that `failures.py` (the sentences a person reads, and whether Retry can work) matches the SAME text:
#: a reworded message here changes there too, and a test drives the real keeper through the too-long path.
TOO_LONG_BEFORE = "longer than "
TOO_LONG_AFTER = " minutes, so it is played but not kept"
NOT_IN_MUSIC_FOLDER = "the file is not inside the music folder"
MUSIC_SERVER_DID_NOT_FIND = "The music server has not found the saved file yet. Check that its library includes the music folder."
#: ...and the reasons a keep WAITS with (the item stays queued with this as its error).
RESTING = "YouTube is being given a rest"
NOT_ANSWERING_BEFORE = "YouTube is not answering ("
LOW_DISK_BEFORE = "less than "
LOW_DISK_AFTER = " GB free, so nothing more is kept for now"


class Source(Protocol):
    def download(self, wanted: Wanted, stem: Path, *, max_bytes: int) -> Path: ...

    def resting_for(self) -> float: ...


@dataclass(frozen=True)
class KeepSettings:
    music_dir: Path
    #: Keeping stops when the music folder's disk has less than this free (docs/04: the free-space floor).
    min_free_gb: float = 10.0
    #: Only keeping is limited; playing any song, of any length, is never refused for it.
    max_file_mb: int = 250
    max_minutes: int = 150
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
        audio_key_: Callable[[Path], str] = audio_key_of,
        fetch_cover_: Callable[[str | None], bytes | None] | None = None,
        find_cover_: Callable[..., str | None] | None = None,
        on_changed: Callable[[dict[str, int]], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        identify_: Callable[[str, int | None], KeepAnswer] | None = None,
        length_of_: Callable[[Path | None, object], tuple[int | None, str]] = file_or_listing_length,
    ) -> None:
        self._db = db
        self._source = source
        self._navidrome = navidrome
        self._settings = settings
        self._work = work_dir
        self._run = runner if runner is not None else run_command
        self._write_tags = write_tags_
        self._make_audio_key = audio_key_
        # Looked up when the keeper is made, not when this module is loaded, so a test can put its own in (B27): a rig that keeps a song with a picture
        # address otherwise fetched it from the real picture host (found by the network guard of P2-12).
        self._cover = fetch_cover_ if fetch_cover_ is not None else fetch_cover
        self._find_cover = find_cover_
        #: N-34 slice 3: which album is the song being kept on (`album_pass.KeepAsker`); `None` = not asked, the keep is filed as it always was.
        self._identify = identify_
        #: How a length is read: the downloaded FILE's own, else the listing's (`album_pass.file_or_listing_length`, the one definition the pass and the dry run read with).
        self._length_of = length_of_
        self._on_changed = on_changed
        self._sleep = sleep
        self._clock = clock

    # ------------------------------------------------------------------ the scheduler's handler

    def handle(self, item: WorkItem) -> None:
        """Keeps the song `item.ref`. Raises [GiveUp] or [Retry] as the scheduler understands them."""
        with self._db.read() as conn:
            ref = refs.get_ref(conn, item.ref, facts=True)
        if self._linked(ref):
            return
        try:
            path = self._existing(ref) or self._fetch(ref, item)
            self._link(ref, path)
        finally:
            RESERVATIONS.release(ref["id"])

    @staticmethod
    def _linked(ref: dict[str, Any]) -> bool:
        file = ref.get("file")
        return bool(file and file.get("navidromeSongId"))

    # ------------------------------------------------------------------ the file

    def _placement(self, ref: dict[str, Any], suffix: str = ".opus") -> Placement:
        return plan_for_ref(self._settings.root, ref, suffix)

    def _relative(self, path: Path) -> str:
        """The path as `song_file.path` holds it: relative to the music folder, with forward slashes."""
        return path.resolve().relative_to(self._settings.music_dir.resolve()).as_posix()

    def _existing(self, ref: dict[str, Any]) -> Path | None:
        """A file for this song already on the disk, so that it is linked and not fetched again: **first the song's OWN file, wherever it lies** (audit B-110: the keeper used to
        look only where it would put the song NOW, so a song whose album became known between two keeps was saved a second time, in the album's folder), then a file at the place
        it would choose now (a run that died after placing it, or the same song put there by hand)."""
        return self._own_file(ref) or find_existing(self._placement(ref), ref["title"], skip=self._taken(ref["id"]))

    def _own_file(self, ref: dict[str, Any]) -> Path | None:
        """A file THIS song's rows hold that the keeper wrote: `source = 'youtube'`, under `Encore/`, still on the disk, preferred one first. **Never a file of the Host's own
        library** (`_link` would attach it again as a kept file and a later repair would move it) and never a path that leaves the server's folder."""
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT path FROM song_file WHERE ref = ? AND source = 'youtube' AND path IS NOT NULL ORDER BY preferred DESC, added_at",
                (ref["id"],),
            ).fetchall()
        for row in rows:
            if not str(row["path"]).startswith(KEPT_FOLDER + "/"):
                continue
            path = self._settings.music_dir / str(row["path"])
            if path.suffix.lower() in AUDIO_SUFFIXES and inside(self._settings.root, path) and path.is_file():
                return path
        return None

    def _taken(self, ref_id: str) -> Callable[[Path], bool]:
        """What `find_existing` asks of a file it would take (only of a file that matches the song): `True` when it is not [ref_id]'s to take (another ref's row holds it, or
        another ref has it reserved); otherwise the file is RESERVED for [ref_id] in the same step (under the lock), so two keeps can never both take one file."""
        held = self._held_by_another(ref_id)

        def taken(path: Path) -> bool:
            with RESERVATIONS.exclusive():
                return held(path) or not RESERVATIONS.claim(path, ref_id)

        return taken

    def _held_by_another(self, ref_id: str) -> Callable[[Path], bool]:
        """Whether a file in the song's folder is the file of ANOTHER song (a row of another ref holds its path): two refs of one song, the owner's Creature, must not be handed one
        file (the shared file N-11's notes name). The music server compares paths without regard to case, and so does this."""

        def held(path: Path) -> bool:
            try:
                relative = self._relative(path)
            except (ValueError, OSError):
                return True  # not inside the music folder: never taken
            with self._db.read() as conn:
                return (
                    conn.execute(
                        "SELECT 1 FROM song_file WHERE ref != ? AND LOWER(path) = LOWER(?)", (ref_id, relative)
                    ).fetchone()
                    is not None
                )

        return held

    def _fetch(self, ref: dict[str, Any], item: WorkItem) -> Path:
        s = self._settings
        resting = self._source.resting_for()
        if resting > 0:
            raise Retry(RESTING, after_s=resting)
        duration_ms = ref.get("durationMs")
        if isinstance(duration_ms, int) and duration_ms > s.max_minutes * 60_000:
            raise GiveUp(f"{TOO_LONG_BEFORE}{s.max_minutes}{TOO_LONG_AFTER}")
        s.root.mkdir(parents=True, exist_ok=True)
        if free_gb(s.root) < s.min_free_gb:
            raise Retry(f"{LOW_DISK_BEFORE}{s.min_free_gb:g}{LOW_DISK_AFTER}", after_s=1800)
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
            if error.code in GIVE_UP:
                raise GiveUp(GIVE_UP[error.code]) from error
            if error.code in _REST:
                raise Retry(
                    f"{NOT_ANSWERING_BEFORE}{error.code})", after_s=max(_REST[error.code], self._source.resting_for())
                ) from error
            raise

    def _finish(self, ref: dict[str, Any], downloaded: Path) -> Path:
        audio = self._as_opus(downloaded)
        # The song may have changed while it downloaded (the album pass stamped its album): it is filed by what it is NOW, not by what it was when the keep began.
        ref = self._current(ref)
        # The length of the file that was just downloaded, not the import's listing (1 to 12 s off, N-11): the album question and the picture look-up are both asked with it.
        length_ms, _ = self._length_of(audio, ref.get("durationMs"))
        ref, answer = self._identified(ref, length_ms)
        picture = (
            answer.cover if answer is not None else None
        )  # a picture that came from the catalogue in this keep (never a video's thumbnail)
        cover_url = ref.get("coverUrl")
        if not cover_url and not (answer is not None and answer.outcome == "matched"):
            # A song the catalogue just placed is not looked up BY NAME for a picture: its release had none usable, and a search by name could only pick another release's.
            cover_url = picture = self._look_for_cover(ref, length_ms)
        cover = self._cover(cover_url)
        if not self._write_tags(audio, tags_of(ref), cover):
            log.info("could not write tags into %s; the file is kept with the names it has", audio.name)
        placement = self._placement(ref, audio.suffix.lower() or ".opus")
        already = find_existing(placement, ref["title"], skip=self._taken(ref["id"]))
        if already is not None:
            return already  # the same song was put there while this ran: that one stays
        with RESERVATIONS.exclusive():  # placed and reserved in one step: no other keep can look in between
            placed = place_file(audio, placement, self._settings.music_dir)
            RESERVATIONS.claim(placed, ref["id"])
        if cover and picture and cover_url == picture:
            # The album's picture is the folder's too, so the music server shows the album with it from its first scan: only a picture of the catalogue (never a video's
            # thumbnail), and only where the PLACED folder allows (`write_folder_picture`: never the shared Singles folder, never over a picture the folder has).
            self._folder_picture(ref["id"], placed, cover)
        return placed

    def _folder_picture(self, ref_id: str, placed: Path, cover: bytes) -> None:
        """The folder's picture is a nicety: whatever goes wrong with it (a full disk, a folder that cannot be written), the keep has placed its file and goes on to link it."""
        try:
            write_folder_picture(self._settings.root, placed, cover)
        except Exception:  # noqa: BLE001 - never a reason to fail a keep
            log.info("could not write the folder picture for %s; the keep goes on", ref_id, exc_info=True)

    def _current(self, ref: dict[str, Any]) -> dict[str, Any]:
        """The song as the database has it now (cheap): a keep takes minutes, and the album pass may have stamped the song meanwhile."""
        try:
            with self._db.read() as conn:
                return refs.get_ref(conn, ref["id"], facts=True)
        except ApiError:
            return ref

    def _identified(self, ref: dict[str, Any], length_ms: int | None) -> tuple[dict[str, Any], KeepAnswer | None]:
        """N-34 slice 3: which album is this song on, asked BEFORE the tags and the folder are made, so that the file lands in `Encore/<artist>/<album>/NN - Title` tagged with the
        album, the track and the year, and is never filed under "Singles" to be moved later. The ref is ALWAYS read again after the question, whatever it came to: the pass may have stamped the song while it was asked (a `not_wanted` or `skipped` answer).

        **The permanence rules.** The question is `album_pass.KeepAsker`'s: the very selection, matcher and write rule of the album pass, so a keep files a song under an album
        ONLY on a `matched` outcome the pass would have written too, and never rewrites an album the ref has. **A catalogue that cannot be asked, or any failure, never stops the
        keep** (an unreachable one fails at once; a slow one can delay it by the question's budget plus one request's own timeout): it goes on exactly as it did before, without an album and with nothing remembered, and the pass of slice 2 (and the repair of slice 5) place the song later."""
        if self._identify is None:
            return ref, None
        try:
            answer = self._identify(ref["id"], length_ms)
        except Exception:  # noqa: BLE001 - an album is a nicety of the keep, never a reason to fail it
            log.info("asking which album %s is on failed; it is kept without one", ref["id"], exc_info=True)
            return self._current(ref), None
        if answer.outcome == "unavailable":
            log.info("no album was asked for %s: the catalogue could not be asked (%s)", ref["id"], answer.reason)
        return self._current(ref), answer

    def _look_for_cover(self, ref: dict[str, Any], length_ms: int | None) -> str | None:
        """A song that came without a picture gets the catalogue's, in its file and on its ref (every phone then shows it). [length_ms] is the downloaded FILE's own (N-34 slice 3: it
        was the listing's, which can be 1 to 12 s off, until the keeper read the file); a song with none is not looked up (the keep goes on without a picture)."""
        if self._find_cover is None or not self._may_ask_the_catalogue(ref):
            return None
        try:
            url = self._find_cover(ref["artists"][0], ref["title"], ref.get("album"), length_ms=length_ms)
        except LookupUnavailable as error:
            # The catalogue is resting, switched off (`ENCORE_CATALOGUE=0`) or did not answer: not a failure, and nothing to dump into the log for every song kept.
            log.info("no picture was asked for %s: the catalogue could not be asked (%s)", ref["id"], error)
            return None
        except Exception:  # noqa: BLE001 - a picture is a nicety, never a reason to fail a keep
            log.info("looking for a picture for %s failed", ref["id"], exc_info=True)
            return None
        if url:
            with self._db.tx() as conn:
                conn.execute("UPDATE song_ref SET cover_url = ? WHERE id = ? AND cover_url IS NULL", (url, ref["id"]))
        return url

    def _may_ask_the_catalogue(self, ref: dict[str, Any]) -> bool:
        """Never for a song whose artist is a channel's name or nobody's (N-26: the stored basis `channel` or `unknown`, or the placeholder name itself,
        which the library scan gives an untagged file with no facts): the name of an uploader is not sent to the catalogue from the Host's address.
        The song is kept all the same. The basis is not in the ref a phone sees, so it is read from the row."""
        if is_unknown_artist(ref["artists"][0]):
            return False
        with self._db.read() as conn:
            row = conn.execute("SELECT artist_basis FROM song_ref WHERE id = ?", (ref["id"],)).fetchone()
        return row is None or is_performer(row["artist_basis"])

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
            raise GiveUp(NOT_IN_MUSIC_FOLDER)
        relative = path.resolve().relative_to(self._settings.music_dir.resolve()).as_posix()
        size = path.stat().st_size
        seconds = (ref.get("durationMs") or 0) / 1000
        kbps = round(size * 8 / seconds / 1000) if seconds else None
        codec = {".opus": "opus", ".ogg": "opus", ".m4a": "aac", ".aac": "aac", ".mp3": "mp3", ".flac": "flac"}.get(
            path.suffix.lower(), path.suffix.lower().lstrip(".")
        )
        navidrome_id = self._wait_for_music_server(ref, relative, size)
        meta = file_meta(self._navidrome.get_song(navidrome_id) or {}) if navidrome_id else None
        audio_key = self._audio_key(path)  # of the file as it is NOW (tagged, placed): the size is the one it is recorded at
        with self._db.tx() as conn:
            refs.attach_file(
                conn,
                ref["id"],
                navidrome_song_id=navidrome_id,
                path=relative,
                codec=codec,
                bitrate_kbps=kbps,
                source="youtube",
                meta=meta,
                audio_key=audio_key,
                audio_key_size=size if audio_key is not None else None,
            )
            touched = library.touch_ref_holders(conn, ref["id"]) if navidrome_id else {}
        if navidrome_id is None:
            # No pause of its own: a music server that never finds the file (the music folder is not one of its libraries, it cannot read it)
            # is not a wait that ends by itself. The scheduler's pauses apply, and after the last it is recorded as failed with this reason (B7).
            raise Retry(MUSIC_SERVER_DID_NOT_FIND)
        if touched and self._on_changed is not None:
            self._on_changed(touched)

    def _audio_key(self, path: Path) -> str | None:
        """The audio-only key of the file just placed (N-38). A song that cannot be keyed now is kept all the same: the hourly errand makes the key later (`audio_key.AudioKeys`)."""
        try:
            return self._make_audio_key(path)
        except (Unreadable, OSError, subprocess.TimeoutExpired) as error:
            log.warning("no audio key made when %s was kept (%s); the hourly pass will try again", path.name, error)
            return None

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
