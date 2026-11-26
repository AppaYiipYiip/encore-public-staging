"""The admin pages' own JavaScript, run in a real browser against a real server (P3-06 slices 1 and 2): the sign-in, the frame, the People page.

What a Python test cannot see is what the browser does with the page: that the scripts load under the policy, that the words come out as the drawings say, that a
dialog opens with Cancel first, that the token stays in `sessionStorage` and nowhere else. This runs the pages in a headless Chromium-family browser (Chrome, Edge, Brave,
Chromium; `ENCORE_BROWSER` names one) and skips when there is none. The server is the real application on a free port, with the test verifier in place of the music
server's login.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn

from encore_server.api import create_app
from encore_server.config import Settings
from tests.conftest import FakeVerifier
from tests.devtools import Browser, find_browser
from tests.test_accounts import FakeAdmin

EXECUTABLE = find_browser()
pytestmark = pytest.mark.skipif(
    EXECUTABLE is None, reason="needs a Chromium-family browser (Chrome, Edge, Brave); ENCORE_BROWSER names one"
)

HOME = {"X-Forwarded-For": "192.168.1.9"}


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
    app = create_app(settings, verifier=verifier, navidrome_admin=admin)  # type: ignore[arg-type]
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
        yield Server(f"http://127.0.0.1:{port}", verifier, admin)
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
        browser.wait("document.querySelector('.amain h1')")
        browser.wait("document.querySelector('.ptab .card')")
        assert "Nobody else yet." in browser.text(".ptab") and "Invite someone with a link" in browser.text(".ptab")
        assert "marwa" in browser.text(".ptab") and "Owner" in browser.text(".ptab") and "You" in browser.text(".ptab")

        # -- two more people; one is locked by the owner
        server.sign_in("nina")
        server.sign_in("mia")
        owner = server.sign_in("marwa")
        mia = next(p["id"] for p in server.api("GET", "/people", token=owner)["items"] if p["username"] == "mia")
        assert server.api("PATCH", f"/people/{mia}", {"locked": True}, token=owner)["person"]["locked"] is True
        browser.go(f"{server.base}/encore/admin")
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
