"""N-53, on the real music server (0.64.2): where a library song's file REALLY lies, and the errand that learns it (`real_paths.py`).

Measured on 27 Nov 2026 (the CI of N-38 and a probe of the native API): the `path` the music server's Subsonic API reports for a song is built from its TAGS, not from the place the file lies, and the
scanner stores it as `song_file.path`. The native API the server signs in to as the administrator names the real place (`GET /api/song?id=a&id=b`: `path`, `libraryPath`, `libraryId`). This pins both
facts (so the day either changes, the failure says what to revisit) and proves the errand end to end, with the audio-key errand that depends on it.
"""

from __future__ import annotations

import secrets
from typing import Any

import pytest

from encore_server.audio_key import AudioKeys, audio_key_of
from encore_server.navidrome import NavidromeClient
from encore_server.navidrome_admin import NavidromeAdmin
from encore_server.real_paths import RealPaths
from encore_server.scanner import link_library
from tests.integration.conftest import MUSIC, URL, Rig, make_audio, scan_and_wait

pytestmark = pytest.mark.integration


def stored(rig: Rig, title: str) -> Any:
    with rig.svc.db.read() as conn:
        return conn.execute(
            "SELECT f.id, f.navidrome_song_id AS song, f.path, f.path_real, f.path_checked_at, f.audio_key FROM song_file f JOIN song_ref r ON r.id = f.ref WHERE r.title = ?",
            (title,),
        ).fetchone()


def test_the_native_api_names_the_real_place_the_subsonic_path_hides(
    rig: Rig, navidrome: NavidromeClient, accounts: dict[str, str]
) -> None:
    unique = secrets.token_hex(3)
    artist, album = f"Zxqv Artist {unique}", f"Zxqv Album {unique}"
    elsewhere = make_audio(
        MUSIC / f"Zxqv misc {unique}" / "random-name-1234.opus", title=f"Zxqv Elsewhere {unique}", artist=artist, album=album
    )
    placed = make_audio(
        MUSIC / artist / album / f"Zxqv Placed {unique}.opus", title=f"Zxqv Placed {unique}", artist=artist, album=album
    )
    scan_and_wait(navidrome)
    link_library(rig.svc.db, navidrome)
    lost, found = stored(rig, f"Zxqv Elsewhere {unique}"), stored(rig, f"Zxqv Placed {unique}")
    assert lost is not None and found is not None, "the library link made a row for both"

    # THE FACT THIS WORK RESTS ON, pinned: the Subsonic path is built from the tags. Where the file lies is another thing.
    assert lost["path"] != elsewhere.relative_to(MUSIC).as_posix(), (
        f"the music server reported {lost['path']!r} for a file that lies at {elsewhere.relative_to(MUSIC).as_posix()!r}: if this flips it now reports real paths and the errand can go"
    )
    assert lost["path_real"] == 0 and found["path_real"] == 0, "the scanner's path is never marked checked"

    admin = NavidromeAdmin(URL, accounts["admin"], accounts["admin_pw"])
    places = admin.song_places([lost["song"], found["song"], "no-such-song-id"])
    assert places == {
        lost["song"]: elsewhere.relative_to(MUSIC).as_posix(),
        found["song"]: placed.relative_to(MUSIC).as_posix(),
    }, "the native API names the real place of each, and says nothing of an id it does not know"

    done = RealPaths(rig.svc.db, MUSIC, admin).run_once()

    assert done.resolved >= 2
    lost, found = stored(rig, f"Zxqv Elsewhere {unique}"), stored(rig, f"Zxqv Placed {unique}")
    assert (lost["path"], lost["path_real"]) == (elsewhere.relative_to(MUSIC).as_posix(), 1)
    assert (found["path"], found["path_real"]) == (placed.relative_to(MUSIC).as_posix(), 1)

    # What it was for (N-38): the audio-key errand now keys the file whose Subsonic path named nothing.
    AudioKeys(rig.svc.db, MUSIC).run_once()
    assert stored(rig, f"Zxqv Elsewhere {unique}")["audio_key"] == audio_key_of(elsewhere)
    assert stored(rig, f"Zxqv Placed {unique}")["audio_key"] == audio_key_of(placed)

    # A second pass does not touch what is checked.
    checked = {title: stored(rig, title)["path_checked_at"] for title in (f"Zxqv Elsewhere {unique}", f"Zxqv Placed {unique}")}
    RealPaths(rig.svc.db, MUSIC, admin).run_once()
    assert {title: stored(rig, title)["path_checked_at"] for title in checked} == checked
