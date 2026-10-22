"""When the server keeps a song (docs/04 D-3), through the HTTP API: saved (a like, a playlist), or listened to on two different days."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.ids import new_id
from tests.conftest import FakeVerifier, creds, resolve, song
from tests.test_keeper import FakeNavidrome, FakeSource, fake_ffmpeg

V1 = "/encore/api/v1"
DAY_MS = 24 * 3600 * 1000


class Configured(FakeNavidrome):
    configured = True


class Rig:
    def __init__(self, client: TestClient, music: Path) -> None:
        self.client = client
        self.music = music
        self.svc = client.app.state.services  # type: ignore[attr-defined]
        self.source: FakeSource = self.svc.youtube

    def drain(self) -> int:
        return self.svc.scheduler.drain()

    def file_of(self, ref: str, user: str = "marwa") -> dict[str, Any] | None:
        response = self.client.get(f"{V1}/refs/{ref}", params=creds(user))
        assert response.status_code == 200, response.text
        return response.json()["file"]  # type: ignore[no-any-return]

    def queued(self) -> int:
        counts = self.svc.scheduler.counts().get("keep", {})
        return int(counts.get("queued", 0))


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier, monkeypatch: pytest.MonkeyPatch) -> Iterator[Rig]:
    music = tmp_path / "music"
    music.mkdir()
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=music,
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        workers=False,
        min_free_gb=0.0,
    )
    source = FakeSource()
    navidrome = Configured(music)
    # No ffmpeg in the test: the repackaging step copies the bytes.
    monkeypatch.setattr("encore_server.keeper.keeper.run_command", fake_ffmpeg)
    with TestClient(create_app(settings, verifier=verifier, youtube=source, navidrome=navidrome)) as client:  # type: ignore[arg-type]
        yield Rig(client, music)


def test_a_server_that_can_keep_says_so(rig: Rig) -> None:
    assert "keep" in rig.client.get(f"{V1}/info").json()["features"]


def test_liking_a_song_keeps_it_in_the_background_and_the_like_is_unchanged(rig: Rig) -> None:
    ref = str(resolve(rig.client, "marwa", song())[0]["id"])

    assert rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa")).status_code == 200
    assert rig.queued() == 1 and rig.file_of(ref) is None, "the like is immediate; the copy comes later"

    rig.drain()

    file = rig.file_of(ref)
    assert file is not None and file["navidromeSongId"] == "nd-1"
    likes = rig.client.get(f"{V1}/library/changes", params={**creds("marwa"), "since": "0"}).json()["likes"]
    assert [like["ref"] for like in likes] == [ref]


def test_liking_it_again_or_by_a_second_person_is_one_copy(rig: Rig) -> None:
    ref = str(resolve(rig.client, "marwa", song())[0]["id"])

    rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    rig.client.put(f"{V1}/likes/{ref}", params=creds("nina"))
    rig.drain()
    rig.client.put(f"{V1}/likes/{ref}", params=creds("mia"))
    rig.drain()

    assert len(rig.source.asked) == 1
    assert len(list(rig.music.rglob("*.opus"))) == 1


def test_adding_songs_to_a_playlist_keeps_them(rig: Rig) -> None:
    refs = [str(r["id"]) for r in resolve(rig.client, "marwa", song(), song("Reckoner"))]
    playlist = new_id("pl")
    rig.client.post(f"{V1}/playlists", params=creds("marwa"), json={"id": playlist, "name": "Mix"})

    rig.client.post(
        f"{V1}/playlists/{playlist}/entries",
        params=creds("marwa"),
        json={"songs": [{"ref": refs[0], "id": new_id("pe")}, {"ref": refs[1], "id": new_id("pe")}]},
    )

    assert rig.queued() == 2
    rig.drain()
    assert all(rig.file_of(r) for r in refs)


def test_playing_a_song_once_or_twice_on_the_same_day_does_not_keep_it(rig: Rig) -> None:
    ref = str(resolve(rig.client, "marwa", song())[0]["id"])
    start = 1_790_000_000_000

    for n, at in enumerate((start, start + 3600_000)):
        rig.client.post(f"{V1}/plays", params=creds("marwa"), json={"id": f"p{n}", "ref": ref, "at": at, "msPlayed": 200_000})

    assert rig.queued() == 0


def test_a_song_listened_to_on_a_second_day_is_kept_even_by_another_person(rig: Rig) -> None:
    ref = str(resolve(rig.client, "marwa", song())[0]["id"])
    start = 1_790_000_000_000
    rig.client.post(f"{V1}/plays", params=creds("marwa"), json={"id": "p1", "ref": ref, "at": start, "msPlayed": 200_000})
    assert rig.queued() == 0

    rig.client.post(f"{V1}/plays", params=creds("nina"), json={"id": "p2", "ref": ref, "at": start + DAY_MS, "msPlayed": 200_000})

    assert rig.queued() == 1


def test_a_skip_is_not_a_listen(rig: Rig) -> None:
    ref = str(resolve(rig.client, "marwa", song())[0]["id"])
    start = 1_790_000_000_000
    rig.client.post(f"{V1}/plays", params=creds("marwa"), json={"id": "p1", "ref": ref, "at": start, "msPlayed": 200_000})

    rig.client.post(f"{V1}/plays", params=creds("marwa"), json={"id": "p2", "ref": ref, "at": start + DAY_MS, "msPlayed": 4_000})

    assert rig.queued() == 0


def test_a_song_the_server_already_has_is_not_queued_again(rig: Rig) -> None:
    ref = str(resolve(rig.client, "marwa", song())[0]["id"])
    rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    rig.drain()

    rig.client.put(f"{V1}/likes/{ref}", params=creds("nina"))

    assert rig.queued() == 0


def test_the_other_persons_app_is_told_when_the_copy_arrives(rig: Rig) -> None:
    ref = str(resolve(rig.client, "marwa", song())[0]["id"])
    rig.client.put(f"{V1}/likes/{ref}", params=creds("nina"))
    cursor = rig.client.get(f"{V1}/library/changes", params={**creds("nina"), "since": "0"}).json()["cursor"]

    rig.drain()

    changed = rig.client.get(f"{V1}/library/changes", params={**creds("nina"), "since": cursor}).json()
    assert changed["refs"][0]["file"]["navidromeSongId"] == "nd-1"


def test_a_server_without_a_way_to_keep_still_works_and_keeps_nothing(tmp_path: Path, verifier: FakeVerifier) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as client:
        ref = str(resolve(client, "marwa", song())[0]["id"])

        assert client.put(f"{V1}/likes/{ref}", params=creds("marwa")).status_code == 200
        assert "keep" not in client.get(f"{V1}/info").json()["features"]


def test_a_download_can_ask_for_a_song_to_be_kept_first_in_line_and_see_how_it_goes(rig: Rig) -> None:
    ref = str(resolve(rig.client, "marwa", song())[0]["id"])
    other = str(resolve(rig.client, "marwa", song("Reckoner"))[0]["id"])
    rig.client.put(f"{V1}/likes/{other}", params=creds("marwa"))  # an older keep waits in the queue

    asked = rig.client.post(f"{V1}/refs/{ref}/keep", params=creds("marwa"))

    assert asked.status_code == 200 and asked.json()["state"] == "queued"
    assert rig.client.get(f"{V1}/refs/{ref}/keep", params=creds("marwa")).json()["state"] == "queued"
    rig.svc.scheduler.run_one("background")
    assert rig.source.asked[0].title == "Weird Fishes / Arpeggi", "the song somebody is waiting for goes before the older keep"
    assert rig.client.get(f"{V1}/refs/{ref}/keep", params=creds("marwa")).json()["state"] == "kept"
    assert rig.client.post(f"{V1}/refs/{ref}/keep", params=creds("marwa")).json()["state"] == "kept"


def test_asking_to_keep_what_is_not_known_is_not_found_and_a_server_that_does_not_keep_says_so(
    tmp_path: Path, verifier: FakeVerifier
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as client:
        ref = str(resolve(client, "marwa", song())[0]["id"])

        missing = client.post(f"{V1}/refs/sr_{'0' * 26}/keep", params=creds("marwa"))
        none = client.post(f"{V1}/refs/{ref}/keep", params=creds("marwa"))

    assert missing.status_code == 404
    assert none.json()["state"] == "unavailable"
