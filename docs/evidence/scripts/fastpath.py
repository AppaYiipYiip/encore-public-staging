"""Hypothesis H2/H3: a lean resolver (one YouTube Music search, one extraction, in a warm process) reaches audio in a few seconds.

Prints, per query: search ms, extract ms, first byte ms, 256 KB ms, and what was picked. Standard output only; no files kept.
"""
import json
import sys
import time
import urllib.request

import yt_dlp
from ytmusicapi import YTMusic

QUERIES = sys.argv[1:] or [
    "Khruangbin Maria Tambien",
    "Daft Punk Instant Crush",
    "Opeth Windowpane",
    "Nas N.Y. State of Mind",
    "Fairuz Kifak Inta",
]

t = time.time()
ytm = YTMusic()
ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                        "format": "bestaudio[acodec=opus]/bestaudio"})
print(f"setup {1000 * (time.time() - t):.0f} ms (one-time, process start)")

for q in QUERIES:
    t0 = time.time()
    hits = ytm.search(q, filter="songs", limit=5)
    t1 = time.time()
    if not hits:
        print(f"{q!r}: no hits")
        continue
    h = hits[0]
    vid = h.get("videoId")
    who = ", ".join(a["name"] for a in h.get("artists") or [])
    info = ydl.extract_info(f"https://music.youtube.com/watch?v={vid}", download=False)
    t2 = time.time()
    url = info.get("url")
    hdrs = dict(info.get("http_headers") or {})
    hdrs["Range"] = "bytes=0-262143"
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=30) as r:
        first = r.read(1)
        t3 = time.time()
        rest = r.read()
        t4 = time.time()
    print(f"{q!r}: search {1000*(t1-t0):.0f} | extract {1000*(t2-t1):.0f} | first byte {1000*(t3-t2):.0f} | "
          f"256KB {1000*(t4-t2):.0f} | TOTAL to first byte {1000*(t3-t0):.0f} ms  -> {h.get('title')} / {who} / "
          f"{(h.get('album') or {}).get('name')} / {h.get('duration')} / itag {info.get('format_id')}")
