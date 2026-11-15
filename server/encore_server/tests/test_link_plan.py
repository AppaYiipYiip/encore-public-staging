"""When the library link runs (P3-35, audit B-60): soon after the music server has finished a scan that changed something, not on the next
tick of an hourly timer. The plan is a pure object (the time and the music server's scan status go in, a decision comes out), so every case
here runs with a made-up clock and no thread."""

from __future__ import annotations

from typing import Any

from encore_server.link_plan import LinkPlan, Step

EVERY = 3600.0
FIRST = 20.0
GAP = 60.0
WATCH = 30.0
BUSY = 5.0
LONG_SCAN = 3 * 3600.0


def status(count: int | None = 100, last: str | None = "scan-1", scanning: bool = False) -> dict[str, Any]:
    return {"scanning": scanning, "count": count, "lastScan": last, "folderCount": 10}


def make(**changes: float) -> LinkPlan:
    settings = {
        "first_after_s": FIRST,
        "every_s": EVERY,
        "min_gap_s": GAP,
        "spread": 9.0,
        "watch_s": WATCH,
        "busy_s": BUSY,
        "scan_wait_max_s": LONG_SCAN,
        **changes,
    }
    plan = LinkPlan(**settings)
    plan.begin(0.0)
    return plan


def do(
    plan: LinkPlan, at: float, music: dict[str, Any] | None, expected: str | None, *, took: float = 1.0, complete: bool = True
) -> Step:
    """Asks the plan at time [at], checks what it decides, and when it decides to run, runs it for [took] seconds."""
    step = plan.next(at, music)
    assert step.run == expected, f"at {at} s the plan said {step.run!r}, wanted {expected!r}"
    if step.run is not None:
        plan.finished(step, started=at, ended=at + took, complete=complete)
    return step


def after_the_first_tick(plan: LinkPlan, music: dict[str, Any] | None = None) -> None:
    do(plan, FIRST, music if music is not None else status(), "tick")


# --------------------------------------------------------------------------------------------- the hourly tick stays


def test_the_first_pass_is_the_tick_a_little_after_start_and_nothing_runs_before() -> None:
    plan = make()

    early = plan.next(0.0, status())

    assert early.run is None and early.wait_s == FIRST, "it looks again when the tick is due, not later"
    do(plan, FIRST, status(), "tick")


def test_a_music_server_that_changes_nothing_gets_only_the_hourly_tick() -> None:
    plan = make()
    after_the_first_tick(plan)

    for at in range(60, int(FIRST + 1 + EVERY), 30):
        do(plan, float(at), status(), None)

    do(plan, FIRST + 1 + EVERY, status(), "tick")


def test_the_tick_is_counted_from_the_end_of_the_last_tick_not_from_a_scan_pass() -> None:
    plan = make()
    after_the_first_tick(plan)  # ends at 21
    do(plan, 500.0, status(count=101, last="scan-2"), "scan")  # a pass because of a scan: the tick is not moved by it

    do(plan, 21.0 + EVERY - 1, status(count=101, last="scan-2"), None)
    do(plan, 21.0 + EVERY, status(count=101, last="scan-2"), "tick")


# --------------------------------------------------------------------------------------------- the link follows the scan


def test_a_scan_that_finished_and_changed_something_is_linked_at_the_next_look() -> None:
    plan = make()
    after_the_first_tick(plan)

    do(plan, 300.0, status(count=107, last="scan-2"), "scan")


def test_a_scan_that_changed_only_its_time_is_linked_too() -> None:
    """An album replaced by another with as many songs, or a retag, moves `lastScan` and not `count`."""
    plan = make()
    after_the_first_tick(plan)

    do(plan, 300.0, status(count=100, last="scan-2"), "scan")


def test_nothing_runs_while_the_music_server_is_scanning_and_the_pass_follows_the_end_of_the_scan() -> None:
    plan = make()
    after_the_first_tick(plan)

    waiting = do(plan, 300.0, status(count=104, last="scan-2", scanning=True), None)
    assert waiting.wait_s == BUSY, "while it scans, it is asked often, so the end of the scan is seen soon"
    do(plan, 305.0, status(count=104, last="scan-2", scanning=True), None)
    do(plan, 310.0, status(count=107, last="scan-2", scanning=False), "scan")


def test_a_pass_records_what_the_music_server_said_before_it_began_so_a_scan_that_ends_meanwhile_is_not_lost() -> None:
    plan = make()
    after_the_first_tick(plan)
    first = plan.next(300.0, status(count=107, last="scan-2"))
    assert first.run == "scan"
    plan.finished(first, started=300.0, ended=302.0, complete=True)

    # While that pass was reading, another scan ended: the status now differs from the one the pass began with.
    do(plan, 302.0 + GAP, status(count=110, last="scan-3"), "scan")
    do(plan, 302.0 + GAP + 3 + GAP, status(count=110, last="scan-3"), None)


def test_the_same_status_is_not_linked_twice() -> None:
    plan = make()
    after_the_first_tick(plan)
    do(plan, 300.0, status(count=107, last="scan-2"), "scan")

    for at in (400.0, 430.0, 460.0, 1000.0):
        do(plan, at, status(count=107, last="scan-2"), None)


def test_no_scan_pass_before_the_first_tick_has_run() -> None:
    """At start the first look would find a status it has never linked; the tick, 20 s later, does that pass, so one pass is enough."""
    plan = make()

    do(plan, 0.0, status(count=100, last="scan-1"), None)
    do(plan, 10.0, status(count=100, last="scan-1"), None)


# --------------------------------------------------------------------------------------------- the floor and the cost


