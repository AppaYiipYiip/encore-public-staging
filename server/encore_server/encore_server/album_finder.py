"""Which album is a song on? The pure matcher of N-34 (slice 1). It asks nobody, reads no file and writes nothing: it is given what the catalogue said and
decides. `docs/tasks/P2-songs-as-references.md`, section "N-34", parts 1 and 2 (the table of steps) is the design; the step numbers below are its.

**A wrong album is worse than none.** What this decides becomes a stamp: `refs.find` matches `deezer_id` and `isrc` first, so a stamp on the wrong
recording would put every later description of the studio song on the live upload's ref, with its file. So the matcher says "no" readily; a "no" costs
a song its place in the bucket and nothing else, and a better rule asks it again.

**The three calls** (the caller does the asking, so every outside request has one owner and this module has no network in it):

* [judge_hits]: steps 1 and 2 over the hits of one search, one [HitVerdict] per hit with the REASON it was refused (`artist`, `title_or_version`,
  `length`, ...). The dry-run report reads the same verdicts ("rejected only by the tolerance" is `reason == "length"`), so the rule is written once.
* [wanted_albums]: which albums the caller must ask the catalogue about (`Catalogue.album`: the album and its songs) before it can decide.
* [choose_release]: all six steps. Its answer is an [Outcome]: `matched`, `none` and `held` are FACTS the catalogue's answer proves and are
  remembered; `unsupported`, `no_length` and `unavailable` ("could not ask") are not, and [Verdict.remember] says which (a test pins it, so a pass can
  never store the second kind: the day the fold is fixed those songs are simply asked).

**Slice 2 (the advisor's ruling of 17 Nov 2026, binding) adds one principle: a stamped album is effectively permanent** (`refs.find` matches the ids first and the repair of slice 5 files
the song by its album), so anything the matcher cannot justify on evidence is a RE-ASKABLE `none` with a reason, never `matched`, and [Verdict.withheld] keeps what the old rule would have
written, for the report only: `single_before_album` (an album or EP carries the recording and an earlier single too: the album wins only inside `SINGLE_BEFORE_ALBUM_WINDOW_DAYS`, NOT
FROZEN), `compilation_title` (the chosen release's title carries a marker of `COMPILATION_MARKERS`) and `latin_spelling_only` (a non-Latin song whose only hits are spelled in Latin letters).
[decide] asks and decides in one function, which the album pass and the dry run both call (the two do not select the same songs: see `album_dryrun`). `IDENTITY_REVISION` is raised by hand with
every change of the rule's code (a new step) and is pinned with the values that are plain data: the tolerance, the single window, the compilation markers, the types that win and
`textnorm.TEXTNORM_REVISION` (a change of the fold changes which keys are equal, which decided most `none` answers).

**The names go through the one fold, so its limits are the matcher's.** Since P2-25 slices 2 and 3 `textnorm` keeps the letters of every alphabet (audit
B-37): two different Arabic songs are two different keys, and a hit is the song only when its artist AND its key (`refs.norm_key`: the artist, the title
and the version) are equal. Nothing is transliterated, so an Arabic name and its Latin spelling are two names: a miss, never a wrong stamp. The one kind of
name that is refused at step 0 is a name with NOTHING TO COMPARE: no letter and no digit after the fold (only symbols, emoji or marks:
`textnorm.survives_fold_whole`, defined by P2-25 slice 1 and described ONCE, in the P2-25 design, part 4: never copied here), or nothing left once the
word rules have taken their noise away (`VEVO`, a title that is only "Audio"). Only the SONG is asked for it: a hit with nothing to compare cannot have the
song's artist and key, so the equality refuses it; a second test for the hit's names would decide nothing the equality does not (a test pins it).
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from . import refs
from .catalogue import map_track, release_key
from .deezer import LookupUnavailable, NotInCatalogue
from .textnorm import fold, is_unknown_artist, mentions_version, norm_artist, norm_title, survives_fold_whole, words

#: How far a song's length may be from the catalogue's for the two to be the same recording, in milliseconds. It starts as the one number the server
#: already uses for "the same recording" (`refs.DURATION_TOLERANCE_MS`, imported, never copied).
#:
#: **MEASURED on 24 Nov 2026 and KEPT at 3 s.** The live dry run (672 songs of VM 108's library, the kept FILES read from disk, the real catalogue) found 404 songs with a
#: hit of the same artist, title and version: 161 (40 percent) within 3 s of the catalogue's length, 243 outside, in a smooth tail with NO cliff (the bins 3 to 4 s, 4 to 5 s and
#: 5 to 10 s hold 14, 10 and 29 songs). There is no better edge in the data, so 3 s stays as the conservative one. Price: a tolerance this tight only makes misses (243 songs
#: with a hit of their name stay a re-askable `none`); one too loose would write a permanent wrong id. It is a decision, not a stop-gap: the report prints it on its first
#: line, and a different library may be read the same way (`--tolerance-ms`).
TOLERANCE_MS = refs.DURATION_TOLERANCE_MS

#: The revision of the rule as a whole. Raised BY HAND when the rule's code changes (a new step, a new reason); the plain data that decides a verdict (`TOLERANCE_MS`, the single
#: window, the compilation markers, the types that win, `textnorm.TEXTNORM_REVISION`) is pinned with it in `tests/test_album_withheld.py`, so a change to one of THOSE cannot land
#: without this rising. A `none` or `held` song whose `identity_rev` is
#: lower is asked again at once (`album_pass`); a `matched` song is never asked (it has its ids).
#: 2: the release-title version rule (`release_markers`), `isrc_differs` and the marker `retrospective`, from the review of PR 125 and the live dry run. Nothing was stamped with 1.
#: 3: the marks Unplugged, Re-recorded and the possessive Version, and a release called `Unknown Album` refused (the adversarial tester). Nothing was stamped with 2.
#: 4: slice 2 never stamps a single (`single_only`, the advisor's ruling after the live dry run). Nothing was stamped with 3.
#: 5: `date_decided` and `sole_album` (the first live pass on a real server stamped five doubtful albums, all undone), the edition families, and a year-only date that is no earlier
#: than another date of its year. **Revision 4 DID stamp** (35 songs on one server, 5 of them wrong): a `matched` song is never asked again, so those stamps are undone by hand, not by this.
IDENTITY_REVISION = 5

#: How many days an ALBUM may come after the SINGLE that carries the same recording and still be the song's album (a lead single comes out before its album).
#: Inside it the album wins; outside it, or when the two dates cannot be compared, the song is `none` with the reason `single_before_album`, which is asked again.
#:
#: **STOP-GAP(N-34 single window): NOT FROZEN (`None`): every earlier single is re-askable.** The advisor's ruling of 17 Nov 2026 asked for a window MEASURED from
#: the tracked recordings (`tests/test_album_withheld.py::measured_pairs`, no network). They hold ONE proven pair (Creature: the same ISRC and length on the single
#: and on the album, 457 days apart) and three more by title and date (127, 84 and 64 days), all of one band and one album: they show that a lead single can come
#: out months before its album, not where a window ends (no counter-example, no second artist, no label that re-dates a catalogue), and a wrong stamp is permanent.
#: Price: every song whose recording came out first as a single and later on an album stays in the bucket "Songs without an album" (named for what it is) and is
#: asked again every 7 days (a search and the album answers, cached 7 days), until the window is frozen. Removal trigger: the live dry run over the owner's library
#: (`python -m encore_server.album_dryrun --live`, after his test week, the lead's decision) measures the gaps of many artists; the lead reads them, this constant
#: is set, `IDENTITY_REVISION` rises and the songs are asked again. Task: N-34 itself (it stays todo until then). Reminder: the dry-run report's first line.
SINGLE_BEFORE_ALBUM_WINDOW_DAYS: int | None = None

#: Words that say a release is a COMPILATION in its title (whole words, in the order they are tried; the catalogue's `record_type` never marks one: no recorded
#: release is typed `compile`). A SECOND LAYER, never the rule: a match to a release whose title carries one is `none` with the reason `compilation_title` (asked
#: again), not `matched`; a best-of called "Gold" or "Legend" passes, and nothing is refused for good.
#:
#: **STOP-GAP(N-34 compilation markers): English words, a guess on a title.** Price: a song whose real album is called "Collection" or "Hits" stays unfiled and is
#: asked again every 7 days; a compilation with no such word is accepted (the ruling's case 1). Removal trigger: the artist's discography (the earliest release
#: among ALL the albums of the artist that hold the recording), which the ruling defers to a later `identity_rev` round if the dry run shows a large unresolved
#: remainder; then this list goes. Task: N-34 itself.
COMPILATION_MARKERS: tuple[str, ...] = (
    "greatest hits",
    "best of",
    "very best",
    "essential",
    "essentials",
    "collection",
    "collections",
    "anthology",
    "definitive",
    "ultimate",
    "retrospective",
    "hits",
)

#: The plain words that make a COMPETITOR of the chosen release no competitor (`date_decided`): a title that says it is a best-of, a collection, a set of singles or a numbered volume is a
#: compilation, and a compilation is not a rival ORIGINAL of the song. Whole words and phrases of the shared fold, tried with [COMPILATION_MARKERS] (a competitor is exempt on either).
#: **A SEPARATE list on purpose**: [COMPILATION_MARKERS] decide `compilation_title` for the CHOSEN release, where a best-of called "Gold" or a set called "Singles" is accepted (the advisor's
#: ruling of 17 Nov 2026: the markers only downgrade, never refuse, and are never the whole rule); a word here exempts a rival from a rule that delays songs, and costs only a missed delay.
#: **STOP-GAP(N-34 date decided): English words, a guess on a title.** Price: a rival ORIGINAL whose title holds one of them ("Greatest Hitz" is not one, "Gold" is) does not delay the song.
#: Removal trigger and task: the artist's discography (item N-48), which tells an original from a compilation by what the catalogue says of the artist's albums, not by a word; then this list goes.
PLAIN_COMPILATION_WORDS: tuple[str, ...] = (
    "greatest",
    "best of",
    "hits",
    "collection",
    "essential",
    "anthology",
    "gold",
    "ultimate",
    "singles",
    "vol",
)

Outcome = Literal["matched", "none", "held", "unsupported", "no_length", "unavailable"]

#: The outcomes that are FACTS about the song and the catalogue, and may be stored. The rest say "not asked": never stored (audit B-124).
REMEMBERED: frozenset[Outcome] = frozenset({"matched", "none", "held"})

HitReason = Literal[
    "same_recording", "unreadable", "artist", "title_or_version", "isrc_differs", "no_length", "length", "no_album"
]
ReleaseReason = Literal["chosen", "outranked", "album_artist", "record_type", "release_version", "release_placeholder"]

#: The `record_type`s of every release in the tracked recordings of Deezer's real answers (the 8 answers of `tests/fixtures/deezer/` that hold releases, and the
#: 20 searches of `app/test/fixtures/deezer/search.json`; the server's own mapped copies in `app/test/fixtures/server/` are not counted, they are the same releases
#: again; plus the 5 answers of the live dry run of 24 Nov 2026 that the tests need): 232 distinct releases, `album` 116, `single` 106, `ep` 10 (recounted by `tests/test_album_finder.py`, which fails when a recording changes them).
#: **The recordings hold no `compile` and no live or remix value: no release of them is marked a compilation or a live record**, so the type cannot tell a
#: best-of from an album (Legend Remixed and the Legacy sets are `album`). **Any other value never wins**: the spellings that mark a compilation or a live
#: record are not known, and a guess would be a wrong album.
_FULL_RELEASE = frozenset({"album", "ep"})
_SINGLE = "single"

_DATE = re.compile(r"(\d{4})-(\d\d)-(\d\d)")


@dataclass(frozen=True)
class Song:
    """What is known of the song being asked about: its FIRST artist (`refs.lead_artist`), its title and its length in milliseconds, the length of the
    kept file when there is one and the import's listing otherwise (`None` when neither is known)."""

    artist: str
    title: str
    length_ms: int | None
    #: The song's own ISRC (`song_ref.isrc`), `None` when it holds none. COUNTER-EVIDENCE only: a recording has one ISRC, so a catalogue entry that carries ANOTHER one is not
    #: this recording (`isrc_differs`); an equal one, or none on either side, changes nothing (nothing is matched BY it here: the pass fills the ids afterwards).
    isrc: str | None = None


