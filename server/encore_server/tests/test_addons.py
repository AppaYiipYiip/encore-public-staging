"""The add-ons (docs/35): one manifest per optional thing, the Host's choices in a table of their own, the admin routes and the command door onto the same operation.

What is proved: the manifest is complete and matches the document's table; a choice is stored, refused in a sentence when it cannot be made, and taken up when the server next
starts; only the owner reaches the routes, and a request from the internet gets a 404; the route and the command give the very same answer; and no route or operation can read
the server's internal `setting` table (its identity private key and the key that signs song addresses).
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from encore_server import addons, host_settings
from encore_server.addons import ADDONS, STATES, by_id
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.ops import cli
from tests.conftest import FakeVerifier

V1 = "/encore/api/v1"
HOME = {"X-Forwarded-For": "192.168.1.20"}
STRANGER = {"X-Forwarded-For": "203.0.113.9"}
PROXY = ("10.0.0.2", 50000)
ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------------------------------------------------- the manifest


def test_the_manifest_is_complete_and_consistent() -> None:
    ids = [a.id for a in ADDONS]
    assert len(ids) == len(set(ids)) and all(re.fullmatch(r"[a-z]+(-[a-z]+)*", i) for i in ids)
    settings = Settings()
    for a in ADDONS:
        assert a.title and a.summary.endswith(".") and set(a.states) <= set(STATES) and a.default in a.states, a.id
        assert a.running(settings) in STATES, a.id
        assert all(by_id(n) is not None for n in a.needs), a.id
        assert a.planned is None or re.fullmatch(r"(P\d-\d+|N-\d+)", a.planned), a.id
        assert not any(word in a.summary for word in ("Docker", "container", "port ", "Funnel")), (
            f"{a.id}: no technical words in a summary"
        )
        assert a.risk_text is None or a.risk_text_version >= 1
        assert a.setting is None or hasattr(settings, a.setting), a.id
    assert by_id("nothing") is None


def test_the_documents_table_and_the_manifest_list_the_same_add_ons() -> None:
    """docs/35 section 2: every add-on is a row there, and every row there is an add-on (a change of one is a change of the other, in one pull request)."""
    text = (ROOT / "docs" / "35-add-ons.md").read_text(encoding="utf-8")
    section = text[text.index("## 2. The add-ons") : text.index("## 3. The manifest")]
    in_doc = set(re.findall(r"\(`([a-z-]+)`\)", section))
    assert in_doc == {a.id for a in ADDONS}


def test_only_built_add_ons_the_server_reads_at_start_have_a_setting() -> None:
    assert {a.id for a in ADDONS if a.setting} == {"youtube", "catalogue", "album-pass"}
    assert all(not (a.setting and (a.planned or a.host_managed)) for a in ADDONS)


def test_no_route_and_no_operation_can_read_the_servers_internal_setting_table() -> None:
    """`setting` holds the identity PRIVATE key and the key that signs song addresses; the Host's choices are in `host_setting` and nothing else."""
    server = Path(__file__).resolve().parent.parent / "encore_server"
    for folder in ("routes", "ops", "addons"):
        for file in (server / folder).glob("*.py"):
            text = file.read_text(encoding="utf-8")
            assert not re.search(r"(FROM|INTO|UPDATE)\s+setting\b", text), file.name
    assert not re.search(r"(FROM|INTO|UPDATE)\s+setting\b", (server / "host_settings.py").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------------------------- the store and the start


def make_app(tmp_path: Path, **more: object):  # type: ignore[no-untyped-def]
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False, **more
    )  # type: ignore[arg-type]
    return settings, create_app(settings, verifier=FakeVerifier())


def test_a_stored_choice_is_put_over_the_environment_when_the_server_starts(tmp_path: Path) -> None:
    settings, app = make_app(tmp_path)
    with TestClient(app, client=PROXY):
        assert app.state.services.settings.album_pass is True
        host_settings.HostSettings(app.state.services.db).put("addon.album-pass", "off", "command")
    _, again = make_app(tmp_path)
    with TestClient(again, client=PROXY):
        assert again.state.services.settings.album_pass is False, "the choice took effect at the next start"
        assert again.state.services.settings.catalogue is True, "what was not chosen is what the environment says"


