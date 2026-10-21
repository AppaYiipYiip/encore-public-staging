"""The invite state machine (docs/35 section 3): single use, expiry, revoke, hashing, input checks, and a provisioner that fails.
Real sqlite files in a temp folder, a fake clock, a fake provisioner: no network, no Navidrome."""
import tempfile
import threading
import unittest
from pathlib import Path

from encore_people.invites import (INVITE_TTL_S, InviteError, Invites,
                                   ProvisionError, check_password, check_username)

NOW = 1_760_000_000.0


class FakeClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeProvisioner:
    def __init__(self) -> None:
        self.created: list[tuple[str, str]] = []
        self.fail: Exception | None = None
        self.taken: set[str] = set()

    def add_person(self, username: str, password: str) -> None:
        if self.fail:
            raise self.fail
        if username in self.taken:
            raise ProvisionError("that name is taken")
        self.created.append((username, password))
        self.taken.add(username)


class InviteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "people.db"
        self.clock = FakeClock()
        self.prov = FakeProvisioner()
        self.invites = Invites(self.db, provisioner=self.prov, clock=self.clock)
        self.addCleanup(self.invites.close)  # runs before the folder is removed (Windows keeps open files)

    # ------------------------------------------------------------ create / status
    def test_a_new_invite_has_a_long_random_code_and_is_valid(self) -> None:
        made = self.invites.create("owner")
        self.assertGreaterEqual(len(made.code), 22)
        self.assertRegex(made.code, r"^[A-Za-z0-9_-]+$")
        self.assertEqual(made.expires_at, NOW + INVITE_TTL_S)
        info = self.invites.lookup(made.code)
        self.assertIsNotNone(info)
        self.assertEqual(info.inviter, "owner")

    def test_two_invites_never_share_a_code(self) -> None:
        self.assertNotEqual(self.invites.create("owner").code, self.invites.create("owner").code)

    def test_the_code_itself_is_never_stored(self) -> None:
        made = self.invites.create("owner")
        raw = self.db.read_bytes()
        self.assertNotIn(made.code.encode(), raw, "only a hash of the code may be on disk")

    def test_an_unknown_code_is_not_valid(self) -> None:
        self.assertIsNone(self.invites.lookup("definitely-not-a-code-0000000000"))
        self.assertIsNone(self.invites.lookup(""))
        self.assertIsNone(self.invites.lookup("x" * 5000))

    # ------------------------------------------------------------ redeem
    def test_redeeming_creates_the_person_once(self) -> None:
        made = self.invites.create("owner")
        who = self.invites.redeem(made.code, "sara", "a long enough password")
        self.assertEqual(who, "sara")
        self.assertEqual(self.prov.created, [("sara", "a long enough password")])

    def test_a_code_works_only_once(self) -> None:
        made = self.invites.create("owner")
        self.invites.redeem(made.code, "sara", "a long enough password")
        with self.assertRaises(InviteError):
            self.invites.redeem(made.code, "ben", "another long password")
        self.assertEqual(len(self.prov.created), 1)
        self.assertIsNone(self.invites.lookup(made.code), "a used invite is not valid any more")

    def test_an_expired_code_is_refused_and_looks_like_an_unknown_one(self) -> None:
        made = self.invites.create("owner")
        self.clock.advance(INVITE_TTL_S + 1)
        self.assertIsNone(self.invites.lookup(made.code))
        with self.assertRaises(InviteError) as cm:
            self.invites.redeem(made.code, "sara", "a long enough password")
        with self.assertRaises(InviteError) as unknown:
            self.invites.redeem("nope" * 8, "sara", "a long enough password")
        self.assertEqual(str(cm.exception), str(unknown.exception), "a wrong and an expired code must look the same")
        self.assertEqual(self.prov.created, [])

    def test_the_last_second_still_counts(self) -> None:
        made = self.invites.create("owner")
        self.clock.advance(INVITE_TTL_S - 1)
        self.assertEqual(self.invites.redeem(made.code, "sara", "a long enough password"), "sara")

    def test_a_revoked_code_is_refused(self) -> None:
        made = self.invites.create("owner")
        self.assertTrue(self.invites.revoke(made.id))
        self.assertIsNone(self.invites.lookup(made.code))
        with self.assertRaises(InviteError):
            self.invites.redeem(made.code, "sara", "a long enough password")

    def test_bad_input_does_not_use_up_the_code(self) -> None:
        made = self.invites.create("owner")
        for name, password in (("", "a long enough password"), ("Sa ra", "a long enough password"),
                               ("sara", "short"), ("admin", "a long enough password")):
            with self.assertRaises(InviteError, msg=f"{name!r}/{password!r}"):
                self.invites.redeem(made.code, name, password)
        self.assertIsNotNone(self.invites.lookup(made.code), "a typo must not burn the invite")
        self.assertEqual(self.invites.redeem(made.code, "sara", "a long enough password"), "sara")

    def test_a_name_that_is_taken_does_not_use_up_the_code(self) -> None:
        self.prov.taken.add("sara")
        made = self.invites.create("owner")
        with self.assertRaises(InviteError) as cm:
            self.invites.redeem(made.code, "sara", "a long enough password")
        self.assertIn("taken", str(cm.exception))
        self.assertEqual(self.invites.redeem(made.code, "sara2", "a long enough password"), "sara2")

    def test_a_failing_server_does_not_use_up_the_code(self) -> None:
        made = self.invites.create("owner")
        self.prov.fail = RuntimeError("the music server is down")
        with self.assertLogs("encore_people.invites", level="ERROR"), self.assertRaises(InviteError) as cm:
            self.invites.redeem(made.code, "sara", "a long enough password")
        self.assertNotIn("down", str(cm.exception), "internal details must not reach the friend")
        self.prov.fail = None
        self.assertEqual(self.invites.redeem(made.code, "sara", "a long enough password"), "sara")

    def test_two_people_racing_for_one_code_make_exactly_one_account(self) -> None:
        made = self.invites.create("owner")
        results: list[object] = []
        gate = threading.Barrier(2)

        def go(name: str) -> None:
            gate.wait()
            try:
                results.append(self.invites.redeem(made.code, name, "a long enough password"))
            except InviteError as error:
                results.append(error)

        threads = [threading.Thread(target=go, args=(n,)) for n in ("sara", "ben")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(self.prov.created), 1, results)
        self.assertEqual(sum(isinstance(r, str) for r in results), 1)

    # ------------------------------------------------------------ list
    def test_the_list_shows_state_but_never_a_code(self) -> None:
        a = self.invites.create("owner")
        b = self.invites.create("owner")
        self.invites.redeem(a.code, "sara", "a long enough password")
        self.invites.revoke(b.id)
        c = self.invites.create("owner")
        rows = {r.id: r for r in self.invites.list()}
        self.assertEqual(rows[a.id].state, "used")
        self.assertEqual(rows[a.id].redeemed_by, "sara")
        self.assertEqual(rows[b.id].state, "revoked")
        self.assertEqual(rows[c.id].state, "open")
        self.assertFalse(any(hasattr(r, "code") for r in rows.values()))
        self.clock.advance(INVITE_TTL_S + 5)
        self.assertEqual({r.id: r.state for r in self.invites.list()}[c.id], "expired")

    def test_state_survives_a_restart(self) -> None:
        made = self.invites.create("owner")
        again = Invites(self.db, provisioner=self.prov, clock=self.clock)
        self.addCleanup(again.close)
        self.assertIsNotNone(again.lookup(made.code))
        again.redeem(made.code, "sara", "a long enough password")
        self.assertIsNone(self.invites.lookup(made.code))


class InputRulesTest(unittest.TestCase):
    def test_usernames(self) -> None:
        for good in ("sara", "ben.k", "a-b_c", "abc", "x" * 32, "user42"):
            self.assertIsNone(check_username(good), good)
        # "42sara": the account tool (encore_user.py) wants a letter first, so a name it would refuse must be refused here, before an invitation is used.
        for bad in ("", "ab", "x" * 33, "Sara", "sa ra", "sara!", "../etc", "_shared", "admin", "root", "owner", "everyone", "42sara", "-sara", ".sara"):
            self.assertIsNotNone(check_username(bad), bad)

    def test_passwords(self) -> None:
        self.assertIsNone(check_password("a long enough password"))
        self.assertIsNone(check_password("12345678"))
        for bad in ("", "short", "x" * 7, "x" * 201):
            self.assertIsNotNone(check_password(bad), bad)


if __name__ == "__main__":
    unittest.main()
