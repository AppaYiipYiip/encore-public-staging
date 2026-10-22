from __future__ import annotations

import pytest

from encore_server import library, refs
from encore_server.db import Database
from encore_server.errors import ApiError
from encore_server.ids import new_id


def make_ref(db: Database, n: int) -> str:
    with db.tx() as conn:
        return str(refs.resolve(conn, {"title": f"Song {n}", "artists": ["Artist"], "durationMs": 180000 + n * 10000})["id"])


def person(db: Database, name: str = "marwa") -> str:
    with db.tx() as conn:
        return str(library.ensure_person(conn, name)["id"])


def entry_refs(db: Database, who: str, playlist: str) -> list[str]:
    with db.read() as conn:
        return [e["ref"] for e in library.get_playlist(conn, who, playlist)["entries"]]


class TestPeople:
    def test_the_first_person_is_the_owner_the_next_are_members(self, db: Database) -> None:
        with db.tx() as conn:
            first = library.ensure_person(conn, "marwa")
            second = library.ensure_person(conn, "nina")
            again = library.ensure_person(conn, "marwa")
        assert (first["role"], second["role"]) == ("owner", "member")
        assert again["id"] == first["id"]

    def test_a_music_server_administrator_is_an_owner_too(self, db: Database) -> None:
        with db.tx() as conn:
            library.ensure_person(conn, "first")
            assert library.ensure_person(conn, "admin", admin=True)["role"] == "owner"


class TestLikes:
    def test_liking_twice_is_one_like_and_one_change(self, db: Database) -> None:
        me, ref = person(db), make_ref(db, 1)
        with db.tx() as conn:
            assert library.set_item(conn, me, "like", ref) is True
            assert library.set_item(conn, me, "like", ref) is False
            assert conn.execute("SELECT COUNT(*) FROM change_log WHERE kind = 'like'").fetchone()[0] == 1

    def test_unliking_what_was_never_liked_is_not_a_change(self, db: Database) -> None:
        me, ref = person(db), make_ref(db, 1)
        with db.tx() as conn:
            assert library.clear_item(conn, me, "like", ref) is False
            assert library.latest_cursor(conn, me) == 0

    def test_a_like_of_an_unknown_song_is_not_found(self, db: Database) -> None:
        me = person(db)
        with pytest.raises(ApiError) as caught, db.tx() as conn:
            library.set_item(conn, me, "like", "sr_00000000000000000000000000")
        assert caught.value.code == "not_found"

    def test_likes_are_private_to_a_person(self, db: Database) -> None:
        me, nina, ref = person(db), person(db, "nina"), make_ref(db, 1)
        with db.tx() as conn:
            library.set_item(conn, me, "like", ref)
        with db.read() as conn:
            assert library.changes(conn, nina, 0)["likes"] == []
            assert [like["ref"] for like in library.changes(conn, me, 0)["likes"]] == [ref]


