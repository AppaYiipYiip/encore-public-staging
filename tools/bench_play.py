"""Times "tap a song the server does not have" through the fetch service's API, stage by stage (docs/tasks P1-01, P1-06).

Run it ON the server machine (it reads the stack's .env on that machine and prints no secret):
    python3 tools/bench_play.py /home/encore/encore-server  "Artist|Title|Album|seconds" ...

It makes (or re-uses) a test person `bench`, then for each song: POST /api/play and poll the job. Reports the seconds until the job
shows each state and until the audio has a stream address (the moment the phone can start playing). Songs are real; use at most a few.
"""
import hashlib
import json
import secrets
import string
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ND = "http://127.0.0.1:4533"
FETCH = "http://127.0.0.1:8701"


def env(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def http(method, url, body=None, headers=None):
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return json.loads(data) if data else None


def make_user(admin_user: str, admin_password: str) -> str:
    token = http("POST", ND + "/auth/login", {"username": admin_user, "password": admin_password})["token"]
    auth = {"x-nd-authorization": f"Bearer {token}"}
    password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))
    users = http("GET", ND + "/api/user", headers=auth)
    existing = next((u for u in users if u["userName"] == "bench"), None)
    if existing:
        http("PUT", f"{ND}/api/user/{existing['id']}", {"id": existing["id"], "userName": "bench", "name": "bench",
                                                         "isAdmin": False, "password": password}, headers=auth)
    else:
        http("POST", ND + "/api/user", {"userName": "bench", "name": "bench", "isAdmin": False, "password": password}, headers=auth)
    return password


def main() -> int:
    stack = Path(sys.argv[1])
    e = env(stack / ".env")
    password = make_user(e["PEOPLE_ADMIN_USER"], e["PEOPLE_ADMIN_PASSWORD"])
    salt = secrets.token_hex(6)
    q = urllib.parse.urlencode({"u": "bench", "t": hashlib.md5((password + salt).encode()).hexdigest(), "s": salt})
    print(f"{'song':36} {'search':>7} {'download':>9} {'audio-ready':>12} {'whole song':>11}")
    for spec in sys.argv[2:]:
        artist, title, album, secs = spec.split("|")
        t0 = time.monotonic()
        job = http("POST", f"{FETCH}/api/play?{q}", {"artist": artist, "title": title, "album": album,
                                                      "durationSec": int(secs), "priority": "now"})
        seen: dict[str, float] = {}
        final = None
        while time.monotonic() - t0 < 120:
            state = http("GET", f"{FETCH}/api/play/{job['id']}?{q}")
            now = time.monotonic() - t0
            seen.setdefault(state["state"], now)
            if state.get("stream") and "audio" not in seen:
                seen["audio"] = now
            if state["state"] in ("ready", "failed"):
                final = state
                break
            time.sleep(0.15)
        label = f"{artist} - {title}"[:35]
        if final and final["state"] == "failed":
            print(f"{label:36} FAILED: {final.get('error')} {final.get('message', '')}")
            continue
        print(f"{label:36} {seen.get('downloading', float('nan')):7.1f} "
              f"{seen.get('downloading', 0) and (seen.get('audio', 0) - seen.get('downloading', 0)):9.1f} "
              f"{seen.get('audio', float('nan')):12.1f} {seen.get('ready', float('nan')):11.1f}")
        time.sleep(3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
