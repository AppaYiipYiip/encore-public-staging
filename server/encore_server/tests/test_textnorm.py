"""The shared text fold (P2-25, audit B-37): one fold for every alphabet, tested against the fixture the phone's twin reads as well.

`app/test/fixtures/text/fold-cases.json` is hand-written (the expected values come from the design table, never from this code) plus a generated
`corpus` section (`tools/gen_text_fold_table.py` writes it). Slice 1 built the fold; slices 2 and 3 moved every caller onto it: the five old functions
of `textnorm` are rebuilt on it (`test_the_five_old_functions_are_built_on_the_new_fold`), the `keys` rows are tested through `refs.norm_key`, and
`survives_fold_whole` is the era-1 rule (the era-0 column is the frozen rule of `keyrepair`).
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from encore_server import keyrepair, refs, textnorm
from tests import legacy_fold as legacy
from tests import textfold_corpus as corpus

FIXTURE = Path(__file__).resolve().parents[3] / "app" / "test" / "fixtures" / "text" / "fold-cases.json"
BUMP = "the fold changed: bump textnorm.TEXTNORM_REVISION (a rekey runs at the next start), then run tools/gen_text_fold_table.py to rewrite the fixture and the phone's table"


def _load() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _rows(section: str) -> list[Any]:
    return list(_load()[section])


def _ids(rows: list[Any], field: str) -> list[str]:
    return [f"{i}-" + re.sub(r"[^A-Za-z0-9]+", "_", str(r[field]))[:40] for i, r in enumerate(rows)]


_REMOVED_MARKS = {cp for lo, hi in textnorm.DECORATING_MARKS for cp in range(lo, hi + 1)}


def _key_of(x: str | list[str]) -> str:
    """A text is compared by `key_text`; a song `[artist, title]` by the key a ref is found by, `refs.norm_key` (`artist|title|version`, no version here)."""
    if isinstance(x, list):
        return refs.norm_key(x[0], x[1])
    return textnorm.key_text(x)


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the header: the fixture and the code name the same version and revision


def test_the_fixture_names_the_pinned_unicode_version_and_the_revision() -> None:
    data = _load()
    assert data["unidata_version"] == textnorm.UNICODE_VERSION
    assert data["revision"] == textnorm.TEXTNORM_REVISION
    assert data["corpus"]["unidata_version"] == textnorm.UNICODE_VERSION


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the hand-written rows

_FOLD = _rows("fold")


@pytest.mark.parametrize("row", _FOLD, ids=_ids(_FOLD, "note"))
def test_fold_rows(row: dict[str, Any]) -> None:
    folded = textnorm.fold(row["input"])
    assert folded == row["fold"], row["note"]
    assert textnorm.words(folded) == row["words"], row["note"]
    assert textnorm.key_text(row["input"]) == row["key"], row["note"]


_MEET = _rows("meet")


@pytest.mark.parametrize("row", _MEET, ids=_ids(_MEET, "note"))
def test_the_same_thing_with_and_without_decoration_meets(row: dict[str, Any]) -> None:
    assert _key_of(row["a"]) == _key_of(row["b"]), row["note"]


_DIFFER = _rows("differ")


@pytest.mark.parametrize("row", _DIFFER, ids=_ids(_DIFFER, "note"))
def test_two_different_things_differ(row: dict[str, Any]) -> None:
    assert _key_of(row["a"]) != _key_of(row["b"]), row["note"]


_KEYS = _rows("keys")


@pytest.mark.parametrize("row", _KEYS, ids=_ids(_KEYS, "note"))
def test_key_rows(row: dict[str, Any]) -> None:
    """The rows are the full key (`artist|title|version`) as `refs.norm_key(artist, title)` makes it, written by hand from the design."""
    assert refs.norm_key(row["artist"], row["title"]) == row["key"], row["note"]


_SURVIVES = _rows("survives")


@pytest.mark.parametrize("row", _SURVIVES, ids=_ids(_SURVIVES, "note"))
def test_the_frozen_old_fold_rule_is_the_era_0_column(row: dict[str, Any]) -> None:
    """Era 0 (decided against the OLD ASCII fold) is what stored data was made under; `keyrepair` keeps it frozen as `_lost_by_old_fold` (a name that
    does not survive the old fold is suspect). Slice 1 shipped it as `survives_fold_whole`; slice 2 moves that name to era 1."""
    assert (not keyrepair._lost_by_old_fold(row["text"])) is row["era0"], row["note"]


@pytest.mark.parametrize("row", _SURVIVES, ids=_ids(_SURVIVES, "note"))
def test_survives_fold_whole_is_true_for_every_text_with_a_letter_or_a_digit(row: dict[str, Any]) -> None:
    """Era 1, what every caller gets from slice 2 on (N-34 imports it): the guards at the call sites never fire for a name in any alphabet."""
    assert textnorm.survives_fold_whole(row["text"]) is row["era1"], row["note"]


def test_the_two_eras_agree_on_every_ascii_text() -> None:
    rng = random.Random(7)
    alphabet = "abcXYZ 019-'!?$"
    for _ in range(500):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8)))
        assert textnorm.survives_fold_whole(text) == (not keyrepair._lost_by_old_fold(text)), text


def test_the_era_1_function_is_not_kept_twice() -> None:
    """Slice 1 had two functions (era 0 for N-34 until slice 2, era 1 as a live test of the second column); slice 2 leaves ONE, the rule."""
    assert not hasattr(textnorm, "survives_fold_whole_era_1")


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# properties


def _old_words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", legacy.ascii_fold(text)).split()


def test_a_key_made_of_ascii_does_not_change() -> None:
    """20,000 seeded strings of ASCII letters, digits, punctuation, spaces and control characters give exactly the word list the old fold gives
    (so stored keys of Latin songs stay valid), by the fast path AND by the general path that every other alphabet takes."""
    rng = random.Random(20261115)
    ascii_chars = [chr(i) for i in range(128)]
    weighted = ascii_chars + [
        c for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -'&.,()[]!?" for _ in range(3)
    ]
    for _ in range(20_000):
        text = "".join(rng.choice(weighted) for _ in range(rng.randint(0, 24)))
        old = _old_words(text)
        assert textnorm.words(textnorm.fold(text)) == old, repr(text)
        assert textnorm.words(textnorm._fold_general(text)) == old, repr(text)
        assert textnorm._fold_general(text) == textnorm.fold(text), repr(text)
        if old:
            assert textnorm.key_text(text) == " ".join(old), repr(text)


def _assigned() -> list[str]:
    return [chr(cp) for cp in range(0x110000) if not 0xD800 <= cp <= 0xDFFF and unicodedata.category(chr(cp)) != "Cn"]


def test_fold_is_idempotent_over_every_code_point() -> None:
    bad = [f"U+{ord(ch):04X}" for ch in _assigned() if textnorm.fold(textnorm.fold(ch)) != textnorm.fold(ch)]
    assert bad == []


def test_a_letter_or_digit_folds_to_nothing_only_when_it_is_nothing_but_decoration() -> None:
    """The tatweel (a letter by category) is removed on purpose, and so are the Arabic presentation forms that are a space plus harakat (a shadda
    with a dammatan, U+FC5E) and the halfwidth voiced marks (a mark alone is not a word): what they ARE is decoration. Nothing else that is a letter
    or a number folds to nothing."""
    for ch in _assigned():
        if unicodedata.category(ch)[0] in "LN" and not textnorm.words(textnorm.fold(ch)):
            what_it_is = unicodedata.normalize("NFKC", ch).casefold()
            assert not any(unicodedata.category(c)[0] in "LN" and c != "ـ" for c in what_it_is), (
                f"U+{ord(ch):04X} folds to nothing"
            )
    assert textnorm.fold("ـ") == ""
    assert textnorm.key_text("ـ") == "ـ"  # the fallback: the case-folded original, so a key part is still not empty


def test_a_key_part_is_never_empty_when_there_is_something_to_read() -> None:
    for text in ["???", "!!!", "\U0001f3b5", "ـ", "(--)", "..."]:
        assert textnorm.key_text(text) != "", text
    assert textnorm.key_text("???") != textnorm.key_text("!!!")
    assert textnorm.key_text("") == ""
    assert textnorm.key_text("   ") == ""


def test_the_fallback_goes_from_the_cleaned_text_to_the_original() -> None:
    """A song called "Audio": its noise word is removed by the layer above the fold, the cleaned text is empty and the original is used."""
    assert textnorm.key_text("", "Audio") == "audio"
    assert textnorm.key_text(" ", "أغنية") == "اغنيه"
    assert textnorm.key_text("", "???") == "???"
    assert textnorm.key_text("abc", "xyz") == "abc"


def test_a_lone_surrogate_does_not_raise() -> None:
    """A title from outside can hold half of a surrogate pair; the fold treats it as an unassigned character (a gap), it never raises."""
    half = chr(0xD800)
    assert textnorm.fold("a" + half + "b") == "a" + half + "b"
    assert textnorm.words(textnorm.fold("a" + half + "b")) == ["a", "b"]
    assert textnorm.key_text(half) == half
    assert textnorm.survives_fold_whole(half) is False


def test_words_drop_a_token_made_only_of_marks() -> None:
    assert textnorm.words("ก\u0e48า \u0e48") == ["ก\u0e48า"]
    assert textnorm.words("\ufe0f") == []


def test_words_of_unfolded_ascii_still_keep_capitals() -> None:
    assert textnorm.words("Hello World-2") == ["Hello", "World", "2"]


def test_a_mark_before_a_format_character_still_composes() -> None:
    """The order trap: `か` + zero-width joiner + the voiced mark must compose to `が` (the format characters go first)."""
    assert textnorm.fold("か\u200d\u3099") == "が"


def test_every_decimal_digit_of_every_script_folds_to_ascii() -> None:
    nd = [ch for ch in _assigned() if unicodedata.category(ch) == "Nd"]
    assert len(nd) > 600
    assert all(textnorm.fold(ch) == str(unicodedata.decimal(ch)) for ch in nd)


def test_the_marks_of_the_allow_list_go_and_every_other_mark_stays() -> None:
    """Allow-list, not "strip every mark": what the table does not know stays distinct (design part 3, step 3)."""
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF or unicodedata.category(chr(cp)) not in ("Mn", "Mc", "Me") or cp == 0x0345:
            continue  # U+0345 (the Greek iota subscript) is a mark the CASE FOLD turns into the letter iota, which is what a reader of Greek means
        ch = chr(cp)
        folded = textnorm.fold("a" + ch)
        if cp in _REMOVED_MARKS:
            assert folded == "a", f"U+{cp:04X} should be removed"
        elif unicodedata.normalize("NFKC", "a" + ch) == "a" + ch:
            assert folded == "a" + ch, f"U+{cp:04X} should stay"


def test_seeded_mark_heavy_strings_are_idempotent() -> None:
    """Idempotence over single code points cannot catch an ORDER bug; strings out of the fixture's pool can."""
    random_section = _load()["corpus"]["random"]
    pool = random_section["pool"]
    other_seed = random_section["seed"] + 1
    bad = []
    for text in corpus.random_strings(pool, other_seed, 20_000, random_section["max_length"]):
        once = textnorm.fold(text)
        if textnorm.fold(once) != once:
            bad.append(text.encode("unicode_escape").decode())
            if len(bad) > 5:
                break
    assert bad == []


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the generated section: the fold of every code point and of 20,000 random strings, as digests (a Python upgrade that changes a result fails here)


