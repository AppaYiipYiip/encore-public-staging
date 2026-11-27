"""The admin pages' own JavaScript, run in a real browser against a real server (P3-06 slices 1 and 2): the sign-in, the frame, the People page.

What a Python test cannot see is what the browser does with the page: that the scripts load under the policy, that the words come out as the drawings say, that a
dialog opens with Cancel first, that the token stays in `sessionStorage` and nowhere else. This runs the pages in a headless Chromium-family browser (Chrome, Edge, Brave,
Chromium; `ENCORE_BROWSER` names one) and skips when there is none. The server is the real application on a free port, with the test verifier in place of the music
server's login.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.helper import HelperAnswer
from tests.conftest import FakeVerifier
from tests.devtools import Browser, find_browser
from tests.test_accounts import FakeAdmin

EXECUTABLE = find_browser()
pytestmark = pytest.mark.skipif(
    EXECUTABLE is None, reason="needs a Chromium-family browser (Chrome, Edge, Brave); ENCORE_BROWSER names one"
)

HOME = {"X-Forwarded-For": "192.168.1.9"}


class FakeHelper:
    """The helper as the pages meet it: what it answers is set by the test, and it remembers what it was asked."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.answers: dict[str, HelperAnswer] = {}
        self.present = True

    def available(self) -> bool:
        return self.present

    def call(self, action: str) -> HelperAnswer:
        self.calls.append(action)
        return self.answers.get(action, HelperAnswer(done="ok"))


class Server:
    def __init__(self, base: str, verifier: FakeVerifier, admin: FakeAdmin) -> None:
        self.base = base
        self.verifier = verifier
        self.admin = admin

    def api(self, method: str, path: str, body: dict[str, Any] | None = None, token: str | None = None) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base}/encore/api/v1{path}",
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {}), **HOME},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as answer:
                return dict(json.loads(answer.read() or b"{}"))
        except urllib.error.HTTPError as error:
            return {"HTTP": error.code, **json.loads(error.read() or b"{}")}

    def sign_in(self, user: str) -> str:
        return str(
            self.api(
                "POST", "/auth/login", {"username": user, "password": f"pw-{user}", "deviceName": user, "deviceKind": "phone"}
            )["deviceToken"]
        )


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Server]:
    tmp = tmp_path_factory.mktemp("admin-browser")
    verifier = FakeVerifier()
    admin = FakeAdmin(verifier)
    settings = Settings(
        data_dir=tmp / "data",
        music_dir=tmp / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        server_name="Our music",
    )
    helper = FakeHelper()
    app = create_app(settings, verifier=verifier, navidrome_admin=admin, helper=helper)  # type: ignore[arg-type]
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not running.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert running.started, "the test server did not start"
    port = running.servers[0].sockets[0].getsockname()[1]
    try:
        made = Server(f"http://127.0.0.1:{port}", verifier, admin)
        made.helper = helper  # type: ignore[attr-defined]
        yield made
    finally:
        running.should_exit = True
        running.force_exit = True
        thread.join(timeout=5)


def sign_in_page(browser: Browser, server: Server, user: str, password: str) -> None:
    browser.go(f"{server.base}/encore/admin")
    browser.wait("document.getElementById('user')")
    browser.js(
        f"document.getElementById('user').value = {json.dumps(user)}; document.getElementById('password').value = {json.dumps(password)}; document.querySelector('form').requestSubmit();"
    )


