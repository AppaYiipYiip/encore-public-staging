"""The edge of the server that faces the internet (backend review 2026-10-31, batch S1: B1, B2, B9, B11, B12, B19).

Funnel makes this server public, so what a stranger can do from the internet is tested here, and each test is the review's proof of a defect turned
round: the proof asserted the bad behaviour, these assert the fix. The address a request is counted against is set the way a proxy sets it: the
connection comes from a proxy (a private address) and `X-Forwarded-For` says who it forwarded.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server import netaddr
from encore_server.accounts import Limiter
from encore_server.api import create_app
from encore_server.config import Settings
from tests.conftest import FakeVerifier, creds
from tests.test_accounts import V1, FakeAdmin

STRANGER = "203.0.113.9"
OWNER_AWAY = "198.51.100.20"
PROXY = "10.0.0.2"


class RecordingMusicServer:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request.url.path)
        return httpx.Response(200, stream=httpx.ByteStream(b"NAVIDROME"))


class VouchingVerifier(FakeVerifier):
    """A verifier that, like the real one, remembers a yes (`known_good`)."""

    def __init__(self) -> None:
        super().__init__()
        self.vouched: set[tuple[str, str, str]] = set()

    def verify(self, user: str, token: str, salt: str) -> bool:
        ok = super().verify(user, token, salt)
        if ok:
            self.vouched.add((user, token, salt))
        return ok

    def known_good(self, user: str, token: str, salt: str) -> bool:
        return (user, token, salt) in self.vouched


class Rig:
    def __init__(self, client: TestClient, verifier: VouchingVerifier, music: RecordingMusicServer, clock: list[float]) -> None:
        self.client = client
        self.verifier = verifier
        self.music = music
        self.clock = clock

    def wrong(self, user: str, i: int, *, address: str) -> httpx.Response:
        """One wrong guess through the music server's login (what every app call carries), from [address]."""
        return self.client.get(
            f"{V1}/me", params={"u": user, "t": f"{i:032x}", "s": f"salt{i:04d}"}, headers={"X-Forwarded-For": address}
        )

    def right(self, user: str, *, address: str, via: str = "get") -> httpx.Response:
        headers = {"X-Forwarded-For": address}
        if via == "login":
            return self.client.post(f"{V1}/auth/login", json={"username": user, "password": f"pw-{user}"}, headers=headers)
        return self.client.get(f"{V1}/me", params=creds(user), headers=headers)


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[Rig]:
    verifier = VouchingVerifier()
    music = RecordingMusicServer()
    clock = [1000.0]
    config = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "m",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        away_url="https://our-music.tail1234.ts.net",
    )
    gateway_client = httpx.AsyncClient(transport=httpx.MockTransport(music.handle))
    app = create_app(config, verifier=verifier, navidrome_admin=FakeAdmin(verifier), gateway_client=gateway_client)  # type: ignore[arg-type]
    with TestClient(app, client=(PROXY, 50000)) as client:
        app.state.services.limiter = Limiter(lambda: clock[0])
        client.get(f"{V1}/me", params=creds("marwa"), headers={"X-Forwarded-For": "192.168.1.5"})  # the first person is the owner
        client.get(f"{V1}/me", params=creds("nina"), headers={"X-Forwarded-For": "192.168.1.6"})
        yield Rig(client, verifier, music, clock)


# ------------------------------------------------------------------------------------------------ B1: guessing is slowed


def test_wrong_guesses_through_the_music_server_login_are_refused_after_five_a_minute_before_the_music_server_is_asked(
    rig: Rig,
) -> None:
    before = rig.verifier.checks

    answers = [rig.wrong("marwa", i, address=STRANGER).status_code for i in range(60)]

    assert answers[:5] == [401] * 5
    assert set(answers[5:]) == {429}, "no more guesses are taken from that address"
    assert rig.verifier.checks - before == 5, "a refused guess never reaches the music server"
    refused = rig.wrong("marwa", 99, address=STRANGER)
    assert refused.json()["error"]["retryAfterMs"] > 0


