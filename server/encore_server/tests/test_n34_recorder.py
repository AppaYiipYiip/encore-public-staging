"""N-34 slice 1, step 0: the recording tool asks Deezer at most ten times in all, and says so in a file (`tools/record_catalogue_fixtures.py n34 ...`).

The lead's leave for the step is "at most 10 paced requests, to Deezer only". A count kept in somebody's head is not a limit, so the tool keeps it in
`tests/fixtures/deezer/n34_requests.json`: every attempt is written BEFORE the connection is made (a failure counts and is never retried), and the 11th is
refused. These tests run the tool with its one outside function replaced; no test here asks anybody anything (the suite's network guard would fail it).
"""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from encore_server import catalogue, deezer

TOOL = Path(__file__).resolve().parents[3] / "tools" / "record_catalogue_fixtures.py"
LEDGER = Path(__file__).resolve().parent / "fixtures" / "deezer" / "n34_requests.json"


@pytest.fixture()
def tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_catalogue_fixtures_under_test", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Asked:
    """Stands in for the tool's one outside function: remembers what was asked, answers a recorded-looking body, can be told to fail."""

    def __init__(self, fail_on: tuple[int, ...] = ()) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_on = fail_on

    def __call__(self, path: str, **params: Any) -> dict[str, Any]:
        self.calls.append((path, params))
        if len(self.calls) in self.fail_on:
            raise TimeoutError("the network did not answer")
        return {"data": [{"id": 1, "title": "x", "preview": "https://cdn.example/p?hdnea=SECRET", "share": "https://example/s"}]}


def run(tool: ModuleType, tmp_path: Path, asked: Asked, *argv: str) -> int:
    tool.get = asked
    return int(tool.n34_main(list(argv), out=tmp_path))


def test_the_eleventh_attempt_is_refused_and_nothing_is_asked(tool: ModuleType, tmp_path: Path) -> None:
    asked = Asked()
    for ident in range(1, 11):
        assert run(tool, tmp_path, asked, "album", str(ident)) == 0
    assert len(asked.calls) == 10
    assert run(tool, tmp_path, asked, "album", "11") == 2
    assert len(asked.calls) == 10, "the 11th went out"
    assert len(json.loads((tmp_path / "n34_requests.json").read_text(encoding="utf-8"))["attempts"]) == 10


def test_the_ledger_itself_refuses_the_eleventh_even_when_the_command_line_check_is_stepped_around(
    tool: ModuleType, tmp_path: Path
) -> None:
    """Two layers: the command line refuses a batch that does not fit, and the ledger refuses the attempt (a function that is called directly, or a
    later change to the command line, cannot go over)."""
    tool.get = asked = Asked()
    ledger = tool.Ledger(tmp_path / "n34_requests.json")
    for ident in range(10):
        tool.n34_ask(ledger, f"/album/{ident}")
    with pytest.raises(tool.CapSpent):
        tool.n34_ask(ledger, "/album/10")
    assert len(asked.calls) == 10
    assert len(tool.Ledger(tmp_path / "n34_requests.json").attempts) == 10, "the count survives a new run of the tool"


def test_a_failed_attempt_counts_and_is_not_retried(tool: ModuleType, tmp_path: Path) -> None:
    asked = Asked(fail_on=(1,))
    with pytest.raises(TimeoutError):
        run(tool, tmp_path, asked, "album", "1")
    attempts = json.loads((tmp_path / "n34_requests.json").read_text(encoding="utf-8"))["attempts"]
    assert len(asked.calls) == 1 and [a["outcome"] for a in attempts] == ["failed: TimeoutError"]
    for ident in range(2, 11):  # nine more fit; the failed one used a place
        assert run(tool, tmp_path, Asked(), "album", str(ident)) == 0
    assert run(tool, tmp_path, Asked(), "album", "99") == 2


