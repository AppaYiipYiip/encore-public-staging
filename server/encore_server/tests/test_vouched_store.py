"""The memory of a device the server already knows, KEPT across a restart (P3-34 slice 2a, the advisor's review).

A restart happens on every update and every crash, and used to clear the memory: a scripted guesser then refilled an account's limit within seconds of the server coming back, and the owner's
app, which the music server had accepted that morning, was the one that waited. The memory is now in the database (`login_vouch`, migration 0025): keyed digests and a name, never a token, a
salt or a password. Every write is a best effort and never refuses or delays the login being checked.
"""

from __future__ import annotations

import sqlite3

import httpx

from encore_server.auth import NavidromeVerifier, subsonic_token
from encore_server.db import Database
from encore_server.login_vouch import SqliteVouchStore
from tests.test_vouched_memory import DAY, Music, Rig


class StoreRig(Rig):
    """The same music server, a REAL store in a migrated database, and two clocks (the monotonic one the verifier counts with and the wall one the database is written with)."""

    def __init__(self, db: Database, **options: object) -> None:
        self.db = db
        self.wall = [1_700_000_000.0]
        self.now = [100.0]
        self.options = options
        self.music = Music()
        self.store = SqliteVouchStore(db)
        self.verifier = self.process()

    def process(self, **more: object) -> NavidromeVerifier:
        """A server process: a new verifier on the same database; the clocks are the test's, so a restart costs no time unless the test says."""
        options = {**self.options, **more}
        store = options.pop("store", self.store)
        return NavidromeVerifier(
            "http://music.invalid",
            client=httpx.Client(transport=httpx.MockTransport(self.music.handle)),
            clock=lambda: self.now[0],
            wall_clock=lambda: self.wall[0],
            store=store,  # type: ignore[arg-type]
            **options,  # type: ignore[arg-type]
        )

    def pass_time(self, seconds: float) -> None:
        self.now[0] += seconds
        self.wall[0] += seconds

    def rows(self) -> list[tuple[bytes, str, int]]:
        with self.db.read() as conn:
            return [(bytes(r["digest"]), r["name"], r["at"]) for r in conn.execute("SELECT digest, name, at FROM login_vouch")]


def test_a_vouched_login_is_written_and_a_new_process_knows_it(db: Database) -> None:
    rig = StoreRig(db)
    login = rig.login()
    assert rig.verifier.verify(*login)
    assert len(rig.rows()) == 1 and rig.rows()[0][1] == "marwa"

    after_a_restart = rig.process()

    assert after_a_restart.vouched(*login) is True, "the owner's app is a device the server knew, restart or not"
    assert after_a_restart.known_good(*login) is False, (
        "the short memory, which skips the music server's check, is NOT kept: the music server is asked again"
    )
    assert after_a_restart.vouched(*rig.login("marwa", password="not it")) is False


def test_the_key_of_the_digests_is_kept_so_a_digest_made_before_a_restart_is_the_one_made_after_it(db: Database) -> None:
    rig = StoreRig(db)
    rig.verifier.verify(*rig.login())
    first = rig.rows()[0][0]

    rig.process().verify(*rig.login())

    assert [row[0] for row in rig.rows()] == [first], "the same digest, one row"
    with db.read() as conn:
        assert conn.execute("SELECT 1 FROM setting WHERE key = 'login_vouch_key'").fetchone() is not None


def test_what_the_database_holds_is_a_digest_and_a_name_never_a_token_a_salt_or_a_password(db: Database) -> None:
    rig = StoreRig(db)
    user, token, salt = rig.login("marwa", salt="zz-a-visible-salt")
    assert rig.verifier.verify(user, token, salt)

    with db.read() as conn:
        dump = " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM login_vouch"))
        keyed = conn.execute("SELECT value FROM setting WHERE key = 'login_vouch_key'").fetchone()["value"]
    assert token not in dump and salt not in dump and "pw-marwa" not in dump
    assert all(len(digest) == 32 for digest, _, _ in rig.rows())
    assert keyed and token not in keyed


def test_a_restart_after_a_day_remembers_nothing_and_the_old_rows_are_deleted(db: Database) -> None:
    rig = StoreRig(db)
    login = rig.login()
    assert rig.verifier.verify(*login)

    rig.pass_time(DAY + 60)
    after = rig.process()

    assert after.vouched(*login) is False
    assert rig.rows() == [], "a table that only grew would keep every credential ever accepted"


