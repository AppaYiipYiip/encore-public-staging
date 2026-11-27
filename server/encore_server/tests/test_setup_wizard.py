"""The first run in the browser (P3-06 slice 5a; docs/36 section 2, "The first run is a takeover risk", hidden risk H36).

Proved here, because each of these is the difference between a server that a stranger on the Wi-Fi can take and one that cannot:

* the setup code: its alphabet, how a typed one is read, a constant-time comparison, and a configured code that is not well formed never opens anything;
* the first-run routes exist only while a code is configured AND nobody exists: otherwise (and from the internet) they answer exactly what an unknown route answers;
* a wrong or missing code is refused and counted, five a minute from one address and thirty in all, with a wait that says how long, by the address the server trusts;
* the owner is made once: validation first and nothing made when it fails, a music-server failure leaves the step open and retryable, two browsers that post at once make ONE
  owner (the lock), and even a person who appears between the check and the write (another process) is caught inside the transaction;
* what comes back is a browser session that works and ends like any other, and a marker is left for the command on the computer to take the code out of `.env`;
* the pages: the page opens only while the server waits, holds no code, and the short address keeps the query.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server import owner_setup, setup_code
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.setup import SetupError, SetupResult
from tests.conftest import FakeVerifier

V1 = "/encore/api/v1"
CODE = "7KQ-4MZ"
PROXY = ("10.0.0.2", 50000)
HOME = {"X-Forwarded-For": "192.168.1.20"}
STRANGER = {"X-Forwarded-For": "203.0.113.9"}


# ---------------------------------------------------------------------------------------------------------------------- the code itself


def test_the_alphabet_has_no_lookalikes_and_a_made_code_is_well_formed() -> None:
    assert len(set(setup_code.ALPHABET)) == 31 and not set("0O1IL") & set(setup_code.ALPHABET)
    for _ in range(200):
        made = setup_code.new_code()
        assert setup_code.well_formed(made) and len(made) == 7 and made[3] == "-"


def test_a_typed_code_is_read_the_way_a_person_writes_it() -> None:
    assert setup_code.normalize(" 7kq 4mz ") == "7KQ4MZ" and setup_code.normalize("7KQ-4MZ\n") == "7KQ4MZ"
    assert setup_code.show("7kq4mz") == "7KQ-4MZ"
    for bad in (None, 5, [], "", "7KQ-4M", "7KQ-4MZZ", "7KQ-4M0", "7KQ-4MO", "7KQ-4M!"):
        assert not setup_code.well_formed(bad), bad


def test_only_the_configured_code_matches_and_a_weak_configured_one_never_does() -> None:
    assert setup_code.matches(CODE, "7kq4mz") and setup_code.matches(CODE, " 7KQ-4MZ ")
    assert not setup_code.matches(CODE, "7KQ-4MY") and not setup_code.matches(CODE, None) and not setup_code.matches(CODE, "")
    assert not setup_code.matches("", "") and not setup_code.matches("1234", "1234"), (
        "an empty or hand-made weak code opens nothing"
    )
    assert not setup_code.matches("AAAAAAAA", "AAAAAAAA")


def test_the_code_is_not_in_the_printed_form_of_the_settings() -> None:
    """A Settings that is printed (a log line, a test failure) must not carry the code."""
    assert CODE not in repr(Settings.from_env({"ENCORE_SETUP_CODE": CODE})) and "7KQ4MZ" not in repr(Settings(setup_code=CODE))


def test_settings_take_a_well_formed_code_and_ignore_the_rest() -> None:
    assert Settings.from_env({"ENCORE_SETUP_CODE": "7kq 4mz"}).setup_code == CODE
    assert Settings.from_env({"ENCORE_SETUP_CODE": CODE}).setup_code == CODE
    for env in ({}, {"ENCORE_SETUP_CODE": ""}, {"ENCORE_SETUP_CODE": "abc"}, {"ENCORE_SETUP_CODE": "7KQ-4M0"}):
        assert Settings.from_env(env).setup_code == "", env


# ---------------------------------------------------------------------------------------------------------------------- the routes


class Maker:
    """The music server's side of the first run: records what it was asked, and can fail or take its time."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail: str | None = None
        self.delay = 0.0
        self.before_return: Callable[[], None] | None = None

    def __call__(self, settings: Settings, owner: dict[str, Any]) -> SetupResult:
        self.calls.append(dict(owner))
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise SetupError(self.fail)
        if self.before_return:
            self.before_return()
        return SetupResult("created", "created")


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[tuple[TestClient, Maker, Settings]]:
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        server_name="Our music",
        setup_code=CODE,
    )
    maker = Maker()
    with TestClient(create_app(settings, verifier=FakeVerifier(), make_owner_account=maker), client=PROXY) as client:
        yield client, maker, settings


