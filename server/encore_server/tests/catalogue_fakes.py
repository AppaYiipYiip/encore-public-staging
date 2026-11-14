"""The catalogue as the tests of P2-12 see it: Deezer's REAL answers, recorded (never made up), served by a mock transport that counts what is asked.

* `tests/fixtures/deezer/*.json` are the answers recorded on 14 Nov 2026 by the lead (`{recorded, path, params, answer}`), with the signed preview
  addresses taken out; `app/test/fixtures/deezer/search.json` holds the 20 searches recorded on 22 Oct 2026 (album and track rows).
* Only the ERROR answers (a refusal, the throttling body, a timeout) are written here: they are the answers a test must be able to ask for and must
  not make the real catalogue give.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
RECORDED = HERE / "fixtures" / "deezer"
SEARCHES = HERE.parents[2] / "app" / "test" / "fixtures" / "deezer" / "search.json"

#: What is in the recordings: Bob Marley & The Wailers, the album "Roots, Rock, Reggae (Live At The Hammersmith Odeon...)".
ARTIST_ID = "719"
ALBUM_ID = "1059353762"

NO_DATA = {"error": {"type": "DataException", "message": "no data", "code": 800}}
QUOTA = {"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}}


def recorded(name: str) -> dict[str, Any]:
    return json.loads((RECORDED / f"{name}.json").read_text(encoding="utf-8"))["answer"]  # type: ignore[no-any-return]


def searches() -> dict[str, dict[str, list[dict[str, Any]]]]:
    return json.loads(SEARCHES.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


Reply = tuple[int, Any] | Exception | Callable[[httpx.Request], httpx.Response]


class RecordedDeezer:
    """A `httpx.MockTransport` handler that answers from the recordings, counts every request and can be told to fail a path."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        #: path -> what to answer instead of the recording (a status and a body, an exception to raise, or a function)
        self.overrides: dict[str, Reply] = {}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def count(self, prefix: str = "") -> int:
        return sum(1 for path in self.paths() if path.startswith(prefix))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        override = self.overrides.get(request.url.path)
        if isinstance(override, Exception):
            raise override
        if callable(override):
            return override(request)
        if override is not None:
            return httpx.Response(override[0], json=override[1])
        return httpx.Response(200, json=self.answer(request.url.path, dict(request.url.params)))

    def answer(self, path: str, params: dict[str, str]) -> Any:
        if (
            path == "/search"
        ):  # the plain search the finders use: songs, as the recorded searches list them (the query is matched without its case)
            row = searches().get(params.get("q", "").lower())
            songs = row["track"] if row else []
            return {"data": songs[: int(params.get("limit", "8"))], "total": len(songs)}
        if match := re.fullmatch(r"/search/(artist|album|track)", path):
            kind = match.group(1)
            query = params.get("q", "")
            if kind == "artist":
                for name in ("bob_marley", "landmarks", "landmvrks"):
                    if params.get("q") == name.replace("_", " "):
                        return recorded(f"search_artist_{name}")
            row = searches().get(query)
            return (
                {"data": row[kind][: int(params.get("limit", "8"))], "total": len(row[kind])} if row else {"data": [], "total": 0}
            )
        known = {
            rf"/artist/{ARTIST_ID}": "artist",
            rf"/artist/{ARTIST_ID}/top": "artist_top",
            rf"/artist/{ARTIST_ID}/albums": "artist_albums",
            rf"/album/{ALBUM_ID}": "album",
            rf"/album/{ALBUM_ID}/tracks": "album_tracks",
            r"/chart/0/tracks": "chart_0_tracks",
            r"/chart/0/artists": "chart_0_artists",
            r"/chart/0/albums": "chart_0_albums",
        }
        for pattern, name in known.items():
            if re.fullmatch(pattern, path):
                return recorded(name)
        return NO_DATA  # Deezer answers HTTP 200 with this for a thing that does not exist
