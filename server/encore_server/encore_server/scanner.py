"""The scanner link (docs/04 section 3, P2-01): every song the music server already has gets a ref and a file.

The Host's own collection, the songs the keeper put there, and anything added by hand all become refs the same way, so a person can
like, queue and add to playlists whatever the server has, and the server's files and the people's choices never share an id. A file that
already has a row (its id in the music server) belongs to the ref of that row, whatever its tags say: the keeper attached it on purpose, to
the ref an import or the catalogue described properly, and the scan makes nothing for it (N-11: describing it again from its tags made a
second ref for the same file). A song no ref has a file
for is described from its tags, and when that description already has a ref (matched by ISRC, then by artist, title and length) it is
*attached* to it, so one recording found in several folders is one ref with several files. A file that is gone from the library loses
its row; the ref, and every like and playlist entry pointing at it, stays.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from . import library, refmerge, refs, rehome, textnorm
from .db import Database
from .errors import ApiError
from .ids import now_ms
from .link_listing import Listing
from .link_plan import LinkPlan
from .navidrome import file_meta

log = logging.getLogger("encore_server.scanner")

PAGE = 500
#: How a pass is said in the log: which of the reasons in `link_plan.Kind` started it.
_WHY = {"scan": "after a scan of the music server", "poke": "asked for"}
_CODEC = {"opus": "opus", "ogg": "opus", "m4a": "aac", "aac": "aac", "mp3": "mp3", "flac": "flac", "wav": "wav"}


class Library(Protocol):
    def songs(self, offset: int, size: int = ...) -> list[dict[str, Any]] | None: ...


@dataclass
class LinkReport:
    seen: int = 0
    linked: int = 0
    new_refs: int = 0
    pruned: int = 0
    skipped: int = 0
    complete: bool = False
    #: Files whose rows were KEPT although this pass did not find them in the music server's listing (P3-33): a pass that saw less than half of what is linked does not remove anything at once.
    held_back: int = 0
    #: What the rehome of the files the old text fold glued onto the wrong song did in this pass (P2-25 slice 4); `None` when there was nothing to do (an empty worklist).
    rehome: rehome.Report | None = None


def _first(value: object) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) if value not in (None, "") else None


def described(song: dict[str, Any]) -> dict[str, Any] | None:
    """The music server's song as `refs.resolve` wants it, or `None` when it has no usable title and artist."""
    artists = [str(a.get("name")) for a in song.get("artists") or [] if isinstance(a, dict) and a.get("name")]
    if not artists and song.get("artist"):
        artists = [str(song["artist"])]
    title = str(song.get("title") or "").strip()
    if not title or not artists:
        return None
    album_artists = [str(a.get("name")) for a in song.get("albumArtists") or [] if isinstance(a, dict) and a.get("name")]
    seconds = song.get("duration")
    return {
        "title": title,
        "artists": artists,
        "album": song.get("album") or None,
        "albumArtist": (album_artists[0] if album_artists else None) or song.get("albumArtist") or None,
        "trackNo": song.get("track"),
        "discNo": song.get("discNumber"),
        "year": song.get("year"),
        "durationMs": int(seconds * 1000) if isinstance(seconds, (int, float)) and seconds > 0 else None,
        "isrc": _first(song.get("isrc")),
        "mbid": _first(song.get("musicBrainzId")),
    }


def _begin_rehome(db: Database, listing: Listing) -> rehome.Rehome | None:
    """The judge of the files the old text fold glued onto the wrong song, or `None` (an empty worklist, which is every install after the repair, or a failure to start:
    the library link itself must never stop for it)."""
    try:
        return rehome.begin(db, described, listing)
    except textnorm.UnicodeVersionError:
        raise  # a refusal, not a failure: this Python must not write a key at all
    except Exception:  # noqa: BLE001 - the link goes on without the rehome; the worklist is untouched and the next pass tries again
        log.exception("the rehome of files glued onto the wrong song could not start; the library link goes on without it")
        return None


