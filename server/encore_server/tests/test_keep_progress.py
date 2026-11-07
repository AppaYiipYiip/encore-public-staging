"""`POST /keep/progress` (P2-22 part 1, docs/17 "Keep progress"): how far the server is with the songs a person pinned for download, many things in
one answer. Every song in exactly one bucket, a failure that survives the scheduler's cleanup, the right sentence for the Host and for a member,
and nothing leaking about what another person has."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.ids import new_id
from encore_server.keeper.failures import describe_failure
from encore_server.keeper.keeper import GIVE_UP
from encore_server.sources.youtube.errors import DownloadError
from tests.conftest import FakeVerifier, creds, resolve, song
from tests.test_keeper import FakeNavidrome, FakeSource, fake_ffmpeg

V1 = "/encore/api/v1"
DAY_S = 24 * 3600


class Configured(FakeNavidrome):
    configured = True


class Rig:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.svc = client.app.state.services  # type: ignore[attr-defined]
        self.source: FakeSource = self.svc.youtube

    def songs(self, user: str, *titles: str) -> list[str]:
        return [str(r["id"]) for r in resolve(self.client, user, *[song(t) for t in titles])]

    def playlist(self, user: str, refs: list[str]) -> str:
        playlist = new_id("pl")
        assert self.client.post(f"{V1}/playlists", params=creds(user), json={"id": playlist, "name": "Mix"}).status_code == 201
        self.client.post(
            f"{V1}/playlists/{playlist}/entries",
            params=creds(user),
            json={"songs": [{"ref": r, "id": new_id("pe")} for r in refs]},
        )
        return playlist

    def ask(self, user: str, *groups: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(f"{V1}/keep/progress", params=creds(user), json={"groups": list(groups)})
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]

    def set_item(self, ref: str, state: str, error: str | None = None) -> None:
        """Puts the keep item of a song in a state the keeper would leave it in (without running the keeper)."""
        with self.svc.db.tx() as conn:
            conn.execute("UPDATE work_item SET state = ?, error = ? WHERE kind = 'keep' AND ref = ?", (state, error, ref))

    def drop_item(self, ref: str) -> None:
        with self.svc.db.tx() as conn:
            conn.execute("DELETE FROM work_item WHERE kind = 'keep' AND ref = ?", (ref,))


def build_rig(tmp_path: Path, verifier: FakeVerifier, monkeypatch: pytest.MonkeyPatch) -> Iterator[Rig]:
    """A server that keeps songs (a fake YouTube and music server), for these tests and the neighbours that build on them."""
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
        yield Rig(client)


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier, monkeypatch: pytest.MonkeyPatch) -> Iterator[Rig]:
    yield from build_rig(tmp_path, verifier, monkeypatch)


def only(answer: dict[str, Any]) -> dict[str, Any]:
    assert len(answer["groups"]) == 1, answer
    return answer["groups"][0]  # type: ignore[no-any-return]


def buckets(group: dict[str, Any]) -> tuple[int, int, int, int]:
    return group["ready"], group["keeping"], group["queued"], group["failed"]


# ------------------------------------------------------------------------------------------------ the counts


def test_every_song_is_in_exactly_one_bucket_and_the_buckets_add_up_to_the_total(rig: Rig) -> None:
    ready, keeping, queued, failed, never, lost = rig.songs("marwa", "Ready", "Keeping", "Queued", "Failed", "Never", "Lost")
    playlist = rig.playlist("marwa", [ready, keeping, queued, failed, never, lost])
    rig.svc.scheduler.drain()  # every song is kept...
    # ...then each one is put where the keeper may leave it:
    rig.set_item(keeping, "running")
    with rig.svc.db.tx() as conn:
        conn.execute("DELETE FROM song_file WHERE ref IN (?, ?, ?, ?, ?)", (keeping, queued, failed, never, lost))
    rig.set_item(queued, "queued")
    rig.set_item(failed, "failed", "no upload of this song was found")
    rig.drop_item(never)  # nothing ever tried it
    rig.set_item(lost, "done")  # it was kept once and its file is gone

    group = only(rig.ask("marwa", {"kind": "playlist", "id": playlist}))

    assert group["total"] == 6
    assert buckets(group) == (1, 1, 1, 3), "ready, keeping, queued, and the three that are not coming"
    assert sum(buckets(group)) == group["total"]
    assert {f["ref"] for f in group["failures"]} == {failed, never, lost}
    assert group["retryable"] == 2, "a song that is not found is not worth another try; the other two are"


def test_a_song_the_server_has_is_ready_even_if_it_is_also_on_the_phone(rig: Rig) -> None:
    """`ready` is what the SERVER holds. What is on the phone is the phone's own table: it is never sent here."""
    refs = rig.songs("marwa", "One", "Two")
    playlist = rig.playlist("marwa", refs)
    rig.svc.scheduler.drain()

    group = only(rig.ask("marwa", {"kind": "playlist", "id": playlist}))

    assert buckets(group) == (2, 0, 0, 0)
    assert "onPhone" not in group and "on_phone" not in group