def _isrc(value: object) -> str | None:
    """An ISRC as the catalogue's mapping writes it (`catalogue.map_track`: upper case, no hyphens), or `None`."""
    text = str(value).replace("-", "").replace(" ", "").upper() if value else ""
    return text or None


@dataclass(frozen=True)
class HitVerdict:
    """What the rule says of ONE hit of the search. `reason` is `same_recording` for a hit that passes and the first test it failed otherwise.
    `delta_ms` is the song's length minus the catalogue's (what the dry run draws as a histogram), when both are known."""

    id: str | None
    artist: str
    title: str
    album_id: str | None
    reason: HitReason
    delta_ms: int | None
    #: The artist, the title and the version all agree (the length is the only thing left to say): `reason` is `length`, `no_length`, `no_album` or
    #: `same_recording`.
    name_fits: bool
    #: The title and the picture of the album the hit is on, as the catalogue's search row carries them (`None` when it carries none): what the cover finder takes
    #: from an ACCEPTED hit.
    album_title: str | None = None
    cover: str | None = None

    @property
    def accepted(self) -> bool:
        return self.reason == "same_recording"


@dataclass(frozen=True)
class ReleaseVerdict:
    """What the rule says of one release a same-recording hit is on."""

    album_id: str
    title: str | None
    record_type: str | None
    release_date: str | None
    #: `catalogue.release_key(title)`: what two editions of one release share (a deluxe and its original). Empty when the title has no letter.
    key: str
    reason: ReleaseReason


