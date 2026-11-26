"""Text normalisation and similarity used to match what a person asked for
against what YouTube returned and against what the library already holds.

Pure functions, no I/O: everything here is unit-tested.

**One fold for every alphabet** (P2-25, audit B-37). `fold` is the character stage (NFKC, case fold, the decorating marks removed, `ø ł ı ß` and the Arabic and
Persian variants folded, every digit ASCII); `words` cuts it into words; `key_text` is the words joined, never empty while there is something to read. The five
functions most of the server calls (`norm_title`, `norm_artist`, `version_signature`, `mentions_version` and, through them, `refs.norm_key`) are built on it and
keep the word rules of before (noise words, brackets, "feat", version words), which sit ABOVE the fold: for ASCII they give what they always gave. The design is
`docs/tasks/P2-songs-as-references.md`, section P2-25; the phone's twin is `app/lib/domain/text_fold.dart`, and `app/test/fixtures/text/fold-cases.json` is the one
fixture both read.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

# ---------------------------------------------------------------------------------------------------------------------------------------------------
# The fold of every alphabet (the design is `docs/tasks/P2-songs-as-references.md`, section P2-25, parts 2 to 4).

#: The Unicode version the fold is pinned to: the one Python 3.12 ships (`unicodedata.unidata_version`, run on 3.12.13), which is what CI
#: (`server.yml`) and the image (`python:3.12-slim`) run. A stored key is a function of the Unicode data of the Python that made it, so the server REFUSES TO START on
#: any other ([require_pinned_unicode]; there is no switch to turn that off) and so does every run of the tests: a newer Python (3.13 has 15.1.0, which only ADDS 627
#: code points, among them 622 CJK ideographs that are letters there and gaps here) would store keys the image cannot reproduce. `tools/gen_text_fold_table.py`
#: refuses to write or to check unless the running Python has exactly this version, and writes it into the phone's table and the fixture.
#: **Why a pin and not a table of our own:** the fold uses `unicodedata` as an ALGORITHM (NFKC, NFD and NFC, `category`, `decimal`, case folding), not a few look-ups,
#: so folding it into a pinned table of ours would mean carrying a copy of Unicode's normalisation and case-folding data: not feasible, and a worse copy of what Python
#: already ships. **What a Python bump costs** (and so the removal trigger of the pin; `docs/18`, "the Unicode pin"): regenerate the phone's table and the fixture with
#: the new Python, raise [TEXTNORM_REVISION] (every Host's keys are rewritten at their next start by `keyrepair`), and move the image, `server.yml`, `requires-python`
#: and this constant in ONE pull request: `tests/test_unicode_pin.py` fails on each of them moved alone.
UNICODE_VERSION = "15.0.0"

#: Which Unicode each Python the project has met ships (`unicodedata.unidata_version`, run). The image's base tag, `server.yml` and `requires-python` are checked against
#: it, so none of them can move to another Python alone; a Python that is not here must be run and added on purpose. It also names the Python that the message of the
#: refusal tells a person to use ([unicode_refusal]).
UNICODE_OF_PYTHON = {"3.12": "15.0.0", "3.13": "15.1.0"}

#: Which fold made the stored keys (`song_ref.norm_key`): 0 is the ASCII fold of the old five functions, 1 is this one. **A change to ANY result of the key**
#: (`fold`, a table row, a rule of `norm_title`, `norm_artist` or `version_signature`, the noise or version words, a Unicode version) raises it by one;
#: `keyrepair` rewrites the stored keys at start-up when `setting.textnorm_revision` is lower, so a change can never leave a stored key behind. (A stored key that is
#: not what the fold makes is also found at every later start: the keys of a rollback image, or a bump somebody forgot.)
TEXTNORM_REVISION = 1


class UnicodeVersionError(RuntimeError):
    """The Python that runs has a Unicode version the fold is not pinned to: the server does not start and the tests do not run."""


def running_unicode() -> str:
    return unicodedata.unidata_version


def unicode_refusal(running: str) -> str:
    """What a person reads when the Python is not the pinned one: which Python is needed and how to get it. One text for the server and for the tests."""
    needed = next((minor for minor, version in UNICODE_OF_PYTHON.items() if version == UNICODE_VERSION), "3.12")
    this = next((f" (that is Python {minor})" for minor, version in UNICODE_OF_PYTHON.items() if version == running), "")
    return (
        f"This Python has Unicode {running or 'unknown'}{this}, and the song keys of Encore are pinned to Unicode {UNICODE_VERSION}, which is what Python {needed} ships. "
        f"A stored key must not depend on the Python that made it, so nothing starts on another one. Python {needed} is what the server image already runs "
        f"(python:{needed}-slim): run the server from the image, or install Python {needed} (https://www.python.org/downloads/ or `uv python install {needed}`) and "
        f'run it from a virtual environment made with that Python. To move the pin on purpose, see "the Unicode pin" in docs/18-data-model-and-migration.md.'
    )


def require_pinned_unicode(running: str | None = None) -> None:
    """Raises [UnicodeVersionError] (with [unicode_refusal]) unless the Python's Unicode is exactly [UNICODE_VERSION]. Called first by `create_app` and by the server
    command, by `keyrepair.repair` and by the test run's `conftest.py`. There is deliberately no way to skip it: no argument, setting or environment variable."""
    version = running_unicode() if running is None else running
    if version != UNICODE_VERSION:
        raise UnicodeVersionError(unicode_refusal(version))


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
#: letters the old fold dropped (and the phone's own `_fold` table of `text_match.dart` plus `ı ħ ŧ`); Arabic and Persian: checked against the sources of the
#: Lucene filters, release `releases/lucene/10.3.2` (the tag object 8241bb80dc7f3ef1be6f222f40cc6cbfa9a9aa98, commit dadfd90b4401947f4d0387669dc94999fbb2c830; design part 3, "Cross-check", ruling D1, and `tests/test_textnorm.py`: every `case` of
#: `ArabicNormalizer` and `PersianNormalizer` is a row there); the Cyrillic `ё` needs no row (it is `е` plus a diaeresis, a decorating mark).
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
    correct. The key's own separator never appears inside a part (`|` becomes `¦` in the fallback), so a stored key is always `artist|title|version`."""
    key = " ".join(words(fold(text)))
    if key:
        return key
    source = text if original is None else original
    key = " ".join(words(fold(source)))
    return key or " ".join(unicodedata.normalize("NFKC", source).casefold().split()).replace("|", "\u00a6")


