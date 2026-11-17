"""N-26 slice 4: the NEGATIVE CORPUS of the upload reader (docs/tasks/P2-songs-as-references.md, "N-26", slice 4).

`tests/fixtures/n26_upload_corpus.json` holds every YouTube upload title the repository knows (the recorded answers of YouTube Music in `tests/fixtures/ytm`,
the titles of the reader tests, and hand-written titles that use *live, op, ed, ost, session, by, in, at* as ordinary words, in four alphabets) with the
artist, the song and the basis `read_upload` must give. **A rule of the reader is accepted only if no `negative` row changes.** The first, wider rule of the
design (any "op", "ed", "ost", "session", "by" or "live in") failed exactly this: "Ed Sheeran - Stand By Me" gave the artist "Me", "Chopin - Nocturne Op. 9 No. 2 |
Piano" the uploader, "We Live in Fear" the artist "We".

Three kinds of row (the file says so too):

* `negative`: right today (a performer named by the title, or an upload that names nobody and keeps its uploader, flagged `channel`: the design's stop-gap). Must not change.
* `fixed`: wrong before slice 4 and a target of it (`before` holds the old reading, so the file shows what changed).
* `leftover`: wrong before AND after; `why` says what it needs and which task owns it. Asserted at the CURRENT reading too, so a drift is a decision.

Pure logic, no I/O but the fixture files; no network.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

from encore_server import textnorm
from encore_server.imports.uploads import read_upload
from tests import legacy_fold as legacy

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CORPUS = json.loads((FIXTURES / "n26_upload_corpus.json").read_text(encoding="utf-8"))
ROWS: list[dict[str, Any]] = CORPUS["rows"]
KINDS = {"negative", "fixed", "leftover"}
#: The one probe the argument below needs: `<X>, live at ...` or `<X>: live at ...` (a comma or a colon, then "live at").
LIVE_AT = re.compile(r"[,:]\s+live\s+at\b", re.IGNORECASE)


def reading(title: str, uploader: str) -> tuple[str, str, str]:
    result = read_upload(title, uploader)
    return result.artist, result.title, result.basis


def of(kind: str) -> list[dict[str, Any]]:
    return [row for row in ROWS if row["kind"] == kind]


# --------------------------------------------------------------------------- every row reads as the corpus says


@pytest.mark.parametrize("row", ROWS, ids=[row["id"] for row in ROWS])
def test_every_row_of_the_corpus_is_read_as_it_says(row: dict[str, Any]) -> None:
    """The whole point: no negative row changes (and no leftover drifts, and every fixed row reads as its new reading)."""
    assert reading(row["title"], row["uploader"]) == (row["artist"], row["song"], row["basis"]), (row["kind"], row["title"])


# --------------------------------------------------------------------------- the corpus itself is what it claims to be


def test_the_corpus_is_big_enough_and_honest_about_its_kinds() -> None:
    assert len({row["id"] for row in ROWS}) == len(ROWS), "ids are unique"
    assert len({(row["title"], row["uploader"]) for row in ROWS}) == len(ROWS), "a title and uploader pair appears once"
    assert {row["kind"] for row in ROWS} <= KINDS
    assert len(of("negative")) >= 150
    hand_negatives = [row for row in of("negative") if row["source"] == "hand"]
    assert len(hand_negatives) >= 40, "at least 40 hand-written good titles"
    for row in of("leftover") + of("fixed"):
        assert row.get("why"), f"{row['id']}: a row that is wrong before says why and what owns it"
    for row in of("fixed"):
        before = (row["before"]["artist"], row["before"]["song"], row["before"]["basis"])
        assert before != (row["artist"], row["song"], row["basis"]), f"{row['id']}: a fixed row must differ from its old reading"


def test_the_audits_three_strings_are_in_the_corpus() -> None:
    """B-125: the three titles the importer used to file under KEXP, ARTE Concert and Crunchyroll."""
    by_title = {(row["title"], row["uploader"]): row for row in ROWS}
    tinariwen = by_title["Tinariwen - Full Performance (Live on KEXP)", "KEXP"]
    assert (tinariwen["kind"], tinariwen["artist"]) == ("negative", "Tinariwen"), "right since slice 1"
    arte = by_title["Sepultura, live at Hellfest Open Air 2026 – ARTE Concert", "ARTE Concert"]
    crunchyroll = by_title["DAN DA DAN Opening | Otonoke by Creepy Nuts", "Crunchyroll"]
    assert arte["kind"] in {"fixed", "leftover"}
    assert crunchyroll["kind"] in {"fixed", "leftover"}


def recorded_upload_entries() -> dict[tuple[str, str], str]:
    """The (title, uploader) pairs of every recorded entry the readers send to `read_upload`: not a song of the catalogue, not an official music video, and not
    an entry with no `videoType` that has an album (a removed song of the catalogue). Same gate as `readers._read_entry`."""
    songs = {"MUSIC_VIDEO_TYPE_ATV", "MUSIC_VIDEO_TYPE_OFFICIAL_SOURCE_MUSIC", "MUSIC_VIDEO_TYPE_OMV"}
    found: dict[tuple[str, str], str] = {}
    for path in sorted((FIXTURES / "ytm").rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("results") or data.get("tracks") or []:
            kind = entry.get("videoType")
            album = entry.get("album")
            if kind in songs or (not kind and isinstance(album, dict) and str(album.get("name") or "").strip()):
                continue
            names = [str(a.get("name") or "") for a in entry.get("artists") or []]
            found.setdefault((entry["title"], names[0] if names else ""), path.relative_to(FIXTURES / "ytm").as_posix())
    return found


def test_every_recorded_upload_is_judged_in_the_corpus() -> None:
    """A new recording cannot slip past the corpus: each recorded upload title has a row, and each recorded row names the file it came from."""
    corpus = {(row["title"], row["uploader"]): row for row in ROWS}
    recorded = recorded_upload_entries()
    assert len(recorded) >= 110, "a guard against fixtures that quietly stopped being read"
    for key, source in recorded.items():
        assert key in corpus, f"recorded upload not judged yet ({source}): {key}"
    for row in ROWS:
        if row["source"].startswith("recorded:"):
            assert (row["title"], row["uploader"]) in recorded, f"{row['id']} says it is recorded but no fixture holds it"


# --------------------------------------------------------------------------- other alphabets (audit B-37 / P2-25)


def test_P2_25_a_name_in_another_alphabet_is_read_right_and_the_servers_fold_now_sees_it() -> None:
    """Audit B-37 / P2-25 slice 2: the server's fold used to keep a-z0-9 only, so an Arabic, Russian or Japanese name folded to the empty string, and this test
    PINNED that (the reader of uploads compared names by their letters in any alphabet on its own). The corpus has non-Latin rows that are right; this proves the
    rows exist (the six scripts, picked by what the FROZEN old fold lost) and that the shared fold now gives every one of those artists a key of its own."""
    non_latin = [row for row in of("negative") if row["artist"] and not legacy.ascii_fold(row["artist"]).strip()]
    scripts = {
        "arabic": any("؀" <= ch <= "ۿ" for row in non_latin for ch in row["artist"]),
        "cyrillic": any("Ѐ" <= ch <= "ӿ" for row in non_latin for ch in row["artist"]),
        "japanese": any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for row in non_latin for ch in row["artist"]),
        "korean": any("가" <= ch <= "힯" for row in non_latin for ch in row["artist"]),
        "greek": any("Ͱ" <= ch <= "Ͽ" for row in non_latin for ch in row["artist"]),
        "hebrew": any("֐" <= ch <= "׿" for row in non_latin for ch in row["artist"]),
    }
    assert all(scripts.values()), scripts
    assert legacy.ascii_fold("فيروز").strip() == ""  # Arabic: the old trap, frozen in tests/legacy_fold.py
    for row in non_latin:
        assert textnorm.norm_artist(row["artist"]), row["id"]
    assert textnorm.norm_artist("فيروز") == "فيروز" and textnorm.norm_artist("Кино") != textnorm.norm_artist("Любэ")


# --------------------------------------------------------------------------- why the live-credit shape is NOT read (decided: left to N-28)


def live_credit_features(title: str, uploader: str) -> tuple[bool, bool]:
    """Everything a rule for `<X>, live at <V> – <Channel>` can look at: whether the left side is `<X>[,:] live at ...` and whether the whole right side is
    the uploader's name (the one thing that makes the right side a credit and not a song, see `read_upload`)."""
    from encore_server.imports import uploads

    sides = uploads._real_split(title)
    if sides is None:
        return (False, False)
    left, right = sides
    live = LIVE_AT.search(left) is not None
    whole = uploads._name_key(uploads.clean_title(right)) == uploads._channel_key(uploader)
    return (live, whole)


