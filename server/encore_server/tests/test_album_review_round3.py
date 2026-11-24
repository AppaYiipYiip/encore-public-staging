"""N-34 slice 2, the adversarial tester's five concerns on PR 125 (24 Nov 2026; verdict: approve, no blocker, 15,000 matcher cases and 450 cut passes, 0 violations).

1. A catalogue release called `Unknown Album` is chosen, `matched` and the id set, but the album written is the placeholder: a PERMANENT match with no album. Refused.
2. Release titles with Unplugged, Re-recorded or a possessive Version (Taylor's Version) are another recording than the library's file: refused unless the song's own title says so.
3. A catalogue id of 5,000 digits made `int()` raise inside the matcher and the pass aborted at that song every pass, so later songs starved.
4. The picture by id accepted Unicode digits (Arabic-Indic, fullwidth) into a URL path.
5. The dry run read the length of a song on its own (a fractional duration, a kept path outside the music folder) where the pass uses `album_pass.length_of`.
"""

# ruff: noqa: F811
from __future__ import annotations

import dataclasses
import logging
import sqlite3
import wave
from pathlib import Path
from typing import Any

import httpx
import pytest

from encore_server import album_dryrun, album_finder, album_pass
from encore_server.album_finder import Song, Verdict, choose_release, judge_hits, release_markers
from encore_server.cover_finder import deezer_picture_by_id
from encore_server.db import Database
from tests.test_album_finder import ALBUM, albums, copy_as, creature_hit, derive
from tests.test_album_pass import Catalogue, finder, landmvrks, make_ref, pdb, row_of  # noqa: F401 - `pdb` is a fixture

CREATURE = Song("LANDMVRKS", "Creature", 225_000)


def with_title(title: str) -> dict[str, dict[str, Any]]:
    """DERIVED: the recorded album of Creature with exactly its title changed."""
    return {ALBUM: derive(albums(ALBUM)[ALBUM], title=title)}


# ------------------------------------------------------------------------------------------------------------------ 1. a release called "Unknown Album"


@pytest.mark.parametrize("title", ["Unknown Album", "[Unknown Album]", "unknown album", "  [UNKNOWN ALBUM] "])
def test_a_release_called_unknown_album_is_never_chosen_it_is_a_re_askable_none(title: str) -> None:
    verdict = choose_release(CREATURE, [creature_hit()], with_title(title))
    assert (verdict.outcome, verdict.reason, verdict.remember, verdict.match) == ("none", "release_placeholder", True, None)
    assert [(r.album_id, r.reason) for r in verdict.releases] == [(ALBUM, "release_placeholder")]


def test_another_release_is_taken_over_one_called_unknown_album() -> None:
    """DERIVED: the recorded album and single of Creature, the album re-titled; the single is the song's release."""
    from tests.test_album_finder import SINGLE, single_hit

    both = {ALBUM: with_title("[Unknown Album]")[ALBUM], SINGLE: albums(SINGLE)[SINGLE]}
    verdict = choose_release(CREATURE, [creature_hit(), single_hit()], both, single_window_days=None)
    assert verdict.outcome == "matched" and verdict.match is not None and verdict.match.album_id == SINGLE


def test_the_pass_stamps_nothing_for_a_release_called_unknown_album(pdb: Database) -> None:  # noqa: F811
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    base = landmvrks()
    finder(pdb, Catalogue(base.searches, with_title("[Unknown Album]"))).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["identity_reason"], after["deezer_id"], after["album"]) == (
        "none",
        "release_placeholder",
        None,
        None,
    )