def test_the_corpus_digests_of_the_fold_have_not_moved() -> None:
    have = corpus.fold_pages(textnorm.fold)
    assert have == _load()["corpus"]["fold_pages"], BUMP


def test_the_corpus_digests_of_the_classes_have_not_moved() -> None:
    assert corpus.class_pages() == _load()["corpus"]["class_pages"], BUMP


def test_the_corpus_digest_of_the_random_strings_has_not_moved() -> None:
    section = _load()["corpus"]["random"]
    have = corpus.random_digest(
        textnorm.fold, textnorm.words, section["pool"], section["seed"], section["count"], section["max_length"]
    )
    assert have == section["digest"], BUMP


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# slices 2 and 3 moved every caller


def test_the_five_old_functions_are_built_on_the_new_fold() -> None:
    """The names stay (no caller changes shape), the fold under them is the new one: an Arabic, Russian or extended-Latin name is no longer nothing.
    Slice 1 pinned the opposite (`norm_title("Łukasz") == "ukasz"`); that pin is the flip this slice makes on purpose."""
    assert textnorm.norm_title("Łukasz") == "lukasz"
    assert textnorm.norm_artist("كلمة") == "كلمه"
    assert textnorm.norm_title("Straße") == "strasse"
    assert textnorm.norm_artist("Кино") == "кино"
    assert not hasattr(textnorm, "ascii_fold"), (
        "its name says ASCII: every caller now folds with `fold`, and nothing else keeps a second fold"
    )


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the Arabic and Persian rows against the real sources of Lucene (read at the tag the fixture names)

