"""The scheduler (docs/04 section 10): single flight, strict priorities, fair share between people, two pools, retries, resume, Stop."""

from __future__ import annotations

import threading
import time

import pytest

from encore_server import library, refs
from encore_server.db import Database
from encore_server.scheduler import GiveUp, Retry, Scheduler, WorkItem


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_refs(db: Database, count: int) -> list[str]:
    with db.tx() as conn:
        return [
            str(refs.resolve(conn, {"title": f"Song {n}", "artists": ["Artist"], "durationMs": 180000 + n * 10000})["id"])
            for n in range(count)
        ]


def make_person(db: Database, name: str) -> str:
    with db.tx() as conn:
        return str(library.ensure_person(conn, name)["id"])


class Rig:
    """A scheduler whose handlers write down what they were asked to do."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.clock = Clock()
        self.log: list[tuple[str, str]] = []
        self.behaviour: dict[str, Exception] = {}
        self.scheduler = Scheduler(
            db,
            {kind: self._handler for kind in ("play", "prepare", "download", "match", "keep", "measure")},
            clock=self.clock,
            backoff_s=(10.0, 100.0),
        )

    def _handler(self, item: WorkItem) -> None:
        self.log.append((item.kind, item.ref))
        failure = self.behaviour.get(item.ref)
        if failure is not None:
            raise failure


@pytest.fixture()
def rig(db: Database) -> Rig:
    return Rig(db)


def test_two_people_wanting_the_same_song_are_one_piece_of_work(db: Database, rig: Rig) -> None:
    (ref,) = make_refs(db, 1)
    marwa, nina = make_person(db, "marwa"), make_person(db, "nina")

    first = rig.scheduler.submit("keep", ref, marwa)
    second = rig.scheduler.submit("keep", ref, nina)
    rig.scheduler.drain()

    assert first == second
    assert rig.log == [("keep", ref)]


def test_work_is_taken_by_priority_whatever_the_order_it_was_asked_in(db: Database, rig: Rig) -> None:
    a, b, c = make_refs(db, 3)
    who = make_person(db, "marwa")
    rig.scheduler.submit("measure", a, who)
    rig.scheduler.submit("keep", b, who)
    rig.scheduler.submit("match", c, who)

    rig.scheduler.drain("background")

    assert [kind for kind, _ in rig.log] == ["match", "keep", "measure"]


def test_a_tap_on_a_song_being_kept_moves_it_to_the_front(db: Database, rig: Rig) -> None:
    first, second, third = make_refs(db, 3)
    who = make_person(db, "marwa")
    for ref in (first, second, third):
        rig.scheduler.submit("keep", ref, who)

    assert rig.scheduler.promote("keep", third) is True
    rig.scheduler.drain()

    assert [ref for _, ref in rig.log][0] == third


def test_people_take_turns_so_a_big_import_cannot_starve_a_small_one(db: Database, rig: Rig) -> None:
    refs_ = make_refs(db, 7)
    big, small = make_person(db, "marwa"), make_person(db, "nina")
    for ref in refs_[:5]:
        rig.scheduler.submit("keep", ref, big)
    for ref in refs_[5:]:
        rig.scheduler.submit("keep", ref, small)

    rig.scheduler.drain()

    order = [ref for _, ref in rig.log]
    # nina's two songs are done within the first four, not after marwa's five.
    assert {refs_[5], refs_[6]} <= set(order[:4])


def test_a_tap_is_never_stuck_behind_background_work(db: Database, rig: Rig) -> None:
    keep_ref, play_ref = make_refs(db, 2)
    who = make_person(db, "marwa")
    rig.scheduler.submit("keep", keep_ref, who)
    rig.scheduler.submit("download", play_ref, who)

    assert rig.scheduler.run_one("interactive") is True
    assert rig.log == [("download", play_ref)]
    assert rig.scheduler.run_one("interactive") is False  # the keep is the other pool's


def test_a_failure_that_may_pass_is_tried_again_after_a_pause(db: Database, rig: Rig) -> None:
    (ref,) = make_refs(db, 1)
    rig.behaviour[ref] = RuntimeError("disk hiccup")
    rig.scheduler.submit("keep", ref, make_person(db, "marwa"))

    rig.scheduler.drain()
    assert len(rig.log) == 1
    state = rig.scheduler.state_of("keep", ref)
    assert state is not None and state["state"] == "queued" and "disk hiccup" in str(state["error"])

    rig.clock.advance(5)
    rig.scheduler.drain()
    assert len(rig.log) == 1  # still resting

    rig.clock.advance(6)
    del rig.behaviour[ref]
    rig.scheduler.drain()
    assert len(rig.log) == 2
    state = rig.scheduler.state_of("keep", ref)
    assert state is not None and state["state"] == "done"


def test_after_the_last_pause_it_is_recorded_as_failed_with_the_reason(db: Database, rig: Rig) -> None:
    (ref,) = make_refs(db, 1)
    rig.behaviour[ref] = RuntimeError("still broken")
    rig.scheduler.submit("keep", ref, make_person(db, "marwa"))

    for _ in range(5):
        rig.scheduler.drain()
        rig.clock.advance(1000)

    state = rig.scheduler.state_of("keep", ref)
    assert state is not None and state["state"] == "failed" and "still broken" in str(state["error"])
    assert len(rig.log) == 3  # the first try and one after each of the two pauses


def test_giving_up_is_immediate_and_a_busy_source_is_never_given_up_on(db: Database, rig: Rig) -> None:
    gone, busy = make_refs(db, 2)
    rig.behaviour[gone] = GiveUp("removed")
    rig.behaviour[busy] = Retry("busy", after_s=60)
    who = make_person(db, "marwa")
    rig.scheduler.submit("keep", gone, who)
    rig.scheduler.submit("keep", busy, who)

    for _ in range(10):
        rig.scheduler.drain()
        rig.clock.advance(61)

    gone_state, busy_state = rig.scheduler.state_of("keep", gone), rig.scheduler.state_of("keep", busy)
    assert gone_state is not None and gone_state["state"] == "failed" and gone_state["error"] == "removed"
    assert busy_state is not None and busy_state["state"] == "queued"
    assert rig.log.count(("keep", gone)) == 1 and rig.log.count(("keep", busy)) >= 5


def test_what_was_running_when_the_server_stopped_runs_again(db: Database, rig: Rig) -> None:
    (ref,) = make_refs(db, 1)
    rig.scheduler.submit("keep", ref, make_person(db, "marwa"))
    rig.scheduler._claim("background")  # taken by a worker that then died with the server
    assert rig.scheduler.state_of("keep", ref)["state"] == "running"  # type: ignore[index]

    restarted = Scheduler(db, rig.scheduler._handlers, clock=rig.clock)
    assert restarted.recover() == 1
    restarted.drain()

    assert rig.log == [("keep", ref)]


def test_finished_work_is_forgotten_after_a_week(db: Database, rig: Rig) -> None:
    (ref,) = make_refs(db, 1)
    rig.scheduler.submit("keep", ref, make_person(db, "marwa"))
    rig.scheduler.drain()
    rig.clock.advance(8 * 24 * 3600)

    rig.scheduler.recover()

    assert rig.scheduler.state_of("keep", ref) is None


def test_stop_cancels_what_only_this_person_wanted_and_leaves_the_rest(db: Database, rig: Rig) -> None:
    mine, shared = make_refs(db, 2)
    marwa, nina = make_person(db, "marwa"), make_person(db, "nina")
    rig.scheduler.submit("keep", mine, marwa)
    rig.scheduler.submit("keep", shared, marwa)
    rig.scheduler.submit("keep", shared, nina)

    assert rig.scheduler.cancel_person(marwa) == 1
    rig.scheduler.drain()

    assert rig.log == [("keep", shared)]
    cancelled = rig.scheduler.state_of("keep", mine)
    assert cancelled is not None and cancelled["state"] == "cancelled"


def test_stop_while_it_runs_is_seen_by_the_handler_and_not_overwritten(db: Database, rig: Rig) -> None:
    (ref,) = make_refs(db, 1)
    who = make_person(db, "marwa")
    seen: list[bool] = []

    def handler(item: WorkItem) -> None:
        rig.scheduler.cancel_person(who)
        seen.append(rig.scheduler.is_cancelled(item))

    scheduler = Scheduler(db, {"keep": handler}, clock=rig.clock)
    scheduler.submit("keep", ref, who)
    scheduler.drain()

    assert seen == [True]
    state = scheduler.state_of("keep", ref)
    assert state is not None and state["state"] == "cancelled"


def test_a_request_inside_the_callers_transaction_is_part_of_that_write(db: Database, rig: Rig) -> None:
    (ref,) = make_refs(db, 1)
    who = make_person(db, "marwa")

    with pytest.raises(RuntimeError), db.tx() as conn:
        rig.scheduler.submit("keep", ref, who, conn=conn)
        raise RuntimeError("the like failed")

    assert rig.scheduler.state_of("keep", ref) is None


def test_the_worker_threads_pick_up_new_work_and_stop_when_asked(db: Database) -> None:
    (ref,) = make_refs(db, 1)
    who = make_person(db, "marwa")
    done = threading.Event()
    scheduler = Scheduler(db, {"keep": lambda item: done.set()}, workers={"background": 1, "interactive": 1})
    scheduler.start()
    try:
        scheduler.submit("keep", ref, who)
        assert done.wait(5), "the worker never ran the item"
    finally:
        scheduler.stop()

    deadline = time.time() + 2
    while time.time() < deadline and (scheduler.state_of("keep", ref) or {}).get("state") != "done":
        time.sleep(0.02)
    assert (scheduler.state_of("keep", ref) or {}).get("state") == "done"
