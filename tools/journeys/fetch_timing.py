#!/usr/bin/env python3
"""J-04 on the real server: ask the "play any song" service for a song the library lacks, time every stage, then check that the
music server lists it for that person.
   python fetch_timing.py <login file> "<artist>" "<title>" ["<album>"] [--port 8701]
The password is read from the login file and never printed. Standard library only."""
import hashlib, json, os, sys, time, urllib.error, urllib.parse, urllib.request

args = [a for a in sys.argv[1:] if not a.startswith("--")]
port = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--port=")), 8701))
path, artist, title = args[0], args[1], args[2]
album = args[3] if len(args) > 3 else None

cfg = {}
for line in open(path, encoding="utf-8"):
    if ":" in line and not line.startswith(" "):
        k, v = line.split(":", 1)
        if k in ("address", "user", "password"):
            cfg[k] = v.strip()
host = urllib.parse.urlsplit(cfg["address"]).hostname
base = f"http://{host}:{port}"


def auth() -> dict:
    salt = "f" + hashlib.md5(os.urandom(6)).hexdigest()[:8]
    return {"u": cfg["user"], "t": hashlib.md5((cfg["password"] + salt).encode()).hexdigest(), "s": salt}


def call(method: str, route: str, body: dict | None = None):
    url = base + route + ("&" if "?" in route else "?") + urllib.parse.urlencode(auth())
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def subsonic(method: str, **p):
    q = {**auth(), "v": "1.16.1", "c": "fetchtest", "f": "json", **p}
    with urllib.request.urlopen(cfg["address"].rstrip("/") + "/rest/" + method + "?" + urllib.parse.urlencode(q), timeout=30) as r:
        return json.load(r)["subsonic-response"]


print("service:", call("GET", "/api/info")[1])
want = {"artist": artist, "title": title, "priority": "now"}
if album:
    want["album"] = album
t0 = time.time()
status, job = call("POST", "/api/play", want)
print(f"POST /api/play -> {status} {job.get('state')}  (+{time.time() - t0:.1f}s)")
if status not in (200, 202):
    sys.exit(f"refused: {job}")
jid = job["id"]
seen, first_audio = {}, None
while time.time() - t0 < 180:
    _, j = call("GET", f"/api/play/{jid}")
    state = j.get("state")
    if state not in seen:
        seen[state] = time.time() - t0
        print(f"  +{seen[state]:5.1f}s  {state}  {j.get('detail', '')}")
    if j.get("stream") and first_audio is None:
        # the first bytes of the song, played while it is still downloading
        req = urllib.request.Request(base + j["stream"] + "?" + urllib.parse.urlencode(auth()))
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                got = r.read(32 * 1024)
            first_audio = time.time() - t0
            print(f"  +{first_audio:5.1f}s  FIRST AUDIO: {len(got)} bytes of the song are streamable")
        except Exception as e:  # noqa: BLE001
            print("  stream not ready yet:", type(e).__name__)
    if state in ("ready", "failed"):
        break
    time.sleep(0.7)
print("final:", {k: j.get(k) for k in ("state", "error", "message", "codec", "bitrateKbps", "path", "songId")})
if j.get("state") != "ready":
    sys.exit(1)

# does the music server list it for this person?
for _ in range(20):
    hit = subsonic("search3", query=title, songCount=20, albumCount=0, artistCount=0).get("searchResult3", {}).get("song", [])
    mine = [s for s in hit if s["title"].lower() == title.lower() and s["artist"].lower() == artist.lower()]
    if mine:
        s = mine[0]
        print(f"  +{time.time() - t0:5.1f}s  in the library: id {s['id']}, {s.get('suffix')}, {s.get('duration')} s, path {s.get('path')}")
        break
    time.sleep(3)
else:
    print("not listed by the music server within about a minute (the hourly scan will find it)")
print(f"total {time.time() - t0:.1f}s; first audio {first_audio and round(first_audio, 1)}s")
