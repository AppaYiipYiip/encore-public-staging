"""Names compared the way a person would: `Magma (Deluxe Edition)` is `Magma`, `Beyoncé` is `Beyonce`, `Guns N' Roses` is `Guns N Roses`.

Pure functions, no I/O.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

_BRACKETS = re.compile(r"\(.*?\)|\[.*?\]|\{.*?\}")
_FEAT = re.compile(r"\b(feat|ft|featuring)\b.*", re.IGNORECASE)
#: `Album - Remastered 2011`, `Album - Deluxe Edition`, `Album - Single`: a dash and a word that says "another edition of it".
_EDITION_TAIL = re.compile(
    r"\s+-\s+(?:(?:\d{4}\s+)?(?:remaster(?:ed)?|deluxe|expanded|anniversary|bonus|special|collector'?s|legacy|super deluxe|"
    r"single|ep|edition|version|mono|stereo)\b.*|\d{4}\b.*)$", re.IGNORECASE)
_EDITION_WORDS = re.compile(
    r"\b(deluxe|remaster(?:ed)?|expanded|anniversary|bonus tracks?|special|collector'?s|legacy|edition|version)\b", re.IGNORECASE)


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def norm_title(text: str) -> str:
    """A song's name without what a store adds to it: `Song (Remastered 2011) [Official Audio]` -> `song`."""
    t = _BRACKETS.sub(" ", ascii_fold(text))
    t = _FEAT.sub(" ", t)
    t = _EDITION_TAIL.sub(" ", t)
    return _squash(t)


def norm_album(text: str) -> str:
    """An album's name without its edition: `Magma (Deluxe Edition)` and `Magma - Remastered 2020` are `magma`.

    A bracket that is the whole title (`(What's the Story) Morning Glory?` is not that, but `[Untitled]` is) is kept."""
    folded = ascii_fold(text)
    bare = _BRACKETS.sub(" ", folded)
    t = bare if _squash(bare) else folded
    t = _EDITION_TAIL.sub(" ", t)
    t = _EDITION_WORDS.sub(" ", t)
    return _squash(t)


def norm_artist(text: str) -> str:
    t = re.sub(r"\s*-\s*topic$", "", text or "", flags=re.IGNORECASE)
    t = re.sub(r"(?i)\bthe\b", " ", ascii_fold(t))
    t = t.replace("&", " and ")
    return _squash(t.replace("'", ""))


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def same_artist(a: str, b: str) -> bool:
    """`Tool` and `Tool`, `Bonobo` and `Bonobo`, `Mike Oldfield` and `Mike Oldfield`; not `Tool` and `Tools`."""
    x, y = norm_artist(a), norm_artist(b)
    if not x or not y:
        return False
    return x == y or ratio(x, y) >= 0.92
