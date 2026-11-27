"""P3-34 slice 2b (audit B-56): wrong logins at HOME on `/rest` are counted from the music server's own answer, and a guesser is refused before the call is passed on.

The audit measured sixty wrong token logins at `/rest/ping` taking 0.3 s, every one passed to the music server, none refused. At home the music server (not this one) checks a Subsonic login, and the
apps that send `p=` (a plain password) must keep working, so the gateway COUNTS wrong answers (a small, sized json or xml answer with a login-refused code, measured on Navidrome 0.64.2) against the
name, the address and the account, refuses a guesser BEFORE the call is passed on in the format the app asked for, and never refuses a device it already knows (a login the music server accepted within
the day). Everything that is not a small sized answer of that kind (a song, a picture, a large list) streams untouched.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server.accounts import Limiter, LoginGuard
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
        self.encodings: list[str] = []  # the Accept-Encoding of each call that reached it
        self.methods: list[str] = []  # the method of each call that reached it
        self.fail_get = False  # a GET is not answered (the connection fails)
        self.fail_all = False  # nothing is answered
        self.delay = 0.0  # seconds the music server takes to answer: what lets a burst overlap
        #: What a music server (a newer one, another one) might do that 0.64.2 was measured NOT to: compress an answer, send it without a length, ignore a login in a form body.
        self.compress = False  # compresses every small answer, asked or not
        self.compress_when_asked = False  # like the real one: only for a client that sends Accept-Encoding: gzip
        self.unsized = False
        self.ignores_form_bodies = False

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
        # Read the way the real music server does (measured on 0.64.2): the form body first, then the address, and of a name given more than once the FIRST wins.
        pairs: list[tuple[str, str]] = []
        if (
            request.method in ("POST", "PUT", "PATCH")
            and not self.ignores_form_bodies
            and "x-www-form-urlencoded" in request.headers.get("content-type", "")
        ):
            pairs += parse_qsl(request.content.decode(), keep_blank_values=True)
        pairs += list(request.url.params.multi_items())
        params: dict[str, str] = {}
        for name, value in pairs:
            params.setdefault(name, value)
        self.encodings.append(request.headers.get("accept-encoding", ""))
        self.methods.append(request.method)
        if self.fail_all or (self.fail_get and request.method == "GET"):
            raise httpx.ConnectError("the music server is not answering", request=request)
        answered = self.misbehave(self.answer_for(request, params))
        if request.method in ("HEAD", "OPTIONS"):
            # As measured on 0.64.2: the headers of the GET answer (its content type and its length); no body is read.
            return httpx.Response(answered.status_code, headers=dict(answered.headers), stream=httpx.ByteStream(b""))
        return answered

    def misbehave(self, response: httpx.Response) -> httpx.Response:
        """The answer as this music server sends it: as measured, or compressed, or without a length."""
        content = response.read() if not response.is_stream_consumed else b""
        if len(content) < 2048 and (self.compress or (self.compress_when_asked and "gzip" in self.encodings[-1])):
            import gzip

            packed = gzip.compress(content)
            return httpx.Response(
                200,
                headers={
                    "content-type": response.headers["content-type"],
                    "content-encoding": "gzip",
                    "content-length": str(len(packed)),
                },
                stream=httpx.ByteStream(packed),
            )
        if self.unsized and len(content) < 2048:
            return httpx.Response(
                200,
                headers={"content-type": response.headers["content-type"], "transfer-encoding": "chunked"},
                stream=httpx.ByteStream(content),
            )
        return httpx.Response(response.status_code, headers=dict(response.headers), stream=httpx.ByteStream(content))

    def answer_for(self, request: httpx.Request, params: dict[str, str]) -> httpx.Response:
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

    @property
    def in_flight(self) -> int:
        """The checks that hold a slot right now (P3-34 slice 2d): nothing, once every call has been answered."""
        return int(self.client.app.state.services.limiter.in_flight())  # type: ignore[attr-defined]

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

    def slow_sync(
        request: httpx.Request,
    ) -> httpx.Response:  # the verifier's calls run in worker threads: a sleep lets them overlap
        time.sleep(music.delay)
        return music.handle(request)

    async def slow(
        request: httpx.Request,
    ) -> httpx.Response:  # the gateway's calls share the event loop: only an await lets them overlap
        await asyncio.sleep(music.delay)
        return music.handle(request)

    verifier = NavidromeVerifier(
        "http://music.invalid", client=httpx.Client(transport=httpx.MockTransport(slow_sync)), clock=lambda: clock[0]
    )
    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path / "m", navidrome_url="http://music.invalid", youtube=False)
    gateway_client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
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
    for _ in range(2):  # accepted twice: a login is a device the server knows from its second sighting
        assert rig.token_call("marwa", "pw-marwa").json()["subsonic-response"]["status"] == "ok"
    rig.clock[0] += 700
    rig.attack_the_address()
    assert rig.token_call("nina", "pw-nina", salt="neverseen").status_code == 429, (
        "a right password nobody has seen the music server accept is held up with the guessers"
    )

    answer = rig.token_call("marwa", "pw-marwa")

    assert answer.status_code == 200 and answer.json()["subsonic-response"]["status"] == "ok"


def test_a_plain_password_app_the_music_server_accepted_is_known_too(rig: Rig) -> None:
    for _ in range(2):
        assert rig.plain_call("marwa", "pw-marwa").json()["subsonic-response"]["status"] == "ok"
    rig.attack_the_address()

    assert rig.plain_call("marwa", "pw-marwa").status_code == 200
    assert rig.plain_call("nina", "pw-nina").status_code == 429


def test_a_known_login_the_music_server_now_refuses_is_counted_and_loses_its_exemption(rig: Rig) -> None:
    """The password was changed at the music server: the old credential is a guess like any other from now on."""
    assert rig.token_call("marwa", "pw-marwa").status_code == 200
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

    assert through == ["begin", "settle", "begin", "settle"]


# ------------------------------------------------------------------------------------------------------------------------------ review of 2b (the advisor)


def accepted_twice(rig: Rig, user: str = "marwa", password: str = "pw-marwa") -> None:
    """A login is a device the server knows from its SECOND accepted sighting."""
    for _ in range(2):
        assert rig.token_call(user, password).json()["subsonic-response"]["status"] == "ok"


def vouched(rig: Rig, user: str = "marwa", password: str = "pw-marwa") -> bool:
    return rig.verifier.vouched(user, subsonic_token(password, "salt1234"), "salt1234")


def test_a_guesser_who_asks_for_gzip_is_still_counted_because_the_gateway_asks_the_music_server_for_plain_answers(
    rig: Rig,
) -> None:
    """Measured on 0.64.2: it compresses its answers for a client that asks, and a compressed refusal cannot be read. The calls whose login is counted go upstream with identity."""
    rig.music.compress_when_asked = True

    answers = [
        rig.token_call("marwa", f"guess-{i}", salt=f"salt{i:04d}", headers={"Accept-Encoding": "gzip"}).status_code
        for i in range(60)
    ]

    assert answers[:5] == [200] * 5 and set(answers[5:]) == {429}
    assert rig.reached("marwa") == 5
    assert all("gzip" not in asked for asked in rig.music.encodings), (
        "no call that carried a login was sent upstream asking for compression"
    )


@pytest.mark.parametrize("misbehaviour", ["compress", "unsized"])
def test_a_refusal_the_gateway_cannot_read_is_neither_counted_nor_taken_for_a_login_that_passed(
    rig: Rig, misbehaviour: str
) -> None:
    """A music server that compresses anyway, or sends no length: what it says about a login is unknown, and unknown is not an acceptance. The same wrong login, twice, does not become a device the
    server knows, and forty wrong guesses under the owner's name leave the owner's own entry where it was."""
    accepted_twice(rig)
    setattr(rig.music, misbehaviour, True)

    for i in range(40):
        rig.token_call("marwa", f"guess-{i % 2}", salt="samesalt", headers={"Accept-Encoding": "gzip"})

    assert not rig.verifier.vouched("marwa", subsonic_token("guess-0", "samesalt"), "samesalt"), (
        "a refusal that was not read is not an acceptance"
    )
    assert vouched(rig), "the owner's entry is still there"
    assert len(rig.verifier._vouched) == 1  # noqa: SLF001


def test_a_form_login_the_music_server_does_not_read_is_never_a_known_device(rig: Rig) -> None:
    """The music server answers code 10 ("a parameter is missing"): the login was never looked at, which is not an acceptance."""
    rig.music.ignores_form_bodies = True

    for _ in range(3):
        got = rig.client.post("/rest/ping.view", data={"u": "marwa", "p": "pw-marwa", "f": "json"})
        assert got.json()["subsonic-response"]["error"]["code"] == 10

    assert rig.verifier.vouched("marwa", "p:pw-marwa", "") is False


def test_a_decoy_name_does_not_hide_the_name_the_music_server_checks(rig: Rig) -> None:
    """Measured on 0.64.2: of a repeated name the FIRST wins. A reader that takes the last would count `decoy` while the music server checks `marwa`, and marwa's limit would never move."""
    for i in range(100):
        got = rig.client.get("/rest/ping.view", params=[("u", "marwa"), ("p", f"guess-{i}"), ("u", f"decoy{i}"), ("f", "json")])
        assert got.status_code == 400
        assert got.json()["subsonic-response"]["error"]["code"] == 10, "a Subsonic answer, in the format that was asked for"

    assert rig.reached("marwa") == 0 and rig.reached() == 0, "none of them was passed on"


