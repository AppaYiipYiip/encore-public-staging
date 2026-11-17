#!/usr/bin/env python3
"""Records what Deezer's public API really answers for each shape the catalogue routes of the server read (P2-12): the fixtures of
`server/encore_server/tests/fixtures/deezer/`, one file per shape, `{recorded, path, params, answer}`.

    python tools/record_catalogue_fixtures.py            # writes next to the tests

NOT run by CI and not run by an agent without the lead's word: it makes 11 requests (spaced by 0.7 s, one artist, one album, three charts,
three artist searches), from the machine it runs on, so the machine's address is what Deezer sees (a development machine, never a Host's).
The signed preview addresses Deezer puts in a song (they carry a token that expires) and the share links are taken out before anything is written.
The searches for albums and songs are not recorded here: `app/test/fixtures/deezer/search.json` holds 20 real ones (`record_deezer_fixtures.py`).

**The `n34` mode (N-34 slice 1, step 0)** records the answers the album matcher is tested on, a few requests at a time, by the lead's leave and never more
than `N34_CAP` (10) in all: the plain `/search` the server's finders send (`search_tracks`: `q="<artist> <title>"`, 8 rows), an album, an album's song list,
an artist's list of releases. Every ATTEMPT is written to `n34_requests.json` BEFORE it is made (a failure counts, there is no retry), and the tool
refuses the 11th: the count is the file, not the operator's memory. It asks Deezer only, paced by 0.7 s.

    python tools/record_catalogue_fixtures.py n34 search "LANDMVRKS Requiem" "LANDMVRKS Creature"
    python tools/record_catalogue_fixtures.py n34 album 12114248 12114262
    python tools/record_catalogue_fixtures.py n34 tracks 12114248
    python tools/record_catalogue_fixtures.py n34 artist-albums 860
    python tools/record_catalogue_fixtures.py n34 count
"""

import argparse
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "server" / "encore_server" / "tests" / "fixtures" / "deezer"
# The ONE function that names a recorded answer is the server package's own (`encore_server/fixture_names.py`, standard library only): the dry run replays by it and
# the tests' fake finds by it, so a copy here would drift (it did: an ASCII-only copy named every non-Latin search `search_track_`).
sys.path.insert(0, str(ROOT / "server" / "encore_server"))
from encore_server.fixture_names import fixture_name  # noqa: E402