def test_the_sign_in_the_people_page_an_invitation_a_lock_and_a_removal_in_a_real_browser(server: Server) -> None:
    assert EXECUTABLE is not None
    with Browser(EXECUTABLE) as browser:
        # -- the sign-in: a sentence for a wrong password, then the frame
        browser.go(f"{server.base}/encore/admin")
        browser.wait("document.getElementById('user')")
        assert "Sign in with the account you made" in browser.text()
        browser.go(f"{server.base}/encore/admin")
        browser.wait("document.getElementById('user')")
        assert "sudo encore reset-password YOURUSERNAME" in browser.text(".login"), (
            "a person who cannot sign in is told where to go"
        )
        sign_in_page(browser, server, "marwa", "not-the-password")
        browser.wait("document.querySelector('.error') && document.querySelector('.error').innerText.length > 0")
        assert "was not accepted" in browser.text(".error")
        browser.js("document.getElementById('password').value = 'pw-marwa'; document.querySelector('form').requestSubmit();")
        browser.wait("document.querySelector('.arail')")
        assert (
            "People" in browser.text(".arail")
            and "Signed in as marwa" in browser.text(".arail")
            and "Our music" in browser.text(".arail")
        )
        # the token is in this tab's sessionStorage and nowhere else
        assert browser.js("sessionStorage.getItem('encore.admin.token') !== null") is True
        assert browser.js("localStorage.length") == 0 and browser.js("document.cookie") == ""

        # -- the owner alone: one sentence and the one button
        # -- Home is the first page: a sentence, no invented "all good" for what only the computer knows, counts and never titles
        browser.wait("document.querySelector('.hrow')")
        assert browser.text(".amain h1") == "Home" and "Everything is working." in browser.text(".ahead")
        home = browser.text(".hlist")
        assert "This computer has not told Encore yet." in home and "Counts only, never titles." in home
        assert "1 person" in home and "Not set up" in home and "GB free" in home and "Version " in home
        assert browser.js("document.querySelector('.arail [aria-current=page]').innerText") == "Home"
        # -- People: the rail switches, the address names the page
        browser.click(".arail button", "People")
        browser.wait("document.querySelector('.ptab .card')")
        assert (
            browser.js("location.hash") == "#/people"
            and browser.js("document.querySelector('.arail [aria-current=page]').innerText") == "People"
        )
        assert "Nobody else yet." in browser.text(".ptab") and "Invite someone with a link" in browser.text(".ptab")
        assert "marwa" in browser.text(".ptab") and "Owner" in browser.text(".ptab") and "You" in browser.text(".ptab")

        # -- two more people; one is locked by the owner
        server.sign_in("nina")
        server.sign_in("mia")
        owner = server.sign_in("marwa")
        mia = next(p["id"] for p in server.api("GET", "/people", token=owner)["items"] if p["username"] == "mia")
        assert server.api("PATCH", f"/people/{mia}", {"locked": True}, token=owner)["person"]["locked"] is True
        browser.go(
            f"{server.base}/encore/admin?again=1#/people"
        )  # a different address: a navigation that only adds a fragment would not reload the page
        browser.wait("document.querySelectorAll('.pt-r').length === 3")
        assert "mia's account is locked." in browser.text(".ptab") and "Unlock mia" in browser.text(".ptab")
        assert "Locked" in browser.text(".ptab") and "never what anybody plays" in browser.text(".amain")
        browser.click("button", "Unlock mia")
        browser.wait("!document.querySelector('.ptab [role=note]')")  # the banner goes
        assert not any(p["locked"] for p in server.api("GET", "/people", token=owner)["items"])

        # -- an invitation: the link is shown once, and waits in the list until it is used or cancelled
        browser.click(".ahead button", "Invite someone")
        browser.wait("document.getElementById('invite-for')")
        browser.js("document.getElementById('invite-for').value = 'Sara'")
        browser.click("dialog button", "Make the invitation")
        browser.wait("document.querySelector('dialog .linkfield')")
        dialog = browser.text("dialog")
        assert "Invitation made for Sara." in dialog and "the code is shown only once" in dialog and "Valid for 7 days" in dialog
        link = browser.js("document.querySelector('dialog .linkfield').value")
        assert link.startswith(f"{server.base}/encore/join/") and "?id=" in link, link
        browser.click("dialog button", "Done")
        browser.wait("!document.querySelector('dialog')")
        browser.wait(
            "document.querySelector('h2') && [...document.querySelectorAll('h2')].some(h => h.innerText === 'Waiting to join')"
        )
        assert "Invitation for Sara" in browser.text(".amain")
        browser.click("button", "Cancel the invitation")
        browser.wait("![...document.querySelectorAll('h2')].some(h => h.innerText === 'Waiting to join')")

        # -- a removal asks first, Cancel is first and has the focus, and only Remove removes
        browser.js("document.querySelectorAll('.pt-r')[1].querySelector('.ibtn').click()")
        browser.click(".menu button", "Remove nina")
        browser.wait("document.querySelector('dialog')")
        sheet = browser.text("dialog")
        assert "Remove nina?" in sheet and "The music files stay." in sheet and "This cannot be undone." in sheet
        assert browser.js("document.activeElement.innerText") == "Cancel"
        browser.click("dialog button", "Cancel")
        browser.wait("!document.querySelector('dialog')")
        assert "nina" in browser.text(".ptab") and server.admin.deleted == []
        browser.js("document.querySelectorAll('.pt-r')[1].querySelector('.ibtn').click()")
        browser.click(".menu button", "Remove nina")
        browser.wait("document.querySelector('dialog')")
        browser.click("dialog button", "Remove")
        browser.wait("!document.querySelector('dialog')")
        browser.wait("!document.querySelector('.ptab').innerText.includes('nina')")
        assert server.admin.deleted == ["nina"]

        # -- sign out forgets the token
        browser.click(".arail button", "Sign out")
        browser.wait("document.getElementById('user')")
        assert browser.js("sessionStorage.getItem('encore.admin.token')") is None

        # -- nothing the policy forbids happened, and nothing was thrown
        bad = [
            line
            for line in browser.logs
            if "Content Security Policy" in line
            or "Refused to" in line
            or line.startswith("[exception]")
            or "[console.error]" in line
        ]
        assert bad == [], bad
        unexpected = [line for line in browser.logs if line.startswith("[error]") and "401" not in line]
        assert unexpected == [], unexpected


