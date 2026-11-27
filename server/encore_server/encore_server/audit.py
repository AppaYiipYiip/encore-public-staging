"""The audit line (docs/36 sections 3 and 6): what a Host did to the server from the computer, as plain facts, in the database and in the log.

A line says who it was about, what was done and how, in one short sentence. It never holds a password, a recovery key or a setup code (a test greps for them). Nothing edits or deletes a
row, and no route writes one: only the operations on the computer do.
"""

from __future__ import annotations

import logging
import sqlite3

from .ids import now_ms

log = logging.getLogger("encore_server.audit")


def record(conn: sqlite3.Connection, kind: str, subject: str, detail: str) -> None:
    """Writes one line inside the caller's transaction (so an act and its line are one write), and says it in the log."""
    conn.execute("INSERT INTO audit_log (at, kind, subject, detail) VALUES (?,?,?,?)", (now_ms(), kind, subject, detail))
    log.warning("audit: %s: %s", kind, detail)