@pytest.mark.parametrize(
    "case",
    [
        "p twice",
        "t twice",
        "s twice",
        "token and plain password",
        "api key and a password",
        "u in the address and in the body",
        "p in the address and in the body",
        "u twice in the body",
        "multipart",
        "put with a body twice",
    ],
)
def test_a_call_that_names_its_login_twice_or_in_two_ways_is_refused_in_the_subsonic_format(rig: Rig, case: str) -> None:
    token = subsonic_token("pw-marwa", "salt1234")
    base = [("f", "json"), ("v", "1.16.1"), ("c", "app")]
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    sent: httpx.Response
    if case == "p twice":
        sent = rig.client.get("/rest/ping.view", params=[("u", "marwa"), ("p", "a"), ("p", "b"), *base])
    elif case == "t twice":
        sent = rig.client.get("/rest/ping.view", params=[("u", "marwa"), ("t", token), ("t", token), ("s", "salt1234"), *base])
    elif case == "s twice":
        sent = rig.client.get(
            "/rest/ping.view", params=[("u", "marwa"), ("t", token), ("s", "salt1234"), ("s", "salt5678"), *base]
        )
    elif case == "token and plain password":
        sent = rig.client.get(
            "/rest/ping.view", params=[("u", "marwa"), ("t", token), ("s", "salt1234"), ("p", "pw-marwa"), *base]
        )
    elif case == "api key and a password":
        sent = rig.client.get("/rest/ping.view", params=[("u", "marwa"), ("apiKey", "k"), ("p", "pw-marwa"), *base])
    elif case == "u in the address and in the body":
        sent = rig.client.post("/rest/ping.view?u=marwa&f=json", data={"u": "nina", "p": "pw-nina"})
    elif case == "p in the address and in the body":
        sent = rig.client.post("/rest/ping.view?u=marwa&p=guess&f=json", data={"p": "pw-marwa"})
    elif case == "u twice in the body":
        sent = rig.client.post("/rest/ping.view?f=json", content="u=marwa&u=nina&p=x", headers=form)
    elif case == "multipart":
        sent = rig.client.post("/rest/ping.view?f=json", files={"u": (None, "marwa"), "p": (None, "pw-marwa")})
    else:
        sent = rig.client.put("/rest/ping.view?f=json", content="u=marwa&u=nina&p=x", headers=form)

    assert sent.status_code == 400, case
    assert sent.json()["subsonic-response"]["error"]["code"] == 10
    assert rig.reached() == 0


