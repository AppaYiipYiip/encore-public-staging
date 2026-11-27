"""The verifier's memory of a device it already knows (P3-34 slice 2a): `vouched`, apart from the ten-minute `known_good`.

`known_good` says "the music server said yes to exactly these credentials a moment ago": it lets a request skip the music server's own check. `vouched` is the longer memory (a day) that
lets a login skip only the REFUSALS of the guess limits, never the check: it is what keeps the owner's app answering while a stranger's guesses are being slowed.
"""

from __future__ import annotations

import httpx
import pytest

from encore_server.auth import NavidromeVerifier, subsonic_token

DAY = 24 * 3600
TEN_MINUTES = 600


class Music:
    """The music server's `ping` as far as a login goes: the right password gives `ok`, any other answers 40."""

    def __init__(self) -> None:
        self.passwords = {"marwa": "pw-marwa", "nina": "pw-nina"}
        self.pings = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.pings += 1
        query = request.url.params
        user, token, salt = query.get("u", ""), query.get("t", ""), query.get("s", "")
        password = self.passwords.get(user)
        if password is not None and subsonic_token(password, salt) == token:
            return httpx.Response(200, json={"subsonic-response": {"status": "ok"}})
        return httpx.Response(200, json={"subsonic-response": {"status": "failed", "error": {"code": 40}}})


class Rig:
    def __init__(self, **options: object) -> None:
        self.now = [100.0]
        self.music = Music()
        self.verifier = NavidromeVerifier(
            "http://music.invalid",
            client=httpx.Client(transport=httpx.MockTransport(self.music.handle)),
            clock=lambda: self.now[0],
            **options,  # type: ignore[arg-type]
        )

    def login(self, user: str = "marwa", password: str | None = None, salt: str = "salt1234") -> tuple[str, str, str]:
        return user, subsonic_token(password or f"pw-{user}", salt), salt


def accept(verifier: NavidromeVerifier, login: tuple[str, str, str]) -> bool:
    """Two accepted calls: a login is remembered on its SECOND sighting (a credential with a fresh salt on every call never is; the review of 2b)."""
    return bool(verifier.verify(*login) and verifier.verify(*login))


def test_a_login_the_music_server_accepted_is_vouched_for_a_day_and_known_good_for_ten_minutes() -> None:
    rig = Rig()
    login = rig.login()
    assert rig.verifier.vouched(*login) is False and rig.verifier.known_good(*login) is False, (
        "nothing is known before it was accepted"
    )

    assert rig.verifier.verify(*login)

    assert rig.verifier.vouched(*login) is False, (
        "the first accepted call is seen once: a fresh salt every call would never be remembered"
    )
    assert rig.verifier.known_good(*login) is True
    assert rig.verifier.vouched(*login) is True, "the second sighting is remembered"
    rig.now[0] += TEN_MINUTES + 1
    assert rig.verifier.known_good(*login) is False, "the short memory, which skips the music server's check, ran out"
    assert rig.verifier.vouched(*login) is True, "the long one, which only skips refusals, did not"
    rig.now[0] += DAY
    assert rig.verifier.vouched(*login) is False


def test_a_credential_the_music_server_refused_is_never_vouched() -> None:
    rig = Rig()
    wrong = rig.login(password="not the password")

    assert rig.verifier.verify(*wrong) is False
    assert rig.verifier.vouched(*wrong) is False


def test_a_vouched_credential_that_the_music_server_now_refuses_loses_its_exemption() -> None:
    """The password was changed at the music server without Encore hearing of it: the next check says no, and the old credential is a guess like any other."""
    rig = Rig()
    login = rig.login()
    assert accept(rig.verifier, login)
    rig.now[0] += TEN_MINUTES + 1
    rig.music.passwords["marwa"] = "a new password"

    assert rig.verifier.verify(*login) is False
    assert rig.verifier.vouched(*login) is False


def test_forgetting_a_person_drops_what_was_vouched_for_them_and_nobody_else() -> None:
    rig = Rig()
    owner, other = rig.login("marwa"), rig.login("nina")
    assert accept(rig.verifier, owner) and accept(rig.verifier, other)

    rig.verifier.forget("MARWA")

    assert rig.verifier.vouched(*owner) is False and rig.verifier.known_good(*owner) is False
    assert rig.verifier.vouched(*other) is True


