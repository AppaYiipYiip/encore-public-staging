"""P3-34 slice 2d: wrong guesses are counted when the music server has answered, so a burst of concurrent ones used to pass the limit before any was counted.

`LoginGuard.refuse` looks at the wrong answers counted so far, and `failed` counts one only after the music server answered. N logins sent at once all look at zero. A guess that is about to be
checked now also reserves a slot (`LoginGuard.begin`): a ceiling on how many may be in flight at once for a name from an address, for an address and for a name, set far above what an app does
in parallel (so a fresh-salt app loading a screen of covers is not held up), and given back when the check is over, on every path.
"""

from __future__ import annotations

import pytest

from encore_server.accounts import Limiter, LoginGuard
from encore_server.errors import ApiError


def test_the_limiter_counts_what_is_in_flight_and_gives_it_back() -> None:
    limiter = Limiter()

    assert limiter.reserve("k", 2) and limiter.reserve("k", 2)
    assert not limiter.reserve("k", 2), "at the ceiling"
    limiter.release("k")
    assert limiter.reserve("k", 2), "one was given back"
    limiter.release("k")
    limiter.release("k")
    assert limiter.in_flight() == 0, "nothing is left behind"


def test_a_key_never_goes_below_nothing_in_flight() -> None:
    limiter = Limiter()

    limiter.release("never-reserved")

    assert limiter.in_flight() == 0 and limiter.reserve("never-reserved", 1)


def test_an_attempt_past_the_pair_ceiling_is_refused_and_nothing_stays_reserved_by_the_refusal() -> None:
    limiter = Limiter()
    guard = LoginGuard(limiter)
    held = [guard.begin("marwa", "10.0.0.1") for _ in range(LoginGuard.IN_FLIGHT_PAIR)]
    before = limiter.in_flight()

    with pytest.raises(ApiError) as refused:
        guard.begin("marwa", "10.0.0.1")

    assert refused.value.code == "rate_limited"
    assert limiter.in_flight() == before, "the refusal gave back the slots it had taken on its way"
    for attempt in held:
        attempt.release()
    assert limiter.in_flight() == 0
    guard.begin("marwa", "10.0.0.1").release()


def test_the_address_and_the_account_have_their_own_ceilings() -> None:
    limiter = Limiter()
    guard = LoginGuard(limiter)
    one_address = [guard.begin(f"name{i}", "10.0.0.1") for i in range(LoginGuard.IN_FLIGHT_ADDRESS)]
    with pytest.raises(ApiError):
        guard.begin("another", "10.0.0.1")
    for attempt in one_address:
        attempt.release()

    many_addresses = [guard.begin("marwa", f"10.0.{i // 200}.{i % 200}") for i in range(LoginGuard.IN_FLIGHT_ACCOUNT)]
    with pytest.raises(ApiError):
        guard.begin("marwa", "192.168.1.1")
    for attempt in many_addresses:
        attempt.release()

    assert limiter.in_flight() == 0


def test_a_device_the_server_knows_is_never_held_by_what_is_in_flight() -> None:
    limiter = Limiter()
    guard = LoginGuard(limiter)
    held = [guard.begin("marwa", "10.0.0.1") for _ in range(LoginGuard.IN_FLIGHT_PAIR)]

    for _ in range(50):
        guard.begin("marwa", "10.0.0.1", vouched=True).release()

    assert limiter.in_flight() == 3 * LoginGuard.IN_FLIGHT_PAIR, "a known device reserves nothing"
    for attempt in held:
        attempt.release()


def test_failures_still_refuse_as_before() -> None:
    guard = LoginGuard(Limiter())
    for _ in range(LoginGuard.PAIR[0]):
        guard.failed("marwa", "10.0.0.1")

    with pytest.raises(ApiError) as refused:
        guard.begin("marwa", "10.0.0.1")

    assert refused.value.code == "rate_limited"
    guard.begin("marwa", "10.0.0.2").release()


def test_the_with_form_gives_the_slot_back_on_every_way_out() -> None:
    limiter = Limiter()
    guard = LoginGuard(limiter)

    with guard.begin("marwa", "10.0.0.1"):
        assert limiter.in_flight() == 3
    assert limiter.in_flight() == 0

    with pytest.raises(RuntimeError), guard.begin("marwa", "10.0.0.1"):
        raise RuntimeError("the music server fell over")
    assert limiter.in_flight() == 0

    attempt = guard.begin("marwa", "10.0.0.1")
    attempt.release()
    attempt.release()  # twice is once
    assert limiter.in_flight() == 0


def test_the_ceilings_are_far_above_what_one_app_does_at_once_and_far_below_a_burst() -> None:
    """A phone loads a screen of covers (a dozen or two) and Dart, OkHttp and the browsers keep 5 to 10 connections to a host: 16 for a name from an address is headroom for all of them, and a
    script that sends sixty at once is held to those sixteen instead of sixty."""
    assert 12 <= LoginGuard.IN_FLIGHT_PAIR <= 32
    assert LoginGuard.IN_FLIGHT_PAIR < LoginGuard.IN_FLIGHT_ACCOUNT < LoginGuard.IN_FLIGHT_ADDRESS
