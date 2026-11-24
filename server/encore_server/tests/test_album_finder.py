"""N-34 slice 1: the pure album matcher (`encore_server/album_finder.py`), the steps 0 to 5 of the rule table in `docs/tasks/P2-songs-as-references.md`
(section N-34, part 2), on Deezer's REAL answers.

Where the data comes from, said plainly because a matcher is only as good as the answers it is tested on:

* The HITS are the recorded searches of `app/test/fixtures/deezer/search.json` (Comfortably Numb, Fade Into You, Hotel California, Weird Fishes,
  Bohemian Rhapsody, Kifak Inta) and the two recorded in step 0 (the searches `LANDMVRKS Requiem` and `LANDMVRKS Creature`): the rows are the catalogue's, untouched.
* The ALBUMS are `Catalogue.album()` over the recorded album and song-list answers (The Wall, the best-of, LANDMVRKS' album and single). Only four
  albums and three song lists were recorded (10 requests, `n34_requests.json`), so the rows for Fade Into You, Hotel California, Weird Fishes and
  Bohemian Rhapsody are tested at the level of the HIT VERDICTS, which is where the rule decides them.
* A DERIVED case (the rule needs a shape no recording holds: a type nobody has seen, two dates swapped, an id order) starts from a recorded answer
  and changes exactly the named fields, and its test says so. Nothing is invented from nothing.
"""

from __future__ import annotations

import ast
import copy
import functools
import inspect
import json
import socket
from typing import Any

import httpx
import pytest

from encore_server import album_finder, refs
from encore_server.album_finder import (
    NO_HOLDINGS,
    REMEMBERED,
    RefHoldings,
    Song,
    Verdict,
    choose_release,
    judge_hits,
    refusal,
    release_date,
    wanted_albums,
)
from encore_server.catalogue import Cache, Catalogue, release_key
from encore_server.db import Database
from encore_server.deezer import DeezerClient, Gate
from encore_server.textnorm import norm_artist, norm_title, survives_fold_whole
from tests.catalogue_fakes import RECORDED, SEARCHES, RecordedDeezer, recorded, recorded_search, searches

# ------------------------------------------------------------------------------------------------------------------ the recorded data

WALL, BEST_OF = "12114248", "12114262"
ALBUM, SINGLE = "676735071", "524195422"  # LANDMVRKS' album "The Darkest Place I've Ever Been" and its single "Creature"


def hits(query: str) -> list[dict[str, Any]]:
    """The recorded search's song rows, as `deezer.search_tracks` returns them."""
    return copy.deepcopy(searches()[query]["track"])


@functools.cache
def _recorded_albums() -> dict[str, dict[str, Any]]:
    cat = Catalogue(
        DeezerClient(Gate(rate=1000, burst=1000, background_gap_s=0.0), httpx.Client(transport=RecordedDeezer().transport())),
        Cache(None),
    )
    return {ident: cat.album(ident, priority="background", deadline_s=10.0) for ident in (WALL, BEST_OF, ALBUM, SINGLE)}


def albums(*ids: str) -> dict[str, dict[str, Any]]:
    """What `Catalogue.album` answers for these albums (recorded)."""
    return {ident: copy.deepcopy(_recorded_albums()[ident]) for ident in ids}


def derive(answer: dict[str, Any], **album: Any) -> dict[str, Any]:
    """A DERIVED answer: the recorded one with exactly these fields of its album changed."""
    out = copy.deepcopy(answer)
    out["album"].update(album)
    return out


def creature_hit() -> dict[str, Any]:
    """The search hit of the song on the ALBUM: the recorded search of `LANDMVRKS Creature`, its row untouched."""
    return copy.deepcopy(recorded_search("LANDMVRKS Creature")["data"][0])


def single_hit() -> dict[str, Any]:
    """The same song as the single's own release: the row of the single's recorded song list with its recorded album's id and title, the way a search hit
    carries them (the recorded search happened to list only the album's row)."""
    row: dict[str, Any] = copy.deepcopy(recorded(f"album_{SINGLE}_tracks")["data"][0])
    row["album"] = {"id": int(SINGLE), "title": recorded(f"album_{SINGLE}")["title"]}
    return row


CREATURE = Song("LANDMVRKS", "Creature", 225_000)
COMFORTABLY_NUMB = Song("Pink Floyd", "Comfortably Numb", 382_000)


def reasons(verdict_hits: Any) -> dict[str, str]:
    return {str(v.id): v.reason for v in verdict_hits}


# ------------------------------------------------------------------------------------------------------------------ step 0: can it be asked


@pytest.mark.parametrize(
    ("artist", "title", "why"),
    [
        ("Pink Floyd", "Audio", "title_not_comparable"),  # a title that is all noise folds to nothing
        ("Pink Floyd", "???", "title_not_comparable"),
        (
            "VEVO",
            "Song",
            "artist_not_comparable",
        ),  # survives the fold, and `norm_artist` strips the word: nothing is left to compare
        ("Official", "Song", "artist_not_comparable"),
        ("Unknown Artist", "Song", "artist_is_nobody"),
        ("[Unknown Artist]", "Song", "artist_is_nobody"),
    ],
)
def test_a_name_that_does_not_survive_the_fold_whole_is_unsupported_and_not_remembered(artist: str, title: str, why: str) -> None:
    song = Song(artist, title, 200_000)
    assert refusal(song) == ("unsupported", why)
    verdict = choose_release(song, hits("pink floyd comfortably numb"), albums(WALL, BEST_OF))
    assert (verdict.outcome, verdict.reason) == ("unsupported", why)
    assert verdict.remember is False and verdict.match is None
    assert wanted_albums(song, hits("pink floyd comfortably numb")) == [], "nothing is asked about a song that cannot be compared"


def test_nothing_is_asked_about_a_song_that_was_refused_even_when_the_hits_would_match_its_name() -> None:
    """DERIVED: the recorded Pink Floyd hits with their artist changed to "Unknown Artist", which is also the library's artist: the names are EQUAL, so
    only the refusal stops the albums being asked."""
    found = hits("pink floyd comfortably numb")
    for row in found:
        row["artist"] = {"id": 1, "name": "Unknown Artist"}
    song = Song("Unknown Artist", "Comfortably Numb", 382_000)
    assert [v.accepted for v in judge_hits(song, found)].count(True) == 2, (
        "the premise: without the refusal the hits are the same recording"
    )
    assert wanted_albums(song, found) == []
    assert wanted_albums(Song("Unknown Artist", "Comfortably Numb", None), found) == []
    no_length = wanted_albums(Song("Pink Floyd", "Comfortably Numb", None), hits("pink floyd comfortably numb"))
    assert no_length == []


