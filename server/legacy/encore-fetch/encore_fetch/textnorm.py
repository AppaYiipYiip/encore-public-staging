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
    "live", "cover", "karaoke", "instrumental", "remix", "sped up",
    "slowed", "reverb", "nightcore", "8d", "acoustic", "demo", "reaction",
    "tutorial", "lesson", "medley", "mashup", "bass boosted",
)


def ascii_fold(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text or "")
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )


def norm_title(text: str) -> str:
    """`Song (Remastered 2011) [Official Audio]` -> `song`."""
    t = _BRACKETS.sub(" ", ascii_fold(text))
    t = _FEAT.sub(" ", t)
    t = _NOISE.sub(" ", t)
    t = re.sub(r"\s+-\s+(remaster(ed)?|single|radio edit|\d{4}).*", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def norm_artist(text: str) -> str:
    t = re.sub(r"\s*-\s*topic$", "", text or "", flags=re.IGNORECASE)
    t = re.sub(r"(?i)vevo$|official$", "", ascii_fold(t))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def mentions_version(text: str) -> set[str]:
    """Which of [VERSION_WORDS] appear in [text] (as whole words)."""
    folded = ascii_fold(text)
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
