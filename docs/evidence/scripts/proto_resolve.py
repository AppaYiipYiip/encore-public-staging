"""Prototype (measurement only, not product code): read a real playlist, resolve stream URLs in parallel in ONE warm process.

usage: python3 proto_resolve.py PLAYLIST_ID N WORKERS  > urls.json   (progress on stderr)
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import yt_dlp
from ytmusicapi import YTMusic

pid, n, workers = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
t0 = time.time()
tracks = YTMusic().get_playlist(pid, limit=None)["tracks"]
t1 = time.time()
print(f"list: {len(tracks)} songs in {t1 - t0:.1f} s", file=sys.stderr)

local = threading.local()


def ydl():
    if not hasattr(local, "y"):
        local.y = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                                    "format": "bestaudio[acodec=opus]/bestaudio"})
    return local.y


def resolve(t):
    s = time.time()
    try:
        info = ydl().extract_info(f"https://music.youtube.com/watch?v={t['videoId']}", download=False)
        return {"videoId": t["videoId"], "title": t["title"], "url": info["url"], "size": info.get("filesize"),
                "headers": info.get("http_headers"), "ms": round(1000 * (time.time() - s)), "ok": True}
    except Exception as e:  # noqa: BLE001
        return {"videoId": t["videoId"], "title": t["title"], "ok": False, "err": str(e)[:160],
                "ms": round(1000 * (time.time() - s))}


with ThreadPoolExecutor(workers) as pool:
    out = list(pool.map(resolve, [t for t in tracks if t.get("videoId")][:n]))
t2 = time.time()
ok = [o for o in out if o["ok"]]
lat = sorted(o["ms"] for o in ok)
print(f"resolved {len(ok)}/{len(out)} with {workers} workers in {t2 - t1:.1f} s "
      f"= {60 * len(ok) / (t2 - t1):.0f} songs/min; per-song p50 {lat[len(lat)//2] if lat else '-'} ms, "
      f"max {lat[-1] if lat else '-'} ms", file=sys.stderr)
for o in out:
    if not o["ok"]:
        print("FAILED", o["title"], o["err"], file=sys.stderr)
json.dump(ok, sys.stdout)