def link_library(db: Database, navidrome: Library, *, page: int = PAGE, prune: bool = True) -> LinkReport:
    """One pass over the music server's songs. Safe to run again at any time (nothing is created twice). With [prune] off it only ever adds: no file row
    is removed, whatever the music server answers (the pass after a scan, P3-35: a scan of a disk that is not mounted finishes with no songs).

    **The rehome (P2-25 slice 4, `rehome.py`)** rides on the same pass: while the worklist of the key repair (`ref_recheck`) is not empty, every page only NOTES what the
    music server says of the worklist's files; **nothing is decided or written until the whole listing has been read, linked and pruned** (a pass that stops early, because the
    music server stopped answering or the process died, decides nothing), and then every file is judged against that one state, the files that belong to another song are
    re-pointed and the refs that are done leave the worklist. It only re-points `song_file` rows."""
    report = LinkReport()
    listing = Listing(began=now_ms())
    offset = 0
    rehomer = _begin_rehome(db, listing)
    while True:
        songs = navidrome.songs(offset, page)
        if songs is None:
            log.info("the music server did not answer; the library link will try again later")
            return report  # incomplete: nothing is pruned
        with db.tx() as conn:
            holders = refs.file_holders(conn, [str(song.get("id") or "") for song in songs])
            for song in songs:
                report.seen += 1
                item = described(song)
                song_id = str(song.get("id") or "")
                if song_id:
                    # The music server HAS this file, whatever its tags are: it is "seen" even when nothing can be made of it. The prune below removes the row of a file the
                    # music server no longer LISTS, not the row of one it lists with tags nobody can describe (it used to: the song lost its file and everybody was told to
                    # stream it again, and the file of a worklist song vanished before the rehome could say it was never judged; P2-25 slice 4, review round).
                    listing.add(song_id)
                if item is None or not song_id:
                    report.skipped += 1
                    continue
                owner = holders.get(song_id)
                if owner is not None:
                    # The file is already some ref's: that is the ref, whatever the tags say (they are often poorer than the description the keeper
                    # saved the file for). `attach_file` finds the row by the id and refreshes it; the row keeps its own path and source.
                    ref_id = str(owner["ref"])
                else:
                    try:
                        known = refs.find(conn, refs.parse_item(item)) is not None
                        ref_id = str(refs.resolve(conn, item)["id"])
                    except ApiError:
                        report.skipped += 1
                        continue
                    if not known:
                        report.new_refs += 1
                suffix = str(song.get("suffix") or "").lower()
                refs.attach_file(
                    conn,
                    ref_id,
                    navidrome_song_id=song_id,
                    path=str(song.get("path") or "") or None,
                    codec=_CODEC.get(suffix, suffix or None),
                    bitrate_kbps=song.get("bitRate") if isinstance(song.get("bitRate"), int) else None,
                    source="library",
                    meta=file_meta(song),
                )
                report.linked += 1
        if rehomer is not None:
            rehomer.page(songs)  # notes, decides nothing: see `rehome.py`
        if len(songs) < page:
            break
        offset += len(songs)
    report.complete = True
    listing.complete = True
    report.pruned, report.held_back = _prune(db, listing) if prune else (0, 0)
    if report.held_back:
        log.warning(
            "the music server listed %d of the files this server has linked and not the other %d: nothing was removed because that looks like a music folder that is not there (a disk or share "
            "that is not mounted, a restart in the middle of a scan); a file that stays absent for a day while the rest is listed is removed",
            len(listing.seen),
            report.held_back,
        )
    if rehomer is not None:
        # After the prune: a file the listing did not have is gone by now (or, in a pass the prune did not trust, held back: not alive either, which is what the rehome counts by), so its ref is
        # not waited for.
        try:
            report.rehome = rehomer.finish()
        except Exception:  # noqa: BLE001 - the scan did its work and committed it; the worklist is kept and the next pass tries again
            log.exception(
                "the rehome of files glued onto the wrong song could not finish its pass; the library link itself is done and the worklist is kept"
            )
    else:
        _rehome_idle(
            db, listing
        )  # no worklist to rehome: what the last pass left owing (the merge repair, the record of a copy nobody will use again) is paid now
    # And the songs that share a file the music server still LISTS are merged now (N-47), in every complete pass, worklist or not: a pair of a ref that is on the key repair's worklist is
    # held (`recheck_pending`) and the rehome pays its own merge debt after it releases a ref, but a worklist that never empties must not stop every other pair from ever merging.
    _merge_repair(db, listing)
    return report


