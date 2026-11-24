"""N-34 slice 1: the dry run of the album matcher (`python -m encore_server.album_dryrun`). It writes nothing and asks nobody in these tests: its catalogue is
a folder of RECORDED answers (the five albums, song lists and searches of `tests/fixtures/deezer/`, the Pink Floyd search of
`app/test/fixtures/deezer/search.json` written in the same shape), and its database is a copy a test makes.

What is pinned: which songs are asked (the design's "who is asked"), where the length of each came from (a copy holds no file, so the report must say
the histogram is not the file's), the report's sections, that the database file is not changed by a byte, that a replay opens no connection, that a
live run is opt-in and capped and saves what it was told, and that the names of the saved answers are the recorder's.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import socket
import sqlite3
import sys
import wave
from pathlib import Path
from typing import Any

import httpx
import pytest

from encore_server import album_dryrun, album_finder, deezer, refs
from encore_server.album_dryrun import (
    AnswerTransport,
    Entry,
    Report,
    Row,
    entries,
    file_length_ms,
    main,
    opened,
    run,
)
from encore_server.album_finder import HitVerdict, Song, Verdict
from encore_server.db import Database
from encore_server.fixture_names import fixture_name, search_name
from tests.catalogue_fakes import QUOTA, RECORDED, searches

# ------------------------------------------------------------------------------------------------------------------ a database and a folder of answers


def make_ref(
    db: Database, title: str, artist: str, length: int | None, *, kept: str | None = None, source: str = "youtube", **more: Any
) -> str:
    """A ref made the way the server makes one (`refs.resolve`); [kept] gives it a kept file of the keeper (`source = 'youtube'`) at that path."""
    with db.tx() as conn:
        ref = str(refs.resolve(conn, {"title": title, "artists": [artist], "durationMs": length, **more})["id"])
        if kept is not None:
            conn.execute(
                "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, source, preferred, added_at) VALUES (?, ?, ?, ?, 'opus', ?, 1, 1)",
                (f"sf_{ref}", ref, f"nd_{ref}", kept, source),
            )
    return ref


def answers_folder(tmp_path: Path) -> Path:
    """The recorded answers the replay serves: the committed step-0 recordings, plus the Pink Floyd search written in the recorder's file shape."""
    folder = tmp_path / "answers"
    folder.mkdir()
    for source in RECORDED.glob("*.json"):
        if re.fullmatch(r"search_track_.*|album_\d+(_tracks)?|artist_albums_\d+", source.stem):
            shutil.copy(source, folder / source.name)
    for asked, recorded_as in (
        ("Pink Floyd Comfortably Numb", "pink floyd comfortably numb"),
        ("Mazzy Star Fade Into You", "mazzy star fade into you"),
    ):
        body = {
            "recorded": "2026-10-22",
            "path": "/search",
            "params": {"q": asked, "limit": 8},
            "answer": {"data": searches()[recorded_as]["track"]},
        }
        (folder / f"{fixture_name('/search', {'q': asked})}.json").write_text(json.dumps(body), encoding="utf-8")
    return folder


@pytest.fixture()
def library(db: Database, tmp_path: Path) -> Database:
    """The songs of a small library: three the recordings know, a twin of one of them, an Arabic one (asked since P2-25 slices 2 and 3: the fold keeps its letters, and
    nobody recorded its search), one whose title has no letter or digit (the one kind of name still refused), one nobody recorded, and the ones that are NOT asked."""
    make_ref(db, "Not Kept", "Someone Else", 202_000)  # made FIRST: only "the ones with a kept file first" puts it last
    # the ref's own ISRC is the catalogue's: it is the song's own, never "another ref's" (a pair)
    make_ref(db, "Requiem", "LANDMVRKS", 240_000, kept="Encore/LANDMVRKS/Singles/Requiem.opus", isrc="DEYO62400324")
    make_ref(db, "Creature", "LANDMVRKS", 225_000, kept="Encore/LANDMVRKS/Singles/Creature.opus")
    # the twin: the same song with its real album (an import gave it) and its own file, 9 s longer so that `refs.find` keeps them two refs
    make_ref(
        db,
        "Creature",
        "LANDMVRKS",
        234_000,
        kept="Encore/LANDMVRKS/Album/Creature.opus",
        album="The Darkest Place I've Ever Been",
    )
    make_ref(db, "Comfortably Numb", "Pink Floyd", 382_000, kept="Encore/Pink Floyd/Singles/Comfortably Numb.opus")
    make_ref(db, "كيفك إنت", "فيروز", 209_000, kept="Encore/x/Singles/a.opus")
    make_ref(
        db, "🎵", "Quiet Band", 200_000, kept="Encore/x/Singles/e.opus"
    )  # no letter and no digit: the fold has nothing to compare (still refused)
    make_ref(db, "A Song Nobody Recorded", "Nobody At All", 200_000, kept="Encore/y/Singles/b.opus")
    make_ref(db, "Has An Id", "Someone", 200_000, kept="Encore/z/Singles/c.opus", deezerId="999")
    make_ref(db, "Has An Album", "Someone", 201_000, kept="Encore/z/Singles/d.opus", album="Their Album")
    make_ref(
        db, "Hosts Own File", "Someone", 203_000, kept="Music/Someone/Hosts Own File.flac", source="library"
    )  # not kept by Encore
    # the search is recorded but the album (319814) is not: the album "could not be asked", which is not "the catalogue knows none"
    make_ref(db, "Fade Into You", "Mazzy Star", 292_000, kept="Encore/Mazzy Star/Singles/Fade Into You.opus")
    make_ref(db, "No Length", "Somebody Quiet", None, kept="Encore/q/Singles/n.opus")
    return db