@dataclass(frozen=True)
class Match:
    """The release chosen and the song on it: what a pass may store (`refs.release_facts_to_fill`, slice 2). The ids are the catalogue's, as text; the
    `deezer_id` is the id of the track ON THE CHOSEN release (a track has a different id on every release)."""

    deezer_id: str
    isrc: str | None
    album_id: str
    #: The catalogue's own title of the release chosen (never the library's guess).
    album: str
    record_type: str
    release_date: str | None
    year: int | None
    track_no: int | None
    disc_no: int | None
    cover: str | None

    @property
    def single(self) -> bool:
        return self.record_type == _SINGLE


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    #: A short code naming the step that decided (`artist_not_comparable`, `no_same_recording`, `track_not_listed`, `deezer_id_held`, ...): for the log and
    #: the report, never for a branch.
    reason: str
    hits: tuple[HitVerdict, ...] = ()
    releases: tuple[ReleaseVerdict, ...] = ()
    #: For `matched`; for `held` too: what WOULD have been written.
    match: Match | None = None
    detail: str = ""
    #: For a `none` the rule WITHHELD (`single_before_album`, `compilation_title`): what the old rule would have written, so that the dry run can show it and count
    #: the songs that wait on a window or a better rule. **Never written by anybody**: only `match` of a `matched` verdict is stored.
    withheld: Match | None = None

    @property
    def remember(self) -> bool:
        """Whether a pass may store this as the song's `identity_outcome`. `unsupported`, `no_length` and `unavailable` are not facts about the catalogue."""
        return self.outcome in REMEMBERED


class Holdings(Protocol):
    """What the OTHER live refs already hold (step 5): the database's side of the pair rule, asked per song so that a pass that writes as it goes never
    reads a stale answer. "Another" excludes the song's own ref."""

    def deezer_id_held(self, deezer_id: str) -> bool: ...

    def isrc_held(self, isrc: str) -> bool: ...

    def twin_held(self, norm_key: str, release: str) -> bool:
        """Another live ref has this `norm_key` and an album with this `release_key`."""
        ...


class _Nothing:
    def deezer_id_held(self, deezer_id: str) -> bool:
        return False

    def isrc_held(self, isrc: str) -> bool:
        return False

    def twin_held(self, norm_key: str, release: str) -> bool:
        return False


#: No other ref holds anything (a fresh database, a test of the earlier steps).
NO_HOLDINGS: Holdings = _Nothing()


class RefHoldings:
    """[Holdings] read from `song_ref` (the unique indexes of `0001_initial.sql` make a second `deezer_id` or `isrc` impossible, so a taken one is a
    HOLD, not a write that fails). Reads only."""

    def __init__(self, conn: sqlite3.Connection, ref_id: str) -> None:
        self._conn = conn
        self._ref = ref_id

    def deezer_id_held(self, deezer_id: str) -> bool:
        return (
            self._conn.execute("SELECT 1 FROM song_ref WHERE deezer_id = ? AND id != ?", (deezer_id, self._ref)).fetchone()
            is not None
        )

    def isrc_held(self, isrc: str) -> bool:
        return self._conn.execute("SELECT 1 FROM song_ref WHERE isrc = ? AND id != ?", (isrc, self._ref)).fetchone() is not None

    def twin_held(self, norm_key: str, release: str) -> bool:
        if not release:
            return False  # a title with no letter in it: never merged on an empty key
        rows = self._conn.execute(
            "SELECT album FROM song_ref WHERE norm_key = ? AND id != ? AND album IS NOT NULL", (norm_key, self._ref)
        )
        return any(not refs.is_placeholder_album(album) and release_key(album) == release for (album,) in rows)


# ------------------------------------------------------------------------------------------------------------------ step 0: can it be asked


def refusal(song: Song) -> tuple[Outcome, str] | None:
    """Step 0. `None` when the song can be asked about, else the outcome and the reason. No refusal is remembered: a song that is given a length (or a name
    with something in it) is simply asked."""
    # A name with nothing to compare: no letter or digit after the fold (`survives_fold_whole`, the one definition: asked, so that a stricter definition
    # tomorrow refuses a song here without a change to this module), or nothing left once the word rules removed their noise (`VEVO`, "Audio").
    if not survives_fold_whole(song.artist) or not norm_artist(song.artist):
        return "unsupported", "artist_not_comparable"
    if not survives_fold_whole(song.title) or not norm_title(song.title):
        return "unsupported", "title_not_comparable"
    if is_unknown_artist(song.artist):
        # A name that cannot be told from "nobody" identifies nothing (`textnorm.is_unknown_artist`; `refs.find` and the artist finder refuse it too).
        return "unsupported", "artist_is_nobody"
    if song.length_ms is None or song.length_ms <= 0:
        return "no_length", "no_length"
    return None


# ------------------------------------------------------------------------------------------------------------------ steps 1 and 2: the same recording


def judge_hits(song: Song, hits: Sequence[object], *, tolerance_ms: int = TOLERANCE_MS) -> tuple[HitVerdict, ...]:
    """One verdict per hit of a search (`deezer.search_tracks`: the raw rows) for a song that step 0 let in. The tests, in order, and the first a hit fails is
    its reason:

    1. `artist`: the same `norm_artist`.
    2. `title_or_version`: the same `refs.norm_key`, which is the artist, `norm_title` AND the version signature (`norm_title` strips brackets, so
       "Comfortably Numb (Live)" and "Comfortably Numb" share it; the signatures are `{live}` and empty).
    3. `length`: within [tolerance_ms] of the song's (a remaster is the same recording; an edit of 238 s against 292 s is not: both signatures are empty,
       only the length tells them apart).

    A hit whose artist or title holds no letter and no digit has nothing to compare, and the equality refuses it at 1 or 2: the song has a letter or a digit in
    both, so it has neither that artist nor that key.
    """
    want_artist, want_key, want_isrc = norm_artist(song.artist), refs.norm_key(song.artist, song.title), _isrc(song.isrc)
    verdicts: list[HitVerdict] = []
    for row in hits:
        track = map_track(row)
        if track is None or not track["artists"]:
            verdicts.append(HitVerdict(None, "", "", None, "unreadable", None, False))
            continue
        name, title = track["artists"][0]["name"], track["title"]
        album_id = track["album"]["id"] if track["album"] else None
        length = track["durationMs"]
        delta = song.length_ms - length if song.length_ms is not None and length is not None else None
        fits = False
        reason: HitReason
        if norm_artist(name) != want_artist:
            reason = "artist"
        elif refs.norm_key(name, title) != want_key:
            reason = "title_or_version"
        elif want_isrc and track["isrc"] and track["isrc"] != want_isrc:
            # The names agree and the ISRCs do not: another recording (a remaster, a re-recording) of the same name. The search row seldom carries an ISRC; the chosen release's
            # song list does, and `choose_release` asks the same question there.
            fits = True
            reason = "isrc_differs"
        else:
            fits = True
            if delta is None:
                reason = "no_length"
            elif abs(delta) > tolerance_ms:
                reason = "length"
            elif album_id is None:
                reason = "no_album"
            else:
                reason = "same_recording"
        verdicts.append(
            HitVerdict(
                track["id"],
                name,
                title,
                album_id,
                reason,
                delta,
                fits,
                track["album"]["title"] if track["album"] else None,
                track["cover"],
            )
        )
    return tuple(verdicts)


