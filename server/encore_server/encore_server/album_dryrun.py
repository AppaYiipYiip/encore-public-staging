"""N-34 slice 1: the DRY RUN of the album matcher. It writes nothing, anywhere: it reads a COPY of the database, asks a catalogue source, runs
`album_finder.decide` on every song and prints a report. The lead reads the report before an image that holds the album pass (slice 2) runs on a server.

**What the report shares with the pass, and what it does not.** It DECIDES with the very function the pass asks with (`album_finder.decide`: one verdict per song, the same rule). It SELECTS the same songs too: [entries] is `album_pass.wanting`, the ONE function (the worklist, the likes and playlist entries, the order, the retry rule of 7 days and of `IDENTITY_REVISION`; a review fix of PR 125, pinned by `tests/test_album_selection.py`); the dry run adds only its limit, `--kept-only` and the file lengths of `--music-root`.

    # Replay recorded answers (no request is made; a song whose answers were not recorded is "not asked", never "the catalogue knows none"):
    python -m encore_server.album_dryrun --db copy.db --answers server/encore_server/tests/fixtures/deezer

    # Ask the REAL catalogue, from this machine's address (the Host's decision, never a test's): paced by the server's own gate (about 4 requests a
    # second, background turns), at most N requests, every raw answer saved to --answers so that a second run asks nothing and can be replayed.
    python -m encore_server.album_dryrun --db copy.db --answers answers --live --max-requests 2000 --music-root /path/to/music

**What the report is for.** (1) The histogram of (the song's length minus the catalogue's length) over the songs that have a hit of the same artist,
title and version: the number `album_finder.TOLERANCE_MS` was read from (measured on 24 Nov 2026 over 672 songs and their kept files, and KEPT at 3 s: see the constant). (2) Every hit rejected ONLY by the tolerance.
(3) Every release type seen, every song with more than one candidate release, every held pair, every song that cannot be asked (a name with no letter
or digit in it, no length). (4) Every match, so that the reader can look for a wrong album.

**The names of the saved answers** are `fixture_names.fixture_name`'s, the one function the recorder and the tests use too: a search is named by a hash of
its FULL query, so a library in any alphabet is safe (two Arabic songs are two files; a replay never answers a song with another song's answer).

**The length of the song.** The matcher compares the length of the KEPT FILE (the import's listing is 1 to 12 s off: N-11). A copy of the database holds no
file, so without `--music-root` the length is `song_ref.duration_ms`, the listing's, and the report says so on every histogram: a histogram made from
the listing's lengths does NOT measure the file against the catalogue, and it is not the one the tolerance is frozen from. With `--music-root` (the folder
the music server reads; a kept file's path is relative to it) the file's own length is read with `mutagen`.

Read-only by construction: the database is opened `mode=ro`, nothing is written to it, and the only thing written anywhere is `--answers` (live) and
`--out`. Slice 1 of N-34 changes no stored data.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from . import album_finder, album_pass, deezer, refs
from .album_finder import RefHoldings, Song, Verdict
from .album_pass import ALBUM_DEADLINE_S, SEARCH_WAIT_S
from .catalogue import Cache, Catalogue
from .deezer import DeezerClient, Gate
from .fixture_names import fixture_name
from .ids import now_ms

#: Fields the recorder (`tools/record_catalogue_fixtures.py`) takes out of an answer before it is saved: signed addresses and share links.
_DROP = frozenset({"preview", "share", "md5_image"})
#: The width of a bar of the histogram.
_BAR = 40


# ------------------------------------------------------------------------------------------------------------------ the catalogue source


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items() if key not in _DROP}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


class AnswerTransport(httpx.BaseTransport):
    """Where the catalogue client's requests go. A request whose answer is in [folder] is answered from it, for nothing. Otherwise: with a [live]
    transport (`--live`) it is made, counted against [max_requests] and its answer saved in [folder]; without one it is refused with a 400, which the
    client reports as "could not ask" (and which rests nobody), and the name is kept in [not_recorded] so the report says so."""

    def __init__(self, folder: Path | None, *, live: httpx.BaseTransport | None = None, max_requests: int | None = None) -> None:
        self._folder = folder
        self._live = live
        self._cap = max_requests
        self.asked = 0
        self.replayed = 0
        self.not_recorded: list[str] = []
        self.spent = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        name = fixture_name(request.url.path, params)
        if name is not None and self._folder is not None and (self._folder / f"{name}.json").is_file():
            self.replayed += 1
            body = json.loads((self._folder / f"{name}.json").read_text(encoding="utf-8"))["answer"]
            return httpx.Response(200, json=body, request=request)
        if self._live is None or name is None:
            self.not_recorded.append(name or request.url.path)
            return httpx.Response(400, json={"error": {"code": 0, "message": "not recorded"}}, request=request)
        if self._cap is not None and self.asked >= self._cap:
            self.spent = True
            return httpx.Response(
                400, json={"error": {"code": 0, "message": "the request cap of this run is spent"}}, request=request
            )
        self.asked += 1
        response = self._live.handle_request(request)
        response.read()
        if response.status_code == 200 and self._folder is not None:
            answer = response.json()
            if isinstance(answer, dict) and "error" not in answer:
                self._folder.mkdir(parents=True, exist_ok=True)
                saved = {
                    "recorded": datetime.now(UTC).date().isoformat(),
                    "path": request.url.path,
                    "params": params,
                    "answer": _scrub(answer),
                }
                text = json.dumps(saved, ensure_ascii=False, indent=1) + "\n"
                (self._folder / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")
        return response

    def close(self) -> None:
        if self._live is not None:
            self._live.close()


@dataclass
class Source:
    """What the dry run asks: the very calls the album pass of slice 2 will make (`deezer.search_tracks` on the installed gate as a background turn,
    `Catalogue.album` in the background, serially), over an [AnswerTransport]."""

    transport: AnswerTransport
    catalogue: Catalogue

    def search(self, artist: str, title: str) -> list[dict[str, Any]]:
        return deezer.search_tracks(artist, title, wait_s=SEARCH_WAIT_S)

    def album(self, album_id: str) -> dict[str, Any]:
        return self.catalogue.album(album_id, priority="background", deadline_s=ALBUM_DEADLINE_S)

    def stop_reason(self) -> str | None:
        """Why the run must not go on, or `None`: the request cap is spent, or the catalogue has rested this server (a refusal or throttling): every
        later request would be "could not ask" at once, and a report made of those would be a report of the rest, not of the catalogue."""
        if self.transport.spent:
            return "the request cap of this run is spent"
        state = self.catalogue.state()
        if state["state"] == "resting":
            return f"the catalogue asked this server to rest ({state['resumesInSec']} s): run the same command again later, what was asked is saved"
        return None


@contextmanager
def opened(
    folder: Path | None, *, live: bool, max_requests: int | None, network: httpx.BaseTransport | None = None
) -> Iterator[Source]:
    """A [Source] with the client INSTALLED (`deezer.install`: one gate for the whole run, so the requests are paced against each other; a search asked
    with a client of its own would get a gate nobody shares). A replay has no pacing at all, a live run has the server's own."""
    transport = AnswerTransport(folder, live=(network or httpx.HTTPTransport()) if live else None, max_requests=max_requests)
    gate = Gate() if live else Gate(rate=1_000_000, burst=1_000_000, background_gap_s=0.0)
    client = DeezerClient(gate, httpx.Client(transport=transport))
    catalogue = Catalogue(client, Cache(None))
    deezer.install(client)
    try:
        yield Source(transport, catalogue)
    finally:
        deezer.install(None)
        catalogue.close()
        transport.close()


