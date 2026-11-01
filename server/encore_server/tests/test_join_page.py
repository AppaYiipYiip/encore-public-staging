"""The page an invitation link opens in a browser (docs/design W-05, decision D-39).

A friend taps `https://<server>/encore/join/<code>`; before this page the server answered with the music server's own page or a 404. These tests are
the promises that matter on a page that is public on the internet: it never reaches the music server, a dead code of any kind gets one identical
answer, nothing from a person or a setting is let through unescaped, and nothing can run, load or leak from it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server import join_page as page
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.ids import now_ms
from tests.conftest import FakeVerifier, creds
from tests.test_accounts import V1, FakeAdmin, Rig


class RecordingMusicServer:
    """Stands in for the music server (Navidrome) behind the gateway, and remembers what was asked of it."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request.url.path)
        return httpx.Response(200, stream=httpx.ByteStream(b"NAVIDROME"))


def make_rig(tmp_path: Path, verifier: FakeVerifier, music: RecordingMusicServer, **settings: Any) -> Iterator[Rig]:
    admin = FakeAdmin(verifier)
    config = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "m",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        **settings,
    )
    gateway_client = httpx.AsyncClient(transport=httpx.MockTransport(music.handle))
    with TestClient(
        create_app(config, verifier=verifier, navidrome_admin=admin, gateway_client=gateway_client)  # type: ignore[arg-type]
    ) as client:
        client.get(f"{V1}/me", params=creds("marwa"))
        client.get(f"{V1}/me", params=creds("nina"))
        yield Rig(client, verifier, admin)


@pytest.fixture()
def music() -> RecordingMusicServer:
    return RecordingMusicServer()


@pytest.fixture()
def rig(tmp_path: Path, verifier: FakeVerifier, music: RecordingMusicServer) -> Iterator[Rig]:
    yield from make_rig(tmp_path, verifier, music, server_name="Our music")


def join_url(code: str) -> str:
    return f"/encore/join/{code}"


# ------------------------------------------------------------------------------------------------ a live invitation


def test_a_live_invitation_says_what_it_is_who_invited_and_how_to_open_it(rig: Rig) -> None:
    code = rig.invite()["code"]

    answer = rig.client.get(join_url(code))

    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/html")
    body = answer.text
    assert "Our music" in body
    assert "Invited by marwa" in body
    assert "marwa invited you to listen on Our music. Encore is the app you listen with." in body
    assert "Open in Encore" in body
    assert f"intent://testserver{join_url(code)}#Intent;scheme=http;package=app.encore.player;end" in body
    assert f"http://testserver{join_url(code)}" in body, "the whole link, to copy and paste it in the app"
    assert "works until" in body


def test_the_server_key_in_the_link_travels_into_the_open_link_and_the_pasted_link(rig: Rig) -> None:
    code = rig.invite()["code"]

    body = rig.client.get(join_url(code), params={"id": "abcDEF123_-xyz"}).text

    assert f"{join_url(code)}?id=abcDEF123_-xyz#Intent;" in body
    assert f"http://testserver{join_url(code)}?id=abcDEF123_-xyz" in body


def test_a_server_key_that_could_carry_anything_else_is_dropped(rig: Rig) -> None:
    code = rig.invite()["code"]

    body = rig.client.get(join_url(code), params={"id": '"><script>alert(1)</script>'}).text

    assert "<script" not in body and "alert(1)" not in body
    assert "?id=" not in body


def test_behind_a_tunnel_the_link_is_written_with_the_scheme_the_visitor_used(rig: Rig) -> None:
    code = rig.invite()["code"]

    body = rig.client.get(join_url(code), headers={"Host": "our-music.tail1234.ts.net", "X-Forwarded-Proto": "https"}).text

    assert f"intent://our-music.tail1234.ts.net{join_url(code)}#Intent;scheme=https;" in body
    assert f"https://our-music.tail1234.ts.net{join_url(code)}" in body


