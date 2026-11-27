"""P3-34 slice 2b (audit B-56): wrong logins at HOME on `/rest` are counted from the music server's own answer, and a guesser is refused before the call is passed on.

The audit measured sixty wrong token logins at `/rest/ping` taking 0.3 s, every one passed to the music server, none refused. At home the music server (not this one) checks a Subsonic login, and the
apps that send `p=` (a plain password) must keep working, so the gateway COUNTS wrong answers (a small, sized json or xml answer with a login-refused code, measured on Navidrome 0.64.2) against the
name, the address and the account, refuses a guesser BEFORE the call is passed on in the format the app asked for, and never refuses a device it already knows (a login the music server accepted within
the day). Everything that is not a small sized answer of that kind (a song, a picture, a large list) streams untouched.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server.accounts import Limiter
from encore_server.api import create_app
from encore_server.auth import NavidromeVerifier, subsonic_token
from encore_server.config import Settings
from tests.test_accounts import FakeAdmin

GATEWAY = "172.19.0.1"  # where Docker hides every visitor: the network's own gateway
AUDIO = bytes(range(256)) * 1200  # 300 KB of "a song"
BIG_LIST = (
    '{"subsonic-response":{"status":"ok","version":"1.16.1","albumList2":{"album":['
    + ",".join(f'{{"id":"al{i}","name":"Album number {i}"}}' for i in range(900))
    + "]}}}"
).encode()


def answer(content: bytes, content_type: str) -> httpx.Response:
    """A 200 with a Content-Length, as a Go server sends a small answer: built as a stream, which is how the gateway reads an upstream answer (`content=` would raise StreamConsumed)."""
    return httpx.Response(
        200, headers={"content-type": content_type, "content-length": str(len(content))}, stream=httpx.ByteStream(content)
    )


def refused_answer(fmt: str, callback: str) -> httpx.Response:
    """The music server's wrong-login answer, byte for byte the shapes measured on 0.64.2 (the sizes differ by a few bytes)."""
    if fmt == "json":
        return answer(
            b'{"subsonic-response":{"status":"failed","version":"1.16.1","type":"navidrome","serverVersion":"0.64.2","openSubsonic":true,"error":{"code":40,"message":"Wrong username or password"}}}',
            "application/json",
        )
    if fmt == "jsonp":
        return answer(
            callback.encode()
            + b'({"subsonic-response":{"status":"failed","version":"1.16.1","error":{"code":40,"message":"Wrong username or password"}}})',
            "application/javascript",
        )
    return answer(
        b'<subsonic-response xmlns="http://subsonic.org/restapi" status="failed" version="1.16.1"><error code="40" message="Wrong username or password"></error></subsonic-response>',
        "application/xml",
    )


class Music:
    """The music server as the home door meets it: it checks the login itself (token, `p=` plain, `p=enc:`), answers like the measured one, and writes down every call it was asked."""

    def __init__(self) -> None:
        self.passwords = {"marwa": "pw-marwa", "nina": "pw-nina", "mia": "pw-mia"}
        self.asked: list[tuple[str, str]] = []

    def good(self, params: dict[str, str]) -> bool:
        password = self.passwords.get(params.get("u", ""))
        if password is None:
            return False
        if "t" in params:
            return hashlib.md5((password + params.get("s", "")).encode()).hexdigest() == params["t"]  # noqa: S324 - the Subsonic protocol's own token
        given = params.get("p", "")
        if given.startswith("enc:"):
            given = bytes.fromhex(given[4:]).decode()
        return given == password

    def handle(self, request: httpx.Request) -> httpx.Response:
        params = (
            {**dict(parse_qsl(request.content.decode())), **dict(request.url.params)}
            if request.method == "POST"
            else dict(request.url.params)
        )
        endpoint = request.url.path.rsplit("/", 1)[-1]
        self.asked.append((endpoint, params.get("u", "")))
        if "u" not in params:
            return answer(
                b'{"subsonic-response":{"status":"failed","error":{"code":10,"message":"required parameter is missing"}}}',
                "application/json",
            )
        if not self.good(params):
            return refused_answer(params.get("f", "xml"), params.get("callback", "callback"))
        if endpoint == "stream.view":
            return answer(AUDIO, "audio/ogg")
        if endpoint == "getAlbumList2.view":
            return answer(BIG_LIST, "application/json")
        if endpoint == "getCoverArt.view":
            return answer(
                b'{"subsonic-response":{"status":"failed","error":{"code":70,"message":"not found"}}}', "application/json"
            )
        return answer(b'{"subsonic-response":{"status":"ok","version":"1.16.1"}}', "application/json")


