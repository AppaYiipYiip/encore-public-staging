"""What the admin pages ask of the computer (P3-25 slice 6b; docs/36 sections 3 and 4): the helper client, and the owner-only routes for backups, the away address and a restart.

Proved here: the client speaks only the seven actions and trusts no answer beyond its shape (garbage lines dropped, a cut answer is "unavailable", a long one is capped); every route is the
owner's and a 404 to the internet; a helper that is not installed is a calm answer on a read and a 503 with the way to get it on a change; the helper's own sentence reaches the page (a refusal is a
409); a change leaves a line in `audit_log` (who, what, how, no secret) and a read leaves none; and nothing but a listed action is ever sent.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.helper import ACTIONS, NOT_INSTALLED, HelperAnswer, HelperClient, HelperUnavailable
from tests.conftest import FakeVerifier, says

V1 = "/encore/api/v1"
PROXY = ("10.0.0.2", 50000)
HOME = {"X-Forwarded-For": "192.168.1.20"}
STRANGER = {"X-Forwarded-For": "203.0.113.9"}
TOKEN = "T" * 40


# ---------------------------------------------------------------------------------------------------------------------- the client


def served(answer: bytes, seen: list[str]) -> HelperClient:
    """A client whose connection ends at a thread that plays the helper: it reads the request line, remembers it and sends [answer]."""

    def connect() -> socket.socket:
        ours, theirs = socket.socketpair()

        def play() -> None:
            line = b""
            while not line.endswith(b"\n"):
                line += theirs.recv(200)
            seen.append(line.decode().strip())
            with contextlib.suppress(OSError):  # the client stopped reading (an answer that is too long)
                theirs.sendall(answer)
            theirs.close()

        threading.Thread(target=play, daemon=True).start()
        return ours

    return HelperClient("/run/encore/helper.sock", TOKEN, timeout=5.0, connect=connect)


def test_the_client_sends_one_line_and_reads_the_four_kinds_of_line() -> None:
    seen: list[str] = []
    answer = b"result: helper=1\nresult: away=https://x.example\nitem: admin a.age 30 1790000000 locked\nitem: computer b.gz 20 1780000000 plain\ndone: ok\n"
    got = served(answer, seen).call("backup.list")
    assert seen == [f"{TOKEN} backup.list"]
    assert got.results == {"helper": "1", "away": "https://x.example"} and got.done == "ok" and got.failed is None
    assert got.items == [["admin", "a.age", "30", "1790000000", "locked"], ["computer", "b.gz", "20", "1780000000", "plain"]]


def test_a_refusal_is_the_helpers_own_sentence() -> None:
    got = served(b"failed: Wait ten minutes, or make one at the computer: sudo encore backup\n", []).call("backup.make")
    assert got.failed == "Wait ten minutes, or make one at the computer: sudo encore backup" and got.done is None


def test_what_is_not_one_of_the_four_kinds_is_dropped() -> None:
    got = served(b"progress: 50%\nnonsense\nresult: nokey\nitem\n\nresult: a=b\ndone: fine\nextra: ignored\n", []).call("status")
    assert got.results == {"a": "b"} and got.items == [] and got.done == "fine"


@pytest.mark.parametrize("answer", [b"", b"result: helper=1\n", b"progress: working\n"])
def test_an_answer_that_does_not_end_is_an_unavailable_helper(answer: bytes) -> None:
    with pytest.raises(HelperUnavailable, match="did not finish"):
        served(answer, []).call("status")


def test_an_answer_that_never_stops_is_capped_and_unavailable() -> None:
    with pytest.raises(HelperUnavailable):
        served(b"result: a=b\n" * 20000, []).call("status")


@pytest.mark.parametrize(
    "action",
    [
        "restore.apply",
        "update.apply",
        "shell",
        "",
        "STATUS",
        "status\nbackup.make",
        "backup.make x",
        "away",
        "backup.verify",
        "addon.enable",
    ],
)
def test_nothing_but_a_listed_action_ever_leaves_this_process(action: str) -> None:
    connected: list[int] = []

    def connect() -> socket.socket:
        connected.append(1)
        raise AssertionError("it connected")

    with pytest.raises(ValueError):
        HelperClient("x", TOKEN, connect=connect).call(action)
    assert connected == []


def test_there_are_seven_actions_and_restore_and_update_are_not_among_them() -> None:
    assert {"status", "backup.make", "backup.list", "away.status", "away.on", "away.off", "restart"} == ACTIONS


def test_a_computer_without_the_helper_says_how_to_get_it(tmp_path: Path) -> None:
    client = HelperClient(str(tmp_path / "no-such.sock"), TOKEN)
    assert not client.available()
    with pytest.raises(HelperUnavailable) as raised:
        client.call("status")
    assert raised.value.message == NOT_INSTALLED and "sudo encore helper install" in NOT_INSTALLED


def test_the_client_is_made_only_when_the_settings_name_a_socket_and_a_token() -> None:
    assert HelperClient.from_settings(Settings()) is None
    assert HelperClient.from_settings(Settings(helper_socket="/run/encore/helper.sock")) is None
    assert HelperClient.from_settings(Settings(helper_token=TOKEN)) is None
    assert HelperClient.from_settings(Settings(helper_socket="/run/encore/helper.sock", helper_token=TOKEN)) is not None
    assert TOKEN not in repr(Settings(helper_token=TOKEN))
    env = {"ENCORE_HELPER_SOCKET": "/run/encore/helper.sock", "ENCORE_HELPER_TOKEN": TOKEN}
    assert Settings.from_env(env).helper_socket == "/run/encore/helper.sock" and Settings.from_env(env).helper_token == TOKEN


# ---------------------------------------------------------------------------------------------------------------------- the routes


class FakeHelper:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.answers: dict[str, HelperAnswer] = {}
        self.present = True
        self.raises: Exception | None = None

    def available(self) -> bool:
        return self.present

    def state(self) -> str:
        return "ready" if self.present else "missing"

    def call(self, action: str) -> HelperAnswer:
        self.calls.append(action)
        if self.raises is not None:
            raise self.raises
        return self.answers.get(action, HelperAnswer(done="ok"))


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[tuple[TestClient, FakeHelper, Settings]]:
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        away_url="https://our-music.tail1234.ts.net",
    )
    helper = FakeHelper()
    with TestClient(create_app(settings, verifier=FakeVerifier(), helper=helper), client=PROXY) as client:  # type: ignore[arg-type]
        yield client, helper, settings


def sign_in(client: TestClient, user: str) -> dict[str, str]:
    answer = client.post(
        f"{V1}/auth/login",
        json={"username": user, "password": f"pw-{user}", "deviceName": "browser", "deviceKind": "web"},
        headers=HOME,
    )
    assert answer.status_code == 200, answer.text
    return {"Authorization": f"Bearer {answer.json()['deviceToken']}", **HOME}


ROUTES = [
    ("get", "/admin/helper"),
    ("get", "/admin/backups"),
    ("post", "/admin/backups"),
    ("get", "/admin/away"),
    ("post", "/admin/away/on"),
    ("post", "/admin/away/off"),
    ("post", "/admin/restart"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_is_the_owners_and_a_404_to_the_internet(
    rig: tuple[TestClient, FakeHelper, Settings], method: str, path: str
) -> None:
    client, helper, _ = rig
    owner = sign_in(client, "marwa")
    member = sign_in(client, "nina")
    send = getattr(client, method)
    assert send(f"{V1}{path}", headers=member).status_code == 403
    assert send(f"{V1}{path}", headers=HOME).status_code == 401
    unknown = client.get(f"{V1}/nothing-here", headers=HOME).json()
    away = send(f"{V1}{path}", headers={**owner, **STRANGER})
    assert away.status_code == 404 and says(away.json()) == says(unknown)
    assert helper.calls == [], "the helper was never asked for a stranger, a member or nobody"
    assert send(f"{V1}{path}", headers=owner).status_code in (200, 409)


def audit_lines(client: TestClient) -> list[str]:
    with client.app.state.services.db.read() as conn:  # type: ignore[attr-defined]
        return [r["detail"] for r in conn.execute("SELECT detail FROM audit_log ORDER BY id")]


def test_the_backups_page_lists_newest_first_and_drops_what_is_not_an_item(rig: tuple[TestClient, FakeHelper, Settings]) -> None:
    client, helper, _ = rig
    owner = sign_in(client, "marwa")
    helper.answers["backup.list"] = HelperAnswer(
        items=[
            ["computer", "encore-backup-1.tar.gz.age", "100", "1700000000", "locked"],
            ["admin", "encore-backup-2.tar.gz.age", "200", "1790000000", "locked"],
            ["computer", "encore-backup-3.tar.gz", "300", "1780000000", "plain"],
            ["broken"],
            ["admin", "x", "notanumber", "1", "locked"],
        ],
        done="ok",
    )
    body = client.get(f"{V1}/admin/backups", headers=owner).json()
    assert body["installed"] is True and body["nightlyAt"] == "03:30" and body["restore"] == "sudo encore restore FILE"
    assert [(b["pool"], b["name"], b["bytes"], b["madeAt"], b["locked"]) for b in body["items"]] == [
        ("admin", "encore-backup-2.tar.gz.age", 200, 1790000000000, True),
        ("computer", "encore-backup-3.tar.gz", 300, 1780000000000, False),
        ("computer", "encore-backup-1.tar.gz.age", 100, 1700000000000, True),
    ]
    assert audit_lines(client) == [], "a read leaves no line"


def test_without_a_helper_a_read_is_calm_and_a_change_says_how_to_get_it(rig: tuple[TestClient, FakeHelper, Settings]) -> None:
    client, helper, _ = rig
    owner = sign_in(client, "marwa")
    helper.present = False
    state = client.get(f"{V1}/admin/helper", headers=owner).json()
    assert state["installed"] is False and state["how"] == "sudo encore helper install"
    backups = client.get(f"{V1}/admin/backups", headers=owner)
    assert backups.status_code == 200 and backups.json()["installed"] is False and backups.json()["items"] == []
    away = client.get(f"{V1}/admin/away", headers=owner).json()
    assert (
        away["installed"] is False and away["tailscale"] == "unknown" and away["address"] == "https://our-music.tail1234.ts.net"
    )
    for path in ("/admin/backups", "/admin/away/on", "/admin/away/off", "/admin/restart"):
        answer = client.post(f"{V1}{path}", headers=owner)
        assert answer.status_code == 503 and answer.json()["error"]["message"] == NOT_INSTALLED, path
    assert helper.calls == [] and audit_lines(client) == []


def test_a_change_goes_to_the_helper_leaves_one_line_and_returns_its_words(rig: tuple[TestClient, FakeHelper, Settings]) -> None:
    client, helper, _ = rig
    owner = sign_in(client, "marwa")
    helper.answers["backup.make"] = HelperAnswer(done="A backup was made.")
    helper.answers["away.on"] = HelperAnswer(done="The away address is on.")
    helper.answers["away.off"] = HelperAnswer(done="The away address is off.")
    helper.answers["restart"] = HelperAnswer(done="Restarting. The admin pages will not answer for about a minute.")
    made = client.post(f"{V1}/admin/backups", headers=owner).json()
    on = client.post(f"{V1}/admin/away/on", headers=owner).json()
    off = client.post(f"{V1}/admin/away/off", headers=owner).json()
    again = client.post(f"{V1}/admin/restart", headers=owner).json()
    assert made["done"] == "A backup was made." and on["done"] == "The away address is on." and on["reconnects"] is True
    assert off["done"] == "The away address is off." and again["done"].startswith("Restarting.")
    assert helper.calls == ["backup.make", "away.on", "away.off", "restart"] and set(helper.calls) <= ACTIONS
    lines = audit_lines(client)
    assert lines == [f"{a} was asked from the admin pages by marwa: done" for a in helper.calls]


def test_the_helpers_refusal_reaches_the_page_in_its_own_sentence_as_a_409_and_is_recorded(
    rig: tuple[TestClient, FakeHelper, Settings],
) -> None:
    client, helper, _ = rig
    owner = sign_in(client, "marwa")
    sentence = "Set up the away address once at the computer: sudo encore funnel on"
    helper.answers["away.on"] = HelperAnswer(failed=sentence)
    answer = client.post(f"{V1}/admin/away/on", headers=owner)
    assert answer.status_code == 409 and answer.json()["error"]["message"] == sentence
    assert audit_lines(client) == [f"away.on was asked from the admin pages by marwa: refused: {sentence}"]


def test_a_helper_that_cannot_be_reached_is_a_503_and_leaves_no_line_for_something_that_did_not_happen(
    rig: tuple[TestClient, FakeHelper, Settings],
) -> None:
    client, helper, _ = rig
    owner = sign_in(client, "marwa")
    helper.raises = HelperUnavailable("The helper did not answer. Is it running? sudo systemctl status encore-helper.socket")
    answer = client.post(f"{V1}/admin/backups", headers=owner)
    assert answer.status_code == 503 and "Is it running?" in answer.json()["error"]["message"]
    assert audit_lines(client) == []


def test_the_away_page_has_the_address_tailscales_state_and_the_key_end(rig: tuple[TestClient, FakeHelper, Settings]) -> None:
    client, helper, settings = rig
    owner = sign_in(client, "marwa")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    ends = 1_795_000_000_000 + 40 * 86_400_000
    status = {"writtenAt": 1_795_000_000_000, "away": {"address": "https://our-music.tail1234.ts.net", "keyExpiresAt": ends}}
    (settings.data_dir / "host-status.json").write_text(json.dumps(status), encoding="utf-8")
    helper.answers["away.status"] = HelperAnswer(
        results={"address": "https://our-music.tail1234.ts.net", "tailscale": "ready"}, done="ok"
    )
    body: dict[str, Any] = client.get(f"{V1}/admin/away", headers=owner).json()
    assert body["installed"] is True and body["tailscale"] == "ready" and body["keyExpiresAt"] == ends
    assert body["address"] == "https://our-music.tail1234.ts.net" and body["how"] == "sudo encore funnel on"
    helper.answers["away.status"] = HelperAnswer(results={"tailscale": "signedout"}, done="ok")
    assert client.get(f"{V1}/admin/away", headers=owner).json()["tailscale"] == "signedout"


def test_no_route_ever_asks_for_anything_but_a_listed_action_and_no_secret_is_recorded(
    rig: tuple[TestClient, FakeHelper, Settings],
) -> None:
    client, helper, _ = rig
    owner = sign_in(client, "marwa")
    for method, path in ROUTES:
        getattr(client, method)(f"{V1}{path}", headers=owner)
    assert set(helper.calls) <= ACTIONS and "restore.apply" not in helper.calls and "update.apply" not in helper.calls
    assert TOKEN not in json.dumps(audit_lines(client))


def test_a_socket_this_process_may_not_open_is_there_but_says_so_in_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Found by the real-install job: the server process had lost the helper's group (the entrypoint reset its groups) and `Path.exists()` raised PermissionError, which made Home answer 500.
    The helper is *there*; asking it is what explains."""
    client = HelperClient(str(tmp_path / "helper.sock"), TOKEN)

    def refuse(self: Path, *args: object, **kwargs: object) -> object:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "stat", refuse)
    assert client.available() is True, "never an exception"
    assert client.state() == "cannot-open", 'not "ready": Home must not say so'

    def deny() -> socket.socket:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(client, "_open", deny)
    with pytest.raises(
        HelperUnavailable, match="may not open the helper's socket.*sudo encore helper install.*sudo encore restart"
    ):
        client.call("status")


