"""N-26 slice 3, the proof: what the real music server (the pinned version, 0.64.2) does with a song whose ARTIST is a YouTube channel, for each way the keeper could tag it.

The question (docs/tasks/P2-songs-as-references.md, N-26 slice 3): an imported song whose artist is the uploading channel ("basis channel") must not make an artist of its own in the Artists
list, yet it must still be kept, linked and played. MEASURED (27 Nov 2026, this file's first run printed every answer):

* ALBUMARTIST = the channel (what the keeper wrote for EVERY song) or no ALBUMARTIST at all: the channel is listed by `getArtists` and its album is the channel's.
* ALBUMARTIST = anything else (`Unknown Artist`, `Various Artists` with COMPILATION, a real performer): the channel is NOT in `getArtists` (that list is the album artists), the album
  is listed under the album artist, and the song's own `artist` is still the channel (so the ref, the link by name and the match do not change).
* What does NOT change: `search3` still finds the channel as an artist (the music server keeps an artist entity for a track artist); only the Artists list is cleaner.

The second test runs the keeper's own code (`tags_of`, `write_tags`, `plan_for_ref`) over a ref whose basis is `channel` and lets the music server read the file it wrote.
"""

from __future__ import annotations

import secrets
from typing import Any

import pytest

from encore_server import refs
from encore_server.keeper.placement import plan_for_ref
from encore_server.keeper.tagging import tags_of, write_tags
from encore_server.navidrome import NavidromeClient
from encore_server.scanner import link_library
from tests.integration.conftest import MUSIC, Rig, make_audio, scan_and_wait

pytestmark = pytest.mark.integration


def unique(word: str) -> str:
    return f"{word} {secrets.token_hex(3)}"


def artists_listed(navidrome: NavidromeClient) -> dict[str, dict[str, Any]]:
    body = navidrome._call("getArtists") or {}
    found: dict[str, dict[str, Any]] = {}
    for group in (body.get("artists") or {}).get("index") or []:
        for artist in group.get("artist") or []:
            found[artist.get("name")] = artist
    return found


def search(navidrome: NavidromeClient, query: str) -> dict[str, Any]:
    return (navidrome._call("search3", query=query, artistCount=20, albumCount=20, songCount=20) or {}).get("searchResult3") or {}


# (the tags added to ARTIST = the channel) -> is the channel in the Artists list, and who is the album by
SHAPES = {
    "today: ALBUMARTIST = the channel": ({"albumartist": "{c}"}, True, "{c}"),
    "no ALBUMARTIST tag at all": ({}, True, "{c}"),
    "ALBUMARTIST = Unknown Artist": ({"albumartist": "Unknown Artist"}, False, "Unknown Artist"),
    "ALBUMARTIST = Various Artists + COMPILATION": (
        {"albumartist": "Various Artists", "compilation": "1"},
        False,
        "Various Artists",
    ),
    "ALBUMARTIST = a performer": ({"albumartist": "{p}"}, False, "{p}"),
}


def test_the_artists_list_holds_the_album_artist_never_the_channel_unless_the_channel_is_the_album_artist(
    rig: Rig, navidrome: NavidromeClient
) -> None:
    performer = unique("Zxqv Performer")
    channels: dict[str, str] = {}
    for n, (label, (extra, _, _)) in enumerate(SHAPES.items()):
        channel = unique(f"Zxqv Channel{n}")
        channels[label] = channel
        tags = {k: v.format(c=channel, p=performer) for k, v in extra.items()}
        make_audio(
            MUSIC / "Encore" / f"folder{n}-{channel}" / "[Unknown Album]" / "01 - Song.opus",
            title=f"Song {n}",
            artist=channel,
            album="[Unknown Album]",
            track="1",
            **tags,
        )
    scan_and_wait(navidrome)
    listed = artists_listed(navidrome)
    for label, (_, in_list, album_by) in SHAPES.items():
        channel = channels[label]
        found = search(navidrome, channel)
        assert (channel in listed) is in_list, (label, "the channel in the Artists list", sorted(listed))
        assert [(a.get("name"), a.get("artist")) for a in found.get("album") or []] == [
            ("[Unknown Album]", album_by.format(c=channel, p=performer))
        ], label
        assert [s.get("artist") for s in found.get("song") or []] == [channel], (
            f"{label}: the song's own artist stays the channel"
        )
        assert channel in [a.get("name") for a in found.get("artist") or []], (
            f"{label}: search still finds the channel as an artist (measured)"
        )
    assert "Unknown Artist" in listed and "Various Artists" in listed and performer in listed


def test_the_keepers_own_tags_for_a_channel_song_keep_the_channel_out_of_the_artists_list(
    rig: Rig, navidrome: NavidromeClient
) -> None:
    channel = unique("Zxqv KEXP")
    with rig.svc.db.tx() as conn:
        made = refs.resolve(conn, {"title": "Full Performance", "artists": [channel]}, artist_basis="channel", uploader=channel)
        ref_id = str(made["id"])
    with rig.svc.db.read() as conn:
        ref = refs.get_ref(conn, ref_id, facts=True)  # the dict the keeper itself plans and tags with
    placement = plan_for_ref(MUSIC / "Encore", ref, ".opus")
    audio = make_audio(placement.path)
    assert placement.path.relative_to(MUSIC).as_posix() == "Encore/Unknown Artist/Singles/Full Performance.opus"
    assert write_tags(audio, tags_of(ref)), "the keeper's own writer tagged the file"
    scan_and_wait(navidrome)
    listed = artists_listed(navidrome)
    found = search(navidrome, channel)
    assert channel not in listed, "the channel is not an artist of the Artists list"
    assert "Unknown Artist" in listed
    assert [s.get("artist") for s in found.get("song") or []] == [channel], (
        "the song is still the channel's: the link by name is unchanged"
    )
    # The scanner describes every file from the music server's OWN answer, which now says ALBUMARTIST = Unknown Artist: the file links to the ref, and the placeholder never becomes the
    # ref's album artist (it would flow into the cover key, the album pass and the artist finder's own-songs query: the class of the N-34 incident).
    link_library(rig.svc.db, navidrome)
    with rig.svc.db.read() as conn:
        linked = refs.get_ref(conn, ref_id)
    assert (linked["file"] or {}).get("navidromeSongId"), "the file is linked to the ref by its name"
    assert linked["albumArtist"] is None, "and the placeholder did not come back as a fact"
