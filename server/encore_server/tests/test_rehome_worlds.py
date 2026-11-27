"""P2-25 slice 4, SECOND review round: the invariants of the rehome on seeded random worlds (the permanent form of the adversarial tester's three probes).

A world is a few songs (some on the worklist, some liked) with a few library files each, whose TAGS may name their own song, another song of the world, nobody (the
placeholder artist, no tags at all) or carry an id; some files are no longer listed by the music server, the lengths differ by a second or by ten, and some songs have no
length yet. The seeds below include the ones that broke the first build of this slice (found by the same generator: 28 of 1,500 worlds stranded a like on a song with no file;
22 of 500 needed a second writing pass; a pass cut by the music server and resumed ended elsewhere than the uncut one), and the rest are plain ones.

Third review (23 Nov 2026): the generator ALSO writes what it could not before and what two blockers hid in (the "0 of 1,500" of the first reports was blind to both):
**tombstones** (`ref_merge` rows: a ref that was merged away, whose name may answer a file by the merged tier) and **arrivals** (songs the music server lists that have no row
yet: the scan attaches them to a ref DURING the pass). The new randomness has its own generator, so the worlds of the seeds below are the same as before plus these.

What must hold, whatever the world:

1. **No like loses its file to a move**: a liked song that held a file the music server lists still holds a file after the pass (the last file of a song a person owns never
   moves, and the files the prune removes in the same pass do not count as files it keeps).
2. **Nothing a person owns changes.**
3. **One pass is enough**: a second pass over an unchanged catalogue writes nothing and takes no copy of the database (`rehome.py`: "one state, rounds to a fixpoint").
4. **The outcome does not depend on how the pass was read**: the page size, a pass cut by the music server and resumed, and a pass KILLED between two chunks of moves and resumed
   end exactly where one uncut pass ends.
5. **At most one copy** of the database for the whole pass.
"""

from __future__ import annotations

import hashlib
import random
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from encore_server import library, refs, rehome
from encore_server.db import Database
from encore_server.scanner import link_library
from tests.test_rehome import ME, Music, add_file, add_ref, rid, song

TITLES = ["كيفك", "حبيتك", "نسّم", "سألوني"]
ARTISTS = ["فيروز", "Кино"]
NAMELESS = "[Unknown Artist]"
ISRCS = ["QZ0000000001", "QZ0000000002"]

#: The seeds that broke the first build (stranded like, second pass, cut and resumed), 24 and 46 (found on 23 Nov by the tombstones and arrivals the generator writes now: a pass killed or
#: cut ends elsewhere than the uncut one on the code of 506bf42), then plain ones.
SEEDS = [1, 13, 16, 24, 46, 48, 50, 65, 71, 90, 106, 110, 117, 176, 213, 221, 238, 300, 306, 604, 605, 606, 607, 608]


def world(seed: int) -> dict[str, Any]:
    r = random.Random(seed)
    refs_: list[dict[str, Any]] = []
    used_isrc: set[str] = set()
    for i in range(1, r.randint(3, 6) + 1):
        isrc = None
        if r.random() < 0.4:
            candidate = r.choice(ISRCS)
            if candidate not in used_isrc:
                isrc = candidate
                used_isrc.add(candidate)
        refs_.append(
            {
                "id": rid("sr", i),
                "title": r.choice(TITLES),
                "artist": r.choice(ARTISTS),
                "dur": r.choice([None, None, 200_000, 200_000, 210_000]),
                "isrc": isrc,
                "like": r.random() < 0.5,
                "worklist": r.random() < 0.85,
            }
        )
    files_: list[dict[str, Any]] = []
    for x in refs_:
        for _ in range(r.choice([0, 1, 1, 2, 2, 3, 4])):
            n = len(files_) + 1
            kind = r.random()
            if kind < 0.3:
                title, artist = x["title"], x["artist"]
            elif kind < 0.8:
                other = r.choice(refs_)
                title, artist = other["title"], other["artist"]
            elif kind < 0.92:
                title, artist = r.choice(TITLES), NAMELESS
            else:
                title, artist = "", ""
            files_.append(
                {
                    "nd": f"nd-{n}",
                    "ref": x["id"],
                    "title": title,
                    "artist": artist,
                    "sec": r.choice([200.0, 200.0, 201.0, 210.0]),
                    "isrc": r.choice([None, None, None, *ISRCS]),
                    "source": "youtube" if r.random() < 0.1 else "library",
                    "listed": r.random() < 0.85,
                    "added": 5000 + n if r.random() < 0.7 else 5000 + r.randint(1, 20),
                }
            )
    # P3-33: a pass that lists fewer than half of the linked files is an outage, not a library (the link then removes nothing at once, `scanner.PLAUSIBLE_SHARE`). These worlds are libraries
    # whose unlisted files are really gone: enough of the files are listed for the pass to be trusted.
    for gone in [f for f in files_ if not f["listed"]]:
        if sum(1 for f in files_ if f["listed"]) * 2 >= len(files_):
            break
        gone["listed"] = True
    if not any(x["worklist"] for x in refs_):
        refs_[0]["worklist"] = True
    order = list(range(len(files_)))
    r.shuffle(order)
    extra = random.Random(seed * 7919 + 13)
    tombstones = []
    for k in range(extra.choice([0, 0, 1, 2])):
        into, named = extra.choice(refs_), extra.choice(refs_)
        tombstones.append(
            {
                "old": rid("sr", 90 + k),
                "into": into["id"],
                "title": named["title"],
                "artist": named["artist"],
                "dur": extra.choice([None, 200_000, 205_000]),
            }
        )
    arrivals = []
    for k in range(extra.choice([0, 0, 1, 2])):
        named = extra.choice(refs_)
        arrivals.append(
            {
                "nd": f"nx-{k + 1}",
                "title": named["title"],
                "artist": named["artist"],
                "sec": extra.choice([200.0, 201.0, 205.5]),
                "isrc": extra.choice([None, None, *ISRCS]),
                "at": extra.randint(0, len(order)),
            }
        )
    return {"refs": refs_, "files": files_, "order": order, "tombstones": tombstones, "arrivals": arrivals}