def test_a_name_that_is_not_part_of_the_login_may_repeat_and_one_login_may_be_split_between_the_address_and_the_body(
    rig: Rig,
) -> None:
    ok = rig.client.get("/rest/ping.view", params=[("u", "marwa"), ("p", "pw-marwa"), ("f", "json"), ("id", "1"), ("id", "2")])
    split = rig.client.post("/rest/ping.view?u=marwa&f=json", data={"p": "pw-marwa"})

    assert ok.json()["subsonic-response"]["status"] == "ok"
    assert split.json()["subsonic-response"]["status"] == "ok"


def test_a_form_login_is_counted_whichever_method_carries_it(rig: Rig) -> None:
    for method in ("POST", "PUT", "PATCH"):
        for i in range(8):
            rig.client.request(method, "/rest/ping.view", data={"u": "marwa", "p": f"{method}-guess-{i}", "f": "json"})

    assert rig.reached("marwa") <= 5, "the limit holds across the three methods"


def test_two_hundred_calls_with_a_fresh_salt_each_leave_the_owners_known_device_alone(rig: Rig) -> None:
    """An app that follows the documentation makes a new salt for every call. None of them is remembered (each is seen once); the owner's entry is not pushed out and no row is written."""
    accepted_twice(rig)

    for i in range(200):
        assert rig.token_call("marwa", "pw-marwa", salt=f"fresh{i:05d}").status_code == 200

    assert vouched(rig)
    assert len(rig.verifier._vouched) == 1  # noqa: SLF001


