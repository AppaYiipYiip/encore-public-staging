"""N-53: the real place of a library song's file (`real_paths.py`), and what the keeper's and the scanner's attaches do to it.

The music server's Subsonic `path` is built from the tags (measured on the real music server: `tests/integration/test_real_paths.py`); its native API names the real place. These tests give the
native client and need no music server.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from encore_server import refs
from encore_server.db import Database
from encore_server.navidrome_admin import AdminUnavailable, NavidromeAdmin
from encore_server.place import trusted_file
from encore_server.real_paths import Pass, RealPaths


class FakePlaces:
    """The native API, given: what it says of each music-server id, and what it was asked."""

    def __init__(self, answers: dict[str, str] | None = None) -> None:
        self.answers = answers or {}
        self.asked: list[list[str]] = []
        self.configured = True
        self.error: Exception | None = None
        self.meanwhile: Callable[[], None] | None = None

    def song_places(self, ids: Sequence[str]) -> dict[str, str]:
        self.asked.append(list(ids))
        if self.meanwhile is not None:
            self.meanwhile()
        if self.error is not None:
            raise self.error
        return {i: self.answers[i] for i in ids if i in self.answers}


def one_ref(db: Database, title: str) -> str:
    with db.tx() as conn:
        return str(refs.resolve(conn, {"title": title, "artists": ["Radiohead"]})["id"])


class Bench:
    def __init__(self, tmp: Path, db: Database) -> None:
        self.music = tmp / "music"
        self.music.mkdir()
        self.db = db
        self.places = FakePlaces()
        self.n = 0
        self.now = 0.0

    def library_file(
        self, real: str, content: bytes = b"audio", *, built: str | None = None, size: int | None = None
    ) -> tuple[str, str]:
        """A library file as the scanner leaves it: the music server's id, a tag-built path, no check. Returns (ref, music-server id)."""
        self.n += 1
        ref = one_ref(self.db, f"Song {self.n}")
        file = self.music / real
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
        song_id = f"nd{self.n}"
        with self.db.tx() as conn:
            refs.attach_file(
                conn,
                ref,
                navidrome_song_id=song_id,
                path=built or f"Radiohead/In Rainbows/Song {self.n}.opus",
                codec="opus",
                bitrate_kbps=1,
                meta={"size": len(content) if size is None else size},
            )
        self.places.answers[song_id] = real
        return ref, song_id

    def errand(self, **more: Any) -> RealPaths:
        return RealPaths(self.db, self.music, self.places, clock=lambda: self.now, **more)

    def row(self, ref: str) -> Any:
        with self.db.read() as conn:
            return conn.execute("SELECT path, path_real, path_checked_at FROM song_file WHERE ref = ?", (ref,)).fetchone()


@pytest.fixture()
def bench(tmp_path: Path, db: Database) -> Bench:
    return Bench(tmp_path, db)


def test_a_library_file_gets_the_real_place_the_music_server_names(bench: Bench) -> None:
    ref, _ = bench.library_file("Misc/random-name-1234.opus", built="Radiohead/In Rainbows/Weird Fishes.opus")
    assert bench.row(ref)["path_real"] == 0, "the scanner's path is not checked"

    first = bench.errand().run_once()

    assert first == Pass(1, 0, 0)
    row = bench.row(ref)
    assert (row["path"], row["path_real"]) == ("Misc/random-name-1234.opus", 1)
    bench.places.asked.clear()
    assert bench.errand().run_once() == Pass(0, 0, 0) and bench.places.asked == [], "a checked row is never asked about again"


def test_a_place_the_file_is_not_at_is_not_trusted_and_the_row_goes_to_the_back(bench: Bench) -> None:
    ref, song_id = bench.library_file("Misc/here.opus")
    bench.places.answers[song_id] = "Elsewhere/not-here.opus"  # the music server names a place that is not a file on this disk

    result = bench.errand().run_once()

    assert result == Pass(0, 1, 0)
    row = bench.row(ref)
    assert row["path"] == "Radiohead/In Rainbows/Song 1.opus" and row["path_real"] == 0 and row["path_checked_at"] is not None


