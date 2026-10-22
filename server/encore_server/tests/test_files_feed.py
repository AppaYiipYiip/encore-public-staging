"""The feed of the server's files (`GET /library/files`): the app's browse index of what the server keeps, one first pass and then changes."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from encore_server import refs
from encore_server.db import Database
from encore_server.scanner import link_library
from tests.conftest import creds
from tests.test_scanner import FakeLibrary, entry

V1 = "/encore/api/v1"


def feed(client: TestClient, since: str = "0", **extra: str) -> dict[str, Any]:
    response = client.get(f"{V1}/library/files", params={**creds("marwa"), "since": since, **extra})
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def attach(db: Database, n: int, **meta: Any) -> str:
    with db.tx() as conn:
        ref = str(refs.resolve(conn, {"title": f"Song {n}", "artists": ["Artist"], "durationMs": 200000 + n})["id"])
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id=f"nd-{n}",
            path=f"A/{n}.opus",
            codec="opus",
            bitrate_kbps=128,
            source="library",
            meta=meta or None,
        )
    return ref


def test_a_first_pass_lists_every_song_the_server_has_with_the_music_servers_ids(client: TestClient) -> None:
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    ref = attach(db, 1, albumId="al-9", artistId="ar-9", coverArt="al-9", size=1234)
    attach(db, 2)

    body = feed(client)

    assert [r["title"] for r in body["refs"]] == ["Song 1", "Song 2"]
    first = next(r for r in body["refs"] if r["id"] == ref)
    assert first["file"]["navidromeSongId"] == "nd-1"
    assert first["file"]["meta"] == {"albumId": "al-9", "artistId": "ar-9", "coverArt": "al-9", "size": 1234}


def test_then_only_what_changed(client: TestClient) -> None:
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    attach(db, 1)
    cursor = feed(client)["cursor"]

    unchanged = feed(client, cursor)
    attach(db, 2)
    changed = feed(client, cursor)

    assert unchanged["refs"] == [] and unchanged["cursor"] == cursor
    assert [r["title"] for r in changed["refs"]] == ["Song 2"]


def test_attaching_what_is_already_attached_writes_nothing_to_the_feed(client: TestClient) -> None:
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    attach(db, 1, albumId="al-1")
    cursor = feed(client)["cursor"]

    attach(db, 1, albumId="al-1")

    assert feed(client, cursor)["refs"] == []


def test_a_file_whose_description_changed_is_in_the_feed_again(client: TestClient) -> None:
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    attach(db, 1, albumId="al-1")
    cursor = feed(client)["cursor"]

    attach(db, 1, albumId="al-2")

    assert feed(client, cursor)["refs"][0]["file"]["meta"]["albumId"] == "al-2"


def test_a_song_that_lost_its_file_comes_back_with_none(client: TestClient) -> None:
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    lib = FakeLibrary([entry(1), entry(2)])
    link_library(db, lib)
    cursor = feed(client)["cursor"]

    lib.songs_ = [entry(2)]
    link_library(db, lib)

    gone = feed(client, cursor)["refs"]
    assert [(r["title"], r["file"]) for r in gone] == [("Song 1", None)]


def test_a_big_library_comes_in_pages(client: TestClient) -> None:
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    for n in range(7):
        attach(db, n)

    first = feed(client, limit="3")
    second = feed(client, first["cursor"], limit="3")
    third = feed(client, second["cursor"], limit="3")

    assert (len(first["refs"]), first["more"]) == (3, True)
    assert (len(second["refs"]), second["more"]) == (3, True)
    assert (len(third["refs"]), third["more"]) == (1, False)
    seen = {r["id"] for page in (first, second, third) for r in page["refs"]}
    assert len(seen) == 7


def test_the_feed_needs_a_login(client: TestClient) -> None:
    assert client.get(f"{V1}/library/files").status_code == 401