# ------------------------------------------------------------------------------------------------------------------------ the public door reads the same login


PUBLIC = {"X-Forwarded-For": "203.0.113.9"}


def test_from_the_internet_a_login_in_the_address_that_the_music_server_does_not_read_first_is_refused(rig: Rig) -> None:
    """One valid account is enough to get through a door that reads a different login than the music server: put your own token where the door looks and the victim's guess where the music server
    looks. Read the way the music server reads, that call names `u` twice and is refused, and the guess never reaches it."""
    mine = subsonic_token("pw-nina", "salt1234")

    got = rig.client.get(
        "/rest/ping.view",
        params=[("u", "marwa"), ("p", "guess"), ("u", "nina"), ("t", mine), ("s", "salt1234"), ("f", "json")],
        headers=PUBLIC,
    )

    assert got.status_code == 400 and got.json()["subsonic-response"]["error"]["code"] == 10
    assert rig.reached("marwa") == 0


def test_from_the_internet_a_login_in_the_body_that_the_door_does_not_read_is_refused_too(rig: Rig) -> None:
    mine = subsonic_token("pw-nina", "salt1234")

    got = rig.client.post(f"/rest/ping.view?u=nina&t={mine}&s=salt1234&f=json", data={"u": "marwa", "p": "guess"}, headers=PUBLIC)

    assert got.status_code == 400
    assert rig.reached("marwa") == 0


def test_from_the_internet_a_login_in_the_x_encore_headers_is_no_login_on_the_music_servers_api(rig: Rig) -> None:
    """The music server ignores those headers, so a door that read them was judging a login nobody would check."""
    got = rig.client.get(
        "/rest/ping.view?f=json",
        headers={
            **PUBLIC,
            "X-Encore-User": "marwa",
            "X-Encore-Token": subsonic_token("pw-marwa", "salt1234"),
            "X-Encore-Salt": "salt1234",
        },
    )

    assert got.status_code == 401
    assert rig.reached() == 0


def test_from_the_internet_a_right_token_login_in_the_address_still_works(rig: Rig) -> None:
    got = rig.token_call("marwa", "pw-marwa", headers=PUBLIC)

    assert got.status_code == 200 and got.json()["subsonic-response"]["status"] == "ok"


# ------------------------------------------------------------------------------------------------------------------------------ slice 2c: a HEAD has no body to read


def test_a_head_with_a_wrong_login_is_counted_like_a_get(rig: Rig) -> None:
    """Measured on 0.64.2: a HEAD says what a GET says in its HEADERS (a wrong login is always application/json of 194 bytes, 168 with gzip; every right answer differs), so a guesser who only
    sends HEADs could tell a right password from a wrong one without ever being counted. A HEAD that carries a login is judged by a GET ping of the same login first."""
    answers = [
        rig.client.head(
            "/rest/ping.view",
            params=[("u", "marwa"), ("t", subsonic_token(f"guess-{i}", f"salt{i:04d}")), ("s", f"salt{i:04d}"), ("f", "json")],
        ).status_code
        for i in range(60)
    ]

    assert answers[:5] == [200] * 5, "the music server's own answer for the first five"
    assert set(answers[5:]) == {429}
    assert rig.reached("marwa") <= 10, "at most five pings and five HEADs reached the music server"


def test_the_same_with_a_plain_password_and_with_gzip_asked_for(rig: Rig) -> None:
    for i in range(60):
        rig.client.head("/rest/ping.view", params=[("u", "marwa"), ("p", f"guess-{i}")], headers={"Accept-Encoding": "gzip"})

    assert rig.reached("marwa") <= 10
    assert all("gzip" not in asked for asked in rig.music.encodings)