@pytest.mark.parametrize(
    ("artist", "title"),
    [
        ("Björk", "Army of Me"),
        ("Beyoncé", "Halo"),
        ("Sigur Rós", "Hoppípolla"),
        ("Ke$ha", "Tik Tok"),
        # refused while the fold lost every letter outside a-z (era 0, B-37); asked since P2-25 slices 2 and 3, where the key keeps them
        ("فيروز", "كيفك إنت"),
        ("Кино", "Группа крови"),
        ("Pink Floyd", "Группа крови"),
        ("Fairuz", "Habibi يا نور"),
        ("Łukasz", "Song"),
        ("Rammstein", "Straße"),
    ],
)
def test_names_the_fold_keeps_whole_are_asked(artist: str, title: str) -> None:
    assert refusal(Song(artist, title, 200_000)) is None


def test_a_song_with_no_length_is_no_length_and_not_remembered() -> None:
    for length in (None, 0, -5):
        verdict = choose_release(
            Song("Pink Floyd", "Comfortably Numb", length), hits("pink floyd comfortably numb"), albums(WALL, BEST_OF)
        )
        assert (verdict.outcome, verdict.reason, verdict.remember) == ("no_length", "no_length", False)


def test_the_remembered_outcomes_are_exactly_the_facts() -> None:
    assert {"matched", "none", "held"} == REMEMBERED
    facts = [
        ("matched", True),
        ("none", True),
        ("held", True),
        ("unsupported", False),
        ("no_length", False),
        ("unavailable", False),
    ]
    for outcome, remembered in facts:
        assert Verdict(outcome, "x").remember is remembered, outcome  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------------------------ the Arabic rows (P2-25 slices 2 and 3: era 1)
# These rows were written for era 0, where `survives_fold_whole` was false for every Arabic name and the skip rule alone refused them (the premise they pinned was
# "both fold to '||'"). From the merge of P2-25 slices 2 and 3 every name below survives the fold WHOLE, so no guard is what holds them: the rows assert the rule
# that holds now, the one the new fold makes true: two different songs are two different keys, and a hit is the song only when the artist AND the key are equal.


ARABIC_A, ARABIC_B, ARABIC_C = "كيفك إنت", "حبيبي", "سألوني الناس"


def arabic_hit(title: str, *, artist: str = "فيروز", duration: int = 209) -> dict[str, Any]:
    """DERIVED: the recorded Fairuz row ("Kifak Inta", 209 s, on "Fairuz Chillout Classics") with its artist and title changed to Arabic names. Nothing else is
    changed: the length, the album and the id are the recording's."""
    hit = copy.deepcopy(hits("fairuz kifak inta")[1])
    assert hit["artist"]["name"] == "Fairuz" and hit["title"] == "Kifak Inta"
    hit.update(title=title, duration=duration, artist={"id": hit["artist"]["id"], "name": artist})
    return hit


def test_the_arabic_names_of_these_rows_all_survive_the_fold_whole_so_no_guard_holds_them() -> None:
    """The premise of every row below, stated once: with the new fold the names are not refused, they are compared."""
    for name in ("فيروز", ARABIC_A, ARABIC_B, ARABIC_C, "Fairuz", "Habibi", "Habibi يا نور", "Habibi يا قمر", "Fairuz فيروز"):
        assert survives_fold_whole(name), name
    for title in (ARABIC_A, ARABIC_B, ARABIC_C):
        assert refusal(Song("فيروز", title, 209_000)) is None, "step 0 asks about the song: it is the key that decides"
    for title in ("Habibi", "Habibi يا نور", "Habibi يا قمر"):
        assert refusal(Song("Fairuz", title, 200_000)) is None


def test_two_different_arabic_songs_and_one_deezer_hit_neither_gets_an_album() -> None:
    """The row the whole dependency on P2-25 is for, and the rule that holds it now: the keys of two different Arabic songs of one artist are two keys (under the
    old fold both were `'||'`, which is also the key of the one hit). The hit is a THIRD Arabic song of the same artist and the same length: it is neither of them,
    and the only thing that says so is that its key differs from both keys. Nothing here may decide, store or ask."""
    keys = {refs.norm_key("فيروز", ARABIC_A), refs.norm_key("فيروز", ARABIC_B), refs.norm_key("فيروز", ARABIC_C)}
    assert len(keys) == 3 and "" not in {part for key in keys for part in key.split("|")[:2]}, (
        "the premise: three songs, three non-empty keys"
    )
    third = arabic_hit(ARABIC_C)
    for title in (ARABIC_A, ARABIC_B):
        song = Song("فيروز", title, 209_000)
        assert [v.reason for v in judge_hits(song, [third])] == ["title_or_version"], title  # the artist is equal; the KEY is not
        verdict = choose_release(song, [third], albums(WALL))
        assert (verdict.outcome, verdict.match) == ("none", None), title
        assert wanted_albums(song, [third]) == []


def test_the_recorded_latin_hit_is_not_either_of_two_arabic_songs() -> None:
    """The same two songs against the recorded Latin row (Fairuz, "Kifak Inta", 209 s): the fold does not transliterate, so an Arabic name and its Latin
    spelling are different names and neither song gets the album (a miss, never a wrong stamp; N-16 measures what else could be done)."""
    fairuz = hits("fairuz kifak inta")
    latin = refs.norm_key("Fairuz", "Kifak Inta")
    for title in (ARABIC_A, ARABIC_B):
        assert refs.norm_key("فيروز", title) != latin
        song = Song("فيروز", title, 209_000)
        assert judge_hits(song, fairuz[1:2])[0].reason == "artist"
        verdict = choose_release(song, fairuz, albums(WALL))
        assert (verdict.outcome, verdict.match) == ("none", None), title
        assert wanted_albums(song, fairuz) == []


def test_an_arabic_hit_is_the_song_it_is_named_for_and_not_the_other_arabic_song() -> None:
    """The control that proves the rows above are the equality rule and not a refusal: the hit NAMED as song A is song A (same recording, the recorded album), and the
    other Arabic song of the same artist and the same length is not it."""
    named_a = arabic_hit(ARABIC_A)
    assert [v.reason for v in judge_hits(Song("فيروز", ARABIC_A, 209_000), [named_a])] == ["same_recording"]
    assert wanted_albums(Song("فيروز", ARABIC_A, 209_000), [named_a]) == ["9950862"]
    other = Song("فيروز", ARABIC_B, 209_000)
    assert [v.reason for v in judge_hits(other, [named_a])] == ["title_or_version"]
    assert wanted_albums(other, [named_a]) == []
    vowelled = arabic_hit(
        "كَيْفَكْ إِنْتَ"
    )  # the same song written with the vowel marks: the fold removes them on purpose, so it is the same key
    assert [v.reason for v in judge_hits(Song("فيروز", ARABIC_A, 209_000), [vowelled])] == ["same_recording"]


