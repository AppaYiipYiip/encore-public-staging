"""`GET me/plays` (P3-34, slice 0): the person's own plays, from the server's own record, newest first.

Why it exists: the phone's Year in Music used to sign in to the music server's own `/auth/login` and read its `/api/scrobble` through the gateway, which (a) is outside the
thin-client rule (ADR-R38), (b) never worked away from home (only `/rest` passes there) and (c) would break when the gateway shuts the music server's own doors by default. In
Encore mode the phone reports every play it counts to `POST plays` (`play_event`), and nowhere else, so that record is the history. The phone applies the rule for "a counted
play" (half the song, at most four minutes, at least thirty seconds) before it reports; the server stores what it is told, and this route gives it back.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from encore_server import refmerge
from encore_server.db import Database
from tests.conftest import creds, resolve, song

V1 = "/encore/api/v1"


def ids_of(items: list[dict[str, object]]) -> list[str]:
    return [str(i["id"]) for i in items]


def report(client: TestClient, user: str, ref: str, play_id: str, at: int, ms: int = 200_000, context: str | None = None) -> None:
    body: dict[str, object] = {"id": play_id, "ref": ref, "at": at, "msPlayed": ms}
    if context is not None:
        body["context"] = context
    assert client.post(f"{V1}/plays", params=creds(user), json=body).status_code in (200, 201)


def refs_of(client: TestClient, user: str, count: int) -> list[str]:
    return [
        str(r["id"]) for r in resolve(client, user, *[song(f"Song {i}", durationMs=100_000 + i * 20_000) for i in range(count)])
    ]


def test_a_person_gets_their_own_plays_newest_first_with_the_fields_a_year_needs(client: TestClient) -> None:
    a, b = refs_of(client, "marwa", 2)
    report(client, "marwa", a, "p-1", 1_700_000_000_000, 190_000, "album")
    report(client, "marwa", b, "p-2", 1_700_000_500_000, 210_000)

    answer = client.get(f"{V1}/me/plays", params=creds("marwa"))

    assert answer.status_code == 200
    body = answer.json()
    assert body["items"] == [
        {"id": "p-2", "ref": b, "at": 1_700_000_500_000, "msPlayed": 210_000, "context": None},
        {"id": "p-1", "ref": a, "at": 1_700_000_000_000, "msPlayed": 190_000, "context": "album"},
    ]
    assert body["nextCursor"] is None and "serverTime" in body


def test_somebody_elses_plays_never_appear_and_the_person_comes_from_the_token_only(client: TestClient) -> None:
    (ref,) = refs_of(client, "marwa", 1)
    report(client, "marwa", ref, "marwa-1", 1_700_000_000_000)
    report(client, "nina", ref, "nina-1", 1_700_000_100_000)

    mine = client.get(f"{V1}/me/plays", params=creds("marwa")).json()["items"]
    hers = client.get(f"{V1}/me/plays", params=creds("nina")).json()["items"]
    sneaky = client.get(f"{V1}/me/plays", params={**creds("nina"), "person": "marwa", "me": "marwa", "user": "marwa"}).json()[
        "items"
    ]

    assert ids_of(mine) == ["marwa-1"] and ids_of(hers) == ["nina-1"]
    assert ids_of(sneaky) == ["nina-1"], "a parameter never names the person"


def test_the_server_says_it_has_the_route_so_a_phone_never_tries_it_to_find_out(client: TestClient) -> None:
    assert "my-plays" in client.get(f"{V1}/info").json()["features"]


def test_it_asks_who_you_are(client: TestClient) -> None:
    assert client.get(f"{V1}/me/plays").status_code == 401
    assert client.get(f"{V1}/me/plays", params={"u": "marwa", "t": "x" * 32, "s": "salt1234"}).status_code == 401


def test_paging_across_equal_times_returns_every_play_exactly_once(client: TestClient) -> None:
    (ref,) = refs_of(client, "marwa", 1)
    same = 1_700_000_000_000
    for n in range(7):  # seven plays in the very same millisecond (a phone that reported a queue it had played offline)
        report(client, "marwa", ref, f"same-{n}", same)
    report(client, "marwa", ref, "earlier", same - 1)
    report(client, "marwa", ref, "later", same + 1)

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params = {**creds("marwa"), "limit": "3", **({"cursor": cursor} if cursor else {})}
        page = client.get(f"{V1}/me/plays", params=params).json()
        assert len(page["items"]) <= 3
        seen += ids_of(page["items"])
        cursor = page["nextCursor"]
        if cursor is None:
            break

    assert sorted(seen) == sorted([f"same-{n}" for n in range(7)] + ["earlier", "later"]), (
        "every play once: none skipped, none twice"
    )
    assert len(seen) == len(set(seen))
    assert seen[0] == "later" and seen[-1] == "earlier", "newest first"


def test_a_bad_cursor_and_a_silly_limit_are_told_not_guessed(client: TestClient) -> None:
    assert client.get(f"{V1}/me/plays", params={**creds("marwa"), "cursor": "nonsense"}).status_code == 400
    assert client.get(f"{V1}/me/plays", params={**creds("marwa"), "cursor": "12:"}).status_code == 400
    assert client.get(f"{V1}/me/plays", params={**creds("marwa"), "limit": "abc"}).status_code in (400, 422)
    refs_of(client, "marwa", 1)
    big = client.get(f"{V1}/me/plays", params={**creds("marwa"), "limit": "100000"})
    assert big.status_code == 200, "the limit is held to 500, not refused"
    assert client.get(f"{V1}/me/plays", params={**creds("marwa"), "limit": "0"}).status_code == 200


def test_a_play_of_a_song_that_was_merged_into_another_comes_back_as_the_survivor(client: TestClient, db: Database) -> None:
    survivor, loser = refs_of(client, "marwa", 2)
    report(client, "marwa", loser, "p-loser", 1_700_000_000_000)
    with client.app.state.services.db.tx() as conn:  # type: ignore[attr-defined]
        refmerge._merge_pair(conn, survivor, loser)  # noqa: SLF001 - the merge itself is proved in test_ref_merge; here only what the route says after it

    items = client.get(f"{V1}/me/plays", params=creds("marwa")).json()["items"]

    assert [(i["id"], i["ref"]) for i in items] == [("p-loser", survivor)]


def test_the_page_is_served_from_the_index_and_is_quick_for_a_person_with_fifty_thousand_plays(client: TestClient) -> None:
    (ref,) = refs_of(client, "marwa", 1)
    services = client.app.state.services  # type: ignore[attr-defined]
    with services.db.read() as conn:
        person = conn.execute("SELECT id FROM person WHERE navidrome_user = 'marwa'").fetchone()["id"]
    with services.db.tx() as conn:
        conn.executemany(
            "INSERT INTO play_event (id, person, ref, at, ms_played) VALUES (?,?,?,?,200000)",
            [
                (f"bulk-{n:06d}", person, ref, 1_600_000_000_000 + (n // 3) * 1000) for n in range(50_000)
            ],  # three plays to every second: ties everywhere
        )

    with services.db.read() as conn:
        plan = " ".join(
            str(r[3])
            for r in conn.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM play_event WHERE person = ? AND (at < ? OR (at = ? AND id < ?)) ORDER BY at DESC, id DESC LIMIT 501",
                (person, 1_700_000_000_000, 1_700_000_000_000, "z"),
            )
        )
    began = time.perf_counter()
    page = client.get(f"{V1}/me/plays", params={**creds("marwa"), "limit": "500"}).json()
    took_ms = (time.perf_counter() - began) * 1000

    print(f"PERF one page of 500 plays out of 50,000: {took_ms:.0f} ms (the whole request)")
    assert len(page["items"]) == 500 and page["nextCursor"] is not None
    assert "play_event_person" in plan and "SCAN play_event" not in plan, plan
    assert took_ms < 500, f"one page of 500 took {took_ms:.0f} ms"


def test_it_is_not_a_door_for_a_stranger_on_the_internet_either(client: TestClient) -> None:
    """A signed-in person's plays are theirs wherever they ask from; the route needs the token, which the tests above show."""
    assert client.get(f"{V1}/me/plays", params={"u": "nobody", "t": "0" * 32, "s": "salt1234"}).status_code == 401


