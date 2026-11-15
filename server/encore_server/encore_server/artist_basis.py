"""How the artist of a song was decided: the vocabulary of N-26 (design `docs/tasks/P2-songs-as-references.md`, section "N-26").

A dependency-free module on purpose: the importer's reading of an upload (`imports/uploads.py`), the refs that keep the facts (`refs.py`, the
`song_ref.artist_basis` column), the merge repair, and the two finders that ask the catalogue about an artist or a cover all speak this one language, and
none of them may need another to do it.

* `declared`: the source says so (a song of the catalogue, a Spotify or file description, an official video's credit);
* `title`: the title names the performer ("Artist - Song");
* `channel`: nothing names a performer, so the uploader stays as the artist, flagged. The one named stop-gap (removed by N-28);
* `unknown`: nobody is named (the song is filed under `textnorm.UNKNOWN_ARTIST`).

**NULL is a fourth state, not a fifth basis: "as before".** A ref made before N-26, by a phone, by the library scan or from a file has no facts and is treated
as a performer, exactly as it always was. It must never be read as `channel`.
"""

from __future__ import annotations

DECLARED = "declared"
TITLE = "title"
CHANNEL = "channel"
UNKNOWN = "unknown"

BASES = (DECLARED, TITLE, CHANNEL, UNKNOWN)

#: The bases that say the artist is NOT a performer: a channel's name or nobody. The catalogue is never asked for the picture of such an artist or for the
#: cover of such a song (`artist_finder`, `cover_finder`).
NOT_PERFORMERS = frozenset({CHANNEL, UNKNOWN})


def is_known_basis(value: object) -> bool:
    return isinstance(value, str) and value in BASES


def is_performer(basis: str | None) -> bool:
    """Whether a stored basis lets the artist be looked up. **NULL is a performer** (as before)."""
    return basis not in NOT_PERFORMERS


def performer_clause(column: str = "artist_basis") -> str:
    """The same rule as SQL. `col NOT IN (...)` is NULL (not true) for a NULL row, which would silently drop every old ref: the NULL is named."""
    quoted = ", ".join(f"'{basis}'" for basis in sorted(NOT_PERFORMERS))
    return f"({column} IS NULL OR {column} NOT IN ({quoted}))"
