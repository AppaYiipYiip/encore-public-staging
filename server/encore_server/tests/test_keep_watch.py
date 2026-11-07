"""`PUT /keep/watch` and the live event `keep.progress` (P2-22 part 1b, docs/17 "Keep progress"): a phone says which downloads it watches and is told,
on its own connection only, when the answer changes. The pushed answer is `progress()` itself, so what a person may see is the same rule."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server import keep_watch as keep_watch_module
from encore_server import refs as refs_module
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.ids import new_id
from encore_server.keep_progress import Group
from encore_server.keep_watch import GONE_FOREVER_S
from tests.conftest import FakeVerifier, creds, resolve, song
from tests.test_keep_triggers import Configured
from tests.test_keeper import FakeSource, fake_ffmpeg

V1 = "/encore/api/v1"


class Device:
    """A signed-in phone: a device token and, when it listens, a live socket."""

    def __init__(self, rig: Rig, user: str, name: str) -> None:
        response = rig.client.post(f"{V1}/auth/login", json={"username": user, "password": f"pw-{user}", "deviceName": name})
        assert response.status_code == 200, response.text
        self.token = response.json()["deviceToken"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.user = user
        self.rig = rig
        self.socket: Any = None
        self._scope: contextlib.ExitStack | None = None

    def listen(self) -> None:
        self._scope = contextlib.ExitStack()
        self.socket = self._scope.enter_context(self.rig.client.websocket_connect("/encore/live"))
        self.socket.send_json({"type": "auth", "token": self.token})
        assert self.socket.receive_json()["type"] == "hello"

    def hang_up(self) -> None:
        assert self._scope is not None
        self._scope.close()
        self._scope = None
        self.socket = None

    def next_progress(self, seconds: float = 4.0) -> dict[str, Any] | None:
        """The next `keep.progress` this device is told (other events are skipped); `None` when none comes in time.

        A timeout leaves its reader thread waiting on the socket, and a later read on the same device would race it for the next event: after a `None`,
        do not read from that device again in the same test."""
        found: dict[str, Any] = {}

        def read() -> None:
            while "event" not in found:
                event = self.socket.receive_json()
                if event["type"] == "keep.progress":
                    found["event"] = event

        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        thread.join(seconds)
        return found.get("event")

    def watch(self, *groups: dict[str, Any]) -> dict[str, Any]:
        response = self.rig.client.put(f"{V1}/keep/watch", headers=self.headers, json={"groups": list(groups)})
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]


class Rig:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.svc = client.app.state.services  # type: ignore[attr-defined]
        self.source: FakeSource = self.svc.youtube
        self.devices: list[Device] = []

    def device(self, user: str = "marwa", name: str = "Phone", *, listening: bool = True) -> Device:
        device = Device(self, user, name)
        if listening:
            device.listen()
        self.devices.append(device)
        return device

    def songs(self, user: str, *titles: str) -> list[str]:
        return [str(r["id"]) for r in resolve(self.client, user, *[song(t) for t in titles])]

    def like(self, user: str, *refs: str) -> None:
        for ref in refs:
            assert self.client.put(f"{V1}/likes/{ref}", params=creds(user)).status_code == 200

    def set_item(self, ref: str, state: str, error: str | None = None) -> None:
        with self.svc.db.tx() as conn:
            conn.execute(
                "UPDATE work_item SET state = ?, error = ?, updated_at = updated_at + 1 WHERE kind = 'keep' AND ref = ?",
                (state, error, ref),
            )


LIKED = {"kind": "liked", "id": "liked"}


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier, monkeypatch: pytest.MonkeyPatch) -> Iterator[Rig]:
    music = tmp_path / "music"
    music.mkdir()
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=music,
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        workers=False,
        min_free_gb=0.0,
    )
    monkeypatch.setattr("encore_server.keeper.keeper.run_command", fake_ffmpeg)
    with TestClient(create_app(settings, verifier=verifier, youtube=FakeSource(), navidrome=Configured(music))) as client:  # type: ignore[arg-type]
        made = Rig(client)
        yield made
        for device in made.devices:
            if device.socket is not None:
                device.hang_up()


def only(groups: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(groups) == 1, groups
    return groups[0]


# ------------------------------------------------------------------------------------------------ the request


def test_watching_answers_with_the_current_counts_so_a_phone_that_just_connected_needs_no_second_call(rig: Rig) -> None:
    refs = rig.songs("marwa", "A", "B")
    rig.like("marwa", *refs)
    rig.svc.scheduler.drain()
    phone = rig.device()

    answer = phone.watch(LIKED)

    assert (only(answer["groups"])["total"], only(answer["groups"])["ready"]) == (2, 2)
    assert answer["youtube"]["state"] == "off" and isinstance(answer["serverTime"], int)
    assert rig.svc.keep_watch.watching() == 1


def test_an_empty_list_stops_watching_and_an_unsigned_device_or_a_bad_request_is_refused_in_words(rig: Rig) -> None:
    phone = rig.device()
    phone.watch(LIKED)

    assert phone.watch()["groups"] == [] and rig.svc.keep_watch.watching() == 0

    legacy = rig.client.put(f"{V1}/keep/watch", params=creds("marwa"), json={"groups": [LIKED]})
    assert legacy.status_code == 400 and "signed-in device" in legacy.json()["error"]["message"]
    for body in ({}, {"groups": "liked"}, {"groups": [{"kind": "album", "id": "x"}]}, {"groups": [LIKED] * 51}):
        refused = rig.client.put(f"{V1}/keep/watch", headers=phone.headers, json=body)
        assert refused.status_code == 400 and refused.json()["error"]["code"] == "validation", body
    assert rig.client.put(f"{V1}/keep/watch", json={"groups": []}).status_code == 401


def test_a_server_that_does_not_keep_songs_has_nothing_to_watch(tmp_path: Path, verifier: FakeVerifier) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as client:
        login = client.post(f"{V1}/auth/login", json={"username": "marwa", "password": "pw-marwa", "deviceName": "Phone"})
        headers = {"Authorization": f"Bearer {login.json()['deviceToken']}"}

        refused = client.put(f"{V1}/keep/watch", headers=headers, json={"groups": []})

        assert refused.status_code == 404 and refused.json()["error"]["message"] == "This server does not keep songs."
        assert client.app.state.services.keep_watch is None  # type: ignore[attr-defined]


# ------------------------------------------------------------------------------------------------ the push


def test_a_change_is_pushed_to_the_watching_device_and_the_same_answer_is_not_pushed_twice(rig: Rig) -> None:
    refs = rig.songs("marwa", "A", "B")
    rig.like("marwa", *refs)
    phone = rig.device()
    before = phone.watch(LIKED)
    assert only(before["groups"])["ready"] == 0

    assert rig.svc.keep_watch.tick() == 0, "nothing has changed since the reply"
    rig.svc.scheduler.drain()  # the server keeps them
    assert rig.svc.keep_watch.tick() == 1

    event = phone.next_progress()
    assert event is not None and event["type"] == "keep.progress"
    assert (only(event["groups"])["total"], only(event["groups"])["ready"]) == (2, 2)
    assert event["youtube"]["state"] == "off" and isinstance(event["serverTime"], int)
    assert rig.svc.keep_watch.tick() == 0, "and asking again changes nothing"


def test_only_the_watching_device_is_told_and_a_device_that_watches_nothing_hears_nothing(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "A")
    rig.like("marwa", ref)
    watcher = rig.device(name="Watcher")
    other = rig.device(name="Other")  # the same person, listening, not watching
    stranger = rig.device("nina", "Nina's phone")
    watcher.watch(LIKED)

    rig.svc.scheduler.drain()

    assert rig.svc.keep_watch.tick() == 1
    assert watcher.next_progress() is not None
    assert other.next_progress(0.5) is None and stranger.next_progress(0.5) is None


def test_a_group_the_person_does_not_have_never_appears_in_a_pushed_answer(rig: Rig) -> None:
    mine, theirs = rig.songs("nina", "Mine"), rig.songs("marwa", "Theirs")
    playlist = new_id("pl")
    rig.client.post(f"{V1}/playlists", params=creds("marwa"), json={"id": playlist, "name": "His"})
    rig.client.post(
        f"{V1}/playlists/{playlist}/entries", params=creds("marwa"), json={"songs": [{"ref": theirs[0], "id": new_id("pe")}]}
    )
    rig.like("nina", *mine)
    nina = rig.device("nina", "Nina's phone")
    # she asks about his playlist (by guessing its id), a playlist that never existed, and her own liked songs
    asked = nina.watch({"kind": "playlist", "id": playlist}, {"kind": "playlist", "id": "pl_" + "0" * 26}, LIKED)
    assert [g["kind"] for g in asked["groups"]] == ["liked"], "the reply already leaves them out"

    rig.svc.scheduler.drain()  # both people's songs are kept: his playlist moves too
    assert rig.svc.keep_watch.tick() == 1

    event = nina.next_progress()
    assert event is not None
    assert [g["kind"] for g in event["groups"]] == ["liked"] and playlist not in str(event), (
        "nothing about his playlist, not even that it exists"
    )


def test_a_playlist_that_is_deleted_while_watched_disappears_from_the_next_push(rig: Rig) -> None:
    refs = rig.songs("marwa", "A")
    playlist = new_id("pl")
    rig.client.post(f"{V1}/playlists", params=creds("marwa"), json={"id": playlist, "name": "Mix"})
    rig.client.post(
        f"{V1}/playlists/{playlist}/entries", params=creds("marwa"), json={"songs": [{"ref": refs[0], "id": new_id("pe")}]}
    )
    rig.like("marwa", refs[0])
    phone = rig.device()
    assert len(phone.watch({"kind": "playlist", "id": playlist}, LIKED)["groups"]) == 2

    rig.client.delete(f"{V1}/playlists/{playlist}", params=creds("marwa"))
    assert rig.svc.keep_watch.tick() == 1

    event = phone.next_progress()
    assert event is not None and [g["kind"] for g in event["groups"]] == ["liked"]


def test_the_host_is_told_the_cause_and_a_member_the_plain_fact_in_the_same_push(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "Gone")
    rig.like("marwa", ref)
    rig.like("nina", ref)
    host, member = rig.device("marwa"), rig.device("nina", "Nina's phone")
    host.watch(LIKED)
    member.watch(LIKED)

    rig.set_item(ref, "failed", "the only copy needs an age check")
    assert rig.svc.keep_watch.tick() == 2

    host_reason = only(host.next_progress()["groups"])["failures"][0]["reason"]  # type: ignore[index]
    member_reason = only(member.next_progress()["groups"])["failures"][0]["reason"]  # type: ignore[index]
    assert host_reason.startswith("The only copy on YouTube needs an age check, which this server cannot pass.")
    assert member_reason == "Needs an age check."


def test_a_person_who_stops_being_the_host_is_told_in_a_members_words_from_the_next_push(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "Gone")
    rig.like("marwa", ref)
    phone = rig.device()
    phone.watch(LIKED)
    rig.set_item(ref, "failed", "the only copy needs an age check")
    rig.svc.keep_watch.tick()
    assert "age check, which this server" in only(phone.next_progress()["groups"])["failures"][0]["reason"]  # type: ignore[index]

    with rig.svc.db.tx() as conn:
        conn.execute("UPDATE person SET role = 'member' WHERE navidrome_user = 'marwa'")
    rig.set_item(ref, "failed", "the only copy needs an age check")  # touches the queue, so the answer is looked at again

    assert rig.svc.keep_watch.tick() == 1
    assert only(phone.next_progress()["groups"])["failures"][0]["reason"] == "Needs an age check."  # type: ignore[index]


# ------------------------------------------------------------------------------------------------ YouTube's rest


def test_a_rest_is_pushed_once_when_it_starts_and_its_count_down_is_not_news(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("encore_server.keep_watch._now", lambda: 1_000_000.0)
    refs = rig.songs("marwa", "A", "B")
    rig.like("marwa", *refs)
    phone = rig.device()
    resting = {"state": "resting", "resumesInSec": 840}
    phone.watch(LIKED)

    rig.source.status = lambda: dict(resting)  # type: ignore[attr-defined]
    assert rig.svc.keep_watch.tick() == 1
    event = phone.next_progress()
    assert event is not None and event["youtube"] == resting
    assert only(event["groups"])["queued"] == 2, "songs that wait for the rest are queued, not failed"

    resting["resumesInSec"] = 830  # ten seconds later, by the same clock
    monkeypatch.setattr("encore_server.keep_watch._now", lambda: 1_000_010.0)
    rig.set_item(refs[0], "queued")  # something touches the queue, so the answer is looked at again
    assert rig.svc.keep_watch.tick() == 0, "the end of the rest did not move, so there is nothing to say"

    resting["state"] = "ok"
    resting["resumesInSec"] = 0
    assert rig.svc.keep_watch.tick() == 1 and phone.next_progress()["youtube"]["state"] == "ok"  # type: ignore[index]


# ------------------------------------------------------------------------------------------------ connections


def test_a_device_that_is_gone_is_not_pushed_to_and_is_forgotten_after_a_while(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "A")
    rig.like("marwa", ref)
    now = [1000.0]
    rig.svc.keep_watch._clock = lambda: now[0]  # type: ignore[attr-defined]
    phone = rig.device()
    phone.watch(LIKED)
    phone.hang_up()

    rig.svc.scheduler.drain()
    assert rig.svc.keep_watch.tick() == 0, "nobody is listening"
    assert rig.svc.keep_watch.watching() == 1, "its watch is kept for a little while: it may reconnect"
    now[0] += GONE_FOREVER_S + 1
    rig.svc.keep_watch.tick()
    assert rig.svc.keep_watch.watching() == 0, "and then it is let go"


def test_a_device_that_reconnects_gets_the_current_answer_from_asking_again_without_any_event(rig: Rig) -> None:
    refs = rig.songs("marwa", "A", "B")
    rig.like("marwa", *refs)
    phone = rig.device()
    phone.watch(LIKED)
    phone.hang_up()
    rig.svc.scheduler.drain()  # the server went on while the phone was away

    phone.listen()
    answer = phone.watch(LIKED)

    assert only(answer["groups"])["ready"] == 2
    assert rig.svc.keep_watch.tick() == 0, "it has been told: nothing to push"


def test_the_clock_pushes_by_itself(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "A")
    rig.like("marwa", ref)
    phone = rig.device()
    phone.watch(LIKED)
    rig.svc.keep_watch._interval = 0.05  # type: ignore[attr-defined]
    rig.svc.keep_watch.start()
    try:
        rig.svc.scheduler.drain()
        event = phone.next_progress()
        for _ in range(5):  # it may first say "keeping": every change is told, the last one is the answer
            if event is None or only(event["groups"])["ready"] == 1:
                break
            event = phone.next_progress()
    finally:
        rig.svc.keep_watch.stop()

    assert event is not None and only(event["groups"])["ready"] == 1


def test_a_recount_that_fails_for_one_device_does_not_stop_the_others_and_is_tried_again_though_nothing_moved(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    (ref,) = rig.songs("marwa", "A")
    rig.like("marwa", ref)
    rig.like("nina", ref)
    first, second = rig.device("marwa"), rig.device("nina", "Nina's phone")
    first.watch(LIKED)
    second.watch(LIKED)
    real = keep_watch_module.progress
    calls: list[str] = []

    def flaky(db: Any, scheduler: Any, person: str, **kwargs: Any) -> Any:
        calls.append(person)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(db, scheduler, person, **kwargs)

    monkeypatch.setattr("encore_server.keep_watch.progress", flaky)
    rig.svc.scheduler.drain()

    assert rig.svc.keep_watch.tick() == 1, "one device was recounted, one was not"
    assert rig.svc.keep_watch.tick() == 1, "nothing moved since, and the device that was missed is still counted for"
    assert only(first.next_progress()["groups"])["ready"] == 1  # type: ignore[index]
    assert only(second.next_progress()["groups"])["ready"] == 1  # type: ignore[index]


def test_a_watch_replaced_while_it_is_being_recounted_never_gets_the_old_groups(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    refs = rig.songs("marwa", "A", "B")
    rig.like("marwa", refs[0])
    phone = rig.device()
    phone.watch(LIKED)
    playlist = new_id("pl")
    rig.client.post(f"{V1}/playlists", params=creds("marwa"), json={"id": playlist, "name": "New"})
    person, device = next(iter(rig.svc.keep_watch._watches))  # type: ignore[attr-defined]
    real = keep_watch_module.progress
    new_groups = [Group("playlist", playlist)]

    def replaced_meanwhile(db: Any, scheduler: Any, who: str, **kwargs: Any) -> Any:
        answer = real(db, scheduler, who, **kwargs)  # the old groups are counted...
        rig.svc.keep_watch.watch(
            person, device, new_groups, "what-the-reply-said"
        )  # ...and the device replaces its watch before the push
        return answer

    monkeypatch.setattr("encore_server.keep_watch.progress", replaced_meanwhile)
    rig.svc.scheduler.drain()  # something moved

    assert rig.svc.keep_watch.tick() == 0, "the count of the old groups is thrown away"
    monkeypatch.setattr("encore_server.keep_watch.progress", real)
    assert rig.svc.keep_watch.tick() == 1, "the new watch is checked at once, even though nothing moved"
    event = phone.next_progress()
    assert event is not None and [g["kind"] for g in event["groups"]] == ["playlist"], "only what it watches now"


def test_a_song_that_becomes_ready_without_the_keeper_is_pushed_too(rig: Rig) -> None:
    """The Host's library scan attaches a file the same way (`refs.attach_file`); it touches the file feed, not the keep queue."""
    (ref,) = rig.songs("marwa", "A")
    rig.like("marwa", ref)
    with rig.svc.db.tx() as conn:  # the like queued a keep; the scan finds the file first
        conn.execute("DELETE FROM work_item")
    phone = rig.device()
    assert only(phone.watch(LIKED)["groups"])["ready"] == 0

    with rig.svc.db.tx() as conn:
        refs_module.attach_file(
            conn, ref, navidrome_song_id="nd-77", path="Radiohead/A.opus", codec="opus", bitrate_kbps=128, source="library"
        )

    assert rig.svc.keep_watch.tick() == 1
    event = phone.next_progress()
    assert event is not None and only(event["groups"])["ready"] == 1


# ------------------------------------------------------------------------------------------------ the scheduler's cheap look


def test_the_keep_queue_says_when_it_moved_without_being_counted_song_by_song(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "A")
    quiet = rig.svc.scheduler.activity("keep")
    assert quiet[0] == 0

    rig.like("marwa", ref)
    queued = rig.svc.scheduler.activity("keep")
    rig.svc.scheduler.drain()
    kept = rig.svc.scheduler.activity("keep")

    assert queued != quiet and kept != queued
    assert rig.svc.scheduler.activity("keep") == kept, "and it stands still while nothing happens"