def test_a_device_still_in_use_is_written_again_at_most_once_an_hour(db: Database) -> None:
    puts: list[int] = []

    class Spy(SqliteVouchStore):
        def put(self, digest: bytes, name: str, at_ms: int) -> None:
            puts.append(at_ms)
            super().put(digest, name, at_ms)

    rig = StoreRig(db)
    verifier = rig.process(store=Spy(db))
    login = rig.login()
    assert verifier.verify(*login)
    for _ in range(100):  # a call every few seconds for ten minutes
        rig.pass_time(5)
        assert verifier.known_good(*login) is True
    assert len(puts) == 1, "renewed in memory by every use, written once"

    rig.pass_time(3600)
    assert verifier.verify(*login) is True
    assert len(puts) == 2, "and once more when an hour has passed"


class BrokenStore:
    """A store that fails in every way: nothing it does may refuse or delay a login."""

    def key(self) -> bytes:
        raise sqlite3.OperationalError("database is locked")

    def load(self, oldest_ms: int) -> list[tuple[bytes, str, int]]:
        raise sqlite3.OperationalError("database is locked")

    def put(self, digest: bytes, name: str, at_ms: int) -> None:
        raise sqlite3.OperationalError("disk full")

    def drop(self, digest: bytes) -> None:
        raise sqlite3.OperationalError("disk full")

    def drop_name(self, name: str) -> None:
        raise sqlite3.OperationalError("disk full")


def test_a_store_that_cannot_be_read_leaves_a_memory_of_this_process_and_refuses_nothing() -> None:
    rig = Rig(store=BrokenStore())
    login = rig.login()

    assert rig.verifier.verify(*login) is True
    assert rig.verifier.vouched(*login) is True, "still remembered, in this process"
    rig.verifier.forget("marwa")
    assert rig.verifier.vouched(*login) is False


def test_a_store_that_cannot_be_written_refuses_nothing(db: Database) -> None:
    rig = StoreRig(db)
    verifier = rig.process(store=BrokenStoreThatReads(db))
    login = rig.login()

    assert verifier.verify(*login) is True
    assert verifier.vouched(*login) is True
    rig.music.passwords["marwa"] = "changed"
    rig.pass_time(700)
    assert verifier.verify(*login) is False, "and a refusal is still a refusal"


class BrokenStoreThatReads(SqliteVouchStore):
    """Reads fine, cannot write: the disk is full."""

    def put(self, digest: bytes, name: str, at_ms: int) -> None:
        raise sqlite3.OperationalError("disk full")

    def drop(self, digest: bytes) -> None:
        raise sqlite3.OperationalError("disk full")

    def drop_name(self, name: str) -> None:
        raise sqlite3.OperationalError("disk full")


def test_forgetting_a_person_and_a_later_refusal_delete_the_rows(db: Database) -> None:
    rig = StoreRig(db)
    owner, other = rig.login("marwa"), rig.login("nina")
    assert rig.verifier.verify(*owner) and rig.verifier.verify(*other)
    assert {name for _, name, _ in rig.rows()} == {"marwa", "nina"}

    rig.verifier.forget("Marwa")
    assert {name for _, name, _ in rig.rows()} == {"nina"}

    rig.music.passwords["nina"] = "changed"
    rig.pass_time(700)
    assert rig.verifier.verify(*other) is False
    assert rig.rows() == []
    assert rig.process().vouched(*owner) is False and rig.process().vouched(*other) is False


def test_one_name_cannot_push_another_out_of_the_memory(db: Database) -> None:
    """A member who sends the right password with a fresh salt on every call makes a new entry every time: at most so many are kept for a name, newest first, and the owner's stay."""
    rig = StoreRig(db, vouch_per_name=4, vouch_cap=10)
    owner = rig.login("marwa")
    assert rig.verifier.verify(*owner)
    for i in range(60):
        rig.pass_time(1)
        assert rig.verifier.verify(*rig.login("nina", salt=f"flood{i:04d}"))

    assert rig.verifier.vouched(*owner) is True, "the owner's is still there"
    assert sum(1 for _, name, _ in rig.rows() if name == "nina") == 4, "the flood is held to four, in the database too"
    assert rig.verifier.vouched(*rig.login("nina", salt="flood0059")) is True, "the newest of the flood is kept"
    assert rig.verifier.vouched(*rig.login("nina", salt="flood0000")) is False, "the oldest made room"


def test_the_global_cap_still_holds_for_many_names(db: Database) -> None:
    rig = StoreRig(db, vouch_cap=20)
    first = rig.login("marwa")
    assert rig.verifier.verify(*first)
    for i in range(40):
        rig.pass_time(1)
        name = f"member{i}"
        rig.music.passwords[name] = f"pw-{name}"
        assert rig.verifier.verify(name, subsonic_token(f"pw-{name}", "saltzzzz"), "saltzzzz")

    assert len(rig.rows()) <= 20 and len(rig.verifier._vouched) <= 20  # noqa: SLF001
    assert rig.verifier.vouched(*first) is False, "the oldest made room"