def test_the_page_never_reaches_the_music_server(rig: Rig, music: RecordingMusicServer) -> None:
    code = rig.invite()["code"]

    rig.client.get(join_url(code))
    rig.client.get(join_url("AAAA-BBBB-CCCC"))
    rig.client.head(join_url(code))

    assert not [path for path in music.asked if path.startswith("/encore/join")], music.asked
    assert rig.client.get("/rest/ping").text == "NAVIDROME", "the stand-in is wired: only this page is kept away from it"


def test_a_name_that_is_a_person_s_choice_is_shown_escaped(rig: Rig) -> None:
    rig.client.patch(f"{V1}/me", params=creds("marwa"), json={"name": '<img src=x onerror=alert(1)> & "Marwa"'})
    code = rig.invite()["code"]

    body = rig.client.get(join_url(code)).text

    assert "<img" not in body
    assert "&lt;img src=x onerror=alert(1)&gt; &amp; &quot;Marwa&quot;" in body


# ------------------------------------------------------------------------------------------------ every dead code is one page


def test_every_kind_of_dead_code_gets_one_identical_page_with_one_status(rig: Rig) -> None:
    used = rig.invite()["code"]
    assert rig.join(used).status_code == 201
    expired = rig.invite()
    revoked = rig.invite()
    with rig.client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        conn.execute("UPDATE invite SET expires_at = ? WHERE id = ?", (now_ms() - 1, expired["id"]))
    assert rig.client.delete(f"{V1}/invites/{revoked['id']}", params=creds("marwa")).json()["revoked"] is True

    dead = [
        used,
        expired["code"],
        revoked["code"],
        "AAAA-BBBB-CCCC",  # never existed
        "x",  # not shaped like a code
        "A" * 80,  # far too long to be one
        "AB<script>CD",  # not shaped like a code, and hostile
    ]
    answers = [rig.client.get(join_url(code)) for code in dead]

    assert {a.status_code for a in answers} == {404}
    assert len({a.content for a in answers}) == 1, (
        "byte for byte the same, so it tells a stranger nothing about which kind of dead"
    )
    assert answers[0].text == page.DEAD_PAGE
    body = answers[0].text
    assert "Our music" not in body and "marwa" not in body
    for code in dead[:4]:
        assert code not in body


def test_the_dead_page_says_one_sentence_and_offers_nothing(rig: Rig) -> None:
    body = rig.client.get(join_url("AAAA-BBBB-CCCC")).text

    assert "That invitation is not valid any more. Ask for a new one." in body
    assert "<a " not in body and "intent://" not in body


# ------------------------------------------------------------------------------------------------ a page that is public


def test_the_answers_carry_the_headers_that_keep_the_code_from_leaking(rig: Rig) -> None:
    live = rig.client.get(join_url(rig.invite()["code"]))
    dead = rig.client.get(join_url("AAAA-BBBB-CCCC"))

    for answer in (live, dead):
        assert answer.headers["cache-control"] == "no-store"
        assert answer.headers["referrer-policy"] == "no-referrer"
        assert answer.headers["x-robots-tag"] == "noindex, nofollow"
        assert answer.headers["x-content-type-options"] == "nosniff"
        policy = answer.headers["content-security-policy"]
        assert "default-src 'none'" in policy
        assert "style-src 'unsafe-inline'" in policy
        assert "frame-ancestors 'none'" in policy
        assert "script-src" not in policy, "nothing may run: default-src 'none' covers scripts"


def test_the_page_has_no_script_font_image_or_other_thing_to_load(rig: Rig) -> None:
    body = rig.client.get(join_url(rig.invite()["code"])).text

    for forbidden in (
        "<script",
        "<img",
        "<link",
        "<iframe",
        "<object",
        "<embed",
        "@import",
        "url(",
        " src=",
        "onclick",
        "onerror",
    ):
        assert forbidden not in body, forbidden
    assert "fonts.googleapis" not in body
    assert not re.search(r'href="https?://', body), "no link out of the page unless the owner set one"