# ---------------------------------------------------------------------------------------------------------------------- the first run (slice 5a)


@pytest.fixture()
def fresh_server(tmp_path: Path) -> Iterator[Server]:
    """A server that has nobody yet and a setup code, as a Host's is after the installer; the music server's account maker is the test one."""
    verifier = FakeVerifier()
    admin = FakeAdmin(verifier)
    calls: list[dict[str, Any]] = []

    def make_account(settings: Settings, owner: dict[str, Any]) -> Any:
        calls.append(owner)
        verifier.passwords[owner["username"]] = owner["password"]
        verifier.admins.add(owner["username"])

    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://navidrome.invalid",
        youtube=False,
        server_name="Our music",
        setup_code="7KQ-4MZ",
    )
    app = create_app(settings, verifier=verifier, navidrome_admin=admin, make_owner_account=make_account)  # type: ignore[arg-type]
    running = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not running.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert running.started, "the test server did not start"
    port = running.servers[0].sockets[0].getsockname()[1]
    server = Server(f"http://127.0.0.1:{port}", verifier, admin)
    server.calls = calls  # type: ignore[attr-defined]
    try:
        yield server
    finally:
        running.should_exit = True
        running.force_exit = True
        thread.join(timeout=5)


def fill(browser: Browser, **values: str) -> None:
    for element, value in values.items():
        browser.js(f"document.getElementById({json.dumps(element)}).value = {json.dumps(value)};")


def test_the_first_run_page_makes_the_owner_and_lands_signed_in(fresh_server: Server) -> None:
    server = fresh_server
    with Browser(EXECUTABLE) as browser:  # type: ignore[arg-type]
        # a link with a wrong code asks for the right one, in words, and the code is not left in the address bar
        browser.go(f"{server.base}/encore/setup?code=AAA-AAA")
        browser.wait("document.getElementById('code')")
        assert browser.js("location.search") == "" and "setup code is not right" in browser.text(".login")
        # the right one, typed the way a person types it
        fill(browser, code="7kq 4mz")
        browser.js("document.querySelector('form').requestSubmit();")
        browser.wait("document.getElementById('user')")
        assert "Welcome to Encore" in browser.text(".login") and "Our music" in browser.text(".login")
        # the two passwords differ: told so, nothing made
        fill(browser, name="Riley", user="riley", password="correct horse", again="correct horsf")
        browser.js("document.querySelector('form').requestSubmit();")
        browser.wait("document.querySelector('.error').textContent.length > 0")
        assert "not the same" in browser.text(".error") and server.calls == []  # type: ignore[attr-defined]
        # a name that is not allowed is refused by the server in words
        fill(browser, user="ri", password="correct horse", again="correct horse")
        browser.js("document.querySelector('form').requestSubmit();")
        browser.wait("document.querySelector('.error').textContent.length > 0")
        assert server.calls == []  # type: ignore[attr-defined]
        # a good one: the owner is made and the Host lands on Home, signed in
        fill(browser, user="riley")
        browser.js("document.querySelector('form').requestSubmit();")
        # the recovery key is shown once, with the way to use it; the Host cannot go on until they say they saved it
        browser.wait("document.getElementById('key')")
        shown = browser.text("#key")
        assert re.fullmatch(r"[2-9A-HJ-KM-NP-Z]{4}(-[2-9A-HJ-KM-NP-Z]{4}){4}", shown), shown
        assert "sudo encore reset-password riley" in browser.text(".login") and "Encore keeps no copy" in browser.text(".login")
        assert browser.js("document.querySelector('button.primary').disabled") is True
        browser.js("document.getElementById('saved').click();")
        assert browser.js("document.querySelector('button.primary').disabled") is False
        browser.js("document.querySelector('button.primary').click();")
        browser.wait("document.querySelector('.hrow')")
        assert browser.text(".amain h1") == "Home"
        assert "Everything is working." in browser.text(".ahead") or "need" in browser.text(".ahead")
        assert [c["username"] for c in server.calls] == ["riley"]  # type: ignore[attr-defined]
        assert browser.js("sessionStorage.getItem('encore.admin.token') !== null") is True
        assert "Riley" in browser.text(".srv"), "signed in as the name given"
        # the page is closed for ever: it sends the Host to the admin pages
        browser.go(f"{server.base}/encore/setup")
        browser.wait("document.querySelector('.amain') || document.getElementById('user')")
        assert browser.js("location.pathname") == "/encore/admin"


