"""N-34 slice 2: the album pass (`encore_server/album_pass.py`), one more errand of the hourly library link that runs BEFORE the cover finder. It asks the catalogue
about the songs the library holds (through the merged matcher, `album_finder`), stamps a song's album ONLY when its album field is empty or the placeholder and never
rewrites one, remembers the three answers that are facts (`matched`, `none`, `held`) and never the ones that are not ("could not ask").

Every catalogue answer here is RECORDED (`tests/fixtures/deezer/`, the searches of `app/test/fixtures/deezer/`, through `test_album_finder.py`'s helpers); the catalogue is
a fake that serves them and counts what is asked: a test never makes a request.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from encore_server import album_finder, album_pass, deezer, library, refs
from encore_server.album_finder import Song
from encore_server.album_pass import AlbumFinder, AlbumReport
from encore_server.api import create_app
from encore_server.catalogue import Cache
from encore_server.catalogue import Catalogue as RealCatalogue
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.deezer import DeezerClient, Gate, LookupUnavailable, NotInCatalogue
from encore_server.navidrome import NavidromeClient
from encore_server.navidrome_admin import NavidromeAdmin
from tests.catalogue_fakes import RecordedDeezer, recorded_search
from tests.test_album_finder import (
    ALBUM,
    BEST_OF,
    SINGLE,
    WALL,
    albums,
    arabic_hit,
    best_of_answer,
    creature_hit,
    hits,
    single_hit,
)
from tests.test_album_withheld import albums_for_arabic_hit, latin_hits

DAY_MS = 24 * 3600 * 1000
NOW = 1_800_000_000_000


class Catalogue:
    """The catalogue as the pass asks it: `search(artist, title)` and `album(id)` over recorded answers, counting every question. `down` makes the search fail the
    way a gate that rests or a timeout does (`LookupUnavailable`); `albums_down` does it for the album answers only."""

    def __init__(
        self,
        searches: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
        known_albums: dict[str, dict[str, Any]] | None = None,
        *,
        down: bool = False,
        albums_down: bool = False,
        on_search: Callable[[], None] | None = None,
    ) -> None:
        self.searches = searches or {}
        self.known_albums = known_albums or {}
        self.down, self.albums_down = down, albums_down
        self.on_search = on_search
        self.searched: list[tuple[str, str]] = []
        self.albumed: list[str] = []

    def search(self, artist: str, title: str) -> list[dict[str, Any]]:
        self.searched.append((artist, title))
        if self.on_search is not None:
            self.on_search()
        if self.down:
            raise LookupUnavailable("the catalogue rests this server")
        return copy.deepcopy(self.searches.get((artist, title), []))

    def album(self, ident: str) -> dict[str, Any]:
        self.albumed.append(ident)
        if self.albums_down:
            raise LookupUnavailable("the catalogue rests this server")
        if ident not in self.known_albums:
            raise NotInCatalogue(ident)
        return copy.deepcopy(self.known_albums[ident])


def landmvrks() -> Catalogue:
    """Requiem and Creature as the two recorded searches of step 0 answered them: the album's row alone (the single's row was not among the eight)."""
    return Catalogue(
        {
            ("LANDMVRKS", "Requiem"): recorded_search("LANDMVRKS Requiem")["data"],
            ("LANDMVRKS", "Creature"): recorded_search("LANDMVRKS Creature")["data"],
        },
        albums(ALBUM, SINGLE),
    )


@pytest.fixture
def pdb(db: Database) -> Database:
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO person (id, navidrome_user, display_name, role, created_at) VALUES ('pn_1','marwa','marwa','owner',0)"
        )
    return db


def make_ref(
    db: Database,
    title: str,
    artist: str,
    length: int | None = 240_000,
    *,
    album: str | None = "[Unknown Album]",
    kept: str | None = "Encore/x/Singles/a.opus",
    like: bool = False,
    source: str = "youtube",
    **columns: Any,
) -> str:
    """A ref made the way the server makes one, then the columns the test names written directly (the placeholder literal is what 595 refs of the owner's
    server hold; a ref made through `refs.resolve` would not keep it)."""
    with db.tx() as conn:
        ref = str(refs.resolve(conn, {"title": title, "artists": [artist], "durationMs": length})["id"])
        conn.execute("UPDATE song_ref SET album = ? WHERE id = ?", (album, ref))
        for column, value in columns.items():
            conn.execute(f"UPDATE song_ref SET {column} = ? WHERE id = ?", (value, ref))  # noqa: S608 - the test's own column names
        if kept is not None:
            conn.execute(
                "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, source, preferred, added_at) VALUES (?, ?, ?, ?, 'opus', ?, 1, 1)",
                (f"sf_{ref}", ref, f"nd_{ref}", kept, source),
            )
        if like:
            library.set_item(conn, "pn_1", "like", ref)
    return ref


def row_of(db: Database, ref: str) -> dict[str, Any]:
    with db.read() as conn:
        return dict(conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref,)).fetchone())


def cursor(db: Database) -> int:
    with db.read() as conn:
        return library.latest_cursor(conn, "pn_1")


def files_logged(db: Database, ref: str) -> int:
    with db.read() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM file_log WHERE ref = ?", (ref,)).fetchone()[0])


def finder(db: Database, catalogue: Catalogue, *, now: int = NOW, **options: Any) -> AlbumFinder:
    return AlbumFinder(db, search=catalogue.search, album=catalogue.album, now=lambda: now, **options)


IDENTITY = ("identity_tried_at", "identity_rev", "identity_outcome", "identity_reason")


# ------------------------------------------------------------------------------------------------------------------ a match is stamped, fill only


def test_a_song_the_catalogue_knows_gets_its_album_and_everything_the_release_says_and_the_phones_are_told(pdb: Database) -> None:
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, like=True)
    before = row_of(pdb, ref)
    seen = cursor(pdb)
    report = finder(pdb, landmvrks()).run_once()

    assert (report.asked, report.matched, report.none, report.held, report.complete) == (1, 1, 0, 0, True)
    after = row_of(pdb, ref)
    assert (after["album"], after["track_no"], after["disc_no"], after["year"], after["deezer_id"], after["isrc"]) == (
        "The Darkest Place I've Ever Been",
        2,
        1,
        2025,
        "3116792061",
        "DEYO62300153",
    )
    assert after["cover_url"] and after["cover_url"].startswith("https://")
    assert (after["identity_outcome"], after["identity_reason"], after["identity_rev"], after["identity_tried_at"]) == (
        "matched",
        "matched",
        album_finder.IDENTITY_REVISION,
        NOW,
    )
    for column in (
        "id",
        "title",
        "artists",
        "norm_key",
        "album_artist",
        "duration_ms",
        "ytm_video_id",
        "created_at",
        "artist_basis",
        "uploader",
    ):
        assert after[column] == before[column], f"{column} is never written by the pass"
    assert cursor(pdb) > seen, "the person who liked the song hears that it changed"
    assert files_logged(pdb, ref) == 1, "and the feed of the server's files says its file's song changed"


def test_an_album_the_song_already_has_is_never_rewritten_because_the_song_is_not_asked(pdb: Database) -> None:
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, album="Hollow")
    catalogue = landmvrks()
    report = finder(pdb, catalogue).run_once()
    assert report.asked == 0 and catalogue.searched == []
    assert row_of(pdb, ref)["album"] == "Hollow" and row_of(pdb, ref)["identity_outcome"] is None


def test_a_song_with_no_album_at_all_is_asked_too_and_a_null_stays_null_when_nothing_is_found(pdb: Database) -> None:
    ref = make_ref(pdb, "A Song Nobody Recorded", "Nobody At All", 200_000, album=None, like=True)
    seen = cursor(pdb)
    report = finder(pdb, Catalogue()).run_once()
    assert (report.asked, report.none) == (1, 1)
    after = row_of(pdb, ref)
    assert after["album"] is None and (after["identity_outcome"], after["identity_reason"]) == ("none", "no_same_recording")
    assert cursor(pdb) == seen and files_logged(pdb, ref) == 0, "nothing the phones show changed: they are not told"


def test_the_placeholder_literal_becomes_no_album_for_a_none_and_the_phones_are_told(pdb: Database) -> None:
    ref = make_ref(pdb, "A Song Nobody Recorded", "Nobody At All", 200_000, like=True)
    seen = cursor(pdb)
    finder(pdb, Catalogue()).run_once()
    after = row_of(pdb, ref)
    assert after["album"] is None and after["identity_outcome"] == "none"
    assert cursor(pdb) > seen and files_logged(pdb, ref) == 1


def test_the_placeholder_literal_becomes_no_album_for_a_held_pair_and_nothing_else_is_written(
    pdb: Database, caplog: pytest.LogCaptureFixture
) -> None:
    """Another ref already holds the catalogue's id of Creature: the pair is HELD, the song gets none of the release's facts, and one INFO line names both refs and
    the catalogue's id (ids only: no title, no artist)."""
    holder = make_ref(
        pdb, "Creature", "LANDMVRKS", 234_000, album="The Darkest Place I've Ever Been", kept=None, deezer_id="3116792061"
    )
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    before = row_of(pdb, ref)
    with caplog.at_level(logging.INFO, logger="encore_server.album_pass"):
        report = finder(pdb, landmvrks()).run_once()
    assert (report.matched, report.held) == (0, 1)
    after = row_of(pdb, ref)
    assert after["album"] is None, "the placeholder is forgotten"
    for column in ("track_no", "disc_no", "year", "deezer_id", "isrc", "cover_url"):
        assert after[column] == before[column] is None or after[column] == before[column], column
    assert (after["identity_outcome"], after["identity_reason"]) == ("held", "deezer_id_held")
    lines = [r.getMessage() for r in caplog.records if "held pair" in r.getMessage()]
    assert len(lines) == 1 and ref in lines[0] and holder in lines[0] and "3116792061" in lines[0], lines
    assert "Creature" not in lines[0] and "LANDMVRKS" not in lines[0], "no title and no artist in the log"


