"""Artists the music server has no picture for get one (N-15): found by one of their own songs, written as `artist.jpg` in their own kept folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from encore_server import refs
from encore_server.artist_finder import (
    RETRY_AFTER_MS,
    ArtistFinder,
    deezer_artist_picture,
    pick_artist_picture,
)
from encore_server.db import Database
from encore_server.deezer import LookupUnavailable
from encore_server.navidrome import NavidromeClient

PICTURE = "https://cdn-images.dzcdn.net/images/artist/c8241e15efdefa9465c7b470643efb3b/1000x1000-000000-80-0-0.jpg"
OTHER = "https://cdn-images.dzcdn.net/images/artist/ffffffffffffffffffffffffffffffff/1000x1000-000000-80-0-0.jpg"
EMPTY = "https://cdn-images.dzcdn.net/images/artist//1000x1000-000000-80-0-0.jpg"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-bytes"

# ------------------------------------------------------------------------------------------------ choosing the artist's picture


def track(title: str, artist: str, picture: str = PICTURE, **extra: Any) -> dict[str, Any]:
    return {"title": title, "artist": {"id": 719, "name": artist, "picture_xl": picture, **extra}}


@pytest.mark.parametrize(
    ("artist", "title", "hits", "expected"),
    [
        # What the owner saw: the music server's name matching wants the same name, and the catalogue lists the group.
        ("Bob Marley", "Could You Be Loved", [track("Could You Be Loved", "Bob Marley & The Wailers")], PICTURE),
        ("Jay-Z", "Numb / Encore", [track("Numb/Encore", "JAY Z")], PICTURE),
        ("Goo Goo Dolls", "Iris", [track("Iris", "The Goo Goo Dolls")], PICTURE),
        ("Mac Miller", "Self Care", [track("Self Care", "Mac Miller")], PICTURE),
        # The same title by somebody else says nothing about this artist: the artist must be ours.
        ("Bob Marley", "Could You Be Loved", [track("Could You Be Loved (Bob Marley)", "Charlie Parra Del Riego")], None),
        # The title must be the song asked for.
        ("Bob Marley", "Could You Be Loved", [track("Jamming", "Bob Marley & The Wailers")], None),
        # Our artist is the second name of a credit: the picture is of somebody else.
        ("The Wailers", "Is This Love", [track("Is This Love", "Bob Marley & The Wailers")], None),
        # Our name is a list of people ("A, B"), the catalogue's is one of them: that is not the same artist.
        ("Lauren Babic, Eric July", "Song", [track("Song", "Lauren Babic")], None),
        # An artist with no picture of its own shows a grey silhouette: dropped BEFORE choosing, so the namesake with a real picture wins.
        (
            "Mac Miller",
            "Self Care",
            [track("Self Care", "Mac Miller", EMPTY), track("Self Care", "MAC MILLER", OTHER)],
            OTHER,
        ),
        ("Mac Miller", "Self Care", [track("Self Care", "Mac Miller", EMPTY)], None),
        # A picture from anywhere else is never fetched.
        ("Mac Miller", "Self Care", [track("Self Care", "Mac Miller", "https://evil.example/a.jpg")], None),
        # The name itself beats a lead name of a credit, whatever the catalogue's order.
        (
            "Prince",
            "Kiss",
            [track("Kiss", "Prince & The Revolution", OTHER), track("Kiss", "Prince", PICTURE)],
            PICTURE,
        ),
        # Names that fold to nothing (not written in Latin letters) are never equal to each other.
        ("박광현", "노래", [track("노래", "박광현")], None),
        ("Mac Miller", "", [track("", "Mac Miller")], None),
    ],
)
def test_the_artist_is_known_by_one_of_its_own_songs(
    artist: str, title: str, hits: list[dict[str, Any]], expected: str | None
) -> None:
    found = pick_artist_picture(hits, artist=artist, title=title)

    assert (found.url if found else None) == expected


def client_for(payload: Any, status: int = 200) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)))


def test_the_lookup_gives_the_picture_of_the_artist_of_the_song_asked_for() -> None:
    payload = {"data": [track("Could You Be Loved", "Bob Marley & The Wailers")]}

    assert deezer_artist_picture("Bob Marley", "Could You Be Loved", None, client=client_for(payload)) == PICTURE
    assert deezer_artist_picture("Somebody Else", "Could You Be Loved", None, client=client_for(payload)) is None
    assert deezer_artist_picture("Bob Marley", "Could You Be Loved", None, client=client_for({"data": []})) is None


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({}, 503),
        ({}, 429),
        ({"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}}, 200),
        ({"data": "nope"}, 200),
        ([], 200),
    ],
)
def test_a_catalogue_that_cannot_be_asked_is_not_a_catalogue_that_knows_nothing(payload: Any, status: int) -> None:
    with pytest.raises(LookupUnavailable):
        deezer_artist_picture("Bob Marley", "Could You Be Loved", None, client=client_for(payload, status))


def test_a_catalogue_that_does_not_answer_is_not_a_catalogue_that_knows_nothing() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(LookupUnavailable):
        deezer_artist_picture("A", "B", None, client=httpx.Client(transport=httpx.MockTransport(refuse)))


# ------------------------------------------------------------------------------------------------ the finder


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000_000

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


class Music:
    """The music server's side: the artists it lists with no picture, and whether it is scanning."""

    def __init__(self, artists: list[tuple[str, str]] | None, *, scanning: bool | None = False) -> None:
        self.artists = artists
        self.busy = scanning

    def artists_without_picture(self) -> list[tuple[str, str]] | None:
        return self.artists

    def scanning(self) -> bool | None:
        return self.busy