# ---------------------------------------------------------------------------------------------------------------------- Backups and Away from home (slice 6b)


def test_the_backups_page_lists_makes_and_never_offers_a_restore_button(server: Server) -> None:
    helper = server.helper  # type: ignore[attr-defined]
    helper.present = True
    helper.calls.clear()
    now = int(time.time())
    helper.answers["backup.list"] = HelperAnswer(
        items=[
            ["computer", "encore-backup-1.tar.gz.age", "14000000", str(now - 3600), "locked"],
            ["admin", "encore-backup-2.tar.gz.age", "15000000", str(now - 60), "locked"],
            ["computer", "encore-backup-0.tar.gz", "9000000", str(now - 90000), "plain"],
        ],
        done="ok",
    )
    helper.answers["backup.make"] = HelperAnswer(done="A backup was made.")
    with Browser(EXECUTABLE) as browser:  # type: ignore[arg-type]
        sign_in_page(browser, server, "marwa", "pw-marwa")
        browser.wait("document.querySelector('.arail')")
        browser.click(".arail button", "Backups")
        browser.wait("document.querySelectorAll('[data-backup]').length === 3")
        page = browser.text(".amain")
        assert "Backups" in page and page.count("Locked") == 2 and "Not locked" in page
        assert "made from this page" in page and "made by the computer" in page and "15 MB" in page
        assert "sudo encore restore FILE" in page and "never a button" in page, "restore is a command, in the drawn words"
        assert browser.js("[...document.querySelectorAll('button')].some((b) => /restore/i.test(b.innerText))") is False
        assert browser.js("location.hash") == "#/backups"
        browser.js("document.getElementById('make-backup').click();")
        browser.wait("document.querySelector('[role=status]').textContent === 'A backup was made.'")
        assert helper.calls.count("backup.make") == 1
        # a refusal in the helper's own words
        helper.answers["backup.make"] = HelperAnswer(
            failed="A backup was made a moment ago from the admin pages. Wait ten minutes, or make one at the computer: sudo encore backup"
        )
        browser.js("document.getElementById('make-backup').click();")
        browser.wait("document.querySelector('.error').textContent.indexOf('Wait ten minutes') >= 0")
        # without the helper: how to get it, and no button to press
        helper.present = False
        browser.click(".arail button", "Home")
        browser.wait("document.querySelector('.hrow')")
        assert "Not installed" in browser.text(".hlist") and "sudo encore helper install" in browser.text(".hlist")
        browser.click(".arail button", "Backups")
        browser.wait("document.querySelector('.card.need')")
        assert "needs a small helper" in browser.text(".amain") and "sudo encore helper install" in browser.text(".amain")
        assert browser.js("document.getElementById('make-backup').disabled") is True
    helper.present = True


def test_the_away_page_never_offers_to_set_tailscale_up_and_only_flips_a_set_up_one(server: Server) -> None:
    helper = server.helper  # type: ignore[attr-defined]
    helper.present = True
    helper.calls.clear()
    helper.answers["away.status"] = HelperAnswer(results={"tailscale": "signedout"}, done="ok")
    helper.answers["away.on"] = HelperAnswer(done="The away address is on.")
    with Browser(EXECUTABLE) as browser:  # type: ignore[arg-type]
        sign_in_page(browser, server, "marwa", "pw-marwa")
        browser.wait("document.querySelector('.arail')")
        browser.click(".arail button", "Away from home")
        browser.wait("document.querySelector('.card.need')")
        page = browser.text(".amain")
        assert (
            "Tailscale says this computer is signed out" in page
            and "sudo encore funnel on" in page
            and "never from a page" in page
        )
        assert browser.js("!!document.getElementById('away-on') || !!document.getElementById('away-off')") is False
        assert "away.on" not in helper.calls
        # a Tailscale that is set up: one button
        helper.answers["away.status"] = HelperAnswer(results={"tailscale": "ready"}, done="ok")
        browser.click(".arail button", "Home")
        browser.wait("document.querySelector('.hrow')")
        browser.click(".arail button", "Away from home")
        browser.wait("document.getElementById('away-on')")
        browser.js("document.getElementById('away-on').click();")
        browser.wait("document.querySelector('[role=status]').textContent.indexOf('The away address is on.') === 0")
        assert "The server restarts" in browser.text("[role=status]") and helper.calls.count("away.on") == 1
