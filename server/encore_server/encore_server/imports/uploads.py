"""Who is the artist of an imported YouTube upload (N-26, audit B-125; the design is `docs/tasks/P2-songs-as-references.md`, section "N-26").

**The channel is the uploader, and the uploader is evidence, not the artist.** YouTube Music lists a song's artists, and for an upload by a person or an
organisation (`MUSIC_VIDEO_TYPE_UGC`) the "artist" it lists is the uploading channel: "Tinariwen - Full Performance (Live on KEXP)" is credited to KEXP. The
importer used to take that name as the artist, so a broadcaster, a label or a stranger's account became an artist of the library, with a folder, a page and a
picture look-up. This module is the ONE door every reader goes through (YouTube Music's playlist answer, yt-dlp's flat listing; later the file import and the
catalogue search) and says, for each upload, **who the artist is and how that was decided** (the `basis`):

* `declared`: the source says so: a song of the catalogue (YouTube's own "Topic" audio), a Spotify or file description, an official music video's credit.
* `title`: the title names the performer ("Artist - Song"; or "<Series> Opening | Song by Artist", the one shape of context that is read, with a pipe and
  one "by"). The channel only breaks the tie between the two sides, and only when it is a WHOLE NAME of a side (never a substring: "kexp" is inside "(Live on KEXP)").
* `channel`: nothing names a performer, so the uploader stays as the visible artist, exactly what YouTube Music shows for the upload, flagged. This is the one
  named stop-gap (U1 of the design): a personal account whose title names nobody looks the same whether it is the band's own or a fan's. Removal trigger: the
  catalogue naming the artist of a song by its title (N-28).
* `unknown`: nothing names anybody and there is no uploader (an official video with an empty credit). The importer files such a song under
  `textnorm.UNKNOWN_ARTIST`, a placeholder that identifies nothing (`textnorm.is_unknown_artist`, `refs.find`).

Titles are read here and nowhere else. Brackets never decide who the artist is: a bracket that names a venue or a show ("(Live on KEXP)") stays in the song
title, because it says which recording this is (`clean_title`, unchanged).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ..artist_basis import CHANNEL, DECLARED, TITLE, UNKNOWN
from ..textnorm import artist_parts, fold, mentions_version
from ..textnorm import words as fold_words

# --------------------------------------------------------------------------- reading text apart

#: A bracket group that only says what kind of upload this is.
_NOISE_WORDS = (
    r"official|video|audio|lyrics?|visuali[sz]er|hd|4k|performance|clip|officiel|oficial|music|"
    r"with|explicit|topic|version|animated|mv|m/v"
)
_NOISE_GROUP = re.compile(rf"\s*[\(\[]\s*(?:(?:{_NOISE_WORDS})\b[\s,/&+-]*)+[\)\]]", re.IGNORECASE)
_PIPE_NOISE = re.compile(rf"\s*\|\s*(?:(?:{_NOISE_WORDS})\b[\s,/&+-]*)+$", re.IGNORECASE)
#: A side that is made only of such words ("Official Video", "Lyrics"): a description, not a name.
_ONLY_NOISE = re.compile(rf"(?:(?:{_NOISE_WORDS})\b[\s,/&+-]*)+", re.IGNORECASE)
_FEAT_GROUP = re.compile(r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s[^\)\]]*[\)\]]", re.IGNORECASE)
_FEAT_TAIL = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s.*$", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
_TOPIC = re.compile(r"\s*-\s*Topic$", re.IGNORECASE)
_VEVO = re.compile(r"\s*VEVO$", re.IGNORECASE)
#: The endings a channel puts on its own name; they are not part of the name when the channel is compared with a side of a title.
_CHANNEL_ENDING = re.compile(r"(?:\s*-\s*topic|\s*vevo|\s+official)$", re.IGNORECASE)
_FIRST_ARTIST = re.compile(r"\s*(?:,|&|\bx\b|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b|\band\b)\s*", re.IGNORECASE)
#: A separator between an artist and a song: a hyphen, any dash, the minus sign, the middle dot or the bullet, with spaces on both sides
#: ("Jay-Z" and "col·legi" have none).
_SEPARATOR = re.compile(r"\s+[-‐-―−·•]\s+")
_OPEN, _CLOSE = "([{", ")]}"
#: Where a series label ends: a PIPE only (a section break, which is NOT a separator between an artist and a song: "Chopin - Nocturne Op. 9 No. 2 | Piano"). A
#: dash is not read: before a dash a name ending in Opening or Ending is a band or a show ("Happy Ending - Born by the River", "Grand Opening - Nothing by
#: Chance"), and the rule filed those under "the River" and "Chance" (the corpus rows of slice 4). Used only by `_series_credit`.
_SERIES_BREAK = re.compile(r"\s*\|\s*")
#: A series label ends in the word Opening or Ending, with a number after it: "DAN DA DAN Opening", "Naruto Shippuden Ending 5". The abbreviations OP and ED
#: are NOT read: they are what broke "Chopin - Nocturne Op. 9 No. 2" and "Ed Sheeran - Stand By Me" when the shape was first tried as a word list.
_SERIES_LABEL = re.compile(r"\b(?:opening|ending)(?:\s*\d{1,2})?$", re.IGNORECASE)
_BY = re.compile(r"\s+by\s+", re.IGNORECASE)
#: What a credited artist must not hold once the noise is cleaned away: a bracket, a pipe or a quote means the credit is not a plain name.
_NOT_A_NAME = re.compile(r"[|()\[\]{}\"“”„«»「」『』]")


def clean_title(raw: str) -> str:
    """`The Type (Official Music Video) ft. Somebody` -> `The Type`. A bracket that is part of the song
    (`(Live at Wembley)`, `(2008 Remaster)`) stays: it is a different recording."""
    text = _NOISE_GROUP.sub("", raw)
    text = _PIPE_NOISE.sub("", text)
    text = _FEAT_GROUP.sub("", text)
    text = _FEAT_TAIL.sub("", text)
    return _SPACES.sub(" ", text).strip()


def _first_artist(text: str) -> str:
    return _FIRST_ARTIST.split(text.strip(), maxsplit=1)[0].strip()


def is_topic(channel: str) -> bool:
    """YouTube's own "Artist - Topic" channel: its uploads are the catalogue's audio of a song, and its name is the artist."""
    return _TOPIC.search((channel or "").strip()) is not None


def plain_name(name: str) -> str:
    """An artist as a person says it: without the "- Topic" and "VEVO" endings YouTube adds to a channel's name."""
    return _VEVO.sub("", _TOPIC.sub("", str(name or ""))).strip()


