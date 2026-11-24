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

**The pass writes no file** and moves none: the album folder, the tags and the folder picture of a file are made by the keeper for a song being kept now (slice 3, `Keeper._identified`, which asks the pass's own question below: [KeepAsker]) and by the repair of the files already kept (slice 5). A song's line on the phone names the album at once; its artist
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


def file_or_listing_length(path: Path | None, listed_ms: object) -> tuple[int | None, str]:
    """A song's length for the comparison with the catalogue's, and where it came from (`file`, `listing` or `none`): the FILE's own when [path] is given and can be read (the
    import's listing is 1 to 12 s off a file's own: N-11), else the ref's own `duration_ms` when it is a whole number above zero (a fractional or negative one is no length), else
    `None`. THE one definition of how a length is read, for a file that is kept (`length_and_source`) and for the file a keep has just downloaded (N-34 slice 3: the keeper)."""
    if path is not None:
        from_file = file_length_ms(path)
        if from_file:
            return from_file, "file"
    if isinstance(listed_ms, int) and listed_ms > 0:
        return int(listed_ms), "listing"
    return None, "none"


def length_and_source(music_dir: Path | None, kept: str | None, listed_ms: object) -> tuple[int | None, str]:
    """[file_or_listing_length] for a KEPT file, given by its path relative to the music folder: a path that leaves the folder is never read. THE one definition: the album pass,
    the cover finder and the dry run all read a length through it."""
    path: Path | None = None
    if music_dir is not None and kept:
        candidate = music_dir / kept
        if inside(music_dir, candidate):
            path = candidate
    return file_or_listing_length(path, listed_ms)


def length_of(music_dir: Path | None, kept: str | None, listed_ms: object) -> int | None:
    """[length_and_source] without the source."""
    return length_and_source(music_dir, kept, listed_ms)[0]


def resting_reason(catalogue: Catalogue) -> str | None:
    """Why the catalogue must not be asked now (it asked this server to rest), or `None`: the pass and a new keep both stop at it, as the cover finder does."""
    state = catalogue.state()
    if state.get("state") == "resting":
        return f"the catalogue asked this server to rest ({state.get('resumesInSec')} s)"
    return None


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
    #: Songs whose matching RAISED something unexpected: logged by ref id, left for the next pass, nothing remembered, the pass went on.
    failed: int = 0
    #: How many songs got each reason, the remembered answers only (`matched`, `no_same_recording`, `latin_spelling_only`, `single_before_album`, ...).
    reasons: dict[str, int] = field(default_factory=dict)
    #: `False` when the pass ended before the last song (the limit, the time, a catalogue that could not be asked).
    complete: bool = True
    stopped: str | None = None


def wanting(
    conn: sqlite3.Connection, *, now: int, report: AlbumReport | None = None, ref_id: str | None = None, being_kept: bool = False
) -> list[sqlite3.Row]:
    """THE selection of the songs the catalogue is asked about, the ONE function the album pass, its dry run (`album_dryrun.entries`) and the keeper's new keeps (N-34 slice 3,
    [ref_id]) all call, so that reading the dry run predicts what the pass will ask and stamp (review of PR 125; a test runs both over one database and compares them). The songs
    whose album is NULL or the placeholder, with no catalogue id, whose artist is a performer or unknown (`artist_basis.performer_clause`: never a channel's name or nobody's, N-26),
    that somebody has (a like, a playlist entry) or the server keeps, and that were never asked, or were answered `none` or `held` by an older rule or more than 7 days before [now].
    Songs with a kept file first, then the order they were made in. A song that is on the P2-25 worklist is left out and counted in [report]: its file, and so its length and its
    name, may belong to another song until the rehome has judged it, and a stamp is permanent. Reads only.

    **[ref_id]** asks the same question of ONE song (a song being kept now): every rule above holds, and only the "somebody has it or the server keeps it" clause is dropped, because
    the keep itself is the server keeping it. A song a keep must not file under an album is therefore exactly a song the pass would not stamp (a real album, an id, a channel's
    name, an answer of this rule from the last week). **[being_kept]** (the dry run's new-keeps mode) also takes the songs the server has a `keep` waiting or running for (a song
    played on two days is kept without a like or a playlist entry): the keeper asks those too. Each row also says whether the music server already has a file of the song (`linked`): a song it has none of is the
    one a keep would fetch (the dry run's section on new keeps)."""
    holder = (
        " AND (EXISTS (SELECT 1 FROM song_file f WHERE f.ref = r.id)"
        "  OR EXISTS (SELECT 1 FROM library_item i WHERE i.kind = 'like' AND i.target = r.id)"
        "  OR EXISTS (SELECT 1 FROM playlist_entry e WHERE e.ref = r.id AND e.deleted_at IS NULL)"
        + (
            "  OR EXISTS (SELECT 1 FROM work_item w WHERE w.ref = r.id AND w.kind = 'keep' AND w.state IN ('queued', 'running'))"
            if being_kept
            else ""
        )
        + ")"
        if ref_id is None
        else " AND r.id = ?"
    )
    rows = conn.execute(
        "SELECT r.id, r.title, r.artists, r.album, r.duration_ms, r.isrc,"
        " (SELECT f.path FROM song_file f WHERE f.ref = r.id AND f.source = 'youtube' AND f.path IS NOT NULL"
        "  ORDER BY f.preferred DESC, f.added_at LIMIT 1) AS kept,"
        " EXISTS (SELECT 1 FROM song_file f WHERE f.ref = r.id AND f.navidrome_song_id IS NOT NULL) AS linked"
        " FROM song_ref r WHERE r.deezer_id IS NULL"
        " AND (r.album IS NULL OR TRIM(r.album) = '' OR LOWER(r.album) LIKE '%unknown album%')"
        f" AND {performer_clause('r.artist_basis')}"
        " AND (r.identity_outcome IS NULL OR (r.identity_outcome IN ('none', 'held')"
        "  AND (r.identity_rev IS NULL OR r.identity_rev < ? OR r.identity_tried_at IS NULL OR r.identity_tried_at <= ?)))"
        f"{holder}"
        " ORDER BY (kept IS NULL), r.created_at, r.id",
        (album_finder.IDENTITY_REVISION, now - RETRY_AFTER_MS, *(() if ref_id is None else (ref_id,))),
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

        return cls(
            db,
            search=lambda artist, title: search_the_catalogue(artist, title),
            album=album,
            resting=lambda: resting_reason(catalogue),
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
            try:
                if self._one(row, report, started):
                    break
            except Exception as error:  # noqa: BLE001 - one song must not stop the pass (an id nobody expected, a row nobody described): the songs after it are asked
                # By ref id only (no title, no artist, and not the exception's own text, which may quote them); the traceback is for a person who asks for DEBUG. Nothing is
                # remembered: the write transaction of that song rolled back, and the next pass asks again.
                report.failed += 1
                log.warning(
                    "album pass: matching song %s failed unexpectedly (%s); left for the next pass",
                    row["id"],
                    type(error).__name__,
                )
                log.debug("album pass: the failure of song %s", row["id"], exc_info=True)
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

    def _one(self, row: sqlite3.Row, report: AlbumReport, started: float) -> bool:
        """One song through the pass. `True` when the pass must stop here (the limit, the time, a catalogue that rests or could not be asked)."""
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
            return False
        if report.asked >= self._per_pass or self._clock() - started >= self._budget_s:
            report.complete = False
            return True
        if (why := self._resting()) is not None:
            report.stopped, report.complete = why, False
            return True
        verdict = album_finder.decide(song, self._search, self._album, _DbHoldings(self._db, row["id"]))
        if verdict.outcome == "unavailable":
            # Not "the catalogue knows none": nothing is stored for this song or the rest, and the next pass asks again (audit B-124).
            report.stopped, report.complete = f"the catalogue could not be asked ({verdict.reason})", False
            log.info("the catalogue could not be asked (%s); the pass stops", verdict.reason)
            return True
        report.asked += 1
        self._store(row["id"], verdict, report)
        return False

    def _store(self, ref_id: str, verdict: Verdict | None, report: AlbumReport) -> None:
        """One transaction per song: the facts (or only the placeholder forgotten), the remembered answer, and the phones told ([commit_verdict], which a new keep calls too).
        [verdict] is `None` for a song that was only examined (no request, nothing remembered)."""
        with self._db.tx() as conn:
            done = commit_verdict(conn, ref_id, verdict, now=self._now())
        if done.skipped:
            report.skipped += 1
            return
        if done.outcome == "matched":
            report.matched += 1
        elif done.outcome == "held":
            report.held += 1
        elif done.outcome == "none":
            report.none += 1
        if done.outcome is not None and done.reason:
            counted = Counter(report.reasons)
            counted[done.reason] += 1
            report.reasons = dict(counted)


@dataclass(frozen=True)
class Committed:
    """What [commit_verdict] did for one song."""

    #: The answer that was remembered (`matched`, `none` or `held`), or `None` when nothing was (a song that was only examined).
    outcome: str | None
    reason: str | None
    #: The row no longer qualified when it was read again inside the write (an album, an id, the worklist): nothing was written.
    skipped: bool = False
    #: Whether any column of the song changed, the identity columns included: the caller reads the ref again.
    wrote: bool = False
    #: The picture address this write put on the song (the release's cover), when it did: the one picture a new keep may also use for the folder.
    cover: str | None = None


def commit_verdict(conn: sqlite3.Connection, ref_id: str, verdict: Verdict | None, *, now: int) -> Committed:
    """THE write rule of the matcher, inside the caller's transaction: the album pass calls it for every song it asks about and a NEW KEEP (N-34 slice 3) calls it for the song it
    is keeping, so a keep can never stamp what the pass would refuse. The facts (or only the placeholder forgotten), the remembered answer and the phones told, in the order
    of the second layers below. [verdict] is `None` for a song that was only examined (no request, nothing remembered).

    The row is read again here and only a ref that is STILL without an album (or with the placeholder) and without a catalogue id, and not on the worklist, is written; every
    other song is `skipped`. Every verdict of the matcher is checked once more against what the row and the database hold NOW (a placeholder release, a single, nothing to fill, a
    new ISRC, an id another song took, a twin made meanwhile): the result is `none` or `held`, never a stamp."""
    row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref_id,)).fetchone()
    if (
        row is None
        or row["deezer_id"] is not None
        or not refs.is_placeholder_album(row["album"])
        # STOP-GAP(P2-25 one-shot-repair; remove after 0.1.0): the second of the two `refs.recheck_pending` calls N-36 removes (the first is in `wanting`).
        or refs.recheck_pending(conn, ref_id)
    ):
        return Committed(None, None, skipped=True)
    outcome, reason = (verdict.outcome, verdict.reason) if verdict is not None and verdict.remember else (None, None)
    updates: dict[str, Any] = {}
    if outcome == "matched" and verdict is not None and verdict.match is not None:
        updates = refs.release_facts_to_fill(conn, row, verdict.match)
        # The second layer of step 5: an id that another song took since the matcher read the database is a pair, not a stamp.
        if refs.is_placeholder_album(verdict.match.album):
            # The second layer of `release_placeholder`: no album and no id are written for a release called `Unknown Album`, whatever the verdict said.
            outcome, reason, updates = "none", "release_placeholder", refs.forget_placeholder_album(row)
        elif verdict.match.single:
            # The second layer of `single_only`: slice 2 never stamps a single, whatever the verdict said (a stamp is permanent and a later round asks only none and held).
            outcome, reason, updates = "none", "single_only", refs.forget_placeholder_album(row)
        elif "album" not in updates:
            outcome, reason, updates = "none", "nothing_to_fill", refs.forget_placeholder_album(row)
        elif row["isrc"] and verdict.match.isrc and album_finder._isrc(row["isrc"]) != album_finder._isrc(verdict.match.isrc):
            # The row may have gained an ISRC since it was read (a phone described the song, a scan read its tags): another recording's ISRC is counter-evidence.
            outcome, reason, updates = "none", "isrc_differs", refs.forget_placeholder_album(row)
        elif verdict.match.deezer_id and "deezer_id" not in updates:
            outcome, reason, updates = "held", "deezer_id_held", refs.forget_placeholder_album(row)
        elif verdict.match.isrc and row["isrc"] is None and "isrc" not in updates:
            outcome, reason, updates = "held", "isrc_held", refs.forget_placeholder_album(row)
        elif album_finder.RefHoldings(conn, ref_id).twin_held(
            refs.norm_key(refs.lead_artist(row["artists"]), row["title"]), release_key(verdict.match.album)
        ):
            # The third kind of pair (step 5), asked again as the matcher asked it: another ref of this song that already has this album was made after the matcher looked.
            outcome, reason, updates = "held", "twin_held", refs.forget_placeholder_album(row)
    else:
        updates = refs.forget_placeholder_album(row)
    if outcome == "held":
        log_pair(conn, ref_id, row, verdict, reason or "")
    if outcome is not None:
        updates |= {
            "identity_tried_at": now,
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
    return Committed(outcome, reason, wrote=bool(updates), cover=updates.get("cover_url"))


def log_pair(conn: sqlite3.Connection, ref_id: str, row: sqlite3.Row, verdict: Verdict | None, reason: str) -> None:
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


# ------------------------------------------------------------------------------------------------------------------ a new keep (N-34 slice 3)

#: How long a keep waits for the catalogue: the design's short wait ("one `background` turn with a short wait (10 s; `search_tracks` takes a `wait_s`, the 120 s default would
#: stall a keep behind the repair's pass)"), for ONE call and in all for the whole question (the search and each album's answer share it). A keep that runs out of time is a
#: keep without an album, exactly as before slice 3, and remembers nothing; the pass of slice 2 and the repair of slice 5 place the song later. PRICE, named: while the gate is busy
#: (the hourly pass asks at the same pace) a keep may stay in `Singles` that a quieter moment would have filed under its album; a miss is re-askable, a wrong album is not.
KEEP_CALL_WAIT_S = 10.0
KEEP_BUDGET_S = 10.0


def search_the_catalogue_for_keep(artist: str, title: str, wait_s: float) -> list[dict[str, Any]]:
    """The one search of a new keep: the installed catalogue, as a background turn with a short wait. (A module function, so the tests of the app put their own in.)"""
    return deezer.search_tracks(artist, title, wait_s=wait_s)


@dataclass(frozen=True)
class KeepAnswer:
    """What the album question of a new keep came to. `outcome`: `matched`, `none` or `held` (remembered answers, written by [commit_verdict]); `not_asked` (a name with nothing
    to compare or no length: nothing asked, nothing remembered); `not_wanted` (the song is not one the pass would ask about: it has an album, an id, a channel's name, a recent
    answer ...); `unavailable` (the catalogue could not be asked: nothing remembered); `skipped` (the row changed while the catalogue was asked: nothing written)."""

    outcome: str
    reason: str = ""
    #: Whether any column of the song changed, so the keeper must read the ref again.
    wrote: bool = False
    #: The picture the catalogue's release gave the song in this write.
    cover: str | None = None


class KeepAsker:
    """Which album is the song being kept on? ONE question per new keep, asked through the very selection (`wanting`, for one ref), the very matcher (`album_finder.decide`) and the
    very write rule ([commit_verdict]) of the album pass, with the length of the FILE the keeper has just downloaded. **It never remembers anything for a catalogue that cannot be
    asked**: the keep goes on without an album, exactly as before slice 3, and the pass of slice 2 asks the song later. (The keeper also catches any other exception.)

    The calls are the caller's (`search(artist, title, wait_s)`, `album(id, wait_s)`: a test gives recorded ones; [on] gives the installed catalogue's, as background turns). Each call
    waits at most [call_wait_s], and the whole question [budget_s]: the time left is what a call is given, and a call after the time is spent is "could not ask". A keep is a
    background job, but a person may be waiting for the file: the question never costs a keep more than its budget."""

    def __init__(
        self,
        db: Database,
        *,
        search: Callable[[str, str, float], list[dict[str, Any]]],
        album: Callable[[str, float], dict[str, Any]],
        resting: Callable[[], str | None] = lambda: None,
        call_wait_s: float = KEEP_CALL_WAIT_S,
        budget_s: float = KEEP_BUDGET_S,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], int] = now_ms,
    ) -> None:
        self._db = db
        self._search, self._album, self._resting = search, album, resting
        self._call_wait, self._budget = call_wait_s, budget_s
        self._clock, self._now = clock, now

    @classmethod
    def on(cls, db: Database, catalogue: Catalogue, **options: Any) -> KeepAsker:
        """The question as the server asks it: the installed gate's one search and the catalogue's album answers, both background turns."""

        def search(artist: str, title: str, wait_s: float) -> list[dict[str, Any]]:
            return search_the_catalogue_for_keep(artist, title, wait_s)

        def album(ident: str, wait_s: float) -> dict[str, Any]:
            return catalogue.album(ident, priority="background", deadline_s=wait_s)

        return cls(db, search=search, album=album, resting=lambda: resting_reason(catalogue), **options)

    def __call__(self, ref_id: str, length_ms: int | None) -> KeepAnswer:
        with self._db.read() as conn:
            rows = wanting(conn, now=self._now(), ref_id=ref_id)
        if not rows:
            return KeepAnswer("not_wanted")
        row = rows[0]
        song = Song(refs.lead_artist(row["artists"]), row["title"], length_ms, row["isrc"])
        if album_finder.refusal(song) is not None:
            # No request and nothing remembered; the song was examined, so the placeholder literal is forgotten (the pass does the same) and never reaches the tags.
            with self._db.tx() as conn:
                done = commit_verdict(conn, ref_id, None, now=self._now())
            return KeepAnswer("not_asked", wrote=done.wrote)
        if (why := self._resting()) is not None:
            return KeepAnswer("unavailable", why)
        deadline = self._clock() + self._budget

        def wait() -> float:
            left = deadline - self._clock()
            if left <= 0:
                raise deezer.LookupUnavailable("the time a keep has for the catalogue is spent")
            return min(self._call_wait, left)

        verdict = album_finder.decide(
            song,
            lambda artist, title: self._search(artist, title, wait()),
            lambda ident: self._album(ident, wait()),
            _DbHoldings(self._db, ref_id),
        )
        if verdict.outcome == "unavailable":
            return KeepAnswer("unavailable", verdict.reason)
        with self._db.tx() as conn:
            done = commit_verdict(conn, ref_id, verdict, now=self._now())
        if done.skipped:
            return KeepAnswer("skipped")
        return KeepAnswer(done.outcome or "not_asked", done.reason or "", wrote=done.wrote, cover=done.cover)
