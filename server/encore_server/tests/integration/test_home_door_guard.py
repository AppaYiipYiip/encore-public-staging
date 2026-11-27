"""P3-34 slices 2b and 2c against the REAL music server: wrong logins at home on `/rest` are counted from Navidrome's own answers (audit B-56).

The unit tests (`tests/test_home_subsonic_guard.py`) use a stand-in that mimics what was measured on Navidrome 0.64.2. This is the same behaviour through the real gateway to the real music server, in
the `encore-server-navidrome` CI job: what a wrong login looks like, that it is still read when the guesser asks for gzip, that a HEAD (which has no body) is judged by a ping, and that a login the
first reader did not recognise (a name with a space, a salt of one character) is counted too. The Encore app here is reached from a made-up peer address, which counts as home.
"""

from __future__ import annotations

import secrets
from typing import Any

import pytest

from encore_server.auth import subsonic_token
from tests.integration.conftest import Rig

pytestmark = pytest.mark.integration


def wrong_token_call(rig: Rig, name: str, i: int, *, method: str = "GET", salt: str | None = None, **headers: str) -> int:
    chosen = salt if salt is not None else secrets.token_hex(6)
    params = {
        "u": name,
        "t": subsonic_token(f"not-the-password-{i}", chosen),
        "s": chosen,
        "f": "json",
        "v": "1.16.1",
        "c": "encore-test",
    }
    return int(rig.client.request(method, "/rest/ping.view", params=params, headers=headers).status_code)


def test_a_guesser_is_refused_after_five_wrong_logins_a_minute_by_the_real_music_servers_answers(rig: Rig) -> None:
    answers = [wrong_token_call(rig, rig.accounts["person"], i) for i in range(12)]

    assert answers[:5] == [200] * 5, "the music server's own answer (code 40), passed on and counted"
    assert set(answers[5:]) == {429}, "then refused before the music server is asked"


def test_the_same_when_the_guesser_asks_for_gzip(rig: Rig) -> None:
    """The real music server compresses its refusals for a client that asks: the gateway asks it for plain answers whatever the client wants, so the refusal is still readable and counted."""
    answers = [wrong_token_call(rig, rig.accounts["person"], i, **{"Accept-Encoding": "gzip"}) for i in range(12)]

    assert answers[:5] == [200] * 5 and set(answers[5:]) == {429}


def test_the_same_with_a_head_which_has_no_body(rig: Rig) -> None:
    """Measured on the real music server: a HEAD says in its headers what a GET says (194 bytes of json for a wrong login, another length for every right one), so a HEAD is judged by a ping."""
    answers = [wrong_token_call(rig, rig.accounts["person"], i, method="HEAD") for i in range(12)]

    assert answers[:5] == [200] * 5 and set(answers[5:]) == {429}


def test_the_same_with_a_name_with_a_space_and_a_salt_of_one_character(rig: Rig) -> None:
    spaced = [
        int(rig.client.get("/rest/ping.view", params={"u": "José Maria", "p": f"guess-{i}", "f": "json"}).status_code)
        for i in range(12)
    ]
    short_salt = [wrong_token_call(rig, rig.accounts["person"], i, salt="x") for i in range(12)]

    assert spaced[:5] == [200] * 5 and set(spaced[5:]) == {429}, (
        "a name this server never makes, that the music server checks like any other"
    )
    assert short_salt[:5] == [200] * 5 and set(short_salt[5:]) == {429}, "the music server takes any salt"


def test_a_name_given_twice_never_reaches_the_music_server(rig: Rig) -> None:
    """The first of a repeated name is the one the real music server checks (measured), and a decoy after it would have hidden it from a guard that read the last."""
    answers: list[Any] = []
    for i in range(30):
        got = rig.client.get(
            "/rest/ping.view", params=[("u", rig.accounts["person"]), ("p", f"guess-{i}"), ("u", f"decoy-{i}"), ("f", "json")]
        )
        answers.append((got.status_code, got.json()["subsonic-response"]["error"]["code"]))

    assert set(answers) == {(400, 10)}


def test_the_right_login_still_works_and_is_known_after_its_second_call(rig: Rig) -> None:
    for _ in range(2):
        salt = "fixedsalt1"
        got = rig.client.get(
            "/rest/ping.view",
            params={
                "u": rig.accounts["person"],
                "t": subsonic_token(rig.accounts["person_pw"], salt),
                "s": salt,
                "f": "json",
                "v": "1.16.1",
                "c": "encore-test",
            },
        )
        assert got.status_code == 200 and got.json()["subsonic-response"]["status"] == "ok"

    verifier = rig.svc.verifier
    assert verifier.vouched(rig.accounts["person"], subsonic_token(rig.accounts["person_pw"], "fixedsalt1"), "fixedsalt1")
