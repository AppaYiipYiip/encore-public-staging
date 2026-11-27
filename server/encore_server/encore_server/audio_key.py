"""The audio-only key of a file (N-38; docs/tasks/N-38-audio-only-key.md): what a phone compares to know a downloaded song is still the song.

**The problem.** The app marks a downloaded song stale when the key it stored at download time differs from the live one, and that key (`refAudioKey`, `fingerprint.dart`) hashes the file's
SIZE. Every rewrite of the TAGS of a kept file (a repair, a retag; N-34, N-26 slice 5) changes the size, so every phone would fetch every repaired song again, on mobile data for some people,
for a change the person never hears. A fix that costs the future: it is paid again by every later repair.

**The key.** `a1:` + the first 32 hex digits of the SHA-256 of the file's FIRST AUDIO STREAM, copied as it is (`ffmpeg -map 0:a:0 -c copy -f hash`): the packets, never the tags, the cover, the
container's pages or boxes. A tag rewrite leaves it as it was (proved on the real ffmpeg in `tests/integration/test_audio_key.py` for Opus, FLAC, AAC in MP4 and MP3, with a cover added); a replaced or
re-encoded file changes it. It is stored (`song_file.audio_key`, with the file size it was taken at: `audio_key_size`) and served as `file.audioKey` in the ref, additive and optional.

**The key is FROZEN.** Phones keep the key they were served in every download. A new way of making it would change every key at once, which is the mass re-download this exists to prevent: it
would need its own prefix (`a2:`), and the phone's adopt-by-match rule (the task doc) to move the stored keys. The prefix says which way made a key, and a phone never compares two prefixes.

**When it is made.**

* **A new keep**: right after the keeper has tagged and placed the file (`keeper._link`), so a song is served with its key from the first moment (`attach_file`).
* **A file the library link found** (an imported library, a file put there by hand), and **a file whose size changed behind the server's back**: [AudioKeys.run_once], an errand of the hourly
  library link, at most [BATCH] files and [BUDGET_S] seconds a pass, preferred files first, never at a priority that competes with playing. **Only a row whose stored path names a file of exactly the size the music
  server reports for it is keyed** (see [on_disk]): for a library file the stored path is the music server's tag-built one, so most library rows are never keyed and keep behaving as before.
* **A server's own tag rewrite** (the repairs to come) must call [carry] after the rewrite, in the same step: it records the NEW size against the SAME key, so the pass does not hash the file again
  and a change of ffmpeg's version cannot change a key the phones hold. A repair that forgets costs only the hashing (the pass finds the same key again), never a key change.

**What is served while a key is out of date.** The last known key, never none: a replaced file shows its new key within one pass (an hour at most), and a file whose size changed because the server
retagged it keeps the key it had. A file that ffmpeg cannot read gets the empty key (served as no key) at that size and is looked at again only when its size changes.

**What costs what.** One ffmpeg process a file (about the file's read time: tens of milliseconds for a song); one query over `song_file` an hour (it is read once a pass, like the library link's own
pass); one `file_log` row a key made or changed, so that a phone learns it.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from . import refs
from .db import Database
from .ids import now_ms
from .keeper.placement import inside

log = logging.getLogger("encore_server.audio_key")

#: The prefix says which way made the key. FROZEN: see the module's text.
KEY_PREFIX = "a1:"
#: How many hex digits of the SHA-256 are kept (128 bits: a collision between two songs is not a thing that happens).
KEY_DIGITS = 32
#: How long hashing one file may take. A song is read in well under a second; this only stops a stuck disk from stopping the hourly errands.
HASH_TIMEOUT_S = 120.0
#: At most this many files a pass, and at most this long: the hourly pass catches up with a library in a few hours and never holds the errands for long.
BATCH = 400
BUDGET_S = 40.0

_HASH_LINE = re.compile(r"^SHA256=([0-9a-f]{64})$", re.MULTILINE)


class Unreadable(Exception):
    """ffmpeg read the file and said it has no audio stream it can copy (a definite answer about THIS file; not a missing program, not a timeout)."""


def ffmpeg_command(path: Path) -> list[str]:
    """The one command that makes a key. `nice` keeps it behind the playing of music when the program exists (it does in the server image)."""
    nice = ["nice", "-n", "10"] if shutil.which("nice") else []
    return [
        *nice,
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-c",
        "copy",
        "-f",
        "hash",
        "-hash",
        "sha256",
        "-",
    ]


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def audio_key_of(path: Path, *, runner: Runner = subprocess.run, timeout: float = HASH_TIMEOUT_S) -> str:
    """The key of [path] (see the module's text). Raises [Unreadable] when ffmpeg refuses the file; an `OSError` (no ffmpeg) and `subprocess.TimeoutExpired` pass through: they say
    nothing about the file, and the caller must not remember them as if they did."""
    done = runner(ffmpeg_command(path), capture_output=True, text=True, timeout=timeout, check=False)
    found = _HASH_LINE.search(done.stdout or "")
    if done.returncode != 0 or found is None:
        raise Unreadable((done.stderr or "").strip()[-200:] or f"ffmpeg exited {done.returncode}")
    return KEY_PREFIX + found.group(1)[:KEY_DIGITS]


def carry(conn: sqlite3.Connection, file_id: str, new_size: int) -> None:
    """The server rewrote the TAGS of this file (it is [new_size] bytes now): the key is the same, so only the size it is recorded at moves, and the music server's size in the row's `meta` moves with it
    (the next scan will say the same number), so that the errand does not take the file for one that changed behind the server's back and hash it again. A key the file does not have yet stays unmade (the
    pass will make it from the file as it is: it cannot be wrong, because the audio did not change). Call it in the same transaction that records the rewrite."""
    row = conn.execute("SELECT meta FROM song_file WHERE id = ? AND audio_key IS NOT NULL", (file_id,)).fetchone()
    if row is None:
        return
    meta = json.loads(row["meta"]) if row["meta"] else {}
    meta["size"] = new_size
    # the one format `refs.attach_file` writes, so that a scan reporting this size changes nothing (and tells no phone)
    conn.execute(
        "UPDATE song_file SET audio_key_size = ?, meta = ? WHERE id = ?",
        (new_size, json.dumps(meta, separators=(",", ":"), sort_keys=True), file_id),
    )


def on_disk(music_dir: Path, stored: str) -> Path | None:
    """The file a `song_file.path` names, or `None` (not there, or not inside the music folder).

    **A stored path is a location only for the files the keeper placed. For a library file it is the music server's own `path`, which the real music server (0.64.2, measured in the integration job) builds
    from the TAGS (`Artist/Album/Title.opus`), not from where the file lies.** So a path that names a file proves nothing about it: the caller still checks the size against the one the music server
    reports for that very row before it trusts the file (the keeper's own rows, and a library laid out exactly as its tags say, pass; any other library row finds no file and has no key)."""
    parts = stored.replace("\\", "/")
    if not parts or any(part in ("..", ".") for part in parts.split("/")):
        return None
    candidate = music_dir / parts
    return candidate if inside(music_dir, candidate) and candidate.is_file() else None


class Pass(NamedTuple):
    """What one pass did: keys made or changed, files ffmpeg could not read, files left for the next pass (not on the disk, or changed while read, or over the budget)."""

    made: int
    unreadable: int
    left: int


#: The files that need a key: never keyed, or whose size is not the size the key was taken at (the music server's own number from the last scan, `meta.size`).
#: The files the errand has NEVER looked at come first (NULL sorts first), then the one looked at longest ago: a file that is never found or never readable cannot keep the others from their turn.
#: Within that, preferred files first (the ones a phone downloads), then the newest.
_TODO = (
    "SELECT id, ref, path, audio_key, audio_key_size, json_extract(meta, '$.size') AS seen_size FROM song_file WHERE path IS NOT NULL AND path_real = 1"
    " AND (audio_key_size IS NULL OR audio_key_size != COALESCE(json_extract(meta, '$.size'), audio_key_size))"
    " ORDER BY audio_key_tried_at, preferred DESC, added_at DESC, id LIMIT ?"
)


class AudioKeys:
    """The errand that makes the keys the keeper did not make. [hash_] and [clock] are given so that a test needs no ffmpeg and no wait."""

    def __init__(
        self,
        db: Database,
        music_dir: Path,
        *,
        hash_: Callable[[Path], str] = audio_key_of,
        clock: Callable[[], float] = time.monotonic,
        batch: int = BATCH,
        budget_s: float = BUDGET_S,
    ) -> None:
        self._db = db
        self._music = music_dir
        self._hash = hash_
        self._clock = clock
        self._batch = batch
        self._budget = budget_s

    def run_once(self) -> Pass:
        with self._db.read() as conn:
            todo = conn.execute(_TODO, (self._batch,)).fetchall()
        began = self._clock()
        made = unreadable = left = 0
        looked_at: list[str] = []  # the files this pass tried and did not key: they go to the back of the queue
        for index, row in enumerate(todo):
            if self._clock() - began > self._budget:
                left += len(todo) - index  # not tried: they keep their place
                break
            path = on_disk(self._music, str(row["path"]))
            if path is None:
                left += 1  # not there (a disk not mounted for a minute, or a path that does not name a file here): nothing is remembered about it but that it was looked at
                looked_at.append(str(row["id"]))
                continue
            try:
                size = path.stat().st_size
                if row["seen_size"] is not None and size != row["seen_size"]:
                    # Not the file the music server means (a library path is built from the tags, so two copies of an album share one), or a file retagged on disk and not scanned yet: either way
                    # it is not hashed for this row. A scan that reports its size lets a later pass take it.
                    left += 1
                    looked_at.append(str(row["id"]))
                    continue
                key, why = "", None
                try:
                    key = self._hash(path)
                except Unreadable as error:
                    why = str(error)
                if path.stat().st_size != size:
                    left += 1  # changed while it was read: the next pass takes it
                    looked_at.append(str(row["id"]))
                    continue
            except (OSError, subprocess.TimeoutExpired) as error:
                log.warning("the audio keys stop for this pass (%s): %s", type(error).__name__, error)
                looked_at.append(
                    str(row["id"])
                )  # the one that stopped the pass goes to the back, so the next pass reaches the others
                left += len(todo) - index
                break
            if why is not None:
                unreadable += 1
                log.warning("no audio key for %s: %s", row["path"], why)
            with self._db.tx() as conn:
                made += self._record(conn, row, key, size)
        if looked_at:
            with self._db.tx() as conn:
                conn.executemany(
                    "UPDATE song_file SET audio_key_tried_at = ? WHERE id = ?", [(now_ms(), file_id) for file_id in looked_at]
                )
        if made or unreadable:
            log.info(
                "audio keys: %d made or changed, %d files could not be read, %d left for the next pass", made, unreadable, left
            )
        return Pass(made, unreadable, left)

    @staticmethod
    def _record(conn: sqlite3.Connection, row: sqlite3.Row, key: str, size: int) -> int:
        """Records the key at the size it was taken at, **only if the row is still as the pass read it** (the keeper may have linked this very file a moment ago, with a key of its own: that one is not
        overwritten with an older answer). Tells the phones when the key SERVED changed (the first key, or another one). Returns 1 then, else 0."""
        done = conn.execute(
            "UPDATE song_file SET audio_key = ?, audio_key_size = ?, audio_key_tried_at = ? WHERE id = ? AND audio_key IS ? AND audio_key_size IS ?",
            (key, size, now_ms(), row["id"], row["audio_key"], row["audio_key_size"]),
        )
        if done.rowcount != 1 or (row["audio_key"] or "") == key:
            return 0
        refs.touch_file(conn, str(row["ref"]))
        return 1
