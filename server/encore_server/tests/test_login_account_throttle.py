"""P3-34 slice 2a (audit B-56): wrong logins are slowed per ACCOUNT as well as per address, and a device the server already knows is never held up.

Where Docker hides the visitor's address, everybody, the Host's family included, arrives as the network's own gateway and shares ONE address: B-56 measured thirty wrong tries from it
refusing the right password for everyone behind it. Today only the ten-minute memory of a yes (`known_good`) keeps the owner's app answering through that. So:

* the guard counts a wrong answer against the account too (`LoginGuard.ACCOUNT`), whatever the address, so a guesser spread over many addresses is slowed;
* a login the music server ACCEPTED within the last day (`vouched`: remembered under an HMAC with a per-process key) skips all three refusals, never the music server's own check;
* an Encore device token never goes through the guard.
The rule and its costs (a NEW sign-in is slowed while its account is under attack; an app that changes its salt on every call is never known; a restart forgets) are in docs/21.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server.accounts import Limiter
from encore_server.api import create_app
from encore_server.config import Settings
from tests.conftest import FakeVerifier, creds
from tests.test_accounts import V1, FakeAdmin

GATEWAY = "172.19.0.1"  # where Docker hides every visitor: the network's own gateway


class TimedVerifier(FakeVerifier):
    """The music server's side as the real verifier behaves: a yes is remembered ten minutes (`known_good`) and, apart, for a day (`vouched`), on a clock the test moves."""

    def __init__(self, clock: list[float]) -> None:
        super().__init__()
        self.clock = clock
        self.seen: dict[tuple[str, str, str], float] = {}

    def verify(self, user: str, token: str, salt: str) -> bool:
        ok = super().verify(user, token, salt)
        if ok:
            self.seen[(user, token, salt)] = self.clock[0]
        else:
            self.seen.pop((user, token, salt), None)
        return ok

    def known_good(self, user: str, token: str, salt: str) -> bool:
        at = self.seen.get((user, token, salt))
        return at is not None and self.clock[0] - at < 600

    def vouched(self, user: str, token: str, salt: str) -> bool:
        at = self.seen.get((user, token, salt))
        return at is not None and self.clock[0] - at < 86400

    def forget(self, user: str) -> None:
        for key in [k for k in self.seen if k[0] == user]:
            del self.seen[key]


class Rig:
    def __init__(self, client: TestClient, verifier: TimedVerifier, clock: list[float]) -> None:
        self.client, self.verifier, self.clock = client, verifier, clock

    def wrong(self, user: str, i: int, *, address: str | None = None) -> httpx.Response:
        """One wrong guess at the music server's login (what every app call carries). No address: it is the gateway's, the one everybody shares."""
        headers = {"X-Forwarded-For": address} if address else {}
        return self.client.get(f"{V1}/me", params={"u": user, "t": f"{i:032x}", "s": f"salt{i:04d}"}, headers=headers)

    def owner(self, *, address: str | None = None) -> httpx.Response:
        """The owner's app: the same credential every time (one salt per install)."""
        headers = {"X-Forwarded-For": address} if address else {}
        return self.client.get(f"{V1}/me", params=creds("marwa"), headers=headers)

    def sign_in(self, user: str, password: str, *, address: str | None = None) -> httpx.Response:
        headers = {"X-Forwarded-For": address} if address else {}
        return self.client.post(f"{V1}/auth/login", json={"username": user, "password": password}, headers=headers)

    def attack_the_address(self) -> None:
        """Forty wrong tries at seven made-up names from the gateway address: the address limit (thirty) is reached, as B-56 measured."""
        for name in ("a", "b", "c", "d", "e", "f", "g"):
            for i in range(5):
                self.wrong(name, i)

    def attack_the_account(self, user: str = "marwa") -> None:
        """Twenty-five wrong tries at ONE account from five different addresses (five a minute each is the most any one address is allowed)."""
        for n in range(5):
            for i in range(5):
                self.wrong(user, n * 10 + i, address=f"203.0.113.{10 + n}")


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[Rig]:
    clock = [1000.0]
    verifier = TimedVerifier(clock)
    config = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    gateway_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"NAVIDROME")))
    app = create_app(config, verifier=verifier, navidrome_admin=FakeAdmin(verifier), gateway_client=gateway_client)  # type: ignore[arg-type]
    with TestClient(app, client=(GATEWAY, 50000)) as client:
        app.state.services.limiter = Limiter(lambda: clock[0])
        yield Rig(client, verifier, clock)


