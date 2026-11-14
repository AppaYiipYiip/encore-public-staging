"""P2-01's acceptance against a real Navidrome: like a catalogue song, a keep job runs, the file appears, the ref gets its file, the like
is unchanged; rename, re-tag or replace the file and the like and the playlist entry are unchanged."""

from __future__ import annotations

import secrets
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from encore_server.ids import new_id
from encore_server.navidrome import NavidromeClient
from encore_server.scanner import link_library
from tests.integration.conftest import MUSIC, V1, Rig, make_audio, scan_and_wait

pytestmark = pytest.mark.integration


def unique(word: str) -> str:
    return f"{word} {secrets.token_hex(3)}"


def song_of(navidrome: NavidromeClient, song_id: str) -> dict[str, Any]:
    body = navidrome._call("getSong", id=song_id)
    assert body is not None, f"the music server has no song {song_id}"
    return body["song"]  # type: ignore[no-any-return]


def bytes_of(navidrome: NavidromeClient, song_id: str) -> bytes:
    """What `stream.view` sends for the song (what the app plays when a kept file exists)."""
    from encore_server.auth import subsonic_token

    salt = secrets.token_hex(6)
    query = urllib.parse.urlencode(
        {
            "u": navidrome._user,
            "t": subsonic_token(navidrome._password, salt),
            "s": salt,
            "v": "1.16.1",
            "c": "it",
            "id": song_id,
            "format": "raw",
        }
    )
    with urllib.request.urlopen(f"{navidrome._base}/rest/stream.view?{query}", timeout=30) as response:  # noqa: S310
        return response.read()


def test_the_hosts_own_music_becomes_refs_and_is_found_by_what_describes_it(rig: Rig, navidrome: NavidromeClient) -> None:
    artist, title = unique("Collection Artist"), unique("Collection Song")
    make_audio(
        MUSIC / "Collection" / artist / "First Album" / f"01 - {title}.flac",
        title=title,
        artist=artist,
        album="First Album",
        track="1",
    )
    scan_and_wait(navidrome)

    report = link_library(rig.svc.db, navidrome)

    assert report.complete and report.new_refs >= 1
    ref = rig.resolve(title=title, artists=[artist], album="First Album", durationMs=3000)
    assert ref["file"] is not None and ref["file"]["navidromeSongId"], "the song described by a person is the one the library has"
    assert song_of(navidrome, ref["file"]["navidromeSongId"])["title"] == title


def test_liking_a_catalogue_song_keeps_it_and_the_music_server_plays_it(rig: Rig, navidrome: NavidromeClient) -> None:
    artist, title = unique("Streamed Artist"), unique("Streamed Song")
    ref = rig.resolve(
        title=title, artists=[artist], album="Singles Club", durationMs=3000, trackNo=7, year=2024, isrc="GBAYE0900001"
    )
    assert ref["file"] is None

    rig.put(f"/likes/{ref['id']}")
    assert rig.get(f"/refs/{ref['id']}")["file"] is None, "the like is immediate; the copy comes after"
    assert rig.svc.scheduler.drain() == 1

    kept = rig.get(f"/refs/{ref['id']}")["file"]
    assert kept is not None and kept["navidromeSongId"] and kept["codec"] == "opus"
    assert kept["meta"]["albumId"] and kept["meta"]["suffix"] == "opus" and kept["meta"]["size"] > 1000, (
        "the app is told the music server's ids"
    )
    files = list((MUSIC / "Encore" / artist).rglob("*.opus"))
    assert len(files) == 1 and files[0].name.startswith("07 - ")
    # What Navidrome read from the file's tags is what the person asked for, not what the downloaded video called itself.
    found = song_of(navidrome, kept["navidromeSongId"])
    assert (found["title"], found["artist"], found["album"], found["track"], found["year"]) == (
        title,
        artist,
        "Singles Club",
        7,
        2024,
    )
    assert len(bytes_of(navidrome, kept["navidromeSongId"])) > 1000
    likes = rig.get("/library/changes", since="0")["likes"]
    assert ref["id"] in [like["ref"] for like in likes]
    assert len(rig.source.asked) == 1


