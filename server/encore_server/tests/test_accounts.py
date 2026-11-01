"""People (docs/21): invitations, joining, the owner's list, resets, wrong passwords."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.accounts import Accounts, Limiter, hash_code, new_code
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.errors import ApiError
from encore_server.navidrome_admin import NameTaken
from tests.conftest import FakeVerifier, creds

V1 = "/encore/api/v1"


class FakeAdmin:
    """The music server's account API: knows who exists, and gives a new account's password to the music server's login check."""

    configured = True

    def __init__(self, verifier: FakeVerifier) -> None:
        self.verifier = verifier
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.passwords: list[tuple[str, str]] = []
        self.fail_after_create: Exception | None = None

    def create_user(self, username: str, display_name: str, password: str) -> str:
        if username in self.verifier.passwords:
            raise NameTaken(username)
        self.verifier.passwords[username] = password
        self.created.append(username)
        return f"nd-{username}"

    def set_password(self, username: str, password: str) -> None:
        self.verifier.passwords[username] = password
        self.passwords.append((username, password))

    def delete_user(self, username: str) -> None:
        self.verifier.passwords.pop(username, None)
        self.deleted.append(username)


class Rig:
    def __init__(self, client: TestClient, verifier: FakeVerifier, admin: FakeAdmin) -> None:
        self.client = client
        self.verifier = verifier
        self.admin = admin

    def invite(self, user: str = "marwa", **body: Any) -> dict[str, Any]:
        response = self.client.post(f"{V1}/invites", params=creds(user), json=body)
        assert response.status_code == 201, response.text
        return response.json()["invite"]  # type: ignore[no-any-return]

    def join(self, code: str, username: str = "sara", password: str = "correct horse", **extra: Any) -> Any:
        return self.client.post(f"{V1}/auth/join", json={"code": code, "username": username, "password": password, **extra})

    def bearer(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def person_of(self, user: str) -> dict[str, Any]:
        people = self.client.get(f"{V1}/people", params=creds("marwa")).json()["items"]
        return next(p for p in people if p["username"] == user)  # type: ignore[no-any-return]


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier) -> Iterator[Rig]:
    admin = FakeAdmin(verifier)
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, navidrome_admin=admin)) as client:  # type: ignore[arg-type]
        # marwa is the first person and so the owner; nina is a member.
        client.get(f"{V1}/me", params=creds("marwa"))
        client.get(f"{V1}/me", params=creds("nina"))
        yield Rig(client, verifier, admin)


# ------------------------------------------------------------------------------------------------ invitations


def test_the_owner_makes_an_invitation_and_the_code_is_shown_once(rig: Rig) -> None:
    invite = rig.invite(note="for Sara")

    assert len(invite["code"]) == 14 and invite["code"].count("-") == 2
    listed = rig.client.get(f"{V1}/invites", params=creds("marwa")).json()["items"]
    assert [(i["note"], i["state"]) for i in listed] == [("for Sara", "open")]
    assert "code" not in listed[0], "the code is kept as a hash"
    assert invite["expiresAt"] - invite["createdAt"] == 7 * 24 * 3600 * 1000


def test_a_member_cannot_make_invitations_or_see_people(rig: Rig) -> None:
    assert rig.client.post(f"{V1}/invites", params=creds("nina"), json={}).status_code == 403
    assert rig.client.get(f"{V1}/invites", params=creds("nina")).status_code == 403
    assert rig.client.get(f"{V1}/people", params=creds("nina")).status_code == 403


def test_the_join_screen_can_say_who_invited_before_a_name_is_chosen(rig: Rig) -> None:
    code = rig.invite()["code"]

    checked = rig.client.get(f"{V1}/invites/check", params={"code": code})

    assert checked.status_code == 200 and checked.json()["invitedBy"] == "marwa"
    assert rig.client.get(f"{V1}/invites/check", params={"code": "AAAA-BBBB-CCCC"}).status_code == 404