class TestPlaylists:
    def test_a_create_that_is_retried_is_one_playlist(self, db: Database) -> None:
        me, pl = person(db), new_id("pl")
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "Road trip")
            library.create_playlist(conn, me, pl, "Road trip")
        with db.read() as conn:
            assert len(library.list_playlists(conn, me)) == 1

    def test_the_id_must_be_a_client_made_playlist_id(self, db: Database) -> None:
        me = person(db)
        with pytest.raises(ApiError) as caught, db.tx() as conn:
            library.create_playlist(conn, me, "my-list", "x")
        assert caught.value.code == "validation"

    def test_somebody_elses_playlist_id_is_a_conflict(self, db: Database) -> None:
        me, nina, pl = person(db), person(db, "nina"), new_id("pl")
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "Mine")
        with pytest.raises(ApiError) as caught, db.tx() as conn:
            library.create_playlist(conn, nina, pl, "Stolen")
        assert caught.value.code == "conflict"

    def test_a_playlist_needs_a_name(self, db: Database) -> None:
        me = person(db)
        with pytest.raises(ApiError), db.tx() as conn:
            library.create_playlist(conn, me, new_id("pl"), "   ")

    def test_songs_are_added_at_the_end_in_order(self, db: Database) -> None:
        me, pl = person(db), new_id("pl")
        r = [make_ref(db, n) for n in range(4)]
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            library.add_entries(conn, me, pl, [{"ref": r[0]}, {"ref": r[1]}])
            library.add_entries(conn, me, pl, [{"ref": r[2]}])
        assert entry_refs(db, me, pl) == r[:3]

    def test_the_same_entry_id_sent_again_adds_nothing(self, db: Database) -> None:
        me, pl, ref, entry = person(db), new_id("pl"), make_ref(db, 1), new_id("pe")
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            assert library.add_entries(conn, me, pl, [{"ref": ref, "id": entry}]) == [entry]
            assert library.add_entries(conn, me, pl, [{"ref": ref, "id": entry}]) == []
        assert entry_refs(db, me, pl) == [ref]

    def test_the_same_song_may_be_in_a_playlist_twice(self, db: Database) -> None:
        me, pl, ref = person(db), new_id("pl"), make_ref(db, 1)
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            library.add_entries(conn, me, pl, [{"ref": ref}])
            library.add_entries(conn, me, pl, [{"ref": ref}])
        assert entry_refs(db, me, pl) == [ref, ref]

    def test_an_unknown_song_refuses_the_whole_call(self, db: Database) -> None:
        me, pl, ref = person(db), new_id("pl"), make_ref(db, 1)
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
        with pytest.raises(ApiError) as caught, db.tx() as conn:
            library.add_entries(conn, me, pl, [{"ref": ref}, {"ref": "sr_00000000000000000000000000"}])
        assert caught.value.code == "not_found"
        assert entry_refs(db, me, pl) == [], "nothing was added"

    def test_songs_are_added_after_a_given_entry(self, db: Database) -> None:
        me, pl = person(db), new_id("pl")
        r = [make_ref(db, n) for n in range(4)]
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            first, _, last = library.add_entries(conn, me, pl, [{"ref": r[0]}, {"ref": r[1]}, {"ref": r[2]}])
            library.add_entries(conn, me, pl, [{"ref": r[3]}], after=first)
        assert entry_refs(db, me, pl) == [r[0], r[3], r[1], r[2]]

    def test_an_anchor_that_was_removed_elsewhere_falls_back_to_the_end(self, db: Database) -> None:
        me, pl = person(db), new_id("pl")
        r = [make_ref(db, n) for n in range(3)]
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            first, second = library.add_entries(conn, me, pl, [{"ref": r[0]}, {"ref": r[1]}])
            library.remove_entries(conn, me, pl, [second])
            library.add_entries(conn, me, pl, [{"ref": r[2]}], after=second)
        assert entry_refs(db, me, pl) == [r[0], r[2]]

    def test_many_inserts_in_the_same_gap_renumber_instead_of_losing_order(self, db: Database) -> None:
        me, pl = person(db), new_id("pl")
        r = [make_ref(db, n) for n in range(2)]
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            first, _ = library.add_entries(conn, me, pl, [{"ref": r[0]}, {"ref": r[1]}])
            expected = [r[0]]
            extra = []
            for n in range(60):
                ref = make_ref_in(conn, 100 + n)
                library.add_entries(conn, me, pl, [{"ref": ref}], after=first)
                extra.insert(0, ref)
        assert entry_refs(db, me, pl) == [r[0], *extra, r[1]]
        assert expected == [r[0]]

    def test_removed_entries_stay_removed_and_removing_twice_is_fine(self, db: Database) -> None:
        me, pl = person(db), new_id("pl")
        r = [make_ref(db, n) for n in range(3)]
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            a, b, c = library.add_entries(conn, me, pl, [{"ref": x} for x in r])
            assert library.remove_entries(conn, me, pl, [b]) == [b]
            assert library.remove_entries(conn, me, pl, [b]) == []
        assert entry_refs(db, me, pl) == [r[0], r[2]]

    def test_a_reorder_puts_the_listed_entries_in_the_places_they_occupy(self, db: Database) -> None:
        me, pl = person(db), new_id("pl")
        r = [make_ref(db, n) for n in range(4)]
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            a, b, c, d = library.add_entries(conn, me, pl, [{"ref": x} for x in r])
            library.reorder(conn, me, pl, [d, c])  # b and a are not listed: they stay put
        assert entry_refs(db, me, pl) == [r[0], r[1], r[3], r[2]]

    def test_a_reorder_that_lists_a_removed_entry_leaves_it_out(self, db: Database) -> None:
        me, pl = person(db), new_id("pl")
        r = [make_ref(db, n) for n in range(3)]
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            a, b, c = library.add_entries(conn, me, pl, [{"ref": x} for x in r])
            library.remove_entries(conn, me, pl, [b])
            library.reorder(conn, me, pl, [c, b, a])
        assert entry_refs(db, me, pl) == [r[2], r[0]]

    def test_deleting_a_playlist_is_gone_for_the_list_and_not_found_for_edits(self, db: Database) -> None:
        me, pl = person(db), new_id("pl")
        ref = make_ref(db, 1)
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            assert library.delete_playlist(conn, me, pl) is True
            assert library.delete_playlist(conn, me, pl) is False
        with db.read() as conn:
            assert library.list_playlists(conn, me) == []
        with pytest.raises(ApiError) as caught, db.tx() as conn:
            library.add_entries(conn, me, pl, [{"ref": ref}])
        assert caught.value.code == "not_found"

    def test_nobody_edits_somebody_elses_playlist(self, db: Database) -> None:
        me, nina, pl = person(db), person(db, "nina"), new_id("pl")
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "Mine")
        for action in (
            lambda conn: library.patch_playlist(conn, nina, pl, {"name": "x"}),
            lambda conn: library.add_entries(conn, nina, pl, [{"ref": make_ref_in(conn, 1)}]),
            lambda conn: library.remove_entries(conn, nina, pl, []),
        ):
            with pytest.raises(ApiError) as caught, db.tx() as conn:
                action(conn)
            assert caught.value.code == "not_found"

    def test_two_devices_adds_both_survive(self, db: Database) -> None:
        """Offline edits merge: each device added a song while the other did too (journey J-15)."""
        me, pl = person(db), new_id("pl")
        a, b = make_ref(db, 1), make_ref(db, 2)
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
        with db.tx() as conn:
            library.add_entries(conn, me, pl, [{"ref": a, "id": new_id("pe")}])
        with db.tx() as conn:
            library.add_entries(conn, me, pl, [{"ref": b, "id": new_id("pe")}])
        assert set(entry_refs(db, me, pl)) == {a, b}

    def test_a_rename_is_last_writer_wins(self, db: Database) -> None:
        me, pl = person(db), new_id("pl")
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "Old")
            library.patch_playlist(conn, me, pl, {"name": "From phone"})
            library.patch_playlist(conn, me, pl, {"name": "From tablet"})
        with db.read() as conn:
            assert library.get_playlist(conn, me, pl)["name"] == "From tablet"