# ------------------------------------------------------------------------------------------------------------------ the songs


@dataclass(frozen=True)
class Entry:
    ref_id: str
    song: Song
    #: Where `song.length_ms` came from: `file` (read from the kept file), `listing` (`song_ref.duration_ms`, the import's), or `none`.
    length_from: str


def entries(
    conn: sqlite3.Connection,
    *,
    kept_only: bool = False,
    limit: int | None = None,
    music_root: Path | None = None,
    now: int | None = None,
) -> list[Entry]:
    """The songs the pass will ask about: **`album_pass.wanting`, the ONE selection** (review of PR 125: reading this report must predict what the pass stamps). On top of it the
    dry run has only its own: [kept_only] leaves out those nobody kept a file of (the pass asks them too), [limit], and the kept file's own length when [music_root] is given.
    [now] is the clock of the retry rule (a `none` of the last 7 days is not asked again)."""
    rows = album_pass.wanting(conn, now=now_ms() if now is None else now)
    out: list[Entry] = []
    for row in rows:
        if kept_only and row["kept"] is None:
            continue
        # THE definition of a song's length, the pass's own (a fractional or negative duration is no length; a kept path that leaves the music folder is never read).
        length, source = album_pass.length_and_source(music_root, row["kept"], row["duration_ms"])
        out.append(Entry(row["id"], Song(refs.lead_artist(row["artists"]), row["title"], length, row["isrc"]), source))
        if limit is not None and len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------------------------------------------------------ the run


