"""How fast can an import read the LIST of a real playlist (no audio)? Real public playlists only.

1. Find real public YouTube Music playlists by searching YouTube Music itself, read the biggest one in full.
2. Read the owner's real public Spotify playlists (ids given by the owner on 2026-10-18) through Spotify's public embed page.
"""
import json
import re
import sys
import time
import urllib.request

from ytmusicapi import YTMusic

ytm = YTMusic()

t0 = time.time()
found = ytm.search("top hits 2026", filter="community_playlists", limit=10)
found += ytm.search("rap francais", filter="featured_playlists", limit=10)
t1 = time.time()
print(f"playlist search: {1000*(t1-t0):.0f} ms, {len(found)} playlists")
best = sorted(found, key=lambda p: int(re.sub(r"\D", "", str(p.get("itemCount") or "0")) or 0), reverse=True)[:2]
for p in best:
    pid = p["browseId"]
    t2 = time.time()
    pl = ytm.get_playlist(pid, limit=None)
    t3 = time.time()
    tracks = pl.get("tracks") or []
    with_vid = sum(1 for t in tracks if t.get("videoId"))
    print(f"YouTube Music playlist {p.get('title')!r} ({pid}): {len(tracks)} songs read in {1000*(t3-t2):.0f} ms; "
          f"{with_vid} already carry their video id (no matching needed); first: "
          f"{tracks[0]['title'] if tracks else '-'} / {', '.join(a['name'] for a in (tracks[0].get('artists') or [])) if tracks else ''}")

for sid in ["3dEfExamplePlaylistC03", "3dEfExamplePlaylistB02", "3dEfExamplePlaylistA01"]:
    t4 = time.time()
    req = urllib.request.Request(f"https://open.spotify.com/embed/playlist/{sid}",
                                 headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"})
    try:
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"Spotify {sid}: failed {e}")
        continue
    t5 = time.time()
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    n = 0
    name = "?"
    if m:
        data = json.loads(m.group(1))
        ent = (((data.get("props") or {}).get("pageProps") or {}).get("state") or {}).get("data", {}).get("entity", {})
        name = ent.get("name") or ent.get("title") or "?"
        n = len(ent.get("trackList") or [])
    print(f"Spotify playlist {name!r} ({sid}): {n} songs read in {1000*(t5-t4):.0f} ms (embed page, {len(html)//1024} KB)")