def make_ref_in(conn, n: int) -> str:  # type: ignore[no-untyped-def]
    return str(refs.resolve(conn, {"title": f"Song {n}", "artists": ["Artist"], "durationMs": 180000 + n * 10000})["id"])


class TestPlays:
    def test_a_report_that_is_sent_twice_is_one_play(self, db: Database) -> None:
        me, ref = person(db), make_ref(db, 1)
        with db.tx() as conn:
            assert (
                library.record_play(
                    conn, me, play_id="01HX", ref=ref, at=1_700_000_000_000, ms_played=180000, device=None, context="album:x"
                )
                is True
            )
            assert (
                library.record_play(
                    conn, me, play_id="01HX", ref=ref, at=1_700_000_000_000, ms_played=180000, device=None, context=None
                )
                is False
            )
            assert conn.execute("SELECT COUNT(*) FROM play_event").fetchone()[0] == 1

    @pytest.mark.parametrize(
        "bad", [{"play_id": "", "ms_played": 1}, {"play_id": "x", "ms_played": -5}, {"play_id": "x", "ms_played": "many"}]
    )
    def test_a_report_that_cannot_be_right_is_refused(self, db: Database, bad: dict[str, object]) -> None:
        me, ref = person(db), make_ref(db, 1)
        with pytest.raises(ApiError) as caught, db.tx() as conn:
            library.record_play(conn, me, ref=ref, at=1, device=None, context=None, **bad)  # type: ignore[arg-type]
        assert caught.value.code == "validation"


