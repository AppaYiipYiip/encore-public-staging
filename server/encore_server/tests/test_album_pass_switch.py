"""N-34, the first live pass on a real server (25 Nov 2026): RULE 3, the Host's OFF SWITCH of the album pass, and RULE 4, the revision.

`ENCORE_ALBUM_PASS` (default on) is read like the other Host switches (`ENCORE_CATALOGUE`, `ENCORE_YOUTUBE`, `ENCORE_KEEP`: `0`, `false` or `no` is off). **Off, neither the hourly pass nor the keeper's
question about a NEW keep asks the catalogue which album a song is on, and nothing is stamped**: the keeper files as it always did (Singles, no album), no identity column is written, the
server says so once in its log. It is NOT `ENCORE_CATALOGUE=0`, which also stops the pictures and the whole catalogue: a Host who wants pictures and no album stamps has this one.
**Why it exists:** a stamp is permanent and reaches the Host's disk through a later keep; a server the project cannot read first (a stranger's) needs a way to say "not on my library".

The revision (`album_finder.IDENTITY_REVISION`, 5 here) is what makes every `none` of an older rule asked again by the retry rule; `matched` songs are never asked.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server import album_finder, album_pass, deezer
from encore_server.api import create_app
from encore_server.catalogue import Cache
from encore_server.catalogue import Catalogue as RealCatalogue
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.deezer import DeezerClient, Gate
from encore_server.navidrome import NavidromeClient
from encore_server.navidrome_admin import NavidromeAdmin
from tests.catalogue_fakes import RecordedDeezer
from tests.conftest import FakeVerifier, creds, resolve
from tests.test_album_pass import DAY_MS, NOW, Catalogue, finder, landmvrks, make_ref, pdb, row_of  # noqa: F401 - `pdb` is a fixture
from tests.test_keeper import FakeNavidrome, FakeSource, fake_ffmpeg
from tests.test_keeper_new_keeps import FILE_LENGTH_MS

COMPOSE = Path(__file__).resolve().parents[1] / "deploy" / "compose.yaml"


# ------------------------------------------------------------------------------------------------------------------ the setting


@pytest.mark.parametrize(
    ("value", "on"),
    [("", True), ("1", True), ("true", True), ("yes", True), ("0", False), ("false", False), ("No", False), (" 0 ", False)],
)
def test_the_switch_is_read_like_the_other_host_switches(value: str, on: bool) -> None:
    assert Settings.from_env({"ENCORE_ALBUM_PASS": value}).album_pass is on
    for other in ("ENCORE_CATALOGUE", "ENCORE_KEEP"):
        assert getattr(Settings.from_env({other: value}), "catalogue" if other == "ENCORE_CATALOGUE" else "keep") is on, (
            "the convention this one follows"
        )


def test_the_default_is_on_and_the_switch_is_independent_of_the_catalogue_switch() -> None:
    assert Settings().album_pass is True and Settings.from_env({}).album_pass is True
    assert Settings.from_env({"ENCORE_ALBUM_PASS": "0"}).catalogue is True, "pictures and the catalogue's pages go on"
    assert Settings.from_env({"ENCORE_CATALOGUE": "0"}).album_pass is True, (
        "the switch of the catalogue says nothing about this one: the pass stops at a catalogue that is off"
    )


def test_the_compose_file_passes_the_switch_into_the_container() -> None:
    """Without this a Host's `.env` value never reaches the server: every other switch is passed the same way."""
    text = COMPOSE.read_text(encoding="utf-8")
    assert "ENCORE_ALBUM_PASS: ${ENCORE_ALBUM_PASS:-1}" in text
    assert "ENCORE_CATALOGUE: ${ENCORE_CATALOGUE:-1}" in text


# ------------------------------------------------------------------------------------------------------------------ the app: off, nothing is asked and nothing is stamped


def make_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, album_pass: bool, upstream: RecordedDeezer, calls: list[str]
) -> Any:
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
        album_pass=album_pass,
    )
    client = NavidromeClient(
        "http://music.invalid", "admin", "pw", client=httpx.Client(transport=httpx.MockTransport(music_server))
    )
    catalogue = RealCatalogue(
        DeezerClient(Gate(rate=1000, burst=1000, background_gap_s=0.0), httpx.Client(transport=upstream.transport())), Cache(None)
    )
    return create_app(
        settings, navidrome=client, navidrome_admin=NavidromeAdmin("http://music.invalid", "", ""), catalogue=catalogue
    )


def test_with_the_switch_off_the_library_link_asks_no_album_and_stamps_nothing_and_the_cover_finder_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream, calls = RecordedDeezer(), []
    app = make_app(tmp_path, monkeypatch, album_pass=False, upstream=upstream, calls=calls)
    services = app.state.services
    placed = make_ref(services.db, "Comfortably Numb", "Pink Floyd", 382_000)
    before = row_of(services.db, placed)
    assert services.linker is not None

    services.linker.run_once()

    assert not any(call.startswith("album pass") for call in calls), calls
    assert "cover finder: Comfortably Numb" in calls, "the pictures are the catalogue's, not this switch's"
    assert not any(path.startswith("/album/") for path in upstream.paths()), "no album question reached the catalogue"
    after = row_of(services.db, placed)
    stamped = (
        "album",
        "track_no",
        "disc_no",
        "year",
        "deezer_id",
        "isrc",
        "identity_tried_at",
        "identity_rev",
        "identity_outcome",
        "identity_reason",
    )
    assert {k: after[k] for k in stamped} == {k: before[k] for k in stamped}, (
        "nothing is stamped and no identity column is written (the cover finder's own note, cover_tried_at, is its own)"
    )


