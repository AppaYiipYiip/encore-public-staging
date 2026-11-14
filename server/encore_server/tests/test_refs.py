from __future__ import annotations

import pytest

from encore_server import refs
from encore_server.db import Database
from encore_server.errors import ApiError


def resolve(db: Database, **song: object) -> dict[str, object]:
    base = {"title": "Weird Fishes / Arpeggi", "artists": ["Radiohead"], "durationMs": 318000}
    with db.tx() as conn:
        return refs.resolve(conn, {**base, **song})


def test_the_same_song_described_twice_is_one_ref(db: Database) -> None:
    assert resolve(db)["id"] == resolve(db)["id"]


def test_a_description_that_differs_only_in_spelling_finds_the_same_ref(db: Database) -> None:
    first = resolve(db, title="Weird Fishes / Arpeggi", artists=["Radiohead"])
    again = resolve(db, title="weird fishes / arpeggi", artists=["RADIOHEAD"], durationMs=319500)
    assert again["id"] == first["id"], "a different case and a length within 3 seconds"


def test_a_different_length_is_a_different_recording(db: Database) -> None:
    studio = resolve(db, durationMs=318000)
    live = resolve(db, durationMs=345000)
    assert live["id"] != studio["id"]


def test_a_rework_is_not_the_plain_song(db: Database) -> None:
    plain = resolve(db, title="Fade Into You", artists=["Mazzy Star"], durationMs=295000)
    rework = resolve(db, title="Fade Into You (The Avener Rework)", artists=["Mazzy Star"], durationMs=295000)
    again = resolve(db, title="Fade Into You (2013 Remaster)", artists=["Mazzy Star"], durationMs=295000)
    assert rework["id"] != plain["id"]
    assert again["id"] == plain["id"], "a remaster mark is not a different song"


def test_the_isrc_wins_over_everything_else(db: Database) -> None:
    first = resolve(db, isrc="GBAYE0701234")
    other_title = resolve(db, title="Weird Fishes (single edit)", isrc="gb-aye-07-01234", durationMs=250000)
    assert other_title["id"] == first["id"]


def test_ids_from_the_catalogue_and_youtube_find_the_ref(db: Database) -> None:
    first = resolve(db, deezerId="12345", videoId="bgsmr7t8zGE")
    assert resolve(db, title="Something else entirely", artists=["Anybody"], deezerId="12345")["id"] == first["id"]
    assert resolve(db, title="Another", artists=["Other"], videoId="bgsmr7t8zGE")["id"] == first["id"]


def test_what_a_ref_lacked_is_filled_in_by_a_later_description(db: Database) -> None:
    first = resolve(db)
    assert first["isrc"] is None and first["videoId"] is None
    richer = resolve(db, isrc="GBAYE0701234", videoId="bgsmr7t8zGE", coverUrl="https://e-cdns-images.dzcdn.net/c.jpg")
    assert richer["id"] == first["id"]
    assert (richer["isrc"], richer["videoId"], richer["coverUrl"]) == (
        "GBAYE0701234",
        "bgsmr7t8zGE",
        "https://e-cdns-images.dzcdn.net/c.jpg",
    )


def test_an_id_another_ref_owns_is_never_taken_from_it(db: Database) -> None:
    a = resolve(db, title="Song A", artists=["X"], videoId="aaaaaaaaaaa", durationMs=200000)
    b = resolve(db, title="Song B", artists=["Y"], durationMs=200000)
    again = resolve(db, title="Song B", artists=["Y"], videoId="aaaaaaaaaaa", durationMs=200000)
    assert again["id"] == a["id"], "the video id is matched first"
    assert b["id"] != a["id"]


def test_no_two_refs_share_an_isrc_even_in_a_race(db: Database) -> None:
    with db.tx() as conn:
        first = refs.resolve(conn, {"title": "A", "artists": ["X"], "isrc": "USRC17607839", "durationMs": 100000})
        # a second description with the same isrc but nothing else alike: matched by isrc, not made new
        second = refs.resolve(
            conn, {"title": "Totally different", "artists": ["Z"], "isrc": "USRC17607839", "durationMs": 999000}
        )
    assert second["id"] == first["id"]


@pytest.mark.parametrize(
    "bad", [None, "text", {}, {"title": "x"}, {"artists": ["a"]}, {"title": "", "artists": ["a"]}, {"title": "t", "artists": []}]
)
def test_what_cannot_be_a_song_is_refused_in_words(db: Database, bad: object) -> None:
    with pytest.raises(ApiError) as caught, db.tx() as conn:
        refs.resolve(conn, bad)
    assert caught.value.code == "validation" and "title and an artist" in caught.value.message


def test_odd_values_are_dropped_not_stored(db: Database) -> None:
    ref = resolve(
        db,
        title="  Spaced   out  ",
        artists=["  A  ", "", 5],
        trackNo="3",
        year=1800,
        durationMs=5,
        coverUrl="http://insecure/x.jpg",
        videoId="short",
    )
    assert ref["title"] == "Spaced out"
    assert ref["artists"] == ["A"]
    assert (ref["trackNo"], ref["year"], ref["durationMs"], ref["coverUrl"], ref["videoId"]) == (None, None, None, None, None)