def _name_key(text: str) -> str:
    """A name as its letters and digits, in any alphabet, joined: the SHARED fold of the server (`textnorm.fold`, P2-25: case, width and compatibility forms, the
    decorating accents and vowel marks, `ø ł ı ß` and the Arabic and Persian variants) and then everything that is not a letter or a digit dropped. (This
    module kept a fold of its own for the length of N-26, because the server's was ASCII only; its comment promised the replacement in the same change.)"""
    return "".join(fold_words(fold(text or "")))


def _channel_key(channel: str) -> str:
    name = (channel or "").strip()
    previous = None
    while previous != name:
        previous, name = name, _CHANNEL_ENDING.sub("", name).strip()
    return _name_key(name)


def _words(text: str) -> str:
    """The words of a text in any alphabet, one space between them (the shared fold: "Mötley" stays one word, a Hindi word keeps its vowel signs, every other
    mark is a gap)."""
    return " ".join(fold_words(fold(text or "")))


def _mentions(name: str, text: str) -> bool:
    """Whether [text] says [name] anywhere, as whole words (never inside another word: "kexp" is not in "kexpress")."""
    words = _words(name)
    return bool(words) and f" {words} " in f" {_words(text)} "


def _names(side: str) -> set[str]:
    """The names a side of a title holds: the whole side, and each name of a credit list ("Peso Pluma, Anitta")."""
    cleaned = clean_title(side)
    keys = {_name_key(cleaned)} | {_name_key(part) for part in artist_parts(cleaned)}
    keys.discard("")
    return keys


