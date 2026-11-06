"""Imports (docs/tasks P2-04): a link or a file of songs is a playlist in seconds; matching and keeping go on in the background; the counts
come from the server's import record only; Stop cancels only what nobody else wants."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.ids import new_id
from encore_server.imports.readers import Playlist, PlaylistError, Track
from encore_server.sources.youtube.errors import DownloadError
from encore_server.sources.youtube.source import Wanted
from tests.conftest import FakeVerifier, creds
from tests.test_keep_triggers import Configured
from tests.test_keeper import FakeSource, fake_ffmpeg

V1 = "/encore/api/v1"
LINK = "https://music.youtube.com/playlist?list=PLabcdefghijkl"


class FakeYoutube(FakeSource):
    """A source that finds songs by name: those in `missing` are not on YouTube, `blocked` makes every look-up fail."""

    def __init__(self) -> None:
        super().__init__()
        self.looked_up: list[str] = []
        self.missing: set[str] = set()
        self.blocked = False

    def find(self, wanted: Wanted) -> str | None:
        self.looked_up.append(wanted.title)
        if self.blocked:
            raise DownloadError("blocked")
        return None if wanted.title in self.missing else f"vid{len(self.looked_up):08d}"[:11]


def tracks(count: int, *, official: bool = False, prefix: str = "Song") -> tuple[Track, ...]:
    return tuple(
        Track(
            title=f"{prefix} {n}",
            artist="Artist",
            album="Album",
            duration_s=180 + n,
            artists=("Artist",),
            video_id=f"v{n:010d}" if official else None,
            official=official,
        )
        for n in range(1, count + 1)
    )


class Rig:
    def __init__(self, client: TestClient, source: FakeYoutube) -> None:
        self.client = client
        self.source = source
        self.svc = client.app.state.services  # type: ignore[attr-defined]
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.svc.hub.publish = lambda person, event, **kw: self.events.append((person, event))
        self.playlist = Playlist("Road trip", "youtube", "playlist", tracks(5), False)
        self.svc.imports._read = self._read

    def _read(self, url: str) -> Playlist:
        if self.failure is not None:
            raise self.failure
        return self.playlist

    failure: PlaylistError | None = None

    def post(self, user: str, body: dict[str, Any]) -> Any:
        return self.client.post(f"{V1}/imports", params=creds(user), json=body)

    def get(self, user: str, route: str) -> Any:
        response = self.client.get(f"{V1}{route}", params=creds(user))
        assert response.status_code == 200, response.text
        return response.json()

    def imported(self, user: str = "marwa", **body: Any) -> dict[str, Any]:
        response = self.post(user, {"url": LINK, **body})
        assert response.status_code == 201, response.text
        return response.json()  # type: ignore[no-any-return]

    def drain(self) -> int:
        return self.svc.scheduler.drain()


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
        scan_every_min=0,
    )
    monkeypatch.setattr("encore_server.keeper.keeper.run_command", fake_ffmpeg)
    source = FakeYoutube()
    with TestClient(create_app(settings, verifier=verifier, youtube=source, navidrome=Configured(music))) as client:  # type: ignore[arg-type]
        yield Rig(client, source)


def test_the_playlist_exists_at_once_with_every_song_in_order(rig: Rig) -> None:
    made = rig.imported()

    assert made["import"]["total"] == 5 and made["import"]["pending"] == 5 and made["import"]["state"] == "running"
    playlist = made["playlist"]
    assert playlist["name"] == "Road trip"
    assert [e["ref"] for e in playlist["entries"]] == [r["id"] for r in made["refs"]]
    assert [r["title"] for r in made["refs"]] == [f"Song {n}" for n in range(1, 6)]
    changes = rig.get("marwa", "/library/changes?since=0")
    assert [p["id"] for p in changes["playlists"]] == [made["playlistId"]] and len(changes["entries"]) == 5


def test_a_song_the_playlist_names_as_the_original_upload_is_not_searched_for(rig: Rig) -> None:
    rig.playlist = Playlist("Albums", "youtube", "playlist", tracks(3, official=True), False)

    made = rig.imported()

    assert made["import"]["matched"] == 3 and made["import"]["state"] == "done"
    assert all(r["videoId"] for r in made["refs"])
    assert rig.drain() == 3  # only the keeps; nothing to match
    assert rig.source.looked_up == []


def test_matching_finds_each_song_and_the_counts_come_from_the_import(rig: Rig) -> None:
    rig.source.missing = {"Song 2", "Song 4"}
    made = rig.imported()
    import_id = made["import"]["id"]

    rig.svc.scheduler.drain("background")

    record = rig.get("marwa", f"/imports/{import_id}")["import"]
    assert (record["total"], record["matched"], record["unmatched"], record["pending"], record["state"]) == (5, 3, 2, 0, "done")
    states = {e["position"]: e["state"] for e in rig.get("marwa", f"/imports/{import_id}/entries")["entries"]}
    assert [states[i] for i in range(5)] == ["matched", "not_found", "matched", "not_found", "matched"]


def test_a_song_the_playlist_points_at_plays_from_that_video_whatever_the_upload_and_is_never_searched_for(rig: Rig) -> None:
    """P1-05: "imported playlists play the same video they came with". Until 6 Nov 2026 only YouTube's own Topic audio was used as it came; for any
    other upload (a music video, a user's upload: most of a real playlist) the server SEARCHED first and used the playlist's video only when the
    search found nothing: importing a 288-song playlist made about 50 look-ups in five minutes, and a tap on a song not yet matched searched at tap time."""
    rig.playlist = Playlist(
        "Uploads",
        "youtube",
        "playlist",
        (
            Track("Song 1", "Artist", video_id="abcdefghijk", official=False),
            Track("Song 2", "Artist", video_id="bcdefghijkl", official=False),
        ),
        False,
    )

    made = rig.imported()

    # At once: nothing pending, so the songs play from their own videos the moment the playlist exists.
    assert (made["import"]["matched"], made["import"]["pending"], made["import"]["state"]) == (2, 0, "done")
    assert [r["videoId"] for r in made["refs"]] == ["abcdefghijk", "bcdefghijkl"]
    rig.drain()
    assert rig.source.looked_up == [], "no search at all: not at import, not later"
    with rig.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM work_item WHERE kind = 'match'").fetchone()["n"] == 0


def test_a_playlist_without_videos_is_still_matched_by_name(rig: Rig) -> None:
    """A list that came from Spotify (or a file) has no video to use: those songs are looked up with the strict match, as before."""
    made = rig.imported()  # the default five tracks have no video id

    assert made["import"]["pending"] == 5
    rig.svc.scheduler.drain("background")
    assert sorted(rig.source.looked_up) == [f"Song {n}" for n in range(1, 6)]


def test_the_kept_count_grows_as_the_background_keeps(rig: Rig) -> None:
    made = rig.imported()
    import_id = made["import"]["id"]
    assert rig.get("marwa", f"/imports/{import_id}")["import"]["kept"] == 0

    rig.drain()

    record = rig.get("marwa", f"/imports/{import_id}")["import"]
    assert record["kept"] == 5 and record["state"] == "done"


def test_progress_is_pushed_to_the_persons_devices(rig: Rig) -> None:
    rig.imported()

    rig.svc.scheduler.drain("background")

    progress = [e for person, e in rig.events if e["type"] == "import.progress"]
    assert progress and progress[-1]["matched"] == 5 and progress[-1]["state"] == "done"
    assert any(e["type"] == "library.changed" for _, e in rig.events)


def test_a_retried_request_is_the_same_import(rig: Rig) -> None:
    body = {"id": new_id("im"), "playlistId": new_id("pl")}

    first = rig.imported(**body)
    again = rig.imported(**body)

    assert again["import"]["id"] == first["import"]["id"] and again["playlistId"] == first["playlistId"]
    assert len(rig.get("marwa", "/playlists")["items"]) == 1


def test_a_list_of_songs_from_a_file_is_an_import_too(rig: Rig) -> None:
    songs = [{"title": f"File song {n}", "artists": ["Someone"], "album": "Export", "durationMs": 200000 + n} for n in range(3)]

    response = rig.post("marwa", {"name": "From Spotify export", "source": "file", "songs": songs})

    assert response.status_code == 201
    made = response.json()
    assert made["import"]["source"] == "file" and made["import"]["total"] == 3
    assert [e["ref"] for e in made["playlist"]["entries"]] == [r["id"] for r in made["refs"]]


def test_a_list_can_be_liked_instead_of_made_a_playlist_and_keeps_its_order(rig: Rig) -> None:
    songs = [{"title": f"Liked {n}", "artists": ["Someone"], "durationMs": 200000 + n} for n in range(3)]

    response = rig.post("marwa", {"name": "Liked from Spotify", "source": "file", "songs": songs, "liked": True})

    assert response.status_code == 201
    made = response.json()
    assert made["playlistId"] is None and made["playlist"] is None
    assert made["import"]["total"] == 3 and made["import"]["playlistId"] is None
    assert rig.get("marwa", "/playlists")["items"] == []
    changes = rig.get("marwa", "/library/changes?since=0")
    by_ref = {like["ref"]: like["at"] for like in changes["likes"]}
    titles = {r["id"]: r["title"] for r in made["refs"]}
    newest_first = [titles[ref] for ref, _ in sorted(by_ref.items(), key=lambda kv: -kv[1])]
    assert newest_first == ["Liked 0", "Liked 1", "Liked 2"], "the first song of the list is the newest like"


def test_a_file_import_needs_a_name_and_a_list_needs_a_link_or_songs(rig: Rig) -> None:
    assert rig.post("marwa", {"songs": [{"title": "T", "artists": ["A"]}]}).status_code == 400
    assert rig.post("marwa", {}).status_code == 400
    assert rig.post("marwa", {"name": "x", "songs": [{"title": "", "artists": []}]}).status_code == 400


@pytest.mark.parametrize(
    ("code", "status", "error"),
    [
        ("unsupported", 400, "validation"),
        ("empty", 400, "validation"),
        ("not_found", 404, "not_found"),
        ("unreachable", 502, "source_unreachable"),
    ],
)
def test_a_link_that_cannot_be_read_says_why_in_words(rig: Rig, code: str, status: int, error: str) -> None:
    rig.failure = PlaylistError(code, "A sentence for the person.")

    response = rig.post("marwa", {"url": LINK})

    assert response.status_code == status
    body = response.json()["error"]
    assert body["code"] == error and body["message"] == "A sentence for the person." and body["details"]["reason"] == code
    assert rig.get("marwa", "/playlists")["items"] == []


def test_two_people_importing_the_same_songs_cause_one_look_up_each(rig: Rig) -> None:
    rig.imported("marwa")
    rig.imported("nina")

    rig.svc.scheduler.drain("background")

    assert sorted(rig.source.looked_up) == [f"Song {n}" for n in range(1, 6)]
    for user in ("marwa", "nina"):
        assert rig.get(user, "/imports")["imports"][0]["matched"] == 5


def test_stop_cancels_what_only_this_person_wanted_and_leaves_the_rest(rig: Rig) -> None:
    rig.playlist = Playlist("Shared", "youtube", "playlist", tracks(4), False)
    mine = rig.imported("marwa")
    rig.playlist = Playlist("Overlap", "youtube", "playlist", tracks(2), False)  # Song 1 and Song 2 again
    rig.imported("nina")

    stopped = rig.client.post(f"{V1}/imports/{mine['import']['id']}/stop", params=creds("marwa")).json()["import"]
    rig.svc.scheduler.drain()

    assert stopped["state"] == "stopped"
    assert sorted(rig.source.looked_up) == ["Song 1", "Song 2"], "only the songs nina also wants were still looked up"
    nina = rig.get("nina", "/imports")["imports"][0]
    assert nina["matched"] == 2 and nina["state"] == "done"
    assert rig.get("marwa", f"/imports/{mine['import']['id']}")["import"]["state"] == "stopped"


def test_when_youtube_pushes_back_the_import_waits_and_carries_on_later(rig: Rig) -> None:
    rig.source.blocked = True
    made = rig.imported()

    rig.svc.scheduler.drain("background")

    record = rig.get("marwa", f"/imports/{made['import']['id']}")["import"]
    assert record["state"] == "running" and record["pending"] == 5, "no song is called missing because YouTube said not now"
    assert rig.svc.scheduler.counts()["match"]["queued"] == 5


def test_a_server_that_cannot_fetch_songs_says_not_found_at_once_instead_of_waiting_for_ever(
    tmp_path: Path, verifier: FakeVerifier
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as client:
        client.app.state.services.imports._read = lambda url: Playlist("P", "youtube", "playlist", tracks(2), False)  # type: ignore[attr-defined]

        made = client.post(f"{V1}/imports", params=creds("marwa"), json={"url": LINK}).json()

    assert made["import"]["unmatched"] == 2 and made["import"]["state"] == "done"


def test_a_big_import_is_quick(rig: Rig) -> None:
    rig.playlist = Playlist("Everything", "youtube", "playlist", tracks(1200), False)

    started = time.time()
    made = rig.imported()

    assert made["import"]["total"] == 1200 and len(made["playlist"]["entries"]) == 1200
    assert time.time() - started < 6, "the request only reads, resolves and records; the rest is background"


def test_somebody_elses_import_is_not_found(rig: Rig) -> None:
    made = rig.imported("marwa")

    response = rig.client.get(f"{V1}/imports/{made['import']['id']}", params=creds("nina"))

    assert response.status_code == 404


def test_the_default_reader_uses_what_the_machine_has(monkeypatch: pytest.MonkeyPatch) -> None:
    from encore_server.imports import service

    seen: dict[str, Any] = {}

    def fake_read(url: str, **kwargs: Any) -> Playlist:
        seen.update(kwargs)
        return Playlist("P", "youtube", "playlist", tracks(1), False)

    monkeypatch.setattr(service, "read_playlist", fake_read)
    monkeypatch.setattr(service.importlib.util, "find_spec", lambda name: object())

    service.default_reader()(LINK)

    assert seen["ytmusic"] is not None and seen["ytdlp"] is not None


def test_the_playlist_gets_the_picture_its_source_gave_it_at_once(rig: Rig) -> None:
    rig.playlist = Playlist("Road trip", "youtube", "playlist", tracks(2), False, cover_url="https://i.ytimg.com/vi/abc/hq.jpg")

    made = rig.imported()

    assert made["playlist"]["cover"] == "https://i.ytimg.com/vi/abc/hq.jpg"
    changes = rig.get("marwa", "/library/changes?since=0")
    assert changes["playlists"][0]["cover"] == "https://i.ytimg.com/vi/abc/hq.jpg"


def test_a_file_import_may_name_a_picture_only_on_a_host_the_readers_allow(rig: Rig) -> None:
    songs = [{"title": "T", "artists": ["A"]}]

    good = rig.post("marwa", {"name": "Good", "songs": songs, "cover": "https://i.scdn.co/image/x"}).json()
    bad = rig.post("marwa", {"name": "Bad", "songs": songs, "cover": "https://evil.example/x.jpg"}).json()
    insecure = rig.post("marwa", {"name": "Plain", "songs": songs, "cover": "http://i.scdn.co/image/x"}).json()

    assert good["playlist"]["cover"] == "https://i.scdn.co/image/x"
    assert bad["playlist"]["cover"] is None and insecure["playlist"]["cover"] is None


def test_an_import_that_finishes_in_the_background_is_told_in_the_bell_once(rig: Rig) -> None:
    rig.source.missing = {"Song 2"}
    made = rig.imported()
    assert rig.get("marwa", "/notifications")["items"] == [], "it is still running: nothing to tell yet"

    rig.svc.scheduler.drain("background")

    items = rig.get("marwa", "/notifications")["items"]
    assert [(i["kind"], i["title"], i["body"], i["route"]) for i in items] == [
        ("import_done", "Your import is ready", "Road trip: 4 of 5 songs", "/settings/import")
    ]

    rig.svc.scheduler.drain("background")
    assert len(rig.get("marwa", "/notifications")["items"]) == 1, "told once, however often the server settles it"
    assert made["import"]["id"]


def test_an_import_that_was_done_at_once_says_nothing_in_the_bell(rig: Rig) -> None:
    rig.playlist = Playlist("Albums", "youtube", "playlist", tracks(3, official=True), False)

    made = rig.imported()

    assert made["import"]["state"] == "done"
    assert rig.get("marwa", "/notifications")["items"] == [], "the person watched it finish"


def test_a_stopped_import_is_not_announced(rig: Rig) -> None:
    made = rig.imported()
    rig.client.post(f"{V1}/imports/{made['import']['id']}/stop", params=creds("marwa"))

    rig.svc.scheduler.drain("background")

    assert rig.get("marwa", "/notifications")["items"] == []


def test_a_bell_that_cannot_ring_does_not_fail_the_matching(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(rig.svc.notifications, "push", broken)
    made = rig.imported()

    rig.svc.scheduler.drain("background")

    assert rig.get("marwa", f"/imports/{made['import']['id']}")["import"]["state"] == "done"


def test_an_entry_removed_while_the_songs_are_still_being_saved_is_not_put_back(rig: Rig) -> None:
    """CF-36: a person edits an imported playlist while the server is still saving its songs: their removes stay removes."""
    made = rig.imported()
    playlist, gone = made["playlistId"], made["playlist"]["entries"][2]
    removal = rig.client.request(
        "DELETE", f"{V1}/playlists/{playlist}/entries", params=creds("marwa"), json={"entryIds": [gone["id"]]}
    )
    assert removal.status_code == 200 and removal.json()["removed"] == [gone["id"]]

    rig.drain()  # the background now matches and saves the songs, the removed one included, and finishes the import

    assert rig.get("marwa", f"/imports/{made['import']['id']}")["import"]["state"] == "done"
    entries = rig.get("marwa", f"/playlists/{playlist}")["entries"]
    assert gone["id"] not in [e["id"] for e in entries] and len(entries) == 4, "the song the person removed was not put back"
    changes = rig.get("marwa", "/library/changes?since=0")
    assert any(e["id"] == gone["id"] and e["deleted"] for e in changes["entries"]), (
        "and the removal is still sent to every device"
    )