#: What the sources say, read 16 Nov 2026 at `releases/lucene/10.3.2` (annotated tag object 8241bb80dc7f3ef1be6f222f40cc6cbfa9a9aa98, commit dadfd90b4401947f4d0387669dc94999fbb2c830), file by file. Every `(from, to)` is a
#: `case` of `ArabicNormalizer.normalize` or `PersianNormalizer.normalize`; a `to` of `""` is a `delete`. `PersianCharFilter` turns U+200C into a space.
_LUCENE_ARABIC = [
    ("آ", "ا"),  # ALEF_MADDA -> ALEF
    ("أ", "ا"),  # ALEF_HAMZA_ABOVE -> ALEF
    ("إ", "ا"),  # ALEF_HAMZA_BELOW -> ALEF
    ("ى", "ي"),  # DOTLESS_YEH -> YEH
    ("ة", "ه"),  # TEH_MARBUTA -> HEH
    ("ـ", ""),  # TATWEEL
    ("ً", ""),  # FATHATAN
    ("ٌ", ""),  # DAMMATAN
    ("ٍ", ""),  # KASRATAN
    ("َ", ""),  # FATHA
    ("ُ", ""),  # DAMMA
    ("ِ", ""),  # KASRA
    ("ّ", ""),  # SHADDA
    ("ْ", ""),  # SUKUN
]
_LUCENE_PERSIAN = [
    ("ی", "ي"),  # FARSI_YEH -> YEH
    ("ے", "ي"),  # YEH_BARREE -> YEH
    ("ک", "ك"),  # KEHEH -> KAF
    ("ۀ", "ه"),  # HEH_YEH -> HEH
    ("ہ", "ه"),  # HEH_GOAL -> HEH
    ("ٔ", ""),  # HAMZA_ABOVE deleted
]


