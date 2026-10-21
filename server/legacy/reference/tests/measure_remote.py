#!/usr/bin/env python3
"""What would a listener get through this address? (docs/33 section 8, T4)

    ENCORE_USER=name ENCORE_PASSWORD=secret python3 measure_remote.py https://music.example.ts.net
    ... --baseline http://192.168.1.50:4533   also measure the direct home address, to compare
    ... --seconds 30                          length of the sustained download (default 60)

It asks the server's own Subsonic API for a big song and measures, through the address you give it:
  * the time to answer a ping (connection + TLS + one request),
  * play-start: the time until the first 16 KB of a small Opus stream (what the phone plays on mobile data) arrive,
  * the sustained speed of a plain download (not limited by the song's own bitrate), and the slowest 5 seconds of it,
  * that a Range request (seeking) is answered with 206.
It then says PASS or FAIL against the targets of docs/33: sustained at least 2 Mbit/s, play-start at most 3 s, Range 206.

Credentials come from the environment only and are never printed. Standard library only.
If you run it from inside the same house as the server, a public address makes the stream leave the house and come back,
so the home upload line is in the path exactly as it is for a listener far away.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MIN_MBIT = 2.0
MAX_PLAY_START_S = 3.0


def url_for(base: str, user: str, password: str, method: str, **params: str) -> str:
    salt = "m" + hashlib.md5(os.urandom(8)).hexdigest()[:8]
    token = hashlib.md5((password + salt).encode()).hexdigest()
    query = urllib.parse.urlencode({"u": user, "t": token, "s": salt, "v": "1.16.1", "c": "measure",
                                    "f": "json", **params})
    return f"{base.rstrip('/')}/rest/{method}?{query}"


def get_json(base: str, user: str, password: str, method: str, **params: str) -> dict:
    with urllib.request.urlopen(url_for(base, user, password, method, **params), timeout=30) as response:
        body = json.loads(response.read())["subsonic-response"]
    if body.get("status") != "ok":
        raise SystemExit(f"{method} failed: {body.get('error', body)}")
    return body


def biggest_song(base: str, user: str, password: str) -> tuple[str, int, str]:
    body = get_json(base, user, password, "search3", query="", songCount="500", albumCount="0", artistCount="0")
    songs = body.get("searchResult3", {}).get("song", [])
    if not songs:
        raise SystemExit("the library has no songs to measure with; copy one in first")
    song = max(songs, key=lambda s: int(s.get("size", 0)))
    return song["id"], int(song.get("size", 0)), song.get("title", "?")


def measure_one(label: str, base: str, user: str, password: str, song_id: str, seconds: float) -> dict:
    out: dict = {"label": label}

    t0 = time.perf_counter()
    get_json(base, user, password, "ping")
    out["ping_s"] = time.perf_counter() - t0

    # Play-start: first 16 KB of a small Opus stream, as the phone asks for it on mobile data.
    starts = []
    for _ in range(3):
        t0 = time.perf_counter()
        with urllib.request.urlopen(url_for(base, user, password, "stream", id=song_id, format="opus",
                                            maxBitRate="96"), timeout=30) as response:
            got = 0
            while got < 16 * 1024:
                chunk = response.read(4096)
                if not chunk:
                    break
                got += len(chunk)
        starts.append(time.perf_counter() - t0)
    out["play_start_s"] = statistics.median(starts)
    out["play_start_all"] = starts

    # Sustained speed: the original file as it is, as fast as the path allows.
    request = urllib.request.Request(url_for(base, user, password, "download", id=song_id))
    t_start = time.perf_counter()
    total, marks = 0, [(0.0, 0)]
    with urllib.request.urlopen(request, timeout=30) as response:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                out["note"] = "the whole file was read before the time was up"
                break
            total += len(chunk)
            elapsed = time.perf_counter() - t_start
            if elapsed - marks[-1][0] >= 1.0:
                marks.append((elapsed, total))
            if elapsed >= seconds:
                break
    elapsed = max(time.perf_counter() - t_start, 1e-9)
    out["bytes"] = total
    out["seconds"] = elapsed
    out["mbit"] = total * 8 / elapsed / 1e6
    window = [(marks[i + 5][1] - marks[i][1]) * 8 / (marks[i + 5][0] - marks[i][0]) / 1e6
              for i in range(len(marks) - 5)] if len(marks) > 5 else []
    out["slowest_5s_mbit"] = min(window) if window else None

    # Seeking.
    request = urllib.request.Request(url_for(base, user, password, "download", id=song_id),
                                     headers={"Range": "bytes=65536-131071"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            out["range_status"] = response.status
            out["range_bytes"] = len(response.read())
    except urllib.error.HTTPError as error:
        out["range_status"] = error.code
        out["range_bytes"] = 0
    return out


def show(r: dict) -> None:
    slow = f"{r['slowest_5s_mbit']:.1f}" if r.get("slowest_5s_mbit") is not None else "n/a"
    print(f"\n{r['label']}")
    print(f"  ping                 {r['ping_s'] * 1000:7.0f} ms")
    print(f"  play-start (median)  {r['play_start_s']:7.2f} s   (three tries: "
          f"{', '.join(f'{x:.2f}' for x in r['play_start_all'])})")
    print(f"  sustained download   {r['mbit']:7.2f} Mbit/s over {r['seconds']:.0f} s "
          f"({r['bytes'] / 1e6:.1f} MB); slowest 5 s: {slow} Mbit/s" + (f"  [{r['note']}]" if r.get("note") else ""))
    print(f"  Range request        {r['range_status']} ({r['range_bytes']} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("address", help="the public address to measure, e.g. https://music.example.ts.net")
    parser.add_argument("--baseline", help="a direct address (the home network) measured the same way")
    parser.add_argument("--seconds", type=float, default=60.0, help="length of the sustained download")
    args = parser.parse_args()

    user, password = os.environ.get("ENCORE_USER"), os.environ.get("ENCORE_PASSWORD")
    if not user or not password:
        print("Set ENCORE_USER and ENCORE_PASSWORD (environment only; they are never printed).", file=sys.stderr)
        return 2

    song_id, size, title = biggest_song(args.baseline or args.address, user, password)
    print(f"measuring with the biggest song, '{title}' ({size / 1e6:.1f} MB)")
    if size < 20e6:
        print("note: this song is small; the sustained figure may end before the time is up. "
              "Copy a long lossless file in for a fuller picture.")

    results = []
    if args.baseline:
        results.append(measure_one("direct (baseline)", args.baseline, user, password, song_id, args.seconds))
    results.append(measure_one("through the public address", args.address, user, password, song_id, args.seconds))
    for r in results:
        show(r)

    r = results[-1]
    problems = []
    if r["mbit"] < MIN_MBIT and "note" not in r:
        problems.append(f"sustained {r['mbit']:.2f} Mbit/s is under {MIN_MBIT}")
    if r["play_start_s"] > MAX_PLAY_START_S:
        problems.append(f"play-start {r['play_start_s']:.2f} s is over {MAX_PLAY_START_S}")
    if r["range_status"] != 206:
        problems.append(f"Range answered {r['range_status']}, not 206")
    print()
    if problems:
        print("FAIL: " + "; ".join(problems))
        return 1
    print(f"PASS: at least {MIN_MBIT} Mbit/s sustained, play-start within {MAX_PLAY_START_S} s, Range works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