def test_a_stored_choice_for_the_catalogue_removes_its_feature_at_the_next_start(tmp_path: Path) -> None:
    _, app = make_app(tmp_path)
    with TestClient(app, client=PROXY) as client:
        assert "catalogue" in client.get(f"{V1}/info", headers=HOME).json()["features"]
        host_settings.HostSettings(app.state.services.db).put("addon.catalogue", "off", "command")
    _, again = make_app(tmp_path)
    with TestClient(again, client=PROXY) as client:
        assert "catalogue" not in client.get(f"{V1}/info", headers=HOME).json()["features"]


def test_a_value_that_is_not_a_state_of_the_add_on_is_ignored_at_start(tmp_path: Path) -> None:
    _, app = make_app(tmp_path)
    with TestClient(app, client=PROXY):
        host_settings.HostSettings(app.state.services.db).put("addon.album-pass", "sideways", "command")
    _, again = make_app(tmp_path)
    with TestClient(again, client=PROXY):
        assert again.state.services.settings.album_pass is True


# ---------------------------------------------------------------------------------------------------------------------- the routes


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[TestClient]:
    _, app = make_app(tmp_path)
    with TestClient(app, client=PROXY) as client:
        yield client


def token(client: TestClient, user: str) -> dict[str, str]:
    answer = client.post(
        f"{V1}/auth/login",
        json={"username": user, "password": f"pw-{user}", "deviceName": "browser", "deviceKind": "web"},
        headers=HOME,
    )
    assert answer.status_code == 200, answer.text
    return {"Authorization": f"Bearer {answer.json()['deviceToken']}", **HOME}


def items(client: TestClient, headers: dict[str, str]) -> dict[str, dict]:  # type: ignore[type-arg]
    answer = client.get(f"{V1}/admin/addons", headers=headers)
    assert answer.status_code == 200, answer.text
    return {i["id"]: i for i in answer.json()["items"]}


def test_the_owner_lists_every_add_on_with_its_state_and_what_it_needs(rig: TestClient) -> None:
    owner = token(rig, "marwa")
    found = items(rig, owner)
    assert list(found) == [a.id for a in ADDONS]
    album = found["album-pass"]
    assert album["state"] == "runs" and album["running"] == "runs" and album["restartNeeded"] is False
    assert album["needs"] == ["catalogue"] and album["riskText"] and album["riskTextVersion"] == 1 and album["planned"] is None
    assert found["federation"]["planned"] == "P4-09" and found["away"]["hostManaged"]
    assert found["lossless"]["state"] == "off" and found["lossless"]["riskText"].startswith("This asks the Soulseek network")
    assert "password" not in json.dumps(found).lower() and "key" not in set(found["youtube"])


def test_a_member_and_a_stranger_and_the_internet_get_what_they_should(rig: TestClient) -> None:
    token(rig, "marwa")  # the first person is the owner
    member = token(rig, "nina")
    assert rig.get(f"{V1}/admin/addons", headers=member).status_code == 403
    assert rig.put(f"{V1}/admin/addons/youtube", json={"state": "off"}, headers=member).status_code == 403
    assert rig.get(f"{V1}/admin/addons", headers=HOME).status_code == 401
    unknown = rig.get(f"{V1}/nothing-here", headers=STRANGER)
    for headers in (STRANGER, {**token(rig, "marwa"), **STRANGER}):  # the second is the owner's own token, used from the internet
        assert rig.get(f"{V1}/admin/addons", headers=headers).json() == unknown.json()
        assert rig.put(f"{V1}/admin/addons/youtube", json={"state": "off"}, headers=headers).status_code == 404