def open_copy(db: Database) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{db.path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------------------------------------------------------------------------------------------------ the names of the answers


def test_the_saved_answers_are_named_exactly_as_the_recorder_names_them() -> None:
    """The recorder (`tools/record_catalogue_fixtures.py n34`) writes `{recorded, path, params, answer}` under these names: every recorded file's own
    path and params give its own name here, so a replay finds what a recording made and the other way round."""
    seen = 0
    for source in RECORDED.glob("*.json"):
        if not re.fullmatch(r"search_track_landmvrks_\w+|album_\d+(_tracks)?|artist_albums_\d+", source.stem):
            continue
        body = json.loads(source.read_text(encoding="utf-8"))
        assert fixture_name(body["path"], body["params"]) == source.stem, source.name
        seen += 1
    assert seen >= 10, "the ten step-0 recordings"
    assert fixture_name("/search", {"q": "Pink Floyd Comfortably Numb"}) == search_name("Pink Floyd Comfortably Numb")
    assert fixture_name("/search", {"q": "(Hello) !"}) != fixture_name("/search", {"q": "Hello"}), (
        "a query is named by ALL of it: these two were one file when only the Latin letters counted (the full rule: tests/test_fixture_names.py)"
    )
    assert (
        fixture_name("/search", {}) is None
        and fixture_name("/chart/0/tracks", {}) is None
        and fixture_name("/album/abc", {}) is None
    )


# ------------------------------------------------------------------------------------------------------------------ who is asked and how long they are


def test_who_is_asked_the_kept_songs_with_no_album_and_no_id_first_and_what_their_length_is(library: Database) -> None:
    """Since the review of PR 125 the selection is `album_pass.wanting`, the pass's own (`test_album_selection.py`): a song somebody has or the server keeps ANY file of is asked
    (the Host's own file included), `kept_only` is the dry run's filter on top."""
    with open_copy(library) as conn:
        kept = entries(conn, kept_only=True)
        assert [(e.song.artist, e.song.title) for e in kept] == [
            ("LANDMVRKS", "Requiem"),
            ("LANDMVRKS", "Creature"),
            ("Pink Floyd", "Comfortably Numb"),
            ("فيروز", "كيفك إنت"),
            ("Quiet Band", "🎵"),
            ("Nobody At All", "A Song Nobody Recorded"),
            ("Mazzy Star", "Fade Into You"),
            ("Somebody Quiet", "No Length"),
        ], "a ref with an album, with a catalogue id, with no kept file or only a file of the Host's own library is not asked"
        assert [e.length_from for e in kept] == ["listing"] * 7 + ["none"], (
            "a copy holds no file: the import's listing is all there is"
        )
        everyone = entries(conn)
        assert [e.song.title for e in everyone][-1:] == ["Hosts Own File"] and len(everyone) == len(kept) + 1, (
            "the Host's own file: the pass asks it too"
        )
        assert "Not Kept" not in [e.song.title for e in everyone], (
            "nobody has it and the server keeps no file of it: the pass does not ask it"
        )
        assert len(entries(conn, limit=2)) == 2


def test_a_song_with_a_basis_that_is_not_a_performer_is_not_asked(db: Database) -> None:
    make_ref(db, "Upload", "Some Channel", 200_000, kept="Encore/c/Singles/u.opus")
    make_ref(db, "Real", "A Band", 200_000, kept="Encore/c/Singles/r.opus")
    with db.tx() as conn:
        conn.execute("UPDATE song_ref SET artist_basis = 'channel' WHERE title = 'Upload'")
    with open_copy(db) as conn:
        assert [e.song.title for e in entries(conn)] == ["Real"]


def test_the_length_of_a_kept_file_is_read_from_the_file_when_a_music_root_is_given(library: Database, tmp_path: Path) -> None:
    root = tmp_path / "music"
    kept = root / "Encore" / "LANDMVRKS" / "Singles" / "Requiem.opus"
    kept.parent.mkdir(parents=True)
    with wave.open(str(kept), "wb") as out:  # mutagen reads a WAV's length; 1.5 s of silence at 8 kHz
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * 12_000)
    assert file_length_ms(kept) == 1_500
    with open_copy(library) as conn:
        by_title = {e.song.title: e for e in entries(conn, music_root=root)}
    assert (by_title["Requiem"].song.length_ms, by_title["Requiem"].length_from) == (1_500, "file")
    assert (by_title["Comfortably Numb"].song.length_ms, by_title["Comfortably Numb"].length_from) == (382_000, "listing"), (
        "no such file: the listing"
    )
    assert file_length_ms(tmp_path / "missing.opus") is None
    junk = tmp_path / "junk.opus"
    junk.write_bytes(b"not audio at all")
    assert file_length_ms(junk) is None


