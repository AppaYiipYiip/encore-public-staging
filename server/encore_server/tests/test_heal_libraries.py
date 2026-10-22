"""A person whose music-server account has no library sees no songs and cannot stream: the server gives it the library."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from encore_server.accounts import Accounts
from encore_server.db import Database
from encore_server.navidrome_admin import NavidromeAdmin
from encore_server.scanner import LibraryLinker, LinkReport


class MusicServer:
    """Just enough of the music server's account API: users, libraries, and the call that sets a user's libraries."""

    def __init__(self, users: list[dict[str, Any]], libraries: list[int]) -> None:
        self.users = users
        self.libraries = libraries
        self.sets: list[tuple[str, list[int]]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/auth/login":
            return httpx.Response(200, json={"token": "t"})
        if path == "/api/user":
            return httpx.Response(200, json=self.users)
        if path == "/api/library":
            return httpx.Response(200, json=[{"id": i} for i in self.libraries])
        if path.startswith("/api/user/") and path.endswith("/library"):
            user_id = path.split("/")[3]
            self.sets.append((user_id, json.loads(request.content)["libraryIds"]))
            return httpx.Response(200, json={})
        return httpx.Response(404)


def admin_for(server: MusicServer) -> NavidromeAdmin:
    client = httpx.Client(transport=httpx.MockTransport(server.handle))
    return NavidromeAdmin("http://music.invalid", "root", "x", client=client)


def user(user_id: str, name: str, *, libraries: list[int], admin: bool = False) -> dict[str, Any]:
    return {"id": user_id, "userName": name, "isAdmin": admin, "libraries": [{"id": i} for i in libraries]}


def test_an_account_without_a_library_is_given_every_library_and_others_are_left_alone() -> None:
    server = MusicServer(
        [
            user("u1", "newtester", libraries=[]),
            user("u2", "sam", libraries=[1]),
            user("u3", "root", libraries=[], admin=True),
            user("u4", "stranger", libraries=[]),
        ],
        libraries=[1, 2],
    )

    fixed = admin_for(server).give_libraries(["newtester", "sam", "root"])

    assert fixed == 1
    assert server.sets == [("u1", [1, 2])], (
        "only the person without a library; not an administrator, not somebody Encore does not know"
    )


def test_nothing_is_done_while_the_music_server_has_no_library_yet() -> None:
    server = MusicServer([user("u1", "newtester", libraries=[])], libraries=[])

    assert admin_for(server).give_libraries(["newtester"]) == 0
    assert server.sets == []


def test_accounts_heal_the_people_it_knows(tmp_path: Path) -> None:
    db = Database(tmp_path / "e.db")
    db.migrate(version="test")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO person (id, navidrome_user, display_name, role, created_at) VALUES ('pn_1','newtester','newtester','member',0)"
        )
    server = MusicServer([user("u1", "newtester", libraries=[]), user("u4", "stranger", libraries=[])], libraries=[1])

    assert Accounts(db, admin_for(server)).heal_libraries() == 1
    assert server.sets == [("u1", [1])]


def test_the_library_link_runs_its_errand_first_and_survives_a_failing_one(tmp_path: Path) -> None:
    db = Database(tmp_path / "e.db")
    db.migrate(version="test")
    calls: list[str] = []

    class Nothing:
        def songs(self, offset: int, size: int = 500) -> list[dict[str, Any]] | None:
            calls.append("link")
            return []

    def errand() -> None:
        calls.append("errand")
        raise RuntimeError("the music server is down")

    report = LibraryLinker(db, Nothing(), before=errand).run_once()

    assert calls[0] == "errand" and "link" in calls
    assert isinstance(report, LinkReport)