def test_renaming_the_file_changes_nothing_a_person_has(rig: Rig, navidrome: NavidromeClient) -> None:
    artist, title = unique("Renamed Artist"), unique("Renamed Song")
    ref = rig.resolve(title=title, artists=[artist], album="Moves", durationMs=3000, isrc="GBAYE0900002")
    rig.put(f"/likes/{ref['id']}")
    playlist, entry = new_id("pl"), new_id("pe")
    rig.post("/playlists", {"id": playlist, "name": "Keeps"})
    rig.post(f"/playlists/{playlist}/entries", {"songs": [{"ref": ref["id"], "id": entry}]})
    rig.svc.scheduler.drain()
    first = rig.get(f"/refs/{ref['id']}")["file"]
    assert first["navidromeSongId"]
    before = rig.get("/library/changes", since="0")

    # The Host tidies the folder by hand: the file moves and is renamed.
    old = next((MUSIC / "Encore" / artist).rglob("*.opus"))
    moved = MUSIC / "Tidied" / artist / "Moves" / "renamed by hand.opus"
    moved.parent.mkdir(parents=True)
    old.rename(moved)
    scan_and_wait(navidrome)
    report = link_library(rig.svc.db, navidrome)

    after = rig.get("/library/changes", since="0")
    now = rig.get(f"/refs/{ref['id']}")["file"]
    assert report.complete
    assert now is not None and now["navidromeSongId"], "the ref has a file again, found in its new place"
    assert song_of(navidrome, now["navidromeSongId"])["title"] == title
    assert [like["ref"] for like in after["likes"]] == [like["ref"] for like in before["likes"]]
    assert [e["id"] for e in after["entries"]] == [e["id"] for e in before["entries"]] == [entry]
    assert [e["ref"] for e in after["entries"]] == [ref["id"]]
    with rig.svc.db.read() as conn:
        rows = conn.execute("SELECT navidrome_song_id FROM song_file WHERE ref = ?", (ref["id"],)).fetchall()
    assert [r["navidrome_song_id"] for r in rows] == [now["navidromeSongId"]], "one file for the ref, however it was found again"


def test_retagging_a_file_in_place_changes_nothing_a_person_has(rig: Rig, navidrome: NavidromeClient) -> None:
    artist, title = unique("Retagged Artist"), unique("Retagged Song")
    ref = rig.resolve(title=title, artists=[artist], album="Before", durationMs=3000, isrc="GBAYE0900003")
    rig.put(f"/likes/{ref['id']}")
    rig.svc.scheduler.drain()
    path = next((MUSIC / "Encore" / artist).rglob("*.opus"))

    first = rig.get(f"/refs/{ref['id']}")["file"]["navidromeSongId"]

    # Another program rewrites the tags (the album is renamed) without changing the audio: same file name, new contents.
    import os
    import time

    from tests.integration.conftest import ffmpeg

    time.sleep(1.1)  # the music server notices a changed file by its modification time, to the second
    scratch = path.with_name("scratch.opus")
    ffmpeg(
        "-i",
        str(path),
        "-map",
        "0:a",
        "-map_metadata",
        "-1",
        "-c:a",
        "copy",  # the old tags go, or the music server reads them first
        "-metadata",
        f"title={title}",
        "-metadata",
        f"artist={artist}",
        "-metadata",
        "album=After",
        str(scratch),
    )
    os.replace(scratch, path)
    scan_and_wait(navidrome)
    link_library(rig.svc.db, navidrome)

    now = rig.get(f"/refs/{ref['id']}")["file"]
    assert now["navidromeSongId"] == first, "the same file, so the same song in the music server"
    assert song_of(navidrome, now["navidromeSongId"])["album"] == "After"
    assert ref["id"] in [like["ref"] for like in rig.get("/library/changes", since="0")["likes"]]
    with rig.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref WHERE isrc = 'GBAYE0900003'").fetchone()[0] == 1


def test_a_song_that_is_deleted_from_disk_is_streamed_again_and_kept_again(rig: Rig, navidrome: NavidromeClient) -> None:
    artist, title = unique("Deleted Artist"), unique("Deleted Song")
    ref = rig.resolve(title=title, artists=[artist], album="Gone", durationMs=3000, isrc="GBAYE0900004")
    rig.put(f"/likes/{ref['id']}")
    rig.svc.scheduler.drain()
    path = next((MUSIC / "Encore" / artist).rglob("*.opus"))

    path.unlink()
    scan_and_wait(navidrome)
    report = link_library(rig.svc.db, navidrome)

    assert report.pruned == 1
    assert rig.get(f"/refs/{ref['id']}")["file"] is None, "no file any more: the app streams it"
    assert ref["id"] in [like["ref"] for like in rig.get("/library/changes", since="0")["likes"]]