def test_a_file_attached_to_a_ref_changes_nothing_about_the_ref(db: Database) -> None:
    ref = resolve(db)
    assert ref["file"] is None
    with db.tx() as conn:
        refs.attach_file(
            conn,
            str(ref["id"]),
            navidrome_song_id="nd-1",
            path="Encore/Radiohead/In Rainbows/05 - Weird Fishes.opus",
            codec="opus",
            bitrate_kbps=140,
        )
        again = refs.get_ref(conn, str(ref["id"]))
    assert again["id"] == ref["id"]
    assert again["file"]["navidromeSongId"] == "nd-1"


def test_replacing_the_file_moves_the_pointer_only(db: Database) -> None:
    ref = resolve(db)
    with db.tx() as conn:
        refs.attach_file(conn, str(ref["id"]), navidrome_song_id="nd-1", path="a.opus", codec="opus", bitrate_kbps=128)
        refs.attach_file(
            conn, str(ref["id"]), navidrome_song_id="nd-2", path="b.flac", codec="flac", bitrate_kbps=900, source="quality"
        )
        current = refs.get_ref(conn, str(ref["id"]))
        files = conn.execute("SELECT preferred FROM song_file WHERE ref = ? ORDER BY added_at", (ref["id"],)).fetchall()
    assert current["file"]["navidromeSongId"] == "nd-2", "the better file is the one used"
    assert [r["preferred"] for r in files] == [0, 1]
    assert current["id"] == ref["id"]


def test_attaching_the_same_file_twice_is_one_file(db: Database) -> None:
    ref = resolve(db)
    with db.tx() as conn:
        first = refs.attach_file(conn, str(ref["id"]), navidrome_song_id="nd-1", path="a.opus", codec="opus", bitrate_kbps=128)
        second = refs.attach_file(conn, str(ref["id"]), navidrome_song_id="nd-1", path="a.opus", codec="opus", bitrate_kbps=130)
        assert conn.execute("SELECT COUNT(*) FROM song_file").fetchone()[0] == 1
    assert first == second


def test_the_holder_of_a_file_is_found_by_id_for_many_ids_and_the_oldest_row_wins(db: Database) -> None:
    ids = [f"nd-{n}" for n in range(1050)]  # more than one query asks about at once
    with db.tx() as conn:
        first = refs.resolve(conn, {"title": "One", "artists": ["A"], "durationMs": 200000})["id"]
        second = refs.resolve(conn, {"title": "Two", "artists": ["B"], "durationMs": 200000})["id"]
        for n in (0, 400, 1049):  # at both ends of the chunks
            refs.attach_file(conn, first, navidrome_song_id=ids[n], path=None, codec="opus", bitrate_kbps=None, source="youtube")
        refs.attach_file(
            conn, second, navidrome_song_id=ids[400], path=None, codec="opus", bitrate_kbps=None, source="library"
        )  # held twice

    with db.read() as conn:
        holders = refs.file_holders(conn, [*ids, "", "nd-unknown"])

    assert sorted(holders) == sorted(ids[n] for n in (0, 400, 1049))
    assert {holders[i]["ref"] for i in holders} == {first}  # the first holder, not the later one


def test_a_file_for_an_unknown_ref_is_not_found(db: Database) -> None:
    with pytest.raises(ApiError) as caught, db.tx() as conn:
        refs.attach_file(conn, "sr_00000000000000000000000000", navidrome_song_id="x", path=None, codec=None, bitrate_kbps=None)
    assert caught.value.code == "not_found"


def test_a_play_that_found_the_upload_leaves_it_on_the_ref(db: Database) -> None:
    ref = resolve(db)
    with db.tx() as conn:
        assert refs.remember_video(conn, str(ref["id"]), "bgsmr7t8zGE") is True
        assert refs.remember_video(conn, str(ref["id"]), "zzzzzzzzzzz") is False, "the first one found is kept"
        assert refs.get_ref(conn, str(ref["id"]))["videoId"] == "bgsmr7t8zGE"


def test_an_upload_another_ref_owns_is_not_taken(db: Database) -> None:
    a = resolve(db, title="A", artists=["X"], videoId="aaaaaaaaaaa", durationMs=100000)
    b = resolve(db, title="B", artists=["Y"], durationMs=100000)
    with db.tx() as conn:
        assert refs.remember_video(conn, str(b["id"]), "aaaaaaaaaaa") is False
        assert refs.get_ref(conn, str(a["id"]))["videoId"] == "aaaaaaaaaaa"


def test_a_picture_address_is_kept_only_from_the_hosts_the_server_itself_would_fetch_from(db: Database) -> None:
    """B6 (QA-BACKEND): any https address a phone named as a song's picture was stored and then loaded by EVERY phone that shows the song: a
    member could make every other phone ask a host of their choosing (showing each phone's address to it). The keeper's own allow-list of picture
    hosts, which it already applies to what it fetches, applies here too."""
    for bad in (
        "https://evil.example/pixel.gif",
        "https://dzcdn.net.evil.example/x.jpg",
        "https://notdzcdn.net/x.jpg",
        "http://e-cdns-images.dzcdn.net/x.jpg",
        "https://user@evil.example/x.jpg",
        "javascript:alert(1)",
    ):
        assert resolve(db, title=f"Song for {bad}", coverUrl=bad)["coverUrl"] is None, bad

    for good in (
        "https://e-cdns-images.dzcdn.net/images/cover/abc/500x500.jpg",
        "https://i.ytimg.com/vi/abc/hqdefault.jpg",
        "https://lh3.googleusercontent.com/abc=w544",
        "https://coverartarchive.org/release/1/front",
        "https://i.scdn.co/image/abc",
    ):
        assert resolve(db, title=f"Song for {good}", coverUrl=good)["coverUrl"] == good, good
