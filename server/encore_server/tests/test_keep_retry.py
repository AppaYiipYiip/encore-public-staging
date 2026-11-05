"""`POST /keep/retry` (P2-22 part 4, docs/17 "Keep progress"): the Retry button under "3 songs did not come". It asks the server again for the songs of ONE
download that failed and can be helped, and leaves alone what asking again cannot change."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from encore_server.sources.youtube.errors import DownloadError
from tests.conftest import FakeVerifier, creds
from tests.test_keep_progress import V1, Rig, buckets, build_rig, only

LIKED_GROUP = {"kind": "liked", "id": "liked"}


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier, monkeypatch: pytest.MonkeyPatch) -> Iterator[Rig]:
    yield from build_rig(tmp_path, verifier, monkeypatch)


def retry(rig: Rig, user: str, group: dict[str, Any]) -> Any:
    return rig.client.post(f"{V1}/keep/retry", params=creds(user), json=group)


def test_retry_asks_again_for_what_can_be_helped_and_leaves_what_cannot(rig: Rig) -> None:
    ready, waiting, flaky, gone, never, lost = rig.songs("marwa", "Ready", "Waiting", "Flaky", "Gone", "Never", "Lost")
    for ref in (ready, waiting, flaky, gone, never, lost):
        rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    rig.svc.scheduler.drain()  # all kept...
    with rig.svc.db.tx() as conn:
        conn.execute("DELETE FROM song_file WHERE ref != ?", (ready,))
    rig.set_item(waiting, "queued")
    rig.set_item(flaky, "failed", "RuntimeError: ffmpeg is not installed")
    rig.set_item(gone, "failed", "no upload of this song was found")
    rig.drop_item(never)
    rig.set_item(lost, "done")

    answer = retry(rig, "marwa", LIKED_GROUP)

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["retried"] == 3, "the flaky one, the one nobody tried, the one whose file is gone"
    group = body["group"]
    assert buckets(group) == (1, 0, 4, 1), "the not-found song stays failed: asking again cannot change it"
    assert [f["ref"] for f in group["failures"]] == [gone] and group["failures"][0]["retry"] is False
    assert body["youtube"]["state"] == "off" and isinstance(body["serverTime"], int)

    rig.svc.scheduler.drain()
    after = only(rig.ask("marwa", LIKED_GROUP))
    assert buckets(after) == (5, 0, 0, 1), "and the asked-for songs really were fetched"


def test_retry_goes_first_in_line_and_a_second_press_finds_nothing_left_to_ask(rig: Rig) -> None:
    older, flaky = rig.songs("marwa", "Older", "Flaky")
    rig.client.put(f"{V1}/likes/{older}", params=creds("marwa"))  # an older keep waits in the queue
    rig.client.put(f"{V1}/likes/{flaky}", params=creds("marwa"))
    rig.set_item(flaky, "failed", "RuntimeError: ffmpeg is not installed")

    assert retry(rig, "marwa", LIKED_GROUP).json()["retried"] == 1
    rig.svc.scheduler.run_one("background")
    assert rig.source.asked[0].title == "Flaky", "the song somebody pressed Retry for goes before the older keep"

    assert retry(rig, "marwa", LIKED_GROUP).json()["retried"] == 0, (
        "nothing is failed any more: the second press asks for nothing"
    )


def test_a_member_retries_their_own_download_and_reads_the_plain_words(rig: Rig) -> None:
    (ref,) = rig.songs("marwa", "Odd")
    rig.client.put(f"{V1}/likes/{ref}", params=creds("nina"))
    rig.source.failure = DownloadError("age_restricted")
    rig.svc.scheduler.drain()
    assert only(rig.ask("nina", LIKED_GROUP))["failures"][0]["reason"] == "Needs an age check."

    body = retry(rig, "nina", LIKED_GROUP).json()

    assert body["retried"] == 0, "an age check does not pass by asking again"
    assert body["group"]["failures"][0]["reason"] == "Needs an age check."


def test_a_release_is_retried_by_its_stored_songs(rig: Rig) -> None:
    first, second = rig.songs("marwa", "Nude", "Reckoner")
    rig.client.put(f"{V1}/saved-albums/cat-1", params=creds("nina"), json={"refs": [first, second]})
    rig.set_item(first, "failed", "RuntimeError: ffmpeg is not installed")

    body = retry(rig, "nina", {"kind": "release", "id": "cat-1"}).json()

    assert body["retried"] == 1 and body["group"]["total"] == 2


def test_a_download_the_person_does_not_have_is_not_found_the_same_way_as_one_that_does_not_exist(rig: Rig) -> None:
    refs = rig.songs("marwa", "A")
    theirs = rig.playlist("marwa", refs)
    rig.set_item(refs[0], "failed", "RuntimeError: ffmpeg is not installed")

    foreign = retry(rig, "nina", {"kind": "playlist", "id": theirs})
    missing = retry(rig, "nina", {"kind": "playlist", "id": "pl_" + "0" * 26})
    unsaved = retry(rig, "nina", {"kind": "release", "id": "never-saved"})

    for refused in (foreign, missing, unsaved):
        assert refused.status_code == 404 and refused.json()["error"]["code"] == "not_found"
    assert foreign.json()["error"] == missing.json()["error"] == unsaved.json()["error"]
    assert rig.svc.scheduler.state_of("keep", refs[0])["state"] == "failed", "and nothing was started for her"  # type: ignore[index]


def test_a_request_that_is_not_one_known_download_is_refused_in_words(rig: Rig) -> None:
    for body in (
        {},
        {"kind": "album", "id": "x"},
        {"kind": "playlist"},
        {"kind": "release", "id": "x", "refs": "sr_1"},
        {"groups": [LIKED_GROUP]},
    ):
        refused = rig.client.post(f"{V1}/keep/retry", params=creds("marwa"), json=body)
        assert refused.status_code == 400 and refused.json()["error"]["code"] == "validation", body
    assert rig.client.post(f"{V1}/keep/retry", json=LIKED_GROUP).status_code == 401
