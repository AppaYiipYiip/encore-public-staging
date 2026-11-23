"""N-34 slice 2, the dry run's half: the report counts what slice 2 adds APART so that the lead can read it before anything is stored, and the dry run asks with the very
function the album pass asks with (`album_finder.decide`), so what the report counts is what the pass will write.

Added to `album_dryrun`: the songs whose only catalogue hits are spelled in Latin letters (a non-Latin song: counted apart, 17 Nov 2026), the songs the rule WITHHELD
(`single_before_album`, `compilation_title`) with what the old rule would have written, the gaps between an earlier single and the album that carries the same recording
(what the window is frozen from) and, on the first lines, the stop-gap of the window.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from encore_server import album_dryrun, album_finder
from encore_server.album_dryrun import Entry, Report, Row, run
from encore_server.album_finder import Song, choose_release
from tests.test_album_finder import ALBUM, SINGLE, albums, creature_hit, derive, single_hit
from tests.test_album_pass import make_ref, pdb  # noqa: F401 - `pdb` is a fixture
from tests.test_album_withheld import ARABIC_FAIRUZ, latin_hits


def row(ref: str, song: Song, hits: list[dict[str, Any]], known: dict[str, Any], window: int | None = None) -> Row:
    return Row(Entry(ref, song, "file"), choose_release(song, hits, known, single_window_days=window))


CREATURE = Song("LANDMVRKS", "Creature", 225_000)


def lines(report: Report) -> list[str]:
    return report.render().splitlines()


def test_the_first_lines_say_that_the_window_is_not_frozen_and_what_it_is_frozen_from() -> None:
    first = lines(Report([], 3000))
    assert first[0].startswith("STOP-GAP: the tolerance is 3000 ms")
    assert first[1].startswith("STOP-GAP: the single-before-album window is NOT FROZEN"), first[1]
    assert "single-before-album gaps" in first[1]
    frozen = lines(Report([], 3000, single_window_days=500))
    assert "is 500 days" in frozen[1] and "NOT FROZEN" not in frozen[1]


def test_the_songs_the_catalogue_spells_in_latin_letters_are_counted_apart_and_shown() -> None:
    rows = [
        row("sr_a", ARABIC_FAIRUZ, latin_hits(), {}),
        row("sr_b", Song("Nobody", "Nothing", 200_000), [], {}),
        row("sr_c", Song("Fairuz", "Habibi", 209_000), latin_hits(), {}),
    ]
    text = "\n".join(lines(Report(rows, 3000)))
    assert "non-Latin songs with only Latin-spelled hits: 1 of 3" in text
    assert "latin_spelling_only" in text and "no_same_recording" in text
    assert "sr_a" in text.split("non-Latin songs with only Latin-spelled hits")[1], "the example names the song"
    causes = text.split("== songs the catalogue could not place, by cause")[1].split("==")[0]
    counts = {
        line.split()[1]: int(line.split()[0]) for line in causes.splitlines() if line.strip().startswith(tuple("0123456789"))
    }
    assert counts == {"no_same_recording": 2, "latin_spelling_only": 1}, (
        "the Latin song with Latin hits is a plain miss, not a spelling case"
    )


def test_the_withheld_songs_show_what_the_old_rule_would_have_written() -> None:
    both = {ALBUM: albums(ALBUM)[ALBUM], SINGLE: albums(SINGLE)[SINGLE]}
    rows = [row("sr_w", CREATURE, [single_hit(), creature_hit()], both)]
    assert rows[0].verdict.reason == "single_before_album"
    text = "\n".join(lines(Report(rows, 3000)))
    assert "withheld (what the old rule would have written; NOT written): 1" in text
    withheld = text.split("withheld (what the old rule would have written; NOT written): 1")[1].split("\n==")[0]
    assert "sr_w" in withheld and "single_before_album" in withheld and "The Darkest Place" in withheld and "457" in withheld


def test_the_gaps_between_an_earlier_single_and_its_album_are_what_the_window_is_frozen_from() -> None:
    both = {ALBUM: albums(ALBUM)[ALBUM], SINGLE: albums(SINGLE)[SINGLE]}
    withheld = row("sr_1", CREATURE, [single_hit(), creature_hit()], both)
    matched = row("sr_2", CREATURE, [single_hit(), creature_hit()], both, window=500)
    alone = row("sr_3", CREATURE, [creature_hit()], {ALBUM: albums(ALBUM)[ALBUM]})
    report = Report([withheld, matched, alone], 3000)
    assert [(r.entry.ref_id, gap) for r, gap in report.single_gaps()] == [("sr_1", 457), ("sr_2", 457)], (
        "one per earlier single; a song with no single has none"
    )
    text = "\n".join(lines(report))
    section = text.split("== single-before-album gaps")[1].split("\n==")[0]
    assert "2 pairs, 2 songs; min 457, median 457, max 457 days" in section
    assert "  365 ..   730 days     2" in section, section


def test_a_single_dated_after_its_album_is_no_gap_before_it() -> None:
    """DERIVED: the recorded single re-dated to a year AFTER the album (a re-release): it is not an earlier single, and counting it would put a negative gap in the histogram."""
    later = derive(albums(SINGLE)[SINGLE], releaseDate="2026-06-01")
    report = Report([row("sr_4", CREATURE, [single_hit(), creature_hit()], {ALBUM: albums(ALBUM)[ALBUM], SINGLE: later})], 3000)
    assert report.single_gaps() == []


def test_a_report_with_no_pair_says_so() -> None:
    text = "\n".join(lines(Report([row("sr_3", CREATURE, [creature_hit()], {ALBUM: albums(ALBUM)[ALBUM]})], 3000)))
    assert "(no song had both a single and an album among its same-recording hits)" in text


def test_the_dry_run_asks_with_the_function_the_album_pass_asks_with(pdb, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    """One function (`album_finder.decide`): a dry run that decided in its own way would count something the pass does not write."""
    make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    called: list[Song] = []
    real = album_finder.decide

    def spy(song: Song, *args: Any, **kwargs: Any) -> Any:
        called.append(song)
        return real(song, *args, **kwargs)

    monkeypatch.setattr(album_finder, "decide", spy)
    conn = sqlite3.connect(f"{pdb.path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        items = album_dryrun.entries(conn)
        rows = run(conn, items, lambda artist, title: [], lambda ident: {}, single_window_days=123)
    finally:
        conn.close()
    assert [song.title for song in called] == ["Creature"] and len(rows) == 1


def test_the_window_given_to_the_run_reaches_the_matcher(pdb, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    seen: list[Any] = []
    real = album_finder.choose_release

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs.get("single_window_days", "missing"))
        return real(*args, **kwargs)

    monkeypatch.setattr(album_finder, "choose_release", spy)
    conn = sqlite3.connect(f"{pdb.path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        run(
            conn,
            album_dryrun.entries(conn),
            lambda artist, title: [creature_hit()],
            lambda ident: {ALBUM: albums(ALBUM)[ALBUM]}.get(ident, {}),
            single_window_days=321,
        )
    finally:
        conn.close()
    assert seen and set(seen) == {321}