class Rig:
    def __init__(self, client: TestClient, music: Music, clock: list[float], verifier: NavidromeVerifier) -> None:
        self.client, self.music, self.clock, self.verifier = client, music, clock, verifier

    def token_call(
        self,
        user: str,
        password: str,
        *,
        salt: str = "salt1234",
        endpoint: str = "ping.view",
        fmt: str = "json",
        headers: dict[str, str] | None = None,
        **more: str,
    ) -> httpx.Response:
        params = {"u": user, "t": subsonic_token(password, salt), "s": salt, "v": "1.16.1", "c": "app", "f": fmt, **more}
        return self.client.get(f"/rest/{endpoint}", params=params, headers=headers or {})

    def plain_call(
        self, user: str, password: str, *, endpoint: str = "ping.view", fmt: str = "json", encoded: bool = False, **more: str
    ) -> httpx.Response:
        secret = "enc:" + password.encode().hex() if encoded else password
        return self.client.get(f"/rest/{endpoint}", params={"u": user, "p": secret, "v": "1.16.1", "c": "app", "f": fmt, **more})

    def reached(self, user: str | None = None) -> int:
        return sum(1 for _, who in self.music.asked if user is None or who == user)

    def attack_the_address(self) -> None:
        """Thirty-five wrong tries at seven made-up names from the shared address: the address limit (thirty) is reached, as B-56 measured, and a right password from it is refused too unless it is known."""
        for name in ("a", "b", "c", "d", "e", "f", "g"):
            for i in range(5):
                self.token_call(name, "x", salt=f"salt{i:04d}")
        assert self.token_call("h", "x", salt="saltzzzz").status_code == 429, "the address is limited"

    def attack(self, count: int = 60, *, user: str = "marwa") -> list[int]:
        return [self.token_call(user, f"guess-{i}", salt=f"salt{i:04d}").status_code for i in range(count)]


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[Rig]:
    music = Music()
    clock = [1000.0]
    verifier = NavidromeVerifier(
        "http://music.invalid", client=httpx.Client(transport=httpx.MockTransport(music.handle)), clock=lambda: clock[0]
    )
    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.invalid", youtube=False)
    gateway_client = httpx.AsyncClient(transport=httpx.MockTransport(music.handle))
    app = create_app(settings, verifier=verifier, navidrome_admin=FakeAdmin(music), gateway_client=gateway_client)  # type: ignore[arg-type]
    with TestClient(app, client=(GATEWAY, 50000)) as client:  # every visitor arrives as the gateway: the address is hidden
        app.state.services.limiter = Limiter(lambda: clock[0])
        yield Rig(client, music, clock, verifier)


# ------------------------------------------------------------------------------------------------------------------------------------ the audit's attack


def test_sixty_wrong_token_logins_at_ping_from_one_address_are_no_longer_all_passed_to_the_music_server(rig: Rig) -> None:
    """The audit measured sixty in 0.3 s, none refused. Five a minute for one name from one address get through (and are counted); the rest are refused before the music server is asked."""
    answers = rig.attack(60)

    assert answers[:5] == [200] * 5, "the music server's own answer, passed on, for the first five"
    assert set(answers[5:]) == {429}
    assert rig.reached("marwa") == 5, "no more than the limit reached the music server"


def test_the_same_with_the_plain_password_form_that_third_party_apps_send(rig: Rig) -> None:
    answers = [rig.plain_call("marwa", f"guess-{i}").status_code for i in range(60)]

    assert answers[:5] == [200] * 5 and set(answers[5:]) == {429}
    assert rig.reached("marwa") == 5


def test_the_same_with_the_hex_spelling_of_the_plain_password(rig: Rig) -> None:
    answers = [rig.plain_call("marwa", f"guess-{i}", encoded=True).status_code for i in range(60)]

    assert answers[:5] == [200] * 5 and set(answers[5:]) == {429}


