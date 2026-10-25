"""The bell (docs/tasks P2-15, docs/11 ADR-R44): news kept per person, said in words, so a phone, a browser and a TV show the same list.

Four kinds and no others, as drawn (docs/design S-24): a release from an artist the person plays, a Jam invitation, an invitation of theirs that was
used, an import that finished. Nothing here reaches a phone's notification shade: the app decides that, and it is off until the person says so.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from .db import Database
from .errors import ApiError
from .ids import now_ms
from .live import Hub

log = logging.getLogger("encore_server.notifications")

#: What may be told. `release` and `jam` are made by their own services later (the recommendations, the Jam hub).
KINDS = frozenset({"release", "jam", "invite_used", "import_done"})

#: How much a person keeps: this many items, none older than this many days. The oldest go when new news arrives.
KEEP_AT_MOST = 200
KEEP_DAYS = 90

DEFAULT_PAGE = 50
MAX_PAGE = 200


class Notifications:
    def __init__(self, db: Database, hub: Hub) -> None:
        self._db = db
        self._hub = hub

    # ------------------------------------------------------------------ telling

    def push(
        self,
        person: str,
        kind: str,
        title: str,
        *,
        body: str | None = None,
        route: str | None = None,
        dedupe: str | None = None,
    ) -> bool:
        """Adds one piece of news and says so on the person's devices. `False` (and nothing said) when the same `dedupe` was told before."""
        if kind not in KINDS:
            raise ApiError("validation", "That kind of news does not exist.")
        now = now_ms()
        with self._db.tx() as conn:
            made = conn.execute(
                "INSERT OR IGNORE INTO notification (person, kind, title, body, route, dedupe, created_at) VALUES (?,?,?,?,?,?,?)",
                (person, kind, title, body, route, dedupe, now),
            )
            if made.rowcount == 0:
                return False
            self._prune(conn, person, now)
            unread = self._unread(conn, person)
        self._hub.publish(person, {"type": "notification.new", "unread": unread})
        return True

    def tell(self, person: str, kind: str, title: str, **extra: str | None) -> None:
        """[push] for what an action leaves behind: news must never fail the thing that caused it (a join, a finished import), so a failure
        here (a locked database, say) is logged and the action goes on."""
        try:
            self.push(person, kind, title, **extra)
        except Exception:  # noqa: BLE001 - the bell is a courtesy; the caller's work is already done
            log.exception("could not tell %s about %s", person, kind)

    @staticmethod
    def _prune(conn: sqlite3.Connection, person: str, now: int) -> None:
        conn.execute("DELETE FROM notification WHERE person = ? AND created_at < ?", (person, now - KEEP_DAYS * 24 * 3600 * 1000))
        conn.execute(
            "DELETE FROM notification WHERE person = ? AND id NOT IN"
            " (SELECT id FROM notification WHERE person = ? ORDER BY id DESC LIMIT ?)",
            (person, person, KEEP_AT_MOST),
        )

    @staticmethod
    def _unread(conn: sqlite3.Connection, person: str) -> int:
        return int(
            conn.execute("SELECT COUNT(*) FROM notification WHERE person = ? AND read_at IS NULL", (person,)).fetchone()[0]
        )

    # ------------------------------------------------------------------ reading

    def list(self, person: str, *, since: int = 0, limit: int = DEFAULT_PAGE) -> dict[str, Any]:
        """The person's news, newest first (only what is newer than [since] when it is given), with how many are unread in all."""
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM notification WHERE person = ? AND id > ? ORDER BY id DESC LIMIT ?", (person, since, limit)
            ).fetchall()
            unread = self._unread(conn, person)
        return {
            "items": [
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "title": r["title"],
                    "body": r["body"],
                    "route": r["route"],
                    "createdAt": r["created_at"],
                    "read": r["read_at"] is not None,
                }
                for r in rows
            ],
            "unread": unread,
            "cursor": str(rows[0]["id"]) if rows else str(since),
        }

    def mark_read(self, person: str, up_to: int | None = None) -> int:
        """Marks the person's news read, all of it or up to an id; safe to repeat. Returns how many are still unread."""
        with self._db.tx() as conn:
            conn.execute(
                "UPDATE notification SET read_at = ? WHERE person = ? AND read_at IS NULL AND (? IS NULL OR id <= ?)",
                (now_ms(), person, up_to, up_to),
            )
            return self._unread(conn, person)