def test_a_twin_on_the_same_release_is_held_and_its_log_line_names_the_twin(
    pdb: Database, caplog: pytest.LogCaptureFixture
) -> None:
    """The owner's Creature: another ref of the same song already has the real album (an import gave it): HELD, never filled, never merged here (slice 6)."""
    twin = make_ref(pdb, "Creature", "LANDMVRKS", 234_000, album="The Darkest Place I've Ever Been", kept=None)
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    with caplog.at_level(logging.INFO, logger="encore_server.album_pass"):
        finder(pdb, landmvrks()).run_once()
    assert (row_of(pdb, ref)["identity_outcome"], row_of(pdb, ref)["identity_reason"]) == ("held", "twin_held")
    assert row_of(pdb, ref)["album"] is None and row_of(pdb, ref)["deezer_id"] is None
    assert any(ref in r.getMessage() and twin in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------------------------------------------------------ what is never stored


def test_a_catalogue_that_cannot_be_asked_stores_nothing_and_stops_the_pass(pdb: Database) -> None:
    """An outage is not "the catalogue knows none" (audit B-124): nothing is stored for any song, not even the placeholder, and the pass stops at the first."""
    refs_made = [make_ref(pdb, title, "LANDMVRKS", 225_000, like=True) for title in ("Creature", "Requiem")]
    catalogue = Catalogue(down=True)
    seen = cursor(pdb)
    report = finder(pdb, catalogue).run_once()
    assert (report.asked, report.complete) == (0, False) and report.stopped
    assert len(catalogue.searched) == 1, "the pass stops at the first song that could not be asked"
    for ref in refs_made:
        after = row_of(pdb, ref)
        assert after["album"] == "[Unknown Album]" and [after[c] for c in IDENTITY] == [None] * 4
    assert cursor(pdb) == seen


def test_an_album_that_could_not_be_asked_stores_nothing_either(pdb: Database) -> None:
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    catalogue = Catalogue(
        {("LANDMVRKS", "Creature"): recorded_search("LANDMVRKS Creature")["data"]}, albums(ALBUM), albums_down=True
    )
    report = finder(pdb, catalogue).run_once()
    assert (report.asked, report.complete) == (0, False)
    after = row_of(pdb, ref)
    assert after["album"] == "[Unknown Album]" and [after[c] for c in IDENTITY] == [None] * 4


def test_a_name_with_nothing_to_compare_and_a_song_with_no_length_are_never_stored_and_cost_no_request(pdb: Database) -> None:
    quiet = make_ref(pdb, "🎵", "Quiet Band", 200_000, like=True)
    no_length = make_ref(pdb, "Some Song", "Some Band", None, like=True)
    catalogue = Catalogue()
    seen = cursor(pdb)
    report = finder(pdb, catalogue).run_once()
    assert catalogue.searched == [] and report.asked == 0 and report.refused == 2
    for ref in (quiet, no_length):
        after = row_of(pdb, ref)
        assert [after[c] for c in IDENTITY] == [None] * 4, "unsupported and no_length are not facts about the catalogue"
        assert after["album"] is None, "but they were examined: the placeholder literal is forgotten"
    assert cursor(pdb) > seen
    again = finder(pdb, catalogue).run_once()
    assert again.refused == 2, "and they are looked at again next time, for nothing"


def test_a_refusal_needs_no_catalogue_so_the_literal_is_forgotten_even_on_a_day_the_catalogue_is_down(pdb: Database) -> None:
    """The refusal needs no catalogue, so the literal of such a song is forgotten even on a day the catalogue is down."""
    quiet = make_ref(pdb, "🎵", "Quiet Band", 200_000)
    finder(pdb, Catalogue(down=True)).run_once()
    assert row_of(pdb, quiet)["album"] is None


@pytest.mark.parametrize(
    ("what", "columns", "kept"),
    [
        ("a channel's name", {"artist_basis": "channel"}, "Encore/x/Singles/a.opus"),
        ("nobody's name", {"artist_basis": "unknown"}, "Encore/x/Singles/a.opus"),
        ("a song that has an id already", {"deezer_id": "42"}, "Encore/x/Singles/a.opus"),
        ("a song nobody has and no file", {}, None),
    ],
)
def test_who_is_not_asked(pdb: Database, what: str, columns: dict[str, Any], kept: str | None) -> None:
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, kept=kept, **columns)
    catalogue = landmvrks()
    finder(pdb, catalogue).run_once()
    assert catalogue.searched == [], what
    assert row_of(pdb, ref)["album"] == "[Unknown Album]" and row_of(pdb, ref)["identity_outcome"] is None, what