def wanted_albums(song: Song, hits: Sequence[object], *, tolerance_ms: int = TOLERANCE_MS) -> list[str]:
    """The albums the caller must ask the catalogue about before [choose_release] can decide: those the same-recording hits are on, each once, in the
    order the search listed them. Nothing for a song that cannot be asked about."""
    if refusal(song) is not None:
        return []
    ids: list[str] = []
    for verdict in judge_hits(song, hits, tolerance_ms=tolerance_ms):
        if verdict.accepted and verdict.album_id and verdict.album_id not in ids:
            ids.append(verdict.album_id)
    return ids


# ------------------------------------------------------------------------------------------------------------------ steps 3 to 5: which release


def release_date(value: object) -> str | None:
    """A date the catalogue gave, when it is one: `YYYY-MM-DD`, year from 1900. The catalogue's "unknown" is `0000-00-00` (`map_album` keeps it and turns
    it into year 0): it is not a date, and a release with none never wins "earliest"."""
    match = _DATE.fullmatch(value) if isinstance(value, str) else None
    if match is None or int(match[1]) < 1900 or not 1 <= int(match[2]) <= 12 or not 1 <= int(match[3]) <= 31:
        return None
    return str(value)


#: The most digits a catalogue id has (Deezer's are 8 to 10 today; a 64-bit number has 19 or 20).
_MAX_ID_DIGITS = 20


def _id_order(ident: str) -> tuple[int, int, str]:
    """Catalogue ids are numbers sent as text: the LOWEST id is the numerically lowest ("9" is lower than "10"); anything else sorts after them. A real id is 1 to 20 ASCII
    digits: a longer one is not an id (`int()` of 4,301 digits raises, the tester's probe made the pass abort at that song every pass) and sorts after every real id."""
    # `isascii` first: a superscript two is `isdigit()` and `int()` raises on it, and `catalogue._id` passes any text through.
    return (0, int(ident), ident) if ident.isascii() and ident.isdigit() and len(ident) <= _MAX_ID_DIGITS else (1, 0, ident)


@dataclass(frozen=True)
class _Facts:
    """What the rule reads of one album answer (`Catalogue.album`: `album` is `catalogue.map_album`'s shape)."""

    album_id: str
    title: str
    record_type: str | None
    date: str | None
    key: str
    artist: str
    track_count: int | None
    cover: str | None


def _facts(album_id: str, answer: object) -> _Facts | None:
    """`None` when the answer holds no album at all (it could not be asked)."""
    album = answer.get("album") if isinstance(answer, Mapping) else None
    if not isinstance(album, Mapping) or not album.get("title"):
        return None
    artists = album.get("artists")
    by = artists[0].get("name") if isinstance(artists, list) and artists and isinstance(artists[0], Mapping) else None
    count, cover = album.get("trackCount"), album.get("cover")
    return _Facts(
        album_id=album_id,
        title=str(album["title"]),
        record_type=str(album["recordType"]).strip().lower() if album.get("recordType") else None,
        date=release_date(album.get("releaseDate")),
        key=release_key(str(album["title"])),
        artist=str(by or ""),
        track_count=count if isinstance(count, int) else None,
        cover=cover if isinstance(cover, str) else None,
    )


#: The forms of a version word that a release title can carry and `textnorm.mentions_version` (whole words of `VERSION_WORDS`) does not see: "Remixed", "The Remixes".
_VERSION_FORMS = {
    "remixed": "remix",
    "remixes": "remix",
    "demos": "demo",
    "covers": "cover",
    "instrumentals": "instrumental",
    "mashups": "mashup",
    "medleys": "medley",
}


#: Marks a title can carry that `textnorm.VERSION_WORDS` does not list: another RECORDING of the song, which the library's file is not unless the song's own title says so.
#: (`textnorm` is the pinned fold and its list feeds the YouTube matcher, so these are the album matcher's own.) **`Sessions` and `Tribute` are left out on purpose**: they are in too
#: many real album names, the cost of a miss is a re-askable `none`, and the artist's discography (the remedy named on 17 Nov) tells such a release apart. A possessive "Version"
#: (Taylor's Version, Mine's Version) is a re-recording by its own convention.
_EXTRA_MARKS: tuple[tuple[str, str], ...] = (
    ("unplugged", r"\bunplugged\b"),
    ("re-recorded", r"\bre[ -]?record(?:ed|ing|ings|s)?\b"),
    ("possessive version", r"\b\w+['\u2019]s version\b"),
)
_EXTRA_PATTERNS = tuple((name, re.compile(pattern)) for name, pattern in _EXTRA_MARKS)


def release_markers(title: str) -> frozenset[str]:
    """The version marks a RELEASE's title carries: the server's one list of "versions that are not what was asked for unless the request says so" (`textnorm.VERSION_WORDS`:
    live, remix, acoustic, demo, instrumental, karaoke, cover ...), as whole words, and the plural and past forms a title uses ("Remixed", "The Remixes"). **The labels that say which
    PRINTING it is, not which recording, are not marks** (Remastered, Deluxe, Bonus or Expanded Edition, Explicit, Clean, Radio Edit, a year): they are not in the list."""
    found = set(mentions_version(title))
    folded = fold(title or "")
    found |= {_VERSION_FORMS[token] for token in words(folded) if token in _VERSION_FORMS}
    found |= {name for name, pattern in _EXTRA_PATTERNS if pattern.search(folded)}
    return frozenset(found)


# ------------------------------------------------------------------------------------------------------------------ release families: editions of one release are one release

