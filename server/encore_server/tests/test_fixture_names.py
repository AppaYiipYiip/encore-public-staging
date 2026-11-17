"""N-34 slice 1 (cleanup after P2-25): the ONE name of a recorded catalogue answer (`encore_server/fixture_names.py`).

The defect this closes, found by the independent review of the dry run: `album_dryrun` and `tools/record_catalogue_fixtures.py` each named a recorded search by the
Latin letters of its query, so EVERY query without a Latin letter was called `search_track_`, and a `--live` dry run over an Arabic library saved the first answer under
that name and replayed it to every later Arabic song (a report built on it would have been the first song's catalogue answer repeated 400 times, with no sign of it).
Before P2-25 such a song was never asked (its name did not survive the fold); since P2-25 slices 2 and 3 it is asked.

What is pinned: the name is a function of the FULL query (no two different queries share one), it is the one function everywhere (the dry run, the recorder, the tests'
catalogue fake: never a copy), and every answer already tracked still resolves (the 10 real answers of step 0 and the ledger that counts them: nothing is re-recorded,
nothing is asked).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from encore_server import album_dryrun, fixture_names
from encore_server.album_dryrun import AnswerTransport
from encore_server.fixture_names import READABLE_LETTERS, fixture_name, search_name
from tests import catalogue_fakes
from tests.catalogue_fakes import RECORDED

LEDGER = RECORDED / "n34_requests.json"
ARABIC = ["فيروز كيفك إنت", "فيروز حبيبي", "فيروز سألوني الناس"]


def test_queries_with_no_latin_letter_are_different_files() -> None:
    """The bug itself: these were all `search_track_`."""
    queries = [
        *ARABIC,
        "Кино Группа крови",
        "Кино Звезда по имени Солнце",
        "YOASOBI 夜に駆ける",
        "YOASOBI アイドル",
        "방탄소년단 봄날",
        "🎵",
    ]
    names = [fixture_name("/search", {"q": query}) for query in queries]
    assert None not in names and len(set(names)) == len(queries), names
    assert "search_track_" not in names and all(name != "search_track_" for name in names)


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("(Hello) !", "Hello"),
        ("Hello?", "Hello!"),
        ("AC/DC Back In Black", "AC DC Back In Black"),
        ("LANDMVRKS Requiem", "landmvrks requiem"),
        ("Beyoncé Halo", "Beyonce Halo"),
        ("فيروز كيفك إنت", "فيروز كيفك إنتَ"),
        ("a  b", "a b"),
    ],
)
def test_queries_that_differ_only_in_punctuation_case_accents_or_a_vowel_mark_are_different_files(one: str, other: str) -> None:
    """The old name was lower case, Latin letters and digits only: each of these pairs was ONE file. The query is hashed exactly as it is sent: a replay that
    misses says "not recorded"; one that answers with another query's answer says nothing."""
    assert fixture_name("/search", {"q": one}) != fixture_name("/search", {"q": other})


def test_the_names_of_the_tracked_recordings_are_pinned_so_a_change_of_the_rule_is_a_decision() -> None:
    assert search_name("LANDMVRKS Requiem") == "search_track_landmvrks_requiem_089cbcc2aeabd7da"
    assert search_name("LANDMVRKS Creature") == "search_track_landmvrks_creature_4784c2a08b472e71"
    assert search_name("فيروز حبيبي") == "search_track_2692aa718440c199", "no Latin letter: the hash alone"
    assert search_name("Pink Floyd Comfortably Numb") == "search_track_pink_floyd_comfortably_numb_58537b8646d8983e"


@pytest.mark.parametrize(
    "query",
    ["x" * 2000, "../../etc/passwd", "a\\b\x00c", "فيروز " * 300, 'Song (feat. X) / Y: "Z" *?', " "],
)
def test_a_name_is_short_and_made_of_safe_characters_whatever_the_query(query: str) -> None:
    name = search_name(query)
    assert re.fullmatch(r"search_track_([a-z0-9_]+_)?[0-9a-f]{16}", name), name
    assert len(name) <= len("search_track_") + READABLE_LETTERS + 1 + 16 and search_name(query) == name


def test_a_query_that_is_not_valid_text_still_gets_a_name() -> None:
    """A lone surrogate cannot be encoded as UTF-8; naming must never be what stops a run."""
    assert re.fullmatch(r"search_track_([a-z0-9_]+_)?[0-9a-f]{16}", search_name("lone " + chr(0xD800)))


