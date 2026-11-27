"""The Home page (W-02): the words, the facts the computer tells the server, and the route (P3-06 slice 4).

Proved here: every row says something a person understands and nothing is invented (a fact the server cannot know is said so); what needs somebody comes first and counts in
the sentence at the top, while resting and information never do; counts only, never a title; the file the computer writes is read as untrusted input; and the route is the
owner's and a 404 to the internet.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from encore_server import health, host_status
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.health import DAY_MS, Facts, build
from encore_server.host_status import HostStatus, LastBackup
from encore_server.ids import now_ms
from tests.conftest import FakeVerifier

NOW = 1_795_000_000_000
V1 = "/encore/api/v1"
HOME = {"X-Forwarded-For": "192.168.1.20"}
STRANGER = {"X-Forwarded-For": "203.0.113.9"}
PROXY = ("10.0.0.2", 50000)


def told(**more: object) -> HostStatus:
    base = HostStatus(
        NOW - 3600_000,
        LastBackup(NOW - 8 * 3600_000, 14_000_000, True),
        "https://our-music.tail1234.ts.net",
        NOW + 82 * DAY_MS,
        NOW - 5 * DAY_MS,
    )
    return replace(base, **more)  # type: ignore[arg-type]


def facts(**more: object) -> Facts:
    base = Facts(
        now=NOW,
        music_answers=True,
        youtube_state="ok",
        youtube_resumes_at=None,
        tools_degraded=False,
        away_url="https://our-music.tail1234.ts.net",
        free_bytes=412_000_000_000,
        floor_bytes=10_000_000_000,
        version="0.1.0",
        people=3,
        devices=4,
        last_sign_in=NOW - 3600_000,
        plays_today=212,
        imports_today=1,
        host=told(),
    )
    return replace(base, **more)  # type: ignore[arg-type]


def row(answer: dict, row_id: str) -> dict:  # type: ignore[type-arg]
    return next(r for r in answer["rows"] if r["id"] == row_id)


# ---------------------------------------------------------------------------------------------------------------------- the words


def test_when_everything_works_it_says_so_and_every_row_says_something() -> None:
    answer = build(facts())
    assert (
        answer["summary"]["state"] == "good"
        and answer["summary"]["words"] == "Everything is working."
        and answer["needsYou"] == []
    )
    assert [r["id"] for r in answer["rows"]] == ["music-server", "youtube", "away", "disk", "backup", "encore", "people", "today"]
    assert row(answer, "music-server")["words"] == "Working"
    assert row(answer, "away")["detail"] == "https://our-music.tail1234.ts.net · the key lasts another 82 days."
    assert row(answer, "disk")["words"] == "412 GB free" and row(answer, "disk")["detail"] == "Room for about 74,909 songs."
    assert row(answer, "backup")["detail"] == "14 MB. Locked."
    assert row(answer, "encore")["words"] == "Version 0.1.0"
    assert (
        row(answer, "people")["words"] == "3 people"
        and row(answer, "people")["detail"] == "4 devices. The last sign-in was today."
    )
    assert (
        row(answer, "today")["words"] == "212 songs played"
        and row(answer, "today")["detail"] == "1 import finished. Counts only, never titles. Since midnight UTC."
    )
    assert all(r["state"] == "ok" for r in answer["rows"])


def test_a_music_server_that_does_not_answer_needs_the_host_and_comes_first() -> None:
    answer = build(facts(music_answers=False))
    assert answer["summary"] == {"state": "needs", "words": "One thing needs you.", "checkedAt": NOW}
    assert (
        answer["needsYou"][0]["words"] == "Music server is not answering."
        and "sudo encore restart" in answer["needsYou"][0]["detail"]
    )
    assert (
        row(answer, "music-server")["state"] == "down"
        and row(answer, "music-server")["detail"] == "It usually comes back by itself."
    )


def test_the_key_of_the_away_address_warns_a_fortnight_ahead_and_after_it_ends() -> None:
    soon = build(facts(host=told(away_key_expires_at=NOW + 14 * DAY_MS - 1)))
    assert soon["needsYou"][0]["words"] == "The away-from-home key expires in 13 days." and soon["needsYou"][0]["page"] == "away"
    assert row(soon, "away")["state"] == "warn" and row(soon, "away")["words"] == "The key expires in 13 days"
    one = build(facts(host=told(away_key_expires_at=NOW + DAY_MS + 5)))
    assert one["needsYou"][0]["words"] == "The away-from-home key expires in 1 day."
    gone = build(facts(host=told(away_key_expires_at=NOW - DAY_MS)))
    assert (
        gone["needsYou"][0]["words"] == "The away-from-home key has expired."
        and row(gone, "away")["words"] == "The key has expired"
    )
    far = build(facts(host=told(away_key_expires_at=NOW + 15 * DAY_MS)))
    assert far["needsYou"] == []
    # the same, from a file that has gone quiet: the key's end is absolute, so it still warns, and says it may be out of date
    quiet = build(facts(host=told(written_at=NOW - 3 * DAY_MS, away_key_expires_at=NOW + 4 * DAY_MS)))
    assert quiet["needsYou"][0]["words"] == "The away-from-home key expires in 4 days."
    assert "last reported 3 days ago" in quiet["needsYou"][0]["detail"] and "next backup" in quiet["needsYou"][0]["detail"]


def test_an_address_that_is_not_set_up_is_not_a_problem_and_no_key_is_invented() -> None:
    off = build(facts(away_url=""))
    assert off["needsYou"] == [] and row(off, "away")["words"] == "Not set up"
    unknown_key = build(facts(host=told(away_key_expires_at=None)))
    assert row(unknown_key, "away")["detail"] == "https://our-music.tail1234.ts.net" and unknown_key["needsYou"] == []


def test_youtube_resting_is_shown_plainly_and_needs_nobody() -> None:
    answer = build(facts(youtube_state="resting", youtube_resumes_at=NOW + 3600_000))
    assert answer["needsYou"] == [] and answer["summary"]["state"] == "good"
    assert row(answer, "youtube")["state"] == "resting" and row(answer, "youtube")["restingUntil"] == NOW + 3600_000
    assert "starts again by itself" in row(answer, "youtube")["detail"]
    assert row(build(facts(youtube_state="off")), "youtube")["words"] == "Off"
    stale = row(build(facts(tools_degraded=True)), "youtube")
    assert stale["state"] == "warn" and "tries again by itself" in stale["detail"]


def test_a_full_disk_needs_the_host_and_an_unreadable_one_is_said_not_invented() -> None:
    low = build(facts(free_bytes=3_000_000_000))
    assert low["needsYou"][0]["words"] == "The disk is almost full." and row(low, "disk")["words"] == "3.0 GB free"
    unknown = build(facts(free_bytes=None))
    assert row(unknown, "disk")["state"] == "unknown" and unknown["needsYou"] == []


def test_the_backup_row_never_invents_what_only_the_computer_knows() -> None:
    nothing = build(facts(host=None))
    assert (
        row(nothing, "backup")["state"] == "unknown"
        and row(nothing, "backup")["words"] == "This computer has not told Encore yet."
    )
    assert nothing["needsYou"] == [] and nothing["summary"]["state"] == "good", (
        "not knowing is not a failure, and not 'all good' either: it is a row that says so"
    )
    # A status the computer has not rewritten for a while is STILL USED (a time of a backup is absolute: an old file can only make a warning come early), and says how old it is.
    stale = build(
        facts(host=told(written_at=NOW - 2 * DAY_MS, last_backup=LastBackup(NOW - 2 * DAY_MS - 3600_000, 9_000_000, True)))
    )
    assert row(stale, "backup")["state"] == "ok" and row(stale, "backup")["detail"].endswith(
        "The computer last reported 2 days ago."
    )
    assert stale["needsYou"] == []
    failing = build(
        facts(host=told(written_at=NOW - 4 * DAY_MS, last_backup=LastBackup(NOW - 4 * DAY_MS - 3600_000, 9_000_000, True)))
    )
    assert failing["summary"]["state"] == "needs" and failing["needsYou"][0]["words"] == "The last backup is 4 days old."
    assert "Everything is working." not in failing["summary"]["words"], "a backup that stopped is never 'all good'"
    assert row(failing, "backup")["state"] == "warn"
    future = build(facts(host=told(written_at=NOW + 5 * DAY_MS)))
    assert row(future, "backup")["state"] == "ok", "a file dated in the future (a clock that was behind) is still read"
    none_yet = build(facts(host=told(last_backup=None)))
    assert none_yet["needsYou"][0]["words"] == "There is no backup yet." and row(none_yet, "backup")["state"] == "warn"
    old = build(facts(host=told(last_backup=LastBackup(NOW - 5 * DAY_MS - 5, 9_000_000, False))))
    assert old["needsYou"][0]["words"] == "The last backup is 5 days old."
    assert row(old, "backup")["detail"] == "9 MB. Not locked: run sudo encore secure."
    last_night = build(facts(host=told(last_backup=LastBackup(NOW - 2 * DAY_MS, 9_000_000, True))))
    assert last_night["needsYou"] == []


def test_several_things_are_counted_in_the_sentence_and_listed_in_order() -> None:
    answer = build(facts(music_answers=False, free_bytes=1_000_000_000, host=told(away_key_expires_at=NOW + 3 * DAY_MS)))
    assert answer["summary"]["words"] == "3 things need you."
    assert [n["id"] for n in answer["needsYou"]] == ["music-server", "away-key", "disk"]


def test_a_person_alone_and_a_server_nobody_used_are_said_in_words() -> None:
    answer = build(facts(people=1, devices=1, last_sign_in=None, plays_today=1, imports_today=0))
    assert (
        row(answer, "people")["words"] == "1 person" and row(answer, "people")["detail"] == "1 device. Nobody has signed in yet."
    )
    assert (
        row(answer, "today")["words"] == "1 song played"
        and row(answer, "today")["detail"] == "Counts only, never titles. Since midnight UTC."
    )
    assert row(build(facts(last_sign_in=NOW - DAY_MS - 5)), "people")["detail"].endswith("The last sign-in was yesterday.")
    assert row(build(facts(last_sign_in=NOW - 12 * DAY_MS)), "people")["detail"].endswith("The last sign-in was 12 days ago.")
    assert row(build(facts(music_answers=None)), "music-server")["words"] == "Not set up"
    assert health.DAY_MS == 86_400_000


# ---------------------------------------------------------------------------------------------------------------------- what the computer tells the server


def status_file(folder: Path, body: object) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / host_status.HOST_STATUS_FILE).write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")


GOOD = {
    "writtenAt": NOW,
    "lastBackup": {"at": NOW - 3600_000, "bytes": 14_000_000, "locked": True},
    "away": {"address": "https://our-music.tail1234.ts.net", "keyExpiresAt": NOW + 82 * DAY_MS},
    "backupKey": {"madeAt": NOW - 5 * DAY_MS},
}


def test_a_status_the_computer_wrote_is_read(tmp_path: Path) -> None:
    status_file(tmp_path, GOOD)
    read = host_status.read(tmp_path)
    assert read is not None and read.fresh(NOW + 1000)
    assert read.last_backup == LastBackup(NOW - 3600_000, 14_000_000, True) and read.away_key_expires_at == NOW + 82 * DAY_MS
    assert read.away_address == "https://our-music.tail1234.ts.net" and read.backup_key_made_at == NOW - 5 * DAY_MS
    assert not read.fresh(NOW + 37 * 3600_000) and not read.fresh(NOW - 1), "too old, and a clock that is behind the file"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "not json",
        "[]",
        "null",
        '{"writtenAt": "yesterday"}',
        '{"writtenAt": true}',
        '{"writtenAt": 5}',
        '{"lastBackup": {}}',
        '{"writtenAt": 99999999999999999}',
    ],
)
def test_a_status_that_cannot_be_trusted_is_no_status(tmp_path: Path, body: str) -> None:
    status_file(tmp_path, body)
    assert host_status.read(tmp_path) is None


def test_a_status_with_odd_parts_keeps_what_is_sound_and_drops_the_rest(tmp_path: Path) -> None:
    status_file(
        tmp_path,
        {
            "writtenAt": NOW,
            "lastBackup": {"at": "tonight", "bytes": -3},
            "away": {"address": "javascript:alert(1)", "keyExpiresAt": "never"},
            "backupKey": 7,
            "extra": {"anything": 1},
        },
    )
    read = host_status.read(tmp_path)
    assert (
        read is not None
        and read.last_backup is None
        and read.away_address is None
        and read.away_key_expires_at is None
        and read.backup_key_made_at is None
    )
    status_file(tmp_path, {"writtenAt": NOW, "lastBackup": {"at": NOW, "bytes": -3, "locked": "yes"}})
    odd = host_status.read(tmp_path)
    assert odd is not None and odd.last_backup == LastBackup(NOW, 0, False)


def test_a_missing_or_huge_file_is_no_status(tmp_path: Path) -> None:
    assert host_status.read(tmp_path) is None
    status_file(tmp_path, json.dumps({"writtenAt": NOW, "pad": "x" * (host_status.MAX_BYTES + 10)}))
    assert host_status.read(tmp_path) is None


# ---------------------------------------------------------------------------------------------------------------------- the route


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        away_url="https://a.example",
    )
    with TestClient(create_app(settings, verifier=FakeVerifier()), client=PROXY) as client:
        yield client, settings.data_dir


def sign_in(client: TestClient, user: str) -> dict[str, str]:
    answer = client.post(
        f"{V1}/auth/login",
        json={"username": user, "password": f"pw-{user}", "deviceName": "browser", "deviceKind": "web"},
        headers=HOME,
    )
    assert answer.status_code == 200, answer.text
    return {"Authorization": f"Bearer {answer.json()['deviceToken']}", **HOME}


def test_the_owner_gets_the_home_page_and_nobody_else_does(rig: tuple[TestClient, Path]) -> None:
    client, _ = rig
    owner = sign_in(client, "marwa")
    answer = client.get(f"{V1}/admin/health", headers=owner)
    assert answer.status_code == 200
    body = answer.json()
    assert [r["id"] for r in body["rows"]] == ["music-server", "youtube", "away", "disk", "backup", "encore", "people", "today"]
    assert row(body, "people")["words"] == "1 person"
    assert row(body, "backup")["state"] == "unknown", "no computer has told the server anything yet"
    member = sign_in(client, "nina")
    assert client.get(f"{V1}/admin/health", headers=member).status_code == 403
    assert client.get(f"{V1}/admin/health", headers=HOME).status_code == 401
    unknown = client.get(f"{V1}/nothing-here", headers=STRANGER)
    assert client.get(f"{V1}/admin/health", headers={**owner, **STRANGER}).json() == unknown.json()


def test_the_route_says_what_the_computer_told_it_and_counts_what_people_did_without_a_title(
    rig: tuple[TestClient, Path],
) -> None:
    client, data = rig
    owner = sign_in(client, "marwa")
    status_file(
        data,
        {
            **GOOD,
            "writtenAt": now_ms(),
            "lastBackup": {"at": now_ms() - 3600_000, "bytes": 14_000_000, "locked": True},
            "away": {"address": "https://a.example", "keyExpiresAt": now_ms() + 3 * DAY_MS},
        },
    )
    svc = client.app.state.services  # type: ignore[attr-defined]
    with svc.db.tx() as conn:
        person = conn.execute("SELECT id FROM person").fetchone()[0]
        conn.execute(
            "INSERT INTO song_ref (id, norm_key, title, artists, duration_ms, created_at) VALUES ('sr_x', 'k', 'A Secret Title', '[\"A Secret Artist\"]', 1000, 1)"
        )
        for n in range(3):
            conn.execute(
                "INSERT INTO play_event (id, person, ref, at, ms_played) VALUES (?, ?, 'sr_x', ?, 1000)",
                (f"pl_{n}", person, now_ms()),
            )
        conn.execute(
            "INSERT INTO play_event (id, person, ref, at, ms_played) VALUES ('pl_old', ?, 'sr_x', 1000000000000, 1000)", (person,)
        )
    body = client.get(f"{V1}/admin/health", headers=owner).json()
    assert row(body, "today")["words"] == "3 songs played"
    assert "A Secret Title" not in json.dumps(body) and "A Secret Artist" not in json.dumps(body), "counts only, never titles"
    assert row(body, "backup")["state"] == "ok" and row(body, "backup")["detail"] == "14 MB. Locked."
    assert body["needsYou"][0]["words"] == "The away-from-home key expires in 2 days."
    assert body["summary"]["state"] == "needs"


def test_a_full_disk_on_this_computer_is_a_thing_that_needs_the_host(
    rig: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = rig
    owner = sign_in(client, "marwa")
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("encore_server.routes.admin_health.shutil.disk_usage", lambda path: usage(100, 99, 1_000_000_000))
    body = client.get(f"{V1}/admin/health", headers=owner).json()
    assert body["needsYou"][0]["id"] == "disk" and row(body, "disk")["words"] == "1.0 GB free"
    monkeypatch.setattr(
        "encore_server.routes.admin_health.shutil.disk_usage", lambda path: (_ for _ in ()).throw(OSError("gone"))
    )
    body = client.get(f"{V1}/admin/health", headers=owner).json()
    assert row(body, "disk")["state"] == "unknown" and body["needsYou"] == []
