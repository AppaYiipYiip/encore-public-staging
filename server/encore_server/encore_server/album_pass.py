"""Which album is a song on, ASKED OF THE CATALOGUE: the album pass of N-34 (slice 2). One more errand of the hourly library link, run BEFORE the cover finder, so the one
search that finds the album also gives the picture and the cover finder is left with fewer songs (`docs/tasks/P2-songs-as-references.md`, section N-34, parts 1 to 3).

It asks about the songs the library holds whose album is EMPTY or the music server's placeholder (`[Unknown Album]`), through the merged matcher (`album_finder.decide`:
the search, the albums the same-recording hits are on, then the six steps) and writes what the catalogue answered:

* **`matched`**: the song's album and the facts of the release (`refs.release_facts_to_fill`: fill only, never rewrite). **Only a ref whose album is still empty or the
  placeholder, and that has no catalogue id yet, is written** (the row is read again inside the write transaction: somebody may have given it an album while the catalogue
  was being asked). The phones are told (`library.touch_ref_holders`, `refs.touch_file`).
* **`none`** (the catalogue answered and nothing can be justified: no recording passes, a single before its album, a compilation by its title, a name the catalogue spells in
  Latin letters only) and **`held`** (another ref already holds the id, or is this song on this release): nothing is filled, the reason is remembered, one INFO line names a
  held pair (ids only). Asked again after 7 days and whenever `album_finder.IDENTITY_REVISION` rises.
* **Never remembered** ("could not ask": the catalogue down or resting, an album answered without its songs, a name with nothing to compare, no length): nothing is stored for
  the song and a catalogue that cannot be asked STOPS the pass (audit B-124), as the cover finder does.
* **The placeholder literal becomes NULL for every song the pass examines**, whatever the answer, in the same transaction, and the phones are told: the 595 literals on the
  owner's server were written by the library scan before the N-11 guard. (A song the pass does not examine keeps what it has: a channel's or nobody's name, a song that has a
  catalogue id already, a song nobody has. Not done, and said.)

**The pass writes no file** and moves none: the album folder, the tags and the folder picture are slices 3 and 5. A song's line on the phone names the album at once; its artist
page keeps showing the music server's own albums until the files are filed under them.

The songs are asked ONE AT A TIME (the album answers serially: a long deadline parks one of the pool's workers the routes share), at the gate's own pace (background turns). A
pass asks at most `per_pass` songs and runs at most `budget_s` seconds, and goes on at the next one.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import album_finder, deezer, library, refs
from .album_finder import Song, Verdict
from .artist_basis import performer_clause
from .catalogue import Catalogue, release_key
from .db import Database
from .ids import now_ms
from .keeper.placement import inside
from .keeper.tagging import file_length_ms

log = logging.getLogger("encore_server.album_pass")

#: How long a `none` or a `held` song is left alone (the cover finder's own window).
RETRY_AFTER_MS = 7 * 24 * 3600 * 1000
#: How many songs one pass asks about, and for how long it may run: the errand runs in the library link's thread, before its scan.
PER_PASS = 200
BUDGET_S = 300.0
#: What a background pass waits for one search (its turn at the gate) and for one album and its songs: a pass's patience, not a person's.
SEARCH_WAIT_S = 30.0
ALBUM_DEADLINE_S = 30.0

Search = Callable[[str, str], list[dict[str, Any]]]
AlbumAsk = Callable[[str], dict[str, Any]]

_IDENTITY_COLUMNS = frozenset({"identity_tried_at", "identity_rev", "identity_outcome", "identity_reason"})


def length_of(music_dir: Path | None, kept: str | None, listed_ms: object) -> int | None:
    """A song's length for the comparison with the catalogue's: the kept FILE's own when the music folder is known and the file can be read (the import's listing is 1 to 12 s
    off: N-11; a path that leaves the folder is never read), else the ref's own `duration_ms`, else `None`. ONE rule for the album pass and the cover finder."""
    if music_dir is not None and kept:
        path = music_dir / kept
        if inside(music_dir, path):
            from_file = file_length_ms(path)
            if from_file:
                return from_file
    return int(listed_ms) if isinstance(listed_ms, int) and listed_ms > 0 else None


