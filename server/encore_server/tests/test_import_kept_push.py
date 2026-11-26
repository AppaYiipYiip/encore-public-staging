"""N-43 (server half): the server tells the phone when a song of an import is STORED, not only when one is matched or the import is stopped.

Before, `kept` moved silently after the matching, so a phone had to ask `GET imports` every 10 seconds for as long as an import was saving (up to 30 minutes per app
launch, on every stranger's phone). The push is `import.progress`, the very event the matching already sends (docs/17 section 4), and the server says it does so in
`info.features` (`import-kept`), so that an app can stop asking only when it is talking to a server that pushes: strangers' servers are on every older image.

What drives it: the same world the keep watch reads (the feed of file changes, which the keeper AND the Host's library scan write to), only for people who are
connected, only for imports that are still moving, and a push only when the numbers the phone shows differ from the last it was told."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server import refs
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.imports.watch import ImportWatch
from encore_server.live import Connection
from tests.conftest import FakeVerifier, creds
from tests.test_imports import Rig
from tests.test_imports import rig as imports_rig  # noqa: F401  (the fixture, under another name: a test's own parameter is called `rig`)

V1 = "/encore/api/v1"
SHAPE = {"type", "importId", "state", "total", "matched", "unmatched", "pending", "kept"}


@pytest.fixture()
def rig(imports_rig: Rig) -> Rig:  # noqa: F811 - the imported fixture, taken under its other name
    return imports_rig


def person_of(rig: Rig, import_id: str) -> str:
    with rig.svc.db.read() as conn:
        return str(conn.execute("SELECT person FROM import WHERE id = ?", (import_id,)).fetchone()["person"])


def connect(rig: Rig, person: str) -> Connection:
    """A phone that is listening. (The hub is given the connection directly: a real socket needs the event loop of the test client, and what is tested is who is asked.)"""
    connection = Connection(person, "phone")
    with rig.svc.hub._lock:
        rig.svc.hub._connections.setdefault(person, set()).add(connection)
    return connection


def watch_of(rig: Rig) -> ImportWatch:
    assert rig.svc.import_watch is not None
    return rig.svc.import_watch  # type: ignore[no-any-return]


def pushed_by(rig: Rig, watch: ImportWatch) -> list[dict[str, Any]]:
    """What ONE tick of the watch told, apart from what the matching told on its own."""
    before = len(rig.events)
    watch.tick()
    return [event for _, event in rig.events[before:] if event["type"] == "import.progress"]


def match_everything(rig: Rig) -> None:
    """Runs the look-ups (the matching tells its own numbers) and leaves the keeping undone."""
    scheduler = rig.svc.scheduler
    while True:
        item = scheduler._claim("background")
        if item is None:
            return
        if item.kind == "match":
            scheduler._run(item)
        else:
            with rig.svc.db.tx() as conn:  # put the keep back as it was: the test keeps one song at a time
                conn.execute("UPDATE work_item SET state = 'queued' WHERE id = ?", (item.id,))
            return


def test_a_tick_after_each_stored_song_pushes_kept_one_up_at_a_time(rig: Rig) -> None:
    made = rig.imported()
    import_id = made["import"]["id"]
    connect(rig, person_of(rig, import_id))
    watch = watch_of(rig)
    scheduler = rig.svc.scheduler
    kept_pushed: list[int] = []
    for _ in range(200):
        if not scheduler.run_one("background"):
            break
        kept_pushed += [e["kept"] for e in pushed_by(rig, watch) if e["importId"] == import_id]

    assert rig.get("marwa", f"/imports/{import_id}")["import"]["kept"] == 5
    assert kept_pushed == sorted(set(kept_pushed)), "no number is pushed twice"
    assert set(range(1, 6)) <= set(kept_pushed), kept_pushed


def test_the_push_is_the_event_the_matching_sends(rig: Rig) -> None:
    import_id = rig.imported()["import"]["id"]
    connect(rig, person_of(rig, import_id))
    watch = watch_of(rig)
    rig.drain()

    pushed = pushed_by(rig, watch)

    assert pushed and pushed[-1]["kept"] == 5 and pushed[-1]["state"] == "done" and pushed[-1]["importId"] == import_id
    assert all(set(e) == SHAPE for e in pushed)


def test_a_song_the_library_scan_attaches_is_pushed_too(rig: Rig) -> None:
    """The Host's own scan finds a file for a song of the import (the same row the keeper writes): `kept` moves without the keeper."""
    made = rig.imported()
    import_id = made["import"]["id"]
    connect(rig, person_of(rig, import_id))
    watch = watch_of(rig)
    match_everything(rig)
    pushed_by(rig, watch)  # whatever the matching left unsaid is said now

    with rig.svc.db.tx() as conn:
        refs.attach_file(
            conn, made["refs"][0]["id"], navidrome_song_id="nd-1", path="Artist/Album/Song 1.mp3", codec="mp3", bitrate_kbps=320
        )
    pushed = pushed_by(rig, watch)

    assert [(e["importId"], e["kept"]) for e in pushed] == [(import_id, 1)]
    assert set(pushed[0]) == SHAPE