def test_a_guesser_who_writes_a_new_forwarded_address_on_every_call_is_held_to_the_accounts_twenty_a_minute(rig: Rig) -> None:
    for i in range(100):
        rig.token_call("marwa", f"guess-{i}", salt=f"salt{i:04d}", headers={"X-Forwarded-For": f"203.0.{i // 250}.{i % 250 + 1}"})

    assert rig.reached("marwa") <= 20


def test_a_guesser_trying_many_names_from_one_address_is_held_to_thirty_a_minute(rig: Rig) -> None:
    for n in range(12):
        for i in range(5):
            rig.token_call(f"name{n}", "x", salt=f"salt{i:04d}")

    assert len(rig.music.asked) <= 30


def test_the_wait_ends_and_the_wrong_count_starts_again(rig: Rig) -> None:
    rig.attack(10)
    assert rig.token_call("marwa", "pw-marwa", salt="newsalt1").status_code == 429, (
        "even a right password waits while the address is being limited: it is not known yet"
    )

    rig.clock[0] += 61

    assert rig.token_call("marwa", "pw-marwa", salt="newsalt2").json()["subsonic-response"]["status"] == "ok"


# ------------------------------------------------------------------------------------------------------------------------------------ the owner and the apps


def test_a_correct_plain_password_login_at_home_works_when_nobody_is_guessing_and_is_passed_on_as_it_came(rig: Rig) -> None:
    answer = rig.plain_call("marwa", "pw-marwa")

    assert answer.status_code == 200
    assert answer.json() == {"subsonic-response": {"status": "ok", "version": "1.16.1"}}, (
        "the music server's own answer, untouched"
    )
    assert rig.plain_call("marwa", "pw-marwa", encoded=True).status_code == 200


def test_the_owners_accepted_login_keeps_getting_answers_through_an_attack_from_the_shared_address(rig: Rig) -> None:
    assert (
        rig.token_call("marwa", "pw-marwa").json()["subsonic-response"]["status"] == "ok"
    )  # accepted: now a device the server knows
    rig.clock[0] += 700
    rig.attack_the_address()
    assert rig.token_call("nina", "pw-nina", salt="neverseen").status_code == 429, (
        "a right password nobody has seen the music server accept is held up with the guessers"
    )

    answer = rig.token_call("marwa", "pw-marwa")

    assert answer.status_code == 200 and answer.json()["subsonic-response"]["status"] == "ok"


def test_a_plain_password_app_the_music_server_accepted_is_known_too(rig: Rig) -> None:
    assert rig.plain_call("marwa", "pw-marwa").json()["subsonic-response"]["status"] == "ok"
    rig.attack_the_address()

    assert rig.plain_call("marwa", "pw-marwa").status_code == 200
    assert rig.plain_call("nina", "pw-nina").status_code == 429


def test_a_known_login_the_music_server_now_refuses_is_counted_and_loses_its_exemption(rig: Rig) -> None:
    """The password was changed at the music server: the old credential is a guess like any other from now on."""
    assert rig.token_call("marwa", "pw-marwa").status_code == 200
    rig.music.passwords["marwa"] = "changed"

    first = rig.token_call("marwa", "pw-marwa")  # still exempt from the refusal; the answer tells it is wrong
    assert first.json()["subsonic-response"]["status"] == "failed"
    assert rig.verifier.vouched("marwa", subsonic_token("pw-marwa", "salt1234"), "salt1234") is False


def test_a_song_a_picture_and_a_large_list_are_passed_on_untouched_and_never_read(rig: Rig) -> None:
    song = rig.token_call("marwa", "pw-marwa", endpoint="stream.view", fmt="xml", id="s1")
    albums = rig.token_call("marwa", "pw-marwa", endpoint="getAlbumList2.view", type="newest")

    assert song.status_code == 200 and song.content == AUDIO and song.headers["content-type"] == "audio/ogg"
    assert albums.status_code == 200 and albums.content == BIG_LIST


def test_a_right_login_that_asks_for_something_that_is_not_there_is_not_a_wrong_guess(rig: Rig) -> None:
    """Code 70, not found, with the right password: forty of them make no guesser."""
    for i in range(40):
        assert rig.token_call("marwa", "pw-marwa", endpoint="getCoverArt.view", id=f"nope{i}").status_code == 200
    assert rig.token_call("marwa", "pw-marwa").status_code == 200