def search_the_catalogue(artist: str, title: str) -> list[dict[str, Any]]:
    """The one search of the pass: the installed catalogue, as a background turn. (A module function, so the tests of the app put their own in: none of them may ask the real
    catalogue.)"""
    return deezer.search_tracks(artist, title, wait_s=SEARCH_WAIT_S)


@dataclass
class AlbumReport:
    #: Songs the catalogue was asked about and answered (a `none` or a `held` counts: they are answers).
    asked: int = 0
    matched: int = 0
    none: int = 0
    held: int = 0
    #: Songs that could not be asked about at all (a name with nothing to compare, no length): examined, never remembered, no request made.
    refused: int = 0
    #: Songs that were left alone: on the P2-25 worklist, or changed while the catalogue was being asked.
    skipped: int = 0
    #: How many songs got each reason, the remembered answers only (`matched`, `no_same_recording`, `latin_spelling_only`, `single_before_album`, ...).
    reasons: dict[str, int] = field(default_factory=dict)
    #: `False` when the pass ended before the last song (the limit, the time, a catalogue that could not be asked).
    complete: bool = True
    stopped: str | None = None


def wanting(conn: sqlite3.Connection, *, now: int, report: AlbumReport | None = None) -> list[sqlite3.Row]:
    """THE selection of the songs the catalogue is asked about, the ONE function the album pass and its dry run (`album_dryrun.entries`) both call, so that reading the dry run
    predicts what the pass will ask and stamp (review of PR 125; a test runs both over one database and compares them). The songs whose album is NULL or the placeholder, with no
    catalogue id, whose artist is a performer or unknown (`artist_basis.performer_clause`: never a channel's name or nobody's, N-26), that somebody has (a like, a playlist entry)
    or the server keeps, and that were never asked, or were answered `none` or `held` by an older rule or more than 7 days before [now]. Songs with a kept file first, then the
    order they were made in. A song that is on the P2-25 worklist is left out and counted in [report]: its file, and so its length and its name, may belong to another song until
    the rehome has judged it, and a stamp is permanent. Reads only."""
    rows = conn.execute(
        "SELECT r.id, r.title, r.artists, r.album, r.duration_ms, r.isrc,"
        " (SELECT f.path FROM song_file f WHERE f.ref = r.id AND f.source = 'youtube' AND f.path IS NOT NULL"
        "  ORDER BY f.preferred DESC, f.added_at LIMIT 1) AS kept"
        " FROM song_ref r WHERE r.deezer_id IS NULL"
        " AND (r.album IS NULL OR TRIM(r.album) = '' OR LOWER(r.album) LIKE '%unknown album%')"
        f" AND {performer_clause('r.artist_basis')}"
        " AND (r.identity_outcome IS NULL OR (r.identity_outcome IN ('none', 'held')"
        "  AND (r.identity_rev IS NULL OR r.identity_rev < ? OR r.identity_tried_at IS NULL OR r.identity_tried_at <= ?)))"
        " AND (EXISTS (SELECT 1 FROM song_file f WHERE f.ref = r.id)"
        "  OR EXISTS (SELECT 1 FROM library_item i WHERE i.kind = 'like' AND i.target = r.id)"
        "  OR EXISTS (SELECT 1 FROM playlist_entry e WHERE e.ref = r.id AND e.deleted_at IS NULL))"
        " ORDER BY (kept IS NULL), r.created_at, r.id",
        (album_finder.IDENTITY_REVISION, now - RETRY_AFTER_MS),
    ).fetchall()
    wanted: list[sqlite3.Row] = []
    for row in rows:
        if not refs.is_placeholder_album(row["album"]):
            continue  # the SQL prefilter is a superset of "no album or the placeholder"
        # STOP-GAP(P2-25 one-shot-repair; remove after 0.1.0): the worklist is the one-time repair of other alphabets (N-36 removes `refs.recheck_pending` and BOTH calls to it in this file).
        if refs.recheck_pending(conn, row["id"]):
            if report is not None:
                report.skipped += 1
            continue
        wanted.append(row)
    return wanted