def test_a_file_of_another_size_than_the_music_server_reports_is_not_trusted(bench: Bench) -> None:
    """Another library's file by the same relative path, or a file retagged on the disk and not scanned yet: it is not the file the row means."""
    ref, _ = bench.library_file("Misc/a.opus", b"the real bytes", size=999)

    assert bench.errand().run_once() == Pass(0, 1, 0) and bench.row(ref)["path_real"] == 0


@pytest.mark.parametrize("place", ["../outside.opus", "/etc/passwd", "", "Misc/.."])
def test_a_place_that_leaves_the_music_folder_is_never_trusted(bench: Bench, tmp_path: Path, place: str) -> None:
    (tmp_path / "outside.opus").write_bytes(b"audio")
    ref, song_id = bench.library_file("Misc/a.opus")
    bench.places.answers[song_id] = place

    assert bench.errand().run_once().resolved == 0 and bench.row(ref)["path_real"] == 0


def test_a_song_the_music_server_does_not_know_is_stamped_not_resolved(bench: Bench) -> None:
    ref, song_id = bench.library_file("Misc/a.opus")
    del bench.places.answers[song_id]

    assert bench.errand().run_once() == Pass(0, 1, 0) and bench.row(ref)["path_checked_at"] is not None


def test_a_music_server_that_does_not_answer_stops_the_pass_and_stamps_nothing(bench: Bench) -> None:
    first, _ = bench.library_file("Misc/a.opus")
    second, _ = bench.library_file("Misc/b.opus")
    bench.places.error = AdminUnavailable("The music server is not answering.")

    assert bench.errand().run_once() == Pass(0, 0, 2)

    assert bench.row(first)["path_checked_at"] is None and bench.row(second)["path_checked_at"] is None
    bench.places.error = None
    assert bench.errand().run_once().resolved == 2, "the next pass takes them"


def test_an_unconfigured_errand_does_nothing(bench: Bench) -> None:
    bench.library_file("Misc/a.opus")
    bench.places.configured = False

    assert bench.errand().run_once() == Pass(0, 0, 0) and bench.places.asked == []


def test_rows_it_cannot_resolve_never_keep_the_others_from_their_turn(bench: Bench) -> None:
    good, _ = bench.library_file("Misc/good.opus")
    for n in range(4):
        _, song_id = bench.library_file(f"Misc/lost{n}.opus")
        del bench.places.answers[song_id]  # the music server no longer knows these

    first = bench.errand(batch=3, chunk=3).run_once()
    assert first == Pass(0, 3, 0) and bench.row(good)["path_real"] == 0, "the three newest were tried and sent to the back"
    second = bench.errand(batch=3, chunk=3).run_once()

    assert second.resolved == 1 and bench.row(good)["path_real"] == 1


def test_the_music_server_is_asked_a_chunk_at_a_time(bench: Bench) -> None:
    for n in range(5):
        bench.library_file(f"Misc/{n}.opus")

    assert bench.errand(chunk=2).run_once().resolved == 5

    assert [len(asked) for asked in bench.places.asked] == [2, 2, 1]


def test_the_budget_stops_the_pass_and_the_rest_waits(bench: Bench) -> None:
    for n in range(4):
        bench.library_file(f"Misc/{n}.opus")

    def slow(ids: Sequence[str]) -> dict[str, str]:
        bench.now += 20.0
        return {i: bench.places.answers[i] for i in ids}

    bench.places.song_places = slow  # type: ignore[method-assign]
    result = bench.errand(chunk=1, budget_s=30.0).run_once()

    assert result.resolved == 2 and result.left == 2, "two chunks of 20 s are over the 30 s budget"


def test_a_key_the_keeper_linked_while_the_errand_was_asking_is_not_overwritten(bench: Bench) -> None:
    ref, song_id = bench.library_file("Misc/a.opus")

    def keeper_links_meanwhile() -> None:
        with bench.db.tx() as conn:
            refs.attach_file(
                conn,
                ref,
                navidrome_song_id=song_id,
                path="Encore/Radiohead/In Rainbows/Song 1.opus",
                codec="opus",
                bitrate_kbps=1,
                path_real=True,
            )

    bench.places.meanwhile = keeper_links_meanwhile

    result = bench.errand().run_once()

    assert result.resolved == 0, "the row is no longer unchecked"
    assert bench.row(ref)["path"] == "Encore/Radiohead/In Rainbows/Song 1.opus"


