"""N-31 (N-27 slice 2d): the songs of deleted playlists, removed entries and old imports are cleaned away too.

Slice 2a's janitor never retired a ref that a TOMBSTONED playlist entry or an `import_entry` row still named (the foreign key has no cascade, and an away
phone learns a removal from those rows), so the 29 refs of a deleted test playlist stayed for ever (VM 108, 14 Nov 2026). This slice removes the POINTERS,
not the janitor's rule: tombstoned entries are purged after 90 days, the entries of an old import after 60, and then the janitor retires their refs and
`ref_gone` tells the phones.

What the design in the item got wrong, shown by the code, and what is built instead (each is a test below):

* A deleted playlist's ROW is kept (it holds no ref; it is the tombstone). `migrate_from_navidrome` finds a source playlist by `(owner, source_id)` with no
  `deleted_at` filter, so purging the row would bring a deleted playlist back; `import.playlist` has a foreign key with no cascade; a create retried by a
  long-offline phone still answers with the deleted row. Only the ENTRIES are purged.
* A removed entry of a LIVE playlist is purged too, and the feed then says `{id, playlist, deleted: true}`: the phone skips an entry that names no playlist
  (`encore_writer.dart` `if (e.id.isEmpty || e.playlist.isEmpty) continue;`), so the feed must name it: `change_log.parent` (migration 0016) keeps the
  playlist of an `entry` row.
* An import's counts were computed from its entries: they are stored when its entries are purged (migration 0016).

The data is SYNTHETIC: fixed clock (`NOW`), invented songs, rows written with SQL where a test needs an exact age. The rows are built with `library` itself
wherever the feed is the thing under test.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from encore_server import library, ref_janitor, refs, tombstone_purge
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.ids import new_id, now_ms
from encore_server.imports.service import ImportService
from encore_server.navidrome import NavidromeClient
from encore_server.navidrome_admin import NavidromeAdmin
from encore_server.tombstone_purge import ENTRY_AGE_MS, ENTRY_RULES, IMPORT_AGE_MS, IMPORT_RULES, TombstonePurge
from tests.conftest import creds

V1 = "/encore/api/v1"
DAY = 24 * 3600 * 1000
NOW = 1_800_000_000_000  # the clock of every test: the purge is given it, it never reads the wall clock
OLD = NOW - 100 * DAY  # a song ref made 100 days ago (the janitor wants 14)


# ------------------------------------------------------------------------------------------------ a world to hang rows from


def make_person(db: Database, name: str = "me") -> str:
    with db.tx() as conn:
        return str(library.ensure_person(conn, name)["id"])


_next_ref = iter(range(1, 10_000))


def make_ref(db: Database, created_at: int = OLD) -> str:
    n = next(_next_ref)
    with db.tx() as conn:
        ref = str(refs.resolve(conn, {"title": f"Song {n}", "artists": ["Artist"], "durationMs": 180000 + n * 10000})["id"])
        conn.execute("UPDATE song_ref SET created_at = ? WHERE id = ?", (created_at, ref))
    return ref


def make_list(db: Database, me: str, ref_ids: list[str], name: str = "L") -> tuple[str, list[str]]:
    """A playlist of [me] holding these songs: its id and the ids of its entries, in order."""
    playlist = new_id("pl")
    with db.tx() as conn:
        library.create_playlist(conn, me, playlist, name)
        entries = library.add_entries(conn, me, playlist, [{"ref": r} for r in ref_ids])
    return playlist, entries


def remove_entry(db: Database, me: str, playlist: str, entry: str, *, days_ago: int) -> None:
    """The person removes the entry, and the removal is [days_ago] days old at NOW."""
    with db.tx() as conn:
        library.remove_entries(conn, me, playlist, [entry])
        conn.execute("UPDATE playlist_entry SET deleted_at = ? WHERE id = ?", (NOW - days_ago * DAY, entry))


def delete_playlist(db: Database, me: str, playlist: str, *, days_ago: int) -> None:
    with db.tx() as conn:
        library.delete_playlist(conn, me, playlist)
        conn.execute("UPDATE playlist SET deleted_at = ? WHERE id = ?", (NOW - days_ago * DAY, playlist))


def purge(db: Database, **kwargs: Any) -> TombstonePurge:
    return TombstonePurge(db, clock=lambda: NOW, **kwargs)


def janitor(db: Database) -> ref_janitor.RefJanitor:
    return ref_janitor.RefJanitor(db, clock=lambda: NOW)


def entry_ids(db: Database) -> set[str]:
    with db.read() as conn:
        return {row["id"] for row in conn.execute("SELECT id FROM playlist_entry")}


def ref_ids(db: Database) -> set[str]:
    with db.read() as conn:
        return {row["id"] for row in conn.execute("SELECT id FROM song_ref")}


def make_import(
    db: Database,
    me: str,
    *,
    state: str = "done",
    updated_days_ago: int = 61,
    states: tuple[str, ...] = ("matched", "matched", "not_found"),
    playlist: str | None = None,
) -> str:
    """An import with one entry per item of [states] (each on a song of its own), last touched [updated_days_ago] days before NOW."""
    import_id = new_id("im")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO import (id, person, source, name, playlist, state, created_at, updated_at) VALUES (?,?, 'file', 'Road trip', ?, ?, 1, ?)",
            (import_id, me, playlist, state, NOW - updated_days_ago * DAY),
        )
    for position, entry_state in enumerate(states):
        ref = make_ref(db)
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO import_entry (import, position, ref, state) VALUES (?,?,?,?)",
                (import_id, position, ref, entry_state),
            )
    return import_id


def record(db: Database, me: str, import_id: str) -> dict[str, Any]:
    with db.read() as conn:
        found = ImportService._record(conn, me, import_id)
    assert found is not None
    return found


def import_state(db: Database, import_id: str) -> tuple[int, int | None, int | None]:
    """(how many entries it still has, when they were purged, the stored total)."""
    with db.read() as conn:
        row = conn.execute("SELECT entries_purged_at, final_total FROM import WHERE id = ?", (import_id,)).fetchone()
        entries = conn.execute("SELECT COUNT(*) FROM import_entry WHERE import = ?", (import_id,)).fetchone()[0]
    return int(entries), row["entries_purged_at"], row["final_total"]


# ------------------------------------------------------------------------------------------------ which entries go


def _removed_entry_of_a_live_playlist(db: Database, me: str) -> str:
    playlist, (entry,) = make_list(db, me, [make_ref(db)])
    remove_entry(db, me, playlist, entry, days_ago=91)
    return entry


def _entry_of_a_playlist_deleted_long_ago(db: Database, me: str) -> str:
    playlist, (entry,) = make_list(db, me, [make_ref(db)])
    delete_playlist(db, me, playlist, days_ago=91)
    return entry


#: rule -> a scenario in which ONLY that rule removes the entry it returns.
ENTRY_SCENARIOS: dict[str, Callable[[Database, str], str]] = {
    "removed_entry": _removed_entry_of_a_live_playlist,
    "entry_of_deleted_playlist": _entry_of_a_playlist_deleted_long_ago,
}


@pytest.mark.parametrize("rule", ENTRY_SCENARIOS)
def test_an_entry_a_rule_names_is_purged_after_ninety_days(db: Database, rule: str) -> None:
    me = make_person(db)
    goes = ENTRY_SCENARIOS[rule](db, me)
    _, (stays,) = make_list(db, me, [make_ref(db)])

    result = purge(db).run_once()

    assert result.entries == 1
    assert entry_ids(db) == {stays}, f"{rule}: {goes} must go and a live entry of a live playlist must stay"


@pytest.mark.parametrize("rule", ENTRY_SCENARIOS)
def test_every_entry_rule_is_load_bearing_without_it_the_entry_it_names_stays(
    db: Database, monkeypatch: pytest.MonkeyPatch, rule: str
) -> None:
    """Without this a rule could be wrong (or deleted) and the test above would still pass because the other rule happened to take the entry."""
    me = make_person(db)
    goes = ENTRY_SCENARIOS[rule](db, me)
    monkeypatch.setattr(tombstone_purge, "ENTRY_RULES", {k: v for k, v in ENTRY_RULES.items() if k != rule})

    purge(db).run_once()

    assert goes in entry_ids(db), f"the rule {rule!r} is not what purges the entry in its scenario"


def test_every_scenario_names_a_rule_and_every_rule_has_a_scenario() -> None:
    assert set(ENTRY_SCENARIOS) == set(ENTRY_RULES)


def test_the_entry_age_is_exactly_ninety_days_counted_from_the_removal_and_from_the_deletion(db: Database) -> None:
    assert ENTRY_AGE_MS == 90 * DAY
    me = make_person(db)
    live_list, (on_the_line, one_older) = make_list(db, me, [make_ref(db), make_ref(db)])
    with db.tx() as conn:
        library.remove_entries(conn, me, live_list, [on_the_line, one_older])
        conn.execute("UPDATE playlist_entry SET deleted_at = ? WHERE id = ?", (NOW - ENTRY_AGE_MS, on_the_line))
        conn.execute("UPDATE playlist_entry SET deleted_at = ? WHERE id = ?", (NOW - ENTRY_AGE_MS - 1, one_older))
    deleted_list, (list_on_the_line,) = make_list(db, me, [make_ref(db)])
    deleted_list_2, (list_one_older,) = make_list(db, me, [make_ref(db)])
    with db.tx() as conn:
        library.delete_playlist(conn, me, deleted_list)
        library.delete_playlist(conn, me, deleted_list_2)
        conn.execute("UPDATE playlist SET deleted_at = ? WHERE id = ?", (NOW - ENTRY_AGE_MS, deleted_list))
        conn.execute("UPDATE playlist SET deleted_at = ? WHERE id = ?", (NOW - ENTRY_AGE_MS - 1, deleted_list_2))

    purge(db).run_once()

    assert entry_ids(db) == {on_the_line, list_on_the_line}, "one millisecond past the line goes; the line itself stays"
    assert one_older not in entry_ids(db) and list_one_older not in entry_ids(db)


def test_a_live_entry_of_a_live_playlist_is_never_purged_however_old(db: Database) -> None:
    me = make_person(db)
    _, (entry,) = make_list(db, me, [make_ref(db)])
    with db.tx() as conn:
        conn.execute("UPDATE playlist_entry SET at = 1")

    assert purge(db).run_once() == (0, 0)
    assert entry_ids(db) == {entry}


def test_a_deleted_playlist_keeps_its_row_only_its_songs_go(db: Database) -> None:
    """The playlist row is the tombstone: it holds no ref, a second 'bring over my library' finds it by `source_id`, and an import may name it."""
    me = make_person(db)
    playlist, _ = make_list(db, me, [make_ref(db), make_ref(db)])
    with db.tx() as conn:
        conn.execute("UPDATE playlist SET source_id = 'nd:p1' WHERE id = ?", (playlist,))
    delete_playlist(db, me, playlist, days_ago=100)

    purge(db).run_once()

    assert entry_ids(db) == set()
    with db.read() as conn:
        row = conn.execute("SELECT deleted_at, source_id FROM playlist WHERE id = ?", (playlist,)).fetchone()
    assert row["deleted_at"] == NOW - 100 * DAY and row["source_id"] == "nd:p1"


def test_a_second_pass_changes_nothing(db: Database) -> None:
    me = make_person(db)
    for scenario in ENTRY_SCENARIOS.values():
        scenario(db, me)
    make_import(db, me)

    assert purge(db).run_once() == (2, 1)
    with db.read() as conn:
        snapshot = (
            [tuple(r) for r in conn.execute("SELECT * FROM playlist_entry ORDER BY id")],
            [tuple(r) for r in conn.execute("SELECT * FROM import ORDER BY id")],
        )
    assert purge(db).run_once() == (0, 0)
    with db.read() as conn:
        again = (
            [tuple(r) for r in conn.execute("SELECT * FROM playlist_entry ORDER BY id")],
            [tuple(r) for r in conn.execute("SELECT * FROM import ORDER BY id")],
        )
    assert again == snapshot


def test_the_pass_says_so_once_when_it_did_something_and_is_silent_when_it_did_not(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    me = make_person(db)
    _entry_of_a_playlist_deleted_long_ago(db, me)
    with caplog.at_level(logging.INFO, logger="encore_server.tombstone_purge"):
        purge(db).run_once()
        purge(db).run_once()

    lines = [r.getMessage() for r in caplog.records if r.name == "encore_server.tombstone_purge"]
    assert len(lines) == 1 and "1 playlist entries" in lines[0]


def test_the_batch_is_applied_to_the_entries_and_what_is_left_goes_on_the_next_pass(db: Database) -> None:
    assert tombstone_purge.BATCH == 5000
    me = make_person(db)
    playlist, _ = make_list(db, me, [make_ref(db) for _ in range(5)])
    delete_playlist(db, me, playlist, days_ago=100)

    assert purge(db, batch=2).run_once().entries == 2
    assert len(entry_ids(db)) == 3
    assert purge(db, batch=2).run_once().entries == 2
    assert purge(db, batch=2).run_once().entries == 1
    assert purge(db, batch=2).run_once().entries == 0


def test_an_entry_both_removed_and_in_a_deleted_playlist_is_counted_once(db: Database) -> None:
    me = make_person(db)
    playlist, (entry,) = make_list(db, me, [make_ref(db)])
    remove_entry(db, me, playlist, entry, days_ago=100)
    delete_playlist(db, me, playlist, days_ago=100)

    assert purge(db).run_once().entries == 1


def test_the_purge_reads_the_tombstones_by_their_indexes_and_never_scans_the_playlists_or_their_entries(db: Database) -> None:
    """The pass runs every hour on a table that holds every entry of every person: a scan of it makes the pass slower with every song anybody adds."""
    plan = tombstone_purge.query_plan(db)

    assert plan, "the plan was not read"
    shown = "\n".join(plan)
    assert not [line for line in plan if "SCAN playlist" in line], shown
    assert any("playlist_entry_removed" in line for line in plan) and any("playlist_deleted" in line for line in plan), shown


# ------------------------------------------------------------------------------------------------ which imports go


def test_an_import_finished_more_than_sixty_days_ago_loses_its_songs_and_keeps_its_counts(db: Database) -> None:
    assert IMPORT_AGE_MS == 60 * DAY
    me = make_person(db)
    import_id = make_import(
        db, me, states=("matched", "matched", "not_found", "not_found", "not_found", "pending"), state="stopped"
    )
    with db.tx() as conn:  # one of its songs has a copy on the server
        first = conn.execute("SELECT ref FROM import_entry WHERE import = ? AND position = 0", (import_id,)).fetchone()["ref"]
        conn.execute(
            "INSERT INTO song_file (id, ref, navidrome_song_id, source, added_at) VALUES ('sf_1', ?, 'nd-1', 'library', 1)",
            (first,),
        )
    before = record(db, me, import_id)
    assert (before["total"], before["matched"], before["unmatched"], before["pending"], before["kept"]) == (6, 2, 3, 1, 1)

    result = purge(db).run_once()

    assert result.imports == 1
    assert import_state(db, import_id) == (0, NOW, 6)
    assert record(db, me, import_id) == before, "what a person sees of an old import does not change: counts, not songs"


@pytest.mark.parametrize("state", ["done", "stopped", "failed"])
def test_a_finished_import_of_any_kind_is_purged(db: Database, state: str) -> None:
    me = make_person(db)
    import_id = make_import(db, me, state=state)

    assert purge(db).run_once().imports == 1
    assert import_state(db, import_id)[0] == 0


def _a_running_import(db: Database, me: str) -> str:
    return make_import(db, me, state="running", updated_days_ago=400)


def _an_import_finished_a_day_short(db: Database, me: str) -> str:
    return make_import(db, me, state="done", updated_days_ago=59)


def _an_import_already_purged(db: Database, me: str) -> str:
    import_id = make_import(db, me, states=(), state="done", updated_days_ago=200)
    with db.tx() as conn:
        conn.execute("UPDATE import SET entries_purged_at = ?, final_total = 7 WHERE id = ?", (NOW - 100 * DAY, import_id))
    return import_id


#: rule -> an import that breaks ONLY that rule: nothing may happen to it, and without the rule something does.
IMPORT_SCENARIOS: dict[str, Callable[[Database, str], str]] = {
    "finished": _a_running_import,
    "sixty_days": _an_import_finished_a_day_short,
    "not_yet_purged": _an_import_already_purged,
}


@pytest.mark.parametrize("rule", IMPORT_SCENARIOS)
def test_an_import_that_breaks_a_rule_is_left_alone(db: Database, rule: str) -> None:
    me = make_person(db)
    import_id = IMPORT_SCENARIOS[rule](db, me)
    before = import_state(db, import_id)

    assert purge(db).run_once().imports == 0
    assert import_state(db, import_id) == before


@pytest.mark.parametrize("rule", IMPORT_SCENARIOS)
def test_every_import_rule_is_load_bearing_without_it_the_import_is_touched(
    db: Database, monkeypatch: pytest.MonkeyPatch, rule: str
) -> None:
    me = make_person(db)
    import_id = IMPORT_SCENARIOS[rule](db, me)
    before = import_state(db, import_id)
    monkeypatch.setattr(tombstone_purge, "IMPORT_RULES", {k: v for k, v in IMPORT_RULES.items() if k != rule})

    purge(db).run_once()

    assert import_state(db, import_id) != before, f"the rule {rule!r} is not what keeps this import"


def test_every_import_scenario_names_a_rule_and_every_rule_has_a_scenario() -> None:
    assert set(IMPORT_SCENARIOS) == set(IMPORT_RULES)


def test_the_import_age_is_exactly_sixty_days_from_the_last_change(db: Database) -> None:
    me = make_person(db)
    on_the_line = make_import(db, me, updated_days_ago=60)
    one_older = make_import(db, me, updated_days_ago=60)
    with db.tx() as conn:
        conn.execute("UPDATE import SET updated_at = ? WHERE id = ?", (NOW - IMPORT_AGE_MS - 1, one_older))

    assert purge(db).run_once().imports == 1
    assert import_state(db, on_the_line)[0] == 3 and import_state(db, one_older)[0] == 0


def test_an_import_keeps_its_row_and_its_playlist_and_the_playlist_keeps_its_songs(db: Database) -> None:
    me = make_person(db)
    playlist, (entry,) = make_list(db, me, [make_ref(db)])
    import_id = make_import(db, me, playlist=playlist)

    purge(db).run_once()

    with db.read() as conn:
        assert conn.execute("SELECT playlist FROM import WHERE id = ?", (import_id,)).fetchone()["playlist"] == playlist
    assert entry_ids(db) == {entry}, "an import's songs are not the playlist's songs"


def test_a_pass_that_fails_changes_nothing_not_even_what_an_earlier_statement_did(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    me = make_person(db)
    _entry_of_a_playlist_deleted_long_ago(db, me)
    first = make_import(db, me)
    second = make_import(db, me)
    calls: list[str] = []
    real = tombstone_purge.counts_of

    def fails_on_the_second(conn: sqlite3.Connection, import_id: str) -> dict[str, int]:
        calls.append(import_id)
        if len(calls) == 2:
            raise RuntimeError("the disk is full")
        return real(conn, import_id)

    monkeypatch.setattr(tombstone_purge, "counts_of", fails_on_the_second)

    with pytest.raises(RuntimeError):
        purge(db).run_once()

    assert len(entry_ids(db)) == 1, "the entry that was deleted first is back"
    assert import_state(db, first)[:2] == (3, None) and import_state(db, second)[:2] == (3, None)


def test_the_import_batch_is_applied_to_the_imports(db: Database) -> None:
    me = make_person(db)
    ids = [make_import(db, me, states=("matched",)) for _ in range(3)]

    assert purge(db, import_batch=2).run_once().imports == 2
    assert purge(db, import_batch=2).run_once().imports == 1
    assert purge(db, import_batch=2).run_once().imports == 0
    assert all(import_state(db, i)[0] == 0 for i in ids)


# ------------------------------------------------------------------------------------------------ the counts of an old import over the API


def test_an_old_import_still_answers_with_its_counts_over_the_api_and_its_songs_are_an_empty_list(client: TestClient) -> None:
    client.get(f"{V1}/imports", params=creds("marwa"))  # the person is made by being seen
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    with db.read() as conn:
        me = conn.execute("SELECT id FROM person WHERE navidrome_user = 'marwa'").fetchone()["id"]
    import_id = make_import(db, me)
    before = client.get(f"{V1}/imports/{import_id}", params=creds("marwa")).json()["import"]
    assert client.get(f"{V1}/imports/{import_id}/entries", params=creds("marwa")).json()["entries"] != []

    purge(db).run_once()

    assert client.get(f"{V1}/imports/{import_id}", params=creds("marwa")).json()["import"] == before
    assert client.get(f"{V1}/imports", params=creds("marwa")).json()["imports"] == [before]
    assert client.get(f"{V1}/imports/{import_id}/entries", params=creds("marwa")).json()["entries"] == []


# ------------------------------------------------------------------------------------------------ the janitor, after the purge


def test_the_refs_of_a_deleted_playlist_and_of_an_old_import_are_retired_and_a_ref_somebody_keeps_is_not(db: Database) -> None:
    """The point of the whole slice (VM 108: the 29 refs of a deleted test playlist stayed for ever)."""
    me, you = make_person(db), make_person(db, "you")
    gone_with_the_list, liked, in_a_live_list, played, also_in_an_import = (make_ref(db) for _ in range(5))
    playlist, _ = make_list(db, me, [gone_with_the_list, liked, played, also_in_an_import])
    delete_playlist(db, me, playlist, days_ago=100)
    _, _ = make_list(db, you, [in_a_live_list])
    with db.tx() as conn:
        library.set_item(conn, me, "like", liked)
        library.record_play(conn, me, play_id="p1", ref=played, at=1, ms_played=40_000, device=None, context=None)
    old_import = make_import(db, me, states=("matched",))
    with db.read() as conn:
        import_ref = conn.execute("SELECT ref FROM import_entry WHERE import = ?", (old_import,)).fetchone()["ref"]
    with db.tx() as conn:
        conn.execute("INSERT INTO import_entry (import, position, ref) VALUES (?, 9, ?)", (old_import, also_in_an_import))

    before_the_purge = janitor(db).run_once()
    purge(db).run_once()
    retired = janitor(db).run_once()

    assert before_the_purge == 0, "while the tombstones and the import's rows name them, nothing is retired (today's behaviour)"
    assert retired == 3
    left = ref_ids(db)
    assert gone_with_the_list not in left and import_ref not in left and also_in_an_import not in left
    assert {liked, played, in_a_live_list} <= left, "a like, a play and another person's live entry keep their refs"
    with db.read() as conn:
        told = {row["ref_id"] for row in conn.execute("SELECT ref_id FROM ref_gone")}
    assert {gone_with_the_list, import_ref, also_in_an_import} <= told, "every retired ref is told to the phones"


def test_a_ref_another_persons_import_still_names_is_kept(db: Database) -> None:
    me, you = make_person(db), make_person(db, "you")
    shared = make_ref(db)
    old = make_import(db, me, states=("matched",))
    recent = make_import(db, you, states=("matched",), updated_days_ago=5)
    with db.tx() as conn:
        conn.execute("INSERT INTO import_entry (import, position, ref) VALUES (?, 7, ?)", (old, shared))
        conn.execute("INSERT INTO import_entry (import, position, ref) VALUES (?, 7, ?)", (recent, shared))

    purge(db).run_once()
    janitor(db).run_once()

    assert shared in ref_ids(db), "the recent import of the other person still names it"


# ------------------------------------------------------------------------------------------------ what the feed says


def test_a_phone_that_was_away_over_the_whole_purge_and_the_retirement_still_learns_everything(db: Database) -> None:
    """The scenario the design had to survive. The phone reads the feed, goes away; the person deletes a playlist and removes a song of another; 91 days
    on the purge runs and the janitor retires what nothing points at; the phone returns with its OLD cursors."""
    me = make_person(db)
    a, b, c, d = (make_ref(db) for _ in range(4))
    deleted_list, (entry_a, entry_b) = make_list(db, me, [a, b], "Old mix")
    live_list, (entry_c, entry_d) = make_list(db, me, [c, d], "Keepers")
    with db.tx() as conn:
        library.set_item(conn, me, "like", b)  # b stays: liked
    with db.read() as conn:
        first = library.changes(conn, me, 0)
        phone_changes = int(first["cursor"])
        phone_gone = int(library.files_since(conn, 0, gone_since=0)["goneCursor"])
    assert {e["id"] for e in first["entries"]} == {entry_a, entry_b, entry_c, entry_d}

    delete_playlist(db, me, deleted_list, days_ago=91)
    remove_entry(db, me, live_list, entry_c, days_ago=91)
    purge(db).run_once()
    assert janitor(db).run_once() == 2

    assert ref_ids(db) == {b, d}
    with db.read() as conn:
        feed = library.changes(conn, me, phone_changes)
        files = library.files_since(conn, 0, gone_since=phone_gone)
    assert {(p["id"], p["deleted"]) for p in feed["playlists"]} == {(deleted_list, True), (live_list, False)}
    tombstone = next(p for p in feed["playlists"] if p["id"] == deleted_list)
    assert tombstone["name"] == "Old mix", "the playlist row is still there: the phone gets the whole tombstone it always got"
    assert feed["entries"] == [{"id": entry_c, "playlist": live_list, "deleted": True}], (
        "the purged removal reaches the phone naming its playlist, because a phone skips an entry that names none"
    )
    assert {g["id"] for g in files["gone"]} == {a, c}, "the songs it held are told gone too"


def test_a_phone_that_asks_from_the_start_is_told_a_purged_entry_is_deleted_with_its_playlist(db: Database) -> None:
    me = make_person(db)
    playlist, (entry,) = make_list(db, me, [make_ref(db)])
    delete_playlist(db, me, playlist, days_ago=100)
    purge(db).run_once()

    with db.read() as conn:
        feed = library.changes(conn, me, 0)

    assert feed["entries"] == [{"id": entry, "playlist": playlist, "deleted": True}]
    assert feed["refs"] == [], "a deleted entry needs no song"
    with db.read() as conn:
        assert library.changes(conn, me, 0) == feed, "asking twice gives the same answer"


def test_an_id_the_log_names_that_exists_nowhere_is_told_deleted_for_both_kinds(db: Database) -> None:
    me = make_person(db)
    ghost_list, ghost_entry = new_id("pl"), new_id("pe")
    with db.tx() as conn:
        conn.execute("INSERT INTO change_log (person, kind, target, at) VALUES (?, 'playlist', ?, 1)", (me, ghost_list))
        conn.execute(
            "INSERT INTO change_log (person, kind, target, parent, at) VALUES (?, 'entry', ?, ?, 1)",
            (me, ghost_entry, ghost_list),
        )

    with db.read() as conn:
        feed = library.changes(conn, me, 0)

    assert feed["playlists"] == [{"id": ghost_list, "deleted": True}]
    assert feed["entries"] == [{"id": ghost_entry, "playlist": ghost_list, "deleted": True}]


def test_an_entry_the_log_names_without_a_playlist_is_told_deleted_without_one(db: Database) -> None:
    """A log row from before migration 0016 whose entry is already gone: nothing can name its playlist. The phone skips it, as it always did."""
    me = make_person(db)
    ghost = new_id("pe")
    with db.tx() as conn:
        conn.execute("INSERT INTO change_log (person, kind, target, at) VALUES (?, 'entry', ?, 1)", (me, ghost))

    with db.read() as conn:
        assert library.changes(conn, me, 0)["entries"] == [{"id": ghost, "deleted": True}]


class TestACollaborativePlaylistIsNeverToldDeleted:
    """The trap of the design. Today the feed asks for a row by id AND owner, so a naive 'no row, so deleted' answers a MEMBER of somebody else's live
    playlist that it was deleted. The rule is: told deleted only when NO row with that id exists at all, whoever owns it."""

    def shared_world(self, db: Database) -> tuple[str, str, str, str]:
        owner, member = make_person(db, "owner"), make_person(db, "member")
        playlist, (entry,) = make_list(db, owner, [make_ref(db)], "Shared")
        with db.tx() as conn:
            conn.execute("UPDATE playlist SET collaborative = 1 WHERE id = ?", (playlist,))
            # Only owners write the log today; a member's rows are what a collaborative playlist will write, and what the feed must survive.
            conn.execute("INSERT INTO change_log (person, kind, target, at) VALUES (?, 'playlist', ?, 1)", (member, playlist))
            conn.execute(
                "INSERT INTO change_log (person, kind, target, parent, at) VALUES (?, 'entry', ?, ?, 1)",
                (member, entry, playlist),
            )
        return owner, member, playlist, entry

    def test_a_member_is_not_told_a_live_shared_playlist_or_its_entry_was_deleted(self, db: Database) -> None:
        _, member, _, _ = self.shared_world(db)

        with db.read() as conn:
            feed = library.changes(conn, member, 0)

        assert feed["playlists"] == [] and feed["entries"] == []

    def test_nor_when_the_owner_has_deleted_it_the_row_exists_and_is_the_owners_to_tell(self, db: Database) -> None:
        owner, member, playlist, _ = self.shared_world(db)
        delete_playlist(db, owner, playlist, days_ago=1)

        with db.read() as conn:
            feed = library.changes(conn, member, 0)

        assert feed["playlists"] == [] and feed["entries"] == []

    def test_but_a_member_is_told_when_the_row_is_gone_altogether(self, db: Database) -> None:
        """The control: the same log rows, with the rows they name gone. Told deleted, because nobody owns anything by that id any more."""
        _, member, playlist, entry = self.shared_world(db)
        with db.tx() as conn:
            conn.execute("DELETE FROM playlist_entry WHERE id = ?", (entry,))
        with db.read() as conn:
            only_the_entry = library.changes(conn, member, 0)
        with db.tx() as conn:
            conn.execute("DELETE FROM playlist WHERE id = ?", (playlist,))
        with db.read() as conn:
            both = library.changes(conn, member, 0)

        assert only_the_entry["playlists"] == [] and only_the_entry["entries"] == [
            {"id": entry, "playlist": playlist, "deleted": True}
        ]
        assert both["playlists"] == [{"id": playlist, "deleted": True}]


# ------------------------------------------------------------------------------------------------ every entry change names its playlist


def test_every_change_of_an_entry_is_logged_with_its_playlist(db: Database) -> None:
    """Migration 0016 gives `change_log` a `parent`. A purged entry can only be told to a phone with the playlist it belonged to, so EVERY writer of an
    `entry` row must give it: adding, removing, moving, and the song's file changing (`touch_ref_holders`)."""
    me = make_person(db)
    first, second = make_ref(db), make_ref(db)
    playlist, (entry_1, entry_2) = make_list(db, me, [first, second])
    with db.tx() as conn:
        library.reorder(conn, me, playlist, [entry_2, entry_1])
        library.touch_ref_holders(conn, first)
        library.remove_entries(conn, me, playlist, [entry_1])
    other, (entry_3,) = make_list(db, me, [first], "Another")
    with db.tx() as conn:
        library.touch_ref_holders(conn, first)

    with db.read() as conn:
        rows = list(conn.execute("SELECT target, parent FROM change_log WHERE kind = 'entry'"))
    assert {r["target"] for r in rows} == {entry_1, entry_2, entry_3}
    assert all(r["parent"] is not None for r in rows), [tuple(r) for r in rows]
    assert {r["target"]: r["parent"] for r in rows} == {entry_1: playlist, entry_2: playlist, entry_3: other}