def test_the_owner_whose_login_the_music_server_accepted_keeps_answering_through_an_attack_from_the_shared_gateway_address(
    rig: Rig,
) -> None:
    """B-56: thirty wrong tries from the one address everybody shares refused the right password too. The ten-minute memory of a yes carried the owner's app only for ten minutes."""
    assert rig.owner().status_code == 200  # accepted by the music server
    rig.clock[0] += 700  # the ten-minute memory has run out; the day's has not
    rig.attack_the_address()
    assert rig.wrong("zed", 1).status_code == 429, "the address is limited: a stranger's next guess is refused"

    answer = rig.owner()

    assert answer.status_code == 200, (
        "the credential the music server accepted this morning is not held up by a stranger's guesses"
    )


def test_a_guesser_spread_over_many_addresses_is_slowed_for_the_account(rig: Rig) -> None:
    rig.attack_the_account()
    asked = rig.verifier.checks

    fresh_wrong = rig.wrong("marwa", 777, address="198.51.100.9")

    assert fresh_wrong.status_code == 429, "a sixth address is refused for this account although it never guessed before"
    assert rig.verifier.checks == asked, "refused before the music server is asked"
    assert fresh_wrong.json()["error"]["retryAfterMs"] > 0


def test_a_new_sign_in_is_slowed_while_its_account_is_under_attack_and_works_when_the_minute_is_over(rig: Rig) -> None:
    """The stated cost: a NEW phone has no remembered yes. It waits for the minute; it is never locked out and nobody is signed out."""
    rig.attack_the_account()
    asked = rig.verifier.checks

    slowed = rig.sign_in("marwa", "pw-marwa", address="198.51.100.9")

    assert slowed.status_code == 429 and slowed.json()["error"]["retryAfterMs"] > 0
    assert rig.verifier.checks == asked
    rig.clock[0] += 61
    assert rig.sign_in("marwa", "pw-marwa", address="198.51.100.9").status_code == 200, (
        "the minute is over: the right password signs in"
    )


def test_a_known_device_is_not_held_up_by_an_attack_on_its_account(rig: Rig) -> None:
    assert rig.owner(address="192.168.1.5").status_code == 200
    rig.clock[0] += 700
    rig.attack_the_account()

    assert rig.owner(address="198.51.100.77").status_code == 200, (
        "the credential the music server accepted is exempt from the account limit too"
    )


def test_the_exemption_never_skips_the_music_servers_own_check(rig: Rig) -> None:
    """A vouched credential is still asked of the music server (the ten-minute memory has run out): if the password changed, it is wrong and counted."""
    assert rig.owner().status_code == 200
    rig.clock[0] += 700
    rig.verifier.passwords["marwa"] = "a new password"  # changed at the music server without Encore hearing of it
    before = rig.verifier.checks

    answer = rig.owner()

    assert answer.status_code == 401 and rig.verifier.checks == before + 1, "asked, and refused"
    assert ("marwa", creds("marwa")["t"], "salt1234") not in rig.verifier.seen, (
        "and the old credential is no longer vouched: it is a guess like any other"
    )
    assert rig.verifier.vouched("marwa", creds("marwa")["t"], "salt1234") is False


def test_after_a_password_change_the_old_credential_is_not_exempt(rig: Rig) -> None:
    assert rig.owner().status_code == 200
    rig.clock[0] += 700
    rig.verifier.forget("marwa")  # what `forget_credentials` does when a password is changed, a person removed or locked
    rig.attack_the_account()

    assert rig.owner(address="198.51.100.77").status_code == 429, (
        "a forgotten credential has no exemption: it is slowed like a guess"
    )


def test_a_credential_that_was_never_accepted_gets_nothing_from_the_exemption(rig: Rig) -> None:
    rig.attack_the_address()

    assert rig.wrong("marwa", 4242).status_code == 429
    assert rig.wrong("nina", 4242).status_code == 429


def test_an_encore_device_token_never_goes_through_the_guard(rig: Rig) -> None:
    signed_in = rig.sign_in("marwa", "pw-marwa", address="192.168.1.5")
    token = signed_in.json()["deviceToken"]
    rig.clock[0] += 3600
    rig.attack_the_address()
    rig.attack_the_account()

    answer = rig.client.get(f"{V1}/me", headers={"Authorization": f"Bearer {token}"})

    assert answer.status_code == 200


