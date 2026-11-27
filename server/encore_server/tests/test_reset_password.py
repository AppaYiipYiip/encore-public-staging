"""Getting back in (P3-16; docs/36 section 6): a new password made at the server's own computer, the owner's recovery key, and the audit line.

Proved here: the key (format, only a hash kept, constant-time); `reset_password` for a member, for an owner with a key (right, wrong, none), for an owner made before keys, with every
refusal in words and **nothing changed** when it fails (the music server refusing, a bad password, a wrong key); every device of the person signed out; a lock cleared; the owner's key
replaced by each reset; `recovery-key` for an owner who has none; the command door (`op reset-password`, `op recovery-key`); an audit line that never holds a secret; and the
wizard's own key (made with the owner, in the same transaction, shown once).
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server import recovery
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.errors import ApiError
from encore_server.ops import cli as ops_cli
from encore_server.ops import reset as ops_reset
from tests.conftest import FakeVerifier
from tests.test_accounts import FakeAdmin

V1 = "/encore/api/v1"
PROXY = ("10.0.0.2", 50000)
HOME = {"X-Forwarded-For": "192.168.1.20"}


# ---------------------------------------------------------------------------------------------------------------------- the key itself


def test_a_key_is_five_groups_of_four_without_lookalikes() -> None:
    for _ in range(100):
        key = recovery.new_key()
        groups = key.split("-")
        assert len(groups) == 5 and all(len(g) == 4 for g in groups) and recovery.well_formed(key)
        assert not set(key.replace("-", "")) & set("0O1IL")


def test_only_a_hash_is_kept_and_it_is_checked_in_constant_time_form() -> None:
    key = recovery.new_key()
    stored = recovery.hash_key(key)
    assert key.replace("-", "") not in stored and len(stored) == 64
    assert recovery.matches(stored, key.lower()) and recovery.matches(stored, key.replace("-", " "))
    for bad in (None, "", "ABCD", key[:-1], key + "A", 5):
        assert not recovery.matches(stored, bad), bad
    assert not recovery.matches(stored, recovery.new_key())


# ---------------------------------------------------------------------------------------------------------------------- a server with an owner (made in the browser) and people


class World:
    def __init__(
        self, client: TestClient, db: Database, admin: FakeAdmin, verifier: FakeVerifier, owner_key: str, owner_token: str
    ) -> None:
        self.client = client
        self.db = db
        self.admin = admin
        self.verifier = verifier
        self.owner_key = owner_key
        self.owner_token = owner_token

    def sign_in(self, user: str, password: str | None = None) -> str:
        answer = self.client.post(
            f"{V1}/auth/login",
            json={"username": user, "password": password or f"pw-{user}", "deviceName": f"{user}'s phone", "deviceKind": "phone"},
            headers=HOME,
        )
        assert answer.status_code == 200, answer.text
        return str(answer.json()["deviceToken"])

    def alive(self, token: str) -> bool:
        return self.client.get(f"{V1}/me", headers={"Authorization": f"Bearer {token}", **HOME}).status_code == 200

    def audit(self) -> list[dict[str, Any]]:
        with self.db.read() as conn:
            return [dict(r) for r in conn.execute("SELECT kind, subject, detail FROM audit_log ORDER BY id")]


@pytest.fixture()
def world(tmp_path: Path) -> Iterator[World]:
    verifier = FakeVerifier()
    admin = FakeAdmin(verifier)
    code = "7KQ-4MZ"
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        setup_code=code,
    )

    def make_account(_settings: Settings, owner: dict[str, Any]) -> Any:
        verifier.passwords[owner["username"]] = owner["password"]

    app = create_app(settings, verifier=verifier, navidrome_admin=admin, make_owner_account=make_account)  # type: ignore[arg-type]
    with TestClient(app, client=PROXY) as client:
        made = client.post(
            f"{V1}/setup/owner",
            json={"username": "riley", "password": "correct horse", "name": "Riley"},
            headers={**HOME, "X-Setup-Code": code},
        )
        assert made.status_code == 201, made.text
        body = made.json()
        yield World(client, client.app.state.services.db, admin, verifier, body["recoveryKey"], body["deviceToken"])  # type: ignore[attr-defined]


def test_the_wizard_makes_the_key_with_the_owner_shows_it_once_and_keeps_only_a_hash(world: World) -> None:
    assert recovery.well_formed(world.owner_key)
    with world.db.read() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM recovery_key")]
        assert len(rows) == 1 and rows[0]["key_hash"] == recovery.hash_key(world.owner_key)
        assert world.owner_key.replace("-", "") not in json.dumps(rows)
        owner = conn.execute("SELECT id FROM person WHERE role = 'owner'").fetchone()["id"]
        assert rows[0]["person"] == owner


# ---------------------------------------------------------------------------------------------------------------------- reset-password


def test_a_members_password_is_reset_every_device_is_signed_out_and_a_lock_is_cleared(world: World) -> None:
    world.verifier.passwords["nina"] = "pw-nina"
    first, second = world.sign_in("nina"), world.sign_in("nina")
    with world.db.tx() as conn:
        conn.execute("UPDATE person SET locked = 1, failed_logins = 7 WHERE navidrome_user = 'nina'")
    assert not world.alive(first), "a locked person's devices are refused"
    with world.db.tx() as conn:
        conn.execute("UPDATE person SET locked = 0 WHERE navidrome_user = 'nina'")
    assert world.alive(first) and world.alive(second)
    done = ops_reset.reset_password(world.db, world.admin, "nina", "a brand new password")  # type: ignore[arg-type]
    assert done == {"name": "nina", "role": "member", "usedKey": False, "devicesEnded": 2, "recoveryKey": None}
    assert world.admin.passwords == [("nina", "a brand new password")]
    assert not world.alive(first) and not world.alive(second), "the old sessions are refused"
    world.sign_in("nina", "a brand new password")
    with world.db.read() as conn:
        person = conn.execute("SELECT locked, failed_logins FROM person WHERE navidrome_user = 'nina'").fetchone()
    assert (person["locked"], person["failed_logins"]) == (0, 0)
    assert world.audit()[0]["kind"] == "reset_password" and world.audit()[0]["subject"] == "nina"
    assert "2 signed-in devices signed out" in world.audit()[0]["detail"]


def test_an_owner_with_a_key_resets_with_it_and_gets_a_new_one(world: World) -> None:
    done = ops_reset.reset_password(world.db, world.admin, "riley", "another long password", world.owner_key.lower())  # type: ignore[arg-type]
    assert done["usedKey"] is True and done["role"] == "owner" and recovery.well_formed(done["recoveryKey"])
    assert done["recoveryKey"] != world.owner_key, "the key that was typed on a terminal is spent"
    with world.db.read() as conn:
        owner = conn.execute("SELECT id FROM person WHERE role = 'owner'").fetchone()["id"]
        assert not recovery.verify(conn, owner, world.owner_key) and recovery.verify(conn, owner, done["recoveryKey"])
    assert not world.alive(world.owner_token), "the owner's browser session ended"
    assert "with the recovery key" in world.audit()[0]["detail"]


def test_a_wrong_key_is_refused_and_nothing_changes(world: World) -> None:
    with pytest.raises(ApiError, match="recovery key is not right"):
        ops_reset.reset_password(world.db, world.admin, "riley", "another long password", recovery.new_key())  # type: ignore[arg-type]
    assert world.admin.passwords == [] and world.alive(world.owner_token) and world.audit() == []
    with world.db.read() as conn:
        assert recovery.verify(
            conn, conn.execute("SELECT id FROM person WHERE role='owner'").fetchone()["id"], world.owner_key
        ), "the key is unchanged"


def test_root_at_the_computer_may_go_on_without_a_key_and_the_line_says_so(world: World) -> None:
    done = ops_reset.reset_password(world.db, world.admin, "riley", "another long password", "")  # type: ignore[arg-type]
    assert done["usedKey"] is False and recovery.well_formed(done["recoveryKey"])
    assert "without the recovery key" in world.audit()[0]["detail"]
    with world.db.read() as conn:
        owner = conn.execute("SELECT id FROM person WHERE role = 'owner'").fetchone()["id"]
        assert not recovery.verify(conn, owner, world.owner_key), "a reset without the key replaces it as well"


def test_an_owner_made_before_keys_existed_is_reset_and_given_a_first_key(world: World) -> None:
    with world.db.tx() as conn:
        conn.execute("DELETE FROM recovery_key")
    assert ops_reset.person_state(world.db, "riley") == "owner"
    done = ops_reset.reset_password(world.db, world.admin, "riley", "another long password")  # type: ignore[arg-type]
    assert done["usedKey"] is False and recovery.well_formed(done["recoveryKey"])
    assert "from the server computer" in world.audit()[0]["detail"]
    assert ops_reset.person_state(world.db, "riley") == "owner-with-key"


def test_a_key_given_for_somebody_who_has_none_is_refused(world: World) -> None:
    world.verifier.passwords["nina"] = "pw-nina"
    world.sign_in("nina")
    with pytest.raises(ApiError, match="no recovery key for this account"):
        ops_reset.reset_password(world.db, world.admin, "nina", "a brand new password", world.owner_key)  # type: ignore[arg-type]
    assert world.admin.passwords == []


def test_every_refusal_is_in_words_and_changes_nothing(world: World) -> None:
    world.verifier.passwords["nina"] = "pw-nina"
    token = world.sign_in("nina")
    cases: list[tuple[object, object, str]] = [
        ("nobody", "a brand new password", "nobody called"),
        ("", "a brand new password", "Say whose password"),
        (None, "a brand new password", "Say whose password"),
        ("nina", "short", "8 to 128"),
        ("nina", "nina", "8 to 128"),
        ("nina", "x" * 200, "8 to 128"),
        ("nina", None, "8 to 128"),
    ]
    for name, password, words in cases:
        with pytest.raises(ApiError, match=words):
            ops_reset.reset_password(world.db, world.admin, name, password)  # type: ignore[arg-type]
    world.verifier.passwords["nina-lopez"] = "pw-nina-lopez"
    world.sign_in("nina-lopez")
    with pytest.raises(ApiError, match="same as the name"):
        ops_reset.reset_password(world.db, world.admin, "nina-lopez", "NINA-LOPEZ")  # type: ignore[arg-type]
    assert world.admin.passwords == [] and world.alive(token) and world.audit() == []


def test_a_name_is_found_without_regard_to_case_when_only_one_matches(world: World) -> None:
    world.verifier.passwords["nina"] = "pw-nina"
    world.sign_in("nina")
    assert ops_reset.reset_password(world.db, world.admin, " NINA ", "a brand new password")["name"] == "nina"  # type: ignore[arg-type]


def test_when_the_music_server_refuses_nothing_else_is_changed(world: World) -> None:
    world.verifier.passwords["nina"] = "pw-nina"
    token = world.sign_in("nina")

    class Refusing(FakeAdmin):
        def set_password(self, username: str, password: str) -> None:
            raise ApiError("server_busy", "The music server is not answering.")

    with pytest.raises(ApiError, match="not answering"):
        ops_reset.reset_password(world.db, Refusing(world.verifier), "nina", "a brand new password")  # type: ignore[arg-type]
    assert world.alive(token) and world.audit() == [], "no session ended and no line written for something that did not happen"


def test_a_server_without_its_music_server_account_says_so(world: World) -> None:
    class Unconfigured(FakeAdmin):
        configured = False

    with pytest.raises(ApiError, match="no account for the music server"):
        ops_reset.reset_password(world.db, Unconfigured(world.verifier), "riley", "another long password", world.owner_key)  # type: ignore[arg-type]


def test_the_audit_line_never_holds_a_secret(world: World) -> None:
    world.verifier.passwords["nina"] = "pw-nina"
    world.sign_in("nina")
    done = ops_reset.reset_password(world.db, world.admin, "nina", "very secret words here")  # type: ignore[arg-type]
    owner = ops_reset.reset_password(world.db, world.admin, "riley", "another long password", world.owner_key)  # type: ignore[arg-type]
    text = json.dumps(world.audit())
    for secret in (
        "very secret words here",
        "another long password",
        world.owner_key,
        owner["recoveryKey"],
        done["name"] + "-secret",
    ):
        assert secret not in text and secret.replace("-", "") not in text


# ---------------------------------------------------------------------------------------------------------------------- recovery-key


def test_a_new_key_replaces_the_old_one_and_leaves_the_password_alone(world: World) -> None:
    made = ops_reset.new_recovery_key(world.db)
    assert made["name"] == "riley" and recovery.well_formed(made["recoveryKey"]) and made["recoveryKey"] != world.owner_key
    with world.db.read() as conn:
        owner = conn.execute("SELECT id FROM person WHERE role = 'owner'").fetchone()["id"]
        assert not recovery.verify(conn, owner, world.owner_key) and recovery.verify(conn, owner, made["recoveryKey"])
    assert world.admin.passwords == [] and world.alive(world.owner_token)
    assert world.audit()[0]["kind"] == "recovery_key" and "the old one no longer works" in world.audit()[0]["detail"]


def test_a_key_is_only_for_owners_and_the_name_is_needed_when_there_are_several(world: World) -> None:
    world.verifier.passwords["nina"] = "pw-nina"
    world.sign_in("nina")
    with pytest.raises(ApiError, match="Only an owner"):
        ops_reset.new_recovery_key(world.db, "nina")
    with world.db.tx() as conn:
        conn.execute("UPDATE person SET role = 'owner' WHERE navidrome_user = 'nina'")
    with pytest.raises(ApiError, match="more than one owner"):
        ops_reset.new_recovery_key(world.db)
    assert ops_reset.new_recovery_key(world.db, "nina")["name"] == "nina"


def test_with_no_owner_yet_there_is_nothing_to_make_a_key_for(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    db.migrate(version="test")
    with pytest.raises(ApiError, match="no owner yet"):
        ops_reset.new_recovery_key(db)


# ---------------------------------------------------------------------------------------------------------------------- the command door


def run_command(world: World, argv: list[str], stdin: str = "") -> tuple[int, str, str]:
    settings = Settings(data_dir=world.db.path.parent, music_dir=world.db.path.parent, navidrome_url="http://navidrome.invalid")
    out, err = io.StringIO(), io.StringIO()
    code = ops_cli.command(argv, settings=settings, out=out, err=err, stdin=io.StringIO(stdin), admin=world.admin)  # type: ignore[arg-type]
    return code, out.getvalue(), err.getvalue()


def test_the_command_says_what_to_ask_then_resets_and_answers_in_lines(world: World) -> None:
    world.verifier.passwords["nina"] = "pw-nina"
    token = world.sign_in("nina")
    assert run_command(world, ["reset-password", "nina", "--info"]) == (0, "member\n", "")
    assert run_command(world, ["reset-password", "riley", "--info"])[1] == "owner-with-key\n"
    code, out, err = run_command(
        world, ["reset-password", "nina"], json.dumps({"password": "a brand new password", "recoveryKey": ""})
    )
    assert code == 0 and err == "" and out == "name=nina\ndevicesEnded=1\nusedKey=false\n"
    assert not world.alive(token)
    assert "a brand new password" not in out + err
    code, out, err = run_command(
        world, ["reset-password", "riley"], json.dumps({"password": "another long password", "recoveryKey": world.owner_key})
    )
    assert code == 0 and "usedKey=true" in out and "recovery-key=" in out and world.owner_key not in out


def test_the_command_refuses_in_the_pages_own_sentences(world: World) -> None:
    code, out, err = run_command(world, ["reset-password", "nobody", "--info"])
    assert code == 1 and out == "" and "nobody called" in err
    code, out, err = run_command(
        world, ["reset-password", "riley"], json.dumps({"password": "another long password", "recoveryKey": recovery.new_key()})
    )
    assert code == 1 and "recovery key is not right" in err and world.admin.passwords == []
    assert run_command(world, ["reset-password", "riley"], "not json")[0] == 2
    assert run_command(world, ["reset-password"])[0] == 2 and run_command(world, ["whatever"])[0] == 2


def test_the_command_makes_a_key_and_says_for_whom(world: World) -> None:
    code, out, err = run_command(world, ["recovery-key"])
    assert (
        code == 0
        and err == ""
        and out.splitlines()[0] == "name=riley"
        and recovery.well_formed(out.splitlines()[1].split("=", 1)[1])
    )
    assert run_command(world, ["recovery-key", "nobody"])[0] == 1


def test_the_command_does_nothing_before_the_server_has_started(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "none", music_dir=tmp_path, navidrome_url="http://navidrome.invalid")
    err = io.StringIO()
    assert ops_cli.command(["reset-password", "x", "--info"], settings=settings, err=err) == 1
    assert "has not started yet" in err.getvalue()