def test_the_buckets_agree_with_the_state_of_one_song_asked_alone_in_all_seven_situations(rig: Rig) -> None:
    """`GET refs/{id}/keep` and the batch answer must not tell two stories. The one place they differ in words is on purpose: for a song somebody WANTS,
    the single-song call says `none` (nothing queued, which is what `save_album` and `keep_now` act on) and the batch says `failed` (so the phone names it
    and offers Retry)."""
    refs = rig.songs("marwa", "Kept", "Keeping", "Queued", "Failed", "Done", "Cancelled", "Never")
    playlist = rig.playlist("marwa", refs)
    rig.svc.scheduler.drain()
    with rig.svc.db.tx() as conn:
        conn.execute("DELETE FROM song_file WHERE ref != ?", (refs[0],))
    rig.set_item(refs[1], "running")
    rig.set_item(refs[2], "queued")
    rig.set_item(refs[3], "failed", "boom")
    rig.set_item(refs[4], "done")  # kept once, the file is gone
    rig.set_item(refs[5], "cancelled")
    rig.drop_item(refs[6])

    group = only(rig.ask("marwa", {"kind": "playlist", "id": playlist}))
    alone = {r: rig.client.get(f"{V1}/refs/{r}/keep", params=creds("marwa")).json()["state"] for r in refs}
    in_batch = {"kept": "ready", "keeping": "keeping", "queued": "queued", "failed": "failed", "none": "failed"}

    assert list(alone.values()) == ["kept", "keeping", "queued", "failed", "none", "none", "none"]
    expected = [in_batch[state] for state in alone.values()]
    assert buckets(group) == tuple(expected.count(name) for name in ("ready", "keeping", "queued", "failed"))
    assert {f["ref"] for f in group["failures"]} == {refs[3], refs[4], refs[5], refs[6]}


def test_a_song_the_real_keeper_gave_up_on_for_length_says_so_and_cannot_be_retried(rig: Rig) -> None:
    """The sentence and the Retry flag are matched against the keeper's own text, so this goes through the keeper, not through a copy of its words."""
    (ref,) = [str(r["id"]) for r in resolve(rig.client, "marwa", song("Very Long", durationMs=151 * 60_000))]
    for user in ("marwa", "nina"):
        rig.client.put(f"{V1}/likes/{ref}", params=creds(user))

    rig.svc.scheduler.drain()

    host = only(rig.ask("marwa", {"kind": "liked", "id": "liked"}))["failures"][0]
    assert host["retry"] is False and host["reason"].startswith("Longer than this server's limit"), host
    member = only(rig.ask("nina", {"kind": "liked", "id": "liked"}))["failures"][0]
    assert member["retry"] is False and member["reason"] == "Too long to keep."


