"""The admin site's skeleton (P3-06 slice 1, docs/36 section 2): what it serves and how, who may see it, and when a browser is signed out.

The rules proved here: the page and its files are served with one strict policy (no inline script or style, nothing from anywhere else, no frame, no referrer); a request
from the internet gets the very 404 an unknown route of ours gets, for the page, a file, the short address AND the admin route, with or without a token; only the owner
may use the admin route; a browser device is signed out after 12 hours unused or 7 days in all, by the sign-in check and by the live channel alike; the files that are
served are only the files of `web/`, of the types listed; and every file under `web/` is inside the package data, so the image has it.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from encore_server import web
from encore_server.api import create_app
from encore_server.auth import WEB_SESSION_IDLE_MS, WEB_SESSION_LIFETIME_MS, web_session_over
from encore_server.config import Settings
from encore_server.ids import now_ms
from tests.conftest import FakeVerifier

V1 = "/encore/api/v1"
PROXY = ("10.0.0.2", 50000)  # the connection comes from a proxy of ours, so X-Forwarded-For says who is asking
STRANGER = {"X-Forwarded-For": "203.0.113.9"}
HOME = {"X-Forwarded-For": "192.168.1.20"}


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[TestClient]:
    verifier = FakeVerifier()
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier), client=PROXY) as client:
        yield client


def sign_in(client: TestClient, user: str = "marwa", kind: str = "web", headers: dict[str, str] | None = None) -> str:
    answer = client.post(
        f"{V1}/auth/login",
        json={"username": user, "password": f"pw-{user}", "deviceName": "Browser", "deviceKind": kind},
        headers=headers or HOME,
    )
    assert answer.status_code == 200, answer.text
    return str(answer.json()["deviceToken"])


def bearer(token: str, **more: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **HOME, **more}


def age(client: TestClient, token: str, *, seen_ms_ago: int | None = None, created_ms_ago: int | None = None) -> None:
    """Makes a device older in the database, as time would."""
    from encore_server.auth import hash_token

    now = now_ms()
    with client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        if seen_ms_ago is not None:
            conn.execute("UPDATE device SET last_seen = ? WHERE token_hash = ?", (now - seen_ms_ago, hash_token(token)))
        if created_ms_ago is not None:
            conn.execute("UPDATE device SET created_at = ? WHERE token_hash = ?", (now - created_ms_ago, hash_token(token)))


# ---------------------------------------------------------------------------------------------------------------------- what is served


EXPECTED_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def test_the_page_is_served_at_home_with_the_whole_policy(rig: TestClient) -> None:
    answer = rig.get("/encore/admin", headers=HOME)
    assert answer.status_code == 200 and answer.headers["content-type"].startswith("text/html")
    assert answer.headers["content-security-policy"] == EXPECTED_CSP
    assert answer.headers["referrer-policy"] == "no-referrer"
    assert answer.headers["x-content-type-options"] == "nosniff"
    assert answer.headers["cache-control"] == "no-store"
    assert (
        answer.headers["cross-origin-opener-policy"] == "same-origin"
        and answer.headers["cross-origin-resource-policy"] == "same-origin"
    )
    assert "camera=()" in answer.headers["permissions-policy"]
    assert "/encore/web/admin.js" in answer.text and "<script>" not in answer.text
    head = rig.head("/encore/admin", headers=HOME)
    assert head.status_code == 200 and head.content == b"" and head.headers["content-security-policy"] == EXPECTED_CSP


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("admin.js", "text/javascript"),
        ("api.js", "text/javascript"),
        ("dom.js", "text/javascript"),
        ("people.js", "text/javascript"),
        ("admin.css", "text/css"),
        ("tokens.css", "text/css"),
        ("fonts/Figtree-Regular.ttf", "font/ttf"),
        ("fonts/OFL.txt", "text/plain"),
    ],
)
def test_the_files_of_the_site_are_served_with_the_same_policy(rig: TestClient, path: str, kind: str) -> None:
    answer = rig.get(f"/encore/web/{path}", headers=HOME)
    assert answer.status_code == 200 and answer.headers["content-type"].startswith(kind), answer.headers
    assert answer.headers["content-security-policy"] == EXPECTED_CSP and answer.headers["x-content-type-options"] == "nosniff"
    assert answer.headers["cache-control"] == "no-cache" and len(answer.content) > 100


@pytest.mark.parametrize(
    "path",
    [
        "admin.html",  # a page is not a file
        "../admin.js",
        "..%2fadmin.js",
        "fonts/%2e%2e/admin.js",
        "..\\admin.js",
        "fonts/Figtree-Regular.ttf/..",
        "fonts/nothing.ttf",
        "nothing.js",
        "fonts",
        "fonts/",
        "a/b/c.js",
        ".hidden.js",
        "admin.js%00.css",
        "admin.py",
        "tokens.css.map",
    ],
)
def test_a_path_that_is_not_a_listed_file_is_the_same_404_as_any_unknown_route(rig: TestClient, path: str) -> None:
    unknown = rig.get("/encore/nothing-here", headers=HOME)
    answer = rig.get(f"/encore/web/{path}", headers=HOME)
    assert answer.status_code == 404 and answer.json() == unknown.json()


@pytest.mark.parametrize(
    "path",
    [
        "../admin.js",
        "fonts/../admin.js",
        "fonts/..",
        "..",
        "/etc/passwd",
        "C:/x.js",
        "fonts\\..\\admin.js",
        "admin.js\x00.css",
        "admin.html",
        "",
    ],
)
def test_the_file_finder_itself_refuses_a_path_that_leaves_the_folder(path: str) -> None:
    """A client may tidy `fonts/../admin.js` before it sends it (the test client does), so the finder is asked directly as well."""
    assert web.asset(path) is None


def test_the_short_address_goes_to_the_page(rig: TestClient) -> None:
    answer = rig.get("/admin", headers=HOME, follow_redirects=False)
    assert answer.status_code == 302 and answer.headers["location"] == "/encore/admin"


# ---------------------------------------------------------------------------------------------------------------------- the internet sees nothing


def test_a_request_from_the_internet_gets_the_404_of_an_unknown_route_for_everything_of_the_site(rig: TestClient) -> None:
    unknown = rig.get("/encore/nothing-here", headers=STRANGER)
    assert unknown.status_code == 404
    token = sign_in(rig)
    for path in ("/encore/admin", "/encore/web/admin.js", "/encore/web/fonts/OFL.txt", "/admin", f"{V1}/admin/session"):
        for headers in (
            STRANGER,
            {**STRANGER, "Authorization": f"Bearer {token}"},
            {**STRANGER, "Authorization": "Bearer nonsense"},
        ):
            answer = rig.get(path, headers=headers, follow_redirects=False)
            assert answer.status_code == 404 and answer.json() == unknown.json(), (path, headers)
    assert rig.head("/encore/admin", headers=STRANGER).status_code == 404


def test_the_same_pages_through_the_away_address_are_refused_too(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "m",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        away_url="https://our-music.tail1234.ts.net",
    )
    with TestClient(create_app(settings, verifier=FakeVerifier()), client=PROXY) as client:
        answer = client.get("/encore/admin", headers={**HOME, "Host": "our-music.tail1234.ts.net"})
        assert answer.status_code == 404


# ---------------------------------------------------------------------------------------------------------------------- the admin route


def test_the_owner_sees_who_is_signed_in_and_when_this_browser_signs_out(rig: TestClient) -> None:
    token = sign_in(rig)
    answer = rig.get(f"{V1}/admin/session", headers=bearer(token))
    assert answer.status_code == 200
    body = answer.json()
    assert body["person"]["role"] == "owner" and body["person"]["name"]
    assert body["session"]["kind"] == "browser" and body["session"]["idleMs"] == WEB_SESSION_IDLE_MS
    assert 0 < body["session"]["expiresAt"] - now_ms() <= WEB_SESSION_IDLE_MS


def test_a_phone_signed_in_to_the_page_has_no_end(rig: TestClient) -> None:
    token = sign_in(rig, kind="phone")
    body = rig.get(f"{V1}/admin/session", headers=bearer(token)).json()
    assert body["session"] == {"kind": "device", "idleMs": None, "expiresAt": None}


def test_a_member_may_not_use_the_admin_route_and_nobody_without_a_login_may(rig: TestClient) -> None:
    sign_in(rig, "marwa")  # the first person is the owner
    nina = sign_in(rig, "nina")
    answer = rig.get(f"{V1}/admin/session", headers=bearer(nina))
    assert answer.status_code == 403
    assert rig.get(f"{V1}/admin/session", headers=HOME).status_code == 401


# ---------------------------------------------------------------------------------------------------------------------- a browser is signed out after a while


@pytest.mark.parametrize(
    ("created", "seen", "now", "over"),
    [
        (0, 0, WEB_SESSION_IDLE_MS, False),
        (0, 0, WEB_SESSION_IDLE_MS + 1, True),
        (0, None, WEB_SESSION_IDLE_MS, False),  # never seen: counted from when it was made
        (0, None, WEB_SESSION_IDLE_MS + 1, True),
        (0, WEB_SESSION_LIFETIME_MS - 1, WEB_SESSION_LIFETIME_MS, False),  # busy, and not yet seven days old
        (0, WEB_SESSION_LIFETIME_MS, WEB_SESSION_LIFETIME_MS + 1, True),  # busy, but seven days are over
    ],
)
def test_the_two_limits_of_a_browser_session(created: int, seen: int | None, now: int, over: bool) -> None:
    assert web_session_over(created, seen, now) is over


def test_a_browser_that_was_not_used_for_twelve_hours_is_signed_out_but_a_phone_is_not(rig: TestClient) -> None:
    browser = sign_in(rig, kind="web")
    phone = sign_in(rig, kind="phone")
    for token in (browser, phone):
        age(rig, token, seen_ms_ago=WEB_SESSION_IDLE_MS - 60_000)
        assert rig.get(f"{V1}/me", headers=bearer(token)).status_code == 200
    for token in (browser, phone):
        age(rig, token, seen_ms_ago=WEB_SESSION_IDLE_MS + 60_000)
    gone = rig.get(f"{V1}/me", headers=bearer(browser))
    assert gone.status_code == 401 and "signed out after a while" in gone.json()["error"]["message"]
    assert rig.get(f"{V1}/me", headers=bearer(phone)).status_code == 200


def test_a_browser_older_than_seven_days_is_signed_out_however_busy_it_was(rig: TestClient) -> None:
    browser = sign_in(rig, kind="web")
    age(rig, browser, seen_ms_ago=1_000, created_ms_ago=WEB_SESSION_LIFETIME_MS - 60_000)
    assert rig.get(f"{V1}/me", headers=bearer(browser)).status_code == 200
    age(rig, browser, seen_ms_ago=1_000, created_ms_ago=WEB_SESSION_LIFETIME_MS + 60_000)
    assert rig.get(f"{V1}/me", headers=bearer(browser)).status_code == 401


def test_the_live_channel_ends_a_browser_session_by_the_same_rule(rig: TestClient) -> None:
    browser = sign_in(rig, kind="web")
    with rig.websocket_connect("/encore/live") as socket:
        socket.send_json({"type": "auth", "token": browser})
        assert socket.receive_json()["type"] == "hello"
    age(rig, browser, seen_ms_ago=WEB_SESSION_IDLE_MS + 60_000)
    with rig.websocket_connect("/encore/live") as socket:
        socket.send_json({"type": "auth", "token": browser})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 4401


# ---------------------------------------------------------------------------------------------------------------------- what the files may contain, and that the image has them


WEB = Path(web.WEB_DIR)
TEXT_FILES = [p for p in WEB.rglob("*") if p.is_file() and p.suffix in {".html", ".js", ".css"}]


def test_there_are_files_to_check() -> None:
    assert {p.name for p in TEXT_FILES} >= {"admin.html", "admin.js", "api.js", "admin.css", "tokens.css"}


@pytest.mark.parametrize("file", TEXT_FILES, ids=lambda p: p.name)
def test_no_file_of_the_site_runs_or_styles_anything_inline_or_builds_markup_from_text(file: Path) -> None:
    text = file.read_text(encoding="utf-8")
    forbidden = {
        "an inline script": re.compile(r"<script(?![^>]*\ssrc=)[^>]*>", re.I),
        "an event attribute": re.compile(r"\son[a-z]+\s*=", re.I),
        "an inline style": re.compile(r"<style\b|\sstyle\s*=", re.I),
        "a javascript: address": re.compile(r"javascript:", re.I),
        "eval": re.compile(r"\beval\s*\(|new\s+Function\s*\(", re.I),
        "innerHTML": re.compile(r"innerHTML|outerHTML|insertAdjacentHTML", re.I),
        "document.write": re.compile(r"document\.write", re.I),
        "an address outside this server": re.compile(r"""(?:src|href|url\()\s*=?\s*["']?https?://""", re.I),
    }
    for what, pattern in forbidden.items():
        assert pattern.search(text) is None, f"{file.name} has {what}"


def test_every_file_of_the_site_is_inside_the_package_data_so_the_image_has_it() -> None:
    settings = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    globs = settings["tool"]["setuptools"]["package-data"]["encore_server"]
    package = WEB.parent
    for file in WEB.rglob("*"):
        if file.is_file():
            relative = file.relative_to(package).as_posix()
            assert any(fnmatch(relative, pattern) for pattern in globs), f"{relative} is not covered by package-data {globs}"


def test_every_listed_page_exists_and_every_served_type_has_a_real_content_type() -> None:
    for name, file in web.PAGES.items():
        assert (WEB / file).is_file(), name
    assert all("/" in kind for kind in web.ASSET_TYPES.values())
