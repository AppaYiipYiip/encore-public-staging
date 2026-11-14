"""P2-12 slice 1 moved the cover finder and the artist finder onto the gate. These tests run the REAL look-ups (`deezer_lookup`, `deezer_artist_picture`)
through the installed gate, with the catalogue's answers served from the recordings, to show that what the two finders promised before is unchanged:

* **B-124**: a catalogue that could not be asked (refused, throttled, off, resting) is not "no picture exists": nothing is stored, the pass stops, the
  next pass asks again;
* **B-127**: the artist pass still waits for a scan that is running, and then finds its picture through the gate.

The old tests of both finders (`test_cover_finder.py`, `test_artist_finder.py`) are untouched and still pass: they ask through a client of their own.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from encore_server import deezer
from encore_server.artist_finder import ArtistFinder, deezer_artist_picture
from encore_server.cover_finder import CoverFinder, deezer_lookup
from encore_server.deezer import CatalogueOff, DeezerClient, Gate, LookupUnavailable
from tests.catalogue_fakes import QUOTA, RecordedDeezer, recorded
from tests.test_artist_finder import Clock, Music, kept
from tests.test_artist_finder import database as artist_database
from tests.test_cover_finder import cover_of, database, liked

# The conftest puts "nobody" in the place of these two for every other test; these tests are about the real ones, so they hand them to the finders.
REAL_COVER_LOOKUP = deezer_lookup
REAL_ARTIST_LOOKUP = deezer_artist_picture


def install(upstream: RecordedDeezer, **gate: object) -> Gate:
    the_gate = Gate(**{"rate": 1000, "burst": 1000, "background_gap_s": 0.0, **gate})  # type: ignore[arg-type]
    deezer.install(DeezerClient(the_gate, httpx.Client(transport=upstream.transport())))
    return the_gate


# ------------------------------------------------------------------------------------------------------------------ the cover finder


def test_the_cover_finder_finds_the_cover_through_the_gate_from_a_recorded_answer(tmp_path: Path) -> None:
    upstream = RecordedDeezer()
    install(upstream)
    db = database(tmp_path)
    ref = liked(db, "Blinding Lights", artist="The Weeknd", album="After Hours")

    report = CoverFinder(db, REAL_COVER_LOOKUP, sleep=lambda _: None).run_once()

    assert (report.looked, report.found) == (1, 1)
    assert (cover_of(db, ref) or "").startswith("https://cdn-images.dzcdn.net/images/cover/")
    assert upstream.paths() == ["/search"]


@pytest.mark.parametrize("refusal", [(429, {}), (503, {}), (200, QUOTA)], ids=["429", "503", "quota-in-a-200"])
def test_b124_a_refusal_at_the_gate_is_not_no_picture_and_the_next_pass_asks_again(
    tmp_path: Path, refusal: tuple[int, object]
) -> None:
    upstream = RecordedDeezer()
    gate = install(upstream)
    db = database(tmp_path)
    ids = [
        liked(db, "Blinding Lights", artist="The Weeknd", album="After Hours"),
        liked(db, "Other", artist="Somebody", album="Else"),
    ]
    upstream.overrides["/search"] = refusal  # type: ignore[assignment]

    report = CoverFinder(db, REAL_COVER_LOOKUP, sleep=lambda _: None).run_once()

    assert report.complete is False and report.found == 0
    assert upstream.count("/search") == 1, "the pass stopped at the first refusal"
    assert gate.state()["state"] == "resting", "and nobody else asks the catalogue meanwhile"
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref WHERE cover_tried_at IS NOT NULL").fetchone()[0] == 0, (
            "an outage is not a miss"
        )
    assert [cover_of(db, i) for i in ids] == [None, None]

    # The rest is over and the catalogue answers: the same songs are asked about at once, not in a week.
    del upstream.overrides["/search"]
    install(upstream)
    again = CoverFinder(db, REAL_COVER_LOOKUP, sleep=lambda _: None).run_once()
    assert again.looked == 2 and again.found == 1


def test_b124_a_resting_gate_asks_nothing_and_remembers_nothing(tmp_path: Path) -> None:
    upstream = RecordedDeezer()
    gate = install(upstream)
    gate.done(gate.acquire("interactive"), "refused")
    db = database(tmp_path)
    liked(db, "Blinding Lights", artist="The Weeknd", album="After Hours")

    report = CoverFinder(db, REAL_COVER_LOOKUP, sleep=lambda _: None).run_once()

    assert upstream.requests == [] and report.complete is False and report.looked == 0
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref WHERE cover_tried_at IS NOT NULL").fetchone()[0] == 0


def test_a_server_whose_catalogue_is_switched_off_opens_no_connection_and_remembers_no_miss(tmp_path: Path) -> None:
    upstream = RecordedDeezer()
    install(upstream, enabled=False)
    db = database(tmp_path)
    liked(db, "Blinding Lights", artist="The Weeknd", album="After Hours")

    report = CoverFinder(db, REAL_COVER_LOOKUP, sleep=lambda _: None).run_once()

    assert upstream.requests == [] and report.found == 0 and report.complete is False
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM song_ref WHERE cover_tried_at IS NOT NULL").fetchone()[0] == 0


def test_a_look_up_with_no_catalogue_set_up_says_it_could_not_ask_and_opens_nothing() -> None:
    deezer.install(None)
    with pytest.raises(CatalogueOff):
        deezer.search_tracks("The Weeknd", "Blinding Lights")
    assert issubclass(CatalogueOff, LookupUnavailable)


# ------------------------------------------------------------------------------------------------------------------ the artist finder


def a_hit_for(title: str) -> dict[str, object]:
    """A song by the recorded artist (Bob Marley & The Wailers, with the picture Deezer really gives him)."""
    return {"data": [{"id": 1, "title": title, "artist": recorded("artist")}]}


def test_b127_the_artist_pass_still_waits_for_a_running_scan_and_then_finds_the_picture_through_the_gate(tmp_path: Path) -> None:
    upstream = RecordedDeezer()
    upstream.overrides["/search"] = (200, a_hit_for("Could You Be Loved"))
    install(upstream)
    db, music, clock = artist_database(tmp_path), tmp_path / "music", Clock()
    kept(db, music, "Bob Marley", "Could You Be Loved")

    class ScanThatEnds(Music):
        def __init__(self) -> None:
            super().__init__([("ar-1", "Bob Marley")], scanning=True)
            self.polls = 0

        def scanning(self) -> bool | None:
            self.polls += 1
            return self.polls <= 3

    slept: list[float] = []
    the = ArtistFinder(
        db,
        ScanThatEnds(),
        REAL_ARTIST_LOOKUP,
        music_dir=music,
        fetch=lambda url: b"\xff\xd8\xff\xe0" + b"jpeg-bytes",
        sleep=slept.append,
        clock=clock,
        scan_wait_s=60.0,
        scan_poll_s=2.0,
    )

    report = the.run_once()

    assert (report.looked, report.found) == (1, 1)
    assert slept.count(2.0) == 3, "it looked again at every poll while the scan ran"
    assert (music / "Encore" / "Bob Marley" / "artist.jpg").exists()
    assert upstream.paths() == ["/search"], "and its question went through the gate, once"


def test_b124_an_artist_the_catalogue_could_not_be_asked_about_is_not_remembered_as_having_no_picture(tmp_path: Path) -> None:
    upstream = RecordedDeezer()
    upstream.overrides["/search"] = (429, {})
    gate = install(upstream)
    db, music, clock = artist_database(tmp_path), tmp_path / "music", Clock()
    kept(db, music, "Bob Marley", "Could You Be Loved")
    the = ArtistFinder(
        db, Music([("ar-1", "Bob Marley")]), REAL_ARTIST_LOOKUP, music_dir=music, sleep=lambda _: None, clock=clock
    )

    report = the.run_once()

    assert report.complete is False and report.found == 0 and upstream.count("/search") == 1
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM artist_picture").fetchone()[0] == 0, (
            "no row: the artist is asked about again next pass"
        )
    assert gate.state()["state"] == "resting"