def test_a_song_twice_in_a_playlist_or_removed_from_it_counts_as_it_is(rig: Rig) -> None:
    a, b = rig.songs("marwa", "A", "B")
    playlist = rig.playlist("marwa", [a, a, b])
    entries = rig.client.get(f"{V1}/playlists/{playlist}", params=creds("marwa")).json()["entries"]
    rig.client.request(
        "DELETE", f"{V1}/playlists/{playlist}/entries", params=creds("marwa"), json={"entryIds": [entries[2]["id"]]}
    )

    group = only(rig.ask("marwa", {"kind": "playlist", "id": playlist}))

    assert group["total"] == 1, "the same song twice is one file; a removed entry is not wanted"


def test_the_liked_songs_and_a_playlist_in_one_request_and_a_big_playlist_across_the_query_chunks(rig: Rig) -> None:
    titles = [f"Song {n}" for n in range(450)]
    refs = rig.songs("marwa", *titles)
    playlist = new_id("pl")
    rig.client.post(f"{V1}/playlists", params=creds("marwa"), json={"id": playlist, "name": "Big"})
    with rig.svc.db.tx() as conn:
        for position, ref in enumerate(refs):
            conn.execute(
                "INSERT INTO playlist_entry (id, playlist, position, ref, added_by, at) SELECT ?, ?, ?, ?, id, 0 FROM person WHERE navidrome_user = 'marwa'",
                (new_id("pe"), playlist, float(position), ref),
            )
    rig.client.put(f"{V1}/likes/{refs[0]}", params=creds("marwa"))
    rig.svc.scheduler.drain(limit=2000)

    answer = rig.ask("marwa", {"kind": "playlist", "id": playlist}, {"kind": "liked", "id": "liked"})

    big, liked = answer["groups"]
    assert (big["id"], big["total"], big["ready"]) == (playlist, 450, 1), "only the liked one was ever queued"
    assert sum(buckets(big)) == 450 and big["failed"] == 449
    assert (liked["kind"], liked["total"], liked["ready"]) == ("liked", 1, 1)
    assert len(big["failures"]) == 20, "a failure is named for the first twenty; `failed` counts them all"


# ------------------------------------------------------------------------------------------------ failures


def test_a_failure_stays_after_the_scheduler_forgets_old_work_for_as_long_as_somebody_has_the_song(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "Gone")
    rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    rig.set_item(ref, "failed", "no upload of this song was found")
    with rig.svc.db.tx() as conn:
        conn.execute("UPDATE work_item SET updated_at = 1")  # a very old failure

    rig.svc.scheduler.recover()  # the cleanup at the server's start

    group = only(rig.ask("marwa", {"kind": "liked", "id": "liked"}))
    assert group["failed"] == 1 and "No upload" in group["failures"][0]["reason"], "still named, not 'never fetched'"
    assert group["failures"][0]["retry"] is False

    rig.client.delete(f"{V1}/likes/{ref}", params=creds("marwa"))  # nobody has it any more
    rig.svc.scheduler.recover()
    assert rig.svc.scheduler.state_of("keep", ref) is None, "then it is forgotten like any old work"


def test_old_finished_work_nobody_needs_is_still_forgotten(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "Done")
    rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    rig.svc.scheduler.drain()
    with rig.svc.db.tx() as conn:
        conn.execute("UPDATE work_item SET updated_at = 1")

    rig.svc.scheduler.recover()

    assert rig.svc.scheduler.state_of("keep", ref) is None