# ------------------------------------------------------------------------------------------------------------------ the run and the report


def run_library(library: Database, tmp_path: Path, **more: Any) -> tuple[list[Row], AnswerTransport]:
    with open_copy(library) as conn, opened(answers_folder(tmp_path), live=False, max_requests=None) as source:
        rows = run(conn, entries(conn), source.search, source.album, **more)
        return rows, source.transport


def test_the_run_decides_every_song_on_the_recorded_answers_and_says_what_it_could_not_ask(
    library: Database, tmp_path: Path
) -> None:
    rows, transport = run_library(library, tmp_path)
    outcomes = {row.entry.song.title + str(row.entry.song.length_ms): (row.verdict.outcome, row.verdict.reason) for row in rows}
    assert outcomes == {
        "Requiem240000": ("matched", "matched"),
        "Creature225000": ("held", "twin_held"),  # the twin already holds this song on this album
        "Comfortably Numb382000": ("matched", "matched"),
        # asked: the name survives the fold whole now (it was refused as "artist_not_comparable" before P2-25 slices 2 and 3); nobody recorded its search
        "كيفك إنت209000": ("unavailable", "search_not_asked"),
        "🎵200000": ("unsupported", "title_not_comparable"),  # NOT asked: no letter and no digit
        "A Song Nobody Recorded200000": (
            "unavailable",
            "search_not_asked",
        ),  # NOT "none": nobody recorded what the catalogue says
        "Fade Into You292000": ("unavailable", "release_not_asked"),
        "No LengthNone": ("no_length", "no_length"),
        "Hosts Own File203000": (
            "unavailable",
            "search_not_asked",
        ),  # a song of the Host's own library with no album: the pass asks it too
    }
    matched = {row.entry.song.title: row.verdict.match for row in rows if row.verdict.match}
    assert matched["Requiem"] is not None and matched["Requiem"].album == "The Darkest Place I've Ever Been"
    assert matched["Comfortably Numb"] is not None and (matched["Comfortably Numb"].album, matched["Comfortably Numb"].year) == (
        "The Wall",
        1979,
    )
    # the best-of's song list was never recorded and is not needed (The Wall is chosen), so it is "could not ask" for a song that did not need it
    assert (
        sorted(transport.not_recorded)
        # the Arabic song's search has a name of its own (the hash of its whole query): it used to be `search_track_`, the name of EVERY query without a Latin
        # letter, so a live run replayed the first Arabic answer to all the others (tests/test_fixture_names.py)
        == sorted(
            [
                "album_12114262_tracks",
                "album_319814",
                search_name("فيروز كيفك إنت"),
                search_name("Nobody At All A Song Nobody Recorded"),
                search_name("Someone Hosts Own File"),
            ]
        )
        and transport.asked == 0
    )