#: What an EDITION LABEL is made of: the words that say which PRINTING of a release it is, never which recording (a live, remix or acoustic record, a re-recording, "Taylor's Version" carry a
#: version mark and are another release, `release_markers`): they are not here, so a group that holds one is never a label. Nothing is stripped from a title unless EVERY word of the
#: group is one of these, so a title's own words ("Green Album", "Refill", "Resurrected", "Epilogue") stay. The words that are enough to END an unbracketed label are [_LABEL_ENDS].
_LABEL_WORDS = frozenset(
    {
        "deluxe", "expanded", "extended", "bonus", "anniversary", "legacy", "special", "standard", "digital", "super", "limited", "original",
        "remastered", "remaster", "remasters", "explicit", "clean", "edited", "international", "album", "single", "and", "the",
    }
)  # fmt: skip
#: A trailing run of label words with NO brackets around it is a label only when it ends in one of these ("Meteora 20th Anniversary Edition"): a bare "Clean" or "Legacy" at the end of a
#: title is the title's own ("Squeaky Clean").
_LABEL_ENDS = ("edition", "version", "remaster", "remastered", "remasters", "anniversary", "deluxe", "expanded", "explicit")
_LABEL_ORDINAL, _LABEL_YEAR = r"\d{1,3}(?:st|nd|rd|th)", r"(?:19|20)\d\d"
_LABEL_TOKEN = rf"(?:{_LABEL_ORDINAL}|{_LABEL_YEAR}|{'|'.join(sorted(map(re.escape, _LABEL_WORDS | set(_LABEL_ENDS)), key=len, reverse=True))})"
_LABEL_GAP = r"[\s/&,+\-]+"
_LABEL_BRACKETED = re.compile(rf"\s*[(\[]\s*{_LABEL_TOKEN}(?:{_LABEL_GAP}{_LABEL_TOKEN})*\s*[)\]]\s*$")
_LABEL_TRAILING = re.compile(
    rf"(?:^|\s)(?:{_LABEL_TOKEN}{_LABEL_GAP})*(?:{'|'.join(_LABEL_ENDS)})(?:{_LABEL_GAP}{_LABEL_YEAR})?\s*$"
)


def _plain_text(text: str) -> str:
    """The fallback of a family key: the title's own text, Unicode-normalised, case-folded and with its whitespace collapsed (NOT `release_key`, which drops symbols and edition words)."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _key(text: str) -> str:
    """`catalogue.release_key` of the text with its standalone SYMBOLS kept (a word made of no letter or digit: "÷", "+", "!!!"), or, where nothing is left, the text's own plain form: a family key is
    never empty for a title that has any character, and two titles that differ only in such a symbol are two releases ("÷ (Tour Edition)" and "+ (Tour Edition)" were both the key "tour": a rival
    disappeared, found by the property test of PR 132). The release key alone drops them, by design, for the twin rule and the cover finder, which this does not change."""
    base = release_key(text)
    symbols = [word for word in _plain_text(text).split() if not any(ch.isalnum() for ch in word) and word != "&"]
    if symbols:
        return " ".join(part for part in (base, " ".join(symbols)) if part)
    return base or _plain_text(text)


def _strip_labels(title: str) -> str:
    """The folded title with the NARROW list of edition labels taken off its end, never down to nothing: a shorter text is taken only when it has a key of its own."""
    text = fold(title.strip())
    while True:
        shorter = _LABEL_BRACKETED.sub("", text, count=1)
        if shorter == text:
            shorter = _LABEL_TRAILING.sub("", text, count=1)
        if shorter == text or not _key(shorter):
            return text
        text = shorter


def release_family(title: str) -> str:
    """The NARROW family: what two titles must share to be ONE RELEASE for the rival test of `date_decided`: `catalogue.release_key` (no case, the shared fold, the edition suffixes it knows, no
    leading "the") with the edition labels of the live data folded too: "Hybrid Theory (Bonus Edition)", "(20th Anniversary Edition)", "Meteora 20th Anniversary Edition", "(20th Anniversary / Deluxe)"
    "[Edited Version]", "(International Version)", "(Clean)", "(2001)" are the plain title's release. **The one place the labels live** (`catalogue.release_key` also feeds the twin rule, the
    fill rule and the cover finder, which are not changed by this slice); a group that holds any other word is part of the title, so "Relapse: Refill" and "Waking The Fallen: Resurrected" are other
    releases and "(Live)", "(Acoustic)" and "(Taylor's Version)" never fold. A title that is only labels or only symbols keeps a key of its own (`_key`: never the empty family).
    **The direction of an error, for THIS comparison**: a label it misses makes a RIVAL (two families), so the song is held (`date_decided`, a delay); a label it folds that it should not would hide a rival
    and let a stamp through, so the words are few and listed. The other rule, `sole_album`, fails the other way and uses [broad_release_family]."""
    return _key(_strip_labels(title))


#: The BROAD key's extra tails: any trailing bracketed group, a dashed group, a colon group ("Harbour (Tour Edition)", "Harbour - Japan", "Relapse: Refill"). Never a run of words: a run that ends in
#: an edition word and starts anywhere eats the title's own words ("Gold Harbour 10th Anniversary Edition" -> "gold": found by the property test of PR 132), which makes a SECOND release out of one.
_BROAD_TAIL = re.compile(r"\s*[(\[][^()\[\]]*[)\]]\s*$|\s*:\s+\S.*$|\s+[-–—]\s+\S.*$")


def broad_release_family(title: str) -> str:
    """The BROAD key: the narrow family with every trailing bracketed, dashed or colon group taken off as well. It is NOT the whole comparison (see [broadly_the_same_release]): an unbracketed label this
    code has never seen ("Harbour Japanese Version") is left as extra words after the plain title, and the comparison treats a title that continues another as the same release. Never empty for a
    title that has any character (`_key`)."""
    text = fold(title.strip())
    while True:
        shorter = _BROAD_TAIL.sub("", text, count=1)
        if shorter == text:
            shorter = _strip_labels(text)
        if shorter == text or not _key(shorter):
            return _key(text)
        text = shorter


#: The word that ENDS an edition label however many words come before it ("Tour Edition", "Japanese Version", "Reissue 2009"): the unbracketed labels this code has never seen all end in one.
_EDITION_ENDS = frozenset({*_LABEL_ENDS, "reissue", "reissued"})


def _broad_tokens(title: str) -> list[str]:
    """The title as plain words (symbols kept: "÷" is a word), with only the bracketed, dashed and colon tails taken off; the labels the narrow list knows stay, they are judged as the extra words
    they are."""
    text = fold(title.strip())
    while True:
        shorter = _BROAD_TAIL.sub("", text, count=1)
        if shorter == text or not _plain_text(shorter):
            break
        text = shorter
    return _plain_text(text).split()


def _edition_like(rest: list[str]) -> bool:
    """Nothing, or a year, or one to four words that end in an edition word (and perhaps a year): what an edition label of a release looks like after the plain title."""
    if rest and re.fullmatch(r"(?:19|20)\d\d", rest[-1]):
        rest = rest[:-1]
    return not rest or (len(rest) <= 4 and rest[-1] in _EDITION_ENDS)


def broadly_the_same_release(one: str, other: str) -> bool:
    """The BROAD comparison, for the sole-album test of `sole_album`: two titles are one release when they share a first word and what follows the words they share, in each, is nothing or an edition
    label ("Harbour" and "Harbour Japanese Version", "Harbour Deluxe Edition" and "Harbour Tour Edition 2009", "÷" and "÷ Reissue"): extra words that END in an edition word. **Its error direction
    is the other one from the narrow family's**: it may call two different releases one, and then a song is held as a sole album (a delay: the discography round, N-48, tells them apart); it never
    makes a second release out of one, which would let a sole album through. "Harbour" and "Harbour Lights" are two releases. A title with no words at all is treated as the same release: when in
    doubt, hold."""
    first, second = _broad_tokens(one), _broad_tokens(other)
    if not first or not second:
        return True
    if broad_release_family(one) == broad_release_family(other):
        return True
    common = 0
    while common < min(len(first), len(second)) and first[common] == second[common]:
        common += 1
    return common > 0 and _edition_like(first[common:]) and _edition_like(second[common:])


def _family_of(facts: _Facts) -> str:
    """A release's NARROW family key; a release with no title at all is a family of its own (its id), never one with every other untitled release."""
    return release_family(facts.title) or f"#{facts.album_id}"