@pytest.mark.parametrize(
    ("stored", "retry"),
    [
        ("no upload of this song was found", False),
        ("YouTube has no copy that can be fetched", False),
        ("the only copy needs an age check", False),
        ("the file is bigger than the limit for keeping", False),
        ("longer than 45 minutes, so it is played but not kept", False),
        ("the file is not inside the music folder", False),
        ("The music server has not found the saved file yet. Check that its library includes the music folder.", True),
        ("RuntimeError: ffmpeg is not installed", True),
        (None, True),
    ],
)
def test_each_way_a_keep_fails_says_whether_trying_again_can_help(rig: Rig, stored: str | None, retry: bool) -> None:
    (ref,) = rig.songs("marwa", "Trouble")
    rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    rig.set_item(ref, "failed", stored)

    failure = only(rig.ask("marwa", {"kind": "liked", "id": "liked"}))["failures"][0]

    assert failure["retry"] is retry
    assert failure["title"] == "Trouble" and failure["artist"] == "Radiohead"
    assert failure["reason"] and failure["reason"].endswith(".")


def test_the_host_reads_the_cause_and_a_member_reads_the_plain_fact(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "Shared")
    for user in ("marwa", "nina"):
        rig.client.put(f"{V1}/likes/{ref}", params=creds(user))
    rig.set_item(ref, "failed", "the only copy needs an age check")

    host = only(rig.ask("marwa", {"kind": "liked", "id": "liked"}))["failures"][0]["reason"]
    member = only(rig.ask("nina", {"kind": "liked", "id": "liked"}))["failures"][0]["reason"]

    assert host.startswith("The only copy on YouTube needs an age check, which this server cannot pass.")
    assert "signed in on the server" in host and "asking again will not" in host, (
        "the Host is told what would fix it, and that Retry will not"
    )
    assert member == "Needs an age check."
    assert "server" not in member.lower(), "a member can do nothing about the server, so is not told about it"


def test_a_cause_that_is_the_servers_own_business_is_not_shown_to_a_member(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "Odd")
    rig.client.put(f"{V1}/likes/{ref}", params=creds("nina"))
    rig.set_item(ref, "failed", "OperationalError: unable to open database file /srv/encore/state.db")

    reason = only(rig.ask("nina", {"kind": "liked", "id": "liked"}))["failures"][0]["reason"]

    assert reason == "Something went wrong on the server." and "srv" not in reason


def test_every_reason_the_keeper_can_give_up_with_has_a_sentence() -> None:
    """A new code in the keeper's table without a sentence would reach a phone as 'Something went wrong' and a Retry that cannot work."""
    for code, stored in GIVE_UP.items():
        for host in (True, False):
            failure = describe_failure(stored, host=host)
            assert failure.retry is False, code
            assert "went wrong" not in failure.reason, code


def test_a_failure_that_the_keeper_really_raises_is_read_back_the_same_way(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "Missing")
    rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    rig.source.failure = DownloadError("not_found")

    rig.svc.scheduler.drain()

    failure = only(rig.ask("marwa", {"kind": "liked", "id": "liked"}))["failures"][0]
    assert failure["reason"] == "No upload of this song was found on YouTube." and failure["retry"] is False


# ------------------------------------------------------------------------------------------------ YouTube resting, the time


def test_the_answer_says_when_youtube_lets_the_server_go_on_and_what_time_the_server_thinks_it_is(rig: Rig) -> None:
    rig.source.status = lambda: {"state": "resting", "resumesInSec": 840}  # type: ignore[attr-defined]
    refs = rig.songs("marwa", "A", "B")
    playlist = rig.playlist("marwa", refs)

    answer = rig.ask("marwa", {"kind": "playlist", "id": playlist})

    assert answer["youtube"] == {"state": "resting", "resumesInSec": 840}
    assert isinstance(answer["serverTime"], int)
    assert buckets(only(answer)) == (0, 0, 2, 0), "songs waiting for the rest are queued, not failed"


def test_a_server_that_does_not_know_youtube_says_off(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "A")
    rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))

    assert rig.ask("marwa", {"kind": "liked", "id": "liked"})["youtube"] == {"state": "off", "resumesInSec": 0}


# ------------------------------------------------------------------------------------------------ whose groups they are


