"""Songs without a picture get one from the catalogue, once per album, and every phone that has the song hears about it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from encore_server import library, refs
from encore_server.cover_finder import CoverFinder, deezer_lookup
from encore_server.db import Database

PICTURE = "https://cdn-images.dzcdn.net/images/cover/abc/1000x1000-000000-80-0-0.jpg"


def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "e.db")
    db.migrate(version="test")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO person (id, navidrome_user, display_name, role, created_at) VALUES ('pn_1','marwa','marwa','owner',0)"
        )
    return db


def liked(db: Database, title: str, artist: str = "Radiohead", album: str | None = "In Rainbows") -> str:
    with db.tx() as conn:
        ref = refs.resolve(conn, {"title": title, "artists": [artist], "album": album})
        library.set_item(conn, "pn_1", "like", ref["id"])
    return str(ref["id"])


def cover_of(db: Database, ref_id: str) -> str | None:
    with db.read() as conn:
        return refs.get_ref(conn, ref_id)["coverUrl"]  # type: ignore[no-any-return]


class Catalogue:
    def __init__(self, answers: dict[str, str | None]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def __call__(self, artist: str, title: str, album: str | None) -> str | None:
        self.asked.append(title)
        return self.answers.get(title)


def test_a_liked_song_without_a_picture_gets_one_and_its_holders_are_told(tmp_path: Path) -> None:
    db = database(tmp_path)
    ref = liked(db, "Nude")
    with db.read() as conn:
        before = library.latest_cursor(conn, "pn_1")

    report = CoverFinder(db, Catalogue({"Nude": PICTURE}), sleep=lambda _: None).run_once()

    assert (report.looked, report.found) == (1, 1)
    assert cover_of(db, ref) == PICTURE
    with db.read() as conn:
        assert library.latest_cursor(conn, "pn_1") > before, "the person's apps pull the changed song"


def test_songs_of_one_album_are_one_question(tmp_path: Path) -> None:
    db = database(tmp_path)
    ids = [liked(db, t) for t in ("Nude", "Reckoner", "Videotape")]
    catalogue = Catalogue({"Nude": PICTURE, "Reckoner": None})

    CoverFinder(db, catalogue, sleep=lambda _: None).run_once()

    # The finder asks about the songs of an album in the order of their ids, which are random within one millisecond (CI creates the three in
    # one): 'Reckoner' or 'Videotape' may be asked first and answer nothing. What the album promises is that the question stops at the song
    # that answered and that every song of the album gets that picture.
    assert catalogue.asked[-1] == "Nude", "nothing is asked after the song that answered"
    assert len(catalogue.asked) == len(set(catalogue.asked)), "no song is asked twice"
    assert [cover_of(db, i) for i in ids] == [PICTURE] * 3


def test_a_song_nothing_is_found_for_is_not_asked_about_again_soon(tmp_path: Path) -> None:
    db = database(tmp_path)
    ref = liked(db, "Obscure", artist="Nobody", album=None)
    catalogue = Catalogue({})
    finder = CoverFinder(db, catalogue, sleep=lambda _: None)

    finder.run_once()
    finder.run_once()

    assert catalogue.asked == ["Obscure"]
    assert cover_of(db, ref) is None


def test_a_song_nobody_has_and_the_server_does_not_keep_is_left_alone(tmp_path: Path) -> None:
    db = database(tmp_path)
    with db.tx() as conn:
        refs.resolve(conn, {"title": "Unheard", "artists": ["Someone"]})
    catalogue = Catalogue({"Unheard": PICTURE})

    CoverFinder(db, catalogue, sleep=lambda _: None).run_once()

    assert catalogue.asked == []


def test_a_pass_stops_at_its_limit_and_says_there_is_more(tmp_path: Path) -> None:
    db = database(tmp_path)
    for n in range(5):
        liked(db, f"Song {n}", album=f"Album {n}")

    report = CoverFinder(db, Catalogue({}), per_pass=3, sleep=lambda _: None).run_once()

    assert (report.looked, report.complete) == (3, False)


# ------------------------------------------------------------------------------------------------ the catalogue lookup


def client_for(payload: Any, status: int = 200) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)))


def hit(title: str, artist: str, album: str, cover: str = PICTURE) -> dict[str, Any]:
    return {"title": title, "artist": {"name": artist}, "album": {"title": album, "cover_xl": cover}}


def test_the_lookup_takes_the_album_of_the_same_song_and_prefers_the_album_asked_for() -> None:
    payload = {
        "data": [
            hit("Nude", "Radiohead", "Live Recordings", "https://cdn.dzcdn.net/other.jpg"),
            hit("Nude", "Radiohead", "In Rainbows"),
            hit("Nude", "Some Cover Band", "Tribute", "https://cdn.dzcdn.net/tribute.jpg"),
        ]
    }

    assert deezer_lookup("Radiohead", "Nude", "In Rainbows", client=client_for(payload)) == PICTURE
    assert deezer_lookup("Radiohead", "Nude", None, client=client_for(payload)) == "https://cdn.dzcdn.net/other.jpg"


def test_the_lookup_is_not_fooled_by_another_artist_or_another_picture_host() -> None:
    wrong_artist = {"data": [hit("Nude", "Some Cover Band", "Tribute")]}
    wrong_host = {"data": [hit("Nude", "Radiohead", "In Rainbows", "https://evil.example/x.jpg")]}

    assert deezer_lookup("Radiohead", "Nude", None, client=client_for(wrong_artist)) is None
    assert deezer_lookup("Radiohead", "Nude", None, client=client_for(wrong_host)) is None


def test_the_lookup_gives_nothing_when_the_catalogue_is_down_or_answers_nonsense() -> None:
    assert deezer_lookup("A", "B", None, client=client_for({}, status=503)) is None
    assert deezer_lookup("A", "B", None, client=client_for({"data": "nope"})) is None
    assert deezer_lookup("A", "B", None, client=client_for([])) is None


# ------------------------------------------------------------------------------------------------ the album folder


def kept_file(db: Database, music: Path, ref_id: str, relative: str) -> Path:
    path = music / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"audio")
    with db.tx() as conn:
        refs.attach_file(conn, ref_id, navidrome_song_id="nd-1", path=relative, codec="opus", bitrate_kbps=130, source="youtube")
    return path


def test_a_kept_album_gets_a_picture_file_in_its_folder_and_the_music_server_is_asked_to_scan(tmp_path: Path) -> None:
    db = database(tmp_path)
    music = tmp_path / "music"
    first = liked(db, "Nude")
    second = liked(db, "Reckoner")
    song = kept_file(db, music, first, "Encore/Radiohead/In Rainbows/03 - Nude.opus")
    kept_file(db, music, second, "Encore/Radiohead/In Rainbows/07 - Reckoner.opus")
    scans: list[int] = []

    CoverFinder(
        db,
        Catalogue({"Nude": PICTURE}),
        sleep=lambda _: None,
        music_dir=music,
        fetch=lambda url: b"jpeg-bytes",
        after=lambda: scans.append(1),
    ).run_once()

    assert (song.parent / "cover.jpg").read_bytes() == b"jpeg-bytes"
    assert scans == [1], "one scan for the whole pass"


def test_a_folder_that_has_a_picture_already_and_songs_outside_the_servers_folder_are_left_alone(tmp_path: Path) -> None:
    db = database(tmp_path)
    music = tmp_path / "music"
    mine = liked(db, "Nude")
    theirs = liked(db, "Reckoner", album="Other")
    song = kept_file(db, music, mine, "Encore/Radiohead/In Rainbows/03 - Nude.opus")
    (song.parent / "folder.png").write_bytes(b"the host's own")
    hosts = kept_file(db, music, theirs, "Hosts Collection/Radiohead/Other/07 - Reckoner.opus")
    fetched: list[str | None] = []

    def fetch(url: str | None) -> bytes:
        fetched.append(url)
        return b"jpeg"

    CoverFinder(
        db, Catalogue({"Nude": PICTURE, "Reckoner": PICTURE}), sleep=lambda _: None, music_dir=music, fetch=fetch
    ).run_once()

    assert not (song.parent / "cover.jpg").exists()
    assert not (hosts.parent / "cover.jpg").exists()
    assert fetched == []