def survives_fold_whole(text: str) -> bool:
    """Can [text] be compared by key without losing what tells it apart from another name? The text holds at least one letter or digit AFTER the fold, which
    keeps a word character for every letter, digit and kept mark of it that the table does not remove on purpose (the decorating marks, the tatweel, the
    format characters). True for every name in any alphabet (`Björk`, `Łukasz`, `Straße`, `فيروز`, `Кино`, `夜に駆ける`, `Habibi يا نور`, `BTS`, `Ke$ha`); false
    for a text with nothing to compare (`???`, `!!!`, a lone tatweel). It guards against a WRONG match (an over-merge, a wrong stamp, a wrong move), never
    against a miss, and N-34 and every repair that moves or stamps by name call it (design part 4: the rule is described there and nowhere else).

    It was ERA 0 until P2-25 slice 2 (decided against the old ASCII fold: false for every non-Latin or extended-Latin name); `keyrepair._lost_by_old_fold` keeps
    that form frozen, because it is what tells a stored ref the old fold damaged."""
    return any(unicodedata.category(ch)[0] in "LN" for ch in fold(text))


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# The dense scripts: a short title or name is compared for EQUALITY

#: Han, Kana and Hangul: a syllable or a character carries a whole word, so at the same `ratio` they are far MORE permissive than Latin letters
#: (run: `사랑해` against `사랑이` is 0.667, above the 0.6 title bar). Inclusive ranges, written out so that no Unicode version matters.
_DENSE: tuple[tuple[int, int], ...] = (
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x3005, 0x3007),  # the Han iteration mark, the Han closing mark, the ideographic zero
    (0x3040, 0x30FF),  # Hiragana, Katakana, the prolonged sound mark
    (0x3130, 0x318F),  # Hangul compatibility Jamo
    (0x31F0, 0x31FF),  # Katakana phonetic extensions
    (0x3400, 0x4DBF),  # Han, extension A
    (0x4E00, 0x9FFF),  # Han
    (0xA960, 0xA97F),  # Hangul Jamo extended A
    (0xAC00, 0xD7FF),  # Hangul syllables and Jamo extended B
    (0xF900, 0xFAFF),  # Han compatibility
    (0x1B000, 0x1B16F),  # Kana supplement and extended
    (0x20000, 0x2FA1F),  # Han, the supplementary planes
)