@dataclass
class Row:
    entry: Entry
    verdict: Verdict


def run(
    conn: sqlite3.Connection,
    items: Sequence[Entry],
    search: Callable[[str, str], list[dict[str, Any]]],
    album: Callable[[str], dict[str, Any]],
    *,
    tolerance_ms: int = album_finder.TOLERANCE_MS,
    single_window_days: int | None = album_finder.SINGLE_BEFORE_ALBUM_WINDOW_DAYS,
    stop: Callable[[], bool] = lambda: False,
) -> list[Row]:
    """Every song through the matcher, exactly as slice 2's pass will ask: the search, then each album the same-recording hits are on (serially), then
    `choose_release` with the other refs' holdings read from [conn]. A search or an album that could not be asked is `unavailable`, never `none`.
    [stop] is asked after each song (the request cap of a live run)."""
    rows: list[Row] = []
    for item in items:
        rows.append(Row(item, _decide(conn, item, search, album, tolerance_ms, single_window_days)))
        if stop():
            break
    return rows


def _decide(
    conn: sqlite3.Connection,
    item: Entry,
    search: Callable[[str, str], list[dict[str, Any]]],
    album: Callable[[str], dict[str, Any]],
    tolerance_ms: int,
    single_window_days: int | None,
) -> Verdict:
    """Decides with the very function the album pass asks with (`album_finder.decide`). The SELECTION of the songs differs, see the module docstring."""
    return album_finder.decide(
        item.song, search, album, RefHoldings(conn, item.ref_id), tolerance_ms=tolerance_ms, single_window_days=single_window_days
    )


# ------------------------------------------------------------------------------------------------------------------ the report

#: The edges of the histogram in milliseconds (the song's length minus the catalogue's): coarse outside 5 s, one second wide inside.
_EDGES = (-30_000, -10_000, -5_000, -4_000, -3_000, -2_000, -1_000, 0, 1_000, 2_000, 3_000, 4_000, 5_000, 10_000, 30_000)


def _bucket(delta: int) -> int:
    return sum(1 for edge in _EDGES if delta >= edge)


def _bucket_label(index: int) -> str:
    low = "-inf" if index == 0 else f"{_EDGES[index - 1] / 1000:+.0f}"
    high = "+inf" if index == len(_EDGES) else f"{_EDGES[index] / 1000:+.0f}"
    return f"{low:>5} .. {high:<5} s"


def _name(entry: Entry, width: int = 30) -> str:
    return f"{entry.ref_id} {(entry.song.artist + ' - ' + entry.song.title)[:width]}"


