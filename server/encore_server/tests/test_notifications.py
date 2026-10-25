"""The bell (docs/tasks P2-15 slice A, ADR-R44): news is kept per person and said in words; nothing is pushed to a phone from here."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server.errors import ApiError
from encore_server.notifications import KEEP_AT_MOST, Notifications
from tests.conftest import creds

V1 = "/encore/api/v1"


def person_id(client: TestClient, user: str) -> str:
    return str(client.get(f"{V1}/me", params=creds(user)).json()["id"])


def news(client: TestClient) -> Notifications:
    return client.app.state.services.notifications  # type: ignore[no-any-return, attr-defined]


def listed(client: TestClient, user: str = "marwa", **params: Any) -> dict[str, Any]:
    response = client.get(f"{V1}/notifications", params={**creds(user), **params})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    body.pop("serverTime")
    return body


def test_a_person_with_no_news_sees_an_empty_list_and_nothing_unread(client: TestClient) -> None:
    body = listed(client)

    assert body == {"items": [], "unread": 0, "cursor": "0"}


def test_news_is_listed_newest_first_with_what_a_screen_needs_to_say_it(client: TestClient) -> None:
    marwa = person_id(client, "marwa")
    news(client).push(marwa, "import_done", "Your import is ready", body="Road trip: 47 of 48 songs", route="/settings/import")
    news(client).push(marwa, "invite_used", "Sara joined")

    body = listed(client)

    assert [i["title"] for i in body["items"]] == ["Sara joined", "Your import is ready"]
    first = body["items"][1]
    assert set(first) == {"id", "kind", "title", "body", "route", "createdAt", "read"}
    assert (first["kind"], first["body"], first["route"], first["read"]) == (
        "import_done",
        "Road trip: 47 of 48 songs",
        "/settings/import",
        False,
    )
    assert body["unread"] == 2 and body["cursor"] == str(body["items"][0]["id"])


def test_everybody_sees_only_their_own_news(client: TestClient) -> None:
    marwa, nina = person_id(client, "marwa"), person_id(client, "nina")
    news(client).push(marwa, "invite_used", "Sara joined")

    assert listed(client, "nina")["items"] == []
    assert len(listed(client, "marwa")["items"]) == 1
    assert nina != marwa


def test_since_gives_only_what_is_newer(client: TestClient) -> None:
    marwa = person_id(client, "marwa")
    news(client).push(marwa, "invite_used", "Sara joined")
    cursor = listed(client)["cursor"]
    news(client).push(marwa, "import_done", "Your import is ready")

    newer = listed(client, since=cursor)

    assert [i["title"] for i in newer["items"]] == ["Your import is ready"]
    assert newer["unread"] == 2, "the count is of everything unread, not only of what is newer"
    assert listed(client, since=newer["cursor"])["items"] == []


def test_reading_marks_everything_up_to_an_id_and_is_safe_to_repeat(client: TestClient) -> None:
    marwa = person_id(client, "marwa")
    for title in ("One", "Two", "Three"):
        news(client).push(marwa, "invite_used", title)
    ids = sorted(i["id"] for i in listed(client)["items"])

    done = client.post(f"{V1}/notifications/read", params=creds("marwa"), json={"upTo": ids[1]})
    assert done.status_code == 200 and done.json()["unread"] == 1
    again = client.post(f"{V1}/notifications/read", params=creds("marwa"), json={"upTo": ids[1]})
    assert again.json()["unread"] == 1

    items = listed(client)["items"]
    assert [(i["title"], i["read"]) for i in items] == [("Three", False), ("Two", True), ("One", True)]
    assert client.post(f"{V1}/notifications/read", params=creds("marwa"), json={}).json()["unread"] == 0


def test_somebody_cannot_read_away_the_news_of_another_person(client: TestClient) -> None:
    marwa = person_id(client, "marwa")
    person_id(client, "nina")
    news(client).push(marwa, "invite_used", "Sara joined")

    client.post(f"{V1}/notifications/read", params=creds("nina"), json={})

    assert listed(client, "marwa")["unread"] == 1


def test_the_same_news_is_made_once_however_often_it_is_told(client: TestClient) -> None:
    marwa = person_id(client, "marwa")

    first = news(client).push(marwa, "import_done", "Your import is ready", dedupe="import:im_1")
    second = news(client).push(marwa, "import_done", "Your import is ready", dedupe="import:im_1")

    assert first is True and second is False
    assert len(listed(client)["items"]) == 1


def test_the_person_is_told_at_once_on_their_devices(client: TestClient) -> None:
    marwa = person_id(client, "marwa")
    told: list[tuple[str, dict[str, Any]]] = []
    client.app.state.services.hub.publish = lambda person, event, **kw: told.append((person, event))  # type: ignore[attr-defined]

    news(client).push(marwa, "invite_used", "Sara joined")
    news(client).push(marwa, "invite_used", "Sara joined", dedupe="x")
    news(client).push(marwa, "invite_used", "Sara joined", dedupe="x")

    assert told == [
        (marwa, {"type": "notification.new", "unread": 1}),
        (marwa, {"type": "notification.new", "unread": 2}),
    ], "a repeat that made nothing says nothing"


def test_only_the_kinds_the_drawing_has_are_accepted(client: TestClient) -> None:
    marwa = person_id(client, "marwa")

    with pytest.raises(ApiError):
        news(client).push(marwa, "advertisement", "Buy things")


def test_the_oldest_go_when_there_are_too_many(client: TestClient) -> None:
    marwa = person_id(client, "marwa")
    for n in range(KEEP_AT_MOST + 5):
        news(client).push(marwa, "invite_used", f"News {n}")

    body = listed(client, limit=200)

    assert len(body["items"]) == KEEP_AT_MOST
    assert body["items"][0]["title"] == f"News {KEEP_AT_MOST + 4}"
    assert body["items"][-1]["title"] == "News 5"


def test_news_older_than_ninety_days_goes_when_new_news_arrives(client: TestClient) -> None:
    marwa = person_id(client, "marwa")
    notes = news(client)
    notes.push(marwa, "invite_used", "Long ago")
    with client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        conn.execute("UPDATE notification SET created_at = created_at - ?", (91 * 24 * 3600 * 1000,))

    notes.push(marwa, "invite_used", "Today")

    assert [i["title"] for i in listed(client)["items"]] == ["Today"]


def test_the_list_needs_a_signed_in_person(client: TestClient) -> None:
    assert client.get(f"{V1}/notifications").status_code == 401
    assert client.post(f"{V1}/notifications/read", json={}).status_code == 401


def test_a_bad_limit_or_cursor_is_refused_in_words(client: TestClient) -> None:
    for params in ({"limit": 0}, {"limit": 1000}, {"since": "later"}):
        response = client.get(f"{V1}/notifications", params={**creds("marwa"), **params})
        assert response.status_code == 400, params