def test_other_requests_are_named_by_the_id_in_their_path_and_the_rest_are_not_saved() -> None:
    assert fixture_name("/album/12114248", {}) == "album_12114248"
    assert fixture_name("/album/12114248/tracks", {"limit": 100}) == "album_12114248_tracks"
    assert fixture_name("/artist/9985838/albums", {"limit": 200}) == "artist_albums_9985838"
    for path, params in (
        ("/search", {}),
        ("/search", {"q": ""}),
        ("/chart/0/tracks", {}),
        ("/album/abc", {}),
        ("/album/1/other", {}),
        ("/artist/1", {}),
    ):
        assert fixture_name(path, params) is None, (path, params)


def test_every_tracked_search_recording_is_named_by_its_own_query() -> None:
    """The recorder writes `{recorded, path, params, answer}`: a file's own path and params give its own name, so a replay finds what a recording made."""
    searches = sorted(RECORDED.glob("search_track_*.json"))
    assert len(searches) >= 2, "the two searches of step 0"
    for source in searches:
        body = json.loads(source.read_text(encoding="utf-8"))
        assert fixture_name(body["path"], body["params"]) == source.stem, source.name


def test_every_request_of_the_step_0_ledger_still_resolves_to_its_recording() -> None:
    """The ledger is the evidence of the ten requests that were spent. Re-recording is out of the question (the leave is spent and nothing here asks anybody), so
    every one of them must still find its file by the ONE rule: the 2 searches (renamed when the rule changed), the 4 albums, the 3 song lists, the 1 list of an
    artist's releases."""
    attempts = json.loads(LEDGER.read_text(encoding="utf-8"))["attempts"]
    assert len(attempts) == 10 and {a["outcome"] for a in attempts} == {"ok"}
    names = []
    for attempt in attempts:
        name = fixture_name(attempt["path"], attempt["params"])
        assert name is not None, attempt
        recording = RECORDED / f"{name}.json"
        assert recording.is_file(), f"{attempt['path']} {attempt['params']} has no recording {recording.name}"
        body = json.loads(recording.read_text(encoding="utf-8"))
        assert (body["path"], body["params"]) == (attempt["path"], attempt["params"]), "the file holds the answer to THIS request"
        names.append(name)
    assert len(set(names)) == 10, "ten requests, ten files"


def test_nothing_names_an_answer_but_the_one_function() -> None:
    """A copy of the rule is how the first version went wrong (two `_slug`s, one per tool). The dry run and the tests' fake use THE function; the recorder's own
    check is in `test_n34_recorder.py` (it imports the tool)."""
    assert album_dryrun.fixture_name is fixture_names.fixture_name
    assert catalogue_fakes.fixture_name is fixture_names.fixture_name
    for module in (album_dryrun, catalogue_fakes):
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        assert "[^a-z0-9]" not in source and "_slug" not in source and "def slug" not in source, module.__name__


class Echo(httpx.BaseTransport):
    """The real network of `--live`, replaced: answers every search with a body that names the query it was asked."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        query = request.url.params["q"]
        self.requests.append(query)
        return httpx.Response(200, json={"data": [{"id": len(self.requests), "title": query}]}, request=request)


def ask(transport: AnswerTransport, query: str) -> httpx.Response:
    return httpx.Client(transport=transport).get("https://api.deezer.com/search", params={"q": query, "limit": 8})


def test_a_live_run_over_arabic_songs_asks_for_each_and_replays_each_its_own_answer(tmp_path: Path) -> None:
    """The defect end to end: with an ASCII-only name the second Arabic query was answered from the first one's file (one request made, not three), and a later
    replay gave every song the first song's answer."""
    folder, network = tmp_path / "answers", Echo()
    live = AnswerTransport(folder, live=network, max_requests=10)
    for query in ARABIC:
        assert ask(live, query).json()["data"][0]["title"] == query
    assert (live.asked, live.replayed, network.requests) == (3, 0, ARABIC), "each is asked: none is answered from another's file"
    assert len(list(folder.iterdir())) == 3
    silent = Echo()
    replay = AnswerTransport(folder, live=silent, max_requests=10)
    for query in ARABIC:
        assert ask(replay, query).json()["data"][0]["title"] == query, "each song gets ITS answer"
    assert (replay.asked, replay.replayed, silent.requests) == (0, 3, [])


def test_a_query_nobody_recorded_is_not_answered_from_a_look_alike(tmp_path: Path) -> None:
    folder = tmp_path / "answers"
    ask(AnswerTransport(folder, live=Echo(), max_requests=5), "Hello")
    replay = AnswerTransport(folder)
    assert ask(replay, "Hello").status_code == 200
    assert ask(replay, "(Hello) !").status_code == 400, "not recorded: said so, not answered with Hello's answer"
    assert replay.not_recorded == [search_name("(Hello) !")]
