"""Records real YouTube Music search answers as test fixtures (docs/24 section 3).

Run rarely (when a test needs a new query), never in CI. At most a handful of look-ups, spaced 2 s apart, from a developer machine:
    python tools/record_ytm_fixtures.py

Needs `pip install ytmusicapi`. Writes server/legacy/encore-fetch/tests/fixtures/ytm/<slug>.json with
{"query", "filter", "recorded", "results"} where results is ytmusicapi's own list, trimmed of fields no test uses.
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "server" / "legacy" / "encore-fetch" / "tests" / "fixtures" / "ytm"

# (artist, title, filter): real queries as people type them, covering mainstream, obscure, non-Latin and long content.
# For songs both word orders are recorded, because YouTube Music answers them differently (docs/19 section 4).
SPECS = [
    ("Khruangbin", "Maria Tambien", "songs"),
    ("Daft Punk", "Instant Crush", "songs"),
    ("Radiohead", "Weird Fishes", "songs"),
    ("Nas", "N.Y. State of Mind", "songs"),
    ("Fairuz", "Kifak Inta", "songs"),
    ("Oum", "Taragalte", "songs"),
    ("Mishary Alafasy", "Surah Al-Baqarah", "videos"),
]

KEEP = ("videoId", "title", "artists", "album", "duration", "duration_seconds", "resultType", "isExplicit", "year", "category",
        "views")


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def main() -> int:
    from ytmusicapi import YTMusic

    ytm = YTMusic()
    OUT.mkdir(parents=True, exist_ok=True)
    done = 0
    for artist, title, flt in SPECS:
        variants = [f"{artist} {title}", f"{title} {artist}"] if flt == "songs" else [f"{title} {artist}"]
        for query in variants:
            path = OUT / f"{slug(query)}.{flt}.json"
            if path.exists():
                continue  # recorded already: never ask again (at most a handful of look-ups per run)
            results = ytm.search(query, filter=flt, limit=8)
            trimmed = [{k: r[k] for k in KEEP if k in r} for r in results]
            path.write_text(json.dumps({"query": query, "filter": flt, "recorded": date.today().isoformat(), "results": trimmed},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{query!r} [{flt}]: {len(trimmed)} results -> {path.name}")
            done += 1
            time.sleep(2)
            if done >= 10:
                print("stopping at 10 look-ups; run again for the rest")
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