def test_a_head_that_the_music_server_accepts_still_gets_the_music_servers_headers_and_the_login_becomes_known(rig: Rig) -> None:
    got = rig.client.head(
        "/rest/ping.view",
        params=[("u", "marwa"), ("t", subsonic_token("pw-marwa", "salt1234")), ("s", "salt1234"), ("f", "json")],
    )
    again = rig.client.head(
        "/rest/ping.view",
        params=[("u", "marwa"), ("t", subsonic_token("pw-marwa", "salt1234")), ("s", "salt1234"), ("f", "json")],
    )

    assert got.status_code == 200 and again.status_code == 200
    assert got.headers["content-type"] == "application/json" and got.content == b""
    assert vouched(rig), "seen twice, accepted both times"
    assert rig.music.methods.count("HEAD") == 2 and rig.music.methods.count("GET") == 2, (
        "one ping each, then the HEAD itself, passed on"
    )


def test_a_head_with_no_login_is_passed_on_alone(rig: Rig) -> None:
    rig.client.head("/rest/ping.view", params={"f": "json"})

    assert rig.music.methods == ["HEAD"]


def test_a_music_server_that_does_not_answer_the_ping_does_not_stop_the_head_from_being_passed_on(rig: Rig) -> None:
    rig.music.fail_get = True

    got = rig.client.head("/rest/ping.view", params=[("u", "marwa"), ("p", "pw-marwa"), ("f", "json")])

    assert got.status_code == 200
    assert "HEAD" in rig.music.methods


# ------------------------------------------------------------------------------------------------------------------------------ a login is what the music server reads


def test_a_wrong_login_for_a_name_with_a_space_or_a_letter_with_an_accent_is_counted_too(rig: Rig) -> None:
    """The first reader only knew names of letters, digits and . _ @ -: the music server takes any (an attached one may have `José Maria`), so those were free guesses."""
    answers = [
        rig.client.get("/rest/ping.view", params=[("u", "José Maria"), ("p", f"guess-{i}"), ("f", "json")]).status_code
        for i in range(60)
    ]

    assert answers[:5] == [200] * 5 and set(answers[5:]) == {429}


@pytest.mark.parametrize("salt", ["x", "ab", "a-b_c!", "s" * 100])
def test_a_wrong_token_login_with_a_salt_the_old_reader_did_not_know_is_counted_too(rig: Rig, salt: str) -> None:
    """The first reader asked for a salt of 4 to 64 letters and digits; the music server takes any salt, and a guesser who picked a one-character salt was never counted."""
    answers = [
        rig.client.get(
            "/rest/ping.view", params=[("u", "marwa"), ("t", subsonic_token(f"guess-{i}", salt)), ("s", salt), ("f", "json")]
        ).status_code
        for i in range(60)
    ]

    assert answers[:5] == [200] * 5 and set(answers[5:]) == {429}


def test_a_very_long_wrong_password_is_counted_too(rig: Rig) -> None:
    answers = [
        rig.client.get("/rest/ping.view", params=[("u", "marwa"), ("p", "x" * 3000 + str(i)), ("f", "json")]).status_code
        for i in range(30)
    ]

    assert answers[:5] == [200] * 5 and set(answers[5:]) == {429}


def test_from_the_internet_a_salt_or_a_token_of_a_shape_this_server_does_not_make_is_still_refused(rig: Rig) -> None:
    """The internet door stays as strict as it was: only a token login of the shape the apps make."""
    for params in (
        [("u", "marwa"), ("t", subsonic_token("pw-marwa", "x")), ("s", "x"), ("f", "json")],
        [("u", "marwa"), ("t", "short"), ("s", "salt1234"), ("f", "json")],
        [("u", "mar wa"), ("t", subsonic_token("pw", "salt1234")), ("s", "salt1234"), ("f", "json")],
    ):
        got = rig.client.get("/rest/ping.view", params=params, headers=PUBLIC)
        assert got.status_code == 401, params

    assert rig.reached() == 0


