"""P2-12 slice 1: the routes under `/encore/api/v1/catalogue/*` (docs/17 section 3), on Deezer's real recorded answers.

What these hold: every route's shape, that a read makes NO ref, row or file (B-126, B-131: the page of a catalogue is not a song on this server), that a
catalogue that could not be asked is told apart from one that knows nothing (B-124), the validation of every id before it reaches the catalogue's address,
the limit per person, and the Host's switch (`ENCORE_CATALOGUE=0`: nothing opened, nothing listed, nothing stored).

Nothing in the phone calls these routes yet (slice 2); the answers are saved as `app/test/fixtures/server/catalogue-*.json` so that the app's parser is
written against what this server really says (ADR-R41 T5: `ENCORE_WRITE_FIXTURES=1 pytest tests/test_catalogue_api.py -k saved_fixture`).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server import deezer, refs
from encore_server.api import create_app
from encore_server.catalogue import Cache, Catalogue, fold_releases, release_key
from encore_server.config import Settings
from encore_server.deezer import CatalogueOff, DeezerClient, Gate
from tests.catalogue_fakes import ALBUM_ID, ARTIST_ID, QUOTA, RecordedDeezer, recorded
from tests.conftest import FakeVerifier, creds

V1 = "/encore/api/v1"
FIXTURES = Path(__file__).resolve().parents[3] / "app" / "test" / "fixtures" / "server"


class Rig:
    def __init__(self, client: TestClient, upstream: RecordedDeezer, catalogue: Catalogue, data: Path) -> None:
        self.client = client
        self.upstream = upstream
        self.catalogue = catalogue
        self.data = data

    def get(self, route: str, user: str = "marwa", **params: Any) -> httpx.Response:
        return self.client.get(f"{V1}{route}", params={**creds(user), **params})

    def ok(self, route: str, user: str = "marwa", **params: Any) -> dict[str, Any]:
        response = self.get(route, user, **params)
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]


def make(tmp_path: Path, verifier: FakeVerifier, *, catalogue_on: bool = True, **gate: Any) -> Iterator[Rig]:
    upstream = RecordedDeezer()
    data = tmp_path / "data"
    the_gate = Gate(**{"rate": 1000, "burst": 1000, "background_gap_s": 0.0, "enabled": catalogue_on, **gate})
    catalogue = Catalogue(
        DeezerClient(the_gate, httpx.Client(transport=upstream.transport())),
        Cache(data / "catalogue-cache.db") if catalogue_on else None,
    )
    settings = Settings(
        data_dir=data,
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        catalogue=catalogue_on,
    )
    with TestClient(create_app(settings, verifier=verifier, catalogue=catalogue)) as client:
        yield Rig(client, upstream, catalogue, data)


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier) -> Iterator[Rig]:
    yield from make(tmp_path, verifier)


@pytest.fixture()
def off(tmp_path: Path, verifier: FakeVerifier) -> Iterator[Rig]:
    yield from make(tmp_path, verifier, catalogue_on=False)


def every_text(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from every_text(item)
    elif isinstance(value, list):
        for item in value:
            yield from every_text(item)


# ------------------------------------------------------------------------------------------------------------------ info and sign-in


def test_the_catalogue_is_a_feature_with_a_state_and_every_route_needs_a_sign_in(rig: Rig) -> None:
    info = rig.client.get(f"{V1}/info").json()
    assert "catalogue" in info["features"]
    assert info["catalogue"] == {"state": "ok", "resumesInSec": 0}
    for route in (
        "/catalogue/search?q=abc",
        f"/catalogue/artists/{ARTIST_ID}",
        f"/catalogue/albums/{ALBUM_ID}",
        "/catalogue/genres",
        "/catalogue/genres/0",
    ):
        assert rig.client.get(f"{V1}{route}").status_code == 401, route
    assert rig.upstream.requests == []


# ------------------------------------------------------------------------------------------------------------------ search


def test_a_search_answers_with_artists_albums_and_songs_in_our_shape(rig: Rig) -> None:
    body = rig.ok("/catalogue/search", q="billie eilish")
    assert body["query"] == "billie eilish" and "unavailable" not in body
    artist = body["artists"][0]
    assert artist == {
        "id": "9635624",
        "name": "Billie Eilish",
        "picture": "https://cdn-images.dzcdn.net/images/artist/8eab1a9a644889aabaca1e193e05f984/1000x1000-000000-80-0-0.jpg",
        "fans": 9282134,
        "albumCount": 32,
    }
    album = body["albums"][0]
    assert album["id"] == "586786102" and album["title"] == "HIT ME HARD AND SOFT"
    assert album["artists"] == [{"id": "9635624", "name": "Billie Eilish"}]
    assert (
        album["trackCount"] == 10
        and album["recordType"] == "album"
        and album["cover"].startswith("https://cdn-images.dzcdn.net/")
    )
    song = body["tracks"][0]
    assert isinstance(song["id"], str) and song["artists"] and song["durationMs"] and song["durationMs"] % 1000 == 0
    assert rig.upstream.paths().count("/search/artist") == 1 and len(rig.upstream.requests) == 3, (
        "one request per kind: the ceiling is 7"
    )


def test_no_picture_field_is_an_address_at_the_catalogue_or_the_grey_silhouette(rig: Rig) -> None:
    for route, params in (
        ("/catalogue/search", {"q": "billie eilish"}),
        (f"/catalogue/artists/{ARTIST_ID}", {}),
        (f"/catalogue/albums/{ALBUM_ID}", {}),
        ("/catalogue/genres/0", {}),
    ):
        text = list(every_text(rig.ok(route, **params)))
        assert not [t for t in text if "api.deezer.com" in t], f"{route}: an address that tells Deezer who asked"
        assert not [t for t in text if "/images/artist//" in t], f"{route}: the picture of nobody"


def test_a_search_asks_only_for_the_kinds_named_and_says_only_those(rig: Rig) -> None:
    body = rig.ok("/catalogue/search", q="billie eilish", types="artists")
    assert set(body) == {"query", "artists", "serverTime"}
    assert rig.upstream.paths() == ["/search/artist"]


def test_a_song_comes_with_the_description_a_resolve_takes_and_never_a_video(rig: Rig) -> None:
    song = rig.ok("/catalogue/search", q="billie eilish")["tracks"][0]
    description = song["description"]
    assert refs.parse_item(description)["title"] == song["title"], "it is what `POST refs/resolve` takes, as it is"
    assert "videoId" not in description and "thumbnailUrl" not in description
    assert description["deezerId"] == song["id"] and isinstance(description["deezerId"], str)
    assert description["artists"] == [a["name"] for a in song["artists"]]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "a"},
        {"q": "x" * 201},
        {"q": "ok", "types": "bogus"},
        {"q": "ok", "types": ""},
        {"q": "ok", "limit": 0},
        {"q": "ok", "limit": 26},
        {"q": "ok", "limit": "many"},
    ],
)
def test_a_search_that_makes_no_sense_is_refused_before_anything_is_asked(rig: Rig, params: dict[str, Any]) -> None:
    response = rig.get("/catalogue/search", **params)
    assert response.status_code == 400 and response.json()["error"]["code"] == "validation"
    assert rig.upstream.requests == []


def test_a_kind_that_could_not_be_asked_is_named_and_the_others_are_still_there(rig: Rig) -> None:
    rig.upstream.overrides["/search/track"] = httpx.ReadTimeout("slow")
    body = rig.ok("/catalogue/search", q="billie eilish")
    assert body["unavailable"] == ["tracks"] and body["tracks"] == []
    assert body["artists"] and body["albums"]


def test_a_catalogue_that_refuses_is_a_busy_answer_not_an_empty_one_and_then_nothing_more_is_asked(rig: Rig) -> None:
    rig.upstream.overrides["/search/artist"] = (429, {})
    rig.upstream.overrides["/search/album"] = (429, {})
    rig.upstream.overrides["/search/track"] = (200, QUOTA)
    first = rig.get("/catalogue/search", q="billie eilish")
    assert (
        first.status_code == 503 and first.json()["error"]["code"] == "source_busy" and first.json()["error"]["retryable"] is True
    )
    asked = len(rig.upstream.requests)
    again = rig.get("/catalogue/search", q="another band")
    assert again.status_code == 503 and again.json()["error"]["retryAfterMs"] > 0
    assert len(rig.upstream.requests) == asked, "a resting catalogue is not asked, by anybody"
    info = rig.client.get(f"{V1}/info").json()
    assert info["catalogue"]["state"] == "resting" and info["catalogue"]["resumesInSec"] > 0


def test_an_outage_is_never_stored_as_nothing_found(rig: Rig) -> None:
    rig.upstream.overrides["/search/artist"] = httpx.ConnectError("down")
    assert rig.ok("/catalogue/search", q="billie eilish", types="artists,albums")["unavailable"] == ["artists"]
    del rig.upstream.overrides["/search/artist"]
    assert rig.ok("/catalogue/search", q="billie eilish", types="artists,albums")["artists"], (
        "asked again, not remembered as empty"
    )


# ------------------------------------------------------------------------------------------------------------------ the artist page


def test_an_artist_page_is_one_call_with_who_what_is_popular_and_what_was_released(rig: Rig) -> None:
    body = rig.ok(f"/catalogue/artists/{ARTIST_ID}")
    assert body["artist"]["id"] == ARTIST_ID and body["artist"]["name"] == "Bob Marley & The Wailers"
    assert body["artist"]["fans"] == 12308836 and body["artist"]["albumCount"] == 83
    assert len(body["popular"]) == 10 and body["popular"][0]["title"] == "Could You Be Loved"
    assert sorted(rig.upstream.paths()) == [f"/artist/{ARTIST_ID}", f"/artist/{ARTIST_ID}/albums", f"/artist/{ARTIST_ID}/top"], (
        "three requests: the ceiling"
    )
    assert all(r["artists"] == [{"id": ARTIST_ID, "name": "Bob Marley & The Wailers"}] for r in body["releases"]), (
        "the list names no artist: the page's own"
    )


def test_releases_come_newest_first_with_the_editions_folded(rig: Rig) -> None:
    releases = rig.ok(f"/catalogue/artists/{ARTIST_ID}")["releases"]
    dates = [r["releaseDate"] for r in releases]
    assert dates == sorted(dates, reverse=True)
    titles = [r["title"] for r in releases]
    assert "Exodus (Deluxe Edition)" in titles and "Exodus" not in titles, "the newest edition stands for the release"
    assert "Kaya - Deluxe Edition" in titles and "Kaya" not in titles
    assert len({release_key(t) for t in titles}) == len(titles)
    assert "Live! (Deluxe Edition)" in titles and "Live!" not in titles
    assert len(titles) == 50 - 3, (
        "three of the fifty recorded rows (Exodus, Kaya, Live!) were another edition of a release listed"
    )


def test_parts_choose_what_an_artist_page_asks_for(rig: Rig) -> None:
    body = rig.ok(f"/catalogue/artists/{ARTIST_ID}", parts="popular")
    assert "popular" in body and "releases" not in body
    assert sorted(rig.upstream.paths()) == [f"/artist/{ARTIST_ID}", f"/artist/{ARTIST_ID}/top"]
    assert rig.get(f"/catalogue/artists/{ARTIST_ID}", parts="everything").status_code == 400


def test_a_part_of_an_artist_page_that_could_not_be_asked_is_named(rig: Rig) -> None:
    rig.upstream.overrides[f"/artist/{ARTIST_ID}/albums"] = httpx.ReadTimeout("slow")
    body = rig.ok(f"/catalogue/artists/{ARTIST_ID}")
    assert body["unavailable"] == ["releases"] and body["releases"] == [] and len(body["popular"]) == 10


def test_an_artist_the_catalogue_does_not_have_is_not_found_and_says_why(rig: Rig) -> None:
    response = rig.get("/catalogue/artists/123456")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found" and response.json()["error"]["details"]["reason"] == "not_in_catalogue"
    assert rig.client.get(f"{V1}/info").json()["catalogue"]["state"] == "ok", (
        "a missing artist says nothing about the catalogue's health"
    )


# ------------------------------------------------------------------------------------------------------------------ albums and genres


def test_an_album_page_has_the_album_and_its_songs_in_order(rig: Rig) -> None:
    body = rig.ok(f"/catalogue/albums/{ALBUM_ID}")
    album = body["album"]
    assert album["id"] == ALBUM_ID and album["recordType"] == "album" and album["year"] == 2026 and album["trackCount"] == 18
    tracks = body["tracks"]
    assert len(tracks) == 18
    assert [t["trackNo"] for t in tracks] == list(range(1, 19)) and all(t["discNo"] == 1 for t in tracks)
    assert all(t["album"] == {"id": ALBUM_ID, "title": album["title"]} and t["cover"] == album["cover"] for t in tracks), (
        "an album's own list names no album"
    )
    first = refs.parse_item(tracks[0]["description"])
    assert (
        first["isrc"] == "USUM72604638"
        and first["track_no"] == 1
        and first["year"] == 2026
        and first["album_artist"] == "Bob Marley & The Wailers"
    )
    assert rig.upstream.paths() == [f"/album/{ALBUM_ID}", f"/album/{ALBUM_ID}/tracks"]


def test_an_album_the_catalogue_does_not_have_is_not_found_and_its_songs_are_not_asked(rig: Rig) -> None:
    response = rig.get("/catalogue/albums/999")
    assert response.status_code == 404 and response.json()["error"]["details"]["reason"] == "not_in_catalogue"
    assert rig.upstream.paths() == ["/album/999"]


def test_the_genre_list_is_ours_and_a_genre_page_is_its_chart(rig: Rig) -> None:
    genres = rig.ok("/catalogue/genres")["genres"]
    assert len(genres) == 23 and genres[0] == {"id": "132", "name": "Pop"} and all(isinstance(g["id"], str) for g in genres)
    assert rig.upstream.requests == [], "the list needs no outside request"
    chart = rig.ok("/catalogue/genres/0")
    assert len(chart["tracks"]) == 12 and len(chart["artists"]) == 15 and len(chart["albums"]) == 3
    assert chart["tracks"][0]["title"] and chart["artists"][0]["fans"] is None and chart["albums"][0]["artists"]
    assert sorted(rig.upstream.paths()) == ["/chart/0/albums", "/chart/0/artists", "/chart/0/tracks"]


# ------------------------------------------------------------------------------------------------------------------ ids are checked before they reach an address


@pytest.mark.parametrize(
    "route",
    [
        "/catalogue/artists/abc",
        "/catalogue/artists/12abc",
        "/catalogue/artists/-1",
        "/catalogue/artists/1234567890123456789",
        "/catalogue/artists/%2e%2e",
        "/catalogue/artists/1%2F..%2F2",
        "/catalogue/albums/x",
        "/catalogue/albums/1%3Fq%3D2",
        "/catalogue/genres/x",
        "/catalogue/genres/1.5",
    ],
)
def test_an_id_that_is_not_digits_never_reaches_the_catalogue_address(rig: Rig, route: str) -> None:
    response = rig.get(route)
    assert response.status_code in (400, 404), response.text
    assert rig.upstream.requests == []


# ------------------------------------------------------------------------------------------------------------------ nothing is made by a read


def counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


def test_reading_the_catalogue_makes_no_song_no_row_and_no_file(rig: Rig, tmp_path: Path) -> None:
    rig.ok("/me")  # the person exists now: signing in the first time is the one write there is
    before = counts(rig.data / "encore.db")
    assert before["song_ref"] == 0
    files_before = sorted(p.name for p in (tmp_path / "music").rglob("*"))
    rig.ok("/catalogue/search", q="billie eilish")
    rig.ok(f"/catalogue/artists/{ARTIST_ID}")
    rig.ok(f"/catalogue/albums/{ALBUM_ID}")
    rig.ok("/catalogue/genres")
    rig.ok("/catalogue/genres/0")
    assert rig.get("/catalogue/albums/999").status_code == 404
    assert counts(rig.data / "encore.db") == before, "no ref, no work item, no cache row in the library's own database"
    assert sorted(p.name for p in (tmp_path / "music").rglob("*")) == files_before
    assert "answer" not in before, "the catalogue's memory is a file of its own"
    assert (rig.data / "catalogue-cache.db").is_file()


# ------------------------------------------------------------------------------------------------------------------ limits


def test_one_person_may_make_thirty_outside_requests_a_minute_and_a_cached_answer_costs_nothing(rig: Rig) -> None:
    for n in range(10):
        rig.ok("/catalogue/search", q=f"billie eilish {n}")  # three outside requests each: thirty
    rig.ok("/catalogue/search", q="billie eilish 0")  # remembered: nothing asked, nothing charged
    refused = rig.get("/catalogue/search", q="billie eilish 11")
    assert (
        refused.status_code == 429
        and refused.json()["error"]["code"] == "rate_limited"
        and refused.json()["error"]["retryAfterMs"] > 0
    )
    assert rig.get("/catalogue/search", "nina", q="billie eilish 11").status_code == 200, "the limit is each person's own"


# ------------------------------------------------------------------------------------------------------------------ the Host's switch


def test_a_catalogue_switched_off_is_not_listed_opens_nothing_and_stores_nothing(off: Rig) -> None:
    info = off.client.get(f"{V1}/info").json()
    assert "catalogue" not in info["features"] and info["catalogue"] == {"state": "off", "resumesInSec": 0}
    for route in (
        "/catalogue/search?q=abcd",
        f"/catalogue/artists/{ARTIST_ID}",
        f"/catalogue/albums/{ALBUM_ID}",
        "/catalogue/genres",
        "/catalogue/genres/0",
    ):
        response = off.get(route)
        assert response.status_code == 404, route
        assert (
            response.json()["error"]["code"] == "not_found" and response.json()["error"]["details"]["reason"] == "catalogue_off"
        )
    assert off.upstream.requests == []
    assert not (off.data / "catalogue-cache.db").exists()
    with pytest.raises(CatalogueOff):
        deezer.search_tracks("Radiohead", "Nude")


def test_the_default_wiring_gives_the_finders_the_apps_own_gate_and_the_cache_its_own_file(
    tmp_path: Path, verifier: FakeVerifier
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as client:
        installed = deezer.installed()
        assert installed is not None and installed.gate.state() == {"state": "ok", "resumesInSec": 0}
        assert client.get(f"{V1}/info").json()["catalogue"]["state"] == "ok"
        assert (tmp_path / "data" / "catalogue-cache.db").is_file()
    assert deezer.installed() is None, "a server that has stopped leaves no gate behind"
    switched = Settings(
        data_dir=tmp_path / "data2",
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        catalogue=False,
    )
    with TestClient(create_app(switched, verifier=verifier)):
        installed = deezer.installed()
        assert installed is not None and installed.gate.state()["state"] == "off"
    assert not (tmp_path / "data2" / "catalogue-cache.db").exists()


def test_the_switch_is_read_from_the_environment() -> None:
    assert Settings.from_env({}).catalogue is True
    for value in ("0", "false", "No", " 0 "):
        assert Settings.from_env({"ENCORE_CATALOGUE": value}).catalogue is False
    assert Settings.from_env({"ENCORE_CATALOGUE": "1"}).catalogue is True


# ------------------------------------------------------------------------------------------------------------------ no text in the log


def test_what_a_person_typed_is_not_in_the_log(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        rig.ok("/catalogue/search", q="a private band name")
        rig.ok("/catalogue/search", q="nobody at all zzz", types="artists")
    assert "private band" not in caplog.text.lower() and "nobody at all" not in caplog.text.lower()


# ------------------------------------------------------------------------------------------------------------------ pure: editions


def album(title: str, date: str) -> dict[str, Any]:
    return {"id": title, "title": title, "artists": [], "releaseDate": date, "year": int(date[:4])}


def test_editions_of_one_release_are_one_and_two_scripts_are_never_one() -> None:
    folded = fold_releases(
        [
            album("Legend", "2001-01-01"),
            album("Legend (Deluxe Edition)", "2020-02-07"),
            album("Legend (Remastered 2002)", "2002-05-01"),
            album("The Legend", "2005-01-01"),
        ]
    )
    assert [a["title"] for a in folded] == ["Legend (Deluxe Edition)"], (
        "the editions and the one with 'The' are one release; the newest stands"
    )
    arabic, russian, other = "فيروز", "Кино", "فيروز (Deluxe Edition)"
    kept = fold_releases(
        [album(arabic, "2001-01-01"), album(russian, "2002-01-01"), album("!!!", "2003-01-01"), album("???", "2004-01-01")]
    )
    assert len(kept) == 4, (
        "a title with no Latin letter is not folded to nothing and merged with another (B-37), and symbols alone never merge"
    )
    assert release_key(arabic) and release_key(russian) and release_key(arabic) != release_key(russian)
    assert release_key(other) == release_key(arabic), "an edition suffix goes in any script's title"
    assert release_key("!!!") == "" and release_key("???") == ""


# ------------------------------------------------------------------------------------------------------------------ the saved real responses


def saved(name: str, body: dict[str, Any]) -> None:
    """ADR-R41 T5 (one contract): the server's own test saves what the route REALLY answers, on the recorded catalogue, and the app's parser reads it.
    When an answer changes, the test fails until the file is written again with `ENCORE_WRITE_FIXTURES=1`. Nothing in them is a person's data."""
    body = {k: v for k, v in body.items() if k != "serverTime"}
    path = FIXTURES / f"catalogue-{name}.json"
    text = json.dumps(body, indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("ENCORE_WRITE_FIXTURES") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.is_file(), "run with ENCORE_WRITE_FIXTURES=1 once to write it"
    assert json.loads(path.read_text(encoding="utf-8")) == body


def test_the_answers_are_the_saved_fixtures_the_phones_parser_reads(rig: Rig) -> None:
    saved("search", rig.ok("/catalogue/search", q="billie eilish"))
    saved("artist-page", rig.ok(f"/catalogue/artists/{ARTIST_ID}"))
    saved("album", rig.ok(f"/catalogue/albums/{ALBUM_ID}"))
    saved("genres", rig.ok("/catalogue/genres"))
    saved("genre", rig.ok("/catalogue/genres/0"))
    assert recorded("artist")["id"] == int(ARTIST_ID)
