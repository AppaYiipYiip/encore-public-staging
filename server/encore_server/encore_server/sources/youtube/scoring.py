"""Choosing which YouTube upload is "the song".

Two sources, best first:

1. **YouTube Music search**, then the structured metadata of the top few hits
   (`track`, `artist`, `album`, `duration`: what an official upload declares).
   This tells the album version from the radio edit and from a live take.
2. **Plain YouTube search** (title, channel, duration only) when the first
   finds nothing acceptable.

Scoring is pure and unit-tested; the only I/O is the yt-dlp command line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ...textnorm import is_dense_short, mentions_version, non_latin, norm_artist, norm_title, ratio


@dataclass(frozen=True)
class Want:
    """What the person asked for (from the catalogue)."""

    artist: str
    title: str
    album: str | None = None
    duration_s: int | None = None


@dataclass(frozen=True)
class Candidate:
    """One upload. Plain search fills the first five fields; metadata adds
    the structured ones."""

    video_id: str
    title: str
    channel: str
    duration_s: int | None
    is_topic: bool = False
    track: str | None = None
    artists: tuple[str, ...] = ()
    album: str | None = None
    year: int | None = None

    @property
    def structured(self) -> bool:
        return self.track is not None


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    score: float
    reasons: tuple[str, ...]


#: The revision of the MATCHER: this file's thresholds and weights, `lean.py`'s queries and its artist and title rules. A song the server found no upload for is
#: remembered for a week (`missing.py`) together with this number, and an answer made by an older revision is not believed. **Change it by one whenever a
#: change here could make the matcher find what it did not find before** (a looser threshold, a better query, a new rule); a change that only makes it
#: stricter, or that touches no decision, leaves it. One number voids every older "not found" at once: no sweep, no migration.
#: **N-44 (audit B-136) did NOT raise it: it only makes the matcher STRICTER** (the plain path needs the title too, a title bar worked out word by word), and a stricter rule leaves the revision. (The
#: item's first text said the revision would make songs already matched be asked again: it does not, it voids only a remembered "not found". A wrong upload already KEPT has no re-ask path; the
#: raw upload title is not stored either, so finding them is a network audit of the kept videos: a later item.)
#: 2 (P2-25): the text fold under every comparison now keeps the letters of every alphabet (before, an Arabic, Russian, Korean or Japanese title was `''` and an exact
#: result was REJECTED), and a title of up to four dense-script characters is compared for equality (`textnorm.ratio`): a "not found" earned under revision 1 for a song
#: in another alphabet was a wrong answer, so it is not believed any more.
MATCHER_REVISION = 2

# A candidate must reach this to be used; below it the answer is "not found"
# rather than a wrong song.
ACCEPT = 4.0

#: How alike two titles must be for an upload to be "the same song" (the scoring alone let a 0.21 title through on the artist's name). The structured path and the plain path are
#: held to the same bar (N-44, audit B-136: the plain path had none, so another song of the artist's own channel at the same length scored 7.5 and was kept under the wrong name).
MIN_TITLE_SIMILARITY = 0.6
#: The bar for an upload seen only by its title, channel and length. HIGHER than the structured path's, because nothing else corroborates it, and because 0.6 is where two UNRELATED short titles
#: meet by chance: measured on the real uploads of `tests/fixtures/ytm` (1,342 pairs of two different titles by one artist), the most alike two different songs are is 0.609 ("Enta Wana"
#: and "Malekna Wassal", transliterated Arabic), while one song spelled two ways is 0.84 and above ("Kifak Inta" and "Kifak Enta" 0.90). **FINDING for the structured bar** (not changed here: it
#: has the declared artist beside it, and a change of what is found needs its own measurement): the same 0.609 pair passes `MIN_TITLE_SIMILARITY` there.
PLAIN_MIN_TITLE_SIMILARITY = 0.7

# A plain-search hit this good (right title, the artist's own or Topic
# channel, the right length to the second) is taken at once: the slower
# YouTube Music metadata lookup is only for when it is not clear.
STRONG = 11.5


def _duration_points(want: Want, c: Candidate, max_duration_s: int, reasons: list[str]) -> float:
    pts = 0.0
    if want.duration_s and c.duration_s:
        diff = abs(want.duration_s - c.duration_s)
        if diff <= 2:
            pts += 3.0
            reasons.append("duration<=2s")
        elif diff <= 6:
            pts += 1.5
            reasons.append("duration<=6s")
        elif diff > 15:
            pts -= 6.0
            reasons.append(f"duration off by {diff}s")
        else:
            pts -= 1.0
    # An upload longer than any song is a loop or a full album. When the length of the song is known the comparison
    # above already says so (off by more than 15 s), and a 25-minute song must not be refused for being long.
    if c.duration_s and c.duration_s > max_duration_s and not want.duration_s:
        pts -= 10.0
        reasons.append("too long")
    return pts


def _contains(name: str, text: str) -> bool:
    """Whether a normalised [name] is in a normalised [text]. A short dense-script name (see `textnorm.is_dense_short`) is only found as a WHOLE WORD: it is compared for equality everywhere
    else, and a substring would let two different short names share a character (B-136: "嵐" in "嵐 Fan Channel" was an artist match worth 2.0)."""
    if not name:
        return False
    return name in text.split() if is_dense_short(name) else name in text


#: From this length on, an upload that is the wanted length to the second counts as the same recording whatever else its title says (a recitation, a mix, a long set).
LONG_CONTENT_S = 1200


def _long_and_same_length(want: Want, c: Candidate) -> bool:
    return bool(
        want.duration_s and c.duration_s and want.duration_s >= LONG_CONTENT_S and abs(want.duration_s - c.duration_s) <= 2
    )


def _words_alike(a: str, b: str) -> float:
    """How alike two normalised titles are WORD BY WORD, in order: 0 unless they have the same number of words, then the weakest word's `ratio`. One song spelled two ways keeps its words
    ("kifak inta" and "kifak enta" 0.75); another song does not ("hurt" and "hurt me", "ny state of mind" and "ny state of mind pt 3": an extra word is another title). The character
    similarity of whole strings (`difflib` over the full title) let a short title plus a short word through at 0.73 and two unrelated transliterated titles at 0.61."""
    xs, ys = a.split(), b.split()
    if not xs or not ys or len(xs) != len(ys):
        return 0.0
    return min(ratio(x, y) for x, y in zip(xs, ys, strict=True))


def _own_channel_same_length(want: Want, c: Candidate) -> bool:
    """The upload is on the artist's own (or an auto-generated Topic) channel and is the wanted length to the second: the evidence a title written TWICE may rest on."""
    channel = norm_artist(c.channel)
    own = c.is_topic or channel.endswith("topic") or ratio(norm_artist(want.artist), channel) >= 0.9
    return own and bool(want.duration_s and c.duration_s and abs(want.duration_s - c.duration_s) <= 2)


