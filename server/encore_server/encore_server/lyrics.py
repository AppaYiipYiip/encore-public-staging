"""Lyrics on the server (docs/tasks P2-14, docs/11 ADR-R38).

The phone used to ask LRCLIB itself. Now it asks this server, which asks LRCLIB once for everybody, keeps the answer per song and turns it into
the same lines for every client (a web page, an iPhone, a TV). What leaves this server for LRCLIB is the artist, the title, the album and the
length of a song: never a person, an address or a ref id.

Rules (the phone's own, kept): the exact question first, then a search; a synced entry beats a plain one; an entry whose length is more than
`max(3, length / 50)` seconds off is another version (a live cut, a remix); a sheet of the song's own details where the words should be is no
lyrics (AUDIT R1-3). New: a miss is asked about again after an hour, then six hours, a day, a week (AUDIT F22: the phone waited a whole day, even
for a song released that morning), a failed look is not a miss, and many people asking for one song cause one question.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from .db import Database
from .errors import ApiError

log = logging.getLogger("encore_server.lyrics")

BASE_URL = "https://lrclib.net/api"
USER_AGENT = "Encore/0.1 (https://github.com/AppaYiipYiip/encore)"
#: One question to LRCLIB may take this long before it counts as "not answering".
DEADLINE_S = 10.0
#: After a miss: asked about again after an hour, six hours, a day, a week (and then every week).
MISS_PAUSES_S = (3600, 6 * 3600, 24 * 3600, 7 * 24 * 3600)
#: A plain answer is looked at again for a synced one; an instrumental is looked at again in case it was a mistake.
PLAIN_LOOK_AGAIN_S = 14 * 24 * 3600
INSTRUMENTAL_LOOK_AGAIN_S = 30 * 24 * 3600
#: When LRCLIB does not answer for a song that has an answer on record, the record is kept and the service left alone for this long.
FAILED_LOOK_PAUSE_S = 3600
#: "Try again" from a person is passed on at most this often per song.
ASK_AGAIN_AFTER_S = 60

_STAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_HEADER = re.compile(r"^\[[a-zA-Z]+:.*\]$")
_DETAILS = re.compile(r"^(artist|album|title|track|song|composer|lyricist|writer|length|year|genre)\s*:\s*\S?.*$", re.IGNORECASE)


def parse_lrc(content: str) -> tuple[str, Any]:
    """`("synced", [{ms, text}])`, `("plain", "text")` or `("none", None)` for the words of one LRCLIB entry."""
    synced: list[dict[str, Any]] = []
    for raw in re.split(r"\r?\n", content):
        stamps = list(_STAMP.finditer(raw))
        if not stamps:
            continue
        text = raw[stamps[-1].end() :].strip()
        for stamp in stamps:
            fraction = stamp.group(3)
            ms = int(fraction.ljust(3, "0")[:3]) if fraction else 0
            synced.append({"ms": (int(stamp.group(1)) * 60 + int(stamp.group(2))) * 1000 + ms, "text": text})
    if synced:
        synced.sort(key=lambda line: line["ms"])
        return ("synced", synced) if any(line["text"] for line in synced) else ("none", None)
    plain: list[str] = []
    for raw in re.split(r"\r?\n", content):
        line = raw.strip()
        if not line:
            if plain and plain[-1] != "":
                plain.append("")
            continue
        if _HEADER.match(line):
            continue
        plain.append(line)
    while plain and plain[-1] == "":
        plain.pop()
    words = [line for line in plain if line]
    if not words or all(_DETAILS.match(word) for word in words):
        return "none", None
    return "plain", "\n".join(plain)


def tolerance_s(wanted: int) -> int:
    """How far off the length of a song may be for an entry to be the same version of it."""
    return max(3, wanted // 50)


class _Unavailable(Exception):
    """LRCLIB did not answer (timeout, refusal, a server error): a failed look, not a miss."""


class LyricsService:
    def __init__(self, db: Database, client: httpx.Client | None = None, *, clock: Callable[[], float] = time.time) -> None:
        self._db = db
        self._http = client or httpx.Client(
            base_url=BASE_URL, timeout=httpx.Timeout(DEADLINE_S, connect=5.0), headers={"User-Agent": USER_AGENT}
        )
        self._clock = clock
        self._guard = threading.Lock()
        self._inflight: dict[str, list[Any]] = {}

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ what a client is told

    def get(self, ref: dict[str, Any], *, refresh: bool = False) -> dict[str, Any]:
        """The lyrics of one song reference, from the record or, when it is due, from LRCLIB (one question however many people ask)."""
        ref_id = str(ref["id"])
        row = self._row(ref_id)
        if row is not None and not self._due(row, refresh):
            return self._payload(row)
        with self._single_flight(ref_id):
            row = self._row(ref_id)  # whoever was in front of us may just have answered
            if row is not None and not self._due(row, refresh):
                return self._payload(row)
            return self._payload(self._look(ref, row))

    # ------------------------------------------------------------------ the record

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _row(self, ref_id: str) -> sqlite3.Row | None:
        with self._db.read() as conn:
            return conn.execute("SELECT * FROM lyrics WHERE ref = ?", (ref_id,)).fetchone()  # type: ignore[no-any-return]

    def _due(self, row: sqlite3.Row, refresh: bool) -> bool:
        now = self._now_ms()
        if refresh and now - row["fetched_at"] >= ASK_AGAIN_AFTER_S * 1000:
            return True
        return row["retry_at"] is not None and now >= row["retry_at"]

    def _payload(self, row: sqlite3.Row) -> dict[str, Any]:
        kind = row["kind"]
        body = json.loads(row["body"]) if row["body"] is not None else None
        return {
            "kind": kind,
            "lines": body if kind == "synced" else None,
            "text": body if kind == "plain" else None,
            "source": row["source"] if kind != "none" else None,
            "fetchedAt": row["fetched_at"],
            "retryAfterMs": max(0, row["retry_at"] - self._now_ms()) if kind == "none" and row["retry_at"] is not None else None,
        }

    def _save(self, ref_id: str, kind: str, body: Any, retry_in_s: int | None, misses: int) -> sqlite3.Row:
        now = self._now_ms()
        with self._db.tx() as conn:
            conn.execute(
                "INSERT INTO lyrics (ref, kind, body, source, fetched_at, retry_at, misses) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(ref) DO UPDATE SET kind = excluded.kind, body = excluded.body, source = excluded.source,"
                " fetched_at = excluded.fetched_at, retry_at = excluded.retry_at, misses = excluded.misses",
                (
                    ref_id,
                    kind,
                    json.dumps(body, ensure_ascii=False) if body is not None else None,
                    "lrclib",
                    now,
                    now + retry_in_s * 1000 if retry_in_s is not None else None,
                    misses,
                ),
            )
        row = self._row(ref_id)
        assert row is not None
        return row

    # ------------------------------------------------------------------ asking LRCLIB

    def _look(self, ref: dict[str, Any], old: sqlite3.Row | None) -> sqlite3.Row:
        ref_id = str(ref["id"])
        try:
            found = self._find(ref)
        except _Unavailable:
            if old is None:
                raise ApiError("source_unreachable", "This server cannot reach the lyrics service right now.") from None
            # A song that has an answer on record keeps it; the service is left alone for a while.
            with self._db.tx() as conn:
                conn.execute(
                    "UPDATE lyrics SET retry_at = ? WHERE ref = ?", (self._now_ms() + FAILED_LOOK_PAUSE_S * 1000, ref_id)
                )
            row = self._row(ref_id)
            assert row is not None
            return row
        if found is not None:
            kind, body = found
            again = {"plain": PLAIN_LOOK_AGAIN_S, "instrumental": INSTRUMENTAL_LOOK_AGAIN_S}.get(kind)
            return self._save(ref_id, kind, body, again, 0)
        if old is not None and old["kind"] in ("plain", "instrumental"):
            # Looked again for something better and found nothing: what was on record stays.
            again = PLAIN_LOOK_AGAIN_S if old["kind"] == "plain" else INSTRUMENTAL_LOOK_AGAIN_S
            return self._save(ref_id, old["kind"], json.loads(old["body"]) if old["body"] else None, again, 0)
        misses = (old["misses"] if old is not None and old["kind"] == "none" else 0) + 1
        return self._save(ref_id, "none", None, MISS_PAUSES_S[min(misses, len(MISS_PAUSES_S)) - 1], misses)

    def _find(self, ref: dict[str, Any]) -> tuple[str, Any] | None:
        title = str(ref["title"])
        artists = ref.get("artists") or []
        artist = str(artists[0]) if artists else None
        album = ref.get("album") or None
        duration_s = round(ref["durationMs"] / 1000) if ref.get("durationMs") else None
        exact = self._exact(title, artist, album, duration_s)
        if exact is not None and exact[0] in ("synced", "instrumental"):
            return exact
        searched = self._search(title, artist, duration_s)
        if searched is not None and (exact is None or searched[0] == "synced"):
            return searched  # a synced entry of the same length beats a plain one
        return exact

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            response = self._http.get(path, params=params)
        except httpx.HTTPError as error:
            log.info("the lyrics service did not answer %s: %s", path, type(error).__name__)
            raise _Unavailable from error
        if response.status_code in (400, 404):
            return None
        if response.status_code != 200:
            log.info("the lyrics service answered %s with HTTP %s", path, response.status_code)
            raise _Unavailable
        try:
            return response.json()
        except ValueError as error:
            raise _Unavailable from error

    def _exact(self, title: str, artist: str | None, album: str | None, duration_s: int | None) -> tuple[str, Any] | None:
        if not artist or not album or duration_s is None:
            return None  # the exact question needs all four; without them only the search can help
        entry = self._get("/get", {"track_name": title, "artist_name": artist, "album_name": album, "duration": duration_s})
        return _read_entry(entry)

    def _search(self, title: str, artist: str | None, duration_s: int | None) -> tuple[str, Any] | None:
        params: dict[str, Any] = {"track_name": title}
        if artist:
            params["artist_name"] = artist
        data = self._get("/search", params)
        if not isinstance(data, list):
            return None
        best: tuple[tuple[int, int], dict[str, Any]] | None = None
        for item in data:
            if not isinstance(item, dict):
                continue
            synced = bool(str(item.get("syncedLyrics") or "").strip())
            plain = bool(str(item.get("plainLyrics") or "").strip())
            if not synced and not plain:
                continue
            gap = 0
            if duration_s is not None:
                length = item.get("duration")
                if not isinstance(length, int | float):
                    continue
                gap = abs(round(length) - duration_s)
                if gap > tolerance_s(duration_s):
                    continue  # another version
            rank = (0 if synced else 1, gap)
            if best is None or rank < best[0]:
                best = (rank, item)
        return _read_entry(best[1]) if best is not None else None

    # ------------------------------------------------------------------ many at once

    @contextlib.contextmanager
    def _single_flight(self, ref_id: str) -> Iterator[None]:
        with self._guard:
            slot = self._inflight.setdefault(ref_id, [threading.Lock(), 0])
            slot[1] += 1
        slot[0].acquire()
        try:
            yield
        finally:
            slot[0].release()
            with self._guard:
                slot[1] -= 1
                if slot[1] == 0:
                    self._inflight.pop(ref_id, None)


def _read_entry(entry: Any) -> tuple[str, Any] | None:
    """What one LRCLIB entry holds, or `None` when it holds no usable lyrics."""
    if not isinstance(entry, dict):
        return None
    if entry.get("instrumental") is True:
        return "instrumental", None
    for key in ("syncedLyrics", "plainLyrics"):
        text = entry.get(key)
        if isinstance(text, str) and text.strip():
            kind, body = parse_lrc(text)
            if kind != "none":
                return kind, body
    return None