def test_the_scanner_does_not_make_a_second_ref_for_a_song_the_keeper_made(rig: Rig, navidrome: NavidromeClient) -> None:
    artist, title = unique("Twice Artist"), unique("Twice Song")
    ref = rig.resolve(title=title, artists=[artist], album="One", durationMs=3000, isrc="GBAYE0900005")
    rig.put(f"/likes/{ref['id']}")
    rig.svc.scheduler.drain()

    link_library(rig.svc.db, navidrome)
    link_library(rig.svc.db, navidrome)

    with rig.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref WHERE isrc = 'GBAYE0900005'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM song_file WHERE ref = ?", (ref["id"],)).fetchone()[0] == 1


def test_the_work_folder_is_left_clean(rig: Rig, tmp_path: Path) -> None:
    ref = rig.resolve(title=unique("Clean Song"), artists=[unique("Clean Artist")], durationMs=3000)
    rig.put(f"/likes/{ref['id']}")
    rig.svc.scheduler.drain()

    assert list((tmp_path / "data" / "work").glob("keep-*")) == []


def test_a_kept_song_plays_through_the_single_address_with_range_and_covers_and_logins_work_too(
    rig: Rig, navidrome: NavidromeClient
) -> None:
    artist, title = unique("Gateway Artist"), unique("Gateway Song")
    ref = rig.resolve(title=title, artists=[artist], album="One Door", durationMs=3000, isrc="GBAYE0900006")
    rig.put(f"/likes/{ref['id']}")
    rig.svc.scheduler.drain()
    song_id = rig.get(f"/refs/{ref['id']}")["file"]["navidromeSongId"]
    query = {**rig.creds(), "v": "1.16.1", "c": "it", "f": "json"}

    ping = rig.client.get("/rest/ping.view", params=query)
    whole = rig.client.get("/rest/stream.view", params={**query, "id": song_id, "format": "raw"})
    jump = rig.client.get(
        "/rest/stream.view", params={**query, "id": song_id, "format": "raw"}, headers={"Range": "bytes=100-199"}
    )
    wrong = rig.client.get("/rest/ping.view", params={**query, "t": "0" * 32})

    assert ping.status_code == 200 and ping.json()["subsonic-response"]["status"] == "ok"
    assert whole.status_code == 200 and len(whole.content) > 1000
    assert jump.status_code == 206 and jump.content == whole.content[100:200]
    assert wrong.json()["subsonic-response"]["status"] == "failed", "Navidrome still judges its own logins"


def test_the_real_music_server_refuses_a_wrong_login_in_the_way_the_guard_expects(rig: Rig) -> None:
    """AUDIT B-41: only a REFUSAL (Subsonic error 40 to 44) is a wrong password; any other answer is "the music server is not answering" (503, not
    counted). This holds the assumption against the real thing: Navidrome answers a wrong password AND an unknown name with the same refusal, so the
    sign-in neither counts an honest person as a guesser nor tells a stranger which names exist."""
    person, password = rig.accounts["person"], rig.accounts["person_pw"]

    right = rig.client.post(f"{V1}/auth/login", json={"username": person, "password": password})
    wrong = rig.client.post(f"{V1}/auth/login", json={"username": person, "password": password + "-x"})
    nobody = rig.client.post(f"{V1}/auth/login", json={"username": unique("nobody"), "password": password})

    assert right.status_code == 200, right.text
    assert wrong.status_code == 401, wrong.text
    assert nobody.status_code == 401, nobody.text
    assert wrong.json()["error"]["code"] == nobody.json()["error"]["code"] == "unauthorized"
    assert wrong.json()["error"]["message"] == nobody.json()["error"]["message"], (
        "an unknown name is not told apart from a wrong password"
    )