def test_joining_makes_the_account_the_person_and_a_device_and_uses_the_invitation_up(rig: Rig) -> None:
    code = rig.invite()["code"]

    joined = rig.join(code, displayName="Sara K")

    assert joined.status_code == 201
    body = joined.json()
    assert body["person"]["name"] == "Sara K" and body["person"]["role"] == "member"
    me = rig.client.get(f"{V1}/me", headers=rig.bearer(body["deviceToken"]))
    assert me.status_code == 200 and me.json()["username"] == "sara"
    assert rig.admin.created == ["sara"]
    assert rig.person_of("sara")["invitedBy"] == "marwa"
    assert rig.client.get(f"{V1}/invites", params=creds("marwa")).json()["items"][0]["usedBy"] == "Sara K"
    assert rig.join(code, username="sara2").status_code == 404, "one person, one invitation"


def test_the_code_is_the_same_typed_in_any_case_with_or_without_dashes(rig: Rig) -> None:
    code = rig.invite()["code"]

    assert hash_code(code) == hash_code(code.lower()) == hash_code(code.replace("-", " "))
    assert rig.join(code.lower().replace("-", "")).status_code == 201


def test_an_invitation_may_make_another_owner(rig: Rig) -> None:
    code = rig.invite(role="owner")["code"]

    assert rig.join(code, username="alex").json()["person"]["role"] == "owner"


@pytest.mark.parametrize(
    ("username", "password", "status"),
    [
        ("ab", "correct horse", 400),
        ("Sara Smith", "correct horse", 400),
        ("-sara", "correct horse", 400),
        ("admin", "correct horse", 409),
        ("sara", "short", 400),
        ("sara", "sara", 400),
    ],
)
def test_a_bad_name_or_password_is_refused_before_anything_is_made(rig: Rig, username: str, password: str, status: int) -> None:
    code = rig.invite()["code"]

    assert rig.join(code, username=username, password=password).status_code == status

    assert rig.admin.created == []
    assert rig.join(code).status_code == 201, "the invitation is still good"


def test_a_name_that_is_taken_is_refused_and_the_invitation_is_not_used_up(rig: Rig) -> None:
    code = rig.invite()["code"]

    taken = rig.join(code, username="nina")

    assert taken.status_code == 409 and "already taken" in taken.json()["error"]["message"]
    assert rig.join(code, username="sara").status_code == 201


def test_an_expired_or_revoked_invitation_does_not_work(rig: Rig) -> None:
    expired = rig.invite()
    revoked = rig.invite()
    from encore_server.ids import now_ms

    with rig.client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        conn.execute("UPDATE invite SET expires_at = ? WHERE id = ?", (now_ms() - 1, expired["id"]))
    assert rig.client.delete(f"{V1}/invites/{revoked['id']}", params=creds("marwa")).json()["revoked"] is True

    assert rig.join(expired["code"]).status_code == 404
    assert rig.join(revoked["code"]).status_code == 404
    states = {i["id"]: i["state"] for i in rig.client.get(f"{V1}/invites", params=creds("marwa")).json()["items"]}
    assert states == {expired["id"]: "expired", revoked["id"]: "revoked"}


def test_a_failure_after_the_music_server_made_the_account_leaves_nobody_half_made(rig: Rig) -> None:
    code = rig.invite()["code"]
    accounts: Accounts = rig.client.app.state.services.accounts  # type: ignore[attr-defined]
    original = rig.admin.create_user

    def create_then_lose_the_invitation(username: str, display_name: str, password: str) -> str:
        made = original(username, display_name, password)
        with accounts._db.tx() as conn:
            conn.execute("UPDATE invite SET revoked_at = 1 WHERE code_hash = ?", (hash_code(code),))
        return made

    rig.admin.create_user = create_then_lose_the_invitation  # type: ignore[method-assign]

    assert rig.join(code).status_code == 404
    assert rig.admin.deleted == ["sara"] and "sara" not in rig.verifier.passwords