def test_a_writer_that_forgets_the_playlist_of_an_entry_is_refused(db: Database) -> None:
    me = make_person(db)
    with pytest.raises(ValueError), db.tx() as conn:
        library._touch(conn, me, "entry", new_id("pe"))


# ------------------------------------------------------------------------------------------------ migration 0016


def test_migration_0016_gives_the_entries_already_in_the_log_their_playlist_and_leaves_imports_unpurged(tmp_path: Path) -> None:
    db = Database(tmp_path / "data" / "encore.db")
    steps = Database._migrations()
    assert [n for n, _, _ in steps][-1] >= 16
    db.migrate(migrations=[s for s in steps if s[0] <= 15])
    pl, pe, hard_deleted, im = new_id("pl"), new_id("pe"), new_id("pe"), new_id("im")
    with db.tx() as conn:
        conn.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES ('pn_1', 'a', 'a', 1)")
        conn.execute("INSERT INTO song_ref (id, title, artists, norm_key, created_at) VALUES ('sr_1', 't', '[]', 'k', 1)")
        conn.execute("INSERT INTO playlist (id, owner, name, created_at, updated_at) VALUES (?, 'pn_1', 'L', 1, 1)", (pl,))
        conn.execute(
            "INSERT INTO playlist_entry (id, playlist, position, ref, added_by, at) VALUES (?, ?, 1.0, 'sr_1', 'pn_1', 1)",
            (pe, pl),
        )
        conn.execute(
            "INSERT INTO import (id, person, source, name, playlist, state, created_at, updated_at) VALUES (?, 'pn_1', 'file', 'x', ?, 'done', 1, 1)",
            (im, pl),
        )
        for kind, target in (("entry", pe), ("entry", hard_deleted), ("playlist", pl), ("like", "sr_1")):
            conn.execute("INSERT INTO change_log (person, kind, target, at) VALUES ('pn_1', ?, ?, 1)", (kind, target))

    assert db.migrate() == [n for n, _, _ in steps if n > 15]

    with db.read() as conn:
        parents = {r["target"]: r["parent"] for r in conn.execute("SELECT target, parent FROM change_log")}
        imported = conn.execute("SELECT entries_purged_at, final_total FROM import WHERE id = ?", (im,)).fetchone()
    assert parents[pe] == pl, "an entry that still exists is given its playlist"
    assert parents[hard_deleted] is None, "an entry that was removed for good (a person deleted) has nobody to name"
    assert parents[pl] is None and parents["sr_1"] is None, "only entries have a parent"
    assert imported["entries_purged_at"] is None and imported["final_total"] is None, "NULL means: count the entries"


