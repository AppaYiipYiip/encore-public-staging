"""Text normalisation and similarity used to match what a person asked for
against what YouTube returned and against what the library already holds.

Pure functions, no I/O: everything here is unit-tested.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

# Words that describe the *kind* of upload, not the song.
_NOISE = re.compile(
    r"\b(official|video|audio|lyrics?|lyric video|hd|hq|4k|remaster(?:ed)?|"
    r"explicit|visuali[sz]er|music video|full album|topic)\b",
    re.IGNORECASE,
)
_BRACKETS = re.compile(r"\(.*?\)|\[.*?\]|\{.*?\}")
_FEAT = re.compile(r"\b(feat|ft|featuring)\b.*", re.IGNORECASE)

# Versions that are not what was asked for unless the request says so.
VERSION_WORDS = (
    "live",
    "cover",
    "karaoke",
    "instrumental",
    "remix",
    "sped up",
    "slowed",
    "reverb",
    "nightcore",
    "8d",
    "acoustic",
    "demo",
    "reaction",
    "tutorial",
    "lesson",
    "medley",
    "mashup",
    "bass boosted",
)


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def norm_title(text: str) -> str:
    """`Song (Remastered 2011) [Official Audio]` -> `song`."""
    t = _BRACKETS.sub(" ", ascii_fold(text))
    t = _FEAT.sub(" ", t)
    t = _NOISE.sub(" ", t)
    t = re.sub(r"\s+-\s+(remaster(ed)?|single|radio edit|\d{4}).*", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


#: Words in a bracket (or after a dash) that say nothing about *which recording* it is.
_SIGNATURE_NOISE = frozenset(
    [
        "official",
        "video",
        "audio",
        "lyrics",
        "lyric",
        "hd",
        "hq",
        "4k",
        "remaster",
        "remastered",
        "explicit",
        "clean",
        "visualizer",
        "visualiser",
        "music",
        "full",
        "album",
        "topic",
        "version",
        "edition",
        "edit",
        "radio",
        "single",
        "mono",
        "stereo",
        "deluxe",
        "expanded",
        "bonus",
        "track",
        "anniversary",
        "the",
        "a",
        "an",
        "of",
        "from",
    ]
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_DASH_VERSION = re.compile(r"\s+-\s+(.*)$")


def version_signature(text: str) -> frozenset[str]:
    """What a title says about *which recording* it is: the words of its brackets and of what follows a dash, without the noise
    (featured artists, remaster years, "explicit", "radio edit"). `Fade Into You` is empty, `Fade Into You (The Avener Rework)` is
    {avener, rework}, `Song - Live at Wembley` is {live, wembley}, `Song (2013 Remaster) (feat. X)` is empty.

    Two titles with the same words but different signatures are different recordings: the library's rework is not the song that was
    asked for (`norm_title` alone treats them as one)."""
    folded = ascii_fold(text)
    pieces = [g for group in re.findall(r"\((.*?)\)|\[(.*?)\]|\{(.*?)\}", folded) for g in group if g]
    outside = re.sub(r"\(.*?\)|\[.*?\]|\{.*?\}", " ", folded)
    dash = _DASH_VERSION.search(outside)
    if dash:
        pieces.append(dash.group(1))
    words: set[str] = set()
    for piece in pieces:
        piece = _FEAT.sub(" ", piece)
        piece = _YEAR.sub(" ", piece)
        for word in re.findall(r"[a-z0-9]+", piece.replace("'", "")):
            if word not in _SIGNATURE_NOISE:
                words.add(word)
    return frozenset(w for w in words if w)


def norm_artist(text: str) -> str:
    t = re.sub(r"\s*-\s*topic$", "", text or "", flags=re.IGNORECASE)
    t = re.sub(r"(?i)vevo$|official$", "", ascii_fold(t))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


#: What a song nobody names is filed under: the folder the keeper makes for an artist it cannot name, and the artist the importer gives a song whose
#: source lists none (N-26). **It is a placeholder, not a name**: see [is_unknown_artist].
UNKNOWN_ARTIST = "Unknown Artist"


def is_unknown_artist(name: str) -> bool:
    """Whether [name] says "nobody": the placeholder in any case, with or without the brackets the music server puts around it (`[Unknown Artist]`).
    **A name that cannot be told from "nobody" identifies nothing** (artist + title + length of two different nameless songs is the same string), so a
    ref whose artist is this is found by its ids and never by its name (`refs.find`), and no catalogue is asked about it (`artist_finder`). That
    includes a real artist who is literally called "Unknown Artist": the one corner this costs (written down in `docs/19` section 3 and tested)."""
    return norm_artist(name) == norm_artist(UNKNOWN_ARTIST)


#: Where a combined artist string ("Daft Punk feat. Pharrell Williams", "Fat Joe, Lil Wayne") is cut into names. The YouTube matcher and the music server's
#: matcher use this one definition.
ARTIST_SPLIT = re.compile(r"\s*(?:,|&|\+|\bfeat\.?\s|\bft\.?\s|\bfeaturing\b|\bx\b|\bwith\b)\s*", re.IGNORECASE)


def artist_parts(text: str) -> list[str]:
    """The names a combined artist string is made of ("A, B & C" is "A", "B", "C"); the string itself is not one of them unless it holds only one name."""
    return [part for part in ARTIST_SPLIT.split(text) if part.strip()]


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def mentions_version(text: str) -> set[str]:
    """Which of [VERSION_WORDS] appear in [text] (as whole words)."""
    folded = ascii_fold(text)
    return {w for w in VERSION_WORDS if re.search(rf"\b{re.escape(w)}\b", folded)}


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# The fold of every alphabet (P2-25 slice 1; the design is `docs/tasks/P2-songs-as-references.md`, section P2-25, parts 2 to 4).
#
# **Nothing above this line calls it yet.** The five functions above still fold to ASCII and every caller still uses them: slices 2 and 3 move the
# call sites together with the stored keys (new keys against stored `||` keys would make a duplicate ref for every non-Latin song described again).
# What is here is the new core, defined once, tested against the fixture the phone's Dart twin reads too (`app/test/fixtures/text/fold-cases.json`),
# and `survives_fold_whole`, the rule N-34 imports.

#: The Unicode version the fold is pinned to: the one Python 3.12 ships (`unicodedata.unidata_version`, run on 3.12.13), which is what CI
#: (`server.yml`) and the image (`python:3.12-slim`) run. A newer Python (3.13 has 15.1.0, which only ADDS 627 code points, run) gives the same fold;
#: a version that changes any result fails the corpus test of `tests/test_textnorm.py` with "bump `TEXTNORM_REVISION`". `tools/gen_text_fold_table.py`
#: refuses to write or to check unless the running Python has exactly this version, and writes it into the phone's table and the fixture.
UNICODE_VERSION = "15.0.0"

#: Which fold made the stored keys (`song_ref.norm_key`): 0 is the ASCII fold of the five functions above, 1 is this one. A change to ANY result of
#: `fold` (a table row, a rule, a Unicode version) raises it by one; slice 3 rewrites the stored keys at start-up when `setting.textnorm_revision`
#: is lower, so a base-image bump can never change a stored key silently.
TEXTNORM_REVISION = 1

#: The marks that DECORATE a letter and are removed (an allow-list: what this table does not know stays, so a Hindi phrase of two words keeps its vowel signs and stays two words, and `が` is
#: not `か`): the combining diacritics, the Arabic harakat and Quranic marks, the Hebrew points. Inclusive ranges of code points.
DECORATING_MARKS: tuple[tuple[int, int], ...] = (
    (0x0300, 0x036F),
    (0x1AB0, 0x1AFF),
    (0x1DC0, 0x1DFF),
    (0x20D0, 0x20FF),
    (0xFE20, 0xFE2F),
    (0x064B, 0x065F),
    (0x0670, 0x0670),
    (0x06D6, 0x06DC),
    (0x06DF, 0x06E4),
    (0x06E7, 0x06E8),
    (0x06EA, 0x06ED),
    (0x08D3, 0x08E1),
    (0x08E3, 0x08FF),
    (0x0591, 0x05BD),
    (0x05BF, 0x05BF),
    (0x05C1, 0x05C2),
    (0x05C4, 0x05C5),
    (0x05C7, 0x05C7),
)

#: Letters that are NOT an accent on another letter although their decomposition says so: they stay (`мой` and `мои` are two words, ruling D6; the
#: hamza seats of Arabic stay apart, ruling D1). Lower case, after the case fold.
PROTECTED_LETTERS = "йїўؤئ"

#: Heh with yeh above decomposes into a letter (`ە`) that is not heh once its hamza mark is removed, so it is mapped BEFORE the marks go.
_BEFORE_MARKS = {0x06C0: "ه"}

#: Letters with no decomposition that a reader of the language writes as another letter, and the tatweel (removed on purpose). Lower case. Latin: the
#: letters the old fold dropped (and the phone's own `_fold` table of `text_match.dart` plus `ı ħ ŧ`); Arabic and Persian: cross-checked against the
#: Lucene filters (design part 3, "Cross-check", ruling D1); the Cyrillic `ё` needs no row (it is `е` plus a diaeresis, a decorating mark).
FOLDED_LETTERS: dict[int, str] = {
    0x00F8: "o",  # ø
    0x0142: "l",  # ł
    0x0111: "d",  # đ
    0x00F0: "d",  # ð
    0x00FE: "th",  # þ
    0x00E6: "ae",  # æ
    0x0153: "oe",  # œ
    0x0131: "i",  # ı (ruling D5)
    0x0127: "h",  # ħ
    0x0167: "t",  # ŧ
    0x0671: "ا",  # ٱ alef wasla is alef
    0x0649: "ي",  # ى alef maksura is yeh
    0x06CC: "ي",  # ی Farsi yeh is yeh
    0x06D2: "ي",  # ے yeh barree is yeh
    0x06A9: "ك",  # ک keheh is kaf
    0x0629: "ه",  # ة teh marbuta is heh (lossy on purpose, ruling D1)
    0x06C1: "ه",  # ہ heh goal is heh
    0x0640: "",  # ـ the tatweel is a stretch, not a letter
}

_ZWNJ = "\u200c"  # the Persian half-space: a SPACE (ruling D7); every other format character (Cf) is removed with no gap
_MARKS_OUT = {cp: None for lo, hi in DECORATING_MARKS for cp in range(lo, hi + 1)}
_AFTER_MARKS = str.maketrans(FOLDED_LETTERS)
_PROTECTED = re.compile(f"([{PROTECTED_LETTERS}])")
_ASCII_WORDS = re.compile(r"[A-Za-z0-9]+")


def _remove_marks(text: str) -> str:
    """NFD, remove the allow-listed marks, NFC; the protected letters are cut out first and put back whole."""
    parts = _PROTECTED.split(text)
    for i in range(0, len(parts), 2):
        part = parts[i]
        if part:
            parts[i] = unicodedata.normalize("NFC", unicodedata.normalize("NFD", part).translate(_MARKS_OUT))
    return "".join(parts)


def _fold_general(text: str) -> str:
    """The character stage for any text (`fold` takes a shortcut for ASCII, and the tests prove the two agree). The order is the design's six steps
    with one correction: the invisible characters go FIRST, so that a format character between a base and its mark (`か` + joiner + the voiced mark)
    cannot stop them composing (run: the other order made `fold` not idempotent)."""
    # 6. invisible characters
    s = "".join(" " if ch == _ZWNJ else ch for ch in text if ch == _ZWNJ or unicodedata.category(ch) != "Cf")
    # 1. NFKC (not NFKD: it would split Hangul and the voiced kana), 2. case fold
    s = unicodedata.normalize("NFKC", s).casefold()
    # 3. the decorating marks (an allow-list)
    s = _remove_marks(s.translate(_BEFORE_MARKS))
    # 4. letters with no decomposition
    s = s.translate(_AFTER_MARKS)
    # 5. every decimal digit of any script is its ASCII digit
    if not s.isascii():
        s = "".join(str(unicodedata.decimal(ch)) if ch > "\x7f" and unicodedata.category(ch) == "Nd" else ch for ch in s)
    return s


def fold(text: str) -> str:
    """The character stage of the one fold: NFKC, case fold, the decorating marks removed, `ø ł ı ß ...` and the Arabic and Persian variants folded,
    every digit ASCII, invisible characters gone. **It keeps punctuation and spaces** (the typo rule of N-23b needs `$ @ !`); `words` cuts it.
    Idempotent. ASCII is just lower-cased, so a key made of ASCII letters, digits and punctuation does not change."""
    if text.isascii():
        return text.lower()
    return _fold_general(text)


def words(folded: str) -> list[str]:
    """The words of a folded text: runs of letters, digits and kept marks (a Hindi word with its vowel signs is one word); everything else is a gap. A run made only of marks
    (a variation selector after an emoji) is not a word. A Chinese or Japanese title is ONE word (no n-grams in a key, ruling D3)."""
    if folded.isascii():
        return _ASCII_WORDS.findall(folded)
    out: list[str] = []
    run: list[str] = []
    readable = False
    for ch in folded:
        kind = unicodedata.category(ch)[0]
        if kind == "L" or kind == "N":
            run.append(ch)
            readable = True
        elif kind == "M":
            run.append(ch)
        else:
            if run and readable:
                out.append("".join(run))
            run, readable = [], False
    if run and readable:
        out.append("".join(run))
    return out


def key_text(text: str, original: str | None = None) -> str:
    """The words of [text] joined by a space, and **never empty when there is something to read**: when [text] has no word (a song called "Audio"
    whose noise word the layer above removed) the words of [original] are used; when there are none (a title that is only punctuation, an emoji or
    decoration) the case-folded original is used as it is, with only its width and compatibility forms (NFKC) and its spaces normalised, so that
    `???` and `!!!` are two songs and so are two titles made of nothing but different marks. An empty or blank original gives an empty key, which is
    correct."""
    key = " ".join(words(fold(text)))
    if key:
        return key
    source = text if original is None else original
    key = " ".join(words(fold(source)))
    return key or " ".join(unicodedata.normalize("NFKC", source).casefold().split())


def survives_fold_whole(text: str) -> bool:
    """Can [text] be compared by key without losing what tells it apart from another name? **Era 0** (every server until slice 2 merges; what N-34
    calls): decided against the CURRENT ASCII fold, so the text holds at least one letter or digit and, after NFKD, every letter and digit that is not
    a combining mark is ASCII. True for `Björk`, `Beyoncé`, `Ke$ha`, `ＡＢＣ`, `Don’t Stop`; false for `فيروز`, `Кино`, `Habibi يا نور`, `Łukasz`, `Straße`,
    `Şımarık`, `Æon`. It guards against a WRONG match (an over-merge, a wrong stamp, a wrong move), never against a miss.

    **Slice 2 rewrites this body to `survives_fold_whole_era_1`** and the guards at the call sites (each marked `STOP-GAP(P2-25 skip-rule)`) never fire.
    The rule is defined here and described in one place, `docs/tasks/P2-songs-as-references.md` (P2-25, part 4): nobody copies it."""
    seen = False
    for ch in unicodedata.normalize("NFKD", text):
        if unicodedata.category(ch)[0] in "LN":
            if ch > "\x7f":
                return False
            seen = True
    return seen


def survives_fold_whole_era_1(text: str) -> bool:
    """Era 1: decided against the new fold, so true for every text with a letter or a digit (the tatweel is removed on purpose, so a text of
    tatweels alone has nothing left to compare and is false)."""
    return any(unicodedata.category(ch)[0] in "LN" for ch in fold(text))


def safe_path_part(text: str, fallback: str = "Unknown") -> str:
    """One file or folder name that cannot escape its parent or confuse a
    file system: no separators or control characters, no trailing dots, at
    most 120 characters."""
    t = unicodedata.normalize("NFC", text or "")
    t = re.sub(r"[\x00-\x1f\x7f]", "", t)
    t = re.sub(r'[\\/:*?"<>|]', "-", t)
    t = re.sub(r"\s+", " ", t).strip(" .")
    if t in ("", ".", ".."):
        return fallback
    return t[:120].rstrip(" .") or fallback