def test_a_song_somebody_likes_is_asked_even_when_the_server_keeps_no_file_of_it(pdb: Database) -> None:
    make_ref(pdb, "Creature", "LANDMVRKS", 225_000, kept=None, like=True)
    catalogue = landmvrks()
    finder(pdb, catalogue).run_once()
    assert catalogue.searched == [("LANDMVRKS", "Creature")]


def test_a_ref_on_the_p2_25_worklist_is_skipped_and_nothing_is_stored(pdb: Database) -> None:
    """Its file, and so its length and its name, may belong to another song until the rehome has judged it, and the stamp is permanent."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, like=True)
    with pdb.tx() as conn:
        conn.execute("INSERT INTO ref_recheck (ref, at, moved) VALUES (?, 1, 0)", (ref,))
    catalogue = landmvrks()
    seen = cursor(pdb)
    report = finder(pdb, catalogue).run_once()
    assert catalogue.searched == [] and report.asked == 0 and report.skipped == 1
    after = row_of(pdb, ref)
    assert after["album"] == "[Unknown Album]" and [after[c] for c in IDENTITY] == [None] * 4 and cursor(pdb) == seen


def test_a_song_that_changed_while_the_catalogue_was_asked_is_not_written(pdb: Database) -> None:
    """Somebody gave the song a real album (or another ref took its id) between the question and the answer: nothing is written, nothing is remembered."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)

    def an_import_gives_the_album() -> None:
        with pdb.tx() as conn:
            conn.execute("UPDATE song_ref SET album = 'Hollow' WHERE id = ?", (ref,))

    report = finder(pdb, landmvrks_with(an_import_gives_the_album)).run_once()
    after = row_of(pdb, ref)
    assert after["album"] == "Hollow" and [after[c] for c in IDENTITY] == [None] * 4
    assert report.skipped == 1 and report.matched == 0