def test_joining_is_rate_limited_per_address(rig: Rig) -> None:
    statuses = [rig.join("AAAA-BBBB-CCCC").status_code for _ in range(12)]

    assert statuses[:10] == [404] * 10 and statuses[10] == 429
    limited = rig.join("AAAA-BBBB-CCCC").json()["error"]
    assert limited["code"] == "rate_limited" and limited["retryAfterMs"] > 0


# ------------------------------------------------------------------------------------------------ the owner's list


def test_the_owner_sees_names_roles_and_counts_and_nothing_else(rig: Rig) -> None:
    people = rig.client.get(f"{V1}/people", params=creds("marwa")).json()["items"]

    assert [(p["username"], p["role"], p["locked"]) for p in people] == [("marwa", "owner", False), ("nina", "member", False)]
    assert set(people[0]) == {
        "id",
        "username",
        "name",
        "role",
        "locked",
        "explicitOk",
        "devices",
        "lastSeen",
        "invitedBy",
        "createdAt",
    }


def test_locking_a_person_signs_their_devices_out_and_unlocking_lets_them_back(rig: Rig) -> None:
    token = rig.client.post(f"{V1}/auth/login", json={"username": "nina", "password": "pw-nina"}).json()["deviceToken"]
    nina = rig.person_of("nina")["id"]

    locked = rig.client.patch(f"{V1}/people/{nina}", params=creds("marwa"), json={"locked": True})

    assert locked.status_code == 200 and locked.json()["person"]["locked"] is True
    assert rig.client.get(f"{V1}/me", headers=rig.bearer(token)).status_code == 401
    refused = rig.client.post(f"{V1}/auth/login", json={"username": "nina", "password": "pw-nina"})
    assert refused.status_code == 403 and "locked" in refused.json()["error"]["message"]

    rig.client.patch(f"{V1}/people/{nina}", params=creds("marwa"), json={"locked": False})
    assert rig.client.post(f"{V1}/auth/login", json={"username": "nina", "password": "pw-nina"}).status_code == 200


def test_the_last_owner_cannot_be_demoted_locked_or_removed_and_nobody_locks_themselves(rig: Rig) -> None:
    marwa = rig.person_of("marwa")["id"]

    assert rig.client.patch(f"{V1}/people/{marwa}", params=creds("marwa"), json={"role": "member"}).status_code == 409
    assert rig.client.patch(f"{V1}/people/{marwa}", params=creds("marwa"), json={"locked": True}).status_code == 409
    assert rig.client.delete(f"{V1}/people/{marwa}", params=creds("marwa")).status_code == 409

    code = rig.invite(role="owner")["code"]
    alex = rig.join(code, username="alex").json()["person"]["id"]
    assert rig.client.patch(f"{V1}/people/{marwa}", params=creds("marwa"), json={"role": "member"}).status_code == 200
    assert rig.client.patch(f"{V1}/people/{alex}", params=creds("marwa"), json={"role": "member"}).status_code == 403, (
        "marwa is a member now and may not change anybody"
    )


def test_removing_a_person_removes_their_account_and_everything_they_had(rig: Rig) -> None:
    nina = rig.person_of("nina")["id"]
    rig.client.post(f"{V1}/playlists", params=creds("nina"), json={"id": "pl_" + "1" * 26, "name": "Mine"})

    removed = rig.client.delete(f"{V1}/people/{nina}", params=creds("marwa"))

    assert removed.status_code == 200 and rig.admin.deleted == ["nina"]
    assert [p["username"] for p in rig.client.get(f"{V1}/people", params=creds("marwa")).json()["items"]] == ["marwa"]
    with rig.client.app.state.services.db.read() as conn:  # type: ignore[attr-defined]
        assert conn.execute("SELECT COUNT(*) FROM playlist").fetchone()[0] == 0


# ------------------------------------------------------------------------------------------------ passwords


