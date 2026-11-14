#!/usr/bin/env python3
"""Records what Deezer's public API really answers for each shape the catalogue routes of the server read (P2-12): the fixtures of
`server/encore_server/tests/fixtures/deezer/`, one file per shape, `{recorded, path, params, answer}`.

    python tools/record_catalogue_fixtures.py            # writes next to the tests

NOT run by CI and not run by an agent without the lead's word: it makes 11 requests (spaced by 0.7 s, one artist, one album, three charts,
three artist searches), from the machine it runs on, so the machine's address is what Deezer sees (a development machine, never a Host's).
The signed preview addresses Deezer puts in a song (they carry a token that expires) and the share links are taken out before anything is written.
The searches for albums and songs are not recorded here: `app/test/fixtures/deezer/search.json` holds 20 real ones (`record_deezer_fixtures.py`).
"""

import json
import pathlib
import time
import urllib.parse
import urllib.request
from datetime import date

OUT = pathlib.Path(__file__).resolve().parents[1] / "server" / "encore_server" / "tests" / "fixtures" / "deezer"
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
    OUT.mkdir(parents=True, exist_ok=True)
    kept = scrub(data)
    for kind, rows in CHART_ROWS.items():
        if name == f"chart_0_{kind}" and isinstance(kept.get("data"), list):
            kept["data"] = kept["data"][:rows]
    body = {"recorded": date.today().isoformat(), "path": path, "params": params, "answer": kept}
    (OUT / f"{name}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
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


if __name__ == "__main__":
    main()