class TestChangeFeed:
    def test_a_cursor_returns_only_what_came_after_it(self, db: Database) -> None:
        me = person(db)
        r1, r2 = make_ref(db, 1), make_ref(db, 2)
        with db.tx() as conn:
            library.set_item(conn, me, "like", r1)
        with db.read() as conn:
            first = library.changes(conn, me, 0)
        with db.tx() as conn:
            library.set_item(conn, me, "like", r2)
        with db.read() as conn:
            second = library.changes(conn, me, int(first["cursor"]))
        assert [like["ref"] for like in first["likes"]] == [r1]
        assert [like["ref"] for like in second["likes"]] == [r2]

    def test_a_like_and_its_removal_arrive_as_the_state_it_is_in_now(self, db: Database) -> None:
        me, ref = person(db), make_ref(db, 1)
        with db.tx() as conn:
            library.set_item(conn, me, "like", ref)
            library.clear_item(conn, me, "like", ref)
        with db.read() as conn:
            feed = library.changes(conn, me, 0)
        assert feed["likes"] == [{"ref": ref, "at": None, "removed": True}]
        assert feed["refs"] == [], "a removed like needs no song"

    def test_asking_twice_gives_the_same_answer(self, db: Database) -> None:
        me, ref = person(db), make_ref(db, 1)
        with db.tx() as conn:
            library.set_item(conn, me, "like", ref)
        with db.read() as conn:
            assert library.changes(conn, me, 0) == library.changes(conn, me, 0)

    def test_the_feed_carries_the_songs_it_mentions(self, db: Database) -> None:
        me, pl, ref = person(db), new_id("pl"), make_ref(db, 1)
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            library.add_entries(conn, me, pl, [{"ref": ref}])
        with db.read() as conn:
            feed = library.changes(conn, me, 0)
        assert [r["id"] for r in feed["refs"]] == [ref]
        assert [p["id"] for p in feed["playlists"]] == [pl]
        assert [e["ref"] for e in feed["entries"]] == [ref]

    def test_a_deleted_playlist_and_a_removed_entry_are_tombstones(self, db: Database) -> None:
        me, pl, ref = person(db), new_id("pl"), make_ref(db, 1)
        with db.tx() as conn:
            library.create_playlist(conn, me, pl, "L")
            (entry,) = library.add_entries(conn, me, pl, [{"ref": ref}])
        with db.read() as conn:
            cursor = int(library.changes(conn, me, 0)["cursor"])
        with db.tx() as conn:
            library.remove_entries(conn, me, pl, [entry])
            library.delete_playlist(conn, me, pl)
        with db.read() as conn:
            feed = library.changes(conn, me, cursor)
        assert feed["playlists"][0]["deleted"] is True
        assert feed["entries"][0]["deleted"] is True

    def test_a_long_feed_is_paged_with_a_flag_to_ask_again(self, db: Database) -> None:
        me = person(db)
        with db.tx() as conn:
            for n in range(library.CHANGES_PAGE + 20):
                library.set_item(conn, me, "saved_album", f"album-{n}")
        with db.read() as conn:
            first = library.changes(conn, me, 0)
            second = library.changes(conn, me, int(first["cursor"]))
        assert first["more"] is True and len(first["savedAlbums"]) == library.CHANGES_PAGE
        assert second["more"] is False and len(second["savedAlbums"]) == 20