def tags(f: dict[str, Any]) -> dict[str, Any]:
    return song(f["nd"], f["title"], f["artist"], f["sec"], **({"isrc": [f["isrc"]]} if f["isrc"] else {}))


def listing_of(w: dict[str, Any]) -> list[dict[str, Any]]:
    songs = [tags(w["files"][i]) for i in w["order"] if w["files"][i]["listed"]]
    for a in w["arrivals"]:  # listed, no row: the scan of the pass attaches it
        songs.insert(
            min(a["at"], len(songs)),
            song(a["nd"], a["title"], a["artist"], a["sec"], **({"isrc": [a["isrc"]]} if a["isrc"] else {})),
        )
    return songs


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One migrated, checkpointed database that every world copies (migrating takes longer than a world)."""
    path = tmp_path_factory.mktemp("worlds") / "template.db"
    Database(path).migrate()
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raw.close()
    return path


def fresh(template: Path, where: Path, w: dict[str, Any]) -> Database:
    where.mkdir(parents=True, exist_ok=True)
    shutil.copy(template, where / "encore.db")
    db = Database(where / "encore.db")
    with db.tx() as c:
        c.execute("INSERT INTO person (id, navidrome_user, display_name, created_at) VALUES (?,?,?,1)", (ME, "ana", "ana"))
        for x in w["refs"]:
            add_ref(c, x["id"], x["title"], [x["artist"]], old=False, duration_ms=x["dur"], isrc=x["isrc"])
            if x["like"]:
                library.set_item(c, ME, "like", x["id"])
            if x["worklist"]:
                c.execute("INSERT INTO ref_recheck (ref, at) VALUES (?, 1)", (x["id"],))
        for f in w["files"]:
            add_file(c, f["ref"], f["nd"], source=f["source"], added_at=f["added"], preferred=0, song=tags(f))
        for x in w["refs"]:
            refs.ensure_one_preferred(c, x["id"])
        for t in w["tombstones"]:
            c.execute(
                "INSERT INTO ref_merge (old_id, into_id, at, norm_key, duration_ms) VALUES (?,?,1,?,?)",
                (t["old"], t["into"], refs.norm_key(t["artist"], t["title"]), t["dur"]),
            )
    return db


def digest(db: Database) -> str:
    h = hashlib.sha256()
    with db.read() as conn:
        for table in ("song_ref", "song_file", "ref_recheck", "file_log", "library_item", "ref_merge", "setting"):
            h.update(repr((table, [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")])).encode())  # noqa: S608 - fixed names
    return h.hexdigest()


def outcome(db: Database, w: dict[str, Any]) -> dict[str, Any]:
    """Where every file is (a song the pass made is named by its key: its id is new each time) and which songs are still held."""
    initial = {x["id"] for x in w["refs"]}
    with db.read() as conn:
        placed = {
            r["nd"]: r["ref"] if r["ref"] in initial else "NEW:" + r["key"]
            for r in conn.execute(
                "SELECT f.navidrome_song_id nd, f.ref ref, s.norm_key key FROM song_file f JOIN song_ref s ON s.id = f.ref"
            )
        }
        held = sorted(r["ref"] for r in conn.execute("SELECT ref FROM ref_recheck") if r["ref"] in initial)
        likes = [tuple(r) for r in conn.execute("SELECT person, kind, target FROM library_item ORDER BY 1, 2, 3")]
        # the songs and the merges the pass made are named by their number: their ids are new each time
        shape = (
            conn.execute("SELECT COUNT(*) FROM song_ref").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM ref_merge").fetchone()[0],
        )
    return {"files": placed, "held": held, "likes": likes, "refs_and_merges": shape}


@pytest.mark.parametrize("seed", SEEDS)
def test_the_invariants_of_the_rehome_hold_on_a_random_world(seed: int, template: Path, tmp_path: Path) -> None:
    w = world(seed)
    songs = listing_of(w)
    listed_ids = {s["id"] for s in songs}
    db = fresh(template, tmp_path / "a", w)
    with db.read() as conn:
        held_before = {
            x["id"]: [r[0] for r in conn.execute("SELECT navidrome_song_id FROM song_file WHERE ref = ?", (x["id"],))]
            for x in w["refs"]
        }
    owned_before = outcome(db, w)["likes"]

    link_library(db, Music(songs), page=2)
    first = outcome(db, w)

    # 1 + 2: no like loses its file, nothing a person owns changes
    assert first["likes"] == owned_before
    with db.read() as conn:
        for x in w["refs"]:
            if x["like"] and any(nd in listed_ids for nd in held_before[x["id"]]):
                files_now = conn.execute("SELECT COUNT(*) FROM song_file WHERE ref = ?", (x["id"],)).fetchone()[0]
                assert files_now, f"seed {seed}: {x['id']} is liked, held a listed file and has none now"
    # 5: one copy for the whole pass
    assert len(db.copies("before-rehome")) <= 1
    # 3: a second pass over the unchanged catalogue writes nothing and takes no copy
    state, copies = digest(db), len(db.copies("before-rehome"))
    link_library(db, Music(songs), page=2)
    assert digest(db) == state, f"seed {seed}: a second pass wrote something"
    assert len(db.copies("before-rehome")) == copies
    # 4: the page size does not matter, nor does a pass cut by the music server and resumed
    for page in (1, 500):
        other = fresh(template, tmp_path / f"p{page}", w)
        link_library(other, Music(songs), page=page)
        assert outcome(other, w) == first, f"seed {seed}: page size {page} ends elsewhere than page size 2"
    cut = fresh(template, tmp_path / "cut", w)
    link_library(cut, Music(songs, down_at=2), page=2)
    link_library(cut, Music(songs), page=2)
    assert outcome(cut, w) == first, f"seed {seed}: a pass cut by the music server and resumed ends elsewhere than the uncut pass"
    # ... and a pass KILLED between two chunks of moves (the second move raises, as when the process dies), then resumed
    killed = fresh(template, tmp_path / "killed", w)
    calls: list[str] = []
    real = rehome.Rehome._move  # noqa: SLF001

    def dying(self: rehome.Rehome, conn: sqlite3.Connection, file_id: str, ref: str, described: dict[str, Any] | None) -> Any:
        calls.append(file_id)
        if len(calls) == 2:
            raise RuntimeError("the process was killed here")
        return real(self, conn, file_id, ref, described)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rehome, "CHUNK", 1)
        patch.setattr(rehome.Rehome, "_move", dying)
        link_library(killed, Music(songs), page=2)
    link_library(killed, Music(songs), page=2)
    assert outcome(killed, w) == first, (
        f"seed {seed}: a pass killed between two chunks and resumed ends elsewhere than the uncut pass"
    )
    # ... and a pass killed AFTER its moves, before the worklist is released (the files the scan attached during the pass are rows of the pass that follows)
    unreleased = fresh(template, tmp_path / "unreleased", w)

    def refusing(self: rehome.Rehome, conn: sqlite3.Connection, part: Any, kept_back: Any) -> Any:
        raise RuntimeError("the process was killed here: the moves are committed, the release is not")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rehome.Rehome, "_release", refusing)
        link_library(unreleased, Music(songs), page=2)
    link_library(unreleased, Music(songs), page=2)
    assert outcome(unreleased, w) == first, (
        f"seed {seed}: a pass killed before its release and resumed ends elsewhere than the uncut pass"
    )