class Catalogue:
    """What the catalogue answers for an artist's name: a picture address, nothing, or an exception for 'could not ask'."""

    def __init__(self, answers: dict[str, str | None | Exception]) -> None:
        self.answers = answers
        self.asked: list[tuple[str, str]] = []

    def __call__(self, artist: str, title: str, album: str | None) -> str | None:
        self.asked.append((artist, title))
        answer = self.answers.get(artist)
        if isinstance(answer, Exception):
            raise answer
        return answer


def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "e.db")
    db.migrate(version="test")
    return db


def kept(
    db: Database,
    music: Path,
    artist: str,
    title: str,
    *,
    album: str = "Uprising",
    folder: str | None = None,
    relative: str | None = None,
) -> Path:
    """A song of [artist] the server keeps: a ref, a file where the keeper puts it (`Encore/<artist>/<album>/...`)."""
    relative = relative or f"Encore/{folder or artist}/{album}/{title}.opus"
    with db.tx() as conn:
        ref = refs.resolve(conn, {"title": title, "artists": [artist], "album": album, "albumArtist": artist})
        refs.attach_file(
            conn, ref["id"], navidrome_song_id=f"nd-{title}", path=relative, codec="opus", bitrate_kbps=130, source="youtube"
        )
    path = music / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"audio")
    return path


def finder(
    db: Database,
    music: Path,
    listed: list[tuple[str, str]] | None,
    catalogue: Catalogue,
    clock: Clock,
    *,
    fetch: Any = None,
    after: Any = None,
    **options: Any,
) -> ArtistFinder:
    return ArtistFinder(
        db,
        Music(listed),
        catalogue,
        music_dir=music,
        fetch=fetch or (lambda url: JPEG),
        after=after,
        sleep=lambda _: None,
        clock=clock,
        **options,
    )


def test_an_artist_without_a_picture_gets_artist_jpg_in_its_own_folder_and_the_music_server_is_asked_to_scan(
    tmp_path: Path,
) -> None:
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    song = kept(db, music, "Bob Marley", "Could You Be Loved")
    scans: list[int] = []
    the = finder(db, music, [("ar-1", "Bob Marley")], Catalogue({"Bob Marley": PICTURE}), clock, after=lambda: scans.append(1))

    report = the.run_once()

    assert (report.looked, report.found) == (1, 1)
    assert (song.parent.parent / "artist.jpg").read_bytes() == JPEG, "in the artist's folder, not in the album's"
    assert not (song.parent / "artist.jpg").exists()
    assert scans == [1], "one scan for the whole pass"


