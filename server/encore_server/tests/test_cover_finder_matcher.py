"""N-34 slice 2 closes audit B-133 (a) and (c-for-the-finder): the cover finder takes its picture through the SAME matcher as the album pass (`album_finder.judge_hits`: the
artist, the title AND the version, and the length), not through a plain name comparison.

What was wrong, run on the code of 22 Nov 2026 (`cover_finder.deezer_lookup`): it compared `artist_key` and `title_key` and nothing else. `title_key` strips brackets, so "Nude"
and "Nude (Live)" are one key, and the first hit of equal score won: a live upload got a studio album's picture and a studio song got a live record's. The version signature
and the length (the only thing that tells "Fade Into You (Edit)" from the album cut) were never looked at.

**What a picture costs, said plainly** (the design's cost list for the finder): a YouTube song whose import listing is more than 3 s off the catalogue's length loses its
catalogue picture and keeps the video's thumbnail (the kept FILE's own length is used when the music folder is known); a song with no length at all is not looked up (settled,
asked again in 7 days); the songs the album pass matches get their picture from the pass and are not asked here at all.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import httpx
import pytest

from encore_server import refs
from encore_server.cover_finder import CoverFinder, deezer_lookup
from encore_server.db import Database
from tests.test_cover_finder import PICTURE, client_for, cover_of, database, liked

STUDIO = "https://cdn.dzcdn.net/studio.jpg"
LIVE = "https://cdn.dzcdn.net/live.jpg"
OTHER = "https://cdn.dzcdn.net/other.jpg"


def hit(ident: int, title: str, artist: str, album: str, duration: int, cover: str = PICTURE) -> dict[str, Any]:
    """A search row as Deezer sends one: an id, a title, a length in SECONDS, the artist and the album (id, title, picture)."""
    return {
        "id": ident,
        "title": title,
        "duration": duration,
        "artist": {"id": 1, "name": artist},
        "album": {"id": ident * 10, "title": album, "cover_xl": cover},
    }


class Counting:
    """A catalogue client that serves one payload and counts the requests."""

    def __init__(self, payload: Any) -> None:
        self.requests = 0

        def serve(request: httpx.Request) -> httpx.Response:
            self.requests += 1
            return httpx.Response(200, json=payload)

        self.client = httpx.Client(transport=httpx.MockTransport(serve))


# ------------------------------------------------------------------------------------------------------------------ the version (B-133 a)


def test_a_live_record_is_not_the_song_so_its_picture_is_not_taken() -> None:
    payload = {"data": [hit(1, "Nude (Live)", "Radiohead", "Live Recordings", 215, LIVE)]}
    assert deezer_lookup("Radiohead", "Nude", "In Rainbows", length_ms=215_000, client=client_for(payload)) is None


def test_the_studio_hit_gives_the_picture_whichever_order_the_catalogue_lists_it_in() -> None:
    both = [
        hit(1, "Nude (Live)", "Radiohead", "Live Recordings", 215, LIVE),
        hit(2, "Nude", "Radiohead", "In Rainbows", 215, STUDIO),
    ]
    for order in (both, both[::-1]):
        assert deezer_lookup("Radiohead", "Nude", None, length_ms=215_000, client=client_for({"data": order})) == STUDIO


def test_a_live_upload_is_not_given_a_studio_albums_picture_when_the_title_says_live() -> None:
    """The reverse: the song asked for IS the live version, and the studio hit (the same key once the brackets are gone) is not it."""
    payload = {"data": [hit(2, "Nude", "Radiohead", "In Rainbows", 215, STUDIO)]}
    assert deezer_lookup("Radiohead", "Nude (Live)", None, length_ms=215_000, client=client_for(payload)) is None


def test_the_album_asked_for_is_preferred_and_the_first_hit_is_the_fallback() -> None:
    payload = {
        "data": [
            hit(1, "Nude", "Radiohead", "Live Recordings", 215, OTHER),
            hit(2, "Nude", "Radiohead", "In Rainbows", 215),
            hit(3, "Nude", "Some Cover Band", "Tribute", 215, "https://cdn.dzcdn.net/tribute.jpg"),
        ]
    }
    assert deezer_lookup("Radiohead", "Nude", "In Rainbows", length_ms=215_000, client=client_for(payload)) == PICTURE
    assert deezer_lookup("Radiohead", "Nude", None, length_ms=215_000, client=client_for(payload)) == OTHER


# ------------------------------------------------------------------------------------------------------------------ the length


@pytest.mark.parametrize(
    ("length_ms", "found"), [(212_000, True), (218_000, True), (211_999, False), (218_001, False), (300_000, False)]
)
def test_the_length_must_be_within_the_tolerance_of_the_catalogues(length_ms: int, found: bool) -> None:
    """The edit and the album cut of one song have the same empty version signature: only the length tells them apart (the matcher's tolerance, 3 s, inclusive)."""
    payload = {"data": [hit(1, "Nude", "Radiohead", "In Rainbows", 215, STUDIO)]}
    assert (deezer_lookup("Radiohead", "Nude", None, length_ms=length_ms, client=client_for(payload)) == STUDIO) is found


def test_a_song_with_no_length_or_a_name_with_nothing_to_compare_is_not_looked_up_and_costs_no_request() -> None:
    served = Counting({"data": [hit(1, "Nude", "Radiohead", "In Rainbows", 215, STUDIO)]})
    assert deezer_lookup("Radiohead", "Nude", None, length_ms=None, client=served.client) is None
    assert deezer_lookup("Radiohead", "Nude", None, length_ms=0, client=served.client) is None
    assert deezer_lookup("Radiohead", "???", None, length_ms=215_000, client=served.client) is None
    assert deezer_lookup("Quiet Band", "\U0001f3b5", None, length_ms=215_000, client=served.client) is None
    assert deezer_lookup("Unknown Artist", "Nude", None, length_ms=215_000, client=served.client) is None
    assert served.requests == 0


# ------------------------------------------------------------------------------------------------------------------ names (B-133 b, kept)


def test_two_different_arabic_songs_and_one_hit_only_the_song_it_is_named_for_gets_the_picture() -> None:
    payload = {"data": [hit(1, "كيفك إنت", "فيروز", "ألبوم", 209, STUDIO)]}
    assert deezer_lookup("فيروز", "كيفك إنت", None, length_ms=209_000, client=client_for(payload)) == STUDIO
    assert deezer_lookup("فيروز", "حبيبي", None, length_ms=209_000, client=client_for(payload)) is None


def test_a_latin_title_that_only_starts_a_mixed_script_title_is_not_the_song() -> None:
    payload = {"data": [hit(1, "Habibi", "Fairuz", "Album", 209, STUDIO)]}
    assert deezer_lookup("Fairuz", "Habibi يا نور", None, length_ms=209_000, client=client_for(payload)) is None


# ------------------------------------------------------------------------------------------------------------------ the finder


class Spy:
    """A lookup that records what the finder asks (artist, title, album and the length it was given) and answers [picture]."""

    def __init__(self, picture: str | None = PICTURE) -> None:
        self.calls: list[tuple[str, str | None, int | None]] = []
        self.picture = picture

    def __call__(self, artist: str, title: str, album: str | None, *, length_ms: int | None = None) -> str | None:
        self.calls.append((title, album, length_ms))
        return self.picture


def set_length(db: Database, ref: str, length_ms: int | None) -> None:
    with db.tx() as conn:
        conn.execute("UPDATE song_ref SET duration_ms = ? WHERE id = ?", (length_ms, ref))


def test_the_finder_gives_the_lookup_the_songs_length(tmp_path: Path) -> None:
    db = database(tmp_path)
    ref = liked(db, "Nude")
    set_length(db, ref, 215_000)
    spy = Spy()
    CoverFinder(db, spy, sleep=lambda _: None).run_once()
    assert spy.calls == [("Nude", "In Rainbows", 215_000)]


def test_the_finder_uses_the_kept_files_own_length_when_the_music_folder_is_known(tmp_path: Path) -> None:
    db = database(tmp_path)
    ref = liked(db, "Nude")
    set_length(db, ref, 215_000)
    music = tmp_path / "music"
    relative = "Encore/Radiohead/Singles/Nude.opus"
    (music / relative).parent.mkdir(parents=True)
    with wave.open(str(music / relative), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(bytes(24_000))  # 1.5 s of silence
    with db.tx() as conn:
        refs.attach_file(conn, ref, navidrome_song_id="nd-1", path=relative, codec="opus", bitrate_kbps=130, source="youtube")
    spy = Spy(None)
    CoverFinder(db, spy, sleep=lambda _: None, music_dir=music).run_once()
    assert spy.calls == [("Nude", "In Rainbows", 1_500)], "the file's length, not the import's listing"


def test_a_song_with_no_length_is_settled_not_asked_again_this_week(tmp_path: Path) -> None:
    """The finder passes `None`; the real lookup answers "no picture" without a request; the song is marked as looked for (7 days), so it does not take a place in every pass."""
    db = database(tmp_path)
    ref = liked(db, "Nude")
    finder = CoverFinder(db, deezer_lookup_without_network, sleep=lambda _: None)
    finder.run_once()
    finder.run_once()
    with db.read() as conn:
        assert conn.execute("SELECT cover_tried_at IS NOT NULL FROM song_ref WHERE id = ?", (ref,)).fetchone()[0] == 1
    assert cover_of(db, ref) is None


def deezer_lookup_without_network(artist: str, title: str, album: str | None, *, length_ms: int | None = None) -> str | None:
    """The real lookup with a client that fails the test when it is asked: a song with no length must not reach the network."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a song with no length was looked up")

    return deezer_lookup(artist, title, album, length_ms=length_ms, client=httpx.Client(transport=httpx.MockTransport(refuse)))


def test_a_song_the_album_pass_matched_gets_its_picture_from_the_identity_and_is_not_asked_here(tmp_path: Path) -> None:
    db = database(tmp_path)
    matched = liked(db, "Nude")
    other = liked(db, "Reckoner")
    with db.tx() as conn:
        conn.execute(
            "UPDATE song_ref SET identity_outcome = 'matched', identity_rev = 1, identity_tried_at = 1 WHERE id = ?", (matched,)
        )
    spy = Spy()
    CoverFinder(db, spy, sleep=lambda _: None).run_once()
    assert [call[0] for call in spy.calls] == ["Reckoner"]
    assert cover_of(db, other) == PICTURE and cover_of(db, matched) is None


def test_a_live_album_does_not_inherit_the_studio_albums_picture(tmp_path: Path) -> None:
    """The one-search-per-album shortcut was keyed by `title_key`, which strips brackets: "In Rainbows (Live)" and "In Rainbows" were one album. They are two releases."""
    db = database(tmp_path)
    studio = liked(db, "Nude", album="In Rainbows")
    live = liked(db, "Reckoner", album="In Rainbows (Live)")
    set_length(db, studio, 215_000)
    set_length(db, live, 290_000)
    spy = Spy()
    CoverFinder(db, spy, sleep=lambda _: None).run_once()
    assert sorted(call[1] or "" for call in spy.calls) == ["In Rainbows", "In Rainbows (Live)"], (
        "both were asked: neither took the other's picture"
    )


def test_two_songs_of_one_album_are_still_one_question_when_the_album_is_found(tmp_path: Path) -> None:
    db = database(tmp_path)
    ids = [
        liked(db, title, album="In Rainbows (Deluxe Edition)" if title == "Reckoner" else "In Rainbows")
        for title in ("Nude", "Reckoner")
    ]
    for ref in ids:
        set_length(db, ref, 215_000)
    spy = Spy()
    CoverFinder(db, spy, sleep=lambda _: None).run_once()
    assert len(spy.calls) == 1, "a deluxe edition is the same release (`catalogue.release_key`): one question"
    assert [cover_of(db, ref) for ref in ids] == [PICTURE, PICTURE]
