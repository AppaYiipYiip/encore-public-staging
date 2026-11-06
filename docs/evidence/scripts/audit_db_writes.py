"""What does one small database write cost on this server, and where does the time go? (6 Nov 2026; audit B-10 family, P3-29)

    docker run --rm -v <repo>/docs/evidence/scripts:/s:ro -w /app --entrypoint python encore-server:local /s/audit_db_writes.py
    C:/dev/venv-encore-server/Scripts/python.exe -X utf8 docs/evidence/scripts/audit_db_writes.py --server server/encore_server

It writes 2,000 likes four ways and prints writes a second for each. SQLite is the server's database; the question this answers is whether the waits seen with
twenty people (docs/evidence/README.md#e02) are SQLite's limit or the way the server uses it. Measured 6 Nov 2026 in the server image (Linux):

    (a) a new connection for every write, which is what `Database.tx()` does           144 a second   (7 ms each)
    (b) opening and closing a connection, nothing written                              2,265 a second  (0.44 ms each)
    (c) ONE connection kept open, one transaction per write                          32,706 a second  (0.03 ms each)
    (d) like (a), plus ONE idle connection kept open for the whole run                2,796 a second  (0.36 ms each)

SQLite itself is not the limit: it does about 30,000 small writes a second here, and twenty real people make a few. The cost of (a) is mostly that when
the LAST connection to a database in WAL mode closes, SQLite checkpoints the journal and deletes its files, which a connection per call does on every write.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", type=Path, default=Path(__file__).resolve().parents[3] / "server" / "encore_server")
    parser.add_argument("--writes", type=int, default=2000)
    args = parser.parse_args()
    sys.path.insert(0, str(args.server))
    from encore_server import library  # noqa: PLC0415
    from encore_server.db import Database  # noqa: PLC0415

    path = Path(tempfile.mkdtemp()) / "writes.db"
    db = Database(path)
    db.migrate()
    with db.tx() as c:
        person = str(library.ensure_person(c, "amy")["id"])
    n_writes = args.writes

    def like(n: int) -> tuple[str, tuple[str, str, int]]:
        return "INSERT OR IGNORE INTO library_item (person, kind, target, at) VALUES (?, 'like', ?, ?)", (person, f"sr_{n:026d}"[:29], n)

    t = time.perf_counter()
    for n in range(n_writes):
        with db.tx() as c:
            c.execute(*like(n))
    a = time.perf_counter() - t

    t = time.perf_counter()
    for _ in range(n_writes):
        db.connect().close()
    b = time.perf_counter() - t

    c = sqlite3.connect(path, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    t = time.perf_counter()
    for n in range(n_writes, 2 * n_writes):
        c.execute("BEGIN IMMEDIATE")
        c.execute(*like(n))
        c.execute("COMMIT")
    kept = time.perf_counter() - t
    c.close()

    idle = db.connect()
    t = time.perf_counter()
    for n in range(3 * n_writes, 4 * n_writes):
        with db.tx() as c2:
            c2.execute(*like(n))
    d = time.perf_counter() - t
    idle.close()

    print(f"(a) a new connection per write (today):                  {n_writes / a:8.0f} writes a second ({a / n_writes * 1000:.3f} ms each)")
    print(f"(b) opening and closing a connection only:               {n_writes / b:8.0f} per second     ({b / n_writes * 1000:.3f} ms each)")
    print(f"(c) one kept connection, one transaction per write:      {n_writes / kept:8.0f} writes a second ({kept / n_writes * 1000:.3f} ms each)")
    print(f"(d) like (a), plus one idle connection kept open:        {n_writes / d:8.0f} writes a second ({d / n_writes * 1000:.3f} ms each)")
    print(f"PASS" if n_writes / a >= 1000 else f"FAIL  wanted (a) to reach 1,000 writes a second: it does {n_writes / a:.0f}; (d) shows {n_writes / d:.0f} with one idle connection kept open")


if __name__ == "__main__":
    main()