def test_a_song_whose_catalogue_id_was_set_while_the_catalogue_was_asked_is_not_written(pdb: Database) -> None:
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)

    def somebody_describes_it() -> None:
        with pdb.tx() as conn:
            conn.execute("UPDATE song_ref SET deezer_id = '777' WHERE id = ?", (ref,))

    report = finder(pdb, landmvrks_with(somebody_describes_it)).run_once()
    after = row_of(pdb, ref)
    assert (after["deezer_id"], after["album"], after["identity_outcome"], report.skipped) == ("777", "[Unknown Album]", None, 1)


def test_a_song_put_on_the_worklist_while_the_catalogue_was_asked_is_not_written(pdb: Database) -> None:
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)

    def the_rekey_puts_it_on_the_worklist() -> None:
        with pdb.tx() as conn:
            conn.execute("INSERT INTO ref_recheck (ref, at, moved) VALUES (?, 1, 0)", (ref,))

    report = finder(pdb, landmvrks_with(the_rekey_puts_it_on_the_worklist)).run_once()
    after = row_of(pdb, ref)
    assert (after["album"], after["identity_outcome"], report.skipped) == ("[Unknown Album]", None, 1)


@pytest.mark.parametrize(
    ("column", "value", "reason"), [("deezer_id", "3116792061", "deezer_id_held"), ("isrc", "DEYO62300153", "isrc_held")]
)
def test_an_id_another_song_took_after_the_matcher_looked_is_a_held_pair_and_not_a_stamp(
    pdb: Database, monkeypatch: pytest.MonkeyPatch, column: str, value: str, reason: str
) -> None:
    """The second layer of step 5: the unique index would refuse the write, and `release_facts_to_fill` leaves a taken id alone; a song stamped with an album but without
    the id it was matched by would be neither found nor held, so the answer becomes HELD and only the placeholder is forgotten."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    other = make_ref(pdb, "Another", "Someone", 200_000, kept=None, album="Their Album")
    original = album_pass._DbHoldings.twin_held

    def late(self: Any, norm_key: str, release: str) -> bool:
        with pdb.tx() as conn:
            conn.execute(f"UPDATE song_ref SET {column} = ? WHERE id = ?", (value, other))  # noqa: S608 - the test's own column
        return original(self, norm_key, release)

    monkeypatch.setattr(album_pass._DbHoldings, "twin_held", late)
    report = finder(pdb, landmvrks()).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["identity_reason"], after["album"], after[column], report.held) == (
        "held",
        reason,
        None,
        None,
        1,
    )


def test_a_match_with_nothing_left_to_fill_is_a_none_and_never_a_stamp_without_an_album(
    pdb: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    monkeypatch.setattr(refs, "release_facts_to_fill", lambda conn, row, found: {})
    finder(pdb, landmvrks()).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["identity_reason"], after["album"], after["deezer_id"]) == (
        "none",
        "nothing_to_fill",
        None,
        None,
    )


def test_a_kept_path_that_leaves_the_music_folder_is_never_read_for_its_length(pdb: Database, tmp_path: Path) -> None:
    import wave

    root = tmp_path / "music"
    root.mkdir()
    outside = tmp_path / "outside.opus"
    with wave.open(str(outside), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * 12_000)
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, kept="../outside.opus")
    report = finder(pdb, landmvrks(), music_dir=root).run_once()
    assert report.matched == 1 and row_of(pdb, ref)["identity_outcome"] == "matched", (
        "the listing's length was used: the file outside the folder was not read"
    )


def landmvrks_with(on_search: Callable[[], None]) -> Catalogue:
    base = landmvrks()
    return Catalogue(base.searches, base.known_albums, on_search=on_search)


# ------------------------------------------------------------------------------------------------------------------ asked again


def test_a_none_is_asked_again_after_seven_days_and_not_before(pdb: Database) -> None:
    ref = make_ref(pdb, "A Song Nobody Recorded", "Nobody At All", 200_000)
    catalogue = Catalogue()
    finder(pdb, catalogue, now=NOW).run_once()
    finder(pdb, catalogue, now=NOW + 7 * DAY_MS - 1).run_once()
    assert len(catalogue.searched) == 1, "a week is not over"
    finder(pdb, catalogue, now=NOW + 7 * DAY_MS).run_once()
    assert len(catalogue.searched) == 2
    assert row_of(pdb, ref)["identity_tried_at"] == NOW + 7 * DAY_MS


def test_a_better_rule_asks_the_none_and_the_held_songs_again_at_once_and_never_a_matched_one(
    pdb: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    none = make_ref(pdb, "A Song Nobody Recorded", "Nobody At All", 200_000)
    make_ref(
        pdb, "Creature", "LANDMVRKS", 234_000, album="The Darkest Place I've Ever Been", kept=None
    )  # the twin that makes the next one held
    held = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    matched = make_ref(pdb, "Requiem", "LANDMVRKS", 240_000)
    catalogue = landmvrks()
    finder(pdb, catalogue).run_once()
    assert [row_of(pdb, r)["identity_outcome"] for r in (none, held, matched)] == ["none", "held", "matched"]
    asked = len(catalogue.searched)

    finder(pdb, catalogue).run_once()
    assert len(catalogue.searched) == asked, "same revision, same week: nobody is asked"

    monkeypatch.setattr(album_finder, "IDENTITY_REVISION", album_finder.IDENTITY_REVISION + 1)
    finder(pdb, catalogue).run_once()
    assert len(catalogue.searched) == asked + 2, "the none and the held are asked again; the matched has its id and is not"
    assert row_of(pdb, none)["identity_rev"] == album_finder.IDENTITY_REVISION
    assert row_of(pdb, matched)["identity_rev"] == album_finder.IDENTITY_REVISION - 1


def test_a_song_with_no_revision_at_all_is_asked_again_like_an_old_one(pdb: Database) -> None:
    ref = make_ref(pdb, "A Song Nobody Recorded", "Nobody At All", 200_000, identity_outcome="none", identity_tried_at=NOW)
    catalogue = Catalogue()
    finder(pdb, catalogue).run_once()
    assert len(catalogue.searched) == 1 and row_of(pdb, ref)["identity_rev"] == album_finder.IDENTITY_REVISION


# ------------------------------------------------------------------------------------------------------------------ the Arabic rows (era 1)


def test_two_different_arabic_songs_and_one_catalogue_hit_only_the_song_it_is_named_for_gets_an_album(pdb: Database) -> None:
    """The row of the design in every slice. The hit is Fairuz's "Kifak Inta" written in Arabic; the other Arabic song of the same artist is another key. Nothing is
    transliterated, nothing is guessed."""
    hit = arabic_hit("كيفك إنت")
    one = make_ref(pdb, "كيفك إنت", "فيروز", 209_000)
    other = make_ref(pdb, "حبيبي", "فيروز", 209_000)
    catalogue = Catalogue({("فيروز", "كيفك إنت"): [hit], ("فيروز", "حبيبي"): [hit]}, albums_for_arabic_hit(hit))
    finder(pdb, catalogue).run_once()
    assert row_of(pdb, one)["album"] == hit["album"]["title"] and row_of(pdb, one)["identity_outcome"] == "matched"
    assert row_of(pdb, other)["album"] is None and (
        row_of(pdb, other)["identity_outcome"],
        row_of(pdb, other)["identity_reason"],
    ) == (
        "none",
        "no_same_recording",
    )
    assert row_of(pdb, other)["deezer_id"] is None


def test_an_arabic_song_whose_only_hits_are_spelled_in_latin_letters_is_a_remembered_none_and_is_asked_again_by_a_better_rule(
    pdb: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = make_ref(pdb, "كيفك إنت", "فيروز", 209_000)
    catalogue = Catalogue({("فيروز", "كيفك إنت"): latin_hits()})
    finder(pdb, catalogue).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["identity_reason"], after["album"], after["deezer_id"]) == (
        "none",
        "latin_spelling_only",
        None,
        None,
    )
    finder(pdb, catalogue).run_once()
    assert len(catalogue.searched) == 1, "a remembered answer: not asked again this week"
    monkeypatch.setattr(album_finder, "IDENTITY_REVISION", album_finder.IDENTITY_REVISION + 1)
    finder(pdb, catalogue).run_once()
    assert len(catalogue.searched) == 2, "identity_rev asks it again when a better rule lands"


# ------------------------------------------------------------------------------------------------------------------ the length, the limit, the order of the pass


def test_the_kept_files_own_length_decides_when_the_music_folder_is_known(pdb: Database, tmp_path: Path) -> None:
    """The listing says 225 s (the catalogue's); the FILE is 1.5 s: it is not the catalogue's recording, so the song is not matched (the import's listing is 1 to 12 s
    off a file's own length: N-11)."""
    import wave

    root = tmp_path / "music"
    kept = root / "Encore" / "LANDMVRKS" / "Singles" / "Creature.opus"
    kept.parent.mkdir(parents=True)
    with wave.open(str(kept), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * 12_000)
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, kept="Encore/LANDMVRKS/Singles/Creature.opus")
    report = finder(pdb, landmvrks(), music_dir=root).run_once()
    assert (report.matched, report.none) == (0, 1)
    assert row_of(pdb, ref)["identity_reason"] == "no_same_recording"
    # the same song with the listing's length alone (no music folder) matches
    other = make_ref(pdb, "Requiem", "LANDMVRKS", 240_000)
    assert finder(pdb, landmvrks()).run_once().matched == 1 and row_of(pdb, other)["identity_outcome"] == "matched"


def test_the_pass_asks_at_most_per_pass_songs_and_the_next_pass_goes_on(pdb: Database) -> None:
    titles = [f"Song {number}" for number in range(5)]
    for title in titles:
        make_ref(pdb, title, "Some Band", 200_000)
    catalogue = Catalogue()
    first = finder(pdb, catalogue, per_pass=2).run_once()
    assert (first.asked, first.complete) == (2, False)
    second = finder(pdb, catalogue, per_pass=2).run_once()
    third = finder(pdb, catalogue, per_pass=2).run_once()
    assert (second.asked, third.asked, third.complete) == (2, 1, True)
    assert len(set(catalogue.searched)) == 5 and len(catalogue.searched) == 5, "nobody is asked twice"


def test_the_pass_stops_when_its_time_is_spent(pdb: Database) -> None:
    for number in range(4):
        make_ref(pdb, f"Song {number}", "Some Band", 200_000)
    ticks = iter(range(0, 1000, 100))
    catalogue = Catalogue()
    report = AlbumFinder(
        pdb, search=catalogue.search, album=catalogue.album, now=lambda: NOW, clock=lambda: float(next(ticks)), budget_s=150.0
    ).run_once()
    assert report.complete is False and 0 < report.asked < 4


def test_a_catalogue_that_is_resting_stops_the_pass_before_the_first_question(pdb: Database) -> None:
    make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    catalogue = landmvrks()
    report = AlbumFinder(
        pdb,
        search=catalogue.search,
        album=catalogue.album,
        resting=lambda: "the catalogue asked this server to rest (300 s)",
        now=lambda: NOW,
    ).run_once()
    assert catalogue.searched == [] and report.stopped and report.complete is False


def test_songs_with_a_kept_file_are_asked_before_the_others_and_each_group_in_the_order_they_were_made(pdb: Database) -> None:
    ids = [
        make_ref(pdb, "Liked First", "Band A", 200_000, kept=None, like=True),
        make_ref(pdb, "Kept", "Band B", 200_000),
        make_ref(pdb, "Liked Last", "Band C", 200_000, kept=None, like=True),
    ]
    with pdb.tx() as conn:  # the order of making is the order of `created_at`, which refs made in one millisecond would tie on
        for number, ref in enumerate(ids):
            conn.execute("UPDATE song_ref SET created_at = ? WHERE id = ?", (1000 + number, ref))
    catalogue = Catalogue()
    finder(pdb, catalogue).run_once()
    assert [title for _, title in catalogue.searched] == ["Kept", "Liked First", "Liked Last"]


def test_the_ask_and_decide_function_asks_nobody_about_a_song_that_cannot_be_compared() -> None:
    """The pass refuses such a song before it asks; `decide` is the one function the dry run asks with too, so it holds the same line itself."""

    def never(*args: Any) -> Any:
        raise AssertionError("the catalogue was asked about a song that cannot be compared")

    for song in (
        Song("Some Band", "🎵", 200_000),
        Song("Some Band", "Fine Title", None),
        Song("Unknown Artist", "Fine Title", 200_000),
    ):
        verdict = album_finder.decide(song, never, never)
        assert verdict.outcome in ("unsupported", "no_length") and verdict.remember is False


def test_a_single_is_re_askable_while_the_window_is_not_frozen_and_no_stamp_is_written(pdb: Database) -> None:
    """The recorded single AND album of Creature among the hits: nothing is written, the reason says why, and the placeholder is forgotten."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    catalogue = Catalogue({("LANDMVRKS", "Creature"): [single_hit(), creature_hit()]}, albums(ALBUM, SINGLE))
    finder(pdb, catalogue).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["identity_reason"]) == ("none", "single_before_album")
    assert after["album"] is None and after["deezer_id"] is None and after["track_no"] is None


def test_a_song_the_rule_withheld_is_asked_again_after_seven_days_and_when_the_rule_gets_better(
    pdb: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The re-ask is what makes `single_before_album` and `compilation_title` safe (review of PR 125, the lead's point 3c): the song is not stamped, it is asked again by the retry
    rule, after 7 days or at once when `IDENTITY_REVISION` rises (a frozen window, a better list of markers)."""
    single = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    marked = make_ref(pdb, "Comfortably Numb", "Pink Floyd", 382_000)
    only = [row for row in hits("pink floyd comfortably numb") if row["id"] != 116914122]
    catalogue = Catalogue(
        {("LANDMVRKS", "Creature"): [single_hit(), creature_hit()], ("Pink Floyd", "Comfortably Numb"): only},
        {**albums(ALBUM, SINGLE), BEST_OF: best_of_answer()},
    )
    finder(pdb, catalogue, now=NOW).run_once()
    assert (row_of(pdb, single)["identity_reason"], row_of(pdb, marked)["identity_reason"]) == (
        "single_before_album",
        "compilation_title",
    )
    assert len(catalogue.searched) == 2

    finder(pdb, catalogue, now=NOW + 7 * DAY_MS - 1).run_once()
    assert len(catalogue.searched) == 2, "a week is not over"
    finder(pdb, catalogue, now=NOW + 7 * DAY_MS).run_once()
    assert len(catalogue.searched) == 4, "after 7 days both are asked again"

    monkeypatch.setattr(album_finder, "IDENTITY_REVISION", album_finder.IDENTITY_REVISION + 1)
    finder(pdb, catalogue, now=NOW + 7 * DAY_MS).run_once()
    assert len(catalogue.searched) == 6, "and at once when the rule gets better"
    assert row_of(pdb, single)["identity_rev"] == row_of(pdb, marked)["identity_rev"] == album_finder.IDENTITY_REVISION


def test_a_best_of_whose_title_says_so_is_re_askable_and_no_stamp_is_written(pdb: Database) -> None:
    only = [row for row in hits("pink floyd comfortably numb") if row["id"] != 116914122]
    marked = make_ref(pdb, "Comfortably Numb", "Pink Floyd", 382_000)
    finder(pdb, Catalogue({("Pink Floyd", "Comfortably Numb"): only}, {BEST_OF: best_of_answer()})).run_once()
    after = row_of(pdb, marked)
    assert (after["identity_outcome"], after["identity_reason"], after["album"], after["deezer_id"]) == (
        "none",
        "compilation_title",
        None,
        None,
    )


def test_a_best_of_that_says_nothing_of_it_in_its_title_is_stamped_when_it_is_the_only_candidate(pdb: Database) -> None:
    """The ruling's case 1: it is a real release of the recording. A best-of called "Gold" passes."""
    only = [row for row in hits("pink floyd comfortably numb") if row["id"] != 116914122]
    gold = best_of_answer()
    gold["album"]["title"] = "Gold"
    ref = make_ref(pdb, "Comfortably Numb", "Pink Floyd", 382_000)
    finder(pdb, Catalogue({("Pink Floyd", "Comfortably Numb"): only}, {BEST_OF: gold})).run_once()
    after = row_of(pdb, ref)
    assert (after["album"], after["identity_outcome"], after["deezer_id"]) == ("Gold", "matched", "116914348")


def test_the_pass_makes_a_report_that_counts_every_answer_and_the_reasons_apart(pdb: Database) -> None:
    make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    make_ref(pdb, "A Song Nobody Recorded", "Nobody At All", 200_000)
    make_ref(pdb, "كيفك إنت", "فيروز", 209_000)
    catalogue = landmvrks()
    catalogue.searches[("فيروز", "كيفك إنت")] = latin_hits()
    report: AlbumReport = finder(pdb, catalogue).run_once()
    assert (report.asked, report.matched, report.none, report.held) == (3, 1, 2, 0)
    assert report.reasons == {"matched": 1, "no_same_recording": 1, "latin_spelling_only": 1}


def test_the_wall_wins_for_comfortably_numb_through_the_pass(pdb: Database) -> None:
    """The recorded search and the recorded albums of The Wall and the best-of: the original, by its date."""
    ref = make_ref(pdb, "Comfortably Numb", "Pink Floyd", 382_000)
    answers = {WALL: albums(WALL)[WALL], BEST_OF: best_of_answer()}
    finder(pdb, Catalogue({("Pink Floyd", "Comfortably Numb"): hits("pink floyd comfortably numb")}, answers)).run_once()
    after = row_of(pdb, ref)
    assert after["album"] == "The Wall" and after["year"] == 1979 and after["identity_outcome"] == "matched"


# ------------------------------------------------------------------------------------------------------------------ the pass writes nothing outside the row


def test_the_pass_never_touches_a_file_or_the_title_or_the_artists(pdb: Database, tmp_path: Path) -> None:
    root = tmp_path / "music"
    kept = root / "Encore" / "LANDMVRKS" / "Singles" / "Creature.opus"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"audio")
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, kept="Encore/LANDMVRKS/Singles/Creature.opus")
    before = (kept.read_bytes(), kept.stat().st_mtime_ns, sorted(p.name for p in kept.parent.iterdir()))
    finder(pdb, landmvrks(), music_dir=root).run_once()
    assert (kept.read_bytes(), kept.stat().st_mtime_ns, sorted(p.name for p in kept.parent.iterdir())) == before
    with pdb.read() as conn:
        file_row = conn.execute("SELECT path, navidrome_song_id, source FROM song_file WHERE ref = ?", (ref,)).fetchone()
    assert tuple(file_row) == ("Encore/LANDMVRKS/Singles/Creature.opus", f"nd_{ref}", "youtube")


