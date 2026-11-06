"""`POST /keep/ask` (P2-22, B-62, docs/17 "Keep progress"): pressing Download on a playlist or the liked songs asks the server for the songs it does not have
yet, first in line behind a single tap. This is the batched sibling of `POST refs/{id}/keep`, and it is what `keep/watch` must never do (asking changes
nothing there)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from tests.conftest import FakeVerifier, creds
from tests.test_keep_progress import V1, Rig, buckets, build_rig, only

LIKED_GROUP = {"kind": "liked", "id": "liked"}


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier, monkeypatch: pytest.MonkeyPatch) -> Iterator[Rig]:
    yield from build_rig(tmp_path, verifier, monkeypatch)


def ask(rig: Rig, user: str, *groups: dict[str, Any]) -> Any:
    return rig.client.post(f"{V1}/keep/ask", params=creds(user), json={"groups": list(groups)})


def priority_of(rig: Rig, ref: str) -> int:
    with rig.svc.db.read() as conn:
        row = conn.execute(
            "SELECT priority FROM work_item WHERE kind = 'keep' AND ref = ? AND state = 'queued'", (ref,)
        ).fetchone()
    assert row is not None, f"{ref} is not waiting in the queue"
    return int(row["priority"])


def test_asking_wants_what_nobody_is_getting_and_leaves_the_rest_alone(rig: Rig) -> None:
    ready, keeping, waiting, flaky, gone, never, lost = rig.songs(
        "marwa", "Ready", "Keeping", "Waiting", "Flaky", "Gone", "Never", "Lost"
    )
    for ref in (ready, keeping, waiting, flaky, gone, never, lost):
        rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    rig.svc.scheduler.drain()
    with rig.svc.db.tx() as conn:
        conn.execute("DELETE FROM song_file WHERE ref != ?", (ready,))
    rig.set_item(keeping, "running")
    rig.set_item(waiting, "queued")
    rig.set_item(flaky, "failed", "RuntimeError: ffmpeg is not installed")
    rig.set_item(gone, "failed", "no upload of this song was found")
    rig.drop_item(never)
    rig.set_item(lost, "done")

    answer = ask(rig, "marwa", LIKED_GROUP)

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["asked"] == 3, "the one that waits, the one nobody tried, the one whose file is gone"
    group = only(body)
    assert buckets(group) == (1, 1, 3, 2), "being kept now is left alone, and so are the two whose keep failed (Retry is theirs)"
    assert {f["ref"] for f in group["failures"]} == {flaky, gone}
    assert body["youtube"]["state"] == "off" and isinstance(body["serverTime"], int)

    for ref in (waiting, never, lost):
        assert priority_of(rig, ref) == 2, "a whole download asked for at once goes ahead of the background work"
    rig.svc.scheduler.drain()
    assert buckets(only(rig.ask("marwa", LIKED_GROUP))) == (4, 1, 0, 2), "and the three asked-for songs really were fetched"


def test_a_song_whose_keep_failed_is_never_tried_again_by_asking_only_by_retry(rig: Rig) -> None:
    """A phone says what it wants again every time it connects. If asking revived a failed song, every start of the app would hit YouTube again from the Host's
    address for ever; the person sees "1 song did not come" with a Retry button and chooses."""
    (flaky,) = rig.songs("marwa", "Flaky")
    rig.client.put(f"{V1}/likes/{flaky}", params=creds("marwa"))
    rig.set_item(flaky, "failed", "RuntimeError: ffmpeg is not installed")

    for _ in range(3):
        assert ask(rig, "marwa", LIKED_GROUP).json()["asked"] == 0
    assert rig.svc.scheduler.state_of("keep", flaky)["state"] == "failed"  # type: ignore[index]
    assert rig.source.asked == []

    assert rig.client.post(f"{V1}/keep/retry", params=creds("marwa"), json=LIKED_GROUP).json()["retried"] == 1
    rig.svc.scheduler.drain()
    assert [s.title for s in rig.source.asked] == ["Flaky"]


def test_a_download_asked_for_goes_before_older_keeps_and_behind_a_single_tap(rig: Rig) -> None:
    """The reason it is a level of its own: if the whole download were promoted like one tap, 200 songs would stand in front of the next person's
    tap (the scheduler looks at the first 200 items only, B-39)."""
    older, tapped, first, second = rig.songs("marwa", "Older", "Tapped", "First", "Second")
    rig.client.put(f"{V1}/likes/{older}", params=creds("marwa"))  # asked long ago, in the background
    playlist = rig.playlist("nina", [first, second])
    rig.client.put(f"{V1}/likes/{tapped}", params=creds("marwa"))

    assert ask(rig, "nina", {"kind": "playlist", "id": playlist}).json()["asked"] == 2
    assert rig.client.post(f"{V1}/refs/{tapped}/keep", params=creds("marwa")).status_code == 200

    assert priority_of(rig, tapped) == 0 and priority_of(rig, first) == 2 and priority_of(rig, older) == 4
    for _ in range(4):
        rig.svc.scheduler.run_one("background")
    assert [s.title for s in rig.source.asked] == ["Tapped", "First", "Second", "Older"]


def test_asking_twice_queues_nothing_twice_and_never_lowers_a_song_somebody_tapped(rig: Rig) -> None:
    tapped, other = rig.songs("marwa", "Tapped", "Other")
    for ref in (tapped, other):
        rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    rig.client.post(f"{V1}/refs/{tapped}/keep", params=creds("marwa"))

    first = ask(rig, "marwa", LIKED_GROUP).json()
    second = ask(rig, "marwa", LIKED_GROUP).json()

    assert first["asked"] == second["asked"] == 2
    with rig.svc.db.read() as conn:
        queued = conn.execute(
            "SELECT ref, COUNT(*) AS n FROM work_item WHERE kind = 'keep' AND state = 'queued' GROUP BY ref"
        ).fetchall()
    assert {r["ref"]: r["n"] for r in queued} == {tapped: 1, other: 1}
    assert priority_of(rig, tapped) == 0, "a tap is still ahead of the download that asked later"
    assert priority_of(rig, other) == 2


def test_asking_again_and_again_never_ends_a_pause_only_a_tap_on_the_song_does(rig: Rig) -> None:
    """The pause can be the scheduler's own back-off after a YouTube hiccup or YouTube's rest. The phone re-asks on every connection."""
    paused, other = rig.songs("marwa", "Paused", "Other")
    for ref in (paused, other):
        rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
    with rig.svc.db.tx() as conn:
        conn.execute("UPDATE work_item SET next_try_at = next_try_at + 3600000 WHERE kind = 'keep' AND ref = ?", (paused,))

    asked = []
    for _ in range(3):
        asked.append(ask(rig, "marwa", LIKED_GROUP).json()["asked"])
        rig.svc.scheduler.drain()
    assert asked == [2, 1, 1], (
        "'Other' is fetched after the first round; the paused song is asked for each time and waits each time"
    )

    assert [s.title for s in rig.source.asked] == ["Other"], "the paused song was not tried, however often the phone asked"
    assert priority_of(rig, paused) == 2

    assert rig.client.post(f"{V1}/refs/{paused}/keep", params=creds("marwa")).status_code == 200
    rig.svc.scheduler.drain()
    assert [s.title for s in rig.source.asked] == ["Other", "Paused"], "but a tap on that song ends its pause, as before"


def test_a_person_can_only_ask_for_their_own_downloads(rig: Rig) -> None:
    refs = rig.songs("marwa", "A", "B")
    theirs = rig.playlist("marwa", refs)
    rig.set_item(refs[0], "failed", "RuntimeError: ffmpeg is not installed")

    foreign = ask(
        rig,
        "nina",
        {"kind": "playlist", "id": theirs},
        {"kind": "playlist", "id": "pl_" + "0" * 26},
        {"kind": "release", "id": "never-saved"},
    )

    assert foreign.status_code == 200, (
        "a group she does not have is left out, exactly like one that does not exist (keep/progress)"
    )
    assert foreign.json()["asked"] == 0 and foreign.json()["groups"] == []
    assert rig.svc.scheduler.state_of("keep", refs[0])["state"] == "failed", "and nothing was started for her"  # type: ignore[index]
    assert priority_of(rig, refs[1]) == 4, "nor was marwa's other song moved"


def test_a_release_is_asked_by_its_stored_songs_and_a_member_reads_the_plain_words(rig: Rig) -> None:
    first, second, third = rig.songs("marwa", "Nude", "Reckoner", "Airbag")
    rig.client.put(f"{V1}/saved-albums/cat-1", params=creds("nina"), json={"refs": [first, second, third]})
    rig.drop_item(first)
    rig.set_item(second, "failed", "no upload of this song was found")
    rig.set_item(third, "running")

    body = ask(rig, "nina", {"kind": "release", "id": "cat-1"}).json()

    assert body["asked"] == 1, "only the one nobody tried"
    assert only(body)["failures"][0]["reason"] == "Not found.", "a member reads the plain fact; the Host reads the cause"


def test_several_downloads_in_one_request_and_a_song_in_two_of_them_is_asked_once(rig: Rig) -> None:
    shared, only_liked = rig.songs("marwa", "Shared", "OnlyLiked")
    playlist = rig.playlist("marwa", [shared])
    for ref in (shared, only_liked):
        rig.client.put(f"{V1}/likes/{ref}", params=creds("marwa"))

    body = ask(rig, "marwa", {"kind": "playlist", "id": playlist}, LIKED_GROUP).json()

    assert body["asked"] == 2 and [g["kind"] for g in body["groups"]] == ["playlist", "liked"]


def test_a_download_the_save_of_a_release_and_a_retry_are_all_whole_downloads_not_taps(rig: Rig) -> None:
    """The three calls that used to push every song of a download to the level of one tap, up to 500 of them."""
    first, second, flaky = rig.songs("marwa", "First", "Second", "Flaky")
    rig.client.put(f"{V1}/saved-albums/cat-9", params=creds("nina"), json={"refs": [first, second]})
    rig.client.put(f"{V1}/likes/{flaky}", params=creds("marwa"))
    rig.set_item(flaky, "failed", "RuntimeError: ffmpeg is not installed")
    assert rig.client.post(f"{V1}/keep/retry", params=creds("marwa"), json=LIKED_GROUP).json()["retried"] == 1

    assert priority_of(rig, first) == priority_of(rig, second) == priority_of(rig, flaky) == 2


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"groups": []},
        {"groups": [{"kind": "album", "id": "x"}]},
        {"groups": [{"kind": "playlist"}]},
        {"groups": "liked"},
        {"kind": "liked", "id": "liked"},
    ],
)
def test_a_request_that_names_no_known_download_is_refused_in_words(rig: Rig, body: dict[str, Any]) -> None:
    refused = rig.client.post(f"{V1}/keep/ask", params=creds("marwa"), json=body)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "validation" and refused.json()["error"]["message"]


def test_it_needs_a_login(rig: Rig) -> None:
    assert rig.client.post(f"{V1}/keep/ask", json={"groups": [LIKED_GROUP]}).status_code == 401


def test_the_app_is_told_by_the_features_that_the_server_can_be_asked(rig: Rig, tmp_path: Path, verifier: FakeVerifier) -> None:
    assert {"keep", "keep-ask"} <= set(rig.client.get(f"{V1}/info").json()["features"])

    settings = Settings(
        data_dir=tmp_path / "bare", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as bare:
        assert not {"keep", "keep-ask"} & set(bare.get(f"{V1}/info").json()["features"])
        refused = bare.post(f"{V1}/keep/ask", params=creds("marwa"), json={"groups": [LIKED_GROUP]})
        assert refused.status_code == 404 and refused.json()["error"]["message"] == "This server does not keep songs."