def _labelled(title: str) -> bool:
    """Whether the title carries one of the narrow edition labels: on a tie, the PLAIN title is the release's name (the album's name is permanent)."""
    return _strip_labels(title) != fold(title.strip())


def _title_says(title: str, phrases: Sequence[str]) -> bool:
    """Whether the title carries one of the phrases as whole words (case, accents and punctuation do not matter: the shared fold)."""
    tokens = words(fold(title))
    for phrase in phrases:
        part = phrase.split()
        if any(tokens[start : start + len(part)] == part for start in range(len(tokens) - len(part) + 1)):
            return True
    return False


def _compilation_like(title: str) -> bool:
    """A title that says it is a compilation, by [COMPILATION_MARKERS] or by [PLAIN_COMPILATION_WORDS]: such a release is no rival original (`date_decided`)."""
    return _title_says(title, COMPILATION_MARKERS) or _title_says(title, PLAIN_COMPILATION_WORDS)


def _why_not(facts: _Facts, want_artist: str, song_marks: frozenset[str] = frozenset()) -> ReleaseReason | None:
    """Step 3 (a) and (b): why this release can never be chosen, or `None`."""
    # (a) The album artist is the song's first artist: a song on somebody else's album, a tribute, a compilation of many artists is a miss. An album that names
    # nobody, or whose artist has nothing to compare, is nobody's: the song's own artist has a letter or a digit (step 0), so the equality refuses it.
    if norm_artist(facts.artist) != want_artist:
        return "album_artist"
    # (b) The type: `album` and `ep` rank first, `single` after them, any other value (or none) never wins.
    if facts.record_type not in _FULL_RELEASE and facts.record_type != _SINGLE:
        return "record_type"
    # (c) The version: a release whose own title says live, remix, acoustic ... when the song's title does not is the release of ANOTHER recording of that name. The hit's title is
    # held to the same marks (`refs.norm_key`'s version signature); without this a studio song was stamped with a live album, the earliest of its two releases (the live dry run).
    if release_markers(facts.title) - song_marks:
        return "release_version"
    # (d) A release called `Unknown Album` is the music server's word for NO album: matched, the id would be set and the album written would be the placeholder, a permanent
    # match with no album that nothing asks again (the tester's probe).
    if refs.is_placeholder_album(facts.title):
        return "release_placeholder"
    return None


def _date_order(date_: str | None) -> tuple[int, int, str]:
    """Where a release date sorts: by YEAR, and within a year a REAL date before a year-only one. A catalogue date that ends `-01-01` is the placeholder for "some day of that year" (the live dry
    run: `1990-01-01`, `2004-01-01`, `2002-01-01` on releases of other years), so it is never EARLIER than another date of the same year: it cannot be shown to be. A date that is not known
    is last. (The rule that withholds a song for an EARLIER single, [_single_before], is NOT loosened the same way: it is a withhold, and loosening a withhold makes permanent stamps.)"""
    if not date_:
        return (9999, 2, "")
    return (int(date_[:4]), 1 if date_.endswith("-01-01") else 0, date_)


def _order(facts: _Facts) -> tuple[int, tuple[int, int, str], int, tuple[int, int, str]]:
    """Step 3 (b) to (d): `album` and `ep` before `single` whatever the dates (the TIER), then the EARLIEST date ([_date_order]), then, on a tie, the title with no edition label ("By the Way", not "By the Way (Deluxe Edition)": the name is permanent), then the lowest id. **Nothing sits between the tier and the
    date**: a release that beat another of its tier ONLY by what follows the tier (a date, a tie, a missing date, an id) is what `date_decided` is about."""
    return (
        0 if facts.record_type in _FULL_RELEASE else 1,
        _date_order(facts.date),
        1 if _labelled(facts.title) else 0,
        _id_order(facts.album_id),
    )


def _gap_days(earlier: str | None, later: str | None) -> int | None:
    """The days from one release date to another, or `None` when either is not a real day (`release_date` checks the shape; a 31st of February passes it)."""
    try:
        return (date.fromisoformat(later) - date.fromisoformat(earlier)).days if earlier and later else None
    except ValueError:
        return None


def _single_before(album: _Facts, singles: Sequence[_Facts], window_days: int | None) -> str | None:
    """The reason the album cannot be taken over an EARLIER single, or `None` (the advisor's ruling, case 2). A single dated on the album's day or after it is
    no earlier single. An earlier one is inside the window when [window_days] is set and the gap is within it (inclusive). Anything else, a gap that cannot be
    measured included (a date that is missing or is not a day), is outside: the album has no proof."""
    for single in singles:
        if album.date and single.date and single.date >= album.date:
            continue
        gap = _gap_days(single.date, album.date)
        if gap is not None and window_days is not None and gap <= window_days:
            continue
        shown = f"{gap} days" if gap is not None else "an unknown gap"
        return f"single {single.album_id} ({single.date or 'no date'}) before album {album.album_id} ({album.date or 'no date'}): {shown}, window {window_days}"
    return None


def _compilation_title(title: str) -> bool:
    """Whether the title carries one of [COMPILATION_MARKERS] as whole words (case, accents and punctuation do not matter: the shared fold)."""
    return _title_says(title, COMPILATION_MARKERS)


def _doubted_by_the_dates(chosen: _Facts, others: Sequence[_Facts]) -> tuple[str, str] | None:
    """`date_decided` or `sole_album` with its detail, or `None`: the two invariants of a stamp (see `choose_release`). [others] are the OTHER eligible releases of the hits, of any type.
    A rival is a release of the same TIER (album or EP: `_order`'s tier), of another family, whose title does not say compilation; it counts whatever its date (earlier, later, the same day,
    none: only the id and the date put the chosen release first, and neither is evidence). The sole rule asks for ONE family among all the eligible releases, a single included: a single of
    the song is the song's own release, a second family that corroborates the album."""
    family = _family_of(chosen)
    if chosen.record_type in _FULL_RELEASE:
        rivals = [
            other
            for other in others
            if other.record_type in _FULL_RELEASE and _family_of(other) != family and not _compilation_like(other.title)
        ]
        if rivals:
            shown = "; ".join(f"{rival.title} ({rival.record_type}, {rival.date or 'no date'})" for rival in rivals[:3])
            return "date_decided", f"{chosen.title} ({chosen.date or 'no date'}) was ahead of {shown} on the date order alone"
    if chosen.record_type == "album" and all(broadly_the_same_release(chosen.title, other.title) for other in others):
        return "sole_album", f"{chosen.title} is the only release of the hits"
    return None