def _only_another_script(rest: str, wt: str) -> bool:
    """Every word left of the upload's title (digits aside) is written in another script than the wanted title: the title said twice, as Arabic artists' own channels write it
    (`Wael Kfoury - Layel W Raad | وائل كفوري - ليل و رعد`). A word of the SAME script left over is another title (`Hurt Me`)."""
    words = [w for w in rest.split() if not w.isdigit()]
    return bool(words) and all(non_latin(w) != non_latin(wt) for w in words)


def plain_title_similarity(want: Want, c: Candidate) -> float:
    """How like the wanted title an upload's title is (0 to 1), as the plain path reads it (N-44, B-136): the titles alike word by word, or alike once the artist's name is taken out
    (\"Radiohead - Creep\"), or the same letters with the spaces and dots moved (\"N.Y.\" and \"NY\", at 0.9 or more), or the wanted title IN the upload's title **with nothing else of the
    song left** (after the title and the artist's name are taken out no word remains), or, for long content, the same length to the second whatever else the title says."""
    wt, ct = norm_title(want.title), norm_title(c.title)
    wa = norm_artist(want.artist)
    bare = ct.replace(wa, " ").strip() if wa else ct
    sim = max(_words_alike(wt, ct), _words_alike(wt, bare))
    squashed_want, squashed_bare = wt.replace(" ", ""), bare.replace(" ", "")
    if squashed_want and ratio(squashed_want, squashed_bare) >= 0.9:
        sim = max(sim, 0.9)
    if wt and wt in ct:
        rest = ct.replace(wt, " ", 1)
        if wa:
            rest = rest.replace(wa, " ")
        # What else the upload's title says is the evidence that it is ANOTHER song ("Hurt Me"), except for long content: an upload of hours that is the wanted length to the second is its
        # own fingerprint, and such titles are long and descriptive on purpose (a recitation: "Surah Al-Baqarah Mishary Rashed Alafasy 1422H ...", the recorded case).
        # A title written twice (Latin and Arabic) is the same song when the rest is ALL in the other script and the upload is on the artist's own channel at the wanted length.
        if (
            not rest.split()
            or _long_and_same_length(want, c)
            or (_only_another_script(rest, wt) and _own_channel_same_length(want, c))
        ):
            sim = max(sim, 0.9)
    return sim


