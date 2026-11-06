"""The one place background work is queued and run (docs/04 section 10, rules 1 to 5).

* **Single flight.** One active item per kind and song, however many people want it: a second request joins the first.
* **Priorities, strictly in this order:** play, prepare, download, match, keep, measure. A tap on a song whose keep is queued
  promotes it to the front; a whole download asked for at once (a playlist, the liked songs, a saved release, Retry) promotes its songs
  to the level of `download`, behind a tap and ahead of every import and other background work (`PROMOTE_ONE`, `PROMOTE_MANY`).
* **Fair share inside a priority:** the person who was served longest ago goes next, so a 2,000-song import cannot starve a friend's
  20-song import.
* **Two pools.** `interactive` (play, prepare, download) never waits behind `background` (match, keep, measure).
* **Resumes.** Items live in the database; one that was running when the server stopped is queued again at the next start.
* **Stop.** Cancelling a person's work removes them from what they asked for; an item somebody else also wants keeps going for them.

A handler raises [Retry] for trouble that may pass (YouTube pushed back, a disk that is full for now) and [GiveUp] for what will not
change (the song is gone). Anything else is retried with growing pauses, a few times, and then recorded as failed.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .db import Database
from .ids import new_id

log = logging.getLogger("encore_server.scheduler")

#: Lower runs first.
PRIORITY = {"play": 0, "prepare": 1, "download": 2, "match": 3, "keep": 4, "measure": 5}
#: How far a keep is promoted when somebody is waiting for it. ONE song a person is looking at (a tap) goes ahead of everything. A WHOLE download asked
#: for at once (a playlist, the liked songs, a saved release, Retry: up to hundreds of songs) goes ahead of other people's imports and background work but
#: BEHIND a tap: the claim looks at the first 200 items by (priority, age) before it shares the turn (B-39), so a download promoted to the level of a tap
#: would stand in front of the next person's tap for as long as it lasts. A promotion only ever raises: a song somebody tapped stays where the tap put it.
#: Only a tap also ends a pause before a retry; a download never does (`promote_many`).
PROMOTE_ONE = 0
PROMOTE_MANY = PRIORITY["download"]
POOL = {
    "play": "interactive",
    "prepare": "interactive",
    "download": "interactive",
    "match": "background",
    "keep": "background",
    "measure": "background",
}
#: Pauses before the next try of an item that failed for a reason that may pass; after the last one it is recorded as failed.
BACKOFF_S = (30.0, 120.0, 600.0, 3600.0)


class Retry(Exception):
    """Not now (YouTube pushed back, the disk is full for the moment): try again after [after_s]. This never counts towards giving up: the
    try that asked for it is given back, so a long wait does not use up the tries a later failure gets (B7). With no [after_s] it is a failure
    that may pass: the scheduler's own pauses, and after the last one it is recorded as failed with the reason."""

    def __init__(self, reason: str, after_s: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.after_s = after_s


class GiveUp(Exception):
    """This will not work however often it is tried; [reason] is kept as the item's error."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class WorkItem:
    id: str
    kind: str
    ref: str
    priority: int
    attempts: int
    persons: tuple[str, ...]


Handler = Callable[[WorkItem], None]

#: The songs somebody still has: liked, in a playlist that exists, or in a saved release (the same holders `library.touch_ref_holders` tells).
_HELD = (
    "SELECT target FROM library_item WHERE kind = 'like'"
    " UNION SELECT e.ref FROM playlist_entry e JOIN playlist p ON p.id = e.playlist WHERE e.deleted_at IS NULL AND p.deleted_at IS NULL"
    " UNION SELECT ref FROM saved_album_ref"
)


class Scheduler:
    def __init__(
        self,
        db: Database,
        handlers: dict[str, Handler],
        *,
        workers: dict[str, int] | None = None,
        clock: Callable[[], float] = time.time,
        backoff_s: tuple[float, ...] = BACKOFF_S,
        keep_done_s: float = 7 * 24 * 3600,
    ) -> None:
        self._db = db
        self._handlers = handlers
        self._workers = {"interactive": 2, "background": 2, **(workers or {})}
        self._clock = clock
        self._backoff = backoff_s
        self._keep_done_s = keep_done_s
        self._wake = threading.Condition()
        self._stopping = False
        self._threads: list[threading.Thread] = []
        #: When each person was last given a turn (fair share). In memory: after a restart everybody starts equal.
        self._served: dict[str, float] = {}
        self._turn = 0
        self._cancelled: set[str] = set()

    def running(self) -> int:
        """How many pieces of work are being done this moment (the server is not quiet while any is)."""
        with self._db.read() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM work_item WHERE state = 'running'").fetchone()["n"])

    # ------------------------------------------------------------------ asking for work

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def submit(self, kind: str, ref: str, person: str | None, *, conn: sqlite3.Connection | None = None) -> str:
        """Queues the work (or joins the same work already queued or running) and returns its id.

        Passing [conn] makes the request part of the caller's transaction: a like and its keep job are one write."""
        if kind not in PRIORITY:
            raise ValueError(f"unknown kind of work {kind!r}")
        if conn is None:
            with self._db.tx() as own:
                item = self._submit(own, kind, ref, person)
        else:
            item = self._submit(conn, kind, ref, person)
        with self._wake:
            self._wake.notify_all()
        return item

    def _submit(self, conn: sqlite3.Connection, kind: str, ref: str, person: str | None) -> str:
        now = self._now_ms()
        row = conn.execute(
            "SELECT id FROM work_item WHERE kind = ? AND ref = ? AND state IN ('queued', 'running')", (kind, ref)
        ).fetchone()
        if row is not None:
            item = str(row["id"])
        else:
            item = new_id("wk")
            conn.execute(
                "INSERT INTO work_item (id, kind, ref, priority, next_try_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (item, kind, ref, PRIORITY[kind], now, now, now),
            )
        if person is not None:
            conn.execute("INSERT OR IGNORE INTO work_item_person (item, person) VALUES (?, ?)", (item, person))
        return item

    def promote(self, kind: str, ref: str) -> bool:
        """A tap: someone is waiting for this one song now. It jumps to the front of its pool and any pause before a retry ends, because the wait
        that counts is the one of the person looking at it."""
        now = self._now_ms()
        with self._db.tx() as conn:
            changed = conn.execute(
                "UPDATE work_item SET priority = MIN(priority, ?), next_try_at = MIN(next_try_at, ?), updated_at = ? WHERE kind = ? AND ref = ? AND state = 'queued'",
                (PROMOTE_ONE, now, now, kind, ref),
            ).rowcount
        with self._wake:
            self._wake.notify_all()
        return bool(changed)

    def promote_many(self, kind: str, ref_ids: list[str], *, priority: int) -> int:
        """A whole download is wanted: what waits in the queue moves up to [priority], in one write. **Only the priority**: a pause before a retry is not
        ended (a phone says what it wants again at every connection, and ending the scheduler's back-off or YouTube's rest each time would try the songs
        again and again), and a song that is already there changes nothing, not even `updated_at` (a repeated ask must not make every watcher recount).
        Returns how many songs moved."""
        wanted = list(dict.fromkeys(ref_ids))
        if not wanted:
            return 0
        now = self._now_ms()
        changed = 0
        with self._db.tx() as conn:
            for start in range(0, len(wanted), 400):
                chunk = wanted[start : start + 400]
                marks = ",".join("?" for _ in chunk)
                changed += conn.execute(
                    "UPDATE work_item SET priority = ?, updated_at = ?"  # noqa: S608 - placeholders only
                    f" WHERE kind = ? AND state = 'queued' AND priority > ? AND ref IN ({marks})",
                    (priority, now, kind, priority, *chunk),
                ).rowcount
        if changed:
            with self._wake:
                self._wake.notify_all()
        return changed

    def cancel_person(self, person: str, kind: str | None = None) -> int:
        """Stop: this person no longer wants their queued work. What nobody else wants is cancelled (a running one at its next check);
        what somebody else also wants carries on for them. Returns the number of items cancelled."""
        cancelled = 0
        with self._db.tx() as conn:
            items = conn.execute(
                "SELECT i.id, i.state FROM work_item i JOIN work_item_person p ON p.item = i.id"
                " WHERE p.person = ? AND i.state IN ('queued', 'running') AND (? IS NULL OR i.kind = ?)",
                (person, kind, kind),
            ).fetchall()
            for item in items:
                cancelled += self._release(conn, item["id"], item["state"], person)
        return cancelled

    def cancel_refs(self, person: str, ref_ids: list[str], *, kinds: tuple[str, ...]) -> int:
        """Stop for part of a person's work: [kinds] of work on these songs. Same rule as [cancel_person]: only what nobody else wants
        is cancelled."""
        cancelled = 0
        with self._db.tx() as conn:
            for start in range(0, len(ref_ids), 400):
                chunk = ref_ids[start : start + 400]
                refs_in = ",".join("?" for _ in chunk)
                kinds_in = ",".join("?" for _ in kinds)
                items = conn.execute(
                    "SELECT i.id, i.state FROM work_item i JOIN work_item_person p ON p.item = i.id"  # noqa: S608 - only placeholders are formatted in
                    f" WHERE p.person = ? AND i.state IN ('queued', 'running') AND i.ref IN ({refs_in}) AND i.kind IN ({kinds_in})",
                    (person, *chunk, *kinds),
                ).fetchall()
                for item in items:
                    cancelled += self._release(conn, item["id"], item["state"], person)
        return cancelled

    def _release(self, conn: sqlite3.Connection, item_id: str, state: str, person: str) -> int:
        conn.execute("DELETE FROM work_item_person WHERE item = ? AND person = ?", (item_id, person))
        if conn.execute("SELECT 1 FROM work_item_person WHERE item = ?", (item_id,)).fetchone() is not None:
            return 0
        conn.execute("UPDATE work_item SET state = 'cancelled', updated_at = ? WHERE id = ?", (self._now_ms(), item_id))
        if state == "running":
            self._cancelled.add(item_id)
        return 1

    def handles(self, kind: str) -> bool:
        """Whether something here does this kind of work (a request for work nobody does would sit in the queue for ever)."""
        return kind in self._handlers

    def is_cancelled(self, item: WorkItem) -> bool:
        """For a long handler to ask between steps: has everybody who wanted this pressed Stop?"""
        return item.id in self._cancelled

    # ------------------------------------------------------------------ looking at the queue

    def counts(self) -> dict[str, dict[str, int]]:
        """How many items are in each state, per kind (for the admin page and for tests)."""
        out: dict[str, dict[str, int]] = {}
        with self._db.read() as conn:
            for row in conn.execute("SELECT kind, state, COUNT(*) AS n FROM work_item GROUP BY kind, state"):
                out.setdefault(row["kind"], {})[row["state"]] = row["n"]
        return out

    def state_of(self, kind: str, ref: str) -> dict[str, object] | None:
        """The newest item for this kind and song: its state, tries and last error."""
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT id, state, attempts, error, next_try_at FROM work_item WHERE kind = ? AND ref = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (kind, ref),
            ).fetchone()
        return dict(row) if row is not None else None

    def activity(self, kind: str) -> tuple[int, int]:
        """`(how many items of this kind, when one last changed)`: two numbers that differ whenever anything of this kind was queued, started, finished,
        failed, cancelled or promoted. A watcher compares them to know whether a recount can give a new answer, without recounting."""
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(MAX(updated_at), 0) AS at FROM work_item WHERE kind = ?", (kind,)
            ).fetchone()
        return int(row["n"]), int(row["at"])

    def states_of(self, kind: str, ref_ids: list[str]) -> dict[str, dict[str, object]]:
        """[state_of] for many songs in a few queries: the newest item of this kind for each song that has one (a song with none is absent).
        This is what a phone asks for to show how a 200-song download is going, so it must not cost one query per song."""
        out: dict[str, dict[str, object]] = {}
        wanted = list(dict.fromkeys(ref_ids))
        with self._db.read() as conn:
            for start in range(0, len(wanted), 400):
                chunk = wanted[start : start + 400]
                marks = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    "SELECT id, ref, state, attempts, error, next_try_at FROM work_item"  # noqa: S608 - only placeholders are formatted in
                    f" WHERE kind = ? AND ref IN ({marks}) ORDER BY created_at, rowid",
                    (kind, *chunk),
                ).fetchall()
                for row in rows:  # oldest first, so the newest overwrites
                    out[row["ref"]] = dict(row)
        return out

    # ------------------------------------------------------------------ running it

    def recover(self) -> int:
        """At start: what was running when the server stopped goes back in the queue; old finished items are forgotten."""
        now = self._now_ms()
        with self._db.tx() as conn:
            back = conn.execute("UPDATE work_item SET state = 'queued', updated_at = ? WHERE state = 'running'", (now,)).rowcount
            conn.execute(
                "DELETE FROM work_item WHERE state IN ('done', 'failed', 'cancelled') AND updated_at < ?"
                # A failed keep of a song somebody still has (liked, in a playlist, in a saved release) stays: it is the reason a phone shows
                # for "3 songs did not come", and forgetting it after a week would turn that into "not fetched yet" with no cause.
                " AND NOT (state = 'failed' AND kind = 'keep' AND ref IN (" + _HELD + "))",
                (now - int(self._keep_done_s * 1000),),
            )
        return back

    def _claim(self, pool: str) -> WorkItem | None:
        """The next item for this pool, or none: best priority first, then the person served longest ago."""
        kinds = [k for k, p in POOL.items() if p == pool and k in self._handlers]
        if not kinds:
            return None
        marks = ",".join("?" for _ in kinds)
        now = self._now_ms()
        with self._db.tx() as conn:
            rows = conn.execute(
                f"SELECT i.id, i.kind, i.ref, i.priority, i.attempts, i.created_at,"  # noqa: S608 - only placeholders are formatted in
                f" (SELECT group_concat(person) FROM work_item_person WHERE item = i.id) AS persons"
                f" FROM work_item i WHERE i.state = 'queued' AND i.next_try_at <= ? AND i.kind IN ({marks})"
                f" ORDER BY i.priority, i.created_at LIMIT 200",
                (now, *kinds),
            ).fetchall()
            if not rows:
                return None
            best = rows[0]["priority"]
            level = [r for r in rows if r["priority"] == best]

            def turn(row: sqlite3.Row) -> tuple[float, int]:
                persons = [p for p in (row["persons"] or "").split(",") if p]
                # An item several people want is served on the turn of whoever has waited longest.
                last = min((self._served.get(p, 0.0) for p in persons), default=0.0)
                return last, row["created_at"]

            chosen = min(level, key=turn)
            conn.execute(
                "UPDATE work_item SET state = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?",
                (now, chosen["id"]),
            )
        persons = tuple(p for p in (chosen["persons"] or "").split(",") if p)
        self._turn += 1
        for person in persons:
            self._served[person] = float(self._turn)
        return WorkItem(chosen["id"], chosen["kind"], chosen["ref"], chosen["priority"], chosen["attempts"] + 1, persons)

    def run_one(self, pool: str) -> bool:
        """Takes the next item of the pool and runs it here. `False` when there was nothing to do (tests drive the scheduler this way)."""
        item = self._claim(pool)
        if item is None:
            return False
        self._run(item)
        return True

    def drain(self, pool: str | None = None, *, limit: int = 1000) -> int:
        """Runs everything that is due, here and now (tests, and the migration tool)."""
        ran = 0
        pools = [pool] if pool else ["interactive", "background"]
        while ran < limit and any(self.run_one(p) for p in pools):
            ran += 1
        return ran

    def _run(self, item: WorkItem) -> None:
        handler = self._handlers[item.kind]
        outcome: tuple[str, str | None, float | None] = ("done", None, None)
        try:
            handler(item)
        except Retry as retry:
            outcome = ("retry", retry.reason, retry.after_s)
        except GiveUp as gone:
            outcome = ("failed", gone.reason, None)
        except Exception as error:  # noqa: BLE001 - a handler's bug must not stop the worker; it is logged and retried
            log.exception("work %s %s for %s failed", item.kind, item.id, item.ref)
            outcome = ("retry", f"{type(error).__name__}: {error}"[:300], None)
        self._finish(item, *outcome)

    def _finish(self, item: WorkItem, result: str, error: str | None, after_s: float | None) -> None:
        now = self._now_ms()
        with self._db.tx() as conn:
            row = conn.execute("SELECT state FROM work_item WHERE id = ?", (item.id,)).fetchone()
            if row is None or row["state"] == "cancelled":
                self._cancelled.discard(item.id)
                return  # Stop was pressed while it ran
            if result == "done":
                conn.execute("UPDATE work_item SET state = 'done', error = NULL, updated_at = ? WHERE id = ?", (now, item.id))
            elif result == "failed" or (after_s is None and item.attempts > len(self._backoff)):
                conn.execute(
                    "UPDATE work_item SET state = 'failed', error = ?, updated_at = ? WHERE id = ?", (error, now, item.id)
                )
            else:
                pause = after_s if after_s is not None else self._backoff[min(item.attempts - 1, len(self._backoff) - 1)]
                # A wait with a pause of its own is not a try that failed: it is given back.
                refund = 1 if after_s is not None else 0
                conn.execute(
                    "UPDATE work_item SET state = 'queued', error = ?, next_try_at = ?, updated_at = ?,"
                    " attempts = MAX(attempts - ?, 0) WHERE id = ?",
                    (error, now + int(pause * 1000), now, refund, item.id),
                )

    # ------------------------------------------------------------------ the worker threads

    def start(self) -> None:
        self.recover()
        self._stopping = False
        for pool, count in self._workers.items():
            for n in range(count):
                thread = threading.Thread(target=self._loop, args=(pool,), name=f"work-{pool}-{n}", daemon=True)
                thread.start()
                self._threads.append(thread)

    def stop(self) -> None:
        with self._wake:
            self._stopping = True
            self._wake.notify_all()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()

    def _loop(self, pool: str) -> None:
        while not self._stopping:
            try:
                ran = self.run_one(pool)
            except Exception:  # noqa: BLE001 - the loop must survive a database hiccup
                log.exception("the %s worker could not take work", pool)
                ran = False
            if not ran:
                with self._wake:
                    if not self._stopping:
                        self._wake.wait(timeout=1.0)