def test_somebody_elses_playlist_or_one_that_does_not_exist_or_was_deleted_is_left_out_the_same_way(rig: Rig) -> None:
    refs = rig.songs("marwa", "A")
    theirs = rig.playlist("marwa", refs)
    gone = rig.playlist("nina", rig.songs("nina", "B"))
    rig.client.delete(f"{V1}/playlists/{gone}", params=creds("nina"))

    foreign = rig.ask("nina", {"kind": "playlist", "id": theirs})
    missing = rig.ask("nina", {"kind": "playlist", "id": "pl_" + "0" * 26})
    deleted = rig.ask("nina", {"kind": "playlist", "id": gone})

    for answer in (foreign, missing, deleted):
        assert answer["groups"] == [], "nothing at all about it"
    assert {k for k in foreign} == {k for k in missing} == {k for k in deleted}, "the three answers cannot be told apart"


def test_a_release_the_person_has_not_saved_is_left_out_and_the_liked_songs_are_only_theirs(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "A")
    rig.client.put(f"{V1}/saved-albums/cat-1", params=creds("marwa"), json={"refs": [ref]})
    rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))

    answer = rig.ask("nina", {"kind": "release", "id": "cat-1", "refs": [ref]}, {"kind": "liked", "id": "liked"})

    assert [(g["kind"], g["total"]) for g in answer["groups"]] == [("liked", 0)], "an empty list of her own, and nothing of his"


def test_groups_come_back_in_the_order_asked_and_only_those_the_person_has(rig: Rig) -> None:
    a = rig.playlist("marwa", rig.songs("marwa", "A"))
    b = rig.playlist("marwa", rig.songs("marwa", "B"))

    answer = rig.ask("marwa", {"kind": "playlist", "id": b}, {"kind": "playlist", "id": "pl_nope"}, {"kind": "playlist", "id": a})

    assert [g["id"] for g in answer["groups"]] == [b, a]


# ------------------------------------------------------------------------------------------------ a saved release


def test_a_saved_release_remembers_its_songs_and_forgets_them_when_it_is_removed(rig: Rig) -> None:
    first, second = rig.songs("marwa", "Nude", "Reckoner")
    rig.client.put(f"{V1}/saved-albums/cat-1", params=creds("marwa"), json={"refs": [first, second]})
    rig.svc.scheduler.drain()

    group = only(rig.ask("marwa", {"kind": "release", "id": "cat-1"}))
    assert (group["total"], group["ready"]) == (2, 2), "the server knows the members without being told"

    rig.client.delete(f"{V1}/saved-albums/cat-1", params=creds("marwa"))
    assert rig.ask("marwa", {"kind": "release", "id": "cat-1"})["groups"] == []
    with rig.svc.db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM saved_album_ref").fetchone()["n"] == 0


def test_saving_it_again_with_more_songs_adds_them_and_never_doubles_one(rig: Rig) -> None:
    first, second, third = rig.songs("marwa", "A", "B", "C")
    rig.client.put(f"{V1}/saved-albums/cat-1", params=creds("marwa"), json={"refs": [first, second]})
    rig.client.put(f"{V1}/saved-albums/cat-1", params=creds("marwa"), json={"refs": [second, third]})

    assert only(rig.ask("marwa", {"kind": "release", "id": "cat-1"}))["total"] == 3


def test_a_release_saved_before_the_server_stored_its_songs_takes_them_from_the_phone_once_and_only_known_ones(rig: Rig) -> None:
    first, second = rig.songs("marwa", "A", "B")
    rig.client.put(f"{V1}/saved-albums/old-one", params=creds("marwa"), json={})  # the old kind of save: no songs named

    asked = rig.ask("marwa", {"kind": "release", "id": "old-one", "refs": [first, second, "sr_" + "0" * 26]})

    assert only(asked)["total"] == 2, "a song this server has never heard of is not counted"
    again = rig.ask("marwa", {"kind": "release", "id": "old-one"})
    assert only(again)["total"] == 0, "asking changes nothing: without the hint there is still nothing stored"