def test_a_correct_login_from_another_address_is_never_held_up_by_a_strangers_guesses(rig: Rig) -> None:
    for i in range(100):
        rig.wrong("marwa", i, address=STRANGER)

    assert rig.right("marwa", address=OWNER_AWAY).status_code == 200, "the owner's phone, at its own address, answers at once"
    assert rig.right("marwa", address=OWNER_AWAY, via="login").status_code == 200
    assert rig.right("marwa", address="192.168.1.5").status_code == 200, "and so does the home network"


def test_a_login_the_music_server_already_vouched_for_is_not_refused_even_from_a_busy_address(rig: Rig) -> None:
    assert rig.right("marwa", address=STRANGER).status_code == 200  # vouched for
    for i in range(60):
        rig.wrong("mia", i, address=STRANGER)  # the address is now over its limit for another name

    assert rig.right("marwa", address=STRANGER).status_code == 200, "a correct, vouched login is not a guess"
    assert rig.right("mia", address=STRANGER).status_code == 429, "a login nobody has vouched for yet, from that address, waits"


def test_the_sign_in_page_is_slowed_the_same_way(rig: Rig) -> None:
    answers = [
        rig.client.post(
            f"{V1}/auth/login", json={"username": "marwa", "password": f"wrong-{i}"}, headers={"X-Forwarded-For": STRANGER}
        ).status_code
        for i in range(8)
    ]

    assert answers == [401] * 5 + [429] * 3
    assert rig.right("marwa", address=OWNER_AWAY, via="login").status_code == 200


def test_the_wait_ends(rig: Rig) -> None:
    for i in range(6):
        rig.wrong("marwa", i, address=STRANGER)
    assert rig.wrong("marwa", 7, address=STRANGER).status_code == 429

    rig.clock[0] += 61

    assert rig.wrong("marwa", 8, address=STRANGER).status_code == 401, "asked again, and answered as a wrong guess"


def test_one_address_trying_many_names_is_cut_off_too(rig: Rig) -> None:
    answers = [rig.wrong(f"person{i}", i, address=STRANGER).status_code for i in range(40)]

    assert answers.count(401) == 30 and answers.count(429) == 10, "thirty wrong answers an address a minute, whatever the names"


# ------------------------------------------------------------------------------------------------ B2: nobody is locked by a guess


