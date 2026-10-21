"""Prototype (measurement only): download already-resolved stream URLs in parallel from THIS machine.

usage: python proto_download.py urls.json COUNT WORKERS
Proves whether a device on the same home connection can fetch the audio itself (no server download, no server cap).
Files are read into memory and discarded.
"""
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

items = json.load(open(sys.argv[1], encoding="utf-8"))[: int(sys.argv[2])]
workers = int(sys.argv[3])


def fetch(it):
    s = time.time()
    hdrs = dict(it.get("headers") or {})
    total = 0
    first = None
    # Ranged requests of 2 MB, the way players and yt-dlp avoid YouTube's per-request throttling.
    start = 0
    while True:
        h = dict(hdrs)
        h["Range"] = f"bytes={start}-{start + 2 * 1024 * 1024 - 1}"
        try:
            with urllib.request.urlopen(urllib.request.Request(it["url"], headers=h), timeout=60) as r:
                data = r.read()
                if first is None:
                    first = time.time() - s
                cr = r.headers.get("Content-Range", "")
        except Exception as e:  # noqa: BLE001
            return {"title": it["title"], "ok": False, "err": str(e)[:120]}
        total += len(data)
        size = int(cr.split("/")[-1]) if "/" in cr else total
        start += len(data)
        if not data or start >= size:
            break
    return {"title": it["title"], "ok": True, "bytes": total, "s": time.time() - s, "first": first}


t0 = time.time()
with ThreadPoolExecutor(workers) as pool:
    res = list(pool.map(fetch, items))
dt = time.time() - t0
ok = [r for r in res if r["ok"]]
mb = sum(r["bytes"] for r in ok) / 1e6
print(f"downloaded {len(ok)}/{len(res)} songs, {mb:.1f} MB in {dt:.1f} s = {mb / dt:.2f} MB/s with {workers} workers; "
      f"first byte p50 {sorted(r['first'] for r in ok)[len(ok)//2]:.2f} s" if ok else "nothing downloaded")
for r in res:
    if not r["ok"]:
        print("FAILED", r["title"], r["err"])