def _split(raw_title: str, separator: re.Pattern[str] = _SEPARATOR) -> tuple[str, str] | None:
    """The two sides of the first separator that is outside every bracket, as written; `None` when the title has none."""
    depth = 0
    index = 0
    while index < len(raw_title):
        char = raw_title[index]
        if char in _OPEN:
            depth += 1
        elif char in _CLOSE:
            depth = max(0, depth - 1)
        elif depth == 0:
            found = separator.match(raw_title, index)
            if found is not None:
                return raw_title[:index].strip(), raw_title[found.end() :].strip()
        index += 1
    return None


def _series_credit(raw_title: str, channel: str) -> tuple[str, str] | None:
    """`DAN DA DAN Opening | Otonoke by Creepy Nuts` -> `("Creepy Nuts", "Otonoke")`: a series label that ends in Opening or Ending, a pipe, then
    `<Song> by <Artist>`. `None` unless EVERY part is there, so that nothing else changes (each guard is a row of the negative corpus):
    no label word at the end of the first segment (a bare "by" is not a shape: "Stand By Me" is a song), or a separator inside that segment (the title already
    reads `Artist - Song`); a label that is the uploader's own name ("Happy Ending |
    Born by the River" on the channel Happy Ending is a band, not a series); no credit, or MORE THAN ONE " by " in it ("Stand By Me by Ben E. King" and "Song by
    Death by Stereo" cannot be told apart by the string, so nobody is named); a credit that is not a clean name (a bracket, a pipe or a quote left in it: a
    half-clean name would file the song under a wrong, trusted artist, which is worse than the uploader flagged `channel`). A dash after the label is not read
    (see `_SERIES_BREAK`). The series is context and is dropped from the song: "Otonoke" is what a catalogue can match."""
    sides = _split(raw_title, _SERIES_BREAK)
    if sides is None:
        return None
    if _split(sides[0]) is not None:
        return None  # a separator before the pipe: the title already reads `Artist - Song` ("Mozart - Opening | Overture by Karajan")
    label = clean_title(sides[0])
    if _SERIES_LABEL.search(label) is None:
        return None
    uploader = _channel_key(channel)
    if uploader and uploader == _name_key(label):
        return None
    credits = list(_BY.finditer(sides[1]))
    if len(credits) != 1:
        return None
    song = clean_title(sides[1][: credits[0].start()])
    artist = clean_title(sides[1][credits[0].end() :])
    if not song or not artist or _NOT_A_NAME.search(artist):
        return None
    return artist, song


def _describes_only(side: str) -> bool:
    """Whether a side says nothing but what kind of upload this is ("Official Video"): the dash in front of it is decoration."""
    text = clean_title(side)
    return not text or _ONLY_NOISE.fullmatch(text) is not None


def _real_split(raw_title: str) -> tuple[str, str] | None:
    """The sides of a title that names an artist next to a song: a separator whose two sides both hold something and whose right side is not a
    description."""
    sides = _split(raw_title)
    if sides is None or not clean_title(sides[0]) or _describes_only(sides[1]):
        return None
    return sides


def _without_decoration(raw_title: str) -> str:
    """The song of a title with no artist in it: a trailing "- Official Video" is dropped, brackets are cleaned."""
    sides = _split(raw_title)
    if sides is not None and clean_title(sides[0]) and _describes_only(sides[1]):
        return clean_title(sides[0])
    return clean_title(raw_title)


# --------------------------------------------------------------------------- the result