# ------------------------------------------------------------------------------------------------ the app runs it


def test_the_app_runs_the_purge_before_the_janitor_in_the_same_errand(tmp_path: Path) -> None:
    """Without this a purge that nothing calls would pass every test above. The order is the point: in ONE pass of the hourly link the entries go and the
    ref they named is retired, so the first hour after the 90 days is enough."""

    def music_server(request: httpx.Request) -> httpx.Response:
        answers: dict[str, dict[str, Any]] = {
            "getScanStatus.view": {"scanStatus": {"scanning": False}},
            "getArtists.view": {"artists": {"index": []}},
            "search3.view": {"searchResult3": {}},
        }
        return httpx.Response(
            200, json={"subsonic-response": {"status": "ok", **answers.get(request.url.path.rsplit("/", 1)[-1], {})}}
        )

    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        navidrome_url="http://music.invalid",
        navidrome_admin_user="admin",
        navidrome_admin_password="pw",
        youtube=False,
        workers=False,
    )
    client = NavidromeClient(
        "http://music.invalid", "admin", "pw", client=httpx.Client(transport=httpx.MockTransport(music_server))
    )
    app = create_app(settings, navidrome=client, navidrome_admin=NavidromeAdmin("http://music.invalid", "", ""))
    services = app.state.services
    now = now_ms()
    me = make_person(services.db)
    ref = make_ref(services.db, created_at=now - 200 * DAY)
    playlist, (entry,) = make_list(services.db, me, [ref])
    with services.db.tx() as conn:
        library.delete_playlist(conn, me, playlist)
        conn.execute("UPDATE playlist SET deleted_at = ? WHERE id = ?", (now - 100 * DAY, playlist))
    assert services.linker is not None

    services.linker.run_once()

    assert entry_ids(services.db) == set()
    assert ref_ids(services.db) == set(), "the same errand retired the song the deleted playlist named"
    with services.db.read() as conn:
        assert [r["ref_id"] for r in conn.execute("SELECT ref_id FROM ref_gone")] == [ref]


