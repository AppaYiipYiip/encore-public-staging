"""N-34 slice 3, the shared parts: a NEW KEEP asks the catalogue about its song by the very selection and the very write rule of the album pass.

The permanence rules of the slice start here: the keeper must not have its own idea of which song may be filed under an album (`album_pass.wanting` is the one function, asked
for one ref), nor its own idea of what a verdict writes (`album_pass.commit_verdict`, which the pass calls too), nor its own way to read a length
(`album_pass.file_or_listing_length`, which `length_and_source` calls). These tests pin the three.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from encore_server import album_finder, album_pass
from encore_server.album_pass import commit_verdict, file_or_listing_length, length_and_source, wanting
from encore_server.db import Database
from tests import test_album_pass
from tests.test_album_pass import DAY_MS, NOW, Catalogue, landmvrks, make_ref, row_of

pdb = test_album_pass.pdb  # the fixture of the pass's tests, under its own name


def asked_for(db: Database, ref: str, *, now: int = NOW) -> bool:
    with db.read() as conn:
        return [row["id"] for row in wanting(conn, now=now, ref_id=ref)] == [ref]


# ------------------------------------------------------------------------------------------------------------------ the selection, for one ref


def test_a_song_being_kept_needs_no_other_holder_the_keep_itself_is_the_reason(pdb: Database) -> None:
    """The pass asks about songs somebody has or the server keeps; a new keep is the server KEEPING it, so for one ref the holder clause is the keep itself. Asked about
    nobody else: the same ref with the pass's own question (no ref given) is not selected."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, album=None, kept=None)
    with pdb.read() as conn:
        assert [row["id"] for row in wanting(conn, now=NOW)] == [], "the pass does not ask about a song nobody has or keeps"
    assert asked_for(pdb, ref)


def test_only_the_named_ref_is_selected(pdb: Database) -> None:
    mine = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, album=None, kept=None)
    make_ref(pdb, "Requiem", "LANDMVRKS", 250_000, album=None, kept=None, like=True)
    with pdb.read() as conn:
        assert [row["id"] for row in wanting(conn, now=NOW, ref_id=mine)] == [mine]


@pytest.mark.parametrize(
    ("what", "columns"),
    [
        ("a real album the song already has", {"album": "Their Album"}),
        ("a catalogue id the song already has", {"deezer_id": "42"}),
        ("an artist that is a channel", {"artist_basis": "channel"}),
        ("an artist that is nobody", {"artist_basis": "unknown"}),
        (
            "a none of this rule asked a moment ago",
            {"identity_outcome": "none", "identity_rev": album_finder.IDENTITY_REVISION, "identity_tried_at": NOW},
        ),
        (
            "a held pair of this rule asked a moment ago",
            {"identity_outcome": "held", "identity_rev": album_finder.IDENTITY_REVISION, "identity_tried_at": NOW},
        ),
        ("a stamp", {"identity_outcome": "matched", "identity_rev": album_finder.IDENTITY_REVISION, "identity_tried_at": NOW}),
    ],
)
def test_a_new_keep_asks_nothing_the_pass_would_not_ask(pdb: Database, what: str, columns: dict[str, Any]) -> None:
    columns = {"album": None, **columns}
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, kept=None, **columns)
    assert not asked_for(pdb, ref), what


def test_a_song_on_the_worklist_of_the_key_repair_is_not_asked_by_a_keep_either(pdb: Database) -> None:
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, album=None, kept=None)
    with pdb.tx() as conn:
        conn.execute("INSERT INTO ref_recheck (ref, at, moved) VALUES (?, 1, 0)", (ref,))
    assert not asked_for(pdb, ref)


def test_the_retry_rule_is_the_passes_a_week_and_a_better_rule(pdb: Database) -> None:
    ref = make_ref(
        pdb,
        "Creature",
        "LANDMVRKS",
        225_000,
        album=None,
        kept=None,
        identity_outcome="none",
        identity_rev=album_finder.IDENTITY_REVISION,
        identity_tried_at=NOW,
    )
    assert not asked_for(pdb, ref)
    assert asked_for(pdb, ref, now=NOW + 8 * DAY_MS), "a none is asked again after seven days"
    with pdb.tx() as conn:
        conn.execute("UPDATE song_ref SET identity_rev = ? WHERE id = ?", (album_finder.IDENTITY_REVISION - 1, ref))
    assert asked_for(pdb, ref), "and at once when the rule got better"