def code(value: str = CODE) -> dict[str, str]:
    return {**HOME, "X-Setup-Code": value}


OWNER = {"username": "riley", "password": "correct horse", "name": "Riley"}


def from_address(client: TestClient, address: str) -> TestClient:
    """The same application, asked from another computer of the house network (a connection from that address: the server counts the connection's own address)."""
    return TestClient(client.app, client=(address, 50000))


def unknown(client: TestClient) -> dict[str, Any]:
    return dict(client.get(f"{V1}/nothing-here", headers=HOME).json())


def test_with_the_right_code_the_server_says_it_waits_for_its_owner(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, _, _ = rig
    answer = client.get(f"{V1}/setup/state", headers=code())
    state = answer.json()
    assert answer.status_code == 200 and state["needsOwner"] is True and state["serverName"] == "Our music"
    assert client.get(f"{V1}/setup/state", headers=code("7kq 4mz")).status_code == 200, "typed the way a person types it"


def test_no_code_configured_means_the_first_run_does_not_exist(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=FakeVerifier(), make_owner_account=Maker()), client=PROXY) as client:
        for answer in (
            client.get(f"{V1}/setup/state", headers=code()),
            client.post(f"{V1}/setup/owner", json=OWNER, headers=code()),
        ):
            assert answer.status_code == 404 and answer.json() == unknown(client)
        assert client.get("/encore/setup", headers=HOME, follow_redirects=False).status_code == 302