def test_a_stranger_cannot_lock_the_only_owner_out_or_sign_out_her_phones(rig: Rig) -> None:
    token = rig.client.post(
        f"{V1}/auth/login", json={"username": "marwa", "password": "pw-marwa"}, headers={"X-Forwarded-For": OWNER_AWAY}
    ).json()["deviceToken"]
    for minute in range(10):  # an hour of patient guessing, a minute at a time
        for i in range(30):
            rig.client.post(
                f"{V1}/auth/login",
                json={"username": "marwa", "password": f"guess-{minute}-{i}"},
                headers={"X-Forwarded-For": STRANGER},
            )
        rig.clock[0] += 61

    with rig.client.app.state.services.db.read() as conn:  # type: ignore[attr-defined]
        owners = conn.execute("SELECT COUNT(*) FROM person WHERE role = 'owner' AND locked = 0").fetchone()[0]
    assert owners == 1, "the owner is still there to unlock anybody"
    assert (
        rig.client.get(f"{V1}/me", headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": OWNER_AWAY}).status_code == 200
    )
    assert rig.right("marwa", address=OWNER_AWAY, via="login").status_code == 200, "and the right password still works"


def test_a_lock_the_owner_made_is_checked_before_the_password_so_it_never_says_whether_a_guess_was_right(rig: Rig) -> None:
    nina = next(p for p in rig.client.get(f"{V1}/people", params=creds("marwa")).json()["items"] if p["username"] == "nina")["id"]
    assert rig.client.patch(f"{V1}/people/{nina}", params=creds("marwa"), json={"locked": True}).status_code == 200
    before = rig.verifier.checks

    right = rig.client.post(
        f"{V1}/auth/login", json={"username": "nina", "password": "pw-nina"}, headers={"X-Forwarded-For": OWNER_AWAY}
    )
    wrong = rig.client.post(
        f"{V1}/auth/login", json={"username": "nina", "password": "not-it"}, headers={"X-Forwarded-For": OWNER_AWAY}
    )
    through_the_music_server = rig.client.get(f"{V1}/me", params=creds("nina"), headers={"X-Forwarded-For": OWNER_AWAY})
    wrong_that_way = rig.wrong("nina", 1, address=OWNER_AWAY)

    assert right.status_code == wrong.status_code == through_the_music_server.status_code == wrong_that_way.status_code == 403
    assert right.json() == wrong.json(), "a right password and a wrong one get the same answer"
    assert rig.verifier.checks == before, "the password was not even looked at"


def test_changing_a_password_cannot_be_used_to_guess_the_current_one(rig: Rig) -> None:
    answers = [
        rig.client.post(
            f"{V1}/me/password",
            params=creds("marwa"),
            json={"oldPassword": f"guess-{i}", "newPassword": "a-new-password"},
            headers={"X-Forwarded-For": STRANGER},
        ).status_code
        for i in range(8)
    ]

    assert answers[:5] == [401] * 5 and set(answers[5:]) == {429}


# ------------------------------------------------------------------------------------------------ B11: the address is the connection's


def test_a_stranger_cannot_choose_the_address_that_is_counted_against_them() -> None:
    # A public connection: whatever it writes is ignored.
    assert netaddr.client_address("203.0.113.9", "1.2.3.4") == "203.0.113.9"
    # A proxy appends the address it saw to what the client wrote: the client's own first value is never used.
    assert netaddr.client_address("172.18.0.1", "6.6.6.6, 203.0.113.9") == "203.0.113.9"
    assert netaddr.client_address("192.168.1.77", "9.9.9.9") == "9.9.9.9", "a proxy on the home network forwarding somebody"
    # The Docker networks beyond 172.19 are ours too (a text prefix missed them: everybody behind the tunnel shared one bucket).
    assert netaddr.client_address("172.24.0.1", "203.0.113.9") == "203.0.113.9"
    assert netaddr.client_address("172.30.0.2", "203.0.113.9, 10.1.1.1") == "203.0.113.9"
    assert netaddr.client_address("100.100.1.2", "203.0.113.9") == "203.0.113.9", "a Tailscale address is a proxy"


def test_nothing_is_believed_beyond_something_that_is_not_an_address() -> None:
    assert netaddr.client_address("10.0.0.2", "1.2.3.4, unknown") == "10.0.0.2"
    assert netaddr.client_address("10.0.0.2", "") == "10.0.0.2"
    assert netaddr.client_address("10.0.0.2", None) == "10.0.0.2"
    assert netaddr.client_address("10.0.0.2", "10.9.9.9, 192.168.1.4") == "10.0.0.2", (
        "all of them ours: the connection is the answer"
    )
    assert netaddr.client_address("10.0.0.2", "[2001:db8::7]:443") == "2001:db8::7"
    assert netaddr.client_address("10.0.0.2", "203.0.113.9:5555") == "203.0.113.9"


def test_the_owner_can_name_a_proxy_of_her_own() -> None:
    extra = netaddr.networks(["198.51.100.0/24", "not a network"])

    assert netaddr.client_address("198.51.100.4", "203.0.113.9", extra) == "203.0.113.9"
    assert netaddr.client_address("198.51.100.4", "203.0.113.9") == "198.51.100.4", "not trusted unless she says so"


def test_what_counts_as_the_public_internet() -> None:
    assert netaddr.is_public("203.0.113.9") and netaddr.is_public("8.8.8.8") and netaddr.is_public("2001:db8::7")
    for ours in (
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.10",
        "172.20.0.3",
        "100.64.1.1",
        "169.254.1.1",
        "::1",
        "fd7a:115c::1",
        "testclient",
        "",
        None,
    ):
        assert not netaddr.is_public(ours), ours


def test_a_spoofed_header_from_a_public_connection_does_not_change_whose_guesses_are_counted(tmp_path: Path) -> None:
    verifier = VouchingVerifier()
    config = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(config, verifier=verifier), client=(STRANGER, 50000)) as client:
        client.get(f"{V1}/me", params=creds("marwa"))
        answers = [
            client.get(
                f"{V1}/me",
                params={"u": "marwa", "t": f"{i:032x}", "s": f"salt{i:04d}"},
                headers={"X-Forwarded-For": f"198.51.100.{i}"},
            ).status_code
            for i in range(8)
        ]

    assert answers == [401] * 5 + [429] * 3, "a new made-up address with every guess does not give a new allowance"


