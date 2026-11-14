"""N-13: the server remembers the songs it cannot get, and says so before anybody taps them (docs/17 "Songs the server cannot get").

The rules these tests hold:

* only a "no" that the source ANSWERED is remembered (a search that answered with nothing, an upload that is gone after one search for another, an age check);
  a search that could not be made, YouTube resting, a timeout are never remembered;
* inside the window a tap makes NO look-up at YouTube; after it, one real search that clears the memory or starts a new window;
* the app can learn it from the ref (`unavailable`) and from one batched read-only question (`POST refs/unavailable`); older servers have neither, which is why
  the field is optional and the route may be absent (the app tests hold the other half).

Nothing here asks YouTube: the searches and the streams are fakes, and the look-ups are counted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from encore_server import library, missing, refmerge, refs
from encore_server.api import create_app
from encore_server.config import Settings
from encore_server.db import Database
from encore_server.ids import now_ms
from encore_server.sources.youtube.errors import DownloadError
from encore_server.sources.youtube.scoring import Candidate, Scored, Want
from encore_server.sources.youtube.source import Wanted, YoutubeSource
from encore_server.sources.youtube.stream import StreamError, StreamProxy
from encore_server.verdicts import RefVerdicts
from tests.conftest import FakeVerifier, creds, resolve, song
from tests.sources.test_stream import FakeYouTube, info_file
from tests.test_ref_merge import add_file, add_ref
from tests.test_stream_route import DATA, V1, address

DAY = 24 * 3600 * 1000


class Clock:
    """The memory's clock, set to now: `get_ref` reads the real one, and a mark made in 2001 would be long over."""

    def __init__(self) -> None:
        self.now = now_ms()

    def __call__(self) -> int:
        return self.now


def make_ref(db: Database, **song_fields: object) -> str:
    base = {"title": "Lofi For Focus", "artists": ["Lofi & Sleep"], "durationMs": 180000}
    with db.tx() as conn:
        return str(refs.resolve(conn, {**base, **song_fields})["id"])


def ref_json(db: Database, ref_id: str) -> dict[str, Any]:
    with db.read() as conn:
        return refs.get_ref(conn, ref_id)


# ------------------------------------------------------------------------------------------------------------ the memory itself


def test_a_remembered_no_is_on_the_ref_while_it_is_believed(db: Database) -> None:
    ref = make_ref(db)
    assert "unavailable" not in ref_json(db, ref), "a ref that remembers nothing has no such field (an old app reads nothing new)"

    with db.tx() as conn:
        refs.remember_missing(conn, ref, "not_found")

    found = ref_json(db, ref)["unavailable"]
    assert found["reason"] == "not_found" and found["message"] == "Nothing matching that song was found."
    assert found["retryAfter"] - found["since"] == missing.WINDOW_MS


def test_the_window_counts_from_the_last_try_and_the_first_sight_is_kept(db: Database) -> None:
    ref = make_ref(db)
    with db.tx() as conn:
        refs.remember_missing(conn, ref, "not_found", now=1_000_000)
        refs.remember_missing(conn, ref, "removed", now=1_000_000 + 8 * DAY)  # the window was over; a real try again said no

    with db.read() as conn:
        row = conn.execute("SELECT * FROM song_ref WHERE id = ?", (ref,)).fetchone()
    standing = missing.standing_of(row, 1_000_000 + 8 * DAY)
    assert standing is not None and standing.live
    assert (standing.reason, standing.since, standing.tried_at) == ("removed", 1_000_000, 1_000_000 + 8 * DAY)
    assert missing.standing_of(row, 1_000_000 + 8 * DAY + 7 * DAY - 1).live  # type: ignore[union-attr]
    assert not missing.standing_of(row, 1_000_000 + 8 * DAY + 7 * DAY).live  # type: ignore[union-attr]


def test_after_the_window_the_ref_says_nothing_but_remembers_that_it_said_it(db: Database) -> None:
    ref = make_ref(db)
    with db.tx() as conn:
        refs.remember_missing(
            conn, ref, "not_found", now=missing.WINDOW_MS
        )  # long ago, in the test's terms: the real clock is far past it
        # (the real clock is used by `get_ref`: the epoch plus one window is more than a week ago)
    assert "unavailable" not in ref_json(db, ref)
    assert RefVerdicts(db).standing(ref) is not None, "the old answer is still there, so that a success can clear it"