def test_a_forgotten_password_is_reset_with_a_link_the_owner_sends(rig: Rig) -> None:
    old_token = rig.client.post(f"{V1}/auth/login", json={"username": "nina", "password": "pw-nina"}).json()["deviceToken"]
    nina = rig.person_of("nina")["id"]
    reset = rig.client.post(f"{V1}/people/{nina}/reset", params=creds("marwa"))
    assert reset.status_code == 201
    code = reset.json()["reset"]["code"]

    done = rig.client.post(f"{V1}/auth/reset", json={"code": code, "password": "a brand new one"})

    assert done.status_code == 200
    assert rig.admin.passwords == [("nina", "a brand new one")]
    assert rig.client.get(f"{V1}/me", headers=rig.bearer(old_token)).status_code == 401, "the old devices are signed out"
    assert rig.client.get(f"{V1}/me", headers=rig.bearer(done.json()["deviceToken"])).status_code == 200
    assert rig.client.post(f"{V1}/auth/reset", json={"code": code, "password": "another one here"}).status_code == 404, "one use"


def test_a_reset_link_expires_and_a_new_one_cancels_the_old(rig: Rig) -> None:
    nina = rig.person_of("nina")["id"]
    first = rig.client.post(f"{V1}/people/{nina}/reset", params=creds("marwa")).json()["reset"]["code"]
    second = rig.client.post(f"{V1}/people/{nina}/reset", params=creds("marwa")).json()["reset"]["code"]

    assert rig.client.post(f"{V1}/auth/reset", json={"code": first, "password": "a brand new one"}).status_code == 404
    from encore_server.ids import now_ms

    with rig.client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        conn.execute("UPDATE reset_code SET expires_at = ?", (now_ms() - 1,))
    assert rig.client.post(f"{V1}/auth/reset", json={"code": second, "password": "a brand new one"}).status_code == 404


def test_changing_your_own_password_needs_the_old_one_and_signs_the_other_devices_out(rig: Rig) -> None:
    here = rig.client.post(f"{V1}/auth/login", json={"username": "nina", "password": "pw-nina"}).json()["deviceToken"]
    elsewhere = rig.client.post(f"{V1}/auth/login", json={"username": "nina", "password": "pw-nina"}).json()["deviceToken"]

    wrong = rig.client.post(
        f"{V1}/me/password", headers=rig.bearer(here), json={"oldPassword": "nope", "newPassword": "a brand new one"}
    )
    right = rig.client.post(
        f"{V1}/me/password", headers=rig.bearer(here), json={"oldPassword": "pw-nina", "newPassword": "a brand new one"}
    )

    assert wrong.status_code == 401 and right.status_code == 200
    assert rig.admin.passwords == [("nina", "a brand new one")]
    assert rig.client.get(f"{V1}/me", headers=rig.bearer(here)).status_code == 200
    assert rig.client.get(f"{V1}/me", headers=rig.bearer(elsewhere)).status_code == 401


def test_a_person_can_change_their_name_and_the_explicit_setting(rig: Rig) -> None:
    changed = rig.client.patch(f"{V1}/me", params=creds("nina"), json={"name": "  Nina   B ", "explicitOk": False})

    assert changed.status_code == 200
    assert (changed.json()["name"], changed.json()["explicitOk"]) == ("Nina B", False)
    assert rig.client.patch(f"{V1}/me", params=creds("nina"), json={"name": "  "}).status_code == 400


# ------------------------------------------------------------------------------------------------ wrong passwords


def test_five_tries_a_minute_for_one_name_and_then_a_wait_that_says_how_long(rig: Rig) -> None:
    attempts = [rig.client.post(f"{V1}/auth/login", json={"username": "nina", "password": "wrong"}) for _ in range(7)]

    assert [a.status_code for a in attempts] == [401] * 5 + [429] * 2
    assert attempts[5].json()["error"]["retryAfterMs"] > 0


