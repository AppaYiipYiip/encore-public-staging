"""In-process probes of the server code for the audit of what is built (6 Nov 2026). No Docker, no network, nothing is sent anywhere.

Each probe runs the real server code on a scratch database and prints what it did; the register row it proves is named in brackets
(docs/tasks/AUDIT-BUILT-2026-11-05.md). A fix is done when the probe's last line says what the "wanted" line says.

    python docs/evidence/scripts/audit_probes.py fair-share     [B-39]  one person queues 2,000 songs, another 20: where do the 20 run?
    python docs/evidence/scripts/audit_probes.py prune          [B-40]  the music server answers with an empty library: what happens to the file links?
    python docs/evidence/scripts/audit_probes.py transient      [B-38]  a YouTube Music search times out: what does the keeper conclude?
    python docs/evidence/scripts/audit_probes.py scripts        [B-37]  songs whose names are not in the Latin alphabet: are they told apart and found?
    python docs/evidence/scripts/audit_probes.py import-lock    [B-10 family]  how long does one big import hold the database write lock?

Needs the server's own environment (`pip install -e server/encore_server[youtube]`), or `--server DIR` pointing at `server/encore_server`.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # a Windows console is cp1252 by default; the probes print Arabic


def _import(server: Path):
    sys.path.insert(0, str(server))
    from encore_server import library, refs  # noqa: PLC0415
    from encore_server.db import Database  # noqa: PLC0415

    return library, refs, Database


def _db(Database):
    db = Database(Path(tempfile.mkdtemp()) / "probe.db")
    db.migrate()
    return db


def fair_share(server: Path) -> None:
    library, refs, Database = _import(server)
    from encore_server.scheduler import Scheduler  # noqa: PLC0415

    db = _db(Database)
    clock = [1000.0]
    sched = Scheduler(db, {"keep": lambda item: None}, clock=lambda: clock[0])
    with db.tx() as conn:
        a = str(library.ensure_person(conn, "marwa")["id"])
        b = str(library.ensure_person(conn, "nina")["id"])
        ids = [str(refs.resolve(conn, {"title": f"Song {n}", "artists": ["Artist"], "durationMs": 180000 + n * 10})["id"]) for n in range(2020)]
        for ref in ids[:2000]:
            clock[0] += 0.001
            sched.submit("keep", ref, a, conn=conn)
        for ref in ids[2000:]:
            clock[0] += 0.001
            sched.submit("keep", ref, b, conn=conn)
    order = []
    while (item := sched._claim("background")) is not None:  # noqa: SLF001 - the probe drives the scheduler by hand
        order.append(item.persons[0])
        sched._finish(item, "done", None, None)  # noqa: SLF001
    positions = [i + 1 for i, p in enumerate(order) if p == b]
    print("nina's 20 items ran at positions", positions[:3], "...", positions[-3:])
    print("wanted: all 20 before position 100 (docs/07 section 6) ->", "PASS" if positions[-1] < 100 else "FAIL")


class _FakeLibrary:
    def __init__(self) -> None:
        self.now: list[dict] = []

    def songs(self, offset, size=500):
        return self.now[offset : offset + size]


def prune(server: Path) -> None:
    library, _refs, Database = _import(server)
    from encore_server import scanner  # noqa: PLC0415

    db = _db(Database)
    fake = _FakeLibrary()
    fake.now = [
        {"id": f"nd{n}", "title": f"Song {n}", "artist": "Artist", "duration": 180 + n, "suffix": "flac", "path": f"Artist/Song {n}.flac"}
        for n in range(300)
    ]
    scanner.link_library(db, fake)
    fake.now = []  # the disk is not mounted: the music server lists nothing
    report = scanner.link_library(db, fake)
    with db.read() as conn:
        files = conn.execute("SELECT COUNT(*) FROM song_file").fetchone()[0]
    print(f"empty answer: complete={report.complete} pruned={report.pruned} file rows left={files}")
    print("wanted: the file links survive an empty answer ->", "PASS" if files == 300 else "FAIL")


def transient(server: Path) -> None:
    _library, refs, Database = _import(server)
    from encore_server.keeper.failures import describe_failure  # noqa: PLC0415
    from encore_server.keeper.keeper import Keeper, KeepSettings  # noqa: PLC0415
    from encore_server.scheduler import GiveUp, Retry, WorkItem  # noqa: PLC0415
    from encore_server.sources.youtube.lean import LeanResolver  # noqa: PLC0415
    from encore_server.sources.youtube.source import YoutubeSource  # noqa: PLC0415

    class Flaky:
        def songs(self, query, limit):
            raise TimeoutError("read timed out")

        videos = songs

    tmp = Path(tempfile.mkdtemp())
    db = Database(tmp / "p.db")
    db.migrate()
    with db.tx() as conn:
        ref = refs.resolve(conn, {"title": "Maria Tambien", "artists": ["Khruangbin"], "durationMs": 215000})["id"]
    source = YoutubeSource(tmp / "work", resolver=LeanResolver(Flaky()), extractor=object())
    keeper = Keeper(db, source, navidrome=None, settings=KeepSettings(music_dir=tmp / "music", min_free_gb=0), work_dir=tmp / "work")
    try:
        keeper.handle(WorkItem("wk_1", "keep", ref, 4, 1, ()))
        verdict = "nothing raised"
    except GiveUp as given_up:
        shown = describe_failure(given_up.reason, host=False)
        verdict = f"GiveUp({given_up.reason!r}); the phone is told {shown.reason!r}, Retry offered: {shown.retry}"
    except Retry as later:
        verdict = f"Retry({later.reason!r}) after {later.after_s}"
    print("a search timeout ends as:", verdict)
    print("wanted: a Retry, not a GiveUp ->", "PASS" if verdict.startswith("Retry") else "FAIL")


def scripts(server: Path) -> None:
    _library, refs, Database = _import(server)
    from encore_server.sources.youtube.lean import rank  # noqa: PLC0415
    from encore_server.sources.youtube.scoring import Candidate, Want  # noqa: PLC0415

    db = _db(Database)
    with db.tx() as conn:
        a = refs.resolve(conn, {"title": "كيفك إنت", "artists": ["فيروز"], "durationMs": 215000})
        b = refs.resolve(conn, {"title": "نسّم علينا الهوا", "artists": ["فيروز"], "durationMs": 216500})
    print("two different Fairuz songs, 1.5 s apart: same song?", a["id"] == b["id"], "| key:", repr(refs.norm_key("فيروز", "كيفك إنت")))
    want = Want("فيروز", "كيفك إنت", None, 215)
    candidate = Candidate("abcdefghijk", "كيفك إنت", "فيروز - Topic", 215, True, "كيفك إنت", ("فيروز",), "Kifak Inta")
    accepted = bool(rank(want, [candidate]))
    print("an exact Arabic match from YouTube Music is accepted?", accepted)
    print("wanted: two songs, and the exact match accepted ->", "PASS" if a["id"] != b["id"] and accepted else "FAIL")


def import_lock(server: Path) -> None:
    library, _refs, Database = _import(server)
    from encore_server.imports.service import ImportService  # noqa: PLC0415
    from encore_server.live import Hub  # noqa: PLC0415

    db = _db(Database)
    with db.tx() as conn:
        person = str(library.ensure_person(conn, "marwa")["id"])
    service = ImportService(db, Hub(), None, read=lambda url: None)
    songs = [{"title": f"Song {n}", "artists": [f"Artist {n % 40}"], "album": f"Album {n % 90}", "durationMs": 180000 + n * 7} for n in range(5000)]
    waited: list[float] = []

    def other_person() -> None:
        time.sleep(0.05)
        started = time.perf_counter()
        with db.tx() as conn:  # what every signed-in request does today
            conn.execute("SELECT 1").fetchone()
        waited.append(time.perf_counter() - started)

    thread = threading.Thread(target=other_person)
    thread.start()
    started = time.perf_counter()
    service.create(person, {"name": "Big list", "songs": songs, "source": "file"})
    took = time.perf_counter() - started
    thread.join()
    print(f"a 5,000-song import took {took:.2f} s; another person's request waited {waited[0]:.2f} s (measured 0.41 s / 0.48 s on 6 Nov 2026)")


PROBES = {"fair-share": fair_share, "prune": prune, "transient": transient, "scripts": scripts, "import-lock": import_lock}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("probe", choices=sorted(PROBES))
    parser.add_argument("--server", type=Path, default=Path(__file__).resolve().parents[3] / "server" / "encore_server")
    args = parser.parse_args()
    PROBES[args.probe](args.server)