def test_one_stranger_cannot_use_the_account_limit_alone_to_slow_everybody(rig: Rig) -> None:
    """A single address is stopped at five wrong tries a minute for one name, so it can never reach the account's twenty by itself."""
    for i in range(60):
        rig.wrong("marwa", i, address="203.0.113.9")

    assert rig.sign_in("marwa", "pw-marwa", address="198.51.100.9").status_code == 200


# ---------------------------------------------------------------------------------------------------------------------------------- a restart (review of 2a)

PERSIST = True  # the real verifier is given the database's store; False is how it was before the review (and how the lockout below is shown)


def restartable_app(tmp_path: Path, music, clock: list[float], *, persist: bool = PERSIST):  # type: ignore[no-untyped-def]
    """A server process: the real verifier (its own memory, not a fake's) over a fake music server, and a fresh in-memory limiter. Calling it again on the same folder is a restart."""
    from encore_server.auth import NavidromeVerifier
    from encore_server.db import Database
    from tests.test_revocation import MusicServer  # noqa: F401 - the music server's fake lives there

    extra = {}
    if persist:
        from encore_server.login_vouch import SqliteVouchStore

        extra["store"] = SqliteVouchStore(Database(tmp_path / "data" / "encore.db"))
    verifier = NavidromeVerifier(
        "http://music.invalid", client=httpx.Client(transport=httpx.MockTransport(music.handle)), clock=lambda: clock[0], **extra
    )
    config = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.invalid", youtube=False)
    app = create_app(config, verifier=verifier, navidrome_admin=FakeAdmin(music))  # type: ignore[arg-type]
    return app, verifier


def test_the_owners_app_keeps_answering_after_a_restart_while_a_stranger_is_still_guessing(tmp_path: Path) -> None:
    """A restart happens on every update and every crash and clears the in-memory memories. A scripted guesser refills the account's twenty within seconds of the server coming back: the
    owner's app, which this server had seen the music server accept that morning, must not be the one that waits. On main it never did (a stranger's guesses counted against the stranger)."""
    from tests.test_revocation import MusicServer

    clock = [1000.0]
    music = MusicServer()
    app, _ = restartable_app(tmp_path, music, clock)
    with TestClient(app, client=(GATEWAY, 50000)) as client:
        for _ in range(2):  # a login is remembered from its second accepted sighting
            assert client.get(f"{V1}/me", params=creds("marwa")).status_code == 200  # accepted by the music server, remembered
    clock[0] += 3600  # an hour: an update, a crash, a night

    app2, _ = restartable_app(tmp_path, music, clock)  # the restart: a new verifier, a new limiter, the same folder
    with TestClient(app2, client=(GATEWAY, 50000)) as client:
        for n in range(5):
            for i in range(5):
                client.get(
                    f"{V1}/me",
                    params={"u": "marwa", "t": f"{n * 10 + i:032x}", "s": f"salt{i:04d}"},
                    headers={"X-Forwarded-For": f"203.0.113.{10 + n}"},
                )
        assert (
            client.get(
                f"{V1}/me", params={"u": "marwa", "t": "f" * 32, "s": "saltffff"}, headers={"X-Forwarded-For": "198.51.100.9"}
            ).status_code
            == 429
        ), "the account is under attack"

        answer = client.get(f"{V1}/me", params=creds("marwa"), headers={"X-Forwarded-For": "192.168.1.5"})

        assert answer.status_code == 200, "the owner's app is a device the server already knew, restart or not"


def test_a_guesser_who_writes_a_new_forwarded_address_on_every_request_is_still_held_to_the_accounts_twenty_a_minute(
    rig: Rig,
) -> None:
    """Where Docker hides the visitor, `client_address` believes `X-Forwarded-For` from the private gateway, so a stranger can write a new made-up address on every request and get five
    tries per name per fake address: unlimited on main. The account limit does not depend on any address: at most twenty of a hundred reach the music server in a minute."""
    asked = rig.verifier.checks

    for i in range(100):
        rig.wrong("marwa", i, address=f"203.0.{i // 250}.{i % 250 + 1}")

    assert rig.verifier.checks - asked <= 20, "the music server is asked about at most twenty of the hundred"