def test_the_report_names_every_section_the_lead_reads(library: Database, tmp_path: Path) -> None:
    rows, transport = run_library(library, tmp_path)
    text = Report(rows, album_finder.TOLERANCE_MS, {"asked": 0, "replayed": transport.replayed}).render()
    first = text.splitlines()[0]
    assert first.startswith("TOLERANCE: 3000 ms") and "MEASURED on 24 Nov 2026 and KEPT" in first and "UNMEASURED" not in first, (
        "the measured state of the tolerance is the first thing the reader sees"
    )
    for section in (
        "== outcomes",
        "== where the song's length came from",
        "== histogram: the song's length minus the catalogue's",
        "== hits rejected ONLY by the tolerance",
        "== releases",
        "== held pairs",
        "== songs that cannot be asked",
        "== matched",
    ):
        assert section in text, section
    assert "NO row used a file's length" in text, (
        "all five lengths are the listing's: the report says it is not the file's histogram"
    )
    assert re.search(r"matched\s+matched\s+\(remembered\)", text) and re.search(
        r"unsupported\s+title_not_comparable\s+\(never remembered\)", text
    )
    assert re.search(r"unavailable\s+search_not_asked\s+\(never remembered\)", text)
    assert re.search(r"unavailable\s+release_not_asked\s+\(never remembered\)", text)
    near = text.split("== hits rejected ONLY by the tolerance")[1].split("==")[0]
    assert "-31000 ms" in near and "Pink Floyd - Comfortably Numb" in near, (
        "the 413 s cut: same artist, title and version, 31 s off"
    )
    assert "+54000 ms" in near and "+4000 ms" in near and "Mazzy Star - Fade Into You" in near, (
        "the 238 s edit and the 288 s cut of Fade Into You"
    )
    assert sum("sr_" in line for line in near.splitlines()) == 3, "only hits the length alone rejected are listed"
    assert "inside the tolerance: 4 of 4" in text, (
        "Requiem, Creature, Comfortably Numb and Fade Into You are exact: the nearest hit of each is 0 s away"
    )
    assert "Creature" in text.split("== held pairs")[1].split("==")[0] and "twin_held" in text


@pytest.mark.parametrize(("delta", "inside"), [(3000, True), (3001, False), (-3000, True), (-3001, False), (0, True)])
def test_the_histogram_counts_the_tolerance_inclusively_and_by_the_nearest_hit(delta: int, inside: bool) -> None:
    song = Song("A", "B", 100_000)
    hit = HitVerdict("1", "A", "B", "9", "same_recording" if inside else "length", delta, True)
    far = HitVerdict("2", "A", "B", "9", "length", 60_000, True)
    row = Row(Entry("sr_1", song, "file"), Verdict("none", "x", hits=(far, hit)))
    text = Report([row], 3000).render()
    assert f"inside the tolerance: {1 if inside else 0} of 1" in text, text
    assert "length from: file" in text and "NO row used a file's length" not in text


def test_the_histogram_buckets_do_not_lose_a_song_at_an_edge() -> None:
    for delta in (
        -1_000_000,
        -30_000,
        -29_999,
        -10_000,
        -5_000,
        -3_001,
        -3_000,
        -1,
        0,
        999,
        1_000,
        3_000,
        3_001,
        5_000,
        29_999,
        30_000,
        10_000_000,
    ):
        row = Row(
            Entry("sr_1", Song("A", "B", 1), "listing"),
            Verdict("none", "x", hits=(HitVerdict("1", "A", "B", "9", "length", delta, True),)),
        )
        text = Report([row], 3000).render()
        counted = [int(m.group(1)) for m in re.finditer(r"^\s+-?\+?\w+ \.\. [-+\w]+ *s +(\d+) ", text, re.M)]
        assert sum(counted) == 1, (delta, counted)


def test_only_length_rejections_are_near_misses_and_the_nearest_is_listed_first() -> None:
    far = Row(
        Entry("sr_far", Song("A", "B", 1), "listing"),
        Verdict(
            "none",
            "x",
            hits=(
                HitVerdict("1", "A", "B", "9", "length", 50_000, True),
                HitVerdict("2", "A", "C", "9", "title_or_version", 10, False),
            ),
        ),
    )
    near = Row(
        Entry("sr_near", Song("A", "B", 1), "listing"),
        Verdict("none", "x", hits=(HitVerdict("3", "A", "B", "9", "length", -5_000, True),)),
    )
    text = Report([far, near], 3000).render()
    lines = [
        line for line in text.split("== hits rejected ONLY by the tolerance")[1].split("\n== ")[0].splitlines() if "sr_" in line
    ]
    assert [("sr_near" in line, "sr_far" in line) for line in lines] == [(True, False), (False, True)], lines
    assert "-5000 ms" in lines[0] and "+50000 ms" in lines[1]