FIXTURE = Path(__file__).resolve().parents[3] / "app" / "test" / "fixtures" / "server" / "me-plays-page.json"


def test_the_first_page_is_the_saved_fixture_the_phones_parser_reads(client: TestClient) -> None:
    """One contract: a REAL response of the real endpoint on synthetic data (fixed ids and times). When it changes this test fails until the file is written again
    (`ENCORE_WRITE_FIXTURES=1 pytest tests/test_my_plays.py -k saved_fixture`) and the app's parser is changed to read it: three plays, one with a context, and a
    next cursor."""
    (ref,) = refs_of(client, "marwa", 1)
    plays = (
        ("play-0", 1_700_000_300_000, 180_000, None),
        ("play-1", 1_700_000_200_000, 181_000, "album"),
        ("play-2", 1_700_000_200_000, 182_000, None),
        ("play-3", 1_700_000_100_000, 183_000, None),
    )
    for play_id, at, ms, context in plays:
        report(client, "marwa", ref, play_id, at, ms, context)

    response = client.get(f"{V1}/me/plays", params={**creds("marwa"), "limit": "3"})
    assert response.status_code == 200
    body = response.json()
    body.pop("serverTime")
    for item in body["items"]:
        item["ref"] = "sr_" + "a" * 26  # the ref id is made by the server at random: the fixture holds a fixed one
    text = json.dumps(body, indent=2, ensure_ascii=False) + "\n"

    if os.environ.get("ENCORE_WRITE_FIXTURES") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")

    assert FIXTURE.is_file(), "run with ENCORE_WRITE_FIXTURES=1 once to write it"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == body
    assert [i["id"] for i in body["items"]] == ["play-0", "play-2", "play-1"], "newest first, equal times by id, newest id first"
    assert body["nextCursor"] == "1700000200000:play-1"