# ------------------------------------------------------------------------------------------------ what the janitor knows is unchanged


def test_the_janitors_list_of_pointers_still_counts_a_tombstoned_entry_and_an_import_entry() -> None:
    """The janitor's rule did not change: a removed entry and an import's row still keep a ref. What changed is that they are PURGED after a time, so a
    ref is no longer kept for ever by them. This is the reason `POINTERS` must not lose either clause (the purge is not the only thing that may write
    one)."""
    assert "playlist_entry" in ref_janitor.POINTERS and "import_entry" in ref_janitor.POINTERS
    assert "deleted_at" not in ref_janitor.POINTERS["playlist_entry"]


# ------------------------------------------------------------------------------------------------ the saved real response (ADR-R41 T5)

FIXTURE = (
    Path(__file__).resolve().parents[3] / "app" / "test" / "fixtures" / "server" / "library-changes-with-purged-tombstones.json"
)


def test_the_changes_response_with_purged_tombstones_is_the_saved_fixture_the_phones_parser_reads(client: TestClient) -> None:
    """One contract: a REAL response of the real endpoint on synthetic data (fixed ids and times). When it changes this test fails until the file is written
    again (`ENCORE_WRITE_FIXTURES=1 pytest tests/test_tombstone_purge.py -k saved_fixture`) and the app's parser is changed to read it: it holds a deleted
    playlist whose row is still there, a removal of a live playlist that was purged (an entry that names its playlist), and the shape of an id that exists
    nowhere (`{id, deleted: true}`), which the server does not produce today and a phone must read all the same."""
    client.get(f"{V1}/imports", params=creds("marwa"))  # the person is made by being seen
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    with db.read() as conn:
        me = conn.execute("SELECT id FROM person WHERE navidrome_user = 'marwa'").fetchone()["id"]
    live, deleted, missing = (f"pl_{c * 26}" for c in "abc")
    removed, in_deleted, gone_for_good = (f"pe_{c * 26}" for c in "xyz")
    with db.tx() as conn:
        for n, (playlist, name) in enumerate(((live, "Keepers"), (deleted, "Old mix")), start=1):
            conn.execute(
                "INSERT INTO playlist (id, owner, name, created_at, updated_at) VALUES (?,?,?,?,?)",
                (playlist, me, name, 1000 * n, 2000 * n),
            )
        conn.execute("UPDATE playlist SET deleted_at = 5000, updated_at = 5000 WHERE id = ?", (deleted,))
        rows = [
            ("playlist", live, None),
            ("playlist", deleted, None),
            ("playlist", missing, None),
            ("entry", removed, live),
            ("entry", in_deleted, deleted),
            ("entry", gone_for_good, None),
        ]
        for n, (kind, target, parent) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO change_log (person, kind, target, parent, at) VALUES (?,?,?,?,?)", (me, kind, target, parent, n)
            )
    response = client.get(f"{V1}/library/changes", params={**creds("marwa"), "since": "0"})
    assert response.status_code == 200
    body = response.json()
    body.pop("serverTime")
    text = json.dumps(body, indent=2, ensure_ascii=False) + "\n"

    if os.environ.get("ENCORE_WRITE_FIXTURES") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")

    assert FIXTURE.is_file(), "run with ENCORE_WRITE_FIXTURES=1 once to write it"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == body
    assert {p["id"] for p in body["playlists"]} == {live, deleted, missing}
    assert {"id": missing, "deleted": True} in body["playlists"]
    assert {"id": removed, "playlist": live, "deleted": True} in body["entries"]
    assert {"id": gone_for_good, "deleted": True} in body["entries"]