def plain_title_ok(want: Want, c: Candidate) -> bool:
    """The upload's title is the wanted song's: a wrong song is worse than \"not found\"."""
    return plain_title_similarity(want, c) >= PLAIN_MIN_TITLE_SIMILARITY


def score_plain(want: Want, c: Candidate, max_duration_s: int = 2700) -> Scored:
    """Title / channel / duration only (the fallback source)."""
    reasons: list[str] = []
    s = 0.0
    ct = norm_title(c.title)
    wa, ca = norm_artist(want.artist), norm_artist(c.channel)

    title_sim = plain_title_similarity(want, c)
    s += 5.0 * title_sim
    reasons.append(f"title={title_sim:.2f}")

    artist_sim = ratio(wa, ca)
    if c.is_topic or ca.endswith("topic"):
        s += 2.5
        reasons.append("topic")
    elif artist_sim >= 0.9:
        s += 2.5  # the artist's own channel
        reasons.append("artist channel")
    if artist_sim >= 0.8 or _contains(wa, ct) or _contains(wa, ca):
        s += 2.0
        reasons.append("artist")

    s += _duration_points(want, c, max_duration_s, reasons)
    asked = mentions_version(f"{want.title} {want.album or ''}")
    extra = mentions_version(c.title) - asked
    if extra:
        s -= 4.0
        reasons.append("version: " + ",".join(sorted(extra)))
    return Scored(c, round(s, 2), tuple(reasons))


def score_structured(want: Want, c: Candidate, max_duration_s: int = 2700) -> Scored:
    """With the upload's declared track / artists / album."""
    reasons: list[str] = []
    s = 0.0
    wt = norm_title(want.title)
    ct = norm_title(c.track or c.title)
    title_sim = ratio(wt, ct)
    s += 5.0 * title_sim
    reasons.append(f"track={title_sim:.2f}")

    wa = norm_artist(want.artist)
    artists = [norm_artist(a) for a in c.artists if a] or [norm_artist(c.channel)]
    if any(ratio(wa, a) >= 0.85 or (wa and wa in a) for a in artists):
        s += 3.0
        reasons.append("artist")
    if want.album and c.album:
        album_sim = ratio(norm_title(want.album), norm_title(c.album))
        if album_sim >= 0.8:
            s += 2.0
            reasons.append("album")
    if c.is_topic or norm_artist(c.channel) == wa:
        s += 1.0
        reasons.append("official channel")

    s += _duration_points(want, c, max_duration_s, reasons)
    asked = mentions_version(f"{want.title} {want.album or ''}")
    shown = mentions_version(f"{c.title} {c.track or ''} {c.album or ''}")
    extra = shown - asked
    if extra:
        s -= 4.0
        reasons.append("version: " + ",".join(sorted(extra)))
    return Scored(c, round(s, 2), tuple(reasons))


def score(want: Want, c: Candidate, max_duration_s: int = 2700) -> Scored:
    return (score_structured if c.structured else score_plain)(want, c, max_duration_s)


def best(want: Want, candidates: list[Candidate], max_duration_s: int = 2700) -> Scored | None:
    scored = sorted(
        (score(want, c, max_duration_s) for c in candidates if c.structured or plain_title_ok(want, c)),
        key=lambda x: x.score,
        reverse=True,
    )
    if not scored or scored[0].score < ACCEPT:
        return None
    return scored[0]


# ----------------------------------------------------------------- yt-dlp


@dataclass(frozen=True)
class Resolver(Protocol):
    def resolve(self, want: Want) -> Scored | None: ...