@dataclass(frozen=True)
class Reading:
    """The artists and the song of an upload, and how the artist was decided (see the module text)."""

    artists: tuple[str, ...]
    title: str
    basis: str
    #: The channel that uploaded it, when the song came from an upload (a fact kept for a later, better reading); `None` for a song of the catalogue.
    uploader: str | None = None

    @property
    def artist(self) -> str:
        return self.artists[0] if self.artists else ""


def read_declared(raw_title: str, artists: Sequence[str]) -> Reading:
    """A song whose artists the source declares (the catalogue's own audio, a removed catalogue entry): taken as they are."""
    names = tuple(name for name in (plain_name(a) for a in artists) if name)
    return Reading(names, clean_title(raw_title), DECLARED if names else UNKNOWN)


def read_upload(raw_title: str, uploader: str) -> Reading:
    """The artist and the song of a video somebody uploaded: `Reading(("Arcangel",), "FN8", "title")` from `Arcangel - FN8 ( Video Lyric )`.

    In this order: a "- Topic" channel is the artist; a series credit (`<Series> Opening | <Song> by <Artist>`) names its artist; a title with a separator is
    `Artist - Song`, unless the channel is a whole name of the RIGHT side only (`Song - Artist`); with no separator the uploader stays, flagged `channel`; with
    no uploader either, nobody is named."""
    channel = (uploader or "").strip()
    if is_topic(channel):
        return Reading((plain_name(channel),), clean_title(raw_title), DECLARED)
    credit = _series_credit(raw_title, channel)
    if credit is not None:
        return Reading((credit[0],), credit[1], TITLE, channel or None)
    sides = _real_split(raw_title)
    if sides is None:
        name = _VEVO.sub("", channel).strip()
        song = _without_decoration(raw_title)
        return Reading((name,), song, CHANNEL, channel) if name else Reading((), song, UNKNOWN)
    left, right = sides
    key = _channel_key(channel)
    if key and key in _names(right) and key not in _names(left):
        # `Song - Artist`. When the right side IS the channel's name and nothing else ("... - ARTE Concert"), the title only repeats the uploader's name,
        # and a broadcaster and a performer look the same here: the artist is reached through the uploader alone, so it is flagged `channel`.
        alone = _name_key(clean_title(right)) == key
        artist = clean_title(right) if alone else _first_artist(clean_title(right))
        return Reading((artist,), clean_title(left), CHANNEL if alone else TITLE, channel)
    return Reading((clean_title(left),), clean_title(right), TITLE, channel or None)


def read_official_video(raw_title: str, credited: Sequence[str]) -> Reading:
    """An official music video (`MUSIC_VIDEO_TYPE_OMV`): YouTube Music credits it to the band in almost every case, so the credit is taken, unless the
    title names a DIFFERENT performer before a separator ("Band - Song" under a label's credit: the band is read from the title). A title with no
    separator keeps the credit (an official video credited to a label with no dash in its title is unknowable from YouTube alone: N-28). A title that says the
    credited name anywhere ("... | ItsKlyo" on a fan's account typed as an official video) does not name a different performer, so the credit stays. A side
    that only describes the upload ("Song - Official Video") or the version ("Song - Live in Moscow") names a song, not a performer, so the credit stays."""
    names = tuple(name for name in (plain_name(a) for a in credited) if name)
    if not names:
        return read_upload(raw_title, "")
    sides = _real_split(raw_title)
    if sides is not None:
        left, right = sides
        named = _names(left) | _names(right)
        confirmed = {_name_key(name) for name in names} & named or any(_mentions(name, raw_title) for name in names)
        if not confirmed and not mentions_version(right):
            return Reading((clean_title(left),), clean_title(right), TITLE)
    return Reading(names, clean_title(raw_title), DECLARED)


def split_artist_title(raw_title: str, channel: str) -> tuple[str, str]:
    """The artist and the song of a video, without the basis: `("Arcangel", "FN8")` from `Arcangel - FN8 ( Video Lyric )` on the channel "Arcangel"."""
    reading = read_upload(raw_title, channel)
    return reading.artist, reading.title