def test_an_options_call_with_a_login_is_judged_by_a_ping_like_a_head(rig: Rig) -> None:
    """Measured on 0.64.2 (the log of PR 188): an OPTIONS answers with the GET's headers too (131 bytes for a right login, 194 for a wrong one), the same oracle as a HEAD."""
    answers = [
        rig.client.request("OPTIONS", "/rest/ping.view", params=[("u", "marwa"), ("p", f"guess-{i}"), ("f", "json")]).status_code
        for i in range(60)
    ]

    assert answers[:5] == [200] * 5 and set(answers[5:]) == {429}
    assert rig.reached("marwa") <= 10


# ------------------------------------------------------------------------------------------------------------------------------ slice 2d: a burst of concurrent wrong logins


BURST = 60


def burst(calls: list[Callable[[], httpx.Response]]) -> list[int]:
    """All of them at the same time: a thread each, every one waiting for the music server for a fifth of a second."""
    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(lambda call: int(call().status_code), calls))


def test_sixty_concurrent_wrong_logins_at_home_are_held_to_the_ceiling_not_to_their_own_size(rig: Rig) -> None:
    """A wrong answer is counted when the music server has given it, so sixty sent together all met a count of zero and all reached it (the advisor's burst). Now the checks under way are limited
    too: only a few more than the ceiling reach the music server, and the rest are refused."""
    rig.music.delay = 0.3

    answers = burst([lambda i=i: rig.token_call("marwa", f"guess-{i}", salt=f"salt{i:04d}") for i in range(BURST)])

    assert rig.reached("marwa") <= LoginGuard.IN_FLIGHT_PAIR + LoginGuard.PAIR[0], (
        "held to the ceiling (plus the few counted while they ran)"
    )
    assert answers.count(429) >= BURST - LoginGuard.IN_FLIGHT_PAIR - LoginGuard.PAIR[0]
    assert rig.in_flight == 0, "every slot was given back"


def test_the_same_burst_from_the_internet_is_held_too(rig: Rig) -> None:
    """The internet door checks the login itself (`check_music_login`, in a worker thread): the same slots."""
    rig.music.delay = 0.3

    burst([lambda i=i: rig.token_call("marwa", f"guess-{i}", salt=f"salt{i:04d}", headers=PUBLIC) for i in range(BURST)])

    assert rig.reached("marwa") <= LoginGuard.IN_FLIGHT_PAIR + LoginGuard.PAIR[0]
    assert rig.in_flight == 0


def test_the_same_burst_of_sign_ins_is_held_too(rig: Rig) -> None:
    rig.music.delay = 0.3

    burst(
        [
            lambda i=i: rig.client.post(
                "/encore/api/v1/auth/login", json={"username": "marwa", "password": f"guess-{i}", "deviceName": "x"}
            )
            for i in range(BURST)
        ]
    )

    assert rig.reached("marwa") <= LoginGuard.IN_FLIGHT_PAIR + LoginGuard.PAIR[0]
    assert rig.in_flight == 0


def test_an_app_that_loads_a_screen_of_covers_with_a_fresh_salt_each_is_not_held_up(rig: Rig) -> None:
    """Twelve at once, every one a login nobody has seen before (a fresh salt each, as the Subsonic documentation says): all answered."""
    rig.music.delay = 0.3

    answers = burst(
        [
            lambda i=i: rig.token_call("marwa", "pw-marwa", salt=f"cover{i:04d}", endpoint="getCoverArt.view", id=f"al{i}")
            for i in range(12)
        ]
    )

    assert set(answers) == {200}
    assert rig.in_flight == 0


def test_a_known_device_is_never_held_by_a_burst_around_it(rig: Rig) -> None:
    accepted_twice(rig)
    rig.music.delay = 0.3

    burst([lambda i=i: rig.token_call("marwa", f"guess-{i}", salt=f"salt{i:04d}") for i in range(BURST)])
    rig.music.delay = 0.0

    assert rig.token_call("marwa", "pw-marwa").status_code == 200, "the owner's app still gets through"


def test_the_slot_is_given_back_when_the_music_server_does_not_answer(rig: Rig) -> None:
    rig.music.fail_all = True

    got = rig.token_call("marwa", "pw-marwa")
    head = rig.client.head("/rest/ping.view", params=[("u", "marwa"), ("p", "x"), ("f", "json")])

    assert got.status_code == 503 and head.status_code == 503
    assert rig.in_flight == 0