# ------------------------------------------------------------------------------------------------------------------ the app runs it


def test_the_app_runs_the_album_pass_as_an_errand_before_the_cover_finder_and_through_the_real_catalogue_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without this a pass that nothing calls would pass every test above, and the order is the design's: the one search that finds the album also gives the picture,
    so the cover finder is left with the songs the pass did not place. The catalogue is the real code over the RECORDED answers (a mock transport): the search is
    `deezer.search_tracks`, the albums are `Catalogue.album`, both as background turns."""
    calls: list[str] = []

    def search(artist: str, title: str) -> list[dict[str, Any]]:
        calls.append(f"album pass: {title}")
        return deezer.search_tracks(artist, title, wait_s=5.0)

    def cover(artist: str, title: str, album: str | None, *, length_ms: int | None = None, client: object = None) -> None:
        calls.append(f"cover finder: {title}")

    monkeypatch.setattr("encore_server.album_pass.search_the_catalogue", search)
    monkeypatch.setattr("encore_server.cover_finder.deezer_lookup", cover)

    def music_server(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"subsonic-response": {"status": "ok", "scanStatus": {"scanning": False}}})

    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://music.invalid",
        navidrome_admin_user="admin",
        navidrome_admin_password="pw",
        youtube=False,
        workers=False,
    )
    client = NavidromeClient(
        "http://music.invalid", "admin", "pw", client=httpx.Client(transport=httpx.MockTransport(music_server))
    )
    recorded_catalogue = RealCatalogue(
        DeezerClient(Gate(rate=1000, burst=1000, background_gap_s=0.0), httpx.Client(transport=RecordedDeezer().transport())),
        Cache(None),
    )
    app = create_app(
        settings, navidrome=client, navidrome_admin=NavidromeAdmin("http://music.invalid", "", ""), catalogue=recorded_catalogue
    )
    services = app.state.services
    placed = make_ref(services.db, "Creature", "LANDMVRKS", 225_000)
    pictureless = make_ref(services.db, "Hollow Song", "Some Band", 200_000, album="Hollow", kept="Encore/b/Hollow/h.opus")

    assert services.linker is not None
    services.linker.run_once()

    assert calls.index("album pass: Creature") < min(i for i, c in enumerate(calls) if c.startswith("cover finder")), calls
    assert "cover finder: Hollow Song" in calls and "cover finder: Creature" not in calls, (
        "the pass gave Creature its picture: the cover finder is not asked"
    )
    after = row_of(services.db, placed)
    assert (after["album"], after["identity_outcome"], after["deezer_id"]) == (
        "The Darkest Place I've Ever Been",
        "matched",
        "3116792061",
    )
    assert after["cover_url"], "the one search that found the album also gave the picture"
    assert row_of(services.db, pictureless)["identity_outcome"] is None, "a song with an album of its own is not asked"
