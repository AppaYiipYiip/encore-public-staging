"""The keeper finds the song it just saved in the music server's list (audit B-105; P2-22, the owner's '00s Hip Hop).

Found 7 Nov 2026 on the test VM: 9 of the 189 songs of an imported playlist stayed "The music server has not found the saved file yet" after five
attempts. Navidrome had every one of them, with the artist written as the joined string "Beanie Sigel, Freeway" (the file's artists, joined); the matcher
compared only the first artist ("Beanie Sigel") with that whole string and refused it, and Navidrome's `path` in an answer is built from the tags, not the real
one, so the path could not save it either. All nine were songs with several artists."""

from __future__ import annotations

from encore_server.navidrome import pick_song


def song(
    sid: str, title: str, artist: str, album: str = "[Unknown Album]", size: int = 4_000_000, path: str = ""
) -> dict[str, object]:
    return {"id": sid, "title": title, "artist": artist, "albumArtist": artist, "album": album, "size": size, "path": path}


def test_a_song_with_several_artists_is_found_by_the_size_of_the_file_just_saved() -> None:
    listed = [
        song(
            "n1",
            "Roc The Mic",
            "Beanie Sigel, Freeway",
            "Def Jam 25, Vol. 8: Girls Just Wanna",
            4_073_435,
            "Beanie Sigel, Freeway/Def Jam 25/Roc The Mic.opus",
        )
    ]

    found = pick_song(
        listed,
        artist="Beanie Sigel",
        title="Roc The Mic",
        album="Def Jam 25, Vol. 8: Girls Just Wanna",
        relative_path="Encore/Beanie Sigel/Def Jam 25, Vol. 8- Girls Just Wanna/Roc The Mic.opus",
        size=4_073_435,
    )

    assert found == "n1"


def test_the_first_artist_is_found_among_the_joined_ones_even_without_a_size() -> None:
    listed = [song("n1", "Make It Rain", "Fat Joe, Lil Wayne", "Me, Myself & I")]

    assert pick_song(listed, artist="Fat Joe", title="Make It Rain", album="Me, Myself & I", relative_path=None) == "n1"
    assert pick_song(listed, artist="Lil Wayne", title="Make It Rain", album="Me, Myself & I", relative_path=None) == "n1"


def test_an_artist_name_with_quotes_and_an_ampersand_is_found_among_the_joined_ones() -> None:
    listed = [
        song("n1", "One Minute Man", 'Ludacris, Missy "Misdemeanor" Elliott'),
        song("n2", "Ms. New Booty", "Bubba Sparxxx, Ying Yang Twins, Mr. Collipark"),
    ]

    assert pick_song(listed, artist='Missy "Misdemeanor" Elliott', title="One Minute Man", album=None, relative_path=None) == "n1"
    assert pick_song(listed, artist="Ying Yang Twins", title="Ms. New Booty", album=None, relative_path=None) == "n2"


def test_the_same_title_by_someone_else_is_not_taken_for_ours() -> None:
    """'Forever' is a title of many songs: another artist's, of another size, is not ours."""
    listed = [
        song("other", "Forever", "Chris Brown", size=3_100_000),
        song("ours", "Forever", "Drake, Kanye West, Lil Wayne, Eminem", size=5_824_747),
    ]

    assert pick_song(listed, artist="Drake", title="Forever", album=None, relative_path=None, size=5_824_747) == "ours"
    assert pick_song([listed[0]], artist="Drake", title="Forever", album=None, relative_path=None, size=5_824_747) is None
    assert pick_song([listed[0]], artist="Drake", title="Forever", album=None, relative_path=None) is None


def test_another_version_of_the_song_with_the_same_size_is_not_ours() -> None:
    """The size does not make a live cut the studio recording: the title's version words still have to agree."""
    listed = [song("live", "Forever (Live)", "Drake, Kanye West", size=5_824_747)]

    assert pick_song(listed, artist="Drake", title="Forever", album=None, relative_path=None, size=5_824_747) is None


def test_a_single_artist_song_still_needs_its_artist_to_be_close() -> None:
    assert (
        pick_song([song("n1", "Lose Yourself", "Eminem")], artist="Eminem", title="Lose Yourself", album=None, relative_path=None)
        == "n1"
    )
    assert (
        pick_song(
            [song("n1", "Lose Yourself", "Someone Else")], artist="Eminem", title="Lose Yourself", album=None, relative_path=None
        )
        is None
    )


def test_the_path_still_decides_when_it_is_the_real_one() -> None:
    listed = [
        song("a", "Same", "X", path="Encore/X/Singles/Same.opus", size=1),
        song("b", "Same", "X", path="Other/Same.opus", size=2),
    ]

    assert pick_song(listed, artist="X", title="Same", album=None, relative_path="Encore/X/Singles/Same.opus", size=2) == "a"