def test_asking_over_and_over_is_slowed_like_the_invitation_check(rig: Rig) -> None:
    code = rig.invite()["code"]

    statuses = [rig.client.get(join_url(code)).status_code for _ in range(22)]

    assert statuses[:20] == [200] * 20
    assert 429 in statuses[20:], "the same limit as /invites/check, so a code cannot be guessed at speed through this page either"


# ------------------------------------------------------------------------------------------------ getting the app


def test_without_an_app_address_the_page_says_to_ask_the_person_who_invited(rig: Rig) -> None:
    body = rig.client.get(join_url(rig.invite()["code"])).text

    assert "Ask marwa for the Encore app." in body
    assert "download the app" not in body


def test_with_an_app_address_the_page_offers_it(tmp_path: Path, verifier: FakeVerifier, music: RecordingMusicServer) -> None:
    for rig in make_rig(tmp_path, verifier, music, server_name="Our music", app_url="https://example.org/encore.apk"):
        body = rig.client.get(join_url(rig.invite()["code"])).text

        assert '<a href="https://example.org/encore.apk">download the app</a>' in body
        assert "Ask marwa" not in body


# ------------------------------------------------------------------------------------------------ the pieces


def test_an_app_address_that_could_break_out_of_the_page_is_not_used() -> None:
    for hostile in (
        "javascript:alert(1)",
        'https://x.test/"onmouseover="alert(1)',
        "https://x.test/'><script>",
        "ftp://x.test/a",
        "https://x test",
    ):
        body = page.valid_page(
            server_name="Our music",
            invited_by="marwa",
            code="ABCD-EFGH-IJKL",
            origin=("https", "a.test"),
            key=None,
            expires_at_ms=None,
            app_url=hostile,
        )
        assert "download the app" not in body, hostile
        assert "Ask marwa for the Encore app." in body


def test_hostile_values_are_escaped_wherever_they_land() -> None:
    body = page.valid_page(
        server_name='<b>"Our" music</b>',
        invited_by="<i>Marwa</i>",
        code="ABCD-EFGH-IJKL",
        origin=("https", "a.test"),
        key=None,
        expires_at_ms=None,
        app_url="",
    )

    assert "<b>" not in body and "<i>" not in body
    assert "&lt;b&gt;" in body and "&lt;i&gt;Marwa&lt;/i&gt;" in body


def test_an_invitation_with_no_inviter_still_reads_well() -> None:
    body = page.valid_page(
        server_name="Our music",
        invited_by=None,
        code="ABCD-EFGH-IJKL",
        origin=("https", "a.test"),
        key=None,
        expires_at_ms=None,
        app_url="",
    )

    assert "You are invited to listen on Our music." in body
    assert "Ask the person who invited you for the Encore app." in body
    assert "Invited by" not in body


def test_the_origin_is_only_what_a_browser_could_have_used() -> None:
    assert page.public_origin("music.example.org", None, "https") == ("https", "music.example.org")
    assert page.public_origin("192.168.1.10:4540", None, "http") == ("http", "192.168.1.10:4540")
    assert page.public_origin("[fd7a::1]:4540", "https", "http") == ("https", "[fd7a::1]:4540")
    assert page.public_origin("music.example.org", "https, http", "http") == ("https", "music.example.org")
    for bad_host in ('evil.test"><script>', "a b", "", None, "x/y", "a.test:99999999"):
        assert page.public_origin(bad_host, None, "https") is None, bad_host
    assert page.public_origin("music.example.org", "javascript", "https") is None


def test_without_a_usable_host_the_page_still_says_what_to_do_but_offers_no_link() -> None:
    body = page.valid_page(
        server_name="Our music", invited_by="marwa", code="ABCD-EFGH-IJKL", origin=None, key=None, expires_at_ms=None, app_url=""
    )

    assert "intent://" not in body and "Open in Encore</a>" not in body
    assert "Come back to this page and press Open in Encore." in body


def test_the_end_of_an_invitation_is_a_plain_date() -> None:
    assert page.expiry_text(1793750400000) == "4 November 2026"
    assert page.expiry_text(None) is None
    assert page.expiry_text(0) is None
    assert page.expiry_text(True) is None
    assert page.expiry_text(10**30) is None