def test_nothing_moved_nothing_pushed(rig: Rig) -> None:
    made = rig.imported()
    connect(rig, person_of(rig, made["import"]["id"]))
    watch = watch_of(rig)
    match_everything(rig)
    pushed_by(rig, watch)

    assert pushed_by(rig, watch) == []
    assert pushed_by(rig, watch) == []


def test_nothing_is_recounted_while_the_world_stands_still(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    made = rig.imported()
    connect(rig, person_of(rig, made["import"]["id"]))
    watch = watch_of(rig)
    match_everything(rig)
    pushed_by(rig, watch)
    asked: list[str] = []
    real = rig.svc.imports.following
    monkeypatch.setattr(rig.svc.imports, "following", lambda person, **kw: asked.append(person) or real(person, **kw))

    pushed_by(rig, watch)
    pushed_by(rig, watch)

    assert asked == []


def test_a_move_of_the_feed_that_changes_no_number_says_nothing(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The feed also moves for songs that are in no import: the watch recounts, finds the same numbers, and the phone is left alone."""
    made = rig.imported()
    connect(rig, person_of(rig, made["import"]["id"]))
    watch = watch_of(rig)
    match_everything(rig)
    pushed_by(rig, watch)
    asked: list[str] = []
    real = rig.svc.imports.following
    monkeypatch.setattr(rig.svc.imports, "following", lambda person, **kw: asked.append(person) or real(person, **kw))

    with rig.svc.db.tx() as conn:
        refs.touch_file(conn, made["refs"][0]["id"])  # a row in the feed, no file attached: `kept` is what it was

    assert pushed_by(rig, watch) == []
    assert asked, "the feed moved, so the watch did look"


def test_nobody_connected_no_push_and_no_work(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    made = rig.imported()
    watch = watch_of(rig)
    match_everything(rig)
    asked: list[str] = []
    monkeypatch.setattr(rig.svc.imports, "following", lambda person, **kw: asked.append(person) or [])

    with rig.svc.db.tx() as conn:
        refs.attach_file(
            conn, made["refs"][0]["id"], navidrome_song_id="nd-1", path="Artist/Album/Song 1.mp3", codec="mp3", bitrate_kbps=320
        )

    assert pushed_by(rig, watch) == [] and asked == []


def test_an_import_that_is_over_is_not_followed_any_more(rig: Rig) -> None:
    made = rig.imported()
    import_id = made["import"]["id"]
    person = person_of(rig, import_id)
    connect(rig, person)
    watch = watch_of(rig)
    rig.drain()
    pushed_by(rig, watch)  # the last number is told: the import is done and every matched song is kept

    assert rig.svc.imports.following(person) == []
    with rig.svc.db.tx() as conn:  # something else moves the feed of file changes
        refs.touch_file(conn, made["refs"][0]["id"])
    assert pushed_by(rig, watch) == []


def test_the_server_says_in_its_features_that_it_pushes_kept(rig: Rig, tmp_path: Path, verifier: FakeVerifier) -> None:
    assert "import-kept" in set(rig.client.get(f"{V1}/info").json()["features"])

    settings = Settings(
        data_dir=tmp_path / "bare", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as bare:
        assert "import-kept" not in set(bare.get(f"{V1}/info").json()["features"])
        assert bare.get(f"{V1}/info", params=creds("marwa")).status_code == 200