def test_an_invited_person_gets_a_real_account_with_the_library_and_can_reset_and_be_removed(
    rig: Rig, navidrome: NavidromeClient
) -> None:
    from encore_server.auth import subsonic_token

    def ping(user: str, password: str) -> dict[str, Any]:
        salt = secrets.token_hex(6)
        query = {"u": user, "t": subsonic_token(password, salt), "s": salt, "v": "1.16.1", "c": "it", "f": "json"}
        return rig.client.get("/rest/ping.view", params=query).json()["subsonic-response"]  # type: ignore[no-any-return]

    def folders(user: str, password: str) -> list[Any]:
        salt = secrets.token_hex(6)
        query = {"u": user, "t": subsonic_token(password, salt), "s": salt, "v": "1.16.1", "c": "it", "f": "json"}
        body = rig.client.get("/rest/getMusicFolders.view", params=query).json()["subsonic-response"]
        return list(body.get("musicFolders", {}).get("musicFolder", []))

    make_audio(
        MUSIC / "Collection" / unique("Invite Artist") / "Album" / "01 - Invite Song.flac", title="Invite Song", artist="X"
    )
    scan_and_wait(navidrome)
    rig.get("/me")  # the first person of a new server is its owner
    invite = rig.post("/invites", {"note": "for a friend"})["invite"]
    name, password = f"friend-{secrets.token_hex(3)}", secrets.token_urlsafe(12)

    joined = rig.client.post(
        "/encore/api/v1/auth/join",
        json={"code": invite["code"], "username": name, "password": password, "displayName": "A Friend"},
    )

    assert joined.status_code == 201, joined.text
    assert ping(name, password)["status"] == "ok", "the music server knows the new account"
    assert ping(name, "not-the-password")["status"] == "failed"
    assert folders(name, password), "the new account may use the library (it is assigned when the account is made)"
    me = rig.client.get("/encore/api/v1/me", headers={"Authorization": f"Bearer {joined.json()['deviceToken']}"})
    assert me.status_code == 200 and me.json()["username"] == name

    person = next(p for p in rig.get("/people")["items"] if p["username"] == name)
    reset = rig.post(f"/people/{person['id']}/reset", {})["reset"]["code"]
    fresh = secrets.token_urlsafe(12)
    assert rig.client.post("/encore/api/v1/auth/reset", json={"code": reset, "password": fresh}).status_code == 200
    assert ping(name, fresh)["status"] == "ok" and ping(name, password)["status"] == "failed"

    removed = rig.client.delete(f"/encore/api/v1/people/{person['id']}", params=rig.creds())
    assert removed.status_code == 200
    assert ping(name, fresh)["status"] == "failed", "the account is gone from the music server"


def test_the_stars_and_playlists_a_person_had_in_the_music_server_come_over_as_likes_and_a_playlist(
    rig: Rig, navidrome: NavidromeClient
) -> None:
    from encore_server.auth import subsonic_token

    artist = unique("Moved Artist")
    for n in (1, 2, 3):
        make_audio(
            MUSIC / "Collection" / artist / "Old Album" / f"0{n} - Old {n}.flac",
            title=f"Old {n}",
            artist=artist,
            album="Old Album",
            track=str(n),
        )
    scan_and_wait(navidrome)
    ids = {s["title"]: s["id"] for s in (navidrome.songs(0, 500) or []) if s.get("artist") == artist}
    assert len(ids) == 3
    salt = secrets.token_hex(6)
    auth = {
        "u": rig.accounts["person"],
        "t": subsonic_token(rig.accounts["person_pw"], salt),
        "s": salt,
        "v": "1.16.1",
        "c": "it",
        "f": "json",
    }

    assert rig.client.get("/rest/star.view", params={**auth, "id": ids["Old 2"]}).json()["subsonic-response"]["status"] == "ok"
    made = rig.client.get(
        "/rest/createPlaylist.view", params={**auth, "name": "From before", "songId": [ids["Old 3"], ids["Old 1"]]}
    )
    assert made.json()["subsonic-response"]["status"] == "ok"

    report = rig.post("/migrate/navidrome", auth)["report"]

    assert report["likes"] == 1 and report["playlists"] == 1 and report["entries"] == 2 and report["unmatched"] == 0
    changes = rig.get("/library/changes", since="0")
    titles = {r["id"]: r["title"] for r in changes["refs"]}
    assert [titles[like["ref"]] for like in changes["likes"]] == ["Old 2"]
    mine = next(p for p in changes["playlists"] if p["name"] == "From before")
    detail = rig.get(f"/playlists/{mine['id']}")
    assert [titles[e["ref"]] for e in detail["entries"]] == ["Old 3", "Old 1"]
    assert rig.post("/migrate/navidrome", auth)["report"]["playlists"] == 0, "again: nothing twice"