def test_the_songs_stored_with_a_release_win_over_a_hint(rig: Rig) -> None:
    first, second = rig.songs("marwa", "A", "B")
    rig.client.put(f"{V1}/saved-albums/cat-1", params=creds("marwa"), json={"refs": [first]})

    assert only(rig.ask("marwa", {"kind": "release", "id": "cat-1", "refs": [first, second]}))["total"] == 1


# ------------------------------------------------------------------------------------------------ the request


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"groups": []},
        {"groups": "pl_1"},
        {"groups": [{"kind": "album", "id": "x"}]},
        {"groups": [{"kind": "playlist"}]},
        {"groups": [{"kind": "playlist", "id": ""}]},
        {"groups": [{"kind": "playlist", "id": "x" * 101}]},
        {"groups": [{"kind": "release", "id": "x", "refs": "sr_1"}]},
        {"groups": [{"kind": "release", "id": "x", "refs": ["sr_a"] * 501}]},
        {"groups": [{"kind": "liked", "id": "liked"}] * 51},
        {"groups": ["liked"]},
    ],
)
def test_a_request_that_is_not_a_list_of_known_downloads_is_refused_in_words(rig: Rig, body: dict[str, Any]) -> None:
    refused = rig.client.post(f"{V1}/keep/progress", params=creds("marwa"), json=body)

    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "validation" and refused.json()["error"]["message"]


def test_it_needs_a_login(rig: Rig) -> None:
    assert rig.client.post(f"{V1}/keep/progress", json={"groups": [{"kind": "liked", "id": "liked"}]}).status_code == 401


