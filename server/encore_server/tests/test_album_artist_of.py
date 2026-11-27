"""N-26 slice 3: who a song's album is BY, one definition for the tag and the folder (`keeper.tagging.album_artist_of`).

Measured on the real music server (`tests/integration/test_channel_artists.py`): a song whose ARTIST is a YouTube channel and whose ALBUMARTIST is also the channel makes the channel an artist
of the Artists list; any other album artist keeps it out. So a song whose artist is not a performer (`channel`, `unknown`) is filed and tagged under `Unknown Artist`, for NEW keeps only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from encore_server import refs
from encore_server.db import Database
from encore_server.keeper.placement import plan_for_ref
from encore_server.keeper.tagging import album_artist_of, tags_of


def ref_of(**more: Any) -> dict[str, Any]:
    return {
        "title": "Heartbeat",
        "artists": ["KEXP"],
        "albumArtist": None,
        "album": None,
        "trackNo": None,
        "discNo": None,
        **more,
    }


@pytest.mark.parametrize(
    ("more", "expected"),
    [
        ({"artistBasis": "channel"}, "Unknown Artist"),
        ({"artistBasis": "unknown"}, "Unknown Artist"),
        ({"artistBasis": "declared"}, "KEXP"),
        ({"artistBasis": "title"}, "KEXP"),
        ({"artistBasis": None}, "KEXP"),
        ({}, "KEXP"),
        ({"artistBasis": "channel", "albumArtist": "Nneka"}, "Nneka"),
        ({"artistBasis": "unknown", "albumArtist": ""}, "Unknown Artist"),
        ({"artistBasis": "declared", "albumArtist": "Various Artists"}, "Various Artists"),
        ({"artistBasis": "somethingelse"}, "KEXP"),
    ],
)
def test_the_album_artist_of_a_song(more: dict[str, Any], expected: str) -> None:
    assert album_artist_of(ref_of(**more)) == expected


def test_the_tags_and_the_folder_ask_the_same_definition() -> None:
    for more in ({"artistBasis": "channel"}, {"artistBasis": "declared"}, {"artistBasis": "unknown", "albumArtist": "Nneka"}, {}):
        ref = ref_of(**more)
        tags = tags_of(ref)
        folder = plan_for_ref(Path("/music/Encore"), ref).path.parent.parent.name
        assert tags.album_artist == folder == album_artist_of(ref), more


def test_a_channel_song_keeps_the_channel_as_its_artist_in_the_tags() -> None:
    tags = tags_of(ref_of(artistBasis="channel"))
    assert (tags.artist, tags.artists, tags.album_artist) == ("KEXP", ("KEXP",), "Unknown Artist")


def test_the_facts_are_for_the_server_and_never_for_an_api_answer(db: Database) -> None:
    with db.tx() as conn:
        made = refs.resolve(conn, {"title": "Heartbeat", "artists": ["KEXP"]}, artist_basis="channel", uploader="KEXP")
        ref_id = str(made["id"])
    with db.read() as conn:
        plain = refs.get_ref(conn, ref_id)
        with_facts = refs.get_ref(conn, ref_id, facts=True)
    assert "artistBasis" not in plain and "uploader" not in plain, "the API shape did not change"
    assert with_facts["artistBasis"] == "channel" and with_facts["uploader"] == "KEXP"
    assert {k: v for k, v in with_facts.items() if k not in ("artistBasis", "uploader")} == plain