def _merge_repair(db: Database, listing: Listing) -> None:
    """The songs that share a file the music server STILL LISTS are one song shown twice: merged at the end of every COMPLETE pass, judged by this pass's own listing (N-47, audit B-138: a
    merge cannot be undone, so a row the music server no longer lists is no evidence). **It looks first and runs the repair only when a pair can be merged**: the repair logs every held pair at
    INFO each time it runs, which was once per start and would be every hour here. Never stops the link; the repair itself never raises."""
    try:
        with db.read() as conn:
            mergeable, held = refmerge.look(conn, listing)
        if mergeable:
            refmerge.repair(db, listing)
        else:
            refmerge.say_held_if_changed(db, held)
    except Exception:  # noqa: BLE001 - the link is done and committed; the repair is tried again at the end of the next pass
        log.exception(
            "the merge of songs that share a listed file raised; the library link is done and the next pass tries again"
        )


def _rehome_idle(db: Database, listing: Listing) -> None:
    """The end of a pass with no worklist (`rehome.idle`): never stops the link."""
    try:
        rehome.idle(db, listing)
    except Exception:  # noqa: BLE001 - the link goes on; what is owed stays owed and the next pass tries again
        log.exception(
            "what the rehome owes after its last pass could not be paid; the library link goes on and the next pass tries again"
        )


#: A pass that finds at least this share of the linked files in the music server's listing is trusted: what it does not find is removed at once (a Host who deleted some music).
PLAUSIBLE_SHARE = 0.5
#: What a pass that saw LESS did not find is removed only after it has been absent this long (the first miss is written down in `song_file.missing_since`). A day, not an hour: keeping the row of a
#: file that is really gone costs nothing (a kept song whose file is gone streams from YouTube again, CF-31), and removing the rows of a library that was only not mounted for a night costs every
#: phone its downloads and the keeper's own rows their `youtube` source.
CONFIRM_AFTER_MS = 24 * 3600 * 1000


def _prune(db: Database, listing: Listing) -> tuple[int, int]:
    """Files the music server no longer LISTS: their rows go; the refs stay, so nothing a person has changes. Everybody who had the song is told that it now has to be
    streamed again. A file attached after the pass began (the keeper, mid-scan) is left alone. **A file the music server lists is never "gone", whatever its tags are**
    (`listing` holds every listed id, also the ones `described` cannot make anything of): its row stays, and so does the worklist ref that holds it (P2-25 slice 4). Whether a row is ALIVE
    is what `Listing.alive` says, the same test the rehome counts files by; **a row the pass held back (below) is not alive and stays**: the rehome counts a person's last file by `alive`,
    not by the rows present, so it never takes a held-back row for a file.

    **An empty or partial answer never wipes the link (P3-33, audit B-40).** A pass that finds at least [PLAUSIBLE_SHARE] of the linked files is trusted. A pass that finds LESS removes nothing
    now: it writes down when it first missed each file (`missing_since`) and removes a file only once it has been absent for [CONFIRM_AFTER_MS] while the music server lists something; a pass
    that finds NOTHING while files are linked never removes anything. A file that is listed again forgets that it was missed. Returns (removed, held back)."""
    removed = 0
    held = 0
    now = now_ms()
    with db.tx() as conn:
        judged = conn.execute(
            "SELECT id, ref, navidrome_song_id, added_at, missing_since FROM song_file WHERE navidrome_song_id IS NOT NULL AND added_at < ?",
            (listing.began,),
        ).fetchall()
        absent = [row for row in judged if not listing.alive(row["navidrome_song_id"], row["added_at"])]
        # What the music server LISTED, not how many of the old rows it listed: a Host who reorganised the library gets new ids for every file, and a pass that lists a full library of new ids is
        # trusted although none of the old rows is in it. The same listing is trusted or not whatever the pass attached itself (a count of old rows only would change from one pass to the next).
        listed = len(listing.seen)
        back = [
            row["id"]
            for row in judged
            if row["missing_since"] is not None and listing.alive(row["navidrome_song_id"], row["added_at"])
        ]
        for start in range(0, len(back), 500):
            chunk = back[start : start + 500]
            conn.execute(f"UPDATE song_file SET missing_since = NULL WHERE id IN ({','.join('?' for _ in chunk)})", chunk)  # noqa: S608 - only placeholders are formatted in
        trusted = listed > 0 and listed >= len(judged) * PLAUSIBLE_SHARE
        for row in absent:
            confirmed = row["missing_since"] is not None and now - row["missing_since"] >= CONFIRM_AFTER_MS and listed > 0
            if not (trusted or confirmed):
                if row["missing_since"] is None:
                    conn.execute("UPDATE song_file SET missing_since = ? WHERE id = ?", (now, row["id"]))
                held += 1
                continue
            conn.execute("DELETE FROM song_file WHERE id = ?", (row["id"],))
            # A song keeps exactly ONE preferred file: the one it has, or the newest remaining copy when the preferred one was the file that went (`refs.ensure_one_preferred`,
            # the one definition: the statement this replaces gave the newest copy the flag WITHOUT taking it from the one that had it, so a song with three files that lost
            # a copy that was not the preferred one had two).
            refs.ensure_one_preferred(conn, row["ref"])
            refs.touch_file(conn, row["ref"])
            library.touch_ref_holders(conn, row["ref"])
            removed += 1
    return removed, held