def test_wrong_passwords_never_lock_an_account_or_sign_out_its_phones(rig: Rig) -> None:
    """AUDIT B2: twenty wrong guesses used to lock the account and sign out every device, which let a stranger lock the only owner out of his own
    server. Wrong passwords are slowed (see test_public_edge), never punished; a lock is only an owner's own act."""
    accounts: Accounts = rig.client.app.state.services.accounts  # type: ignore[attr-defined]
    token = rig.client.post(f"{V1}/auth/login", json={"username": "nina", "password": "pw-nina"}).json()["deviceToken"]

    for _ in range(60):
        accounts.failed_login("nina")

    assert rig.person_of("nina")["locked"] is False
    assert rig.client.get(f"{V1}/me", headers=rig.bearer(token)).status_code == 200, "her phone is still signed in"
    assert rig.client.post(f"{V1}/auth/login", json={"username": "nina", "password": "pw-nina"}).status_code == 200


def test_a_name_nobody_has_is_not_counted_or_locked(rig: Rig) -> None:
    accounts: Accounts = rig.client.app.state.services.accounts  # type: ignore[attr-defined]

    for _ in range(25):
        accounts.failed_login("nobody")

    assert [p["username"] for p in rig.client.get(f"{V1}/people", params=creds("marwa")).json()["items"]] == ["marwa", "nina"]


def test_a_server_that_cannot_make_accounts_says_so_instead_of_failing(tmp_path: Path, verifier: FakeVerifier) -> None:
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier)) as client:
        client.get(f"{V1}/me", params=creds("marwa"))
        code = client.post(f"{V1}/invites", params=creds("marwa"), json={}).json()["invite"]["code"]

        joined = client.post(f"{V1}/auth/join", json={"code": code, "username": "sara", "password": "correct horse"})

    assert joined.status_code == 503 and "not set up" in joined.json()["error"]["message"]


# ------------------------------------------------------------------------------------------------ the pieces


def test_codes_are_easy_to_read_out_and_to_type() -> None:
    codes = {new_code() for _ in range(200)}

    assert len(codes) == 200
    for code in codes:
        assert len(code) == 14 and not set(code) & set("01OIL")


def test_the_limiter_forgets_after_its_window_and_says_how_long_to_wait() -> None:
    now = [100.0]
    limiter = Limiter(lambda: now[0])

    assert [limiter.allow("k", 2, 60) for _ in range(2)] == [None, None]
    wait = limiter.allow("k", 2, 60)
    assert wait is not None and 59_000 < wait <= 60_001
    now[0] += 61
    assert limiter.allow("k", 2, 60) is None
    with pytest.raises(ApiError):
        for _ in range(3):
            limiter.refuse("other", 2, 60)


def test_the_database_has_the_new_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "e.db")
    db.migrate()
    with db.read() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"invite", "reset_code"} <= names
    assert time.time() > 0


def test_the_owner_hears_in_the_bell_that_an_invitation_was_used(rig: Rig) -> None:
    invite = rig.invite(note="for Sara")
    assert rig.join(invite["code"], username="sara", displayName="Sara").status_code == 201

    owner = rig.client.get(f"{V1}/notifications", params=creds("marwa")).json()
    assert [(i["kind"], i["title"], i["body"], i["read"]) for i in owner["items"]] == [
        ("invite_used", "Sara joined My music server", "With the invitation you made.", False)
    ]
    assert owner["unread"] == 1
    assert rig.client.get(f"{V1}/notifications", params=creds("nina")).json()["items"] == [], "only the one who made it"


def test_a_refused_join_tells_nobody(rig: Rig) -> None:
    assert rig.join("AAAA-BBBB-CCCC", username="sara").status_code in (400, 401, 404, 409, 410)

    assert rig.client.get(f"{V1}/notifications", params=creds("marwa")).json()["items"] == []


def test_a_bell_that_cannot_ring_does_not_fail_the_join(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(rig.client.app.state.services.notifications, "push", broken)  # type: ignore[attr-defined]
    invite = rig.invite()

    joined = rig.join(invite["code"], username="sara")

    assert joined.status_code == 201, "the friend is in; only the owner's news was lost"
    assert rig.person_of("sara")["username"] == "sara"