# ---------------------------------------------------------------------------------------------------------------------- attach_file


def test_the_keepers_real_path_wins_over_the_path_the_scanner_stored_first(db: Database) -> None:
    ref = one_ref(db, "Weird Fishes")
    with db.tx() as conn:  # the scanner got there first, with the music server's tag-built path
        refs.attach_file(
            conn, ref, navidrome_song_id="nd1", path="Radiohead/In Rainbows/Weird Fishes.opus", codec="opus", bitrate_kbps=1
        )
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="Encore/Radiohead/In Rainbows/Weird Fishes.opus",
            codec="opus",
            bitrate_kbps=1,
            path_real=True,
        )
    with db.read() as conn:
        rows = conn.execute("SELECT path, path_real FROM song_file WHERE ref = ?", (ref,)).fetchall()

    assert [(r["path"], r["path_real"]) for r in rows] == [("Encore/Radiohead/In Rainbows/Weird Fishes.opus", 1)], (
        "one row, the keeper's place"
    )


def test_the_scanner_never_overwrites_a_path_a_row_has(db: Database) -> None:
    ref = one_ref(db, "Weird Fishes")
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="Encore/Radiohead/Weird Fishes.opus",
            codec="opus",
            bitrate_kbps=1,
            path_real=True,
        )
        refs.attach_file(
            conn, ref, navidrome_song_id="nd1", path="Radiohead/In Rainbows/Weird Fishes.opus", codec="opus", bitrate_kbps=1
        )
    with db.read() as conn:
        row = conn.execute("SELECT path, path_real FROM song_file WHERE ref = ?", (ref,)).fetchone()

    assert (row["path"], row["path_real"]) == ("Encore/Radiohead/Weird Fishes.opus", 1)


def test_the_place_of_a_file_is_not_part_of_what_a_phone_is_given(db: Database) -> None:
    ref = one_ref(db, "Weird Fishes")
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="Encore/Radiohead/Weird Fishes.opus",
            codec="opus",
            bitrate_kbps=1,
            path_real=True,
        )
    with db.read() as conn:
        shown = refs.get_ref(conn, ref)["file"]

    assert "path" not in shown and "pathReal" not in shown and "path" not in shown.get("meta", {})


# ---------------------------------------------------------------------------------------------------------------------- the native client


def admin_with(handler: Callable[[httpx.Request], httpx.Response]) -> NavidromeAdmin:
    return NavidromeAdmin("http://music.test", "admin", "pw", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_song_places_asks_the_native_api_by_ids_and_reads_the_places() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            return httpx.Response(200, json={"token": "t"})
        seen.append(str(request.url))
        assert request.headers["X-ND-Authorization"] == "Bearer t"
        return httpx.Response(
            200,
            json=[
                {"id": "a", "path": "Misc/a.opus", "libraryPath": "/music", "libraryId": 1},
                {"id": "b", "path": "Artist/Album/b.opus", "libraryPath": "/music", "libraryId": 1},
                {"id": "c", "path": ""},
                {"path": "no id"},
                "garbage",
            ],
        )

    places = admin_with(handler).song_places(["a", "b", "c", "d"])

    assert places == {"a": "Misc/a.opus", "b": "Artist/Album/b.opus"}, (
        "an unknown id, an empty path and a malformed entry are absent"
    )
    assert seen == ["http://music.test/api/song?id=a&id=b&id=c&id=d"]


def test_song_places_asks_in_chunks_and_escapes_ids() -> None:
    asked: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            return httpx.Response(200, json={"token": "t"})
        asked.append(len(request.url.params.get_list("id")))
        return httpx.Response(200, json=[])

    admin_with(handler).song_places([f"id{n}" for n in range(250)] + ["a&b=c"])

    assert asked == [100, 100, 51]


def test_song_places_says_so_when_the_music_server_refuses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            return httpx.Response(200, json={"token": "t"})
        return httpx.Response(500)

    with pytest.raises(AdminUnavailable):
        admin_with(handler).song_places(["a"])


# ---------------------------------------------------------------------------------------------------------------------- review of #169


def test_a_row_the_scanner_made_first_becomes_the_kept_file_the_keeper_kept(db: Database) -> None:
    """The keeper's link takes over the place, the mark AND the source of a row the scanner made first: its own-file lookups and the repairs select `source = 'youtube'`."""
    ref = one_ref(db, "Weird Fishes")
    with db.tx() as conn:
        refs.attach_file(
            conn, ref, navidrome_song_id="nd1", path="Radiohead/In Rainbows/Weird Fishes.opus", codec="opus", bitrate_kbps=1
        )
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="Encore/Radiohead/In Rainbows/Weird Fishes.opus",
            codec="opus",
            bitrate_kbps=1,
            source="youtube",
            path_real=True,
        )
    with db.read() as conn:
        rows = conn.execute("SELECT path, path_real, source FROM song_file WHERE ref = ?", (ref,)).fetchall()

    assert [(r["path"], r["path_real"], r["source"]) for r in rows] == [
        ("Encore/Radiohead/In Rainbows/Weird Fishes.opus", 1, "youtube")
    ]