@pytest.mark.parametrize(
    ("delta", "label"),
    [
        (3_000, "+3 .. +4 s"),
        (2_999, "+2 .. +3 s"),
        (-3_000, "-3 .. -2 s"),
        (-3_001, "-4 .. -3 s"),
        (0, "+0 .. +1 s"),
        (-1, "-1 .. +0 s"),
        (30_000, "+30 .. +inf s"),
        (29_999, "+10 .. +30 s"),
        (-30_000, "-30 .. -10 s"),
        (-30_001, "-inf .. -30 s"),
    ],
)
def test_a_delta_on_an_edge_of_the_histogram_goes_to_the_bucket_that_starts_there(delta: int, label: str) -> None:
    assert " ".join(album_dryrun._bucket_label(album_dryrun._bucket(delta)).split()) == label


def test_a_song_whose_hits_have_no_matching_name_is_not_in_the_histogram() -> None:
    other = HitVerdict("1", "X", "Y", "9", "artist", 0, False)
    text = Report([Row(Entry("sr_1", Song("A", "B", 1), "listing"), Verdict("none", "x", hits=(other,)))], 3000).render()
    assert "(no song had a hit of the same artist, title and version)" in text


def test_the_run_stops_when_the_caller_says_so_after_the_song_in_hand(library: Database, tmp_path: Path) -> None:
    asked: list[None] = []

    def stop() -> bool:
        asked.append(None)
        return len(asked) >= 2

    with open_copy(library) as conn, opened(answers_folder(tmp_path), live=False, max_requests=None) as source:
        rows = run(conn, entries(conn), source.search, source.album, stop=stop)
    assert [r.entry.song.title for r in rows] == ["Requiem", "Creature"]


# ------------------------------------------------------------------------------------------------------------------ the command


def test_the_command_writes_nothing_to_the_database_and_prints_the_report(library: Database, tmp_path: Path) -> None:
    database = tmp_path / "data" / "encore.db"
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    printed: list[str] = []
    target = tmp_path / "report.txt"
    code = main(
        ["--db", str(database), "--answers", str(answers_folder(tmp_path)), "--out", str(target), "--examples", "3"],
        out=printed.append,
    )
    assert code == 0
    assert "".join(printed) == target.read_text(encoding="utf-8") and "9 songs through the matcher" in target.read_text(
        encoding="utf-8"
    )
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before, "the database file is not changed by a byte"
    assert deezer.installed() is None, "the client installed for the run is taken away again"