# ------------------------------------------------------------------------------------------------------------------ one way to read a length


def test_a_length_is_the_files_own_and_else_the_listings_whole_number_and_else_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(album_pass, "file_length_ms", lambda path: 231_456 if path.name == "a.opus" else None)
    assert file_or_listing_length(tmp_path / "a.opus", 230_000) == (231_456, "file")
    assert file_or_listing_length(tmp_path / "b.opus", 230_000) == (230_000, "listing"), (
        "a file that cannot be read falls back to the listing"
    )
    assert file_or_listing_length(None, 230_000) == (230_000, "listing")
    assert file_or_listing_length(None, 230_000.5) == (None, "none"), "a fractional listing is no length"
    assert file_or_listing_length(None, -1) == (None, "none")
    assert file_or_listing_length(None, None) == (None, "none")


def test_the_length_of_a_kept_file_is_read_through_the_same_function(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`length_and_source` only adds the music folder's rule (a path that leaves it is never read) and then asks `file_or_listing_length`: one definition."""
    asked: list[Path | None] = []

    def fake(path: Path | None, listed: object) -> tuple[int | None, str]:
        asked.append(path)
        return 1, "file"

    monkeypatch.setattr(album_pass, "file_or_listing_length", fake)
    assert length_and_source(tmp_path, "Encore/x/a.opus", 5) == (1, "file")
    assert asked == [tmp_path / "Encore/x/a.opus"]
    asked.clear()
    length_and_source(tmp_path, "../outside.opus", 5)
    assert asked == [None], "a path that leaves the music folder is never given to the reader"


# ------------------------------------------------------------------------------------------------------------------ one write rule


def test_the_write_rule_is_one_function_the_pass_and_a_keep_both_call(pdb: Database) -> None:
    """`commit_verdict` is the whole of what the pass writes for a song, called inside the caller's transaction: a match fills the album, the ids and the facts and
    remembers the answer; the row is read again inside, so a ref that gained an album meanwhile is skipped."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, album=None, kept=None)
    catalogue = landmvrks()
    song = album_finder.Song("LANDMVRKS", "Creature", 225_000)
    verdict = album_finder.decide(song, catalogue.search, catalogue.album)
    assert verdict.outcome == "matched"

    with pdb.tx() as conn:
        done = commit_verdict(conn, ref, verdict, now=NOW)
    assert (done.outcome, done.reason, done.skipped, done.wrote) == ("matched", "matched", False, True)
    after = row_of(pdb, ref)
    assert after["album"] == "The Darkest Place I've Ever Been" and after["deezer_id"] == "3116792061"
    assert (after["identity_outcome"], after["identity_tried_at"]) == ("matched", NOW)

    with pdb.tx() as conn:
        again = commit_verdict(conn, ref, verdict, now=NOW + 1)
    assert again.skipped and not again.wrote, "the song has its album now: nothing is written twice"
    assert row_of(pdb, ref)["identity_tried_at"] == NOW


def test_a_verdict_of_none_remembers_the_answer_and_forgets_the_placeholder(pdb: Database) -> None:
    ref = make_ref(pdb, "A Song Nobody Recorded", "Nobody At All", 200_000, kept=None)
    verdict = album_finder.decide(
        album_finder.Song("Nobody At All", "A Song Nobody Recorded", 200_000), Catalogue().search, Catalogue().album
    )
    with pdb.tx() as conn:
        done = commit_verdict(conn, ref, verdict, now=NOW)
    assert (done.outcome, done.reason, done.wrote) == ("none", "no_same_recording", True)
    after = row_of(pdb, ref)
    assert after["album"] is None and after["identity_outcome"] == "none"


def test_no_verdict_at_all_only_forgets_the_placeholder_and_remembers_nothing(pdb: Database) -> None:
    """A song that was examined but not asked (a name with nothing to compare): the literal goes, nothing is remembered about the catalogue."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, kept=None)
    with pdb.tx() as conn:
        done = commit_verdict(conn, ref, None, now=NOW)
    assert (done.outcome, done.skipped, done.wrote) == (None, False, True)
    after = row_of(pdb, ref)
    assert after["album"] is None and after["identity_outcome"] is None and after["identity_tried_at"] is None
