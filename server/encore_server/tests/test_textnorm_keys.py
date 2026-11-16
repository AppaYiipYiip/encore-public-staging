"""P2-25 slices 2 and 3 (audit B-37): the five functions of `textnorm` and the key `refs.norm_key` are built on the one fold.

Written BEFORE the code and seen red on main `95d1293`. Three things are proved here, each with its counterpart so that a test cannot pass by merging everything
or by separating everything (on the old fold every non-Latin title is the empty string, so "meets" tests alone would be green for the wrong reason):

* what a key made of ASCII was, it still is (the frozen old functions in `tests/legacy_fold.py` are the witness; 20,000 strings built from the TOKENS the regex layer above
  the fold reads: noise words, brackets, `feat.`, version words, a dash and a year, apostrophes, `Topic` and `VEVO`: random characters almost never reach that layer);
* the same song with and without decoration meets, two different songs do not, in the four shapes of the design (fully non-Latin, mixed script, extended Latin, typographic);
* the dense-script rule: a title of at most four Han, Kana or Hangul characters is compared for equality.
"""

from __future__ import annotations

import random
import re

import pytest

from encore_server import refs, textnorm
from tests import legacy_fold as legacy

# ---------------------------------------------------------------------------------------------------------------------------------------------------
# a key made of ASCII does not change

_TOKENS = [
    "Official", "Video", "Audio", "Lyrics", "Lyric Video", "HD", "4K", "Remastered", "Remaster", "Explicit", "Visualizer", "Music Video", "Full Album",
    "Topic", "feat.", "ft.", "featuring", "Live", "Cover", "Karaoke", "Instrumental", "Remix", "Sped Up", "8D", "Acoustic", "Demo", "Mashup",
    "(Live)", "[Official Video]", "{Demo}", "(feat. Someone)", "(2011 Remaster)", "(The Avener Rework)", "- Remastered 2011", "- Single", "- Radio Edit",
    "- Live at Wembley", "- 1999", "2011", "1999", "'", "-", "&", ",", "!", "?", "$", "@", "+", "x", "with", "Don't", "Fade Into You", "Dancing Queen",
    "ABBA", "Kino", "VEVO", "- Topic", "official", "the", "a", "of", "from", "Version", "Edition", "Mono", "Stereo", "Deluxe", "Bonus Track",
    "Weird Fishes / Arpeggi", "AC/DC", "Mötley Crüe".encode("ascii", "ignore").decode(), "99 Luftballons", "  ", " ", "_", "...", "(", ")", "[", "]",
]  # fmt: skip


