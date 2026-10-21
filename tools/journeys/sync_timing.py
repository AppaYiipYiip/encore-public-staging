#!/usr/bin/env python3
"""R-16 live-sync timing: a 'second device' (this script, through the server's API) adds a song to a playlist; how long until the
phone's Library list shows the new count? The app must be in the foreground on Your Library > Playlists.
   python sync_timing.py <login file> <playlist name> [runs]
Password read from the login file, never printed."""
import hashlib, json, os, random, re, statistics, subprocess, sys, time, urllib.parse, urllib.request

ADB = r"C:\dev\android-sdk\platform-tools\adb.exe"
DEV = ["-s", "emulator-5556"]
path, name = sys.argv[1], sys.argv[2]
runs = int(sys.argv[3]) if len(sys.argv) > 3 else 8
cfg = {}
for line in open(path, encoding="utf-8"):
    if ":" in line and not line.startswith(" "):
        k, v = line.split(":", 1)
        if k in ("address", "user", "password"):
            cfg[k] = v.strip()


def api(method, **p):
    salt = "t" + hashlib.md5(os.urandom(6)).hexdigest()[:8]
    q = {"u": cfg["user"], "t": hashlib.md5((cfg["password"] + salt).encode()).hexdigest(), "s": salt, "v": "1.16.1", "c": "sync", "f": "json"}
    q.update(p)
    with urllib.request.urlopen(cfg["address"].rstrip("/") + "/rest/" + method + "?" + urllib.parse.urlencode(q, doseq=True), timeout=30) as r:
        return json.load(r)["subsonic-response"]


def screen_text():
    for _ in range(3):
        out = subprocess.run([ADB, *DEV, "exec-out", "uiautomator", "dump", "/dev/tty"], capture_output=True, text=True).stdout
        if "<hierarchy" in out:
            return out
        time.sleep(0.3)
    return ""


def count_on_screen():
    out = subprocess.run([ADB, *DEV, "exec-out", "uiautomator", "dump", "/dev/tty"], capture_output=True).stdout.decode("utf-8", "replace")
    m = re.search(re.escape(name) + r", Playlist\W{1,4}(\d+) songs?", out)
    return int(m.group(1)) if m else None


playlists = api("getPlaylists")["playlists"]["playlist"]
pid = next(p["id"] for p in playlists if p["name"] == name)
songs = [s["id"] for s in api("search3", query="", songCount=60, albumCount=0, artistCount=0)["searchResult3"]["song"]]
have = {e["id"] for e in api("getPlaylist", id=pid)["playlist"].get("entry", [])}
fresh = [s for s in songs if s not in have][:runs]
start = count_on_screen()
print(f"playlist {name!r}: {len(have)} songs on the server, {start} shown on the phone; {len(fresh)} runs")
if start is None:
    sys.exit("open Your Library > Playlists on the phone first")

times = []
for i, sid in enumerate(fresh, 1):
    before = count_on_screen()
    t0 = time.time()
    api("updatePlaylist", playlistId=pid, songIdToAdd=sid)
    seen = None
    while time.time() - t0 < 45:
        c = count_on_screen()
        if c is not None and c > (before or 0):
            seen = time.time() - t0
            break
    times.append(seen)
    print(f"run {i}: {'%.1f s' % seen if seen is not None else 'NOT SEEN within 45 s'}", flush=True)
    time.sleep(random.uniform(1.0, 8.0))  # random phase, so the result is not locked to the app's probe

ok = [t for t in times if t is not None]
if ok:
    ok_sorted = sorted(ok)
    p95 = ok_sorted[min(len(ok_sorted) - 1, int(round(0.95 * len(ok_sorted))) - 1)]
    print(f"p95 {p95:.1f} s (budget 5.0 s on the LAN, docs/00)")
    print(f"seen {len(ok)}/{len(times)}; median {statistics.median(ok):.1f} s, worst {max(ok):.1f} s, best {min(ok):.1f} s "
          f"(includes the screen reads: one `uiautomator dump` takes 2.1-2.4 s, so every figure is up to ~2 s above the app's real delay)")