def test_a_choice_is_stored_says_it_waits_for_a_restart_and_survives_one(tmp_path: Path) -> None:
    _, app = make_app(tmp_path)
    with TestClient(app, client=PROXY) as client:
        owner = token(client, "marwa")
        done = client.put(
            f"{V1}/admin/addons/catalogue", json={"state": "runs"}, headers=owner
        )  # already running: stored, nothing waits
        assert done.status_code == 200 and done.json()["addon"]["restartNeeded"] is False
        album = client.put(f"{V1}/admin/addons/album-pass", json={"state": "off"}, headers=owner)
        assert album.status_code == 200
        assert (
            album.json()["addon"]["state"] == "off"
            and album.json()["addon"]["running"] == "runs"
            and album.json()["addon"]["restartNeeded"] is True
        )
        assert items(client, owner)["album-pass"]["restartNeeded"] is True
    _, again = make_app(tmp_path)
    with TestClient(again, client=PROXY) as client:
        found = items(client, token(client, "marwa"))["album-pass"]
        assert found["state"] == "off" and found["running"] == "off" and found["restartNeeded"] is False


def put(client: TestClient, headers: dict[str, str], addon_id: str, **body: object):  # type: ignore[no-untyped-def]
    return client.put(f"{V1}/admin/addons/{addon_id}", json=body, headers=headers)


def test_what_cannot_be_chosen_is_refused_in_a_sentence_and_nothing_is_stored(rig: TestClient) -> None:
    owner = token(rig, "marwa")
    cases = [
        (("nothing", {"state": "off"}), 404, "no such add-on"),
        (("federation", {"state": "runs"}), 409, "not built yet (P4-09)"),
        (("lossless", {"state": "runs", "riskTextVersion": 1}), 409, "not built yet (P4-04)"),
        (("away", {"state": "runs"}), 409, "encore funnel"),
        (("youtube", {"state": "yours"}), 400, "can be: runs, off"),
        (("youtube", {"state": 7}), 400, "can be"),
        (("youtube", {}), 400, "can be"),
    ]
    for (addon_id, body), status, words in cases:
        answer = put(rig, owner, addon_id, **body)
        assert answer.status_code == status and words in answer.json()["error"]["message"], (addon_id, body, answer.text)
    assert all(i["state"] == i["running"] or i["planned"] or i["hostManaged"] for i in items(rig, owner).values())


def test_an_add_on_needs_what_it_needs_both_ways(rig: TestClient) -> None:
    owner = token(rig, "marwa")
    refused = put(rig, owner, "catalogue", state="off")
    assert refused.status_code == 409 and "Turn off “Real albums” first" in refused.json()["error"]["message"]
    assert put(rig, owner, "album-pass", state="off").status_code == 200
    assert put(rig, owner, "catalogue", state="off").status_code == 200
    again = put(rig, owner, "album-pass", state="runs", riskTextVersion=1)
    assert again.status_code == 409 and "Turn on “Pictures, search and artist pages” first" in again.json()["error"]["message"]


def test_a_risky_switch_on_needs_the_risk_text_in_its_present_words(rig: TestClient) -> None:
    owner = token(rig, "marwa")
    assert put(rig, owner, "album-pass", state="off").status_code == 200
    asked = put(rig, owner, "album-pass", state="runs")
    assert (
        asked.status_code == 400
        and asked.json()["error"]["details"]["riskTextVersion"] == 1
        and asked.json()["error"]["details"]["riskText"]
    )
    old = put(rig, owner, "album-pass", state="runs", riskTextVersion=0)
    assert old.status_code == 400, "words that have changed since the Host last read them ask again"
    assert put(rig, owner, "album-pass", state="runs", riskTextVersion=1).status_code == 200
    # switching OFF never asks: off is always safe
    assert put(rig, owner, "album-pass", state="off").status_code == 200


# ---------------------------------------------------------------------------------------------------------------------- one operation, two doors