class LibraryLinker:
    """Runs [link_library] soon after the server starts, every [every_s] (the tick), and, when it is given the music server's scan status, soon after
    each scan of the music server that changed something (P3-35). [poke] asks for a pass at once (a person added music).

    The tick is the whole errand: [before] (the finders, the purges), then the pass, which also removes the rows of files the music server no longer
    has. A pass because of a scan is the link alone and **only adds**: the errands ask the catalogue from the Host's address and themselves start scans,
    so run after every scan they would make a loop, and a scan that finished with no songs (a disk not mounted for a minute, B-40) must not be able to
    remove every file row within a minute of the disk going away: removals keep the hourly timing they had. When to run is decided by [LinkPlan]
    (`link_plan.py`), which has no thread and no clock; this class only asks it and acts."""

    def __init__(
        self,
        db: Database,
        navidrome: Library,
        *,
        scan_status: Callable[[], dict[str, Any] | None] | None = None,
        first_after_s: float = 20.0,
        every_s: float = 3600.0,
        watch_s: float = 30.0,
        busy_s: float = 5.0,
        min_gap_s: float = 60.0,
        before: Callable[[], object] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = db
        self._navidrome = navidrome
        self._before = before
        self._scan_status = scan_status
        self._clock = clock
        self._plan = LinkPlan(first_after_s=first_after_s, every_s=every_s, watch_s=watch_s, busy_s=busy_s, min_gap_s=min_gap_s)
        self._stop = threading.Event()
        self._soon = threading.Event()
        self._thread: threading.Thread | None = None
        self.last: LinkReport | None = None

    @property
    def watching(self) -> bool:
        """Whether the link follows the music server's scans (it was given the scan status) and not only the clock."""
        return self._scan_status is not None

    def run_once(self) -> LinkReport:
        """The tick: the errands, then the pass."""
        if self._before is not None:
            try:
                self._before()
            except Exception:  # noqa: BLE001 - a side errand must not stop the link; it is tried again next time
                log.exception("the errand before the library link failed")
        return self.link_now("every hour", prune=True)

    def link_now(self, why: str = "asked for", *, prune: bool = False) -> LinkReport:
        """The pass alone; it adds, and removes only when asked to ([prune]: the tick)."""
        began = time.monotonic()
        self.last = link_library(self._db, self._navidrome, prune=prune)
        if self.last.linked or self.last.pruned:
            log.info(
                "library linked: %d songs seen, %d new refs, %d files pruned (%s, %.1f s)",
                self.last.seen,
                self.last.new_refs,
                self.last.pruned,
                why,
                time.monotonic() - began,
            )
        return self.last

    def poke(self) -> None:
        self._plan.poke()
        self._soon.set()

    def start(self) -> None:
        self._stop.clear()
        log.info(
            "the library link runs every hour%s",
            " and after each scan of the music server that changed something" if self.watching else "",
        )
        self._thread = threading.Thread(target=self._loop, name="library-link", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._soon.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _status(self) -> dict[str, Any] | None:
        """What the music server's scanner says now; `None` when it was not asked to be watched or could not say."""
        if self._scan_status is None:
            return None
        try:
            return self._scan_status()
        except Exception:  # noqa: BLE001 - a scan status that fails is "cannot say": the tick still links
            log.info("the music server's scan status could not be read; the library link goes by the clock")
            return None

    def _loop(self) -> None:
        self._plan.begin(self._clock())
        while not self._stop.is_set():
            step = self._plan.next(self._clock(), self._status())
            if step.run is None:
                self._soon.wait(timeout=step.wait_s)
                self._soon.clear()
                continue
            began = self._clock()
            try:
                report = self.run_once() if step.run == "tick" else self.link_now(_WHY[step.run])
            except Exception:  # noqa: BLE001 - the loop must survive a hiccup; it is logged and tried again
                log.exception("the library link failed")
                self._plan.failed(step, at=self._clock())
                continue
            self._plan.finished(step, started=began, ended=self._clock(), complete=report.complete)
