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


def test_a_whole_chunk_of_places_comes_back_whole(rig: Rig, navidrome: NavidromeClient, accounts: dict[str, str]) -> None:
    """The probe asked for 2 ids; the native list may have a default page size. The errand asks 100 at a time and an id the answer lacks is only stamped and tried again, so a truncated answer would
    cost passes silently: prove that 105 ids (a chunk and a part of one) all come back."""
    unique = secrets.token_hex(3)
    files = {}
    for n in range(105):
        title = f"Zxqv Bulk {unique} {n:03d}"
        files[title] = make_audio(
            MUSIC / f"Zxqv bulk {unique}" / f"{n:03d}.opus",
            seconds=1,
            title=title,
            artist=f"Zxqv Bulk Artist {unique}",
            album=f"Zxqv Bulk Album {unique}",
        )
    scan_and_wait(navidrome)
    link_library(rig.svc.db, navidrome)
    ids = {title: stored(rig, title)["song"] for title in files}
    assert len(set(ids.values())) == 105

    places = NavidromeAdmin(URL, accounts["admin"], accounts["admin_pw"]).song_places(list(ids.values()))

    assert {title: places.get(song_id) for title, song_id in ids.items()} == {
        title: file.relative_to(MUSIC).as_posix() for title, file in files.items()
    }


def test_a_file_that_moves_is_found_again_whether_or_not_the_music_server_keeps_its_song_id(
    rig: Rig, navidrome: NavidromeClient, accounts: dict[str, str]
) -> None:
    """MEASURED here, handled either way: when a Host moves a file inside the music folder the music server either gives the moved file a new id (the old row is pruned by the library link and the new file
    gets its own row) or keeps the id (the row's checked path is then stale, and the reader that finds no file takes the mark back). After the passes the song has ONE file row, at the new place, checked and keyed."""
    unique = secrets.token_hex(3)
    title = f"Zxqv Mover {unique}"
    old = make_audio(
        MUSIC / f"Zxqv before {unique}" / "song.opus",
        title=title,
        artist=f"Zxqv Mover Artist {unique}",
        album=f"Zxqv Mover Album {unique}",
    )
    scan_and_wait(navidrome)
    link_library(rig.svc.db, navidrome)
    admin = NavidromeAdmin(URL, accounts["admin"], accounts["admin_pw"])
    RealPaths(rig.svc.db, MUSIC, admin).run_once()
    AudioKeys(rig.svc.db, MUSIC).run_once()
    first = stored(rig, title)
    assert (first["path"], first["path_real"]) == (old.relative_to(MUSIC).as_posix(), 1) and first["audio_key"] == audio_key_of(
        old
    )

    new = MUSIC / f"Zxqv after {unique}" / "moved-song.opus"
    new.parent.mkdir(parents=True)
    old.rename(new)
    scan_and_wait(navidrome)
    link_library(rig.svc.db, navidrome)
    kept_id = stored(rig, title)["song"] == first["song"]
    # the reader that needs the file (a repair, here the audio-key errand after a size change) finds it missing at the old place
    from encore_server.place import trusted_file

    with rig.svc.db.read() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT f.id, f.path FROM song_file f JOIN song_ref r ON r.id = f.ref WHERE r.title = ?", (title,)
            )
        ]
    for row in rows:
        trusted_file(rig.svc.db, MUSIC, row["id"], row["path"])
    for _ in range(2):
        RealPaths(rig.svc.db, MUSIC, admin).run_once()
        AudioKeys(rig.svc.db, MUSIC).run_once()

    with rig.svc.db.read() as conn:
        rows = conn.execute(
            "SELECT f.path, f.path_real, f.audio_key FROM song_file f JOIN song_ref r ON r.id = f.ref WHERE r.title = ?", (title,)
        ).fetchall()
    assert [(r["path"], r["path_real"]) for r in rows] == [(new.relative_to(MUSIC).as_posix(), 1)], (
        f"one row at the new place (the music server {'kept' if kept_id else 'changed'} the song id when the file moved)"
    )
    assert rows[0]["audio_key"] == audio_key_of(new)