def test_the_route_and_the_command_give_the_same_answer(tmp_path: Path) -> None:
    settings, app = make_app(tmp_path)
    with TestClient(app, client=PROXY) as client:
        owner = token(client, "marwa")
        via_route = put(client, owner, "album-pass", state="off").json()["addon"]
        listed = items(client, owner)
    # the command, in its own process's way: the same database, the same settings, what the server recorded when it started
    twin_settings, twin = make_app(tmp_path / "twin")
    with TestClient(twin, client=PROXY):
        out, err = io.StringIO(), io.StringIO()
        assert cli.command(["addon", "set", "album-pass", "off", "--json"], settings=twin_settings, out=out, err=err) == 0, (
            err.getvalue()
        )
        via_command = json.loads(out.getvalue())["addon"]
        out = io.StringIO()
        assert cli.command(["addon", "list", "--json"], settings=twin_settings, out=out, err=err) == 0
        command_list = {i["id"]: i for i in json.loads(out.getvalue())["items"]}
    assert via_command == via_route
    assert command_list["album-pass"] == listed["album-pass"] and list(command_list) == list(listed)
    assert settings is not twin_settings


def test_the_command_refuses_with_the_same_sentences_and_says_what_it_needs(tmp_path: Path) -> None:
    settings, app = make_app(tmp_path)
    with TestClient(app, client=PROXY):
        for argv, code, words in [
            (["addon", "set", "federation", "runs"], 1, "not built yet (P4-09)"),
            (["addon", "set", "album-pass", "yours"], 1, "can be: runs, off"),
            (["addon", "set", "nothing", "off"], 1, "no such add-on"),
            (["addon", "set", "album-pass"], 2, "usage"),
            (["nonsense"], 2, "usage"),
        ]:
            out, err = io.StringIO(), io.StringIO()
            assert (
                cli.command(argv, settings=settings, out=out, err=err) == code
                and words in err.getvalue()
                and out.getvalue() == ""
            )
        risky, risk_err = io.StringIO(), io.StringIO()
        cli.command(["addon", "set", "album-pass", "off"], settings=settings, out=risky, err=risk_err)
        again_err = io.StringIO()
        assert cli.command(["addon", "set", "album-pass", "runs"], settings=settings, out=io.StringIO(), err=again_err) == 1
        assert "Read the warning" in again_err.getvalue()
        ok = io.StringIO()
        assert (
            cli.command(
                ["addon", "set", "album-pass", "runs", "--risk-version", "1", "--json"],
                settings=settings,
                out=ok,
                err=io.StringIO(),
            )
            == 0
        )
        assert json.loads(ok.getvalue())["addon"]["state"] == "runs"


def test_the_command_says_to_start_the_server_first_when_there_is_no_database(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "nothing-here", music_dir=tmp_path, youtube=False)
    err = io.StringIO()
    assert cli.command(["addon", "list"], settings=settings, out=io.StringIO(), err=err) == 1
    assert "start it first" in err.getvalue()


def test_a_database_before_the_table_is_a_sentence_not_a_trace(tmp_path: Path) -> None:
    db = Database(tmp_path / "data" / "encore.db")
    db.migrate(migrations=[m for m in Database._migrations() if m[0] <= 19])
    settings = Settings(data_dir=tmp_path / "data", music_dir=tmp_path, youtube=False)
    err = io.StringIO()
    assert (
        cli.command(["addon", "list"], settings=settings, out=io.StringIO(), err=err) == 1 and "start it first" in err.getvalue()
    )
    assert addons.ADDONS  # the manifest itself does not need the table


def test_the_readable_lines_say_the_state_and_what_stands_in_the_way(tmp_path: Path) -> None:
    settings, app = make_app(tmp_path)
    with TestClient(app, client=PROXY):
        out = io.StringIO()
        assert cli.command(["addon", "list"], settings=settings, out=out, err=io.StringIO()) == 0
        text = out.getvalue()
        assert "album-pass       runs   Real albums" in text
        assert "federation       off    Friends on other servers (not built yet: P4-09)" in text
        assert "away             off    Away from home (changed on the computer: encore funnel / autobackup)" in text
        done = io.StringIO()
        assert cli.command(["addon", "set", "catalogue", "runs"], settings=settings, out=done, err=io.StringIO()) == 0
        assert done.getvalue().startswith("catalogue") and "sudo encore restart" not in done.getvalue(), (
            "already what the server is doing: nothing waits"
        )
        waits = io.StringIO()
        assert cli.command(["addon", "set", "album-pass", "off"], settings=settings, out=waits, err=io.StringIO()) == 0
        assert "sudo encore restart" in waits.getvalue()