def test_an_artist_is_asked_about_with_its_own_songs_and_the_asking_stops_at_the_first_answer(tmp_path: Path) -> None:
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    for title in ("One", "Two", "Three", "Four"):
        kept(db, music, "Bob Marley", title)
    catalogue = Catalogue({"Bob Marley": None})
    the = finder(db, music, [("ar-1", "Bob Marley")], catalogue, clock)

    the.run_once()

    assert len(catalogue.asked) == 3, "at most three songs: a few real look-ups, never a sweep"
    assert {artist for artist, _ in catalogue.asked} == {"Bob Marley"}
    assert {title for _, title in catalogue.asked} <= {"One", "Two", "Three", "Four"}, "only songs the artist really has"


def test_a_picture_the_host_put_in_the_folder_is_left_alone(tmp_path: Path) -> None:
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    song = kept(db, music, "Bob Marley", "Could You Be Loved")
    theirs = song.parent.parent / "Artist.PNG"
    theirs.write_bytes(b"the host's own")
    catalogue = Catalogue({"Bob Marley": PICTURE})
    fetched: list[str | None] = []

    def fetch(url: str | None) -> bytes:
        fetched.append(url)
        return JPEG

    the = finder(db, music, [("ar-1", "Bob Marley")], catalogue, clock, fetch=fetch)
    the.run_once()

    assert theirs.read_bytes() == b"the host's own"
    assert not (song.parent.parent / "artist.jpg").exists()
    assert (catalogue.asked, fetched) == ([], []), "nothing is asked of the catalogue for a picture that is there"


def test_an_artist_whose_songs_are_not_in_the_servers_own_folder_costs_no_look_up_and_nothing_is_written(tmp_path: Path) -> None:
    """The Host's own music is never written to; and asking the catalogue for a picture with nowhere to put it would be a wasted look-up."""
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    kept(db, music, "Bob Marley", "Could You Be Loved", relative="Hosts Collection/Bob Marley/Uprising/Could You Be Loved.opus")
    catalogue = Catalogue({"Bob Marley": PICTURE})
    the = finder(db, music, [("ar-1", "Bob Marley")], catalogue, clock)

    report = the.run_once()

    assert (report.looked, catalogue.asked) == (0, [])
    assert not list(music.rglob("artist.*"))


@pytest.mark.parametrize(
    "relative",
    [
        "Encore/Could You Be Loved.opus",  # straight in the server's folder: a picture there would become every artist's picture
        "Encore/../Elsewhere/Uprising/Could You Be Loved.opus",
        "Encore/./Uprising/Could You Be Loved.opus",
        "/Encore/Bob Marley/Uprising/Could You Be Loved.opus",
    ],
)
def test_nothing_is_ever_written_where_it_would_become_another_artists_picture(tmp_path: Path, relative: str) -> None:
    """The music server looks for an artist's picture in its folder and then in every folder above it, up to three levels."""
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    kept(db, music, "Bob Marley", "Could You Be Loved", relative="Encore/Bob Marley/Uprising/Other.opus")
    (music / "Encore" / "Bob Marley" / "Uprising" / "Other.opus").unlink()
    with db.tx() as conn:
        conn.execute("UPDATE song_file SET path = ?", (relative,))
    catalogue = Catalogue({"Bob Marley": PICTURE})
    the = finder(db, music, [("ar-1", "Bob Marley")], catalogue, clock)

    the.run_once()

    assert catalogue.asked == []
    assert not list(tmp_path.rglob("artist.*"))


def test_a_miss_is_remembered_for_a_week_and_asked_again_after_it(tmp_path: Path) -> None:
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    kept(db, music, "Nobody", "Obscure")
    catalogue = Catalogue({"Nobody": None})
    the = finder(db, music, [("ar-1", "Nobody")], catalogue, clock)

    the.run_once()
    the.run_once()
    assert catalogue.asked == [("Nobody", "Obscure")], "asked once, not at every pass"

    clock.advance(RETRY_AFTER_MS + 1)
    the.run_once()
    assert catalogue.asked == [("Nobody", "Obscure")] * 2, "asked again after the window"