def test_the_scanner_never_turns_a_kept_file_into_a_library_one(db: Database) -> None:
    ref = one_ref(db, "Weird Fishes")
    with db.tx() as conn:
        refs.attach_file(
            conn,
            ref,
            navidrome_song_id="nd1",
            path="Encore/R/W.opus",
            codec="opus",
            bitrate_kbps=1,
            source="youtube",
            path_real=True,
        )
        refs.attach_file(conn, ref, navidrome_song_id="nd1", path="R/W.opus", codec="opus", bitrate_kbps=1, source="library")
    with db.read() as conn:
        row = conn.execute("SELECT source, path_real FROM song_file WHERE ref = ?", (ref,)).fetchone()

    assert (row["source"], row["path_real"]) == ("youtube", 1)


def checked_row(bench: Bench, real: str) -> tuple[str, str]:
    ref, _ = bench.library_file(real)
    assert bench.errand().run_once().resolved == 1
    with bench.db.read() as conn:
        return ref, str(conn.execute("SELECT id FROM song_file WHERE ref = ?", (ref,)).fetchone()["id"])


def test_a_checked_path_that_names_a_file_is_trusted_and_left_as_it_is(bench: Bench) -> None:
    ref, file_id = checked_row(bench, "Misc/a.opus")

    assert trusted_file(bench.db, bench.music, file_id, "Misc/a.opus") == bench.music / "Misc" / "a.opus"
    assert bench.row(ref)["path_real"] == 1


def test_a_checked_path_that_names_no_file_any_more_is_not_trusted_and_the_errand_asks_again(bench: Bench) -> None:
    """The music server may keep a song's id when its file moves, and nothing then resets the mark: the reader that finds no file takes it back."""
    ref, file_id = checked_row(bench, "Misc/a.opus")
    (bench.music / "Misc" / "a.opus").rename(bench.music / "Misc" / "moved.opus")

    assert trusted_file(bench.db, bench.music, file_id, "Misc/a.opus") is None

    row = bench.row(ref)
    assert row["path_real"] == 0 and row["path_checked_at"] is None, "back to unverified, at the front of the queue"
    bench.places.answers["nd1"] = "Misc/moved.opus"  # the music server says where it lies now
    assert bench.errand().run_once().resolved == 1
    assert (bench.row(ref)["path"], bench.row(ref)["path_real"]) == ("Misc/moved.opus", 1)


def test_the_mark_is_not_taken_back_from_a_row_that_holds_another_path_now(bench: Bench) -> None:
    ref, file_id = checked_row(bench, "Misc/a.opus")

    assert trusted_file(bench.db, bench.music, file_id, "Some/old/path.opus") is None

    assert bench.row(ref)["path_real"] == 1, "the keeper (or the errand) put a new place there meanwhile: not undone"
