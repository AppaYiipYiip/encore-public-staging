"""Bringing a person's likes and playlists over from the music server."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.auth import subsonic_token
from encore_server.config import Settings
from encore_server.errors import ApiError
from tests.conftest import FakeVerifier, creds

V1 = "/encore/api/v1"


def song(n: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"nd-{n}",
        "title": f"Song {n}",
        "artist": "Artist",
        "album": "Album",
        "duration": 180 + n,
        "suffix": "flac",
        "path": f"Artist/Album/{n}.flac",
        "albumId": "al-1",
        "artistId": "ar-1",
        "coverArt": "al-1",
        **extra,
    }


class FakeMusic:
    """The music server as one person sees it."""

    def __init__(self) -> None:
        self.starred: dict[str, list[dict[str, Any]]] = {"song": [], "album": [], "artist": []}
        self.playlists: list[dict[str, Any]] = []
        self.entries: dict[str, list[dict[str, Any]]] = {}
        self.refuse = False
        self.asked: list[str] = []

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        self.asked.append(method)
        if self.refuse:
            raise ApiError("unauthorized", "no")
        if method == "getStarred2":
            return {"starred2": self.starred}
        if method == "getPlaylists":
            return {"playlists": {"playlist": self.playlists}}
        if method == "getPlaylist":
            return {"playlist": {"id": params["id"], "entry": self.entries.get(params["id"], [])}}
        raise AssertionError(method)


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier) -> Iterator[tuple[TestClient, FakeMusic]]:
    music = FakeMusic()
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    app = create_app(settings, verifier=verifier)
    app.state.services.music_as = lambda user, token, salt: music
    with TestClient(app) as client:
        yield client, music


def login(user: str = "marwa") -> dict[str, str]:
    salt = "salt1234"
    return {"u": user, "t": subsonic_token(f"pw-{user}", salt), "s": salt}


def migrate(client: TestClient, user: str = "marwa", **body: Any) -> Any:
    return client.post(f"{V1}/migrate/navidrome", params=creds(user), json={**login(user), **body})


def changes(client: TestClient, user: str = "marwa") -> dict[str, Any]:
    return client.get(f"{V1}/library/changes", params={**creds(user), "since": "0"}).json()  # type: ignore[no-any-return]


def test_likes_keep_the_time_they_were_given_and_every_song_gets_a_ref_with_its_file(rig: tuple[TestClient, FakeMusic]) -> None:
    client, music = rig
    music.starred["song"] = [song(1, starred="2025-03-01T10:00:00Z"), song(2, starred="2026-01-15T08:30:00Z")]

    report = migrate(client).json()["report"]

    assert report["likes"] == 2 and report["unmatched"] == 0
    likes = changes(client)["likes"]
    assert sorted(like["at"] for like in likes) == [1740823200000, 1768465800000]
    refs = {r["title"]: r for r in changes(client)["refs"]}
    assert refs["Song 1"]["file"]["navidromeSongId"] == "nd-1" and refs["Song 1"]["file"]["meta"]["albumId"] == "al-1"


def test_saved_albums_and_followed_artists_come_over_by_the_music_servers_ids(rig: tuple[TestClient, FakeMusic]) -> None:
    client, music = rig
    music.starred["album"] = [{"id": "al-9", "starred": "2025-01-01T00:00:00Z"}]
    music.starred["artist"] = [{"id": "ar-4", "starred": "2025-01-02T00:00:00Z"}]

    report = migrate(client).json()["report"]

    assert (report["albums"], report["artists"]) == (1, 1)
    body = changes(client)
    assert [a["id"] for a in body["savedAlbums"]] == ["al-9"] and [a["id"] for a in body["follows"]] == ["ar-4"]


def test_a_playlist_comes_with_its_songs_in_order_and_only_the_persons_own_are_taken(rig: tuple[TestClient, FakeMusic]) -> None:
    client, music = rig
    music.playlists = [
        {"id": "p1", "name": "Road trip", "owner": "marwa", "created": "2025-02-02T00:00:00Z"},
        {"id": "p2", "name": "Sara's", "owner": "sara"},
        {"id": "p3", "name": "Made for me", "owner": "marwa", "readonly": True},
    ]
    music.entries = {"p1": [song(3), song(1), song(2)]}

    report = migrate(client).json()["report"]

    assert (report["playlists"], report["entries"]) == (1, 3)
    playlist = changes(client)["playlists"][0]
    assert playlist["name"] == "Road trip" and playlist["sourceId"] == "nd:p1"
    pl = client.get(f"{V1}/playlists/{playlist['id']}", params=creds("marwa")).json()
    titles = {r["id"]: r["title"] for r in changes(client)["refs"]}
    assert [titles[e["ref"]] for e in pl["entries"]] == ["Song 3", "Song 1", "Song 2"]


def test_running_it_again_or_from_a_second_phone_makes_nothing_twice(rig: tuple[TestClient, FakeMusic]) -> None:
    client, music = rig
    music.starred["song"] = [song(1, starred="2025-03-01T10:00:00Z")]
    music.playlists = [{"id": "p1", "name": "Mix", "owner": "marwa"}]
    music.entries = {"p1": [song(1), song(2)]}
    migrate(client)

    again = migrate(client).json()["report"]

    assert again == {"likes": 0, "albums": 0, "artists": 0, "playlists": 0, "entries": 0, "unmatched": 0}
    body = changes(client)
    assert len(body["playlists"]) == 1 and len(body["likes"]) == 1 and len(body["entries"]) == 2


def test_a_song_the_scanner_already_linked_is_not_made_again(rig: tuple[TestClient, FakeMusic]) -> None:
    client, music = rig
    from encore_server import refs

    with client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        ref = refs.resolve(conn, {"title": "Song 1", "artists": ["Artist"], "durationMs": 181000})["id"]
        refs.attach_file(conn, ref, navidrome_song_id="nd-1", path="x", codec="flac", bitrate_kbps=900, source="library")
    music.starred["song"] = [song(1, starred="2025-03-01T10:00:00Z")]

    migrate(client)

    assert [r["id"] for r in changes(client)["refs"]] == [ref]


def test_a_song_without_a_title_is_counted_as_unmatched_not_lost_silently(rig: tuple[TestClient, FakeMusic]) -> None:
    client, music = rig
    music.starred["song"] = [{"id": "nd-9", "title": "", "artist": "A", "starred": "2025-03-01T10:00:00Z"}, song(1)]

    report = migrate(client).json()["report"]

    assert (report["likes"], report["unmatched"]) == (1, 1)


def test_one_persons_library_is_not_anothers(rig: tuple[TestClient, FakeMusic]) -> None:
    client, music = rig
    music.starred["song"] = [song(1, starred="2025-03-01T10:00:00Z")]
    migrate(client)

    assert changes(client, "nina")["likes"] == []


def test_it_needs_the_persons_own_music_server_login(rig: tuple[TestClient, FakeMusic]) -> None:
    client, music = rig

    wrong_person = client.post(f"{V1}/migrate/navidrome", params=creds("marwa"), json=login("nina"))
    bad_token = client.post(f"{V1}/migrate/navidrome", params=creds("marwa"), json={**login("marwa"), "t": "0" * 32})

    assert wrong_person.status_code == 401 and bad_token.status_code == 401
    assert music.asked == []


def test_a_music_server_that_refuses_is_reported_and_nothing_is_half_written(rig: tuple[TestClient, FakeMusic]) -> None:
    client, music = rig
    music.refuse = True

    assert migrate(client).status_code == 401
    assert changes(client)["likes"] == []
