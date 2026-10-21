"""Which release is this song from? (docs/46 section 5)

The quick copy carries a catalogue's names (artist, album, title, year); Lidarr thinks in MusicBrainz releases. This picks, among what
Lidarr's album search returns, the one release group the song belongs to, or says honestly that it cannot: a wrong album would bring the
wrong music into somebody's library, so "no match" is always better than a guess.
"""
from __future__ import annotations

from dataclasses import dataclass

from .textnorm import norm_album, norm_title, same_artist

#: Lower is preferred when two releases carry the same name.
_TYPE_RANK = {"album": 0, "ep": 1, "single": 2, "broadcast": 3, "other": 4}
#: Kinds of release that are not "the" album unless the person's own album name says so.
_NOT_STUDIO = {"live", "compilation", "remix", "dj-mix", "mixtape/street", "demo", "interview", "spokenword", "audio drama"}

NO_RELEASE = "The music catalogue has no album by that name for this artist."
NO_ARTIST = "The music catalogue does not know this artist under that name."


@dataclass(frozen=True)
class Song:
    artist: str
    album: str
    title: str
    year: int | None = None
    release_group: str | None = None  # a MusicBrainz id, when the file carries one


@dataclass(frozen=True)
class Choice:
    album: dict | None
    reason: str = ""

    @property
    def found(self) -> bool:
        return self.album is not None


def _secondary(album: dict) -> set[str]:
    return {str(t).lower() for t in album.get("secondaryTypes") or []}


def _year(album: dict) -> int | None:
    date = str(album.get("releaseDate") or "")
    return int(date[:4]) if date[:4].isdigit() else None


def choose(song: Song, candidates: list[dict]) -> Choice:
    """The candidate (a Lidarr album search result) that is this song's release group, or why there is none."""
    if song.release_group:
        for candidate in candidates:
            if str(candidate.get("foreignAlbumId") or "") == song.release_group:
                return Choice(candidate)
    by_artist = [c for c in candidates if same_artist(song.artist, str((c.get("artist") or {}).get("artistName") or ""))]
    if not by_artist:
        return Choice(None, NO_ARTIST)
    wanted_album = norm_album(song.album)
    named = [c for c in by_artist if wanted_album and norm_album(str(c.get("title") or "")) == wanted_album]
    if not named:
        # The song may be a single whose release carries the song's own name (and the catalogue's "album" is that single).
        wanted_title = norm_title(song.title)
        named = [c for c in by_artist if wanted_title and norm_title(str(c.get("title") or "")) == wanted_title
                 and str(c.get("albumType") or "").lower() == "single"]
    if not named:
        return Choice(None, NO_RELEASE)
    return Choice(min(named, key=lambda c: _rank(song, c)))


def _rank(song: Song, candidate: dict) -> tuple:
    kind = str(candidate.get("albumType") or "other").lower()
    lived = len(_secondary(candidate) & _NOT_STUDIO)
    years = _year(candidate)
    apart = abs(years - song.year) if years is not None and song.year else 50
    # Prefer the plain studio release of the right kind; then the closest year; then the one with the most editions (the best known).
    return (lived, _TYPE_RANK.get(kind, 5), apart, -len(candidate.get("releases") or []))
