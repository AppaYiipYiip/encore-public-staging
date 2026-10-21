"""Hard cases for "tap -> sound": a 2-hour recitation (start + jump to 90%) and obscure songs never played on this server.

Fresh process: no Encore cache of any kind. Prints per case: search, extract, first byte, 256 KB, and for long files a seek.
"""
import sys
import time
import urllib.request

import yt_dlp
from ytmusicapi import YTMusic

ytm = YTMusic()
ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                        "format": "bestaudio[acodec=opus]/bestaudio"})


def ranged(url, hdrs, start, length):
    h = dict(hdrs)
    h["Range"] = f"bytes={start}-{start + length - 1}"
    s = time.time()
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        r.read(1)
        first = time.time() - s
        r.read()
        return first, time.time() - s


def case(label, query, filt):
    t0 = time.time()
    hits = ytm.search(query, filter=filt, limit=5)
    t1 = time.time()
    if not hits:
        print(f"{label}: no hits"); return
    h = hits[0]
    info = ydl.extract_info(f"https://music.youtube.com/watch?v={h['videoId']}", download=False)
    t2 = time.time()
    url, hdrs = info["url"], dict(info.get("http_headers") or {})
    size = info.get("filesize") or info.get("filesize_approx") or 0
    first, full = ranged(url, hdrs, 0, 256 * 1024)
    line = (f"{label}: '{h.get('title')}' {h.get('duration')} ({size/1e6:.0f} MB) | search {1000*(t1-t0):.0f} ms | "
            f"extract {1000*(t2-t1):.0f} ms | first byte {1000*first:.0f} ms | 256 KB {1000*full:.0f} ms | "
            f"TOTAL to sound-ready {1000*(t2-t0+full):.0f} ms")
    if size > 20e6:
        f2, full2 = ranged(url, hdrs, int(size * 0.9), 256 * 1024)
        line += f" | jump to 90%: first byte {1000*f2:.0f} ms, 256 KB {1000*full2:.0f} ms"
    print(line, flush=True)


case("2-hour recitation", "Surah Al-Baqarah full Mishary Rashid Alafasy", "videos")
case("obscure 1", "Oum Taragalte Alhrir", "songs")
case("obscure 2", "Mehdi Nassouli Mogador", "songs")
case("obscure 3", "Hindi Zahra Kiss & Thrills", "songs")