def test_the_attempt_is_in_the_ledger_before_the_connection_is_made(tool: ModuleType, tmp_path: Path) -> None:
    seen: list[str] = []

    def killed_half_way(path: str, **params: Any) -> dict[str, Any]:
        seen.append(json.loads((tmp_path / "n34_requests.json").read_text(encoding="utf-8"))["attempts"][-1]["outcome"])
        raise KeyboardInterrupt

    tool.get = killed_half_way
    with pytest.raises(KeyboardInterrupt):
        tool.n34_main(["album", "5"], out=tmp_path)
    assert seen == ["started"], "an attempt must be counted even when the process is killed while it is in flight"
    assert len(json.loads((tmp_path / "n34_requests.json").read_text(encoding="utf-8"))["attempts"]) == 1


def test_a_batch_larger_than_what_is_left_is_refused_whole(tool: ModuleType, tmp_path: Path) -> None:
    asked = Asked()
    assert run(tool, tmp_path, asked, "album", *[str(i) for i in range(1, 9)]) == 0
    assert run(tool, tmp_path, asked, "album", "20", "21", "22") == 2
    assert len(asked.calls) == 8, "a refused batch asked nothing, not even its first member"


def test_count_asks_nothing_and_an_id_that_is_not_a_number_is_refused(tool: ModuleType, tmp_path: Path) -> None:
    asked = Asked()
    assert run(tool, tmp_path, asked, "count") == 0
    assert run(tool, tmp_path, asked, "album", "../artist/1") == 2
    assert asked.calls == []


def test_what_is_asked_is_what_the_servers_own_calls_ask(tool: ModuleType, tmp_path: Path) -> None:
    """The recording must be of the REQUEST the server sends, or the fake that serves it answers a question nobody asks."""
    asked = Asked()
    assert run(tool, tmp_path, asked, "search", "LANDMVRKS Requiem") == 0
    assert run(tool, tmp_path, asked, "album", "7") == 0
    assert run(tool, tmp_path, asked, "tracks", "7") == 0
    assert run(tool, tmp_path, asked, "artist-albums", "9") == 0
    sent_limit = inspect.signature(deezer.search_tracks).parameters["limit"].default
    assert asked.calls == [
        ("/search", {"q": "LANDMVRKS Requiem", "limit": sent_limit}),
        ("/album/7", {}),
        ("/album/7/tracks", {"limit": catalogue.ALBUM_TRACKS_LIMIT}),
        ("/artist/9/albums", {"limit": catalogue.RELEASES_LIMIT}),
    ]
    assert sorted(p.name for p in tmp_path.glob("*.json")) == [
        "album_7.json",
        "album_7_tracks.json",
        "artist_albums_9.json",
        "n34_requests.json",
        "search_track_landmvrks_requiem.json",
    ]


def test_a_recording_has_the_layout_of_the_others_and_no_signed_address(tool: ModuleType, tmp_path: Path) -> None:
    assert run(tool, tmp_path, Asked(), "search", "LANDMVRKS Creature") == 0
    body = json.loads((tmp_path / "search_track_landmvrks_creature.json").read_text(encoding="utf-8"))
    assert sorted(body) == ["answer", "params", "path", "recorded"]
    text = (tmp_path / "search_track_landmvrks_creature.json").read_text(encoding="utf-8")
    assert "SECRET" not in text and "share" not in text and "preview" not in text


def test_the_ledger_that_is_committed_holds_no_more_than_the_leave_and_only_deezer_paths() -> None:
    """The count of the real recording, as the file says it (the step is done once; the file stays as the evidence)."""
    if not LEDGER.exists():
        pytest.skip("the step-0 recording has not been made yet")
    body = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert len(body["attempts"]) <= body["cap"] <= 10
    for attempt in body["attempts"]:
        assert attempt["path"].startswith(("/search", "/album/", "/artist/")), attempt
        assert attempt["outcome"] in ("ok",) or attempt["outcome"].startswith("failed"), attempt
