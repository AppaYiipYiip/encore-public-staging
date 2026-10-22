#!/usr/bin/env python3
"""Records what Deezer's public search really answers for a list of typed queries (the three calls the app makes), so the search
ranking is tested on real answers: `app/test/fixtures/deezer/search.json`.

    python tools/record_deezer_fixtures.py

Deezer's public API needs no key; one query is three requests, spaced by half a second. Only the fields the app reads are kept."""
import json
import pathlib
import time
import urllib.parse
import urllib.request

QUERIES = [
    "daft punk instant crush", "radiohead weird fishes", "fairuz kifak inta", "opeth windowpane", "nas ny state of mind",
    "beach house space song", "mazzy star fade into you", "blinding lights", "the weeknd blinding lights", "taylor swift cardigan",
    "kendrick lamar humble", "drake gods plan", "tame impala let it happen", "cairokee", "oum kalthoum enta omri",
    "pink floyd comfortably numb", "billie eilish", "hotel california", "bohemian rhapsody", "ed sheeran shape of you",
]
KEEP = {
    "artist": ("id", "name", "picture_xl", "nb_fan", "nb_album"),
    "album": ("id", "title", "cover_xl", "nb_tracks", "record_type", "release_date", "artist"),
    "track": ("id", "title", "duration", "preview", "artist", "album", "rank", "explicit_lyrics"),
}


def get(kind: str, query: str, limit: int) -> list:
    url = f"https://api.deezer.com/search/{kind}?" + urllib.parse.urlencode({"q": query, "limit": limit})
    request = urllib.request.Request(url, headers={"User-Agent": "Encore/0.1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.load(response).get("data") or []
    keep = KEEP[kind]
    slim = []
    for item in data:
        row = {k: item[k] for k in keep if k in item}
        if "artist" in row and isinstance(row["artist"], dict):
            row["artist"] = {k: row["artist"].get(k) for k in ("id", "name")}
        if "album" in row and isinstance(row["album"], dict):
            row["album"] = {k: row["album"].get(k) for k in ("id", "title", "cover_xl")}
        slim.append(row)
    return slim


def main() -> None:
    out = {}
    for query in QUERIES:
        out[query] = {"artist": get("artist", query, 8), "album": get("album", query, 8), "track": get("track", query, 8)}
        time.sleep(0.5)
        print(f"{query:34} artists={len(out[query]['artist'])} albums={len(out[query]['album'])} tracks={len(out[query]['track'])}")
    target = pathlib.Path(__file__).resolve().parent.parent / "app" / "test" / "fixtures" / "deezer"
    target.mkdir(parents=True, exist_ok=True)
    (target / "search.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written", target / "search.json")


if __name__ == "__main__":
    main()