#: Up to this many characters (spaces aside) a name made only of dense characters is compared for equality. A default (ruling D9): N-16 measures the rest.
DENSE_EXACT_MAX = 4


def _dense(text: str) -> bool:
    letters = [ch for ch in text if not ch.isspace()]
    return 0 < len(letters) <= DENSE_EXACT_MAX and all(any(lo <= ord(ch) <= hi for lo, hi in _DENSE) for ch in letters)


def is_dense_short(text: str) -> bool:
    """Whether a NORMALISED name is a short name in a dense script (four characters or fewer of Han, Kana or Hangul): such a name is compared for EQUALITY (see [ratio]), so it must
    never be taken for a part of a longer name either (a title "白日" is not found inside "白日の夢")."""
    return _dense(text)


def ratio(a: str, b: str) -> float:
    """How alike two normalised names are, 0 to 1. Either one empty is 0 (nothing is never like nothing). **A short name in a dense script (four characters or
    fewer of Han, Kana or Hangul) is compared for equality**: one syllable off is another word, not a typo."""
    if not a or not b:
        return 0.0
    if _dense(a) or _dense(b):
        return 1.0 if a == b else 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# The word rules above the fold (English, on purpose: the lists per language are DATA added on the evidence of N-16, ruling D12)

# Words that describe the *kind* of upload, not the song.
_NOISE = re.compile(
    r"\b(official|video|audio|lyrics?|lyric video|hd|hq|4k|remaster(?:ed)?|"
    r"explicit|visuali[sz]er|music video|full album|topic)\b",
    re.IGNORECASE,
)
#: The brackets that hold a TAG, not a title: the three ASCII pairs (the fullwidth ones are ASCII after the fold) and the black lenticular and tortoise-shell
#: pairs Japanese and Chinese uploads put their tags in (`【MV】夜に駆ける`). The corner brackets `「」 『』`, `《》` and `〈〉` QUOTE the song's own name
#: (`YOASOBI「夜に駆ける」`), so they are punctuation: removed with their content they would remove the title.
_BRACKET_PAIRS = (("(", ")"), ("[", "]"), ("{", "}"), ("\u3010", "\u3011"), ("\u3014", "\u3015"))
_BRACKETS = re.compile("|".join(f"{re.escape(o)}.*?{re.escape(c)}" for o, c in _BRACKET_PAIRS))
_BRACKET_CONTENT = re.compile("|".join(f"{re.escape(o)}(.*?){re.escape(c)}" for o, c in _BRACKET_PAIRS))
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


def norm_title(text: str) -> str:
    """`Song (Remastered 2011) [Official Audio]` -> `song`; `【MV】夜に駆ける` -> `夜に駆ける`. Empty when nothing is left (a song called "Audio"): the key's
    own fallback is [title_key]."""
    t = _BRACKETS.sub(" ", fold(text or ""))
    t = _FEAT.sub(" ", t)
    t = _NOISE.sub(" ", t)
    t = re.sub(r"\s+-\s+(remaster(ed)?|single|radio edit|\d{4}).*", " ", t)
    return " ".join(words(t))


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
#: The straight apostrophe is no gap inside a word of a version ("don't" is `dont`); the typographic one is the same character to a reader.
_APOSTROPHES = str.maketrans({"'": None, "\u2019": None})


def version_signature(text: str) -> frozenset[str]:
    """What a title says about *which recording* it is: the words of its brackets and of what follows a dash, without the noise
    (featured artists, remaster years, "explicit", "radio edit"). `Fade Into You` is empty, `Fade Into You (The Avener Rework)` is
    {avener, rework}, `Song - Live at Wembley` is {live, wembley}, `Song (2013 Remaster) (feat. X)` is empty.

    Two titles with the same words but different signatures are different recordings: the library's rework is not the song that was
    asked for (`norm_title` alone treats them as one)."""
    folded = fold(text or "")
    pieces = [g for group in _BRACKET_CONTENT.findall(folded) for g in (group if isinstance(group, tuple) else (group,)) if g]
    outside = _BRACKETS.sub(" ", folded)
    dash = _DASH_VERSION.search(outside)
    if dash:
        pieces.append(dash.group(1))
    found: set[str] = set()
    for piece in pieces:
        piece = _FEAT.sub(" ", piece)
        piece = _YEAR.sub(" ", piece)
        for word in words(piece.translate(_APOSTROPHES)):
            if word not in _SIGNATURE_NOISE:
                found.add(word)
    return frozenset(w for w in found if w)