def test_a_look_up_that_could_not_be_made_is_not_a_miss_and_ends_the_pass(tmp_path: Path) -> None:
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    kept(db, music, "Bob Marley", "Could You Be Loved")
    kept(db, music, "Jay-Z", "Numb")
    catalogue = Catalogue({"Bob Marley": LookupUnavailable("HTTP 429"), "Jay-Z": PICTURE})
    the = finder(db, music, [("ar-1", "Bob Marley"), ("ar-2", "Jay-Z")], catalogue, clock)

    report = the.run_once()

    assert catalogue.asked == [("Bob Marley", "Could You Be Loved")], "the catalogue is not hammered once it has said no"
    assert report.complete is False
    catalogue.answers["Bob Marley"] = PICTURE
    the.run_once()
    assert ("Bob Marley", "Could You Be Loved") in catalogue.asked[1:], "asked again at the next pass: nothing was remembered"
    assert (music / "Encore" / "Bob Marley" / "artist.jpg").exists()


def test_a_pass_stops_at_its_limit_and_goes_on_at_the_next(tmp_path: Path) -> None:
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    names = [f"Artist {n}" for n in range(5)]
    for name in names:
        kept(db, music, name, "Song")
    catalogue = Catalogue({})
    the = finder(db, music, [(f"ar-{n}", name) for n, name in enumerate(names)], catalogue, clock, per_pass=2)

    first = the.run_once()
    second = the.run_once()

    assert (first.looked, first.complete) == (2, False)
    assert second.looked == 2
    assert len({artist for artist, _ in catalogue.asked}) == 4, "the second pass takes other artists, not the same two again"


def test_a_music_server_that_is_scanning_or_silent_is_left_alone(tmp_path: Path) -> None:
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    kept(db, music, "Bob Marley", "Could You Be Loved")
    catalogue = Catalogue({"Bob Marley": PICTURE})
    scanning = ArtistFinder(
        db, Music([("ar-1", "Bob Marley")], scanning=True), catalogue, music_dir=music, sleep=lambda _: None, clock=clock
    )
    silent = ArtistFinder(db, Music(None), catalogue, music_dir=music, sleep=lambda _: None, clock=clock)

    for the in (scanning, silent):
        the.run_once()

    assert catalogue.asked == []


def test_something_that_is_not_a_picture_is_not_written(tmp_path: Path) -> None:
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    kept(db, music, "Bob Marley", "Could You Be Loved")
    scans: list[int] = []
    the = finder(
        db,
        music,
        [("ar-1", "Bob Marley")],
        Catalogue({"Bob Marley": PICTURE}),
        clock,
        fetch=lambda url: b"<html>not a picture</html>",
        after=lambda: scans.append(1),
    )

    report = the.run_once()

    assert (report.looked, report.found) == (1, 0)
    assert not list(tmp_path.rglob("artist.*")) and scans == []


def test_an_artist_with_no_songs_of_its_own_is_not_asked_about(tmp_path: Path) -> None:
    """A name the music server lists but whose songs the server does not hold (a guest on somebody else's album) has nothing to be known by."""
    db, music, clock = database(tmp_path), tmp_path / "music", Clock()
    kept(db, music, "Bob Marley", "Could You Be Loved")
    catalogue = Catalogue({"Ziggy Marley": PICTURE})
    the = finder(db, music, [("ar-9", "Ziggy Marley")], catalogue, clock)

    the.run_once()

    assert catalogue.asked == []


# ------------------------------------------------------------------------------------------------ what the music server says


def artists_reply(*artists: dict[str, Any]) -> httpx.Client:
    body = {"subsonic-response": {"status": "ok", "artists": {"index": [{"name": "B", "artist": list(artists)}]}}}
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))


def test_the_artists_without_a_picture_are_the_ones_the_music_server_lists_with_no_cover_and_with_an_album() -> None:
    client = NavidromeClient(
        "http://music",
        "admin",
        "pw",
        client=artists_reply(
            {"id": "a1", "name": "Has one", "coverArt": "ar-a1_x", "albumCount": 1},
            {"id": "a2", "name": "Bob Marley", "albumCount": 2},
            {"id": "a3", "name": "A name with no album", "albumCount": 0},
            {"id": "a4", "name": "", "albumCount": 1},
        ),
    )

    assert client.artists_without_picture() == [("a2", "Bob Marley")]


def test_a_music_server_that_does_not_answer_has_no_list_of_artists() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = NavidromeClient("http://music", "admin", "pw", client=httpx.Client(transport=httpx.MockTransport(refuse)))

    assert client.artists_without_picture() is None