@dataclass
class Report:
    rows: list[Row]
    tolerance_ms: int
    requests: dict[str, int] = field(default_factory=dict)
    examples: int = 25
    #: The window of `album_finder.SINGLE_BEFORE_ALBUM_WINDOW_DAYS` this run used (`None`: not frozen).
    single_window_days: int | None = None
    #: Why the run ended before the last song (`Source.stop_reason`), or `None`.
    stopped: str | None = None

    def single_gaps(self) -> list[tuple[Row, int]]:
        """The days between an EARLIER single and the album or EP that carries the same recording, one per such single, over every song that has both among the releases
        its same-recording hits are on (the same recording by artist, title, version and length: not by ISRC, which the report does not see). THIS is what
        `album_finder.SINGLE_BEFORE_ALBUM_WINDOW_DAYS` is frozen from."""
        gaps: list[tuple[Row, int]] = []
        for row in self.rows:
            chosen = next(
                (rel for rel in row.verdict.releases if rel.reason == "chosen" and rel.record_type in ("album", "ep")), None
            )
            if chosen is None:
                continue
            for rel in row.verdict.releases:
                if rel.record_type == "single" and rel.reason in ("outranked", "chosen"):
                    gap = album_finder._gap_days(rel.release_date, chosen.release_date)
                    if gap is not None and gap >= 0:
                        gaps.append((row, gap))
        return gaps

    def best_deltas(self) -> dict[str, list[tuple[Row, int]]]:
        """Per length source, per song: the delta of the hit of the same artist, title and version that is NEAREST in length (the song's own
        recording is the nearest one with that name)."""
        out: dict[str, list[tuple[Row, int]]] = {}
        for row in self.rows:
            deltas = [hit.delta_ms for hit in row.verdict.hits if hit.name_fits and hit.delta_ms is not None]
            if deltas:
                out.setdefault(row.entry.length_from, []).append((row, min(deltas, key=abs)))
        return out

    def render(self) -> str:
        lines: list[str] = []
        say = lines.append
        total = len(self.rows)
        if self.tolerance_ms == album_finder.TOLERANCE_MS:
            say(
                f"TOLERANCE: {self.tolerance_ms} ms (album_finder.TOLERANCE_MS, N-34), MEASURED on 24 Nov 2026 and KEPT: the live dry run over 672 songs and their kept FILES found 404 songs "
                f"with a hit of the same artist, title and version, 161 within 3 s and 243 outside, in a smooth tail with NO cliff (the bins 3 to 4 s, 4 to 5 s and 5 to 10 s held 14, 10 and 29 "
                f"songs), so 3 s stays as the conservative edge. Price: misses only. The histogram below is THIS run's own."
            )
        else:
            say(
                f"TOLERANCE: this run asks with {self.tolerance_ms} ms (--tolerance-ms); the server keeps {album_finder.TOLERANCE_MS} ms (album_finder.TOLERANCE_MS, measured on 24 Nov 2026 and kept)."
            )
        window = (
            f"{self.single_window_days} days"
            if self.single_window_days is not None
            else "NOT FROZEN: every song whose recording came out first as a single and later on an album is `single_before_album`, re-askable"
        )
        say(
            f"STOP-GAP: the single-before-album window is {window} (album_finder.SINGLE_BEFORE_ALBUM_WINDOW_DAYS, N-34, the advisor's ruling "
            f"of 17 Nov 2026). Removal trigger: a dry run over a library that holds enough single/album pairs to show a window (about 30; the lead decides): the live run of 24 Nov 2026 "
            f"over 672 songs found 1 (301 days). The section 'single-before-album gaps' below is what it is frozen from."
        )
        say(f"N-34 album dry run: {total} songs through the matcher, nothing written. {datetime.now(UTC):%Y-%m-%d %H:%M} UTC")
        if self.stopped:
            say(f"STOPPED EARLY: {self.stopped}; the songs after this point were not asked.")
        say(f"requests: {', '.join(f'{k} {v}' for k, v in sorted(self.requests.items())) or 'none'}")
        say("")
        say("== outcomes")
        outcomes = Counter((row.verdict.outcome, row.verdict.reason) for row in self.rows)
        for (outcome, reason), count in sorted(outcomes.items(), key=lambda item: (-item[1], item[0])):
            remembered = "remembered" if outcome in album_finder.REMEMBERED else "never remembered"
            say(f"  {count:5d}  {outcome:11s} {reason:24s} ({remembered})")
        say("")
        say(
            "== songs the catalogue could not place, by cause (re-askable: asked again after 7 days and when the rule gets better)"
        )
        causes = Counter(row.verdict.reason for row in self.rows if row.verdict.outcome == "none")
        meaning = {
            "latin_spelling_only": "a non-Latin song whose only catalogue hits are spelled in Latin letters (counted apart)",
            "single_before_album": "an album carries it and an EARLIER single too: the album wins only inside the window",
            "compilation_title": "the only release's title says it is a compilation (Greatest Hits, Best Of, Collection ...)",
            "no_same_recording": "no hit is this recording (artist, title, version and length)",
            "no_album_on_hit": "the hit names no album",
            "no_eligible_release": "no release of the hits is by the song's artist and an album, EP or single",
            "release_version_mismatch": "the only releases are live, remix or other-version records of a song that is not",
            "isrc_differs": "the names agree and the catalogue's ISRC is another recording's",
        }
        for cause, count in sorted(causes.items(), key=lambda item: (-item[1], item[0])):
            say(f"  {count:5d}  {cause:20s} {meaning.get(cause, '')}")
        if not causes:
            say("  (none)")
        spelled = [row for row in self.rows if row.verdict.reason == "latin_spelling_only"]
        say(f"  non-Latin songs with only Latin-spelled hits: {len(spelled)} of {len(self.rows)}")
        for row in spelled[: min(self.examples, 10)]:
            first = next((hit for hit in row.verdict.hits if hit.reason != "unreadable"), None)
            say(f"    {_name(row.entry)}  catalogue says: {(first.artist + ' - ' + first.title)[:40] if first else '?'}")
        withheld = [row for row in self.rows if row.verdict.withheld is not None]
        say(f"  withheld (what the old rule would have written; NOT written): {len(withheld)}")
        for row in withheld[: min(self.examples, 10)]:
            wanted = row.verdict.withheld
            assert wanted is not None
            say(
                f"    {_name(row.entry)}  {row.verdict.reason}: would be {wanted.album[:30]} ({wanted.record_type}, {wanted.release_date or 'no date'})  {row.verdict.detail[:70]}"
            )
        say("")
        say(
            "== single-before-album gaps: days between the earlier single and the album that carries the same recording (the window is frozen from THIS, over many artists)"
        )
        gaps = self.single_gaps()
        if not gaps:
            say("  (no song had both a single and an album among its same-recording hits)")
        else:
            days = sorted(gap for _, gap in gaps)
            say(
                f"  {len(days)} pairs, {len({row.entry.ref_id for row, _ in gaps})} songs; min {days[0]}, median {days[len(days) // 2]}, max {days[-1]} days"
            )
            edges = (30, 90, 180, 365, 730, 1460, 3650)
            for index in range(len(edges) + 1):
                low = 0 if index == 0 else edges[index - 1]
                high = None if index == len(edges) else edges[index]
                n = sum(1 for gap in days if gap >= low and (high is None or gap < high))
                say(f"    {low:5d} .. {'inf' if high is None else high:>5} days {n:5d} {'#' * min(n, _BAR)}")
        say("")
        say("== where the song's length came from (the tolerance must be frozen from `file`)")
        sources = Counter(row.entry.length_from for row in self.rows)
        for source in ("file", "listing", "none"):
            say(f"  {sources.get(source, 0):5d}  {source}")
        if not sources.get("file"):
            say(
                "  NO row used a file's length: the histograms below are the IMPORT'S LISTING against the catalogue, NOT the file. Run with --music-root."
            )
        say("")
        say(
            "== histogram: the song's length minus the catalogue's (the nearest hit with the same artist, title and version, one per song)"
        )
        say(f"   within the tolerance: -{self.tolerance_ms / 1000:g} .. +{self.tolerance_ms / 1000:g} s")
        deltas = self.best_deltas()
        if not deltas:
            say("  (no song had a hit of the same artist, title and version)")
        for source, found in sorted(deltas.items()):
            say(f"  length from: {source}   ({len(found)} songs)")
            counts = Counter(_bucket(delta) for _, delta in found)
            peak = max(counts.values())
            for index in range(len(_EDGES) + 1):
                n = counts.get(index, 0)
                say(f"    {_bucket_label(index)} {n:5d} {'#' * round(_BAR * n / peak) if n else ''}")
            inside = sum(1 for _, delta in found if abs(delta) <= self.tolerance_ms)
            say(f"    inside the tolerance: {inside} of {len(found)}; outside: {len(found) - inside}")
        say("")
        say("== hits rejected ONLY by the tolerance (same artist, title and version; the length is the one thing that failed)")
        near = [(row, hit) for row in self.rows for hit in row.verdict.hits if hit.reason == "length"]
        if not near:
            say("  (none)")
        for row, hit in sorted(near, key=lambda pair: abs(pair[1].delta_ms or 0))[: self.examples]:
            say(
                f"  {_name(row.entry)}  [{row.entry.length_from}] delta {hit.delta_ms:+d} ms  hit {hit.id}  "
                f"{'matched anyway on another hit' if row.verdict.outcome in ('matched', 'held') else 'NO MATCH'}"
            )
        if len(near) > self.examples:
            say(f"  ... {len(near) - self.examples} more (--examples)")
        say("")
        say("== releases")
        types = Counter((rel.record_type or "(none)", rel.reason) for row in self.rows for rel in row.verdict.releases)
        for (record_type, reason), count in sorted(types.items(), key=lambda item: (-item[1], item[0])):
            say(f"  {count:5d}  type {record_type:12s} {reason}")
        many = [row for row in self.rows if len({rel.key or rel.album_id for rel in row.verdict.releases}) > 1]
        say(f"  songs with more than one candidate release (editions counted as one): {len(many)}")
        for row in many[: self.examples]:
            chosen = next((rel for rel in row.verdict.releases if rel.reason == "chosen"), None)
            say(
                f"    {_name(row.entry)}  {len(row.verdict.releases)} releases, chosen: {(chosen.title or '?')[:30] if chosen else 'none'}"
            )
        say("")
        say("== held pairs (nothing would be written)")
        held = [row for row in self.rows if row.verdict.outcome == "held"]
        for row in held[: self.examples]:
            say(
                f"  {_name(row.entry)}  {row.verdict.reason}  catalogue id {row.verdict.match.deezer_id if row.verdict.match else '?'}"
            )
        if not held:
            say("  (none)")
        say("")
        say("== songs that cannot be asked (never remembered)")
        for outcome in ("unsupported", "no_length", "unavailable"):
            some = [row for row in self.rows if row.verdict.outcome == outcome]
            say(f"  {len(some):5d}  {outcome}")
            for row in some[: min(self.examples, 5)]:
                say(f"           {_name(row.entry)}  ({row.verdict.reason})")
        say("")
        say("== matched (read these for a wrong album)")
        matched = [row for row in self.rows if row.verdict.outcome == "matched" and row.verdict.match is not None]
        for row in matched[: self.examples]:
            match = row.verdict.match
            assert match is not None
            say(
                f"  {_name(row.entry)}  ->  {match.album[:30]} ({match.record_type}, {match.release_date or 'no date'}) track {match.track_no}"
            )
        if len(matched) > self.examples:
            say(f"  ... {len(matched) - self.examples} more (--examples)")
        return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------------------------ the command