def norm_artist(text: str) -> str:
    t = re.sub(r"\s*-\s*topic$", "", text or "", flags=re.IGNORECASE)
    t = re.sub(r"(?i)vevo$|official$", "", fold(t))
    return " ".join(words(t))


def title_key(text: str) -> str:
    """[norm_title], and never empty while there is something to read (see [key_text]): what two titles are compared by for EQUALITY."""
    return norm_title(text) or key_text("", text)


def artist_key(text: str) -> str:
    """[norm_artist], and never empty while there is something to read: what two artists are compared by for EQUALITY (`!!!` is `!!!` and not `???`)."""
    return norm_artist(text) or key_text("", text)


#: What a song nobody names is filed under: the folder the keeper makes for an artist it cannot name, and the artist the importer gives a song whose
#: source lists none (N-26). **It is a placeholder, not a name**: see [is_unknown_artist].
UNKNOWN_ARTIST = "Unknown Artist"


def is_unknown_artist(name: str) -> bool:
    """Whether [name] says "nobody": the placeholder in any case, with or without the brackets the music server puts around it (`[Unknown Artist]`).
    **A name that cannot be told from "nobody" identifies nothing** (artist + title + length of two different nameless songs is the same string), so a
    ref whose artist is this is found by its ids and never by its name (`refs.find`), and no catalogue is asked about it (`artist_finder`). That
    includes a real artist who is literally called "Unknown Artist": the one corner this costs (written down in `docs/19` section 3 and tested)."""
    return norm_artist(name) == norm_artist(UNKNOWN_ARTIST)


#: The album the music server lists a file under when its tags name none. It says "no album", so it is never copied onto a ref that has a real one
#: or none (N-11: the doubled songs showed under "[unknown album]").
_PLACEHOLDER_ALBUM = re.compile(r"^\[?\s*unknown album\s*\]?$", re.IGNORECASE)


def is_placeholder_album(value: object) -> bool:
    """Whether an album is no album: nothing, blank, or the music server's `[Unknown Album]`. THE one definition, next to `is_unknown_artist` (its twin for the artist): `refs`
    re-exports it, and a file's tags and folder are built with it (N-34 slice 3: the placeholder is never written to the Host's disk)."""
    return not isinstance(value, str) or not value.strip() or _PLACEHOLDER_ALBUM.match(value.strip()) is not None


#: Where a combined artist string ("Daft Punk feat. Pharrell Williams", "Fat Joe, Lil Wayne") is cut into names. The YouTube matcher and the music server's
#: matcher use this one definition. The comma and the semicolon of other scripts cut like the ASCII ones: the Arabic `،` `؛`, the ideographic `、` and the
#: fullwidth `，` `；`. The words for "and" in other scripts (`و`, `и`, `と`) are NOT separators here: a word inside a name is not a cut (P2-12b's credits).
ARTIST_SPLIT = re.compile(
    "\\s*(?:,|;|\u060c|\u061b|\u3001|\uff0c|\uff1b|&|\\+|\\bfeat\\.?\\s|\\bft\\.?\\s|\\bfeaturing\\b|\\bx\\b|\\bwith\\b)\\s*",
    re.IGNORECASE,
)


def artist_parts(text: str) -> list[str]:
    """The names a combined artist string is made of ("A, B & C" is "A", "B", "C"); the string itself is not one of them unless it holds only one name."""
    return [part for part in ARTIST_SPLIT.split(text) if part.strip()]


def mentions_version(text: str) -> set[str]:
    """Which of [VERSION_WORDS] appear in [text] (as whole words)."""
    folded = fold(text or "")
    return {w for w in VERSION_WORDS if re.search(rf"\b{re.escape(w)}\b", folded)}


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