@pytest.mark.parametrize(
    ("source", "target"), _LUCENE_ARABIC + _LUCENE_PERSIAN, ids=[f"U+{ord(s):04X}" for s, _ in _LUCENE_ARABIC + _LUCENE_PERSIAN]
)
def test_every_mapping_of_lucenes_arabic_and_persian_filters_is_in_the_fold(source: str, target: str) -> None:
    """The fold is a superset of the two filters: each of their `case` branches gives the same letter (or deletes the same character), inside a word."""
    assert textnorm.fold("ب" + source + "ب") == "ب" + target + "ب"


def test_the_half_space_is_a_space_as_lucenes_persian_char_filter_has_it() -> None:
    assert textnorm.fold("می‌خواهم") == "مي خواهم"


def test_the_hamza_seats_are_kept_apart_as_in_lucene() -> None:
    """Neither filter folds `ؤ ئ ء` (kept apart on purpose, ruling D1)."""
    for seat in "ؤئء":
        assert textnorm.fold("ب" + seat + "ب") == "ب" + seat + "ب"


def test_the_fixture_names_the_lucene_release_it_was_checked_against() -> None:
    note = _load()["lucene"]
    assert "releases/lucene/10.3.2" in note
    assert "dadfd90b4401947f4d0387669dc94999fbb2c830" in note, (
        "the COMMIT of the tag, not only the annotated tag object (8241bb80...)"
    )
    assert "8241bb80dc7f3ef1be6f222f40cc6cbfa9a9aa98" in note
    assert "not checked" not in note.lower().split(":")[0]