class _DbHoldings:
    """What the OTHER refs hold (step 5), read from the database one short question at a time: a pass that waits on the network must not hold a read open while it does."""

    def __init__(self, db: Database, ref_id: str) -> None:
        self._db, self._ref = db, ref_id

    def deezer_id_held(self, deezer_id: str) -> bool:
        with self._db.read() as conn:
            return album_finder.RefHoldings(conn, self._ref).deezer_id_held(deezer_id)

    def isrc_held(self, isrc: str) -> bool:
        with self._db.read() as conn:
            return album_finder.RefHoldings(conn, self._ref).isrc_held(isrc)

    def twin_held(self, norm_key: str, release: str) -> bool:
        with self._db.read() as conn:
            return album_finder.RefHoldings(conn, self._ref).twin_held(norm_key, release)


class AlbumFinder:
    def __init__(
        self,
        db: Database,
        *,
        search: Search,
        album: AlbumAsk,
        resting: Callable[[], str | None] = lambda: None,
        per_pass: int = PER_PASS,
        budget_s: float = BUDGET_S,
        music_dir: Path | None = None,
        now: Callable[[], int] = now_ms,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = db
        self._search, self._album, self._resting = search, album, resting
        self._per_pass, self._budget_s = per_pass, budget_s
        self._music = music_dir
        self._now, self._clock = now, clock

    @classmethod
    def on(cls, db: Database, catalogue: Catalogue, *, music_dir: Path | None = None, **options: Any) -> AlbumFinder:
        """The pass as the server runs it: the one search of the installed gate and the catalogue's album answers, both as background turns."""

        def album(ident: str) -> dict[str, Any]:
            return catalogue.album(ident, priority="background", deadline_s=ALBUM_DEADLINE_S)

        def resting() -> str | None:
            state = catalogue.state()
            if state.get("state") == "resting":
                return f"the catalogue asked this server to rest ({state.get('resumesInSec')} s)"
            return None

        return cls(
            db,
            search=lambda artist, title: search_the_catalogue(artist, title),
            album=album,
            resting=resting,
            music_dir=music_dir,
            **options,
        )

    # ------------------------------------------------------------------------------------------------------------ the pass

    def run_once(self) -> AlbumReport:
        report = AlbumReport()
        with self._db.read() as conn:
            rows = wanting(conn, now=self._now(), report=report)
        started = self._clock()
        for row in rows:
            song = Song(
                refs.lead_artist(row["artists"]),
                row["title"],
                length_of(self._music, row["kept"], row["duration_ms"]),
                row["isrc"],
            )
            if album_finder.refusal(song) is not None:
                # No request, nothing remembered ("not asked"); the song was examined, so its placeholder literal is forgotten.
                report.refused += 1
                self._store(row["id"], None, report)
                continue
            if report.asked >= self._per_pass or self._clock() - started >= self._budget_s:
                report.complete = False
                break
            if (why := self._resting()) is not None:
                report.stopped, report.complete = why, False
                break
            verdict = album_finder.decide(song, self._search, self._album, _DbHoldings(self._db, row["id"]))
            if verdict.outcome == "unavailable":
                # Not "the catalogue knows none": nothing is stored for this song or the rest, and the next pass asks again (audit B-124).
                report.stopped, report.complete = f"the catalogue could not be asked ({verdict.reason})", False
                log.info("the catalogue could not be asked (%s); the pass stops", verdict.reason)
                break
            report.asked += 1
            self._store(row["id"], verdict, report)
        if report.asked:
            log.info(
                "album pass: %d songs asked, %d matched, %d none, %d held; %d not asked%s",
                report.asked,
                report.matched,
                report.none,
                report.held,
                report.refused + report.skipped,
                "" if report.complete else f" (stopped early: {report.stopped or 'limit'})",
            )
        return report

    # ------------------------------------------------------------------------------------------------------------ what is written

    def _store(self, ref_id: str, verdict: Verdict | None, report: AlbumReport) -> None:
        """One transaction per song: the facts (or only the placeholder forgotten), the remembered answer, and the phones told. [verdict] is `None` for a song that was only
        examined (no request, nothing remembered)."""
        with self._db.tx() as conn:
            row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref_id,)).fetchone()
            # Re-read, inside the write: only a ref that is STILL without an album (or with the placeholder) and without a catalogue id, and not on the worklist, is written.
            if (
                row is None
                or row["deezer_id"] is not None
                or not refs.is_placeholder_album(row["album"])
                or refs.recheck_pending(conn, ref_id)  # the second of the two calls N-36 removes (see `_wanting`)
            ):
                report.skipped += 1
                return
            outcome, reason = (verdict.outcome, verdict.reason) if verdict is not None and verdict.remember else (None, None)
            updates: dict[str, Any] = {}
            if outcome == "matched" and verdict is not None and verdict.match is not None:
                updates = refs.release_facts_to_fill(conn, row, verdict.match)
                # The second layer of step 5: an id that another song took since the matcher read the database is a pair, not a stamp.
                if "album" not in updates:
                    outcome, reason, updates = "none", "nothing_to_fill", refs.forget_placeholder_album(row)
                elif (
                    row["isrc"]
                    and verdict.match.isrc
                    and album_finder._isrc(row["isrc"]) != album_finder._isrc(verdict.match.isrc)
                ):
                    # The row may have gained an ISRC since it was read (a phone described the song, a scan read its tags): another recording's ISRC is counter-evidence.
                    outcome, reason, updates = "none", "isrc_differs", refs.forget_placeholder_album(row)
                elif verdict.match.deezer_id and "deezer_id" not in updates:
                    outcome, reason, updates = "held", "deezer_id_held", refs.forget_placeholder_album(row)
                elif verdict.match.isrc and row["isrc"] is None and "isrc" not in updates:
                    outcome, reason, updates = "held", "isrc_held", refs.forget_placeholder_album(row)
            else:
                updates = refs.forget_placeholder_album(row)
            if outcome == "held":
                self._log_pair(conn, ref_id, row, verdict, reason or "")
            if outcome is not None:
                updates |= {
                    "identity_tried_at": self._now(),
                    "identity_rev": album_finder.IDENTITY_REVISION,
                    "identity_outcome": outcome,
                    "identity_reason": reason,
                }
            if updates:
                assignments = ", ".join(f"{column} = ?" for column in updates)
                conn.execute(f"UPDATE song_ref SET {assignments} WHERE id = ?", (*updates.values(), ref_id))  # noqa: S608 - fixed column names
                if any(column not in _IDENTITY_COLUMNS for column in updates):
                    library.touch_ref_holders(conn, ref_id)
                    if conn.execute("SELECT 1 FROM song_file WHERE ref = ?", (ref_id,)).fetchone() is not None:
                        refs.touch_file(conn, ref_id)
        if outcome == "matched":
            report.matched += 1
        elif outcome == "held":
            report.held += 1
        elif outcome == "none":
            report.none += 1
        if outcome is not None and reason:
            counted = Counter(report.reasons)
            counted[reason] += 1
            report.reasons = dict(counted)

    def _log_pair(self, conn: sqlite3.Connection, ref_id: str, row: sqlite3.Row, verdict: Verdict | None, reason: str) -> None:
        """One INFO line for a held pair, like `refmerge`'s: the two refs and the catalogue's id, never a title or an artist."""
        match = verdict.match if verdict is not None else None
        other: sqlite3.Row | None = None
        if match is not None and reason == "deezer_id_held":
            other = conn.execute("SELECT id FROM song_ref WHERE deezer_id = ? AND id != ?", (match.deezer_id, ref_id)).fetchone()
        elif match is not None and reason == "isrc_held" and match.isrc:
            other = conn.execute("SELECT id FROM song_ref WHERE isrc = ? AND id != ?", (match.isrc, ref_id)).fetchone()
        elif match is not None and reason == "twin_held":
            wanted = release_key(match.album)
            for twin in conn.execute(
                "SELECT id, album FROM song_ref WHERE norm_key = ? AND id != ? AND album IS NOT NULL", (row["norm_key"], ref_id)
            ):
                if not refs.is_placeholder_album(twin["album"]) and release_key(twin["album"]) == wanted:
                    other = twin
                    break
        log.info(
            "held pair: song %s and song %s are one recording of the catalogue (id %s, album %s): %s; nothing was written",
            ref_id,
            other["id"] if other is not None else "?",
            match.deezer_id if match is not None else "?",
            match.album_id if match is not None else "?",
            reason,
        )
