"""N-15 against a real music server: a picture written as `artist.jpg` into an artist's own kept folder (`Encore/<artist>/`) becomes that artist's
`coverArt` in the music server, and no other artist gets it.

This is what the unit tests can only pretend: that the music server (the pinned version) lists an artist it found no picture for without a
`coverArt`, picks the file up at its next scan although it had already settled "no picture" for that artist, and serves it."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from encore_server.artist_finder import ArtistFinder
from encore_server.navidrome import NavidromeClient
from encore_server.scanner import link_library
from tests.integration.conftest import MUSIC, Rig, ffmpeg, make_audio, scan_and_wait

pytestmark = pytest.mark.integration


def unique(word: str) -> str:
    return f"{word} {secrets.token_hex(3)}"


def listed(navidrome: NavidromeClient, name: str) -> dict[str, Any] | None:
    """The artist as `getArtists` lists it."""
    body = navidrome._call("getArtists") or {}
    for group in (body.get("artists") or {}).get("index") or []:
        for artist in group.get("artist") or []:
            if artist.get("name") == name:
                return artist  # type: ignore[no-any-return]
    return None


def wait_for(check: Callable[[], Any], what: str, *, seconds: float = 60) -> Any:
    """The music server resolves artwork in the background after a scan: wait for it, and say what was being waited for when it does not come."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        result = check()
        if result:
            return result
        time.sleep(1)
    raise AssertionError(f"the music server did not {what} in {seconds:.0f} s")


def a_jpeg(tmp_path: Path) -> bytes:
    path = tmp_path / "artist-source.jpg"
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(path))
    return path.read_bytes()


def test_a_picture_file_in_the_artists_own_kept_folder_becomes_its_cover_and_no_other_artist_gets_it(
    rig: Rig, navidrome: NavidromeClient, tmp_path: Path
) -> None:
    artist, neighbour = unique("Zxqv Pictureless"), unique("Zxqv Neighbour")
    for who in (artist, neighbour):
        make_audio(MUSIC / "Encore" / who / "Debut" / "01 - Song.opus", title="Song", artist=who, album="Debut", track="1")
    scan_and_wait(navidrome)
    link_library(rig.svc.db, navidrome)
    # The music server has looked for a picture for both (no outside source is on in this throwaway server) and listed them without one.
    wait_for(
        lambda: {name for _, name in navidrome.artists_without_picture() or []} >= {artist, neighbour},
        "list both artists without a picture",
    )

    asked: list[tuple[str, str]] = []

    def catalogue(who: str, title: str, album: str | None) -> str | None:
        asked.append((who, title))
        return "https://cdn-images.dzcdn.net/images/artist/abc/1000x1000-000000-80-0-0.jpg" if who == artist else None

    picture = a_jpeg(tmp_path)
    finder = ArtistFinder(
        rig.svc.db, navidrome, catalogue, music_dir=MUSIC, fetch=lambda url: picture, sleep=lambda _: None, per_pass=50
    )

    report = finder.run_once()

    assert report.found == 1
    assert (artist, "Song") in asked
    assert (MUSIC / "Encore" / artist / "artist.jpg").read_bytes() == picture
    assert not (MUSIC / "Encore" / "artist.jpg").exists(), (
        "never in the server's own folder itself: it would be every artist's picture"
    )

    scan_and_wait(navidrome)
    got = wait_for(lambda: (listed(navidrome, artist) or {}).get("coverArt"), "give the artist a cover from its picture file")
    served = navidrome.cover(str(got))
    assert served is not None and served[1].startswith("image/"), (
        "and the cover can be fetched the way the phone's pictures route does"
    )
    assert not (listed(navidrome, neighbour) or {}).get("coverArt"), "an artist whose folder has no picture still has none"
    assert artist not in {name for _, name in navidrome.artists_without_picture() or []}
