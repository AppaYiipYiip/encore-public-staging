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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from . import refs
from .catalogue import map_track, release_key
from .textnorm import is_unknown_artist, norm_artist, norm_title, survives_fold_whole

#: How far a song's length may be from the catalogue's for the two to be the same recording, in milliseconds. It starts as the one number the server
#: already uses for "the same recording" (`refs.DURATION_TOLERANCE_MS`, imported, never copied).
#:
#: **STOP-GAP(N-34 tolerance): UNMEASURED for this use.** 3 s is the figure for two descriptions of one song, not for a YouTube upload against the
#: catalogue's studio length (N-11 found an import's listing 1 to 12 s off the music server's own length of the same file). Price: a tolerance too
#: tight only makes misses (`none`, asked again after a better rule or 7 days); one too loose would write a permanent wrong id. Removal trigger: the lead
#: reads the dry run (`python -m encore_server.album_dryrun`) over the REAL files and the REAL catalogue, and this constant is frozen from its
#: histogram (the task is the start of N-34 slice 2); until then the report prints this sentence on its first line.
TOLERANCE_MS = refs.DURATION_TOLERANCE_MS

Outcome = Literal["matched", "none", "held", "unsupported", "no_length", "unavailable"]

#: The outcomes that are FACTS about the song and the catalogue, and may be stored. The rest say "not asked": never stored (audit B-124).
REMEMBERED: frozenset[Outcome] = frozenset({"matched", "none", "held"})

HitReason = Literal["same_recording", "unreadable", "artist", "title_or_version", "no_length", "length", "no_album"]
ReleaseReason = Literal["chosen", "outranked", "album_artist", "record_type"]

#: The `record_type`s of every release in the tracked recordings of Deezer's real answers (the 8 answers of `tests/fixtures/deezer/` that hold releases, and the
#: 20 searches of `app/test/fixtures/deezer/search.json`; the server's own mapped copies in `app/test/fixtures/server/` are not counted, they are the same releases
#: again): 228 distinct releases, `album` 114, `single` 104, `ep` 10 (recounted by `tests/test_album_finder.py`, which fails when a recording changes them).
#: **The recordings hold no `compile` and no live or remix value: no release of them is marked a compilation or a live record**, so the type cannot tell a
#: best-of from an album (Legend Remixed and the Legacy sets are `album`). **Any other value never wins**: the spellings that mark a compilation or a live
#: record are not known, and a guess would be a wrong album.
_FULL_RELEASE = frozenset({"album", "ep"})
_SINGLE = "single"

_DATE = re.compile(r"(\d{4})-(\d\d)-(\d\d)")
#: Sorts after every real date: a release whose date is not known never wins "earliest".
_NO_DATE = "9999-99-99"


@dataclass(frozen=True)
class Song:
    """What is known of the song being asked about: its FIRST artist (`refs.lead_artist`), its title and its length in milliseconds, the length of the
    kept file when there is one and the import's listing otherwise (`None` when neither is known)."""

    artist: str
    title: str
    length_ms: int | None


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
    want_artist, want_key = norm_artist(song.artist), refs.norm_key(song.artist, song.title)
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
        verdicts.append(HitVerdict(track["id"], name, title, album_id, reason, delta, fits))
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


def _id_order(ident: str) -> tuple[int, int, str]:
    """Catalogue ids are numbers sent as text: the LOWEST id is the numerically lowest ("9" is lower than "10"); anything else sorts after them."""
    # `isascii` first: a superscript two is `isdigit()` and `int()` raises on it, and `catalogue._id` passes any text through.
    return (0, int(ident), ident) if ident.isascii() and ident.isdigit() else (1, 0, ident)


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


def _why_not(facts: _Facts, want_artist: str) -> ReleaseReason | None:
    """Step 3 (a) and (b): why this release can never be chosen, or `None`."""
    # (a) The album artist is the song's first artist: a song on somebody else's album, a tribute, a compilation of many artists is a miss. An album that names
    # nobody, or whose artist has nothing to compare, is nobody's: the song's own artist has a letter or a digit (step 0), so the equality refuses it.
    if not facts.artist or norm_artist(facts.artist) != want_artist:
        return "album_artist"
    # (b) The type: `album` and `ep` rank first, `single` after them, any other value (or none) never wins.
    if facts.record_type not in _FULL_RELEASE and facts.record_type != _SINGLE:
        return "record_type"
    return None


def _order(facts: _Facts) -> tuple[int, str, tuple[int, int, str]]:
    """Step 3 (b) to (d): `album` and `ep` before `single` whatever the dates, then the EARLIEST date (none is last), then the lowest id."""
    return (0 if facts.record_type in _FULL_RELEASE else 1, facts.date or _NO_DATE, _id_order(facts.album_id))


def _held(match: Match, own_key: str, release: str, holdings: Holdings) -> str | None:
    """Step 5: the reason this pair is HELD, or `None`."""
    if holdings.deezer_id_held(match.deezer_id):
        return "deezer_id_held"
    if match.isrc and holdings.isrc_held(match.isrc):
        return "isrc_held"
    if holdings.twin_held(own_key, release):
        return "twin_held"
    return None


def choose_release(
    song: Song,
    hits: Sequence[object],
    albums: Mapping[str, Mapping[str, Any] | None],
    holdings: Holdings = NO_HOLDINGS,
    *,
    tolerance_ms: int = TOLERANCE_MS,
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
    * Step 4: the chosen release's song list must hold the hit's id (a track has another id on every release): it gives the track number, the disc and
      the ISRC. A list that does not is `none`, never a guess at the next release.
    * Step 5: a taken `deezer_id` or `isrc`, or another ref that is this song on this release, is `held`: nothing is written and the pair is logged.
    """
    if (refused := refusal(song)) is not None:
        return Verdict(refused[0], refused[1])
    verdicts = judge_hits(song, hits, tolerance_ms=tolerance_ms)
    accepted = [hit for hit in verdicts if hit.accepted and hit.album_id]
    if not accepted:
        reason = "no_album_on_hit" if any(hit.reason == "no_album" for hit in verdicts) else "no_same_recording"
        return Verdict("none", reason, hits=verdicts)

    ids = list(dict.fromkeys(hit.album_id for hit in accepted if hit.album_id))
    facts = {ident: _facts(ident, albums.get(ident)) for ident in ids}
    unasked = [ident for ident, found in facts.items() if found is None]
    if unasked:
        return Verdict("unavailable", "release_not_asked", hits=verdicts, detail=", ".join(unasked))
    known = {ident: found for ident, found in facts.items() if found is not None}

    want_artist = norm_artist(song.artist)
    refused_why = {ident: _why_not(found, want_artist) for ident, found in known.items()}
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
        return Verdict("none", "no_eligible_release", hits=verdicts, releases=judged(None))
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
        year=int(release.date[:4]) if release.date else None,
        track_no=track.get("trackNo"),
        disc_no=track.get("discNo"),
        cover=release.cover,
    )
    held = _held(match, refs.norm_key(song.artist, song.title), release.key, holdings)
    if held is not None:
        return Verdict("held", held, hits=verdicts, releases=releases, match=match)
    return Verdict("matched", "matched", hits=verdicts, releases=releases, match=match)