DROP = {"preview", "share", "md5_image"}
CHART_ROWS = {"tracks": 12}  # the songs chart is long and only its shape matters


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in DROP}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def get(path: str, **params):
    url = "https://api.deezer.com" + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    request = urllib.request.Request(url, headers={"User-Agent": "encore-server/recording"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    time.sleep(0.7)
    return data


def save(name: str, path: str, params: dict, data) -> None:
    save_to(OUT, name, path, params, data)


def save_to(out: pathlib.Path, name: str, path: str, params: dict, data) -> None:
    out.mkdir(parents=True, exist_ok=True)
    kept = scrub(data)
    for kind, rows in CHART_ROWS.items():
        if name == f"chart_0_{kind}" and isinstance(kept.get("data"), list):
            kept["data"] = kept["data"][:rows]
    body = {"recorded": date.today().isoformat(), "path": path, "params": params, "answer": kept}
    (out / f"{name}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{name}: {path} {params}")


def main() -> None:
    found = get("/search/artist", q="bob marley", limit=8)
    save("search_artist_bob_marley", "/search/artist", {"q": "bob marley", "limit": 8}, found)
    artist_id = found["data"][0]["id"]
    save("artist", "/artist/{id}", {}, get(f"/artist/{artist_id}"))
    save("artist_top", "/artist/{id}/top", {"limit": 10}, get(f"/artist/{artist_id}/top", limit=10))
    albums = get(f"/artist/{artist_id}/albums", limit=50)
    save("artist_albums", "/artist/{id}/albums", {"limit": 50}, albums)
    album_id = albums["data"][0]["id"]
    save("album", "/album/{id}", {}, get(f"/album/{album_id}"))
    save("album_tracks", "/album/{id}/tracks", {"limit": 100}, get(f"/album/{album_id}/tracks", limit=100))
    for kind, limit in (("tracks", 25), ("artists", 15), ("albums", 15)):
        save(f"chart_0_{kind}", "/chart/{genre}/" + kind, {"limit": limit}, get(f"/chart/0/{kind}", limit=limit))
    for query in ("landmvrks", "landmarks"):
        save(f"search_artist_{query}", "/search/artist", {"q": query, "limit": 8}, get("/search/artist", q=query, limit=8))


# ------------------------------------------------------------------------------------------------------------------ N-34 slice 1, step 0

#: The most requests the N-34 recording may make in all, over every run of it. The lead's leave (16 Nov 2026) is "at most 10, to Deezer only".
N34_CAP = 10
N34_LEDGER_NAME = "n34_requests.json"
#: What the server's own calls send: `deezer.search_tracks` (limit 8), `Catalogue.album` (the songs of an album, 100) and `Catalogue.artist_page` (200 releases).
N34_SEARCH_LIMIT, N34_TRACKS_LIMIT, N34_RELEASES_LIMIT = 8, 100, 200


class CapSpent(RuntimeError):
    """The ledger holds [N34_CAP] attempts: nothing more is asked."""


class Ledger:
    """`n34_requests.json`: every attempt, written before the request is made and finished after it. The count of attempts is `len(attempts)`."""

    def __init__(self, path: pathlib.Path, cap: int = N34_CAP) -> None:
        self.path = path
        self.cap = cap
        self.attempts: list[dict] = json.loads(path.read_text(encoding="utf-8"))["attempts"] if path.exists() else []

    def _write(self) -> None:
        body = {"cap": self.cap, "attempts": self.attempts}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    def begin(self, path: str, params: dict) -> None:
        if len(self.attempts) >= self.cap:
            raise CapSpent(f"{len(self.attempts)} of {self.cap} requests are spent: nothing more is asked")
        self.attempts.append(
            {"path": path, "params": params, "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "outcome": "started"}
        )
        self._write()

    def finish(self, outcome: str) -> None:
        self.attempts[-1]["outcome"] = outcome
        self._write()


def n34_ask(ledger: Ledger, path: str, **params):
    """One counted request: the attempt is in the ledger before the connection is made, a failure is counted and is not retried."""
    ledger.begin(path, params)
    try:
        data = get(path, **params)
    except Exception as error:  # noqa: BLE001 - whatever went wrong is written down and re-raised
        ledger.finish(f"failed: {type(error).__name__}")
        raise
    ledger.finish("ok")
    return data


def n34_main(argv: list[str], out: pathlib.Path = OUT) -> int:
    parser = argparse.ArgumentParser(prog="record_catalogue_fixtures.py n34", description="the N-34 step-0 recordings, at most 10 requests in all")
    parser.add_argument("kind", choices=("search", "album", "tracks", "artist-albums", "count"))
    parser.add_argument("what", nargs="*", help="queries (search) or Deezer ids (the others)")
    args = parser.parse_args(argv)
    ledger = Ledger(out / N34_LEDGER_NAME)
    print(f"requests made so far: {len(ledger.attempts)} of {ledger.cap}")
    if args.kind == "count":
        return 0
    if len(args.what) > ledger.cap - len(ledger.attempts):
        print(f"refused: {len(args.what)} asked, {ledger.cap - len(ledger.attempts)} left", file=sys.stderr)
        return 2
    for item in args.what:
        if args.kind == "search":
            path, params = "/search", {"q": item, "limit": N34_SEARCH_LIMIT}
        elif not (item.isascii() and item.isdigit()):
            print(f"refused: {item!r} is not a Deezer id", file=sys.stderr)
            return 2
        elif args.kind == "album":
            path, params = f"/album/{item}", {}
        elif args.kind == "tracks":
            path, params = f"/album/{item}/tracks", {"limit": N34_TRACKS_LIMIT}
        else:
            path, params = f"/artist/{item}/albums", {"limit": N34_RELEASES_LIMIT}
        name = fixture_name(path, params)
        if name is None:  # a search with an empty query: nothing to name, nothing to ask
            print(f"refused: {item!r} has no name to save an answer under", file=sys.stderr)
            return 2
        try:
            answer = n34_ask(ledger, path, **params)
        except CapSpent as error:
            print(f"refused: {error}", file=sys.stderr)
            return 2
        save_to(out, name, path, params, answer)
    print(f"requests made so far: {len(ledger.attempts)} of {ledger.cap}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["n34"]:
        sys.exit(n34_main(sys.argv[2:]))
    main()
