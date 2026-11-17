"""P2-25 slice 2 (audit B-37): every place of the server that compares text goes through the one fold. One test per place of the design's table (part 5), each
with its counterpart (a name in another alphabet is FOUND, and two different names are not confused), written before the code and seen red on main `95d1293`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from encore_server import catalogue, missing, refs
from encore_server.cover_finder import deezer_lookup
from encore_server.imports import uploads
from encore_server.keeper import placement
from encore_server.navidrome import pick_song
from encore_server.sources.youtube import scoring
from encore_server.sources.youtube.lean import artist_matches, rank, title_matches
from encore_server.sources.youtube.scoring import Candidate, Want

# ---------------------------------------------------------------------------------------------------------------------------------------------------
# refs.facts_to_fill (N-26): a basis is a fact about the SAME artist


def _facts(have_artist: str, artist: str) -> dict[str, str]:
    return refs.facts_to_fill(
        have_basis=None,
        have_uploader=None,
        have_artist=have_artist,
        have_video="aaaaaaaaaaa",
        basis="declared",
        uploader=None,
        artist=artist,
        video="aaaaaaaaaaa",
    )


def test_a_basis_is_not_copied_from_one_arabic_artist_to_another() -> None:
    """Before: `'' == ''` for any two non-Latin artists."""
    assert _facts("فيروز", "ام كلثوم") == {}
    assert _facts("Кино", "Любэ") == {}
    assert _facts("宇多田ヒカル", "椎名林檎") == {}


def test_a_basis_is_copied_when_it_is_the_same_artist_in_any_alphabet() -> None:
    assert _facts("فيروز", "فَيْرُوز") == {"artist_basis": "declared"}
    assert _facts("Кино", "кино") == {"artist_basis": "declared"}
    assert _facts("Sigur Rós", "Sigur Ros") == {"artist_basis": "declared"}


def test_a_symbol_only_artist_is_the_same_only_as_itself() -> None:
    assert _facts("!!!", "!!!") == {"artist_basis": "declared"}
    assert _facts("!!!", "???") == {}


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# navidrome.pick_song (the keeper finds the file it just saved)


def song(sid: str, title: str, artist: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": sid,
        "title": title,
        "artist": artist,
        "albumArtist": artist,
        "album": "[Unknown Album]",
        "size": 1000,
        "path": "",
        **extra,
    }


def test_pick_song_finds_an_arabic_title_and_keeps_two_apart() -> None:
    listed = [song("n1", "نسّم علينا الهوا", "فيروز"), song("n2", "سألوني الناس", "فيروز")]
    assert pick_song(listed, artist="فيروز", title="سألوني الناس", album=None, relative_path=None) == "n2"
    assert pick_song(listed, artist="فيروز", title="نسم علينا الهوا", album=None, relative_path=None) == "n1"
    assert pick_song(listed, artist="فيروز", title="أغنية ثالثة", album=None, relative_path=None) is None, (
        "a title of nobody is not any title"
    )


def test_pick_song_does_not_take_an_arabic_artists_other_name() -> None:
    listed = [song("n1", "حبيبي", "ام كلثوم")]
    assert pick_song(listed, artist="فيروز", title="حبيبي", album=None, relative_path=None) is None


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# keeper/placement (where a kept song goes, and whether it is already there)


def test_find_existing_finds_an_arabic_file_so_a_second_keep_is_not_written_as_a_copy(tmp_path: Path) -> None:
    """Before: `if not want: return None` for every Arabic title, so a song kept twice was written as `Title (2).opus`."""
    folder = tmp_path / "فيروز" / "Singles"
    folder.mkdir(parents=True)
    (folder / "01 - سألوني الناس.opus").write_bytes(b"x")
    target = placement.plan_placement(tmp_path, artist="فيروز", album=None, title="سألوني الناس", track=1)
    assert placement.find_existing(target, "سألوني الناس") == folder / "01 - سألوني الناس.opus"
    assert placement.find_existing(target, "نسّم علينا الهوا") is None, "another Arabic song is not the file that is there"


def test_an_arabic_artist_folder_is_reused_whatever_its_marks_and_a_different_one_is_not(tmp_path: Path) -> None:
    (tmp_path / "فَيْرُوز").mkdir()
    (tmp_path / "ام كلثوم").mkdir()
    same = placement.plan_placement(tmp_path, artist="فيروز", album="Album", title="Song")
    assert same.folder.parent.name == "فَيْرُوز", "the folder that is there is joined, not duplicated"
    other = placement.plan_placement(tmp_path, artist="عبد الحليم", album="Album", title="Song")
    assert other.folder.parent.name == "عبد الحليم"


def test_an_existing_latin_folder_is_still_reused_with_its_punctuation(tmp_path: Path) -> None:
    (tmp_path / "AC-DC").mkdir()
    assert placement.plan_placement(tmp_path, artist="AC/DC", album=None, title="Thunderstruck").folder.parent.name == "AC-DC"


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# cover_finder.deezer_lookup (B-133): a hit counts only when its artist and title are the ones asked for


def client_for(hits: list[dict[str, Any]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": hits})

    return httpx.Client(transport=httpx.MockTransport(handler))


def hit(artist: str, title: str, cover: str, album: str = "Album") -> dict[str, Any]:
    return {"artist": {"name": artist}, "title": title, "album": {"title": album, "cover_xl": cover}}


PICTURE = "https://cdn-images.dzcdn.net/images/cover/abc/1000x1000.jpg"
OTHER = "https://cdn-images.dzcdn.net/images/cover/other/1000x1000.jpg"


def test_one_deezer_hit_for_an_arabic_song_does_not_match_another_arabic_song() -> None:
    """Before: every Arabic name folded to `''` and `'' == ''`, so one hit was the cover of every Arabic song."""
    only = client_for([hit("فيروز", "سألوني الناس", PICTURE)])
    assert deezer_lookup("فيروز", "نسّم علينا الهوا", None, client=only) is None
    assert deezer_lookup("ام كلثوم", "سألوني الناس", None, client=only) is None
    assert deezer_lookup("Fairuz", "سألوني الناس", None, client=only) is None


def test_an_exact_arabic_hit_is_the_picture_of_that_song() -> None:
    both = client_for([hit("فيروز", "نسم علينا الهوا", OTHER), hit("فيروز", "سألوني الناس", PICTURE)])
    assert deezer_lookup("فيروز", "سألوني الناس", None, client=both) == PICTURE


def test_a_symbol_only_name_matches_only_itself() -> None:
    assert deezer_lookup("!!!", "Me and Giuliani", None, client=client_for([hit("???", "Me and Giuliani", PICTURE)])) is None
    assert deezer_lookup("!!!", "Me and Giuliani", None, client=client_for([hit("!!!", "Me and Giuliani", PICTURE)])) == PICTURE


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the YouTube matcher (rank): an exact Arabic result is accepted, a dense-script title one syllable off is not


def song_result(track: str, artist: str, *, duration: int = 240) -> Candidate:
    return Candidate(
        video_id="aaaaaaaaaaa",
        title=track,
        channel=f"{artist} - Topic",
        duration_s=duration,
        is_topic=True,
        track=track,
        artists=(artist,),
    )


def test_rank_accepts_an_exact_arabic_result() -> None:
    """Before: `ratio` of two empty strings is 0, so an exact Arabic result was rejected (the 6 Nov probe)."""
    want = Want(artist="فيروز", title="سألوني الناس", duration_s=240)
    ranked = rank(want, [song_result("سألوني الناس", "فيروز")])
    assert [s.candidate.track for s in ranked] == ["سألوني الناس"]


def test_rank_refuses_another_arabic_song_by_the_same_artist() -> None:
    want = Want(artist="فيروز", title="سألوني الناس", duration_s=240)
    assert rank(want, [song_result("نسّم علينا الهوا", "فيروز")]) == []
    assert not title_matches(want, song_result("نسّم علينا الهوا", "فيروز"))
    assert artist_matches("فيروز", ("فَيْرُوز",)) and not artist_matches("فيروز", ("ام كلثوم",))


def test_rank_refuses_a_korean_title_one_syllable_off() -> None:
    """`사랑해` against `사랑이` is 0.667 by characters, above the 0.6 title bar: a syllable carries a whole word, so up to four characters it is equality."""
    want = Want(artist="BTS", title="사랑해", duration_s=200)
    assert rank(want, [song_result("사랑이", "BTS", duration=200)]) == []
    assert [s.candidate.track for s in rank(want, [song_result("사랑해", "BTS", duration=200)])] == ["사랑해"]


def test_the_plain_scorer_finds_an_arabic_title_inside_an_upload_title() -> None:
    plain = Candidate(video_id="bbbbbbbbbbb", title="فيروز - سألوني الناس (Official Audio)", channel="فيروز", duration_s=240)
    right = Want(artist="فيروز", title="سألوني الناس", duration_s=240)
    wrong = Want(artist="فيروز", title="نسّم علينا الهوا", duration_s=240)
    assert scoring.best(right, [plain]) is not None
    # The plain (fallback) scorer is not the guard against another song by the same channel at the same length: it never was, in Latin letters either
    # (`Creep` against `Karma Police` on Radiohead's channel at 240 s scores 8.7). What the fold must do is TELL THE TWO TITLES APART: before, both were `''`.
    assert scoring.score(right, plain).score > scoring.score(wrong, plain).score


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the matcher revision: an Arabic "not found" earned before the fold was fixed is not believed any more


def test_an_old_revisions_not_found_is_void() -> None:
    assert scoring.MATCHER_REVISION >= 2, (
        "P2-25 slice 2 raised it from 1: every 7-day not_found an Arabic song earned was a wrong answer"
    )
    row = {"missing_reason": "not_found", "missing_at": 1, "missing_tried_at": 1_000, "missing_rev": 1}
    standing = missing.standing_of(row, 2_000)
    assert standing is not None and standing.live is False
    current = {**row, "missing_rev": scoring.MATCHER_REVISION}
    live = missing.standing_of(current, 2_000)
    assert live is not None and live.live is True


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# imports/uploads (N-26): its own fold is replaced by the shared one (its comment promised it in the same change)


def test_uploads_name_key_ignores_the_marks_of_a_script_and_keeps_two_names_apart() -> None:
    assert uploads._name_key("فَيْرُوز") == uploads._name_key("فيروز")
    assert uploads._name_key("Mötley Crüe") == uploads._name_key("motley crue")
    assert uploads._name_key("فيروز") != uploads._name_key("ام كلثوم")
    assert uploads._name_key("Кино") != uploads._name_key("Любэ")


def test_uploads_words_keep_a_hindi_word_whole_and_split_on_punctuation() -> None:
    assert uploads._words("तुम हो - Song") == "तुम हो song"
    assert uploads._words("Mötley, Crüe") == "motley crue"


def test_an_arabic_artist_on_her_own_channel_is_read_from_the_title() -> None:
    reading = uploads.read_upload("فيروز - سألوني الناس (Official Audio)", "فيروز")
    assert reading.artists == ("فيروز",) and reading.title == "سألوني الناس"


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# catalogue.release_key: the editions of one release, on the shared fold (the edition-suffix rule stays on top)


def test_release_key_uses_the_shared_fold() -> None:
    assert catalogue.release_key("Straße (Deluxe Edition)") == catalogue.release_key("Strasse")
    assert catalogue.release_key("حبيبي (Remastered 2011)") == catalogue.release_key("حَبِيبِي")
    assert catalogue.release_key("The Wall") == catalogue.release_key("Wall")
    assert catalogue.release_key("Rock & Roll") == catalogue.release_key("Rock and Roll")
    assert catalogue.release_key("Dönerboy") == catalogue.release_key("Donerboy")
    assert catalogue.release_key("حبيبي") != catalogue.release_key("حبيبتي")
    assert catalogue.release_key("???") == "", "a title that holds no letter or digit never merges"
