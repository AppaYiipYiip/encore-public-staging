"""N-34 slice 2, the matcher half: what the advisor's RULING of 17 Nov 2026 (board note on N-34, binding) adds to `album_finder.choose_release`.

**The principle.** The pass writes an album only where the field is empty or the placeholder and never rewrites it, and the repair (slice 5) files a song BY
that album, so a stamped album is effectively permanent. Anything the matcher cannot justify on evidence therefore lands in a RE-ASKABLE outcome (`none` with a
reason: asked again after 7 days and whenever `IDENTITY_REVISION` rises), never in `matched`:

1. A same-artist best-of is a real release of the recording and is ACCEPTED when it is the only candidate; a title marker ("Greatest Hits", "Best Of",
   "Collection") may only DOWNGRADE such a match to re-askable and is never the rule (a best-of called "Gold" passes).
2. An album outranks an EARLIER single only INSIDE a window MEASURED from the recordings (step 0, below). The recordings hold too few pairs to show one, so
   the window is NOT FROZEN and that case is re-askable until the live dry run. The machinery is built, so freezing it is one constant and a revision bump.
3. The artist-discography lookup is not built.

Data: the recorded answers as in `test_album_finder.py`; a derived case starts from a recorded answer and changes exactly the named fields.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from encore_server import album_finder
from encore_server.album_finder import Song, choose_release
from encore_server.textnorm import TEXTNORM_REVISION, VERSION_WORDS, title_key
from tests.catalogue_fakes import RECORDED, recorded, recorded_search
from tests.test_album_finder import (
    ALBUM,
    BEST_OF,
    COMFORTABLY_NUMB,
    CREATURE,
    SINGLE,
    WALL,
    albums,
    best_of_answer,
    creature_hit,
    derive,
    hits,
    single_hit,
)

# ------------------------------------------------------------------------------------------------------------------ step 0: the measurement, from the recordings

LANDMVRKS_LIST = "artist_albums_9985838"
SINGLE_TRACKS, ALBUM_TRACKS = f"album_{SINGLE}_tracks", f"album_{ALBUM}_tracks"


def _days(earlier: str, later: str) -> int:
    return (date.fromisoformat(later) - date.fromisoformat(earlier)).days


def measured_pairs() -> dict[str, Any]:
    """Every single in every tracked ARTIST LIST that has the same recording on an album or EP of the same artist whose song list is tracked, and the days
    between the two. Two kinds, because they are not equally strong:

    * `proven`: the single's own song list is tracked too, and the ISRC and the length of its song are the album's song's (a recording, not a title);
    * `by_title`: only the title and the dates are known (the single's song list was not recorded).

    The search is over the WHOLE of `tests/fixtures/deezer/`: its artist lists (Bob Marley's has no single at all) and every song list. The 20 searches of
    `app/test/fixtures/deezer/search.json` give types and titles but no date and no ISRC, so they cannot give a gap and are not measured."""
    listings: dict[str, dict[str, Any]] = {}
    for path in sorted(RECORDED.glob("artist_albums*.json")):
        for row in recorded(path.stem)["data"]:
            listings[str(row["id"])] = row
    song_lists: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(RECORDED.glob("album_*_tracks.json")):
        song_lists[path.stem.removeprefix("album_").removesuffix("_tracks")] = recorded(path.stem)["data"]
    full = {i: r for i, r in listings.items() if r["record_type"] in ("album", "ep") and i in song_lists}
    proven: list[tuple[str, str, int]] = []
    by_title: list[tuple[str, str, int]] = []
    for single_id, single in listings.items():
        if single["record_type"] != "single":
            continue
        for album_id, album in full.items():
            if album["release_date"] < single["release_date"]:
                continue
            gap = _days(single["release_date"], album["release_date"])
            for song in song_lists.get(single_id, []):
                if any(
                    song.get("isrc") and song["isrc"] == t.get("isrc") and song["duration"] == t["duration"]
                    for t in song_lists[album_id]
                ):
                    proven.append((single["title"], album["title"], gap))
            if single_id not in song_lists and any(
                title_key(t["title"]) == title_key(single["title"]) for t in song_lists[album_id]
            ):
                by_title.append((single["title"], album["title"], gap))
    return {
        "proven": sorted(proven),
        "by_title": sorted(by_title),
        "singles_listed": sum(1 for r in listings.values() if r["record_type"] == "single"),
    }


def test_step_zero_the_recordings_hold_one_proven_pair_and_three_by_title_all_of_one_band_and_one_album() -> None:
    """THE MEASUREMENT (no network). The tracked answers pair a single with an album that carries the same recording only for LANDMVRKS' "The Darkest Place
    I've Ever Been": Creature by ISRC and length (single 2024-01-17, album 2025-04-18: 457 days) and, by title and date only, Sulfur (127 days), A Line in the
    Dust (84) and Blood Red (64). The other releases of the band (the singles of "Lost in the Waves") have no song list recorded; Pink Floyd's and Bob
    Marley's lists hold no single. When someone records more, this fails: re-read the window (the stop-gap in `album_finder.py`) before changing the numbers."""
    found = measured_pairs()
    album = "The Darkest Place I've Ever Been"
    assert found["proven"] == [("Creature", album, 457)]
    assert found["by_title"] == [("A Line in the Dust", album, 84), ("Blood Red", album, 64), ("Sulfur", album, 127)]
    assert found["singles_listed"] == 13, (
        "every single of the band is in the list: only these four have an album's song list beside them"
    )


def test_the_window_is_not_frozen_because_one_proven_pair_of_one_band_cannot_show_where_a_window_ends() -> None:
    """Said plainly, as the ruling asks: the four gaps (64 to 457 days, about 2 to 15 months) show that a lead single can come out well before its album. They
    cannot show how far apart a single and an album can be and still be one release (no counter-example, no second artist, no label that re-dates a catalogue),
    and a wrong stamp is permanent. So the window stays UNSET, and a single that is earlier than the album is re-askable until the live dry run."""
    assert album_finder.SINGLE_BEFORE_ALBUM_WINDOW_DAYS is None
    text = Path(album_finder.__file__).read_text(encoding="utf-8")
    assert "STOP-GAP(N-34 single window)" in text, (
        "the reminder, with its price, its removal trigger and its task, stays beside the constant"
    )


# ------------------------------------------------------------------------------------------------------------------ the window


def both_releases(**single_changes: Any) -> dict[str, dict[str, Any]]:
    """The recorded single (2024-01-17) and album (2025-04-18) of Creature; [single_changes] derive the single's answer."""
    return {ALBUM: albums(ALBUM)[ALBUM], SINGLE: derive(albums(SINGLE)[SINGLE], **single_changes)}


def test_a_single_earlier_than_its_album_is_re_askable_while_the_window_is_not_frozen() -> None:
    verdict = choose_release(CREATURE, [single_hit(), creature_hit()], both_releases())
    assert (verdict.outcome, verdict.reason, verdict.remember) == ("none", "single_before_album", True)
    assert verdict.match is None, "nothing may be written from a verdict that is not matched"
    assert verdict.withheld is not None and (verdict.withheld.album_id, verdict.withheld.record_type) == (ALBUM, "album"), (
        "what WOULD have been written, for the report: the album"
    )
    assert "457" in verdict.detail and SINGLE in verdict.detail
    assert {r.album_id: r.reason for r in verdict.releases} == {SINGLE: "outranked", ALBUM: "chosen"}


@pytest.mark.parametrize(("window", "matched"), [(None, False), (0, False), (456, False), (457, True), (458, True), (4000, True)])
def test_an_album_outranks_an_earlier_single_only_inside_the_window_and_the_boundary_is_inclusive(
    window: int | None, matched: bool
) -> None:
    """The recorded pair is 457 days apart (1 year, 2 months and 1 day)."""
    verdict = choose_release(CREATURE, [single_hit(), creature_hit()], both_releases(), single_window_days=window)
    assert (verdict.outcome == "matched") is matched, (window, verdict.outcome, verdict.detail)
    if matched:
        assert verdict.match is not None and verdict.match.album_id == ALBUM and verdict.withheld is None
    else:
        assert (verdict.outcome, verdict.reason) == ("none", "single_before_album")


@pytest.mark.parametrize("single_date", ["2025-04-18", "2025-04-19", "2026-01-01"])
def test_a_single_on_the_albums_day_or_later_is_no_earlier_single_and_the_window_does_not_matter(single_date: str) -> None:
    """DERIVED: the recorded single re-dated to the album's day or after it (a re-release): the album is the earliest, as before."""
    for window in (None, 0, 30):
        verdict = choose_release(
            CREATURE, [single_hit(), creature_hit()], both_releases(releaseDate=single_date), single_window_days=window
        )
        assert verdict.outcome == "matched" and verdict.match is not None and verdict.match.album_id == ALBUM, (
            single_date,
            window,
        )


@pytest.mark.parametrize(
    ("what", "single_changes", "album_changes"),
    [
        ("the single has no date", {"releaseDate": "0000-00-00", "year": 0}, {}),
        ("the album has no date", {}, {"releaseDate": "0000-00-00", "year": 0}),
        ("a date that is not a day", {"releaseDate": "2024-02-31"}, {}),
        ("the album's date is not a day", {}, {"releaseDate": "2025-02-30"}),
    ],
)
def test_a_gap_that_cannot_be_measured_is_never_inside_the_window(
    what: str, single_changes: dict[str, Any], album_changes: dict[str, Any]
) -> None:
    """The order of the two cannot be told, and the album carries no proof: re-askable, even with a window as wide as it can be."""
    pair = {ALBUM: derive(albums(ALBUM)[ALBUM], **album_changes), SINGLE: derive(albums(SINGLE)[SINGLE], **single_changes)}
    verdict = choose_release(CREATURE, [single_hit(), creature_hit()], pair, single_window_days=100_000)
    assert (verdict.outcome, verdict.reason) == ("none", "single_before_album"), what


def test_a_song_with_only_a_single_among_the_hits_is_not_stamped_whatever_the_window() -> None:
    """CHANGED by the advisor's ruling after the live dry run (`test_album_single_only.py`): decision 3 of the design (a single is a release of one song) is superseded for slice
    2: a stamp is permanent and a later round asks only none and held, so a single is never stamped: `none`/`single_only`, re-askable."""
    for window in (None, 0):
        verdict = choose_release(CREATURE, [single_hit()], albums(SINGLE), single_window_days=window)
        assert (verdict.outcome, verdict.reason, verdict.match) == ("none", "single_only", None)


def test_the_recorded_searches_of_requiem_and_creature_list_only_the_album_so_both_match_whatever_the_window() -> None:
    """The window fires only when an earlier single AND an album are both among the same-recording hits. The two searches recorded in step 0 returned the album's
    row alone (the single's row is not among the eight), so the recorded songs match with the window unset."""
    for title, length in (("Creature", 225_000), ("Requiem", 240_000)):
        found = recorded_search(f"LANDMVRKS {title}")["data"]
        assert {row["album"]["id"] for row in found} == {int(ALBUM)}
        verdict = choose_release(Song("LANDMVRKS", title, length), found, albums(ALBUM))
        assert (verdict.outcome, verdict.reason) == ("matched", "matched"), title
        assert verdict.match is not None and verdict.match.album_id == ALBUM


def test_the_window_looks_at_every_earlier_single_not_only_the_nearest() -> None:
    """DERIVED: a second recorded-shaped single, 100 days before the album, beside the recorded one (457 days). The nearer one is inside a 200-day window; the
    other is not, and one outside is enough."""
    near = derive(albums(SINGLE)[SINGLE], releaseDate="2025-01-08")
    near["album"]["id"] = "999"
    near["tracks"] = copy.deepcopy(albums(SINGLE)[SINGLE]["tracks"])
    near_hit = single_hit()
    near_hit["album"] = {"id": 999, "title": "Creature"}
    both = {ALBUM: albums(ALBUM)[ALBUM], SINGLE: albums(SINGLE)[SINGLE], "999": near}
    verdict = choose_release(CREATURE, [single_hit(), near_hit, creature_hit()], both, single_window_days=200)
    assert (verdict.outcome, verdict.reason) == ("none", "single_before_album")
    only_near = choose_release(CREATURE, [near_hit, creature_hit()], {ALBUM: both[ALBUM], "999": near}, single_window_days=200)
    assert only_near.outcome == "matched" and only_near.match is not None and only_near.match.album_id == ALBUM


def test_an_original_single_no_longer_loses_to_a_best_of_it_is_re_askable() -> None:
    """The slice-1 limit, closed by the ruling: a song whose ORIGINAL release is a single (The Wall typed `single`, 1979) used to get the best-of (2011) as its
    album. The gap is 32 years and the best-of is a best-of: the song is re-askable, and `withheld` says what the old rule would have written."""
    both = {WALL: derive(albums(WALL)[WALL], recordType="single"), BEST_OF: best_of_answer()}
    verdict = choose_release(COMFORTABLY_NUMB, hits("pink floyd comfortably numb"), both)
    assert (verdict.outcome, verdict.reason) == ("none", "single_before_album")
    assert verdict.withheld is not None and verdict.withheld.album_id == BEST_OF
    wide = choose_release(COMFORTABLY_NUMB, hits("pink floyd comfortably numb"), both, single_window_days=366)
    assert (wide.outcome, wide.reason) == ("none", "single_before_album"), (
        "32 years is outside any window a lead single could need"
    )


# ------------------------------------------------------------------------------------------------------------------ the best-of


def only_best_of(title: str | None = None, **album: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """DERIVED: the recorded "Comfortably Numb" search WITHOUT The Wall's hit, and the best-of's answer (see `best_of_answer`), optionally with another title."""
    found = [row for row in hits("pink floyd comfortably numb") if row["id"] != 116914122]
    answer = best_of_answer()
    if title is not None:
        answer["album"]["title"] = title
        answer["tracks"][0]["album"]["title"] = title
    answer["album"].update(album)
    return found, {BEST_OF: answer}


def test_the_recorded_best_of_is_the_only_candidate_and_its_title_says_best_of_so_it_is_re_askable() -> None:
    """The slice-1 pin said `matched` ("a LIMIT, pinned on purpose"). The ruling accepts a same-artist best-of that is the only candidate; its title markers MAY
    downgrade such a match to re-askable, and this is the case: the marker is evidence that this is the compilation and not the song's album, the stamp is
    permanent, and a better rule (the discography, a measured window) asks again. `withheld` is what would have been written."""
    found, answers = only_best_of()
    verdict = choose_release(COMFORTABLY_NUMB, found, answers)
    assert (verdict.outcome, verdict.reason, verdict.remember, verdict.match) == ("none", "compilation_title", True, None)
    assert verdict.withheld is not None and verdict.withheld.album == "A Foot in the Door: The Best of Pink Floyd"
    assert verdict.withheld.deezer_id == "116914348" and verdict.withheld.track_no == 7


@pytest.mark.parametrize("title", ["Gold", "Legend", "Legend - Remastered", "Exodus"])
def test_a_same_artist_best_of_that_says_nothing_of_it_in_its_title_is_accepted_when_it_is_the_only_candidate(title: str) -> None:
    """The title is never the rule: a best-of called "Gold" passes, because only the album's real title can be read and a guess would be worse than the
    catalogue's own word (the ruling, case 1)."""
    found, answers = only_best_of(title)
    verdict = choose_release(COMFORTABLY_NUMB, found, answers)
    assert (verdict.outcome, verdict.reason) == ("matched", "matched"), title
    assert verdict.match is not None and verdict.match.album == title and verdict.withheld is None


@pytest.mark.parametrize(
    "title",
    [
        "Greatest Hits",
        "GREATEST HITS Vol. 2",
        "The Best Of Bob Marley",
        "Best of the Best",
        "The Very Best of Fleetwood Mac",
        "The Essential Collection",
        "Essentials",
        "Anthology 1",
        "The Definitive Collection",
        "Ultimate Hits",
        "Number One Hits",
        "Collection",
        "Collections",
        "Hits",
        "Grandes Éxitos: Greatest Hits",
        "Best-Of",
        "The Best Of: 1990-2000",
        "With Arms Wide Open: A Retrospective",
        "Retrospective",
    ],
)
def test_a_title_that_says_it_is_a_compilation_downgrades_a_match_to_re_askable(title: str) -> None:
    found, answers = only_best_of(title)
    verdict = choose_release(COMFORTABLY_NUMB, found, answers)
    assert (verdict.outcome, verdict.reason, verdict.match) == ("none", "compilation_title", None), title
    assert verdict.withheld is not None and verdict.withheld.album == title


@pytest.mark.parametrize(
    "title",
    [
        "Best Friend",
        "The Best Is Yet to Come",
        "Bestiary",
        "Restless",
        "Hitchcock",
        "Collective Soul",
        "Collected",
        "Ultimatum",
        "Essence",
        "Anthem of Sorrow",
        "Definitely Maybe",
        "Hit Me Baby",
        "Recollections",
        "Penultimate",
        "Nonessential",
        "Hitsville",
        "Gold",
        "Legend",
        "The Wall",
        "Thriller",
    ],
)
def test_a_real_album_whose_title_merely_contains_a_marker_in_a_longer_word_is_not_downgraded(title: str) -> None:
    """A word counts only as a whole word: the marker list is a second layer and must cost songs as little as it can."""
    found, answers = only_best_of(title)
    verdict = choose_release(COMFORTABLY_NUMB, found, answers)
    assert (verdict.outcome, verdict.reason) == ("matched", "matched"), title


def test_a_marker_on_a_release_that_was_not_chosen_changes_nothing() -> None:
    """The recorded case of slice 1, kept: The Wall wins over the best-of by its date, and the best-of's title is not looked at."""
    both = {WALL: albums(WALL)[WALL], BEST_OF: best_of_answer()}
    verdict = choose_release(COMFORTABLY_NUMB, hits("pink floyd comfortably numb"), both)
    assert (verdict.outcome, verdict.reason) == ("matched", "matched")
    assert verdict.match is not None and verdict.match.album_id == WALL


def test_a_marker_on_the_release_that_is_chosen_among_several_downgrades_it_too() -> None:
    """DERIVED: The Wall and the best-of with their dates swapped, so the best-of is the earliest: nothing but the catalogue's date says it is the song's
    album, and the title says it is not (the date alone is not evidence enough for a permanent stamp)."""
    both = {
        WALL: derive(albums(WALL)[WALL], releaseDate="2011-11-08", year=2011),
        BEST_OF: derive(best_of_answer(), releaseDate="1979-11-30", year=1979),
    }
    verdict = choose_release(COMFORTABLY_NUMB, hits("pink floyd comfortably numb"), both)
    assert (verdict.outcome, verdict.reason) == ("none", "compilation_title")
    assert verdict.withheld is not None and verdict.withheld.album_id == BEST_OF


def test_the_markers_are_documented_and_are_a_second_layer_never_the_whole_rule() -> None:
    assert isinstance(album_finder.COMPILATION_MARKERS, tuple) and len(album_finder.COMPILATION_MARKERS) >= 8
    source = Path(album_finder.__file__).read_text(encoding="utf-8")
    assert "STOP-GAP(N-34 compilation markers)" in source, (
        "English markers only, a guess on a title: the price and the removal trigger are written beside them"
    )


# ------------------------------------------------------------------------------------------------------------------ a non-Latin song with a Latin hit


def latin_hits() -> list[dict[str, Any]]:
    """The recorded search `fairuz kifak inta` (Latin spelling: "Fairuz", "Kifak Inta") for an Arabic song."""
    return hits("fairuz kifak inta")


ARABIC_FAIRUZ = Song("فيروز", "كيفك إنت", 209_000)


def test_a_non_latin_song_whose_only_hits_are_spelled_in_latin_letters_is_a_remembered_none_told_apart() -> None:
    """Era 1 compares names in the alphabet they are written in and transliterates nothing, so the catalogue's Latin spelling of an Arabic song can never be
    proved to be the song: asked, answered, a remembered `none`, with its own reason so that the dry run and the database count these songs apart."""
    verdict = choose_release(ARABIC_FAIRUZ, latin_hits(), {})
    assert (verdict.outcome, verdict.reason, verdict.remember, verdict.match, verdict.withheld) == (
        "none",
        "latin_spelling_only",
        True,
        None,
        None,
    )
    assert len(verdict.hits) == len(latin_hits()) and all(h.reason == "artist" for h in verdict.hits)


@pytest.mark.parametrize(
    ("what", "song", "found"),
    [
        ("a Latin song with Latin hits that are not it", Song("Fairuz", "Habibi", 209_000), latin_hits()),
        ("an Arabic song and no hits", ARABIC_FAIRUZ, []),
    ],
)
def test_the_latin_spelling_reason_needs_a_non_latin_song_and_hits(what: str, song: Song, found: list[dict[str, Any]]) -> None:
    verdict = choose_release(song, found, {})
    assert (verdict.outcome, verdict.reason) == ("none", "no_same_recording"), what


def test_a_song_with_one_non_latin_name_and_one_latin_name_is_a_spelling_case_too() -> None:
    """The mixed-script title of the design's rows ("Habibi" plus Arabic words) against the catalogue's Latin hits."""
    verdict = choose_release(Song("Fairuz", "Habibi يا نور", 209_000), latin_hits(), {})
    assert (verdict.outcome, verdict.reason) == ("none", "latin_spelling_only")


def test_an_arabic_song_with_a_hit_that_is_written_in_arabic_is_not_a_latin_spelling_case() -> None:
    """DERIVED (`arabic_hit` of `test_album_finder.py`): one hit in Arabic with another title beside the Latin ones: the catalogue DOES spell some names in Arabic,
    and this song's miss is a plain miss, not a spelling case."""
    from tests.test_album_finder import arabic_hit

    found = [arabic_hit("حبيبي"), *latin_hits()]
    verdict = choose_release(ARABIC_FAIRUZ, found, {})
    assert (verdict.outcome, verdict.reason) == ("none", "no_same_recording")


def test_an_arabic_song_whose_hit_is_spelled_in_arabic_still_matches_by_the_equality_of_the_keys() -> None:
    """The row is unchanged by this slice: only the song named in Arabic is the Arabic hit (`arabic_hit` is the recorded Fairuz row with its names replaced)."""
    from tests.test_album_finder import arabic_hit

    hit = arabic_hit("كيفك إنت")
    verdict = choose_release(ARABIC_FAIRUZ, [hit], albums_for_arabic_hit(hit))
    assert verdict.outcome == "matched", (verdict.outcome, verdict.reason)


def albums_for_arabic_hit(hit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """DERIVED: an album answer for the recorded Fairuz hit's album ("Fairuz Chillout Classics"): the recorded Creature album answer re-named and re-credited,
    with a song list that holds the hit (the recording of this album was not made)."""
    answer = copy.deepcopy(albums(ALBUM)[ALBUM])
    album_id = str(hit["album"]["id"])
    answer["album"].update(id=album_id, title=hit["album"]["title"], artists=[{"id": "1", "name": hit["artist"]["name"]}])
    row = answer["tracks"][1]
    row.update(id=str(hit["id"]), title=hit["title"], album={"id": album_id, "title": hit["album"]["title"]})
    answer["tracks"] = [row]
    return {album_id: answer}


# ------------------------------------------------------------------------------------------------------------------ the revision


def test_the_data_a_better_rule_changes_is_pinned_with_the_revision_that_asks_the_songs_again() -> None:
    """`identity_rev` makes a `none` or `held` song asked again when the rule gets better; it only works if the revision rises WITH the rule. What is pinned here, hashed beside the
    revision it belongs to: the tolerance, the single window, the compilation markers, the types that win, the version words of the release-title rule and the fold's own revision (`textnorm.TEXTNORM_REVISION`: a change of the
    fold changes which keys are equal, and that decided most `none` answers). Change one (freeze the window, widen the tolerance, add a marker) and this fails until `IDENTITY_REVISION`
    is raised and the new line is added, so the songs are asked again by the very change that could give them another answer. **What it cannot see** is a change of the rule's CODE (a new
    step, a new reason): that raises the revision by hand (said on `IDENTITY_REVISION`), and the 7 days' wait is the net under a forgotten bump."""
    state = json.dumps(
        {
            "tolerance_ms": album_finder.TOLERANCE_MS,
            "window_days": album_finder.SINGLE_BEFORE_ALBUM_WINDOW_DAYS,
            "markers": list(album_finder.COMPILATION_MARKERS),
            "full": sorted(album_finder._FULL_RELEASE),
            "textnorm_revision": TEXTNORM_REVISION,
            "version_words": list(VERSION_WORDS),
            "version_forms": album_finder._VERSION_FORMS,
            "extra_marks": album_finder._EXTRA_MARKS,
        },
        sort_keys=True,
    )
    fingerprint = hashlib.sha256(state.encode()).hexdigest()[:16]
    known = {
        1: "90e3395504ceed7b",
        2: "fff965fa74e495fb",
        3: "8d639d3ea5098204",
        4: "8d639d3ea5098204",  # the single rule is code, not data: the pinned data is the same as for 3
    }  # 1 = the state of PR 125 as first pushed (never stamped anywhere)
    assert album_finder.IDENTITY_REVISION in known, "a new revision needs its line here"
    assert known[album_finder.IDENTITY_REVISION] == fingerprint, (
        f"the rule changed without a new IDENTITY_REVISION: raise it and add `{album_finder.IDENTITY_REVISION + 1}: {fingerprint!r}` (state: {state})"
    )
