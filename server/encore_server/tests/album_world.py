"""Test helpers of the two rules of 25 Nov 2026 (`date_decided`, `sole_album`): a catalogue of the test's own making, and the REAL answers of the second live dry run.

**The made catalogue** (`world`): one song, one release per [Rel]; every release carries the song at its length, so the matcher sees only what the test names (the title, the type, the date and
the artist of each release). Nothing here is the matcher's own code: a test states what a release IS, and the matcher says what it makes of it.

**The real answers** (`recorded_song`): the second live dry run's answers (`tests/fixtures/deezer/n34_dryrun_25nov.json` names every file and every song's length; the files are in the folder
`n34_dryrun_25nov/`, SEPARATE from the first run's: a file name is a hash of its request, and the catalogue moved between the two runs, so the same name holds another answer). They are
served by the dry run's own replay (`album_dryrun.opened`: a file that is not there is "not recorded", never a guess). The lengths are the CATALOGUE's, not the kept file's (the files were
not saved): a length within the tolerance of the one the run read, so the same hits are the same recording.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from encore_server import album_dryrun
from encore_server.album_finder import Song, Verdict, choose_release, decide

HERE = Path(__file__).resolve().parent
FOLDER = HERE / "fixtures" / "deezer" / "n34_dryrun_25nov"
LEDGER = HERE / "fixtures" / "deezer" / "n34_dryrun_25nov.json"

# ------------------------------------------------------------------------------------------------------------------ the made catalogue

ARTIST, TITLE, LENGTH_MS = "Pearl Quill", "Harbour Lights", 200_000


@dataclass(frozen=True)
class Rel:
    """One release the catalogue says carries the song. [artist] is the album's artist (`None`: the song's own)."""

    id: str
    title: str
    type: str = "album"
    date: str | None = "2000-05-05"
    artist: str | None = None


def world(
    *releases: Rel, artist: str = ARTIST, title: str = TITLE, length_ms: int = LENGTH_MS
) -> tuple[Song, list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """The song, its search hits (one per release, in the order given) and the album answers `Catalogue.album` would give, in the catalogue's own shapes."""
    hits: list[dict[str, Any]] = []
    answers: dict[str, dict[str, Any]] = {}
    for number, rel in enumerate(releases):
        track = 700_000 + number
        hits.append(
            {
                "id": track,
                "title": title,
                "duration": length_ms // 1000,
                "artist": {"id": 1, "name": artist},
                "album": {"id": int(rel.id), "title": rel.title},
            }
        )
        answers[rel.id] = {
            "album": {
                "id": rel.id,
                "title": rel.title,
                "artists": [{"id": "1", "name": rel.artist or artist}],
                "cover": None,
                "trackCount": 1,
                "year": int(rel.date[:4]) if rel.date and rel.date[:4].isdigit() else None,
                "releaseDate": rel.date,
                "recordType": rel.type,
            },
            "tracks": [
                {
                    "id": str(track),
                    "title": title,
                    "artists": [{"id": "1", "name": artist}],
                    "album": {"id": rel.id, "title": rel.title},
                    "durationMs": length_ms,
                    "isrc": None,
                    "trackNo": 1,
                    "discNo": 1,
                }
            ],
        }
    return Song(artist, title, length_ms), hits, answers


def verdict_of(*releases: Rel, **named: Any) -> Verdict:
    """The matcher's whole decision over a made catalogue."""
    song, hits, answers = world(*releases, **named)
    return choose_release(song, hits, answers)


def outcome(verdict: Verdict) -> tuple[str, str]:
    return verdict.outcome, verdict.reason


# ------------------------------------------------------------------------------------------------------------------ the real answers of the second live dry run


def ledger() -> dict[str, Any]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def song_named(artist: str, title: str) -> Song:
    """A song of the ledger, with the length the ledger gives (see the module's note on the lengths)."""
    row = next(s for s in ledger()["songs"] if s["artist"] == artist and s["title"] == title)
    return Song(row["artist"], row["title"], row["length_ms"])


@contextmanager
def recorded_source() -> Iterator[album_dryrun.Source]:
    """The second run's answers behind the dry run's own replay: `search` and `album` are the very calls the pass makes."""
    with album_dryrun.opened(FOLDER, live=False, max_requests=None) as source:
        yield source


def recorded_song(artist: str, title: str) -> Verdict:
    """What the matcher decides for a song of the ledger over the real answers (`decide`, the one function the pass and the dry run both call)."""
    song = song_named(artist, title)
    with recorded_source() as source:
        return decide(song, source.search, source.album)


def recorded_inputs(artist: str, title: str) -> tuple[Song, list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """The song, the raw hits of its search and the mapped answer of every album its accepted hits name: what `choose_release` takes, for a test that CHANGES one
    thing (removes a hit, re-dates a release) and asks the matcher again."""
    from encore_server.album_finder import wanted_albums

    song = song_named(artist, title)
    with recorded_source() as source:
        hits = source.search(song.artist, song.title)
        answers = {ident: source.album(ident) for ident in wanted_albums(song, hits)}
    return song, hits, answers