def test_a_better_matcher_voids_every_older_no_at_once(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = make_ref(db)
    with db.tx() as conn:
        refs.remember_missing(conn, ref, "not_found")
    assert "unavailable" in ref_json(db, ref)

    monkeypatch.setattr(missing, "MATCHER_REVISION", missing.MATCHER_REVISION + 1)

    assert "unavailable" not in ref_json(db, ref), (
        "an answer made by an older matcher says nothing about what this one would find"
    )
    assert not RefVerdicts(db).standing(ref).live  # type: ignore[union-attr]


def test_only_the_three_reasons_are_ever_stored(db: Database) -> None:
    ref = make_ref(db)
    with db.tx() as conn, pytest.raises(ValueError):
        refs.remember_missing(conn, ref, "blocked")


@pytest.mark.parametrize("how", ["a file is attached", "an upload is found", "an upload is named by a description"])
def test_finding_the_song_voids_what_was_remembered_about_its_absence(db: Database, how: str) -> None:
    ref = make_ref(db)
    with db.tx() as conn:
        refs.remember_missing(conn, ref, "not_found")

    with db.tx() as conn:
        if how == "a file is attached":
            refs.attach_file(conn, ref, navidrome_song_id="nd-1", path="Encore/a.opus", codec="opus", bitrate_kbps=128)
        elif how == "an upload is found":
            assert refs.remember_video(conn, ref, "aaaaaaaaaaa")
        else:
            refs.resolve(
                conn, {"title": "Lofi For Focus", "artists": ["Lofi & Sleep"], "durationMs": 180000, "videoId": "bbbbbbbbbbb"}
            )

    assert "unavailable" not in ref_json(db, ref)
    with db.read() as conn:
        assert conn.execute("SELECT missing_reason FROM song_ref WHERE id = ?", (ref,)).fetchone()["missing_reason"] is None


def test_a_song_the_server_keeps_never_shows_the_mark_even_if_a_row_still_has_it(db: Database) -> None:
    ref = make_ref(db)
    with db.tx() as conn:
        refs.remember_missing(conn, ref, "not_found")
        conn.execute(
            "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, bitrate_kbps, source, preferred, added_at)"
            " VALUES ('sf_1', ?, 'nd-1', 'a.opus', 'opus', 128, 'youtube', 1, 1)",
            (ref,),
        )

    assert "unavailable" not in ref_json(db, ref), "a song with a file plays; nothing may grey it"


def test_a_merge_never_hands_a_mark_to_the_survivor(db: Database) -> None:
    """The survivor holds the file that was attached first; what the other ref remembered about the absence of an upload is not the survivor's."""
    first, second = "sr_" + "0" * 25 + "1", "sr_" + "0" * 25 + "2"
    with db.tx() as c:
        add_ref(c, first, "Same File", ["Ana Vale"])
        add_ref(c, second, "Same File", ["Ana Vale"])
        add_file(c, first, "nd-1", 4000, source="library", path="a.opus")
        add_file(c, second, "nd-1", 5000, source="youtube", path="b.opus")
        refs.remember_missing(c, second, "not_found")

    report = refmerge.repair(db)

    assert [(m.survivor, m.loser) for m in report.merged] == [(first, second)]
    with db.read() as conn:
        row = conn.execute("SELECT missing_reason FROM song_ref WHERE id = ?", (first,)).fetchone()
    assert row["missing_reason"] is None


# ------------------------------------------------------------------------------------------------------------ how a phone learns


def test_marking_and_clearing_do_not_write_to_the_files_feed(db: Database) -> None:
    """The files feed is the phone's index of what the server KEEPS. A song with no file in it would be a row to write and retire on every phone (an
    import of 300 songs that were not found: 300 of them), and the phone reads the mark from the ref it resolves and from `POST refs/unavailable`."""
    ref = make_ref(db)
    with db.read() as conn:
        cursor = library.files_since(conn, 0)["cursor"]

    with db.tx() as conn:
        refs.remember_missing(conn, ref, "not_found")
        refs.remember_missing(conn, ref, "removed")
        refs.clear_missing(conn, ref)

    with db.read() as conn:
        assert library.files_since(conn, int(cursor))["refs"] == []


def test_the_batched_question_answers_in_order_and_makes_no_ref(db: Database) -> None:
    gone = make_ref(db, deezerId="111")
    fine = make_ref(db, title="Rainy Window", deezerId="222")
    with db.tx() as conn:
        refs.remember_missing(conn, gone, "not_found")
        before = conn.execute("SELECT COUNT(*) AS n FROM song_ref").fetchone()["n"]

    with db.read() as conn:
        answers = refs.unavailable_for(
            conn,
            [
                {"title": "Rainy Window", "artists": ["Lofi & Sleep"], "durationMs": 180000},  # a known song with no problem
                {
                    "title": "lofi for focus",
                    "artists": ["LOFI & SLEEP"],
                    "durationMs": 181500,
                },  # spelled otherwise, 1.5 s off: the same song
                {"title": "Never Seen", "artists": ["Nobody"], "durationMs": 100000},  # a song this server has never seen
                {"title": ""},  # cannot be a song
                "not even an object",
                {"title": "Other Name", "artists": ["Else"], "deezerId": "111"},  # found by the catalogue id
            ],
        )

    assert [a is not None for a in answers] == [False, True, False, False, False, True]
    assert answers[1]["reason"] == "not_found" and answers[5]["reason"] == "not_found"  # type: ignore[index]
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM song_ref").fetchone()["n"] == before, "asking creates nothing"
    assert fine != gone


def test_the_route_needs_a_login_takes_one_to_a_hundred_songs_and_is_a_read(client: TestClient) -> None:
    one = song("Lofi For Focus", "Lofi & Sleep")
    ref = str(resolve(client, "marwa", one)[0]["id"])
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    with db.tx() as conn:
        refs.remember_missing(conn, ref, "removed")

    assert client.post(f"{V1}/refs/unavailable", json={"songs": [one]}).status_code == 401
    for bad in ({}, {"songs": []}, {"songs": "x"}, {"songs": [one] * 101}):
        assert client.post(f"{V1}/refs/unavailable", params=creds("marwa"), json=bad).status_code == 400
    reply = client.post(f"{V1}/refs/unavailable", params=creds("marwa"), json={"songs": [one, song("Other", "Else")]})

    assert reply.status_code == 200
    items = reply.json()["items"]
    assert items[0]["reason"] == "removed" and items[0]["message"] and items[1] is None
    assert client.post(f"{V1}/refs/unavailable", params=creds("marwa"), json={"songs": [one] * 100}).status_code == 200


def test_the_question_by_ref_id_answers_in_order_and_makes_no_ref(db: Database) -> None:
    """B-128: a phone's own rows are refs, so it asks by ref id (the exact identity) and not by a description of the song."""
    gone = make_ref(db, deezerId="111")
    fine = make_ref(db, title="Rainy Window", deezerId="222")
    kept = make_ref(db, title="Kept Anyway", deezerId="333")
    with db.tx() as conn:
        refs.remember_missing(conn, gone, "not_found")
        refs.remember_missing(conn, kept, "not_found")
        conn.execute(
            "INSERT INTO song_file (id, ref, navidrome_song_id, path, codec, bitrate_kbps, source, preferred, added_at)"
            " VALUES ('sf_1', ?, 'nd-1', 'k.opus', 'opus', 128, 'youtube', 1, 1)",
            (kept,),
        )
        before = conn.execute("SELECT COUNT(*) AS n FROM song_ref").fetchone()["n"]

    with db.read() as conn:
        answers = refs.unavailable_for_ids(conn, [fine, gone, "sr_" + "9" * 25, 42, kept, gone])  # type: ignore[list-item]

    assert [a is not None for a in answers] == [False, True, False, False, False, True], (
        "no problem, a remembered no, an id never seen, not an id at all, a song the server keeps (never marked), the same id twice"
    )
    assert answers[1]["reason"] == "not_found" and answers[1]["retryAfter"] > now_ms()  # type: ignore[index]
    assert answers[1] == answers[5]
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM song_ref").fetchone()["n"] == before, "asking creates nothing"


def test_a_ref_id_that_was_merged_away_answers_for_the_survivor(db: Database) -> None:
    """N-11: an old phone still names the id the merge removed; the verdict is the survivor's (and a survivor with a file has none)."""
    survivor, loser = "sr_" + "0" * 25 + "1", "sr_" + "0" * 25 + "2"
    with db.tx() as c:
        add_ref(c, survivor, "Same Song", ["Ana Vale"])
        add_ref(c, loser, "Same Song", ["Ana Vale"])
        refs.remember_missing(c, survivor, "removed")
        c.execute("INSERT INTO ref_merge (old_id, into_id, at, norm_key) VALUES (?, ?, 1, 'x')", (loser, survivor))
        c.execute("DELETE FROM song_ref WHERE id = ?", (loser,))

    with db.read() as conn:
        answers = refs.unavailable_for_ids(conn, [loser])

    assert answers[0] is not None and answers[0]["reason"] == "removed"


def test_the_route_takes_ref_ids_too_exactly_one_kind_at_a_time_and_is_still_a_read(client: TestClient) -> None:
    one = song("Lofi For Focus", "Lofi & Sleep")
    ref = str(resolve(client, "marwa", one)[0]["id"])
    db: Database = client.app.state.services.db  # type: ignore[attr-defined]
    with db.tx() as conn:
        refs.remember_missing(conn, ref, "age_restricted")
        before = conn.execute("SELECT COUNT(*) AS n FROM song_ref").fetchone()["n"]
    ask = f"{V1}/refs/unavailable"

    assert client.post(ask, json={"ids": [ref]}).status_code == 401
    for bad in ({"ids": []}, {"ids": "x"}, {"ids": [ref] * 101}, {"ids": [ref, 7]}, {"ids": [ref], "songs": [one]}):
        assert client.post(ask, params=creds("marwa"), json=bad).status_code == 400, bad
    reply = client.post(ask, params=creds("marwa"), json={"ids": [ref, "sr_" + "9" * 25]})

    assert reply.status_code == 200
    items = reply.json()["items"]
    assert items[0]["reason"] == "age_restricted" and items[0]["message"] and items[1] is None
    assert client.post(ask, params=creds("marwa"), json={"ids": [ref] * 100}).status_code == 200
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM song_ref").fetchone()["n"] == before, "asking by id creates nothing"


def test_the_app_is_told_by_the_features_that_it_may_ask_by_ref_id(client: TestClient) -> None:
    """docs/17 "Versions": an app does without a feature the server does not list and never tries a route to find out. An N-13 server before this
    change answers `{"ids": ...}` with a 400, so the phone must not send it there."""
    assert "unavailable-ids" in client.get(f"{V1}/info").json()["features"]


# ------------------------------------------------------------------------------------------------------------ the source: no repeat look-ups


class Rig:
    """A real `YoutubeSource` over a fake search and fake bytes, with the memory in a real database and a clock the test moves. `searches` counts the look-ups
    (one per search); `extractions` the stream-address look-ups. Nothing reaches YouTube."""

    def __init__(self, tmp: Path, db: Database) -> None:
        self.db = db
        self.clock = Clock()
        self.searches: list[str] = []
        self.extractions: list[str] = []
        self.found: list[tuple[str, str, int | None]] | None = []  # what the search answers; None: the search cannot be made
        self.gone: set[str] = set()  # uploads whose extraction says "removed"
        self.age_gated: set[str] = set()
        self.remembered_videos: list[tuple[str, str]] = []

        rig = self

        class FakeResolver:
            """The search the source makes (`_candidates` calls it when the ref names no upload): counted, and answering what the test says."""

            def resolve_ranked(self, want: Want) -> list[Scored]:
                rig.searches.append(want.title)
                if rig.found is None:
                    raise DownloadError("search_failed", "the song search is not answering")
                return [Scored(Candidate(video_id, title, "Topic", duration), 9.0, ()) for video_id, title, duration in rig.found]

        inner = info_file(size=len(DATA))

        def extract(video_id: str, path: Path) -> None:
            self.extractions.append(video_id)
            if video_id in self.gone:
                raise DownloadError("unavailable")
            if video_id in self.age_gated:
                raise DownloadError("age_restricted")
            inner(video_id, path)

        def remember(ref_id: str, video_id: str, replacing: str | None = None) -> None:
            with db.tx() as conn:
                refs.remember_video(conn, ref_id, video_id, replacing=replacing)

        self.source = YoutubeSource(
            tmp / "work",
            resolver=FakeResolver(),
            extractor=object(),
            proxy=StreamProxy(
                candidates=lambda wanted: self.source._candidates(
                    wanted
                ),  # the source's own (resolver, then remembering the upload)
                extract=extract,
                work_dir=tmp / "work",
                opener=FakeYouTube(DATA),
                sleep=lambda s: None,
            ),
            remember_video=remember,
            verdicts=RefVerdicts(db, clock=self.clock),
        )

    def wanted(self, ref: str, video_id: str | None = None) -> Wanted:
        return Wanted(ref_id=ref, artist="Lofi & Sleep", title="Lofi For Focus", album=None, duration_s=180, video_id=video_id)

    def open(self, ref: str, video_id: str | None = None) -> None:
        self.source.open(self.wanted(ref, video_id), None).close()

    def standing(self, ref: str) -> missing.Standing | None:
        return RefVerdicts(self.db, clock=self.clock).standing(ref)


@pytest.fixture()
def rig(tmp_path: Path, db: Database) -> Rig:
    return Rig(tmp_path, db)


def test_a_search_that_answered_nothing_is_remembered_and_the_next_tap_looks_nothing_up(rig: Rig, db: Database) -> None:
    ref = make_ref(db)

    with pytest.raises(StreamError) as first:
        rig.open(ref)
    with pytest.raises(StreamError) as second:
        rig.open(ref)

    assert first.value.code == second.value.code == "not_found"
    assert len(rig.searches) == 1, "the second tap asked YouTube nothing"
    assert rig.standing(ref).reason == "not_found"  # type: ignore[union-attr]
    assert ref_json(db, ref)["unavailable"]["reason"] == "not_found"


def test_after_the_window_one_real_search_decides_again(rig: Rig, db: Database) -> None:
    ref = make_ref(db)
    with pytest.raises(StreamError):
        rig.open(ref)
    rig.clock.now += missing.WINDOW_MS + 1
    rig.found = [("aaaaaaaaaaa", "Lofi For Focus", 180)]  # the catalogue gained an upload in the meantime

    rig.open(ref)  # plays

    assert len(rig.searches) == 2
    assert rig.standing(ref) is None, "found: what was remembered is cleared"


def test_after_the_window_a_second_no_starts_a_new_window_and_keeps_the_first_sight(rig: Rig, db: Database) -> None:
    ref = make_ref(db)
    with pytest.raises(StreamError):
        rig.open(ref)
    first_seen = rig.standing(ref).since  # type: ignore[union-attr]
    rig.clock.now += 10 * DAY

    with pytest.raises(StreamError):
        rig.open(ref)

    standing = rig.standing(ref)
    assert standing is not None and standing.live and standing.since == first_seen and standing.tried_at == rig.clock.now
    assert len(rig.searches) == 2


@pytest.mark.parametrize(
    ("failure"),
    [DownloadError("search_failed"), DownloadError("blocked"), DownloadError("timeout"), DownloadError("download_failed")],
)
def test_what_may_pass_is_never_remembered(rig: Rig, db: Database, failure: DownloadError) -> None:
    """A search that could not be made (B-122), YouTube resting, a timeout, any other failure: not an answer about the song."""
    ref = make_ref(db)
    rig.found = None if failure.code == "search_failed" else []
    if failure.code != "search_failed":

        def refuse(video_id: str, path: Path) -> None:
            raise failure

        rig.source._proxy._extract = refuse  # type: ignore[attr-defined]
        rig.found = [("aaaaaaaaaaa", "Lofi For Focus", 180)]

    with pytest.raises((StreamError, DownloadError)):
        rig.open(ref)

    assert rig.standing(ref) is None
    assert "unavailable" not in ref_json(db, ref)


def test_a_stored_upload_that_is_gone_gets_one_search_for_another_before_the_song_is_called_missing(
    rig: Rig, db: Database
) -> None:
    ref = make_ref(db, videoId="deadvideo01")
    rig.gone = {"deadvideo01"}
    rig.found = [("aliveonenn1", "Lofi For Focus", 180)]

    rig.open(ref, "deadvideo01")  # plays, from the other upload

    assert rig.searches == ["Lofi For Focus"] and rig.standing(ref) is None
    assert ref_json(db, ref)["videoId"] == "aliveonenn1", (
        "the dead upload was replaced by the live one: the next play needs no search"
    )


def test_removed_is_stored_only_after_the_search_for_another_upload_also_found_nothing(rig: Rig, db: Database) -> None:
    ref = make_ref(db, videoId="deadvideo01")
    rig.gone = {"deadvideo01"}
    rig.found = []

    with pytest.raises(StreamError) as caught:
        rig.open(ref, "deadvideo01")

    assert caught.value.code == "unavailable" and rig.searches == ["Lofi For Focus"], "one search was made before saying so"
    assert rig.standing(ref).reason == "removed"  # type: ignore[union-attr]
    assert ref_json(db, ref)["unavailable"]["reason"] == "removed"


def test_an_age_check_is_its_own_reason(rig: Rig, db: Database) -> None:
    """Not folded into `removed`: a signed-in YouTube account on the server (D-67, not built) could clear these without voiding the others."""
    ref = make_ref(db)
    rig.found = [("agegatedvid", "Lofi For Focus", 180)]
    rig.age_gated = {"agegatedvid"}

    with pytest.raises(StreamError) as caught:
        rig.open(ref)

    assert caught.value.code == "age_restricted"
    assert rig.standing(ref).reason == "age_restricted"  # type: ignore[union-attr]
    assert ref_json(db, ref)["unavailable"]["message"] == "That song needs an age check, so it cannot be played here."


def test_background_work_asks_nothing_about_a_song_the_server_knows_it_cannot_get(rig: Rig, db: Database) -> None:
    ref = make_ref(db)
    with pytest.raises(StreamError):
        rig.open(ref)
    asked = len(rig.searches)
    wanted = rig.wanted(ref)

    assert rig.source.is_missing(wanted)
    assert rig.source.prepare(wanted) is False
    assert rig.source.find(wanted) is None
    with pytest.raises(DownloadError) as kept:
        rig.source.download(wanted, Path("unused"), max_bytes=10)

    assert kept.value.code == "not_found", "the keeper gives it up as it does a fresh no"
    assert len(rig.searches) == asked, "none of the three looked anything up"


def test_a_search_that_answers_nothing_is_remembered_by_an_import_too(rig: Rig, db: Database) -> None:
    ref = make_ref(db)

    assert rig.source.find(rig.wanted(ref)) is None
    assert rig.standing(ref).reason == "not_found"  # type: ignore[union-attr]
    assert rig.source.find(rig.wanted(ref)) is None and len(rig.searches) == 1


def test_a_gone_upload_that_a_description_names_again_does_not_void_what_the_server_remembers(rig: Rig, db: Database) -> None:
    """The imported-song case. The ref has a dead upload; the server stored `removed` after one search found nothing else. The phone's description of the
    song carries the SAME dead id on every prepare and tap, and the import matcher's fallback offers the entry's own video: neither may undo the memory,
    or every tap would cost an extraction and a search again."""
    ref = make_ref(db, videoId="deadvideo01")
    rig.gone = {"deadvideo01"}
    rig.found = []
    with pytest.raises(StreamError):
        rig.open(ref, "deadvideo01")
    assert rig.standing(ref).reason == "removed"  # type: ignore[union-attr]
    assert ref_json(db, ref)["videoId"] == "deadvideo01", "the dead id stays until a live one replaces it"

    with db.tx() as conn:
        again = refs.resolve(
            conn, {"title": "Lofi For Focus", "artists": ["Lofi & Sleep"], "durationMs": 180000, "videoId": "deadvideo01"}
        )
        assert refs.remember_video(conn, ref, "deadvideo01") is False  # what an import's fallback does with the entry's video

    assert again["id"] == ref and again["unavailable"]["reason"] == "removed"
    assert rig.standing(ref).live  # type: ignore[union-attr]
    rig.searches.clear()
    rig.extractions.clear()
    with pytest.raises(StreamError) as caught:
        rig.open(ref, "deadvideo01")
    assert caught.value.code == "unavailable"
    assert rig.searches == [] and rig.extractions == [], "the next tap made no look-up of any kind"


def test_a_new_upload_that_is_named_after_a_not_found_does_clear_it(rig: Rig, db: Database) -> None:
    """The other side: the memory said no upload exists, and now somebody names one. That is news, so the memory goes (and the next play tries it)."""
    ref = make_ref(db)
    with pytest.raises(StreamError):
        rig.open(ref)
    assert rig.standing(ref).reason == "not_found"  # type: ignore[union-attr]

    with db.tx() as conn:
        refs.resolve(
            conn, {"title": "Lofi For Focus", "artists": ["Lofi & Sleep"], "durationMs": 180000, "videoId": "newvideo001"}
        )

    assert rig.standing(ref) is None


@pytest.mark.parametrize("fault", ["no_results", "youtube_refuse"])
def test_a_fault_injected_for_a_test_is_never_remembered_and_never_believed(tmp_path: Path, db: Database, fault: str) -> None:
    """`ENCORE_FAULT` makes YouTube misbehave on purpose for a test of the whole app; what it makes up is not an answer about any song. Without this a
    `no_results` run on a real test server would hold every song it touched as missing for a week after the fault was switched off."""
    ref = make_ref(db)

    class NeverSearches:
        def resolve_ranked(self, want: Want) -> list[Scored]:
            raise AssertionError("a fault answers before any search")

    source = YoutubeSource(tmp_path / "work", resolver=NeverSearches(), extractor=object(), fault=fault, verdicts=RefVerdicts(db))
    wanted = Wanted(ref_id=ref, artist="Lofi & Sleep", title="Lofi For Focus", album=None, duration_s=180, video_id=None)

    with pytest.raises((StreamError, DownloadError)):
        source.open(wanted, None)
    assert source.prepare(wanted) is False

    assert RefVerdicts(db).standing(ref) is None
    # and a memory made some other way is not believed while a fault is on (the test of the whole app wants the fault)
    with db.tx() as conn:
        refs.remember_missing(conn, ref, "not_found")
    assert source.is_missing(wanted) is False


# ------------------------------------------------------------------------------------------------------------ the whole route


def test_the_second_tap_of_a_song_the_search_cannot_match_makes_no_look_up_and_the_ref_says_so(
    tmp_path: Path, verifier: FakeVerifier
) -> None:
    """The owner's "Lofi For Focus" (7 Nov 2026, A35: 9 seconds, then 'nothing matches it'; and again on every tap) at the real route."""
    searches: list[str] = []

    def candidates(wanted: Wanted) -> list[tuple[str, str, int | None]]:
        searches.append(wanted.title)
        return []

    class NeverSearches:
        def resolve_ranked(self, want: Want) -> list[Scored]:
            raise AssertionError("this test's search is `candidates`; the default one must never run")

    source = YoutubeSource(
        tmp_path / "work",
        resolver=NeverSearches(),
        extractor=object(),
        proxy=StreamProxy(
            candidates=candidates,
            extract=info_file(size=len(DATA)),
            work_dir=tmp_path / "work",
            opener=FakeYouTube(DATA),
            sleep=lambda s: None,
        ),
    )
    settings = Settings(
        data_dir=tmp_path / "data", music_dir=tmp_path / "music", navidrome_url="http://navidrome.invalid", youtube=False
    )
    with TestClient(create_app(settings, verifier=verifier, youtube=source)) as client:
        ref = str(resolve(client, "marwa", song("Lofi For Focus", "Lofi & Sleep"))[0]["id"])
        first = client.get(address(client, ref))
        second = client.get(address(client, ref))
        shown = client.get(f"{V1}/refs/{ref}", params=creds("marwa")).json()

    for reply in (first, second):
        error = reply.json()["error"]
        assert reply.status_code == 404 and error["code"] == "song_unavailable" and error["details"]["reason"] == "not_found"
    assert searches == ["Lofi For Focus"], "one search for two taps"
    assert shown["unavailable"]["reason"] == "not_found"