def test_a_live_credit_shape_cannot_tell_the_broadcaster_from_the_performer_so_it_is_not_built() -> None:
    """The ARTE rows and the performer-uploaded counter-examples (right today) have the SAME features, so no rule that reads only the title and the uploader can
    fix the first without changing the second. The corpus therefore refuses shape (b) of the design: the ARTE rows are `leftover` (owner N-28, the catalogue names
    the artist by the title), the counter-examples stay `negative`. Decided on 15 Nov (the advisor, option 3): a length threshold would be a guess that needs
    recordings no helper may make, and today's basis `channel` is safe (no artist page, no picture, no catalogue question)."""
    arte = [row for row in ROWS if row.get("why", "").startswith("SHAPE (b), DECIDED NOT TO READ")]
    performer = [row for row in ROWS if row["source"] == "hand" and "COUNTER-EXAMPLE" in row.get("why", "")]
    assert len(arte) == 2, [row["title"] for row in arte]
    assert len(performer) == 4
    assert {row["kind"] for row in arte} == {"leftover"}
    assert {row["kind"] for row in performer} == {"negative"}
    shared = {live_credit_features(row["title"], row["uploader"]) for row in arte + performer}
    assert shared == {(True, True)}, "the two families look the same to any rule that reads only the title and the uploader"