def _stdout(text: str) -> None:
    """The report to the console. A library has names in every alphabet and a Windows console is not UTF-8: a character the console cannot show is
    written as its escape (a backslash, `u` and four digits) instead of ending the run after the whole catalogue was asked. (`--out` is always UTF-8.)"""
    encoding = sys.stdout.encoding or "ascii"
    sys.stdout.write(text.encode(encoding, "backslashreplace").decode(encoding))


def main(
    argv: Sequence[str] | None = None, *, out: Callable[[str], object] | None = None, network: httpx.BaseTransport | None = None
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m encore_server.album_dryrun", description="N-34 slice 1: the album matcher's dry run (writes nothing)."
    )
    parser.add_argument("--db", required=True, type=Path, help="a COPY of encore.db (opened read-only)")
    parser.add_argument(
        "--answers", type=Path, help="a folder of recorded answers: replayed; with --live, every new answer is saved there"
    )
    parser.add_argument(
        "--live", action="store_true", help="ask the REAL catalogue from this machine's address (needs --max-requests)"
    )
    parser.add_argument("--max-requests", type=int, help="the most outside requests a --live run may make")
    parser.add_argument("--music-root", type=Path, help="the music server's folder: the kept files' own lengths are read from it")
    parser.add_argument("--limit", type=int, help="only the first N songs")
    parser.add_argument(
        "--kept-only", action="store_true", help="leave out the songs nobody kept a file of (the pass asks them too)"
    )
    parser.add_argument("--tolerance-ms", type=int, default=album_finder.TOLERANCE_MS)
    parser.add_argument(
        "--single-window-days",
        type=int,
        default=album_finder.SINGLE_BEFORE_ALBUM_WINDOW_DAYS,
        help="how many days an album may come after an earlier single and still be the song's album (default: not frozen)",
    )
    parser.add_argument("--examples", type=int, default=25, help="how many examples of each kind to print")
    parser.add_argument("--out", type=Path, help="also write the report to this file")
    args = parser.parse_args(argv)
    if args.live and (args.max_requests is None or args.max_requests < 1):
        parser.error("--live asks the real catalogue: say how many requests at most with --max-requests N")
    if not args.live and args.answers is None:
        parser.error("nothing to ask: give --answers FOLDER to replay recorded answers, or --live to ask the real catalogue")
    if not args.db.is_file():
        parser.error(f"no such database: {args.db}")
    conn = sqlite3.connect(f"{args.db.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        items = entries(conn, kept_only=args.kept_only, limit=args.limit, music_root=args.music_root)
        with opened(args.answers, live=args.live, max_requests=args.max_requests, network=network) as source:
            why: list[str] = []

            def stop() -> bool:
                if reason := source.stop_reason():
                    why.append(reason)
                return bool(why)

            rows = run(
                conn,
                items,
                source.search,
                source.album,
                tolerance_ms=args.tolerance_ms,
                single_window_days=args.single_window_days,
                stop=stop,
            )
            requests = {
                "asked": source.transport.asked,
                "replayed": source.transport.replayed,
                "not recorded": len(source.transport.not_recorded),
            }
            report = Report(
                rows,
                args.tolerance_ms,
                requests,
                args.examples,
                single_window_days=args.single_window_days,
                stopped=why[0] if why and len(rows) < len(items) else None,
            )
        text = report.render()
    finally:
        conn.close()
    (out or _stdout)(text)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
