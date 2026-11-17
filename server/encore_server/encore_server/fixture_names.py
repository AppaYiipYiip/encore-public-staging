"""The file name of a recorded catalogue answer: ONE function, for everything that saves an answer or looks one up (N-34 slice 1).

`album_dryrun` replays and (with `--live`) saves answers under these names, `tools/record_catalogue_fixtures.py n34` records them under the same names, and
the tests' catalogue fake (`tests/catalogue_fakes.py`) finds them by it. Three copies of a naming rule drift apart, and a drifted copy replays the wrong answer
without saying so; so there is one, here, with nothing but the standard library in it (the recorder is a stand-alone tool and imports only this file).

**A search is named by a hash of its FULL query.** It used to be named by the query's Latin letters only (`[^a-z0-9]+` turned into `_`), so every query with no
Latin letter was `search_track_` and a dry run over an Arabic, Cyrillic or Japanese library replayed the first answer it had saved to every later song; two
queries that differ only in punctuation or in non-Latin letters were one file. Now the name is `search_track_<readable>_<hash>`: the hash (the first 16 hex
digits of the SHA-256 of the query's UTF-8 bytes, so the same on every machine and every Python: the built-in `hash` is salted per process) is the KEY, and the
readable part (the Latin letters of the query, at most [READABLE_LETTERS]) is only there so that a person can find a file in a folder of 650. The query is
hashed exactly as it is sent (no case fold, no normalisation): a replay that misses is reported as "not recorded", a replay that answers with another query's
answer is silent, and only the second is a defect.

The other requests are named by the id in their path, which is already exact (`album_<id>`, `album_<id>_tracks`, `artist_albums_<id>`; an id is the ASCII
digits `0-9`, never another script's).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

#: How many characters of the query's Latin letters a search's file name keeps for a person to read (never part of the key).
READABLE_LETTERS = 40
#: How many hex digits of the SHA-256 are the key (64 bits: a collision between two queries of one library is out of reach).
HASH_DIGITS = 16

_NOT_LATIN = re.compile(r"[^a-z0-9]+")
_BY_ID = (
    (re.compile(r"/album/([0-9]+)"), "album_{}"),
    (re.compile(r"/album/([0-9]+)/tracks"), "album_{}_tracks"),
    (re.compile(r"/artist/([0-9]+)/albums"), "artist_albums_{}"),
)


def search_name(query: str) -> str:
    """The name (without `.json`) of the answer to the search `q=<query>`: `search_track_<readable>_<hash>`, or `search_track_<hash>` when the query has no
    Latin letter or digit at all."""
    key = hashlib.sha256(query.encode("utf-8", "surrogatepass")).hexdigest()[:HASH_DIGITS]
    readable = _NOT_LATIN.sub("_", query.lower()).strip("_")[:READABLE_LETTERS].rstrip("_")
    return f"search_track_{readable}_{key}" if readable else f"search_track_{key}"


def fixture_name(path: str, params: Mapping[str, Any]) -> str | None:
    """The file name (without `.json`) a request's answer is saved in and replayed from, or `None` for a request nobody saves: the plain `/search` (by its
    query), `/album/<id>`, `/album/<id>/tracks` and `/artist/<id>/albums`."""
    if path == "/search":
        query = str(params.get("q") or "")
        return search_name(query) if query else None
    for pattern, name in _BY_ID:
        if match := pattern.fullmatch(path):
            return name.format(match[1])
    return None