def _strings(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        parts = [rng.choice(_TOKENS) for _ in range(rng.randint(1, 8))]
        out.append("".join(p + rng.choice([" ", " ", " ", "", "  ", " - ", ", "]) for p in parts).strip())
    return out


def test_the_five_functions_give_what_they_gave_on_every_ascii_string() -> None:
    """No exception: the word rules (noise words, brackets, feat, version words) sit above the fold and the fold keeps ASCII as it was."""
    for text in _strings(20261116, 20_000):
        assert textnorm.norm_title(text) == legacy.norm_title(text), repr(text)
        assert textnorm.norm_artist(text) == legacy.norm_artist(text), repr(text)
        assert textnorm.version_signature(text) == legacy.version_signature(text), repr(text)
        assert textnorm.mentions_version(text) == legacy.mentions_version(text), repr(text)


def test_a_stored_key_made_of_ascii_does_not_change_except_where_it_was_empty() -> None:
    """`refs.norm_key` on 20,000 (artist, title) pairs against the frozen old key. Where the old artist or title segment was EMPTY (a song called "Audio" or
    "Official Video", "???": the old key was `x||`, shared by every such song of one artist) the new segment is the fallback (never empty while there is
    something to read): that change is the point. Everywhere else the key is byte for byte what it was, so a Latin library is rekeyed to itself."""
    texts = _strings(7, 20_000)
    changed = 0
    for artist, title in zip(texts, reversed(texts), strict=True):
        old = legacy.norm_key(artist, title)
        new = refs.norm_key(artist, title)
        old_artist, old_title, old_version = old.split("|")
        new_artist, new_title, new_version = new.split("|")
        assert new_version == old_version, (artist, title)
        for old_part, new_part, source in ((old_artist, new_artist, artist), (old_title, new_title, title)):
            if old_part:
                assert new_part == old_part, (artist, title, old, new)
            else:
                changed += 1
                expected = " ".join(re.findall(r"[a-z0-9]+", source.lower())) or " ".join(source.split()).casefold()
                assert new_part == expected, (artist, title, old, new)
    assert changed > 100, "the token pool must reach the old empty segments, or this test checks nothing about them"


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the apostrophe, the brackets, the credits


def test_a_curly_apostrophe_is_the_same_song_as_a_straight_one() -> None:
    assert refs.norm_key("Artist", "Don’t Stop") == refs.norm_key("Artist", "Don't Stop")
    assert textnorm.version_signature("Song (Don’t Stop)") == textnorm.version_signature("Song (Don't Stop)")


def test_a_mark_in_black_lenticular_brackets_is_a_tag_to_remove() -> None:
    assert textnorm.norm_title("【MV】夜に駆ける") == textnorm.norm_title("夜に駆ける")
    assert textnorm.norm_title("夜に駆ける〔Official〕") == textnorm.norm_title("夜に駆ける")


def test_the_quoting_corner_brackets_are_punctuation_not_tags() -> None:
    """`YOASOBI「夜に駆ける」Official Music Video` names the song INSIDE the corner brackets: removing the brackets with their content would remove the title
    (the design's list was written without this case; the four quoting pairs are punctuation, the two decoration pairs are brackets: see the PR)."""
    assert "夜に駆ける" in textnorm.norm_title("YOASOBI「夜に駆ける」Official Music Video")
    assert refs.norm_key("YOASOBI", "「夜に駆ける」") == refs.norm_key("YOASOBI", "夜に駆ける")
    assert textnorm.norm_title("Spirited Away「Always With Me」") != textnorm.norm_title("Spirited Away「One Summer’s Day」")


def test_a_credit_is_cut_at_the_arabic_and_ideographic_commas_and_the_semicolon() -> None:
    assert textnorm.artist_parts("فيروز، ام كلثوم") == ["فيروز", "ام كلثوم"]
    assert textnorm.artist_parts("فيروز؛ ام كلثوم") == ["فيروز", "ام كلثوم"]
    assert textnorm.artist_parts("宇多田ヒカル、椎名林檎") == ["宇多田ヒカル", "椎名林檎"]
    assert textnorm.artist_parts("A; B") == ["A", "B"]
    assert textnorm.artist_parts("Earth, Wind & Fire") == [
        "Earth",
        "Wind",
        "Fire",
    ]  # unchanged: the whole name is tried first by the matchers


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# two songs, in the four shapes: the same song meets (with and without decoration) and two different songs do not

SAME = [
    ("fully non-Latin: harakat", ("فيروز", "سألوني الناس"), ("فيروز", "سَأَلُوني الناس")),
    ("fully non-Latin: alef forms and teh marbuta", ("فيروز", "أغنية حلوة"), ("فيروز", "اغنيه حلوه")),
    ("fully non-Latin: a tatweel", ("فيروز", "حبيبي"), ("فيروز", "حبيـــبي")),
    ("fully non-Latin: Arabic-Indic digits", ("Fairuz", "أغنية ١٢"), ("Fairuz", "أغنية 12")),
    ("Russian: yo and ye", ("Кино", "Ёлки"), ("Кино", "Елки")),
    ("Russian: stress mark", ("Кино", "Группа крови"), ("Кино", "Гру́ппа крови")),
    ("Persian: the half-space and a space", ("Googoosh", "می‌خواهم"), ("Googoosh", "می خواهم")),
    ("Greek: tonos and final sigma", ("Δήμητρα", "Ο Ήλιος"), ("Δημητρα", "Ο Ηλιοσ")),
    ("Japanese: halfwidth katakana", ("YOASOBI", "ｱｲﾄﾞﾙ"), ("YOASOBI", "アイドル")),
    ("extended Latin: l with stroke", ("Łukasz", "Łódź"), ("Lukasz", "Lodz")),
    ("extended Latin: sharp s", ("Sia", "Straße"), ("Sia", "Strasse")),
    ("extended Latin: thorn", ("Þórunn", "Song"), ("Thorunn", "Song")),
    ("extended Latin: stacked marks", ("Nguyễn", "Song"), ("Nguyen", "Song")),
    ("extended Latin: dotless i", ("Tarkan", "Şımarık"), ("Tarkan", "Simarik")),
    ("extended Latin: o with stroke", ("Bjørk", "Hyperballad"), ("Bjork", "Hyperballad")),
    ("typographic: curly apostrophe", ("Artist", "Don’t Stop"), ("Artist", "Don't Stop")),
]
DIFFERENT = [
    ("two Arabic songs of one artist", ("فيروز", "سألوني الناس"), ("فيروز", "نسّم علينا الهوا")),
    ("two Russian songs of one band", ("Кино", "Группа крови"), ("Кино", "Звезда по имени Солнце")),
    ("two Korean songs of one band", ("BTS", "봄날"), ("BTS", "봄밤")),
    ("a Latin artist, a title that only STARTS the same", ("Fairuz", "Habibi يا نور"), ("Fairuz", "Habibi يا قمر")),
    ("two Arabic artists, one Latin title", ("فيروز", "Habibi"), ("ام كلثوم", "Habibi")),
    ("two Japanese titles of one artist", ("YOASOBI", "夜に駆ける"), ("YOASOBI", "群青")),
    ("two Japanese artists, one Latin title", ("宇多田ヒカル", "First Love"), ("椎名林檎", "First Love")),
    ("two Russian artists, one Latin title", ("Кино", "Hello"), ("Любэ", "Hello")),
    ("a Latin band and an Arabic one", ("Fairuz", "حبيبي"), ("فيروز", "حبيبي")),
    ("l with stroke is not nothing", ("Łukasz", "Song"), ("Ukasz", "Song")),
    ("a long vowel is not a short one", ("Кино", "мой"), ("Кино", "мои")),
    ("voiced and unvoiced kana", ("YOASOBI", "が"), ("YOASOBI", "か")),
    ("a hamza seat is a different word", ("فيروز", "مسؤول"), ("فيروز", "مسوول")),
    ("two titles that are only a symbol", ("X", "???"), ("X", "!!!")),
    (
        "a bracket word still tells a rework apart",
        ("Mazzy Star", "Fade Into You"),
        ("Mazzy Star", "Fade Into You (The Avener Rework)"),
    ),
]


@pytest.mark.parametrize(("why", "a", "b"), SAME, ids=[row[0] for row in SAME])
def test_the_same_song_meets(why: str, a: tuple[str, str], b: tuple[str, str]) -> None:
    assert refs.norm_key(*a) == refs.norm_key(*b), why


@pytest.mark.parametrize(("why", "a", "b"), DIFFERENT, ids=[row[0] for row in DIFFERENT])
def test_two_different_songs_do_not_share_a_key(why: str, a: tuple[str, str], b: tuple[str, str]) -> None:
    assert refs.norm_key(*a) != refs.norm_key(*b), why


def test_no_part_of_a_key_is_empty_for_a_song_in_any_alphabet() -> None:
    for artist, title in [
        ("فيروز", "سألوني الناس"),
        ("Кино", "Группа крови"),
        ("BTS", "봄날"),
        ("宇多田ヒカル", "初恋"),
        ("X", "Audio"),
        ("X", "Official Video"),
        ("???", "!!!"),
    ]:
        key_artist, key_title, _ = refs.norm_key(artist, title).split("|")
        assert key_artist and key_title, (artist, title)


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the dense scripts: a short title is compared for equality (the thresholds were calibrated on Latin characters)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("사랑해", "사랑이", 0.0),  # 0.667 by characters: above the 0.6 title bar, so one syllable off would have been accepted
        ("사랑해", "사랑해", 1.0),
        ("봄날", "봄밤", 0.0),
        ("初恋", "初戀", 0.0),
        ("初恋", "初恋", 1.0),
        ("アイドル", "アイトル", 0.0),  # four characters: still equality
        ("아름다운", "아름다웠", 0.0),
        ("мой", "мои", 2 / 3),  # Cyrillic is not a dense script: the ratio stays
        ("حبيبي", "حبيبتي", 10 / 11),
        ("abc", "abd", 2 / 3),
        ("夜に駆ける", "夜を駆ける", 0.8),  # five characters: the ratio stays until N-16 measures it
    ],
)
def test_a_short_title_in_a_dense_script_is_compared_for_equality(a: str, b: str, expected: float) -> None:
    assert textnorm.ratio(a, b) == pytest.approx(expected, abs=1e-9)


def test_the_dense_rule_looks_at_either_side() -> None:
    """A short Hangul title against a long one is not a near match either: equality fails, the ratio is not asked."""
    assert textnorm.ratio("사랑해", "사랑해 사랑해") == 0.0
    assert textnorm.ratio("BTS 봄날", "BTS 봄밤") == pytest.approx(
        10 / 12
    )  # mixed: not only dense characters, so the ratio stays