def test_with_the_switch_on_the_same_app_asks_and_stamps_the_control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other side of the test above: the same app and song with the switch on (the default) IS placed, so the first test proves the switch and not a broken setup."""
    upstream, calls = RecordedDeezer(), []
    app = make_app(tmp_path, monkeypatch, album_pass=True, upstream=upstream, calls=calls)
    services = app.state.services
    placed = make_ref(services.db, "Comfortably Numb", "Pink Floyd", 382_000)
    assert services.linker is not None

    services.linker.run_once()

    assert "album pass: Comfortably Numb" in calls
    assert row_of(services.db, placed)["identity_outcome"] == "matched"


def test_with_the_switch_off_the_keeper_has_no_album_question_and_files_the_song_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Configured(FakeNavidrome):
        configured = True

    music = tmp_path / "music"
    music.mkdir()
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=music,
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        workers=False,
        min_free_gb=0.0,
        album_pass=False,
    )
    monkeypatch.setattr("encore_server.keeper.keeper.run_command", fake_ffmpeg)
    monkeypatch.setattr("encore_server.keeper.keeper.fetch_cover", lambda url: b"cover-bytes")
    upstream = RecordedDeezer()
    catalogue = RealCatalogue(
        DeezerClient(Gate(rate=1000, burst=1000, background_gap_s=0.0), httpx.Client(transport=upstream.transport())), Cache(None)
    )
    app = create_app(settings, verifier=FakeVerifier(), youtube=FakeSource(), navidrome=Configured(music), catalogue=catalogue)  # type: ignore[arg-type]
    with TestClient(app) as client:
        service = client.app.state.services  # type: ignore[attr-defined]
        item = {"title": "Creature", "artists": ["LANDMVRKS"], "durationMs": FILE_LENGTH_MS}
        ref = str(resolve(client, "marwa", item)[0]["id"])
        assert client.put(f"/encore/api/v1/likes/{ref}", params=creds("marwa")).status_code == 200
        service.scheduler.drain()
        with service.db.read() as conn:
            row = conn.execute("SELECT album, deezer_id, identity_outcome FROM song_ref WHERE id = ?", (ref,)).fetchone()

    kept = sorted(p.relative_to(music).as_posix() for p in (music / "Encore").rglob("*.opus"))
    assert kept == ["Encore/LANDMVRKS/Singles/Creature.opus"], kept
    assert not any(path.startswith("/album/") for path in upstream.paths()), "the keeper asked no album question"
    assert row["deezer_id"] is None and row["identity_outcome"] is None


def test_the_server_says_once_in_its_log_that_the_pass_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        make_app(tmp_path, monkeypatch, album_pass=False, upstream=RecordedDeezer(), calls=[])
    lines = [r.getMessage() for r in caplog.records if "album pass" in r.getMessage().lower() and "off" in r.getMessage().lower()]
    assert len(lines) == 1 and "ENCORE_ALBUM_PASS" in lines[0], lines


def test_the_server_says_nothing_about_the_pass_when_it_is_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        make_app(tmp_path, monkeypatch, album_pass=True, upstream=RecordedDeezer(), calls=[])
    assert not [r for r in caplog.records if "ENCORE_ALBUM_PASS" in r.getMessage()]


# ------------------------------------------------------------------------------------------------------------------ the revision: every none of an older rule is asked again


def remembered(pdb: Database, ref: str, outcome: str, reason: str, revision: int, tried: int) -> None:  # noqa: F811
    with pdb.tx() as conn:
        conn.execute(
            "UPDATE song_ref SET identity_outcome = ?, identity_reason = ?, identity_rev = ?, identity_tried_at = ? WHERE id = ?",
            (outcome, reason, revision, tried, ref),
        )


def test_a_none_of_the_old_revision_is_asked_again_at_once_and_one_of_this_revision_is_not(pdb: Database) -> None:  # noqa: F811
    old = make_ref(pdb, "Creature", "LANDMVRKS", 225_000)
    current = make_ref(pdb, "Requiem", "LANDMVRKS", 240_000)
    remembered(pdb, old, "none", "no_same_recording", album_finder.IDENTITY_REVISION - 1, NOW - DAY_MS)
    remembered(pdb, current, "none", "sole_album", album_finder.IDENTITY_REVISION, NOW - DAY_MS)
    catalogue = landmvrks()

    finder(pdb, catalogue).run_once()

    assert catalogue.searched == [("LANDMVRKS", "Creature")], "a day old, so only the old revision's answer is asked again"
    assert row_of(pdb, old)["identity_rev"] == album_finder.IDENTITY_REVISION
    assert row_of(pdb, current)["identity_reason"] == "sole_album" and row_of(pdb, current)["identity_tried_at"] == NOW - DAY_MS


def test_a_matched_song_of_an_older_revision_is_never_asked_again(pdb: Database) -> None:  # noqa: F811
    """Revision 4 DID stamp on one real server (35 songs, 5 wrong): `matched` songs hold their ids, and no rule asks them again. Those stamps are undone by hand (the lead's script)."""
    ref = make_ref(pdb, "Creature", "LANDMVRKS", 225_000, album="Wonderful", deezer_id="3116792061")
    remembered(pdb, ref, "matched", "matched", album_finder.IDENTITY_REVISION - 1, NOW - 30 * DAY_MS)
    catalogue = landmvrks()

    finder(pdb, catalogue).run_once()

    assert catalogue.searched == [] and row_of(pdb, ref)["album"] == "Wonderful"


def test_the_album_pass_module_still_exists_for_the_dry_run_whatever_the_switch_says() -> None:
    """The switch turns off the ERRAND and the keeper's question, not the code: `python -m encore_server.album_dryrun` reads a copy of a server's database whatever its settings say."""
    assert hasattr(album_pass, "AlbumFinder") and hasattr(album_pass, "KeepAsker")