def test_a_server_that_does_not_keep_songs_says_so_and_the_app_is_told_by_the_features_not_by_trying(
    tmp_path: Path, verifier: FakeVerifier
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as client:
        assert "keep" not in client.get(f"{V1}/info").json()["features"]

        refused = client.post(f"{V1}/keep/progress", params=creds("marwa"), json={"groups": [{"kind": "liked", "id": "liked"}]})

        assert refused.status_code == 404 and refused.json()["error"]["message"] == "This server does not keep songs."


def test_asking_changes_nothing(rig: Rig) -> None:
    refs = rig.songs("marwa", "A", "B")
    playlist = rig.playlist("marwa", refs)
    rig.svc.scheduler.drain()
    rig.drop_item(refs[0])
    with rig.svc.db.tx() as conn:
        conn.execute("DELETE FROM song_file WHERE ref = ?", (refs[0],))
    before = rig.svc.scheduler.counts()

    first = rig.ask("marwa", {"kind": "playlist", "id": playlist})
    second = rig.ask("marwa", {"kind": "playlist", "id": playlist})

    assert rig.svc.scheduler.counts() == before, "a song nobody fetched is reported, not started: Retry is its own call"
    assert first["groups"] == second["groups"]


# ------------------------------------------------------------------------------------------------ the scheduler's bulk read


def test_the_newest_item_of_each_song_is_the_one_reported(rig: Rig) -> None:
    older, newer = rig.songs("marwa", "A", "B")
    rig.client.put(f"{V1}/likes/{older}", params=creds("marwa"))
    rig.client.put(f"{V1}/likes/{newer}", params=creds("marwa"))
    rig.set_item(older, "failed", "boom")
    rig.svc.scheduler.submit("keep", older, None)  # asked for again: a newer, queued item

    states = rig.svc.scheduler.states_of("keep", [older, newer, "sr_" + "0" * 26])

    assert states[older]["state"] == "queued" and states[newer]["state"] == "queued"
    assert "sr_" + "0" * 26 not in states, "a song with no item is simply absent"


# ------------------------------------------------------------------------------------------------ the single-song call speaks the same way


def _reason_of(rig: Rig, user: str, ref: str) -> str | None:
    """What `GET refs/{id}/keep` tells this person about the song (`None` when it tells nothing)."""
    body = rig.client.get(f"{V1}/refs/{ref}/keep", params=creds(user)).json()
    return body.get("reason")  # type: ignore[no-any-return]


def test_a_member_is_never_told_the_raw_error_of_a_failed_keep_by_the_single_song_call(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "Odd")
    rig.client.put(f"{V1}/likes/{ref}", params=creds("nina"))
    rig.set_item(ref, "failed", "OperationalError: unable to open database file /srv/encore/state.db")

    assert _reason_of(rig, "nina", ref) == "Something went wrong on the server."
    assert (
        _reason_of(rig, "marwa", ref)
        == "Something went wrong: OperationalError: unable to open database file /srv/encore/state.db."
    )


@pytest.mark.parametrize(
    ("stored", "host", "member"),
    [
        ("YouTube is being given a rest", "YouTube is resting.", "YouTube is resting."),
        ("YouTube is not answering (blocked)", "YouTube is not answering.", "YouTube is not answering."),
        (
            "less than 10 GB free, so nothing more is kept for now",
            "The server's disk is nearly full, so nothing more is kept for now.",
            "The server has no room for now.",
        ),
        (
            "RuntimeError: ffmpeg is not installed",
            "Something went wrong, trying again: RuntimeError: ffmpeg is not installed.",
            None,
        ),
        (None, None, None),
    ],
)
def test_a_song_that_waits_says_why_in_words_for_the_one_who_asks(
    rig: Rig, stored: str | None, host: str | None, member: str | None
) -> None:
    (ref,) = rig.songs("marwa", "Waiting")
    rig.client.put(f"{V1}/likes/{ref}", params=creds("nina"))
    with rig.svc.db.tx() as conn:
        conn.execute("UPDATE work_item SET error = ? WHERE kind = 'keep' AND ref = ?", (stored, ref))

    assert rig.client.get(f"{V1}/refs/{ref}/keep", params=creds("nina")).json()["state"] == "queued"
    assert _reason_of(rig, "marwa", ref) == host
    assert _reason_of(rig, "nina", ref) == member


def test_the_reasons_the_real_keeper_waits_with_are_understood(rig: Rig) -> None:
    """Driven through the keeper, not through a copy of its words: YouTube's rest and a nearly full disk."""
    resting, full = rig.songs("marwa", "Resting", "Full")
    rig.client.put(f"{V1}/likes/{resting}", params=creds("nina"))
    rig.source.resting = 600.0
    rig.svc.scheduler.drain()
    assert _reason_of(rig, "nina", resting) == "YouTube is resting."

    rig.source.resting = 0.0
    rig.svc.keeper._settings = dataclasses.replace(rig.svc.keeper._settings, min_free_gb=1e9)  # type: ignore[attr-defined]
    rig.client.put(f"{V1}/likes/{full}", params=creds("nina"))
    rig.svc.scheduler.drain()
    assert _reason_of(rig, "nina", full) == "The server has no room for now."
    assert _reason_of(rig, "marwa", full) == "The server's disk is nearly full, so nothing more is kept for now."


def test_saving_a_release_tells_each_song_in_words_for_the_one_who_saves(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "Waiting")
    rig.client.put(f"{V1}/likes/{ref}", params=creds("nina"))
    with rig.svc.db.tx() as conn:
        conn.execute(
            "UPDATE work_item SET error = ? WHERE kind = 'keep' AND ref = ?",
            ("RuntimeError: /srv/encore/work/keep-1 is not writable", ref),
        )

    member = rig.client.put(f"{V1}/saved-albums/cat-1", params=creds("nina"), json={"refs": [ref]}).json()["keep"][ref]
    host = rig.client.put(f"{V1}/saved-albums/cat-2", params=creds("marwa"), json={"refs": [ref]}).json()["keep"][ref]

    assert member == {"state": "queued"}, "nothing about the server's folders"
    assert host["reason"].startswith("Something went wrong, trying again: RuntimeError")
