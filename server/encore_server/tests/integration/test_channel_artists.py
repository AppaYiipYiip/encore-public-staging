"""N-26 slice 3, the proof: what the real music server (the pinned version) does with a song whose ARTIST is a YouTube channel, for each way the keeper could tag it.

The question (docs/tasks/P2-songs-as-references.md, N-26 slice 3): an imported song whose artist is the uploading channel ("basis channel") must not make an artist page of its own, yet it must
still be kept, linked and played. Which tags does the music server need for that? This file asks the music server itself, for every shape, and says what it answered.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import pytest

from encore_server.navidrome import NavidromeClient
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


# one folder and one file per shape: the keeper's layout is Encore/<folder>/<album>/<song>.<ext>
SHAPES = {
    "today: ALBUMARTIST = the channel": {"albumartist": "{c}"},
    "no ALBUMARTIST tag at all": {},
    "ALBUMARTIST = Unknown Artist": {"albumartist": "Unknown Artist"},
    "ALBUMARTIST = Various Artists + COMPILATION": {"albumartist": "Various Artists", "compilation": "1"},
    "ALBUMARTIST = the performer (control: a real artist)": {"albumartist": "{p}"},
}


def test_probe_what_the_music_server_does_with_each_way_of_tagging_a_channel_song(rig: Rig, navidrome: NavidromeClient) -> None:
    channel_names: dict[str, str] = {}
    performer = unique("Zxqv Performer")
    for n, (label, extra) in enumerate(SHAPES.items()):
        channel = unique(f"Zxqv Channel{n}")
        channel_names[label] = channel
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
    report: dict[str, Any] = {
        "performerListed": performer in listed,
        "listedNames": sorted(n for n in listed if n.startswith("Zxqv") or n in ("Unknown Artist", "Various Artists")),
    }
    for label, channel in channel_names.items():
        hit = search(navidrome, channel)
        songs = hit.get("song") or []
        report[label] = {
            "channelIsInGetArtists": channel in listed,
            "artistHitsInSearch": [a.get("name") for a in hit.get("artist") or []],
            "albumHitsInSearch": [(a.get("name"), a.get("artist")) for a in hit.get("album") or []],
            "songFacts": [
                {k: s.get(k) for k in ("title", "artist", "albumArtist", "album", "isCompilation") if k in s} for s in songs
            ],
        }
    # the probe: it fails on purpose so that CI prints what the music server said
    pytest.fail("N26_PROBE_BEGIN\n" + json.dumps(report, indent=1, ensure_ascii=False) + "\nN26_PROBE_END")