def _non_latin(text: str) -> bool:
    """Whether the text holds a letter of another script than the Latin one (Arabic, Cyrillic, Hangul, kana, ideographs, Greek...)."""
    return any(
        unicodedata.category(ch) in ("Lu", "Ll", "Lt", "Lo") and not unicodedata.name(ch, "").startswith("LATIN") for ch in text
    )


def _latin_spelling_only(song: Song, verdicts: Sequence[HitVerdict]) -> bool:
    """A song with a name in another script, and a catalogue that answered with hits spelled in Latin letters ONLY: era 1 compares names in the alphabet they
    are written in and transliterates nothing, so the Latin spelling of an Arabic song can never be proved to be the song. Told apart so that the dry run and the
    database count the songs the catalogue cannot place by that cause."""
    readable = [hit for hit in verdicts if hit.reason != "unreadable"]
    if not readable or not (_non_latin(song.artist) or _non_latin(song.title)):
        return False
    return not any(_non_latin(hit.artist) or _non_latin(hit.title) for hit in readable)


def _held(match: Match, own_key: str, release: str, holdings: Holdings) -> str | None:
    """Step 5: the reason this pair is HELD, or `None`."""
    if holdings.deezer_id_held(match.deezer_id):
        return "deezer_id_held"
    if match.isrc and holdings.isrc_held(match.isrc):
        return "isrc_held"
    if holdings.twin_held(own_key, release):
        return "twin_held"
    return None


def decide(
    song: Song,
    search: Callable[[str, str], list[dict[str, Any]]],
    album: Callable[[str], dict[str, Any]],
    holdings: Holdings = NO_HOLDINGS,
    *,
    tolerance_ms: int = TOLERANCE_MS,
    single_window_days: int | None = SINGLE_BEFORE_ALBUM_WINDOW_DAYS,
) -> Verdict:
    """ASK and decide, the one function the album pass and its dry run both call (they do not select the same songs, see `album_dryrun`): the search, then each album the
    same-recording hits are on (serially), then [choose_release]. [search] and [album] are the caller's (this module opens no connection: the pass gives the gate's, a test
    gives a fake). A search or an album that could not be asked is `unavailable`, never `none`: a "no" is a fact about the catalogue."""
    if refusal(song) is not None:
        return choose_release(song, [], {})
    try:
        found = search(song.artist, song.title)
    except LookupUnavailable as error:
        return Verdict("unavailable", "search_not_asked", detail=str(error))
    answers: dict[str, Mapping[str, Any] | None] = {}
    for album_id in wanted_albums(song, found, tolerance_ms=tolerance_ms):
        try:
            answers[album_id] = album(album_id)
        except (LookupUnavailable, NotInCatalogue):
            continue  # `choose_release` reads an album that is not in the mapping as "could not ask"
    return choose_release(song, found, answers, holdings, tolerance_ms=tolerance_ms, single_window_days=single_window_days)