def test_a_path_that_is_odd_is_simply_not_a_helper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = HelperClient(str(tmp_path / "helper.sock"), TOKEN)

    def odd(self: Path, *args: object, **kwargs: object) -> object:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(Path, "stat", odd)
    assert client.available() is False


def test_a_socket_that_is_there_but_not_writable_for_this_process_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review of #160: connecting to a unix socket needs write permission on the socket, so that is the honest test of "ready"."""
    sock = tmp_path / "helper.sock"
    sock.write_text("", encoding="utf-8")  # a path that exists; the test only asks about permission
    client = HelperClient(str(sock), TOKEN)
    monkeypatch.setattr("encore_server.helper.os.access", lambda path, mode: True)
    assert client.state() == "ready"
    monkeypatch.setattr("encore_server.helper.os.access", lambda path, mode: False)
    assert client.state() == "cannot-open" and client.available() is True
    assert HelperClient(str(tmp_path / "missing.sock"), TOKEN).state() == "missing"


def test_a_change_that_takes_long_says_it_may_still_be_running() -> None:
    """Review of #160: a backup of a big library can outlast the client's wait; the page must not say it failed."""
    from encore_server.helper import TIMEOUTS

    assert TIMEOUTS["backup.make"] > 90, "a backup gets longer than a read, and less than the helper session's own 300 seconds"
    assert TIMEOUTS["backup.make"] < 300

    def connect() -> socket.socket:
        ours, theirs = socket.socketpair()
        theirs.close()  # nothing ever comes: the read times out
        ours.settimeout(0.05)
        return ours

    client = HelperClient("x", TOKEN, timeout=0.05, connect=connect)
    with pytest.raises(HelperUnavailable) as raised:
        client.call("status")
    assert raised.value.message  # a closed connection with no answer is an unfinished answer