def test_the_write_transaction_refuses_a_placeholder_album_even_when_the_verdict_says_matched(
    pdb: Database, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    """The second layer: a matched verdict whose release carries the placeholder as its title (a future matcher, a hand-made verdict) writes no album and no id."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    real = album_finder.decide

    def a_matched_verdict_for_a_placeholder(song: Song, *args: Any, **kwargs: Any) -> Verdict:
        good = real(song, *args, **kwargs)
        assert good.match is not None
        return Verdict("matched", "matched", match=dataclasses.replace(good.match, album="[Unknown Album]"))

    monkeypatch.setattr(album_finder, "decide", a_matched_verdict_for_a_placeholder)
    finder(pdb, landmvrks()).run_once()
    after = row_of(pdb, ref)
    assert (after["identity_outcome"], after["identity_reason"], after["deezer_id"]) == ("none", "release_placeholder", None)


def test_the_fill_rule_never_writes_the_placeholder_as_an_album(pdb: Database) -> None:  # noqa: F811
    from tests.test_album_identity import facts, match

    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    assert facts(pdb, ref, match(album="[Unknown Album]")) == {}


# ------------------------------------------------------------------------------------------------------------------ 2. Unplugged, Re-recorded, Taylor's Version


@pytest.mark.parametrize(
    "title",
    [
        "MTV Unplugged",
        "Unplugged",
        "Fearless (Taylor's Version)",
        "Fearless (Taylor’s Version)",
        "Red (Mine's Version)",
        "Songs (Re-recorded)",
        "Songs Rerecorded",
        "The Re-Recording",
        "Songs (Re-record)",
        "Songs (Re Recorded)",
    ],
)
def test_these_release_titles_carry_a_version_mark(title: str) -> None:
    assert release_markers(title), title


@pytest.mark.parametrize(
    "title",
    [
        "Sessions",
        "The Basement Sessions",
        "A Tribute to the Band",
        "Recorded at Home",
        "Record Store Day",
        "Recording Studio",
        "Version Control",
        "The Version",
        "Her Version of Events",
        "Plugged In",
        "Unplug",
    ],
)
def test_sessions_tribute_and_the_plain_words_stay_out_they_are_too_common_in_real_album_names(title: str) -> None:
    """On purpose (the lead's ruling): `Sessions` and `Tribute` are in too many real album names; the cost of a miss is a re-askable `none`, and the artist's discography is the remedy."""
    assert release_markers(title) == frozenset(), title


@pytest.mark.parametrize(
    "title", ["Fearless (Taylor's Version)", "Live From Nowhere (Unplugged)", "Songs (Re-recorded)", "Red (Mine's Version)"]
)
def test_a_studio_song_is_not_stamped_with_another_recording_of_its_name(title: str) -> None:
    verdict = choose_release(CREATURE, [creature_hit()], with_title(title))
    assert (verdict.outcome, verdict.reason) == ("none", "release_version_mismatch"), title


def test_a_song_whose_own_title_says_it_may_take_the_release_that_says_it() -> None:
    hit = creature_hit()
    hit["title"] = "Creature (Taylor's Version)"
    song = Song("LANDMVRKS", "Creature (Taylor's Version)", 225_000)
    verdict = choose_release(song, [hit], with_title("Creature (Taylor's Version)"))
    assert verdict.outcome == "matched", (verdict.outcome, verdict.reason)


@pytest.mark.parametrize(
    "track", ["Creature (Unplugged)", "Creature (Re-recorded)", "Creature (Taylor's Version)", "Creature (Rerecorded 2024)"]
)
def test_the_track_title_carries_the_same_marks_through_the_version_signature(track: str) -> None:
    """The hit's own title was already held to them (`refs.norm_key` carries the version signature: any non-noise word of a bracket or a dash), so a studio song is not the
    song on a record whose track says so. Pinned here because the rule for releases now names the same marks."""
    row = creature_hit()
    row["title"] = track
    (verdict,) = judge_hits(CREATURE, [row])
    assert not verdict.accepted and verdict.reason == "title_or_version", track


def test_the_revision_was_raised_for_the_new_marks_and_the_placeholder_rule() -> None:
    assert album_finder.IDENTITY_REVISION == 3


# ------------------------------------------------------------------------------------------------------------------ 3. a huge id, an unexpected exception


@pytest.mark.parametrize("ident", ["9" * 5000, "9" * 21, "0" * 25, "١٢", "1" * 4301])
def test_an_id_that_is_not_one_to_twenty_ascii_digits_sorts_after_every_real_id_and_never_raises(ident: str) -> None:
    assert album_finder._id_order(ident) == (1, 0, ident)
    assert album_finder._id_order("9" * 20) < album_finder._id_order(ident)
    assert album_finder._id_order("9") < album_finder._id_order("10") < album_finder._id_order(ident)


def test_a_real_id_of_twenty_digits_is_still_a_number() -> None:
    assert album_finder._id_order("1" * 20) == (0, int("1" * 20), "1" * 20)


def test_an_album_with_a_huge_id_among_the_hits_does_not_stop_the_matcher() -> None:
    huge = "9" * 5000
    on_huge, on_real = creature_hit(), creature_hit()
    on_huge.update(id=1, album={"id": huge, "title": "x"})
    on_real.update(id=2, album={"id": 10, "title": "x"})
    both = {huge: copy_as(huge, "1"), "10": copy_as("10", "2")}
    verdict = choose_release(CREATURE, [on_huge, on_real], both)
    assert verdict.match is not None and (verdict.match.album_id, verdict.match.deezer_id) == ("10", "2")


class Exploding(Catalogue):
    """A catalogue whose search RAISES something nobody planned for, for one song."""

    def search(self, artist: str, title: str) -> list[dict[str, Any]]:
        if title == "Boom":
            self.searched.append((artist, title))
            raise RuntimeError("an unexpected failure")
        return super().search(artist, title)


def test_a_song_whose_matching_raises_is_logged_by_its_ref_and_skipped_and_the_pass_goes_on(
    pdb: Database,
    caplog: pytest.LogCaptureFixture,  # noqa: F811
) -> None:
    boom = make_ref(pdb, "Boom", "Some Band", 200_000, like=True)
    fine = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    after_it = make_ref(pdb, "Requiem", "LANDMVRKS", 240_000)
    with pdb.tx() as conn:  # the order of making is the order the pass asks in
        for number, ref in enumerate((boom, fine, after_it)):
            conn.execute("UPDATE song_ref SET created_at = ? WHERE id = ?", (1000 + number, ref))
    base = landmvrks()
    catalogue = Exploding(base.searches, base.known_albums)
    with caplog.at_level(logging.INFO, logger="encore_server.album_pass"):
        report = finder(pdb, catalogue).run_once()
    assert report.failed == 1 and report.matched == 2 and report.complete is True
    assert [row_of(pdb, ref)["identity_outcome"] for ref in (boom, fine, after_it)] == [None, "matched", "matched"]
    assert row_of(pdb, boom)["album"] == "[Unknown Album]", "nothing was remembered, not even the placeholder"
    lines = [r.getMessage() for r in caplog.records if boom in r.getMessage()]
    assert len(lines) == 1 and "Boom" not in lines[0] and "Some Band" not in lines[0], "logged by ref id only"
    again = finder(pdb, catalogue).run_once()
    assert again.failed == 1, "and it is asked again at the next pass"


# ------------------------------------------------------------------------------------------------------------------ 4. a picture by id takes ASCII digits only


@pytest.mark.parametrize("ident", ["١٢٣", "１２３４", "12٣", "²³", "१२"])
def test_a_picture_by_id_takes_ascii_digits_only_and_asks_nothing_for_other_digits(ident: str) -> None:
    requests: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json={})

    assert deezer_picture_by_id(ident, client=httpx.Client(transport=httpx.MockTransport(serve))) is None
    assert requests == []


# ------------------------------------------------------------------------------------------------------------------ 5. the dry run reads a song's length as the pass does


def open_copy(db: Database) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{db.path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def test_the_dry_run_reads_the_length_as_the_pass_does_a_fractional_listing_and_a_path_outside_the_music_folder(
    pdb: Database, tmp_path: Path
) -> None:  # noqa: F811
    root = tmp_path / "music"
    root.mkdir()
    outside = tmp_path / "outside.opus"
    with wave.open(str(outside), "wb") as out:  # 1.5 s: if it is read, the length is 1500
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * 12_000)
    escaping = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, kept="../outside.opus")
    fractional = make_ref(pdb, "Requiem", "LANDMVRKS", 240_000)
    negative = make_ref(pdb, "Negative", "Some Band", 200_000)
    with pdb.tx() as conn:
        conn.execute("UPDATE song_ref SET duration_ms = 240000.5 WHERE id = ?", (fractional,))
        conn.execute("UPDATE song_ref SET duration_ms = -5 WHERE id = ?", (negative,))
    conn = open_copy(pdb)
    try:
        entries = {e.ref_id: e for e in album_dryrun.entries(conn, music_root=root, now=1)}
    finally:
        conn.close()
    with pdb.read() as read:
        rows = {r["id"]: r for r in album_pass.wanting(read, now=1)}
    for ref, entry in entries.items():
        row = rows[ref]
        assert entry.song.length_ms == album_pass.length_of(root, row["kept"], row["duration_ms"]), ref
    assert (entries[escaping].song.length_ms, entries[escaping].length_from) == (225_000, "listing"), (
        "a path that leaves the folder is never read"
    )
    assert (entries[fractional].song.length_ms, entries[fractional].length_from) == (None, "none"), (
        "a fractional duration is no length, for both"
    )
    assert (entries[negative].song.length_ms, entries[negative].length_from) == (None, "none")


def test_the_pass_and_the_dry_run_agree_on_which_of_those_songs_are_asked(pdb: Database, tmp_path: Path) -> None:  # noqa: F811
    root = tmp_path / "music"
    root.mkdir()
    make_ref(pdb, "Creature", "LANDMVRKS", 225_000, kept="../outside.opus")
    fractional = make_ref(pdb, "Requiem", "LANDMVRKS", 240_000)
    with pdb.tx() as conn:
        conn.execute("UPDATE song_ref SET duration_ms = 240000.5 WHERE id = ?", (fractional,))
    conn = open_copy(pdb)
    try:
        askable = [
            e.song.title for e in album_dryrun.entries(conn, music_root=root, now=1) if album_finder.refusal(e.song) is None
        ]
    finally:
        conn.close()
    catalogue = landmvrks()
    finder(pdb, catalogue, music_dir=root, now=1).run_once()
    assert [title for _, title in catalogue.searched] == askable == ["Creature"]