def choose_release(
    song: Song,
    hits: Sequence[object],
    albums: Mapping[str, Mapping[str, Any] | None],
    holdings: Holdings = NO_HOLDINGS,
    *,
    tolerance_ms: int = TOLERANCE_MS,
    single_window_days: int | None = SINGLE_BEFORE_ALBUM_WINDOW_DAYS,
) -> Verdict:
    """The six steps. [hits] are the rows of `deezer.search_tracks`; [albums] maps an album id to `Catalogue.album(id)` (`{album, tracks, unavailable?}`)
    for the ids [wanted_albums] named, `None` (or no entry) for one that could not be asked. [holdings] is what the other refs hold (step 5).

    * Steps 0 to 2: [refusal] and [judge_hits]. No hit passes: `none` (`no_same_recording`).
    * An album that could not be asked, or one whose song list could not be asked: `unavailable`, never `none`: a "no" is a fact about the catalogue.
    * Step 3, which release: of the albums the passing hits are on, those whose album artist is the song's first artist and whose type is `album`, `ep` or
      `single`; `album` and `ep` rank before `single` WHATEVER the dates (a lead single comes out before its album); then the EARLIEST release date
      (the original is older than its best-ofs and reissues: "Comfortably Numb" is 382 s on The Wall and on a best-of, only the date tells them apart);
      then the lowest id. Editions are compared only where two releases must be told apart as one (step 5, and the report's count of releases): a
      deluxe reissue is later than its original, so the date already prefers the original. What is written is the catalogue's own title.
    * **Withheld (the advisor's ruling of 17 Nov 2026): what cannot be justified on evidence is `none` with a reason, never `matched`**, because a stamped album
      is effectively permanent. (a) The chosen release is an album or EP and an EARLIER single carries the recording: the album outranks it only inside
      [single_window_days] (`single_before_album`; `None`, the default, is NOT FROZEN: see `SINGLE_BEFORE_ALBUM_WINDOW_DAYS`). (b) The chosen release's title carries
      a compilation marker (`compilation_title`). Both keep `withheld`, the match the old rule would have written. A SOLE album (one release family among the eligible
      releases of the hits) is `sole_album` and a choice only the dates decided is `date_decided`: see `_doubted_by_the_dates`.
    * Step 4: the chosen release's song list must hold the hit's id (a track has another id on every release): it gives the track number, the disc and
      the ISRC. A list that does not is `none`, never a guess at the next release.
    * Step 5: a taken `deezer_id` or `isrc`, or another ref that is this song on this release, is `held`: nothing is written and the pair is logged.
    """
    if (refused := refusal(song)) is not None:
        return Verdict(refused[0], refused[1])
    verdicts = judge_hits(song, hits, tolerance_ms=tolerance_ms)
    accepted = [hit for hit in verdicts if hit.accepted and hit.album_id]
    if not accepted:
        if any(hit.reason == "no_album" for hit in verdicts):
            reason = "no_album_on_hit"
        elif any(hit.reason == "isrc_differs" for hit in verdicts):
            reason = "isrc_differs"  # the names agree and the catalogue's own ISRC says it is another recording: counter-evidence, told apart from a plain miss
        else:
            reason = "latin_spelling_only" if _latin_spelling_only(song, verdicts) else "no_same_recording"
        return Verdict("none", reason, hits=verdicts)

    ids = list(dict.fromkeys(hit.album_id for hit in accepted if hit.album_id))
    facts = {ident: _facts(ident, albums.get(ident)) for ident in ids}
    unasked = [ident for ident, found in facts.items() if found is None]
    if unasked:
        return Verdict("unavailable", "release_not_asked", hits=verdicts, detail=", ".join(unasked))
    known = {ident: found for ident, found in facts.items() if found is not None}

    want_artist = norm_artist(song.artist)
    song_marks = release_markers(song.title)
    refused_why = {ident: _why_not(found, want_artist, song_marks) for ident, found in known.items()}
    eligible = [ident for ident in ids if refused_why[ident] is None]

    def judged(chosen: str | None) -> tuple[ReleaseVerdict, ...]:
        return tuple(
            ReleaseVerdict(
                ident,
                found.title,
                found.record_type,
                found.date,
                found.key,
                "chosen" if ident == chosen else refused_why[ident] or "outranked",
            )
            for ident, found in known.items()
        )

    if not eligible:
        # Named when the version was what refused a release: the song is on a live or remix release of its name only, the one case a better rule or another recording of the
        # catalogue may turn into a stamp.
        why = (
            "release_version_mismatch"
            if any(refused_why[ident] == "release_version" for ident in ids)
            else "release_placeholder"
            if any(refused_why[ident] == "release_placeholder" for ident in ids)
            else "no_eligible_release"
        )
        return Verdict("none", why, hits=verdicts, releases=judged(None))
    chosen = min(eligible, key=lambda ident: _order(known[ident]))
    releases = judged(chosen)
    release, answer = known[chosen], albums[chosen]
    assert answer is not None  # `unasked` was empty

    if "tracks" in (answer.get("unavailable") or ()):
        return Verdict("unavailable", "track_list_missing", hits=verdicts, releases=releases, detail=chosen)
    hit = min((h for h in accepted if h.album_id == chosen), key=lambda h: _id_order(h.id or ""))
    listed = [row for row in answer.get("tracks") or () if isinstance(row, Mapping)]
    track = next((row for row in listed if row.get("id") == hit.id), None)
    if track is None:
        cut = release.track_count is not None and release.track_count > len(listed)
        detail = f"{hit.id} on {chosen}: {len(listed)} songs listed of {release.track_count}"
        return Verdict("none", "track_list_cut" if cut else "track_not_listed", hits=verdicts, releases=releases, detail=detail)

    match = Match(
        deezer_id=str(hit.id),
        isrc=track.get("isrc") or None,
        album_id=chosen,
        album=release.title,
        record_type=release.record_type or "",
        release_date=release.date,
        # STOP-GAP(N-34 year): the year is NOT written by a stamp. The catalogue's dates of old releases are reissue dates and year-only placeholders (Weathered 2009, The Invisible Band 2009,
        # Contraband 1990-01-01) and no rule inside the hits can tell them from the real one; a wrong year is as permanent as a wrong album and reaches the Host's disk through the keeper's tags.
        # PRICE: a song stamped here has no year until another source fills it. Removal trigger and task: the artist's discography (item N-48), whose album list can say the first year.
        # The date stays in `release_date` for the report.
        year=None,
        track_no=track.get("trackNo"),
        disc_no=track.get("discNo"),
        cover=release.cover,
    )
    # COUNTER-EVIDENCE comes first (review of PR 125): the song holds an ISRC and the catalogue's entry on the chosen release carries another one, so it is not this
    # recording and a permanent stamp would be a wrong one. Re-askable, with what would have been written, like every withheld answer.
    if (own := _isrc(song.isrc)) and match.isrc and _isrc(match.isrc) != own:
        return Verdict(
            "none",
            "isrc_differs",
            hits=verdicts,
            releases=releases,
            detail=f"the song holds {own}, the catalogue's entry {match.isrc}",
            withheld=match,
        )
    # SLICE 2 NEVER STAMPS A SINGLE (the advisor's ruling after the live dry run of 24 Nov 2026, where 40 of 150 stamps were singles and two of them album tracks: `What's Luv?`,
    # `Buy U A Drank`). A stamp is PERMANENT and the later rounds (the artist's discography, a better rule) only ask `none` and `held` again, so a single stamped here can never be
    # corrected; and the eight hits of a search cannot prove that no album carries the recording. The song is a re-askable `none`. EPs stay accepted; an album that wins over an
    # earlier single is decided above (the window). **The cost is a delay**: the song stays in "Songs without an album" until the discography round, whose first measured target
    # these songs are.
    if release.record_type == _SINGLE:
        return Verdict(
            "none",
            "single_only",
            hits=verdicts,
            releases=releases,
            detail=f"the only release of the hits is the single {release.album_id}",
            withheld=match,
        )
    withhold: tuple[str, str] | None = None
    if release.record_type in _FULL_RELEASE:
        earlier = _single_before(
            release, [known[ident] for ident in eligible if known[ident].record_type == _SINGLE], single_window_days
        )
        if earlier is not None:
            withhold = ("single_before_album", earlier)
    if withhold is None and _compilation_title(release.title):
        withhold = ("compilation_title", release.title)
    if withhold is None:
        # **THE TWO INVARIANTS OF A STAMP** (25 Nov 2026, the first live pass on a real server: 5 of 35 stamps were wrong). A `matched` verdict NEVER (1) has an eligible competitor of the same
        # tier (album or EP), of another release family (`release_family`: the editions of one release are ONE) and with no compilation title (`PLAIN_COMPILATION_WORDS`, `COMPILATION_MARKERS`),
        # that it beat ONLY on the date order, and NEVER (2) comes from a SOLE release of type album (one release family among the eligible releases of the hits; a sole EP is accepted, a sole
        # single is `single_only`). `tests/test_album_rules_property.py` states both against ground truth. Why: the catalogue's DATES of old releases are reissue dates and placeholders
        # (`Enema Of The State` 2018 and 2019, `1990-01-01`), so the earliest date picks an EP or a compilation over the real album, and eight hits cannot prove that no other album carries
        # the song (a compilation, a re-record). A stamp is permanent and a `none` is asked again, so doubt goes to `none`.
        # **STOP-GAP(N-34 date decided): the cost is a DELAY, and a correct stamp is delayed with the wrong ones.** A song whose original is the earliest release but whose artist has
        # another album or EP among the hits (a compilation with no telling word, a re-recording, a "Papercuts") stays in "Songs without an album", asked again every 7 days. Removal trigger
        # and task: the artist's discography (item N-48), which can say which album came first from the catalogue's list of the artist's albums; then both rules become a check on its answer.
        # Reminder: the dry run's report names both reasons and their cost. The same STOP-GAP covers `sole_album`.
        withhold = _doubted_by_the_dates(release, [known[ident] for ident in eligible if ident != chosen])
    if withhold is not None:
        return Verdict("none", withhold[0], hits=verdicts, releases=releases, detail=withhold[1], withheld=match)
    held = _held(match, refs.norm_key(song.artist, song.title), release.key, holdings)
    if held is not None:
        return Verdict("held", held, hits=verdicts, releases=releases, match=match)
    return Verdict("matched", "matched", hits=verdicts, releases=releases, match=match)
