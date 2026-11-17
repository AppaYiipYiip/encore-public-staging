"""The fold the server used until P2-25 slices 2 and 3: **test code only, frozen**. Production keeps no copy of it (`keyrepair.py` keeps one small rule, `_lost_by_old_fold`,
which is a property of text, not a fold).

It exists so that a test can build a database the way the OLD code built it (the stored keys, the damage of audit B-37) and prove what the rekey does to it, and so that
a test can prove that a key made of ASCII did not change. It is a literal copy of `textnorm.ascii_fold`, `norm_title`, `norm_artist`, `version_signature`,
`mentions_version` and `refs.norm_key` as they were on main `95d1293`: do not "improve" it. Marked `STOP-GAP(P2-25 one-shot-repair; remove after 0.1.0)`: it goes with the repair
(N-36), when the worklist table is empty on every install the project knows.
"""

from __future__ import annotations

import re
import unicodedata

_NOISE = re.compile(
    r"\b(official|video|audio|lyrics?|lyric video|hd|hq|4k|remaster(?:ed)?|"
    r"explicit|visuali[sz]er|music video|full album|topic)\b",
    re.IGNORECASE,
)
_BRACKETS = re.compile(r"\(.*?\)|\[.*?\]|\{.*?\}")
_FEAT = re.compile(r"\b(feat|ft|featuring)\b.*", re.IGNORECASE)

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


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def norm_title(text: str) -> str:
    t = _BRACKETS.sub(" ", ascii_fold(text))
    t = _FEAT.sub(" ", t)
    t = _NOISE.sub(" ", t)
    t = re.sub(r"\s+-\s+(remaster(ed)?|single|radio edit|\d{4}).*", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def version_signature(text: str) -> frozenset[str]:
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


def mentions_version(text: str) -> set[str]:
    folded = ascii_fold(text)
    return {w for w in VERSION_WORDS if re.search(rf"\b{re.escape(w)}\b", folded)}


def norm_key(artist: str, title: str) -> str:
    """`refs.norm_key` as it was: the key every stored `song_ref.norm_key` of the old server holds."""
    version = " ".join(sorted(version_signature(title)))
    return f"{norm_artist(artist)}|{norm_title(title)}|{version}"