def test_a_device_that_keeps_being_known_stays_vouched_beyond_a_day() -> None:
    """Each use of a remembered yes renews the day: an app that talks every few minutes never falls out of the memory while a stranger guesses."""
    rig = Rig()
    login = rig.login()
    assert accept(rig.verifier, login)
    for _ in range(30 * 12):  # thirty hours, a call every five minutes
        rig.now[0] += 300
        assert rig.verifier.known_good(*login) or rig.verifier.verify(*login)
    assert rig.verifier.vouched(*login) is True


def test_the_memory_keeps_no_raw_token_no_salt_and_no_name() -> None:
    rig = Rig()
    user, token, salt = rig.login("marwa", salt="zz-a-visible-salt")
    assert rig.verifier.verify(user, token, salt)

    held = repr(rig.verifier._vouched) + repr(rig.verifier._vouch_key)  # noqa: SLF001 - what the long memory holds IS the point (the ten-minute `_ok` has always held the triple, in memory)
    assert token not in held and salt not in held, "no raw credential in the memory"
    assert all(isinstance(key, bytes) and len(key) == 32 for key in rig.verifier._vouched), "a keyed digest, nothing readable"  # noqa: SLF001


def test_two_processes_do_not_share_a_digest() -> None:
    """The key is made per process: a memory of digests is of no use outside it."""
    first, second = Rig(), Rig()
    login = first.login()
    assert accept(first.verifier, login) and accept(second.verifier, login)

    assert set(first.verifier._vouched) != set(second.verifier._vouched)  # noqa: SLF001


def test_one_name_keeps_only_its_newest_logins() -> None:
    rig = Rig(vouch_per_name=5)
    logins = [rig.login("marwa", salt=f"salt{i:05d}") for i in range(80)]
    for login in logins:
        rig.now[0] += 1
        assert accept(rig.verifier, login)

    assert len(rig.verifier._vouched) == 5  # noqa: SLF001
    assert rig.verifier.vouched(*logins[-1]) is True, "the newest is kept"
    assert rig.verifier.vouched(*logins[0]) is False, "the oldest made room"


def test_a_music_server_that_gives_no_answer_vouches_for_nothing_and_forgets_nothing() -> None:
    rig = Rig()
    login = rig.login()
    assert accept(rig.verifier, login)
    rig.now[0] += TEN_MINUTES + 1
    rig.verifier._client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))  # noqa: SLF001
    from encore_server.auth import MusicServerUnavailable

    with pytest.raises(MusicServerUnavailable):
        rig.verifier.verify(*login)

    assert rig.verifier.vouched(*login) is True, "an outage says nothing about the password"


# ------------------------------------------------------------------------------------------------------------------------------ the second sighting (review of 2b)


def test_a_login_with_a_fresh_salt_on_every_call_is_never_remembered_and_cannot_push_the_owners_out() -> None:
    """An app that follows the Subsonic documentation makes a new salt for every call. Remembering each would be a digest, a database write and an eviction a call, and two hundred of them
    under the owner's name would push the owner's own entry out. A credential is remembered on its SECOND sighting; one that never repeats never is."""
    rig = Rig(vouch_per_name=32)
    owner = rig.login("marwa")
    assert accept(rig.verifier, owner)

    for i in range(200):
        rig.now[0] += 1
        assert rig.verifier.verify(*rig.login("marwa", salt=f"fresh{i:05d}")) is True

    assert rig.verifier.vouched(*owner) is True, "the owner's is still there"
    assert len(rig.verifier._vouched) == 1, "and nothing was added: every one of the two hundred was seen once"  # noqa: SLF001


def test_the_second_sighting_may_come_through_either_door_and_a_day_apart_counts_as_a_first() -> None:
    rig = Rig()
    login = rig.login()

    assert rig.verifier.verify(*login) and rig.verifier.vouched(*login) is False
    rig.verifier.note_accepted(*login)  # the home door saw the music server accept it again
    assert rig.verifier.vouched(*login) is True

    other = rig.login("nina")
    assert rig.verifier.verify(*other)
    rig.now[0] += DAY + 1
    rig.verifier.note_accepted(*other)  # a day later: the first sighting has expired, so this is a first again
    assert rig.verifier.vouched(*other) is False


def test_the_logins_seen_once_are_held_in_a_bounded_memory_only() -> None:
    from encore_server import auth

    rig = Rig()
    for i in range(auth.SEEN_ONCE_CAP + 50):
        rig.verifier.note_accepted("flood", f"{i:032x}", "saltaaaa")

    assert len(rig.verifier._seen_once) <= auth.SEEN_ONCE_CAP  # noqa: SLF001
    assert len(rig.verifier._vouched) == 0  # noqa: SLF001