def test_from_the_internet_every_first_run_address_is_the_unknown_route(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, maker, _ = rig
    away = {**STRANGER, "X-Setup-Code": CODE}
    expected = unknown(client)
    for answer in (
        client.get(f"{V1}/setup/state", headers=away),
        client.post(f"{V1}/setup/owner", json=OWNER, headers=away),
        client.get("/encore/setup", headers=STRANGER, follow_redirects=False),
        client.get("/setup", headers=STRANGER, follow_redirects=False),
    ):
        assert answer.status_code == 404
    assert client.get(f"{V1}/setup/state", headers=away).json() == expected
    assert maker.calls == [], "nothing was made for a stranger who even had the code"


def test_a_wrong_or_missing_code_is_refused_and_counted(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, maker, _ = rig
    for n in range(5):
        wrong = client.get(f"{V1}/setup/state", headers=code("7KQ-4M" + "23456"[n]))
        assert wrong.status_code == 403 and "setup code is not right" in wrong.json()["error"]["message"]
    limited = client.get(f"{V1}/setup/state", headers=code("7KQ-4MY"))
    assert limited.status_code == 429 and limited.json()["error"]["retryAfterMs"] > 0
    assert "Wait a moment" in limited.json()["error"]["message"]
    # the right code is refused too while the address waits: a guesser is not allowed to keep asking
    assert client.get(f"{V1}/setup/state", headers=code()).status_code == 429
    assert client.post(f"{V1}/setup/owner", json=OWNER, headers=code()).status_code == 429
    # another address on the house network is not held up by it
    other = from_address(client, "192.168.1.77").get(f"{V1}/setup/state", headers={"X-Setup-Code": CODE})
    assert other.status_code == 200
    assert maker.calls == []


def test_a_missing_header_is_a_wrong_code(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, _, _ = rig
    assert client.get(f"{V1}/setup/state", headers=HOME).status_code == 403
    assert client.post(f"{V1}/setup/owner", json=OWNER, headers=HOME).status_code == 403


def test_guesses_from_many_addresses_meet_a_wall_in_all(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, _, _ = rig
    seen = [
        from_address(client, f"192.168.2.{n + 1}").get(f"{V1}/setup/state", headers={"X-Setup-Code": "7KQ-4MY"}).status_code
        for n in range(40)
    ]
    assert seen[:30] == [403] * 30 and set(seen[30:]) == {429}, "thirty wrong in all, then a wait for everybody"
    assert from_address(client, "192.168.9.9").get(f"{V1}/setup/state", headers={"X-Setup-Code": CODE}).status_code == 429


def test_the_limit_counts_the_address_the_server_trusts_not_one_a_client_wrote(rig: tuple[TestClient, Maker, Settings]) -> None:
    """A client that writes more addresses in front of its own does not get a fresh allowance: the right-most one that is not a proxy of ours counts."""
    client, _, _ = rig
    for n in range(5):
        client.get(f"{V1}/setup/state", headers={"X-Forwarded-For": f"10.9.9.{n}, 192.168.1.20", "X-Setup-Code": "7KQ-4MY"})
    assert (
        client.get(
            f"{V1}/setup/state", headers={"X-Forwarded-For": "10.1.1.1, 192.168.1.20", "X-Setup-Code": "7KQ-4MY"}
        ).status_code
        == 429
    )


def test_the_owner_is_made_once_with_a_working_browser_session(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, maker, settings = rig
    answer = client.post(f"{V1}/setup/owner", json=OWNER, headers=code())
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["person"] == {"id": body["person"]["id"], "name": "Riley", "role": "owner"} and body["deviceToken"]
    assert maker.calls == [{"username": "riley", "password": "correct horse", "name": "Riley"}]
    headers = {"Authorization": f"Bearer {body['deviceToken']}", **HOME}
    me = client.get(f"{V1}/me", headers=headers).json()
    assert me["username"] == "riley" and me["role"] == "owner" and me["name"] == "Riley"
    session = client.get(f"{V1}/admin/session", headers=headers).json()
    assert session["session"]["kind"] == "browser" and session["session"]["idleMs"], (
        "a browser session that the server ends like any other"
    )
    assert (settings.data_dir / owner_setup.MARKER).read_text(encoding="utf-8").strip() == "done"
    # the first run is closed for ever: 404, the unknown route's own answer, even with the right code
    for finished in (
        client.get(f"{V1}/setup/state", headers=code()),
        client.post(f"{V1}/setup/owner", json=OWNER, headers=code()),
    ):
        assert finished.status_code == 404 and finished.json() == unknown(client)
    assert len(maker.calls) == 1


def test_the_shown_name_defaults_to_the_username(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, maker, _ = rig
    body = client.post(f"{V1}/setup/owner", json={"username": "riley", "password": "correct horse"}, headers=code()).json()
    assert body["person"]["name"] == "riley" and maker.calls[0]["name"] == "riley"


@pytest.mark.parametrize(
    "body",
    [
        {"username": "", "password": "correct horse"},
        {"username": "ri", "password": "correct horse"},
        {"username": "riley", "password": "short"},
        {"username": "rileyriley", "password": "RileyRiley"},
        {"username": "a name with spaces", "password": "correct horse"},
        {"username": "admin", "password": "correct horse"},
        {"password": "correct horse"},
        {"username": 5, "password": "correct horse"},
    ],
)
def test_a_bad_name_or_password_is_refused_in_words_and_nothing_is_made(
    rig: tuple[TestClient, Maker, Settings], body: dict[str, Any]
) -> None:
    client, maker, settings = rig
    answer = client.post(f"{V1}/setup/owner", json=body, headers=code())
    assert answer.status_code in (400, 409) and answer.json()["error"]["message"], body
    assert maker.calls == [] and not (settings.data_dir / owner_setup.MARKER).exists()
    assert client.get(f"{V1}/setup/state", headers=code()).status_code == 200, "still waiting for its owner"


def test_a_music_server_that_cannot_make_the_account_leaves_the_step_open(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, maker, settings = rig
    maker.fail = "The music server is not answering."
    refused = client.post(f"{V1}/setup/owner", json=OWNER, headers=code())
    assert refused.status_code == 400 and refused.json()["error"]["message"] == "The music server is not answering."
    assert not (settings.data_dir / owner_setup.MARKER).exists()
    with settings_db(client).read() as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM person").fetchone()[0] == 0
            and conn.execute("SELECT COUNT(*) FROM device").fetchone()[0] == 0
        )
    maker.fail = None
    assert client.post(f"{V1}/setup/owner", json=OWNER, headers=code()).status_code == 201, "the same step, tried again"


def settings_db(client: TestClient) -> Any:
    return client.app.state.services.db  # type: ignore[attr-defined]


def test_two_browsers_posting_at_once_make_one_owner(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, maker, _ = rig
    maker.delay = 0.3
    results: list[tuple[int, str]] = []

    def post(name: str) -> None:
        answer = client.post(f"{V1}/setup/owner", json={"username": name, "password": "correct horse"}, headers=code())
        results.append((answer.status_code, name))

    threads = [threading.Thread(target=post, args=(name,)) for name in ("riley", "mallory")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(status for status, _ in results) == [201, 404], results
    assert len(maker.calls) == 1, "the loser never reached the music server"
    with settings_db(client).read() as conn:
        rows = conn.execute("SELECT navidrome_user, role FROM person").fetchall()
    assert len(rows) == 1 and rows[0]["role"] == "owner"


def test_a_person_who_appears_between_the_check_and_the_write_is_caught_in_the_transaction(
    rig: tuple[TestClient, Maker, Settings],
) -> None:
    """Another process (the server is one, but the database is shared) made somebody while this one was talking to the music server."""
    client, maker, settings = rig
    db = settings_db(client)

    def somebody_else() -> None:
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO person (id, navidrome_user, display_name, role, created_at) VALUES ('pn_x', 'mallory', 'Mallory', 'owner', 1)"
            )

    maker.before_return = somebody_else
    answer = client.post(f"{V1}/setup/owner", json=OWNER, headers=code())
    assert answer.status_code == 404
    with db.read() as conn:
        assert [r["navidrome_user"] for r in conn.execute("SELECT navidrome_user FROM person")] == ["mallory"]
        assert conn.execute("SELECT COUNT(*) FROM device").fetchone()[0] == 0, "no session for the loser"
    assert not (settings.data_dir / owner_setup.MARKER).exists()


def test_an_existing_person_closes_the_first_run_whatever_the_environment_says(rig: tuple[TestClient, Maker, Settings]) -> None:
    """The code may still be in `.env` (the command door tidies it later): the server ignores it from the moment anybody exists."""
    client, maker, _ = rig
    with settings_db(client).tx() as conn:
        conn.execute(
            "INSERT INTO person (id, navidrome_user, display_name, role, created_at) VALUES ('pn_a', 'marwa', 'Marwa', 'owner', 1)"
        )
    assert client.get(f"{V1}/setup/state", headers=code()).status_code == 404
    assert client.post(f"{V1}/setup/owner", json=OWNER, headers=code()).status_code == 404
    assert maker.calls == []


def test_a_server_without_a_way_to_make_accounts_says_so(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        setup_code=CODE,
    )
    with TestClient(create_app(settings, verifier=FakeVerifier()), client=PROXY) as client:
        services = client.app.state.services  # type: ignore[attr-defined]
        assert services.make_owner_account is not None, "the real one is in place by default"
        services.make_owner_account = None
        answer = client.post(f"{V1}/setup/owner", json=OWNER, headers=code())
        assert answer.status_code == 503


# ---------------------------------------------------------------------------------------------------------------------- the pages


def test_the_page_opens_while_the_server_waits_and_holds_no_code(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, _, _ = rig
    answer = client.get(f"/encore/setup?code={CODE}", headers=HOME)
    assert answer.status_code == 200 and "text/html" in answer.headers["content-type"]
    assert CODE not in answer.text and "script-src 'self'" in answer.headers["content-security-policy"]
    assert answer.headers["referrer-policy"] == "no-referrer" and answer.headers["cache-control"] == "no-store"
    assert "<script>" not in answer.text and "style=" not in answer.text, "no inline script or style"
    assert client.head("/encore/setup", headers=HOME).status_code == 200


def test_the_short_address_goes_to_the_page_and_keeps_the_code(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, _, _ = rig
    answer = client.get(f"/setup?code={CODE}", headers=HOME, follow_redirects=False)
    assert answer.status_code == 302 and answer.headers["location"] == f"/encore/setup?code={CODE}"
    assert answer.headers["referrer-policy"] == "no-referrer"
    assert client.get("/setup", headers=HOME, follow_redirects=False).headers["location"] == "/encore/setup"
    weird = client.get("/setup?code=%3Cscript%3E&x=a b", headers=HOME, follow_redirects=False)
    assert weird.status_code == 302 and "<" not in weird.headers["location"] and " " not in weird.headers["location"]


def test_when_the_owner_exists_the_page_sends_the_host_to_sign_in(rig: tuple[TestClient, Maker, Settings]) -> None:
    client, _, _ = rig
    assert client.post(f"{V1}/setup/owner", json=OWNER, headers=code()).status_code == 201
    answer = client.get("/encore/setup", headers=HOME, follow_redirects=False)
    assert answer.status_code == 302 and answer.headers["location"] == "/encore/admin"