def test_scans_that_finish_inside_the_floor_are_one_pass_after_it() -> None:
    plan = make()
    after_the_first_tick(plan)
    do(plan, 300.0, status(count=101, last="scan-2"), "scan", took=2.0)  # ends at 302; the floor ends at 362

    # A person copying an album: a scan finishes every few seconds.
    for index, at in enumerate((310.0, 320.0, 330.0, 340.0, 350.0, 360.0), start=3):
        step = do(plan, at, status(count=100 + index, last=f"scan-{index}"), None)
        assert step.wait_s <= WATCH, "and it never sleeps past the end of the floor"
    do(plan, 362.0, status(count=110, last="scan-9"), "scan")


def test_the_floor_is_nine_times_the_length_of_the_last_pass_so_a_big_library_spends_a_tenth_of_its_time_on_passes() -> None:
    plan = make()
    after_the_first_tick(plan)
    do(plan, 300.0, status(count=101, last="scan-2"), "scan", took=100.0)  # a library of 200,000 songs: ends at 400

    do(plan, 410.0, status(count=102, last="scan-3"), None)
    do(plan, 400.0 + 899.0, status(count=102, last="scan-3"), None)
    do(plan, 400.0 + 900.0, status(count=102, last="scan-3"), "scan")


def test_a_library_whose_pass_is_very_long_is_still_linked_by_the_hourly_tick() -> None:
    plan = make()
    after_the_first_tick(plan)
    do(plan, 300.0, status(count=101, last="scan-2"), "scan", took=1000.0)  # 9 x 1000 s would be two and a half hours

    do(plan, 21.0 + EVERY - 1, status(count=102, last="scan-3"), None)
    do(plan, 21.0 + EVERY, status(count=102, last="scan-3"), "tick")


def test_a_pass_that_could_not_ask_the_music_server_is_tried_again_after_the_floor() -> None:
    plan = make()
    after_the_first_tick(plan)
    do(plan, 300.0, status(count=101, last="scan-2"), "scan", complete=False)  # the music server did not answer the songs

    do(plan, 301.0 + GAP, status(count=101, last="scan-2"), "scan")


def test_an_incomplete_tick_is_tried_again_in_two_minutes() -> None:
    """(With a music server that does not answer: it cannot say anything else either.)"""
    plan = make()
    do(plan, FIRST, None, "tick", complete=False)  # ends at 21

    do(plan, 21.0 + 119.0, None, None)
    do(plan, 21.0 + 120.0, None, "tick")


def test_a_pass_that_failed_with_an_error_is_tried_again_by_the_tick_in_five_minutes() -> None:
    plan = make()
    step = plan.next(FIRST, None)
    plan.failed(step, at=FIRST + 1.0)

    do(plan, FIRST + 1.0 + 299.0, None, None)
    do(plan, FIRST + 1.0 + 300.0, None, "tick")


def test_a_status_that_was_never_linked_because_the_tick_failed_is_linked_after_the_floor() -> None:
    plan = make()
    step = plan.next(FIRST, status())
    plan.failed(step, at=FIRST + 1.0)

    do(plan, FIRST + 1.0 + GAP - 1, status(), None)
    do(plan, FIRST + 1.0 + GAP, status(), "scan")


# --------------------------------------------------------------------------------------------- the tick and a running scan


def test_the_tick_waits_for_a_running_scan_and_runs_when_it_ends() -> None:
    plan = make()

    do(plan, FIRST, status(scanning=True), None)
    do(plan, FIRST + 5, status(scanning=True), None)
    do(plan, FIRST + 10, status(scanning=False, last="scan-2"), "tick")


def test_a_scan_that_never_ends_does_not_stop_the_tick_for_ever() -> None:
    plan = make()

    do(plan, FIRST, status(scanning=True), None)  # the tick is due from here
    do(plan, FIRST + LONG_SCAN - 1, status(scanning=True), None)
    do(plan, FIRST + LONG_SCAN, status(scanning=True), "tick")


# --------------------------------------------------------------------------------------------- a music server that cannot say


def test_a_music_server_that_cannot_say_gets_the_tick_and_nothing_else() -> None:
    plan = make()

    do(plan, FIRST, None, "tick")
    for at in (100.0, 200.0, 300.0):
        do(plan, at, None, None)
    do(plan, 21.0 + EVERY, None, "tick")


def test_a_status_that_says_neither_a_count_nor_a_time_never_asks_for_a_pass() -> None:
    plan = make()
    after_the_first_tick(plan, {"scanning": False})

    for at in (100.0, 500.0, 1000.0):
        do(plan, at, {"scanning": False}, None)


# --------------------------------------------------------------------------------------------- a person asks


def test_a_poke_runs_at_once_even_inside_the_floor() -> None:
    plan = make()
    after_the_first_tick(plan)
    do(plan, 300.0, status(count=101, last="scan-2"), "scan")

    plan.poke()
    step = plan.next(305.0, status(count=101, last="scan-2"))

    assert step.run == "poke"


def test_a_poke_waits_for_a_running_scan() -> None:
    plan = make()
    after_the_first_tick(plan)

    plan.poke()
    step = plan.next(305.0, status(scanning=True))

    assert step.run is None and step.wait_s == BUSY
    assert plan.next(310.0, status(scanning=False)).run == "poke", "it was kept, not lost, while the scan ran"
    assert plan.next(311.0, status(scanning=False)).run is None, "and it runs once"


def test_a_poke_runs_when_the_music_server_cannot_say() -> None:
    plan = make()

    plan.poke()
    assert plan.next(1.0, None).run == "poke"