def test_a_console_that_cannot_show_a_name_gets_its_escape_and_the_run_still_ends_well(
    library: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found by running it on a real library's copy: an Arabic title crashed the print on a cp1252 console, after everything was asked."""
    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", console)
    assert main(["--db", str(tmp_path / "data" / "encore.db"), "--answers", str(answers_folder(tmp_path))]) == 0
    console.flush()
    shown = console.buffer.getvalue().decode("cp1252")  # type: ignore[attr-defined]
    assert r"\u0643" in shown and "9 songs through the matcher" in shown


@pytest.mark.parametrize(
    "argv",
    [
        ["--db", "x.db"],  # nothing to ask
        ["--db", "x.db", "--live"],  # live without a cap
        ["--db", "x.db", "--live", "--max-requests", "0"],
        ["--db", "no-such-file.db", "--answers", "somewhere"],
    ],
)
def test_the_command_refuses_to_ask_without_being_told_how_much(
    argv: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.db").write_bytes(b"")
    with pytest.raises(SystemExit) as stopped:
        main(argv)
    assert stopped.value.code == 2


def test_a_replay_opens_no_connection_and_rests_nobody(
    library: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[object] = []

    def refuse(self: socket.socket, address: object) -> None:
        attempts.append(address)
        raise AssertionError(f"the dry run tried to connect to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    with open_copy(library) as conn, opened(answers_folder(tmp_path), live=False, max_requests=None) as source:
        run(conn, entries(conn), source.search, source.album)
        assert source.catalogue.state() == {"state": "ok", "resumesInSec": 0}, "a request nobody recorded must not rest the gate"
        assert deezer.installed() is source.catalogue.client
    assert attempts == []


# ------------------------------------------------------------------------------------------------------------------ the live path, with a fake network


class FakeNetwork(httpx.BaseTransport):
    """Stands in for the real network of `--live`: answers every request and counts them."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        body = {
            "data": [
                {
                    "id": 1,
                    "title": "x",
                    "preview": "https://cdn.example/p?hdnea=SECRET",
                    "share": "https://example/s",
                    "md5_image": "abc",
                }
            ]
        }
        return httpx.Response(200, json=body, request=request)


def ask(transport: AnswerTransport, path: str, **params: Any) -> httpx.Response:
    return httpx.Client(transport=transport).get("https://api.deezer.com" + path, params=params)


def test_a_live_run_is_capped_saves_what_it_was_told_and_a_second_run_asks_nothing(tmp_path: Path) -> None:
    folder, network = tmp_path / "answers", FakeNetwork()
    first = AnswerTransport(folder, live=network, max_requests=2)
    assert ask(first, "/search", q="Pink Floyd Comfortably Numb", limit=8).status_code == 200
    assert ask(first, "/album/12114248").status_code == 200
    assert first.asked == 2 and not first.spent
    refused = ask(first, "/album/12114248/tracks", limit=100)
    assert refused.status_code == 400 and first.spent and first.asked == 2 and len(network.requests) == 2, (
        "the third request is not made"
    )
    saved = json.loads((folder / f"{search_name('Pink Floyd Comfortably Numb')}.json").read_text(encoding="utf-8"))
    assert saved["path"] == "/search" and saved["params"] == {"q": "Pink Floyd Comfortably Numb", "limit": "8"}
    assert (
        "preview" not in json.dumps(saved) and "SECRET" not in json.dumps(saved) and "share" not in saved["answer"]["data"][0]
    ), "signed addresses are taken out"
    assert sorted(path.name for path in folder.iterdir()) == [
        "album_12114248.json",
        f"{search_name('Pink Floyd Comfortably Numb')}.json",
    ]
    second, silent = AnswerTransport(folder, live=FakeNetwork(), max_requests=2), FakeNetwork()
    assert (
        ask(second, "/album/12114248").status_code == 200
        and ask(second, "/search", q="Pink Floyd Comfortably Numb").status_code == 200
    )
    assert (second.asked, second.replayed) == (0, 2), "a saved answer is replayed, not asked again"
    assert silent.requests == []


def test_the_tolerance_of_the_run_reaches_both_the_albums_asked_and_the_decision(db: Database, tmp_path: Path) -> None:
    """Requiem listed 4.5 s longer than the catalogue's 240 s: refused at 3 s, the same recording at 5 s. (The albums asked and the decision both use it.)"""
    make_ref(db, "Requiem", "LANDMVRKS", 244_500, kept="Encore/LANDMVRKS/Singles/Requiem.opus")
    with open_copy(db) as conn, opened(answers_folder(tmp_path), live=False, max_requests=None) as source:
        default = run(conn, entries(conn), source.search, source.album)
        wider = run(conn, entries(conn), source.search, source.album, tolerance_ms=5_000)
        narrower = run(conn, entries(conn), source.search, source.album, tolerance_ms=100)
    assert [(r.verdict.outcome, r.verdict.reason) for r in default] == [("none", "no_same_recording")]
    assert [(r.verdict.outcome, r.verdict.reason) for r in wider] == [("matched", "matched")]
    assert default[0].verdict.hits[0].delta_ms == 4_500 and narrower[0].verdict.outcome == "none"


def test_the_command_takes_the_tolerance_from_its_flag(db: Database, tmp_path: Path) -> None:
    make_ref(db, "Requiem", "LANDMVRKS", 244_500, kept="Encore/LANDMVRKS/Singles/Requiem.opus")
    base = ["--db", str(tmp_path / "data" / "encore.db"), "--answers", str(answers_folder(tmp_path))]
    default, wider = [], []
    assert main(base, out=default.append) == 0 and main([*base, "--tolerance-ms", "5000"], out=wider.append) == 0
    assert "NO MATCH" in "".join(default) and "5000 ms" in "".join(wider) and "(remembered)" in "".join(wider)
    assert re.search(r"\d+\s+matched\s+matched", "".join(wider)) and not re.search(r"\d+\s+matched\s+matched", "".join(default))


class Quota(FakeNetwork):
    """Deezer's throttling answer (HTTP 200 with the body of code 4, `tests/catalogue_fakes.QUOTA`) to everything."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        return httpx.Response(200, json=QUOTA, request=request)


def test_a_live_run_stops_when_the_catalogue_rests_this_server_and_says_so(library: Database, tmp_path: Path) -> None:
    network, printed = Quota(), []
    code = main(
        ["--db", str(tmp_path / "data" / "encore.db"), "--answers", str(tmp_path / "answers"), "--live", "--max-requests", "50"],
        out=printed.append,
        network=network,
    )
    text = "".join(printed)
    assert code == 0 and len(network.requests) == 1, "the first refusal rested the gate: not one request more"
    assert "STOPPED EARLY: the catalogue asked this server to rest" in text and "run the same command again later" in text
    assert re.search(r"1 songs? through the matcher", text), (
        "only the song in hand was decided; the rest were never asked, not reported as failures"
    )
    assert not (tmp_path / "answers").exists() or list((tmp_path / "answers").iterdir()) == [], "an error answer is never saved"


def test_a_live_run_stops_at_its_request_cap_and_says_so(library: Database, tmp_path: Path) -> None:
    network, printed = FakeNetwork(), []
    main(
        ["--db", str(tmp_path / "data" / "encore.db"), "--answers", str(tmp_path / "answers"), "--live", "--max-requests", "3"],
        out=printed.append,
        network=network,
    )
    text = "".join(printed)
    assert len(network.requests) == 3, "the cap is a ceiling on the requests made, not on the songs"
    assert "STOPPED EARLY: the request cap of this run is spent" in text and "requests: asked 3" in text
    assert len(list((tmp_path / "answers").iterdir())) == 3, (
        "what was asked is saved, so the next run starts where this one stopped"
    )


def test_a_live_run_over_a_library_in_another_alphabet_asks_about_every_song_and_saves_one_answer_each(
    db: Database, tmp_path: Path
) -> None:
    """The review's defect at the level of the command: three Arabic songs of one artist. Every one is asked (the fold keeps their letters since P2-25) and the
    folder gets three answers; with the ASCII-only name of before, the first answer was saved as `search_track_` and replayed to the other two."""
    for title in ("كيفك إنت", "حبيبي", "سألوني الناس"):
        make_ref(db, title, "فيروز", 209_000, kept=f"Encore/f/Singles/{title}.opus")
    network, printed = FakeNetwork(), []
    code = main(
        ["--db", str(tmp_path / "data" / "encore.db"), "--answers", str(tmp_path / "answers"), "--live", "--max-requests", "50"],
        out=printed.append,
        network=network,
    )
    assert code == 0 and len([url for url in network.requests if "/search" in url]) == 3, network.requests
    saved = sorted(path.name for path in (tmp_path / "answers").glob("search_track_*.json"))
    assert saved == sorted(f"{search_name(f'فيروز {title}')}.json" for title in ("كيفك إنت", "حبيبي", "سألوني الناس"))
    assert "requests: asked 3" in "".join(printed)


def test_a_run_that_ends_by_itself_says_nothing_of_stopping(library: Database, tmp_path: Path) -> None:
    printed: list[str] = []
    main(["--db", str(tmp_path / "data" / "encore.db"), "--answers", str(answers_folder(tmp_path))], out=printed.append)
    assert "STOPPED EARLY" not in "".join(printed)


def test_the_flags_kept_only_limit_and_music_root_reach_the_selection(library: Database, tmp_path: Path) -> None:
    kept = tmp_path / "music" / "Encore" / "LANDMVRKS" / "Singles" / "Requiem.opus"
    kept.parent.mkdir(parents=True)
    with wave.open(str(kept), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * 12_000)
    base = ["--db", str(tmp_path / "data" / "encore.db"), "--answers", str(answers_folder(tmp_path))]
    texts: dict[str, list[str]] = {name: [] for name in ("plain", "kept_only", "limit", "root")}
    for name, extra in (
        ("plain", []),
        ("kept_only", ["--kept-only"]),
        ("limit", ["--limit", "2"]),
        ("root", ["--music-root", str(tmp_path / "music")]),
    ):
        assert main([*base, *extra], out=texts[name].append) == 0
    got = {name: "".join(parts) for name, parts in texts.items()}
    assert "9 songs through" in got["plain"] and "8 songs through" in got["kept_only"] and "2 songs through" in got["limit"]
    assert re.search(r"1\s+file\n", got["root"]) and "NO row used a file's length" not in got["root"], (
        "one kept file was read: the histogram can say so"
    )
    assert "NO row used a file's length" in got["plain"]


def test_the_catalogue_is_asked_for_an_album_as_background_work_with_the_runs_own_deadline(
    library: Database, tmp_path: Path
) -> None:
    seen: list[dict[str, Any]] = []
    with opened(answers_folder(tmp_path), live=False, max_requests=None) as source:
        real = source.catalogue.client.get

        def get(path: str, params: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
            seen.append({"path": path, **kw})
            return real(path, params, **kw)

        source.catalogue.client.get = get  # type: ignore[method-assign]
        source.album("12114248")
    assert [call["path"] for call in seen] == ["/album/12114248", "/album/12114248/tracks"]
    assert {call["priority"] for call in seen} == {"background"}
    assert seen[0]["wait_s"] == album_dryrun.ALBUM_DEADLINE_S and 0 < seen[1]["wait_s"] <= album_dryrun.ALBUM_DEADLINE_S


class FakeTime:
    """A clock the test owns: `sleep` moves it. A gate that paces its requests "waits" without the test waiting, and a gate that does not pace never sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_a_live_run_is_paced_by_the_servers_gate_and_a_replay_is_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate keeps 0.25 s between background requests (about 4 a second): a live run of 1,500 requests is 5 to 8 minutes and never a burst. A replay
    asks nobody and is not slowed down. Asserted on the WORK the gate does (the pauses it asks for, on a clock the test owns), not on the seconds a machine takes:
    the first version said "under 0.5 s" and "at least 0.45 s", which a loaded machine can break."""
    fake = FakeTime()
    gate = album_dryrun.Gate
    monkeypatch.setattr(album_dryrun, "Gate", lambda **kw: gate(**kw, clock=fake.clock, sleep=fake.sleep))
    with opened(answers_folder(tmp_path), live=False, max_requests=None) as replay:
        for _ in range(4):
            replay.search("LANDMVRKS", "Requiem")
    assert (replay.transport.replayed, replay.transport.asked) == (4, 0), "four answers served from the folder, nobody asked"
    assert fake.slept == [] and fake.now == 1000.0, "a replay does not pause: not one request waited for a token or a gap"
    with opened(tmp_path / "live", live=True, max_requests=10, network=FakeNetwork()) as live:
        for query in ("one", "two", "three"):
            live.search("Artist", query)
    assert (live.transport.asked, live.transport.replayed) == (3, 0)
    assert fake.slept == [0.25, 0.25], (
        "three background requests: the gap of 0.25 s before the second and before the third, and nothing else"
    )


def test_a_run_whose_last_song_met_the_rest_is_not_called_early(library: Database, tmp_path: Path) -> None:
    printed: list[str] = []
    argv = [
        "--db",
        str(tmp_path / "data" / "encore.db"),
        "--answers",
        str(tmp_path / "answers"),
        "--live",
        "--max-requests",
        "50",
        "--limit",
        "1",
    ]
    main(argv, out=printed.append, network=Quota())
    assert "STOPPED EARLY" not in "".join(printed) and re.search(r"1 songs? through the matcher", "".join(printed))


def test_the_preferred_kept_file_is_the_one_whose_length_is_read(library: Database, tmp_path: Path) -> None:
    """Requiem has two kept files: the preferred one (1.5 s) and a later, unpreferred copy (3 s)."""
    root = tmp_path / "music"
    for name, frames in (("Requiem.opus", 12_000), ("Requiem copy.opus", 24_000)):
        path = root / "Encore" / "LANDMVRKS" / "Singles" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(8000)
            out.writeframes(b"\x00\x00" * frames)
    with library.tx() as conn:
        ref = conn.execute("SELECT id FROM song_ref WHERE title = 'Requiem'").fetchone()[0]
        conn.execute(
            "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, source, preferred, added_at) VALUES ('sf_copy', ?, 'nd_copy', ?, 'opus', 'youtube', 0, 2)",
            (ref, "Encore/LANDMVRKS/Singles/Requiem copy.opus"),
        )
    with open_copy(library) as conn:
        requiem = next(e for e in entries(conn, music_root=root) if e.song.title == "Requiem")
    assert (requiem.song.length_ms, requiem.length_from) == (1_500, "file")


def test_a_request_the_tool_never_saves_is_not_made_live_either(tmp_path: Path) -> None:
    network = FakeNetwork()
    transport = AnswerTransport(tmp_path / "answers", live=network, max_requests=10)
    assert ask(transport, "/chart/0/tracks", limit=25).status_code == 400
    assert network.requests == [] and transport.asked == 0 and transport.not_recorded == ["/chart/0/tracks"]


def test_an_error_answer_is_never_saved_as_a_recording(tmp_path: Path) -> None:
    class Throttled(FakeNetwork):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}}, request=request
            )

    folder = tmp_path / "answers"
    assert ask(AnswerTransport(folder, live=Throttled(), max_requests=5), "/album/12114248").status_code == 200
    assert not folder.exists() or list(folder.iterdir()) == []


def test_the_database_is_opened_read_only_and_only_once() -> None:
    """The one place the module opens a database says `mode=ro`: a write through that connection fails, whatever the code above it does."""
    source = Path(album_dryrun.__file__).read_text(encoding="utf-8")
    assert source.count("sqlite3.connect(") == 1 and 'mode=ro", uri=True' in source


def test_a_connection_opened_the_way_the_command_opens_it_cannot_write(library: Database) -> None:
    with open_copy(library) as conn, pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("UPDATE song_ref SET album = 'x'")
