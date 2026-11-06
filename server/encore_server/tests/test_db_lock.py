"""Signing a request in is a READ (docs/tasks/AUDIT-BUILT-2026-11-05.md, B-10 and B-18).

The database is in WAL mode so that readers never wait for the writer. Signing in used to take the write lock on every request, and a new person's
first request asked the music server inside it, so one slow write (or one slow music server) stopped every phone for as long: with 20 phones busy
the 95th-percentile read took 2.5 s and the worst 12 s. These tests hold the write lock and check that the calls a phone makes all the time go on.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.auth import stream_secret
from encore_server.config import Settings
from encore_server.db import Database
from tests.conftest import FakeVerifier, creds, resolve, song

V1 = "/encore/api/v1"
HOLD_S = 2.0
QUICK_S = 0.8


class Held:
    """Somebody else is writing: the write lock is held for [HOLD_S] seconds (never longer, so a regression fails the test instead of hanging it)."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._release = threading.Event()
        self._started = threading.Event()
        self._thread = threading.Thread(target=self._hold, daemon=True)

    def _hold(self) -> None:
        with self._db.tx():
            self._started.set()
            self._release.wait(HOLD_S)

    def __enter__(self) -> Held:
        self._thread.start()
        assert self._started.wait(5)
        return self

    def __exit__(self, *_: object) -> None:
        self._release.set()
        self._thread.join()


def took(call: Any) -> tuple[Any, float]:
    started = time.perf_counter()
    answer = call()
    return answer, time.perf_counter() - started


class MusicServerWatcher(FakeVerifier):
    """A music server that, when asked whether somebody is an administrator, looks whether anybody could write to the database at that moment."""

    def __init__(self) -> None:
        super().__init__()
        self.db_path: Path | None = None
        self.write_lock_was_free: bool | None = None

    def is_admin(self, user: str, token: str, salt: str) -> bool:
        assert self.db_path is not None
        conn = sqlite3.connect(self.db_path, timeout=0.2, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
            self.write_lock_was_free = True
        except sqlite3.OperationalError:
            self.write_lock_was_free = False
        finally:
            conn.close()
        return super().is_admin(user, token, salt)


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[tuple[TestClient, MusicServerWatcher]]:
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "m",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        workers=False,
    )
    verifier = MusicServerWatcher()
    with TestClient(create_app(settings, verifier=verifier)) as client:
        verifier.db_path = client.app.state.services.db.path  # type: ignore[attr-defined]
        yield client, verifier