def test_a_call_that_carries_no_login_is_left_alone(rig: Rig) -> None:
    for _ in range(40):
        assert rig.client.get("/rest/ping.view", params={"f": "json"}).status_code == 200
    assert rig.reached() == 40


def test_an_api_key_is_left_alone_this_music_server_takes_none(rig: Rig) -> None:
    for _ in range(40):
        assert rig.client.get("/rest/ping.view", params={"u": "marwa", "apiKey": "ndk-abc", "f": "json"}).status_code == 200


def test_a_form_post_with_the_credential_in_the_body_is_counted_too(rig: Rig) -> None:
    answers = [
        rig.client.post(
            "/rest/ping.view", data={"u": "marwa", "p": f"guess-{i}", "f": "json", "v": "1.16.1", "c": "app"}
        ).status_code
        for i in range(30)
    ]

    assert answers[:5] == [200] * 5 and set(answers[5:]) == {429}
    assert rig.reached("marwa") == 5


# ------------------------------------------------------------------------------------------------------------------------------------ the refusal itself


def test_the_refusal_is_in_the_format_the_app_asked_for_and_says_how_long_to_wait(rig: Rig) -> None:
    rig.attack(10)

    xml = rig.token_call("marwa", "guess", salt="aaaa0001", fmt="xml")
    json_ = rig.token_call("marwa", "guess", salt="aaaa0002", fmt="json")
    jsonp = rig.token_call("marwa", "guess", salt="aaaa0003", fmt="jsonp", callback="myCallback")

    for answer in (xml, json_, jsonp):
        assert answer.status_code == 429 and int(answer.headers["retry-after"]) >= 1
        assert len(answer.content) < 1024
    assert (
        xml.headers["content-type"].startswith("application/xml")
        and xml.content.startswith(b"<subsonic-response")
        and b'code="0"' in xml.content
    )
    assert (
        json_.headers["content-type"].startswith("application/json") and json_.json()["subsonic-response"]["error"]["code"] == 0
    )
    assert jsonp.headers["content-type"].startswith("application/javascript") and jsonp.content.startswith(b"myCallback({")
    assert rig.reached("marwa") == 5, "and none of those reached the music server"


def test_a_callback_that_could_carry_a_script_is_not_echoed(rig: Rig) -> None:
    rig.attack(10)

    answer = rig.token_call("marwa", "guess", salt="aaaa0004", fmt="jsonp", callback="a b<script>alert(1)</script>")

    assert b"<script>" not in answer.content and answer.content.startswith(b"callback(")


# ------------------------------------------------------------------------------------------------------------------------------------ nothing else changes


def test_the_public_door_is_exactly_as_before(rig: Rig) -> None:
    """A request from the internet (a public address behind the shared gateway) is checked at the door as before: a token login is needed and a plain password is refused."""
    plain = rig.client.get(
        "/rest/ping.view", params={"u": "marwa", "p": "pw-marwa", "f": "json"}, headers={"X-Forwarded-For": "203.0.113.9"}
    )
    token = rig.client.get(
        "/rest/ping.view",
        params={"u": "marwa", "t": subsonic_token("pw-marwa", "salt1234"), "s": "salt1234", "f": "json"},
        headers={"X-Forwarded-For": "203.0.113.9"},
    )

    assert plain.status_code == 401, "a plain password is not accepted from the internet"
    assert token.status_code == 200


def test_the_music_servers_shut_doors_are_still_shut(rig: Rig) -> None:
    assert rig.client.get("/app/").status_code == 404
    assert re.search(rb"not_found", rig.client.get("/auth/login").content)


def test_the_guard_runs_in_a_worker_thread_never_on_the_event_loop(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """It may write to the database (the first accepted login, an hourly renewal, the one-time load): a busy database must not stall every other call on the loop, so both of its calls go through
    the thread pool."""
    from encore_server import gateway

    through: list[str] = []
    original = gateway.run_in_threadpool

    async def spy(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        through.append(getattr(func, "__name__", ""))
        return await original(func, *args, **kwargs)

    monkeypatch.setattr(gateway, "run_in_threadpool", spy)

    assert rig.token_call("marwa", "pw-marwa").status_code == 200  # a right login: refuse, then settle
    assert rig.token_call("marwa", "wrong", salt="aaaa0001").status_code == 200  # a wrong one: refuse, then settle (counted)

    assert through == ["refuse", "settle", "refuse", "settle"]