# ------------------------------------------------------------------------------------------------ B9: a request has a size


def test_a_huge_body_is_refused_before_it_is_read(rig: Rig) -> None:
    big = b'{"username":"x","password":"y","deviceName":"' + b"A" * (5 * 1024 * 1024) + b'"}'

    answer = rig.client.post(f"{V1}/auth/login", content=big, headers={"content-type": "application/json"})

    assert answer.status_code == 413
    assert answer.json()["error"]["code"] == "payload_too_large"


def test_a_body_that_does_not_say_how_big_it_is_is_cut_off_as_it_arrives(rig: Rig) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(8):
            yield b"A" * (1024 * 1024)

    answer = rig.client.post(f"{V1}/auth/login", content=chunks(), headers={"content-type": "application/json"})

    assert answer.status_code == 413


def test_what_is_passed_on_to_the_music_server_is_limited_too_and_never_reaches_it(rig: Rig) -> None:
    answer = rig.client.post("/rest/ping", content=b"A" * (2 * 1024 * 1024))

    assert answer.status_code == 413
    assert "/rest/ping" not in rig.music.asked


def test_ordinary_requests_are_not_in_the_way(rig: Rig) -> None:
    assert rig.right("marwa", address=OWNER_AWAY, via="login").status_code == 200
    songs = [{"title": f"Song {i}", "artists": ["Someone"], "album": "A"} for i in range(500)]
    answer = rig.client.post(f"{V1}/imports", params=creds("marwa"), json={"name": "big", "songs": songs})
    assert answer.status_code != 413, "a few hundred songs are far under the limit"
    assert rig.client.post("/rest/ping", content=b"A" * 1000).status_code == 200


# ------------------------------------------------------------------------------------------------ B19 and B12: what the internet can see


def test_the_server_does_not_publish_its_own_route_list(rig: Rig) -> None:
    app = rig.client.app
    assert app.openapi_url is None  # type: ignore[attr-defined]
    assert not any(getattr(route, "path", "") in ("/openapi.json", "/docs", "/redoc") for route in app.routes)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "path", ["/app/", "/auth/login", "/api/user", "/auth/createAdmin", "/", "/share/abc", "/ping", "/rest.view/ping"]
)
def test_the_music_servers_own_pages_and_sign_in_are_not_reachable_from_the_internet(rig: Rig, path: str) -> None:
    answer = rig.client.get(path, headers={"X-Forwarded-For": STRANGER})

    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "not_found"
    assert path not in rig.music.asked and not rig.music.asked


def test_the_subsonic_api_still_reaches_the_music_server_from_the_internet(rig: Rig) -> None:
    answer = rig.client.get("/rest/ping", params=creds("marwa"), headers={"X-Forwarded-For": STRANGER})

    assert answer.status_code == 200 and answer.text == "NAVIDROME"


def test_on_the_home_network_the_music_servers_page_is_still_there(rig: Rig) -> None:
    assert rig.client.get("/app/", headers={"X-Forwarded-For": "192.168.1.30"}).text == "NAVIDROME"
    assert rig.client.get("/auth/login").text == "NAVIDROME", "no forwarded address at all: the connection is a private one"


def test_a_request_that_arrives_by_the_away_address_is_public_whatever_it_says_about_itself(rig: Rig) -> None:
    answer = rig.client.get("/app/", headers={"Host": "our-music.tail1234.ts.net"})

    assert answer.status_code == 404 and not rig.music.asked
    assert rig.client.get("/rest/ping", headers={"Host": "our-music.tail1234.ts.net"}).status_code == 200