def test_habibi_and_two_different_arabic_words_are_three_keys_and_none_matches_the_latin_hit() -> None:
    """ "Fairuz - Habibi <Arabic A>" and "<Arabic B>", one hit "Habibi" (the recorded Fairuz row with its title changed: DERIVED). Under the old fold all three were
    `fairuz|habibi|`; now they are three keys, and neither song is the hit."""
    hit = copy.deepcopy(hits("fairuz kifak inta")[1])
    assert hit["artist"]["name"] == "Fairuz"
    hit.update(title="Habibi", duration=200)
    one, other = "Habibi يا نور", "Habibi يا قمر"
    keys = [refs.norm_key("Fairuz", title) for title in (one, other, "Habibi")]
    assert len(set(keys)) == 3 and keys[2] == "fairuz|habibi|", (
        "the premise: three different keys, and the Latin hit's is not either Arabic one"
    )
    assert [v.reason for v in judge_hits(Song("Fairuz", "Habibi", 200_000), [hit])] == ["same_recording"], (
        "the control: the Latin song IS the hit"
    )
    for title in (one, other):
        song = Song("Fairuz", title, 200_000)
        assert [v.reason for v in judge_hits(song, [hit])] == ["title_or_version"], title
        verdict = choose_release(song, [hit], albums(WALL))
        assert (verdict.outcome, verdict.match) == ("none", None), title
        assert wanted_albums(song, [hit]) == []


def test_a_latin_song_is_not_matched_with_a_hit_whose_title_only_starts_in_latin() -> None:
    """The same from the other side: the library's "Habibi" against the hit "Habibi <Arabic>" (DERIVED from the recorded row): two keys, so no match. The hit's
    artist "Fairuz فيروز" is not "Fairuz" either (it was a skip-rule row under the old fold; it is an artist mismatch now)."""
    hit = copy.deepcopy(hits("fairuz kifak inta")[1])
    hit.update(title="Habibi يا نور", duration=200)
    song = Song("Fairuz", "Habibi", 200_000)
    assert refs.norm_key("Fairuz", "Habibi") != refs.norm_key("Fairuz", "Habibi يا نور"), "the premise"
    assert [v.reason for v in judge_hits(song, [hit])] == ["title_or_version"]
    assert choose_release(song, [hit], albums(WALL)).outcome == "none"
    hit.update(title="Habibi", artist={"id": 1, "name": "Fairuz فيروز"})
    assert [v.reason for v in judge_hits(song, [hit])] == ["artist"]


@pytest.mark.parametrize(
    ("name", "what"),
    [
        ("🎵", "an emoji only"),
        ("♪♪", "music notes only"),
        ("ـــ", "a tatweel only: removed on purpose, so nothing is left to compare"),
        ("ً", "a lone Arabic vowel mark"),
        ("???", "punctuation only"),
    ],
)
def test_a_name_with_no_letter_or_digit_still_cannot_be_compared_safely(name: str, what: str) -> None:
    """The era-1 rule keeps its one job: a name that holds no letter and no digit identifies nothing, so it is refused whichever alphabet the rest of the song
    is in, and not remembered (`textnorm.survives_fold_whole`, P2-25 design part 4)."""
    assert not survives_fold_whole(name), what
    for song, why in (
        (Song("فيروز", name, 209_000), "title_not_comparable"),
        (Song(name, "حبيبي", 209_000), "artist_not_comparable"),
    ):
        assert refusal(song) == ("unsupported", why), (name, what)
        verdict = choose_release(song, hits("fairuz kifak inta"), albums(WALL))
        assert (verdict.outcome, verdict.reason, verdict.remember) == ("unsupported", why, False)
        assert wanted_albums(song, hits("fairuz kifak inta")) == []