def device(client: TestClient, user: str = "marwa") -> dict[str, str]:
    login = client.post(f"{V1}/auth/login", json={"username": user, "password": f"pw-{user}", "deviceName": "phone"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['deviceToken']}"}


def database(client: TestClient) -> Database:
    return client.app.state.services.db  # type: ignore[attr-defined,no-any-return]


def test_a_phone_signed_in_with_its_device_is_not_held_up_by_a_writer(rig: tuple[TestClient, MusicServerWatcher]) -> None:
    client, _ = rig
    phone = device(client)

    with Held(database(client)):
        _, quiet = took(lambda: client.get(f"{V1}/library/changes", headers=phone, params={"since": "0"}))
        feed, seconds = took(lambda: client.get(f"{V1}/playlists", headers=phone))

    assert feed.status_code == 200 and seconds < QUICK_S, f"a plain read waited {seconds:.2f} s for a writer"
    assert quiet < QUICK_S


def test_a_phone_signed_in_with_the_music_server_login_is_not_held_up_either(rig: tuple[TestClient, MusicServerWatcher]) -> None:
    client, _ = rig
    client.get(f"{V1}/me", params=creds("marwa"))  # known from now on

    with Held(database(client)):
        answer, seconds = took(lambda: client.get(f"{V1}/playlists", params=creds("marwa")))

    assert answer.status_code == 200 and seconds < QUICK_S, f"a plain read waited {seconds:.2f} s for a writer"


def test_addresses_for_songs_and_pictures_are_made_without_the_write_lock(rig: tuple[TestClient, MusicServerWatcher]) -> None:
    """A screen asks for thirty pictures; each used to open a write transaction just to read the signing secret."""
    client, _ = rig
    phone = device(client)
    ref = str(resolve(client, "marwa", song())[0]["id"])

    with Held(database(client)):
        pass_, a = took(lambda: client.get(f"{V1}/covers/pass", headers=phone))
        cover, b = took(lambda: client.get(f"{V1}/covers/cover-1/url", headers=phone, params={"size": 300}))
        stream, c = took(lambda: client.get(f"{V1}/refs/{ref}/stream-url", headers=phone))

    assert pass_.status_code == cover.status_code == stream.status_code == 200
    assert max(a, b, c) < QUICK_S, f"an address waited {max(a, b, c):.2f} s for a writer"


def test_serving_a_picture_checks_the_signature_without_the_write_lock(rig: tuple[TestClient, MusicServerWatcher]) -> None:
    client, _ = rig
    phone = device(client)
    cover_url = client.get(f"{V1}/covers/cover-1/url", headers=phone).json()["url"]

    with Held(database(client)):
        answer, seconds = took(lambda: client.get(cover_url))

    # No music server is configured in this test, so the picture is "not found": what matters is that the signature was accepted, and quickly.
    assert answer.status_code == 404 and seconds < QUICK_S, f"a picture waited {seconds:.2f} s for a writer"


def test_the_music_server_is_not_asked_inside_a_transaction(rig: tuple[TestClient, MusicServerWatcher]) -> None:
    """A new person's first request asks the music server whether they are an administrator. That may take seconds; nobody else may wait for it."""
    client, music = rig

    assert client.get(f"{V1}/me", params=creds("nina")).status_code == 200

    assert music.write_lock_was_free is True, "the music server was asked while the database was locked for writing"


def test_the_first_request_of_a_person_still_makes_them_and_the_first_person_is_the_owner(
    rig: tuple[TestClient, MusicServerWatcher],
) -> None:
    client, _ = rig

    mine = client.get(f"{V1}/me", params=creds("marwa")).json()
    nina = client.get(f"{V1}/me", params=creds("nina")).json()
    again = client.get(f"{V1}/me", params=creds("nina")).json()

    assert mine["role"] == "owner" and nina["role"] == "member" and again["id"] == nina["id"]


def test_two_first_requests_of_the_same_person_at_once_make_one_person(rig: tuple[TestClient, MusicServerWatcher]) -> None:
    client, _ = rig
    client.get(f"{V1}/me", params=creds("marwa"))
    answers: list[Any] = []

    def ask() -> None:
        answers.append(client.get(f"{V1}/me", params=creds("mia")).json())

    threads = [threading.Thread(target=ask) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len({a["id"] for a in answers}) == 1, "one person, however many first requests arrive together"


def test_a_device_is_noted_as_seen_at_most_once_a_minute_and_a_busy_database_never_refuses_the_request(
    rig: tuple[TestClient, MusicServerWatcher],
) -> None:
    client, _ = rig
    phone = device(client)
    db = database(client)

    def last_seen() -> int | None:
        with db.read() as conn:
            return conn.execute("SELECT last_seen FROM device").fetchone()["last_seen"]  # type: ignore[no-any-return]

    client.get(f"{V1}/playlists", headers=phone)
    first = last_seen()
    assert first is not None, "the first request notes it"
    time.sleep(0.05)
    client.get(f"{V1}/playlists", headers=phone)
    assert last_seen() == first, "a second request within the minute writes nothing"

    with db.tx() as conn:  # it was last seen long ago, and the database is busy with somebody else
        conn.execute("UPDATE device SET last_seen = 1")
    with Held(db):
        answer, _ = took(lambda: client.get(f"{V1}/playlists", headers=phone))
    assert answer.status_code == 200


def test_the_signing_secret_is_the_same_after_a_restart_so_addresses_already_handed_out_still_work(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "m",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        workers=False,
    )
    with TestClient(create_app(settings, verifier=FakeVerifier())) as first:
        key = first.app.state.services.stream_key  # type: ignore[attr-defined]
    with TestClient(create_app(settings, verifier=FakeVerifier())) as second:
        again = second.app.state.services.stream_key  # type: ignore[attr-defined]
        with second.app.state.services.db.read() as conn:  # type: ignore[attr-defined]
            stored = stream_secret(conn)

    assert len(key) == 32 and key == again == stored