def test_step_zero_asks_the_one_definition_of_a_name_that_can_be_compared(monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 0 is the song's own gate and it names the rule instead of copying it: `textnorm.survives_fold_whole` (P2-25 design, part 4). Today the word rules'
    emptiness (`norm_artist`, `norm_title`) also refuses a name with no letter or digit, so the call decides nothing the second condition does not; it stays so
    that a stricter definition of the one rule tomorrow refuses a song here without a change to this module. Stubbed, the rule's answer is what refuses."""
    song = Song("Pink Floyd", "Comfortably Numb", 382_000)
    assert refusal(song) is None
    monkeypatch.setattr(album_finder, "survives_fold_whole", lambda text: text != "Comfortably Numb")
    assert refusal(song) == ("unsupported", "title_not_comparable")
    monkeypatch.setattr(album_finder, "survives_fold_whole", lambda text: text != "Pink Floyd")
    assert refusal(song) == ("unsupported", "artist_not_comparable")
    assert choose_release(song, hits("pink floyd comfortably numb"), albums(WALL, BEST_OF)).outcome == "unsupported"


def test_a_text_that_does_not_survive_the_fold_has_empty_word_keys_too_so_the_rule_is_what_step_zero_names_not_an_extra_refusal() -> (
    None
):
    """The reachability proof behind the comment in `refusal`: every single character of the two first Unicode planes that `survives_fold_whole` refuses is also
    empty under `norm_artist` and `norm_title`. So at step 0 the named rule decides nothing the word rules' emptiness does not (it is kept as the one definition,
    see `test_step_zero_asks_the_one_definition...`), and a hit with no letter or digit has a key that no song which step 0 let in can have. When this fails, a
    name can pass the word rules and fail the fold: step 0's call has become the only thing that refuses it, and the comment there must say so."""
    for code in range(0x20000):
        if 0xD800 <= code <= 0xDFFF:
            continue
        text = chr(code)
        if not survives_fold_whole(text):
            assert norm_artist(text) == "" and norm_title(text) == "", hex(code)


#: Hit names the era-1 fold holds no letter or digit of: nothing to compare, in any alphabet's company.
NAMELESS = ["🎵", "♪♪", "???", "!!!", "—", "ـــ", "ً"]


@pytest.mark.parametrize("nameless", NAMELESS)
def test_a_hit_with_no_letter_or_digit_in_its_names_is_never_the_song_and_the_equality_rule_alone_says_so(
    nameless: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hit-side guard of era 0 ("the HIT's names must survive the fold whole too": under the old fold a hit "Habibi <Arabic>" was `habibi`, the same as the
    library's "Habibi") is gone, because the rule it guarded is. A hit whose artist or title has nothing to compare is refused by the EQUALITY of the artist and of
    the key (a song that step 0 let in has a letter or a digit in both), and that decides it whatever `survives_fold_whole` says: with the function replaced by
    "always yes" the verdicts are the same, reason by reason. (Run on the old code the reasons were `skip_rule`.)"""
    assert not survives_fold_whole(nameless)
    wrong_artist = copy.deepcopy(creature_hit())
    wrong_artist["artist"] = {"id": 1, "name": nameless}
    wrong_title = copy.deepcopy(creature_hit())
    wrong_title["title"] = nameless
    both = copy.deepcopy(creature_hit())
    both["artist"], both["title"] = {"id": 1, "name": nameless}, nameless
    songs = [CREATURE, Song("فيروز", ARABIC_A, 225_000), Song(nameless + " x", "Creature", 225_000)]
    seen: dict[str, list[list[str]]] = {}
    for label, stub in (("real", None), ("always yes", lambda text: True)):
        if stub is not None:
            monkeypatch.setattr(album_finder, "survives_fold_whole", stub)
        seen[label] = [[v.reason for v in judge_hits(song, [wrong_artist, wrong_title, both])] for song in songs]
    assert seen["real"] == seen["always yes"], "a guard that decides something the equality does not is not dead"
    assert seen["real"][0] == ["artist", "title_or_version", "artist"], "the equality rule: the artist first, then the key"
    for song in songs:
        found = [wrong_artist, wrong_title, both]
        assert not any(v.accepted for v in judge_hits(song, found)), (song, nameless)
        assert wanted_albums(song, found) == [] and choose_release(song, found, albums(ALBUM)).match is None


def test_the_matcher_carries_no_era_0_stop_gap_and_keeps_the_one_that_is_still_true() -> None:
    """The text of era 0 (the skip rule that refused every non-Latin name until P2-25 slice 2) was true once and is false now; a false sentence in a source file
    tells the next reader a refusal exists that does not. The stop-gaps that ARE still true are the window's and the compilation markers'."""
    source = inspect.getsource(album_finder)
    for stale in ("STOP-GAP(P2-25", "era 0", "until P2-25", "skip_rule", "skip rule"):
        assert stale not in source, stale
    assert "STOP-GAP(N-34 single window)" in source and "STOP-GAP(N-34 compilation markers)" in source


# ------------------------------------------------------------------------------------------------------------------ steps 1 and 2: the same recording


def test_comfortably_numb_the_wall_wins_over_the_two_best_ofs_and_every_live_version_and_the_long_cut_is_rejected() -> None:
    found = hits("pink floyd comfortably numb")
    got = reasons(judge_hits(COMFORTABLY_NUMB, found))
    assert got == {
        "116914122": "same_recording",  # The Wall, 382 s
        "116914348": "same_recording",  # A Foot in the Door: The Best of, 382 s
        "116914310": "length",  # Echoes: The Best of, 413 s: the same title and version, 31 s longer
        "1520205192": "title_or_version",  # Pulse (Live)
        "116914072": "title_or_version",  # Delicate Sound of Thunder (Live)
        "1352940292": "title_or_version",  # Live at Knebworth 1990
        "1122138232": "title_or_version",  # 2019 remix Live
        "2454812225": "title_or_version",  # a compilation's (Live)
    }
    assert wanted_albums(COMFORTABLY_NUMB, found) == [WALL, BEST_OF]
    verdict = choose_release(COMFORTABLY_NUMB, found, albums(WALL, BEST_OF))
    assert (verdict.outcome, verdict.reason) == ("matched", "matched")
    match = verdict.match
    assert match is not None
    assert (match.deezer_id, match.album_id, match.album, match.record_type) == ("116914122", WALL, "The Wall", "album")
    assert (match.release_date, match.year, match.track_no, match.disc_no, match.isrc) == (
        "1979-11-30",
        1979,
        6,
        2,
        "GBN9Y1100113",
    )
    assert [(r.album_id, r.reason) for r in verdict.releases] == [(WALL, "chosen"), (BEST_OF, "outranked")]


def test_fade_into_you_the_238_second_edit_and_the_288_second_cut_are_rejected_by_length_alone() -> None:
    found = hits("mazzy star fade into you")
    song = Song("Mazzy Star", "Fade Into You", 292_000)
    assert reasons(judge_hits(song, found)) == {
        "3360821": "same_recording",
        "93477542": "title_or_version",  # The Avener Rework
        "3584532281": "length",  # (Edit): both signatures are empty, only the length tells them apart
        "44131701": "length",  # 288 s: 4 s off
        "2387789085": "title_or_version",  # (Live)
        "975408622": "artist",  # covers
        "1911843627": "artist",
        "2123174417": "artist",
    }
    assert wanted_albums(song, found) == ["319814"]
    fits = {v.id: v.name_fits for v in judge_hits(song, found)}
    assert [k for k, v in fits.items() if v] == ["3360821", "3584532281", "44131701"], (
        "the artist, title and version agree; the length is what failed"
    )
    edit = {v.id: v for v in judge_hits(Song("Mazzy Star", "Fade Into You (Edit)", 238_000), found)}
    assert edit["3584532281"].accepted and not edit["3360821"].accepted, "asked for the edit, the 292 s song is the one rejected"
    assert edit["3360821"].reason == "length" and edit["3360821"].delta_ms == -54_000


def test_hotel_california_a_remaster_is_the_same_recording() -> None:
    found = hits("hotel california")
    song = Song("Eagles", "Hotel California", 391_000)
    got = reasons(judge_hits(song, found))
    assert got["426703682"] == "same_recording", "'(2013 Remaster)' has an empty signature"
    assert {k: v for k, v in got.items() if v != "artist"} == {
        "426703682": "same_recording",
        "642692332": "title_or_version",  # (Live On MTV, 1994)
        "2421747515": "title_or_version",  # (Live)
        "426703852": "title_or_version",  # (Live at The Forum, ...)
    }
    assert wanted_albums(song, found) == ["51350192"]


def test_weird_fishes_five_covers_by_other_artists_are_rejected_and_the_original_is_another_title() -> None:
    found = hits("radiohead weird fishes")
    song = Song("Radiohead", "Weird Fishes", 318_000)
    got = reasons(judge_hits(song, found))
    assert got["138546809"] == "title_or_version", "Radiohead's own song is 'Weird Fishes / Arpeggi': another title"
    assert [k for k, v in got.items() if v == "artist"].__len__() == 7
    verdict = choose_release(song, found, {})
    assert (verdict.outcome, verdict.reason) == ("none", "no_same_recording") and verdict.remember
    assert wanted_albums(song, found) == []


def test_a_song_by_somebody_else_is_not_matched_with_the_real_recording_of_the_same_title_and_length() -> None:
    """Only the ARTIST differs: "Josh Cohen - Weird Fishes / Arpeggi" at Radiohead's 318 s against Radiohead's recorded hit (derived: the library's artist)."""
    song = Song("Josh Cohen", "Weird Fishes / Arpeggi", 318_000)
    got = {v.id: v for v in judge_hits(song, hits("radiohead weird fishes"))}
    assert got["138546809"].reason == "artist" and got["138546809"].delta_ms == 0 and got["138546809"].name_fits is False


def test_bohemian_rhapsody_a_live_version_three_seconds_away_and_a_live_aid_length_are_not_the_studio_song() -> None:
    found = hits("bohemian rhapsody")
    song = Song("Queen", "Bohemian Rhapsody", 354_000)
    got = {v.id: v for v in judge_hits(song, found)}
    assert got["4091937401"].accepted
    wembley = got["4092342471"]
    assert (wembley.delta_ms, wembley.reason) == (3_000, "title_or_version"), (
        "inside the tolerance: only the version tells it apart"
    )
    assert got["4091936771"].reason == "title_or_version"  # (Live Aid), 148 s
    assert got["4298783512"].reason == "artist"  # another 148 s Bohemian Rhapsody, by somebody else
    live_aid = {v.id: v for v in judge_hits(Song("Queen", "Bohemian Rhapsody (Live Aid)", 148_000), found)}
    assert [k for k, v in live_aid.items() if v.accepted] == ["4091936771"]


def test_only_the_catalogues_label_refuses_a_live_hit_so_an_unlabelled_live_upload_is_the_studio_song() -> None:
    """A LIMIT, pinned so that nobody states the opposite (the CHANGELOG line of N-34 slice 1 names it, in plain words): the matcher is given an artist, a
    title and a length, never where the file came from, and it reads a hit's version from the hit's TITLE only. DERIVED: the recorded Wembley hit (351 s,
    3 s inside the tolerance, on the album "Live at Wembley Stadium") with the label taken out of its title is the same recording; so is the recorded
    studio hit for a song that is in fact a live upload of the studio length. If a refusal is ever added (a look at the album's title, say), these two
    turn red: change them AND the CHANGELOG sentence together."""
    found = hits("bohemian rhapsody")
    song = Song("Queen", "Bohemian Rhapsody", 354_000)
    wembley = next(row for row in found if row["id"] == 4092342471)
    wembley["title"] = "Bohemian Rhapsody"
    got = {v.id: v for v in judge_hits(song, found)}
    assert (got["4092342471"].reason, got["4092342471"].delta_ms) == ("same_recording", 3_000)
    assert got["4091937401"].reason == "same_recording", "the studio song is the other candidate: nothing says which one it is"
    labelled = {v.id: v for v in judge_hits(song, hits("bohemian rhapsody"))}
    assert labelled["4092342471"].reason == "title_or_version", "with the label in its title the same hit is refused"


def test_a_different_title_with_the_right_artist_and_length_is_not_the_song() -> None:
    """ "Prova (Kifak Inta)" (211 s) is a different song on the single "Kifak Inta": only the TITLE differs from the library's "Kifak Inta" at 211 s."""
    got = {v.id: v for v in judge_hits(Song("Fairuz", "Kifak Inta", 211_000), hits("fairuz kifak inta"))}
    assert got["800748262"].reason == "title_or_version" and got["800748262"].delta_ms == 0
    assert (
        got["97733306"].accepted and got["3458672"].reason == "title_or_version"
    )  # 'Kifak Inta' (209 s) passes; the (Live) does not


@pytest.mark.parametrize(
    ("length_ms", "reason"),
    [(243_000, "same_recording"), (243_001, "length"), (237_000, "same_recording"), (236_999, "length")],
)
def test_the_tolerance_is_three_thousand_milliseconds_inclusive(length_ms: int, reason: str) -> None:
    requiem = copy.deepcopy(recorded_search("LANDMVRKS Requiem")["data"])  # 240 s
    (verdict,) = judge_hits(Song("LANDMVRKS", "Requiem", length_ms), requiem)
    assert verdict.reason == reason, (length_ms, verdict.delta_ms)
    assert verdict.delta_ms == length_ms - 240_000


def test_the_tolerance_can_be_given_and_is_the_servers_own_figure_measured_and_kept() -> None:
    requiem = copy.deepcopy(recorded_search("LANDMVRKS Requiem")["data"])
    assert judge_hits(Song("LANDMVRKS", "Requiem", 244_000), requiem, tolerance_ms=4_000)[0].accepted
    assert not judge_hits(Song("LANDMVRKS", "Requiem", 244_001), requiem, tolerance_ms=4_000)[0].accepted
    assert album_finder.TOLERANCE_MS == refs.DURATION_TOLERANCE_MS == 3_000
    source = inspect.getsource(album_finder)
    assert "TOLERANCE_MS = refs.DURATION_TOLERANCE_MS" in source, "imported from the one place, never copied"
    assert (
        "MEASURED on 24 Nov 2026 and KEPT at 3 s" in source
        and "UNMEASURED" not in source
        and "STOP-GAP(N-34 tolerance)" not in source
    ), "the measurement, its numbers and the price stay beside the constant; it is a decision now, not a stop-gap"


def test_a_hit_with_no_length_or_no_artist_is_never_the_same_recording() -> None:
    row = creature_hit()
    row["duration"] = 0
    nameless = creature_hit()
    nameless.pop("artist")
    junk: Any = "not a row"
    got = judge_hits(CREATURE, [row, nameless, junk])
    assert [v.reason for v in got] == ["no_length", "unreadable", "unreadable"]
    assert not any(v.accepted for v in got)


# ------------------------------------------------------------------------------------------------------------------ steps 3 to 5: which release


def creature_albums() -> dict[str, dict[str, Any]]:
    return albums(ALBUM, SINGLE)


def test_an_album_two_hits_are_on_is_asked_once_and_the_lowest_track_id_is_the_hit() -> None:
    """DERIVED: the recorded hit twice on the same album, the copy with another track id (a reissued track)."""
    twin = creature_hit()
    twin["id"] = 3116792062
    assert wanted_albums(CREATURE, [twin, creature_hit()]) == [ALBUM]
    verdict = choose_release(CREATURE, [twin, creature_hit()], albums(ALBUM))
    assert verdict.match is not None and verdict.match.deezer_id == "3116792061"


def test_an_album_beats_an_earlier_single_inside_the_window() -> None:
    """The recorded single is dated 2024-01-17, the recorded album 2025-04-18 (457 days): a lead single is older than its album. Slice 1 let the album win
    WHATEVER the dates; the advisor's ruling of 17 Nov 2026 lets it win only INSIDE a window, which is not frozen (`SINGLE_BEFORE_ALBUM_WINDOW_DAYS`, the rows
    of `test_album_withheld.py`): the window is given here, so that the rest of the rule is still pinned."""
    verdict = choose_release(CREATURE, [single_hit(), creature_hit()], creature_albums(), single_window_days=500)
    assert (verdict.outcome, verdict.reason) == ("matched", "matched")
    match = verdict.match
    assert match is not None
    assert (match.album_id, match.album, match.record_type, match.deezer_id, match.track_no, match.year) == (
        ALBUM,
        "The Darkest Place I've Ever Been",
        "album",
        "3116792061",
        2,
        2025,
    )
    assert not match.single
    assert {r.album_id: r.reason for r in verdict.releases} == {SINGLE: "outranked", ALBUM: "chosen"}


def test_a_single_is_its_own_release_when_nothing_else_carries_the_recording() -> None:
    verdict = choose_release(CREATURE, [single_hit()], albums(SINGLE))
    match = verdict.match
    assert verdict.outcome == "matched" and match is not None
    assert (match.album_id, match.album, match.record_type, match.track_no, match.deezer_id, match.isrc) == (
        SINGLE,
        "Creature",
        "single",
        1,
        "2586602502",
        "DEYO62300153",
    )
    assert match.single and match.release_date == "2024-01-17"


def test_an_ep_beats_a_single_that_is_older_and_an_album_beats_an_earlier_single() -> None:
    """DERIVED: the recorded album answer typed `single` (and dated 2024-06-01), the recorded single's answer typed `ep` and dated later (465 days: inside the
    window given below; the window itself is `test_album_withheld.py`'s)."""
    both = {
        ALBUM: derive(albums(ALBUM)[ALBUM], recordType="single", releaseDate="2024-06-01"),
        SINGLE: derive(albums(SINGLE)[SINGLE], recordType="ep", releaseDate="2025-09-09"),
    }
    verdict = choose_release(CREATURE, [creature_hit(), single_hit()], both, single_window_days=500)
    assert verdict.match is not None and verdict.match.album_id == SINGLE, "the ep wins although it is the later one"
    assert verdict.match.record_type == "ep"


@pytest.mark.parametrize("unknown", ["compile", "compilation", "live", "soundtrack", "", None, "album version"])
def test_an_unknown_record_type_never_wins_even_when_it_is_the_earlier_release(unknown: str | None) -> None:
    """DERIVED: the album's answer with a `recordType` nobody has seen and an EARLIER date than the single's."""
    both = {ALBUM: derive(albums(ALBUM)[ALBUM], recordType=unknown, releaseDate="2020-01-01"), SINGLE: albums(SINGLE)[SINGLE]}
    verdict = choose_release(CREATURE, [creature_hit(), single_hit()], both)
    assert verdict.match is not None and verdict.match.album_id == SINGLE
    assert {r.album_id: r.reason for r in verdict.releases} == {ALBUM: "record_type", SINGLE: "chosen"}
    alone = choose_release(CREATURE, [creature_hit()], {ALBUM: both[ALBUM]})
    assert (alone.outcome, alone.reason, alone.match) == ("none", "no_eligible_release", None)


def _recorded_release_types() -> tuple[dict[str, str], int]:
    """Every release (by Deezer's id) in Deezer's REAL recorded answers, with its `record_type`, and how many files hold some: the answers of
    `tests/fixtures/deezer/` and the 20 searches of `app/test/fixtures/deezer/search.json`. Not `app/test/fixtures/server/`: those are this server's own
    mapped copies of the same releases (a different key, folded editions), so counting them would count the same releases twice."""
    seen: dict[str, str] = {}
    holders = 0

    def walk(node: Any, found: dict[str, str]) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("record_type"), str):
                found[str(node.get("id"))] = node["record_type"]
            for value in node.values():
                walk(value, found)
        elif isinstance(node, list):
            for value in node:
                walk(value, found)

    for path in (*sorted(RECORDED.glob("*.json")), SEARCHES):
        found: dict[str, str] = {}
        walk(json.loads(path.read_text(encoding="utf-8")), found)
        holders += bool(found)
        for ident, kind in found.items():
            assert seen.setdefault(ident, kind) == kind, f"release {ident} has two types"
    return seen, holders


def test_the_record_types_of_every_recorded_release_are_the_ones_the_matcher_documents() -> None:
    """The numbers in `album_finder`'s comment above `_FULL_RELEASE`. They were once 49 / 1 / 13, which no set of recordings reproduces (49 and 1 are the Bob
    Marley list, 13 is LANDMVRKS' singles: two lists added up as if they were one). Recounted from ALL the tracked recordings; when someone records more,
    this fails and the comment is rewritten with the new counts."""
    seen, holders = _recorded_release_types()
    counts = {kind: sum(1 for value in seen.values() if value == kind) for kind in sorted(set(seen.values()))}
    assert counts == {"album": 116, "ep": 10, "single": 104}, counts
    assert len(seen) == 230 and holders == 12, (
        "230 releases in 11 answers of the server's folder (8 of step 0 and 3 of the live dry run of 24 Nov 2026: Ja Rule live and studio, Opeth remixed) and the 20 recorded searches"
    )
    assert set(counts) <= {"album", "ep", "single"}, (
        "no compile, no live, no remix value was ever recorded: the matcher's `never wins` rule is untested on a real one"
    )
    assert not {"compile", "live"} & set(counts)


def test_the_type_is_read_without_its_case() -> None:
    answer = derive(albums(ALBUM)[ALBUM], recordType="Album")
    assert choose_release(CREATURE, [creature_hit()], {ALBUM: answer}).outcome == "matched"


def test_the_earliest_release_date_beats_the_lowest_id() -> None:
    """DERIVED: the two recorded albums of Comfortably Numb with their dates SWAPPED, so the later date belongs to the lower id (The Wall, 12114248).
    The best-of's song list was not recorded: it gets the one row the rule reads (The Wall's recorded row of the song with the best-of's own track id).
    Its TITLE is shortened to "A Foot in the Door", because "The Best of Pink Floyd" is a compilation marker and would hold the match back
    (`test_album_withheld.py`): this row is about the date and the id."""
    pair = albums(WALL, BEST_OF)
    row = next(t for t in pair[WALL]["tracks"] if t["title"] == "Comfortably Numb")
    pair[BEST_OF]["tracks"] = [{**row, "id": "116914348", "trackNo": 14, "discNo": 1}]
    swapped = {
        WALL: derive(pair[WALL], releaseDate="2011-11-08", year=2011),
        BEST_OF: derive(pair[BEST_OF], releaseDate="1979-11-30", year=1979, title="A Foot in the Door"),
    }
    verdict = choose_release(COMFORTABLY_NUMB, hits("pink floyd comfortably numb"), swapped)
    assert verdict.match is not None and (verdict.match.album_id, verdict.match.year, verdict.match.track_no) == (
        BEST_OF,
        1979,
        14,
    )


def copy_as(album_id: str, track_id: str) -> dict[str, Any]:
    """DERIVED: the recorded album answer of "The Darkest Place I've Ever Been" under another album id, with the track of the recorded hit (the album's second
    track) under another track id."""
    answer = copy.deepcopy(albums(ALBUM)[ALBUM])
    answer["album"]["id"] = album_id
    answer["tracks"][1]["id"] = track_id
    return answer


def test_with_the_same_type_and_date_the_lowest_id_wins_and_ids_are_compared_as_numbers() -> None:
    """DERIVED: the recorded album answer copied under the ids "9" and "10" (the text order would say "10") with the same type and date; the recorded
    hit put on each of them with its own track id."""
    hit_ten, hit_nine = creature_hit(), creature_hit()
    hit_ten.update(id=1, album={"id": 10, "title": "x"})
    hit_nine.update(id=2, album={"id": 9, "title": "x"})
    verdict = choose_release(CREATURE, [hit_ten, hit_nine], {"10": copy_as("10", "1"), "9": copy_as("9", "2")})
    assert verdict.match is not None and verdict.match.album_id == "9" and verdict.match.deezer_id == "2"


@pytest.mark.parametrize("odd", ["²", "①", "⁹"])
def test_an_id_with_a_digit_that_is_not_an_ascii_digit_sorts_after_the_numbers_and_never_raises(odd: str) -> None:
    """`str.isdigit` is true for a superscript two, a circled one and a superscript nine, and `int()` refuses them (ValueError): the catalogue's ids are numbers
    sent as text, but `catalogue._id` passes ANY text through, so an odd id reaches the order. It sorts after every number, as any other non-number does."""
    assert odd.isdigit() and not odd.isdecimal(), "the premise: isdigit says yes where int() says no"
    with pytest.raises(ValueError):
        int(odd)
    assert album_finder._id_order(odd) == (1, 0, odd)
    assert album_finder._id_order("10") < album_finder._id_order(odd)
    assert album_finder._id_order("9") < album_finder._id_order("10") < album_finder._id_order("a") < album_finder._id_order(odd)
    # through the matcher: the album with the odd id and the one with the number are both candidates; the number wins, nothing raises
    on_odd, on_ten = creature_hit(), creature_hit()
    on_odd.update(id=1, album={"id": odd, "title": "x"})
    on_ten.update(id=2, album={"id": 10, "title": "x"})
    both = {odd: copy_as(odd, "1"), "10": copy_as("10", "2")}
    verdict = choose_release(CREATURE, [on_odd, on_ten], both)
    assert verdict.match is not None and (verdict.match.album_id, verdict.match.deezer_id) == ("10", "2")
    # two hits on the SAME chosen album, the second with an odd track id: the numeric id is the hit
    twin = creature_hit()
    twin["id"] = odd
    verdict = choose_release(CREATURE, [twin, creature_hit()], albums(ALBUM))
    assert verdict.match is not None and verdict.match.deezer_id == "3116792061"


def test_a_release_with_no_date_never_wins_earliest() -> None:
    """The catalogue's "unknown" date is `0000-00-00` (`map_album` keeps it): DERIVED, the single's answer with it and a LOWER id than the album's."""
    assert release_date("0000-00-00") is None and release_date("2025-04-18") == "2025-04-18"
    assert (
        release_date("1899-12-31") is None
        and release_date("2011") is None
        and release_date(None) is None
        and release_date("2011-13-01") is None
    )
    for bad in ("2011-11-00", "2011-11-32", "2011-00-10", "11-11-2011", "2011-1-1", ""):
        assert release_date(bad) is None, bad
    one, other = albums(ALBUM)[ALBUM], albums(ALBUM)[ALBUM]
    undated = derive(other, releaseDate="0000-00-00", year=0)
    undated["album"]["id"] = "5"
    undated["tracks"] = copy.deepcopy(one["tracks"])
    hit_undated = creature_hit()
    hit_undated.update(album={"id": 5, "title": "x"})
    verdict = choose_release(CREATURE, [hit_undated, creature_hit()], {"5": undated, ALBUM: one})
    assert verdict.match is not None and verdict.match.album_id == ALBUM, (
        "an album with no date loses to one with a date, whatever its id"
    )
    only = choose_release(CREATURE, [hit_undated], {"5": undated})
    assert only.match is not None and (only.match.release_date, only.match.year) == (None, None)


def test_the_album_artist_must_be_the_songs_first_artist() -> None:
    """DERIVED: the album's answer with another album artist (a compilation's "Various Artists", a tribute) and an EARLIER date than the single's."""
    for other in ("Various Artists", "Some Tribute Band", "LANDMVRKS فيروز"):
        both = {
            ALBUM: derive(albums(ALBUM)[ALBUM], artists=[{"id": "1", "name": other}], releaseDate="2020-01-01"),
            SINGLE: albums(SINGLE)[SINGLE],
        }
        verdict = choose_release(CREATURE, [creature_hit(), single_hit()], both)
        assert verdict.match is not None and verdict.match.album_id == SINGLE, other
        assert {r.album_id: r.reason for r in verdict.releases} == {ALBUM: "album_artist", SINGLE: "chosen"}, other
    no_artist = derive(albums(ALBUM)[ALBUM], artists=[])
    assert choose_release(CREATURE, [creature_hit()], {ALBUM: no_artist}).reason == "no_eligible_release"


def best_of_answer() -> dict[str, Any]:
    """DERIVED: the best-of's recorded answer with a song list that holds the hit (its own list was not recorded: the row is The Wall's recorded
    "Comfortably Numb" with the best-of's hit id, album and a track number)."""
    best_of = albums(BEST_OF)[BEST_OF]
    row = copy.deepcopy(next(t for t in albums(WALL)[WALL]["tracks"] if t["id"] == "116914122"))
    row.update(id="116914348", album={"id": BEST_OF, "title": best_of["album"]["title"]}, trackNo=7, discNo=1)
    best_of["tracks"] = [row]
    return best_of


# Two limits of slice 1 were PINNED here: "an original single loses to a same-artist best-of typed album whatever the dates" and "a same-artist best-of is chosen when
# it is the only release hit" (the lead's open question of 17 Nov 2026). The advisor's ruling of the same day closed both, so they flip: the first is
# `single_before_album` (re-askable; the song keeps no stamp), the second is `compilation_title` when the title says best-of and `matched` when it does not (a
# best-of called "Gold"). They are rewritten, with the rows the ruling adds, in `tests/test_album_withheld.py`.


def test_a_track_list_without_the_hits_id_is_a_miss_never_a_guess_at_another_release() -> None:
    """The single's own track (2586602502) claimed by the ALBUM's release: the album's recorded song list does not hold it. The single is not tried."""
    claim = single_hit()
    claim["album"] = {"id": int(ALBUM), "title": "The Darkest Place I've Ever Been"}
    verdict = choose_release(CREATURE, [claim, single_hit()], creature_albums())
    assert (verdict.outcome, verdict.reason, verdict.match) == ("none", "track_not_listed", None) and verdict.remember
    assert "2586602502" in verdict.detail and ALBUM in verdict.detail


def test_a_cut_song_list_is_told_apart_from_a_list_that_lacks_the_song() -> None:
    answer = albums(ALBUM)[ALBUM]
    answer["tracks"] = answer["tracks"][:1]  # the list stopped at 1 of 11 songs, before the song: the missing id proves nothing
    verdict = choose_release(CREATURE, [creature_hit()], {ALBUM: answer})
    assert (verdict.outcome, verdict.reason) == ("none", "track_list_cut")


def test_an_album_or_a_song_list_that_could_not_be_asked_is_unavailable_never_a_miss() -> None:
    nothing: list[dict[str, Any]] = [{}, {ALBUM: None}, {ALBUM: {"tracks": []}}]
    for missing in nothing:
        verdict = choose_release(CREATURE, [creature_hit()], missing)
        assert (verdict.outcome, verdict.reason, verdict.remember) == ("unavailable", "release_not_asked", False), missing
    answer = albums(ALBUM)[ALBUM]
    answer["unavailable"] = ["tracks"]
    answer["tracks"] = []
    verdict = choose_release(CREATURE, [creature_hit()], {ALBUM: answer})
    assert (verdict.outcome, verdict.reason, verdict.remember) == ("unavailable", "track_list_missing", False)
    # ... and ONE candidate album that could not be asked stops the decision: it may have been the earlier one.
    partly = choose_release(CREATURE, [creature_hit(), single_hit()], {ALBUM: albums(ALBUM)[ALBUM]})
    assert (partly.outcome, partly.detail) == ("unavailable", SINGLE)


def test_no_hit_of_the_same_recording_is_none_and_remembered() -> None:
    verdict = choose_release(Song("LANDMVRKS", "Creature", 100_000), [creature_hit()], {})
    assert (verdict.outcome, verdict.reason, verdict.remember) == ("none", "no_same_recording", True)
    assert choose_release(CREATURE, [], {}).reason == "no_same_recording"
    no_album = creature_hit()
    no_album.pop("album")
    assert choose_release(CREATURE, [no_album], {}).reason == "no_album_on_hit"


# ------------------------------------------------------------------------------------------------------------------ step 5: pairs


class Held:
    """What the other refs hold, as plain sets; remembers what it was asked."""

    def __init__(
        self, ids: set[str] | None = None, isrcs: set[str] | None = None, twins: set[tuple[str, str]] | None = None
    ) -> None:
        self.ids, self.isrcs, self.twins = ids or set(), isrcs or set(), twins or set()
        self.asked: list[tuple[str, ...]] = []

    def deezer_id_held(self, deezer_id: str) -> bool:
        self.asked.append(("id", deezer_id))
        return deezer_id in self.ids

    def isrc_held(self, isrc: str) -> bool:
        self.asked.append(("isrc", isrc))
        return isrc in self.isrcs

    def twin_held(self, norm_key: str, release: str) -> bool:
        self.asked.append(("twin", norm_key, release))
        return (norm_key, release) in self.twins


def test_a_taken_id_or_isrc_or_a_twin_on_the_same_release_is_held_and_names_what_would_have_been_written() -> None:
    found, both = [creature_hit()], albums(ALBUM)
    cases = [
        (Held(ids={"3116792061"}), "deezer_id_held"),
        (Held(isrcs={"DEYO62300153"}), "isrc_held"),
        (Held(twins={(refs.norm_key("LANDMVRKS", "Creature"), release_key("The Darkest Place I've Ever Been"))}), "twin_held"),
    ]
    for holdings, why in cases:
        verdict = choose_release(CREATURE, found, both, holdings)
        assert (verdict.outcome, verdict.reason, verdict.remember) == ("held", why, True)
        assert verdict.match is not None and verdict.match.deezer_id == "3116792061", "what WOULD have been written, for the log"
    nothing = Held()
    assert choose_release(CREATURE, found, both, nothing).outcome == "matched"
    assert nothing.asked == [
        ("id", "3116792061"),
        ("isrc", "DEYO62300153"),
        ("twin", refs.norm_key("LANDMVRKS", "Creature"), "darkest place i ve ever been"),
    ], "every kind of pair is looked for, with the ids ON THE CHOSEN release"


def test_a_twin_on_another_release_is_not_a_pair() -> None:
    other = Held(
        twins={(refs.norm_key("LANDMVRKS", "Creature"), release_key("Creature"))}
    )  # the single's release, not the album's
    assert choose_release(CREATURE, [creature_hit()], albums(ALBUM), other).outcome == "matched"


def test_no_holdings_is_the_default_and_holds_nothing() -> None:
    assert choose_release(CREATURE, [creature_hit()], albums(ALBUM)).outcome == "matched"
    assert not NO_HOLDINGS.deezer_id_held("1") and not NO_HOLDINGS.isrc_held("x") and not NO_HOLDINGS.twin_held("a|b|", "c")


def test_ref_holdings_read_the_database_and_never_count_the_song_itself(db: Database) -> None:
    def make(**song: Any) -> str:
        with db.tx() as conn:
            return str(refs.resolve(conn, {"title": "Creature", "artists": ["LANDMVRKS"], "durationMs": 225_000, **song})["id"])

    other = make(deezerId="3116792061", isrc="DEYO62300153", album="The Darkest Place I've Ever Been (Deluxe Edition)")
    own = make(title="Creature (Live)", durationMs=300_000)
    placeholder = make(title="Another One", album="[Unknown Album]")
    key = refs.norm_key("LANDMVRKS", "Creature")
    with db.tx() as conn:
        conn.execute("PRAGMA query_only = ON")  # the holdings only read: a write would fail here
        theirs = RefHoldings(conn, own)
        assert theirs.deezer_id_held("3116792061") and theirs.isrc_held("DEYO62300153")
        assert not theirs.deezer_id_held("1") and not theirs.isrc_held("NOPE")
        assert theirs.twin_held(key, release_key("The Darkest Place I've Ever Been")), (
            "a deluxe edition and its original are one release"
        )
        assert not theirs.twin_held(key, release_key("Creature")) and not theirs.twin_held(key, "")
        mine = RefHoldings(conn, other)
        assert (
            not mine.deezer_id_held("3116792061")
            and not mine.isrc_held("DEYO62300153")
            and not mine.twin_held(key, release_key("The Darkest Place I've Ever Been"))
        )
        unknown = RefHoldings(conn, own)
        assert not unknown.twin_held(refs.norm_key("LANDMVRKS", "Another One"), release_key("Unknown Album")), (
            "the placeholder is no album"
        )
    assert placeholder != other
    with db.tx() as conn:
        refs.resolve(conn, {"title": "Bar", "artists": ["Foo"], "durationMs": 100_000, "album": "???"})
        lone = str(refs.resolve(conn, {"title": "Bar", "artists": ["Foo"], "durationMs": 200_000})["id"])
        assert release_key("???") == "" and RefHoldings(conn, lone).twin_held(refs.norm_key("Foo", "Bar"), "") is False, (
            "never merged on an empty key"
        )


# ------------------------------------------------------------------------------------------------------------------ the network guard


def test_the_matcher_opens_no_connection_and_imports_no_network_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """The matcher is given the catalogue's answers and asks nobody. Two nets: the module imports nothing that can reach a network, and a connection
    attempt during a whole decision fails the test (the suite's own guard refuses an outside address; this one refuses ANY, loopback included)."""
    tree = ast.parse(inspect.getsource(album_finder))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {
        (node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0
    }
    assert not imported & {"httpx", "socket", "urllib", "requests", "http", "aiohttp", "ssl", "asyncio"}, imported
    attempts: list[object] = []

    def refuse(self: socket.socket, address: object) -> None:
        attempts.append(address)
        raise AssertionError(f"the matcher tried to connect to {address!r}")

    def refuse_ex(self: socket.socket, address: object) -> int:
        attempts.append(address)
        return 1

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_ex)
    choose_release(COMFORTABLY_NUMB, hits("pink floyd comfortably numb"), albums(WALL, BEST_OF))
    choose_release(CREATURE, [creature_hit(), single_hit()], creature_albums())
    assert attempts == []
