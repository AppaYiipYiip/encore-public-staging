"""Search-only look at Soulseek through slskd (nothing is downloaded): how many peers answer for a few freely licensed albums."""
import json
import sys
import time
import urllib.request

env = dict(line.strip().split("=", 1) for line in open("/srv/encore/.env") if "=" in line)
BASE = "http://localhost:5030/api/v0"
KEY = env["SLSKD_KEY"]


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-API-Key": KEY, "Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=60).read()
    return json.loads(raw) if raw else None


for text in sys.argv[1:]:
    started = time.time()
    s = call("POST", "/searches", {"searchText": text, "searchTimeout": 15000, "fileLimit": 5000, "responseLimit": 100})
    sid = s["id"]
    while time.time() - started < 40:
        st = call("GET", f"/searches/{sid}")
        if st["isComplete"]:
            break
        time.sleep(2)
    responses = call("GET", f"/searches/{sid}/responses")
    folders = {}
    for r in responses:
        for f in r["files"]:
            folder = f["filename"].rsplit("\\", 1)[0]
            folders.setdefault((r["username"], folder), []).append(f["filename"].rsplit(".", 1)[-1].lower())
    best = sorted(folders.items(), key=lambda kv: -len(kv[1]))[:3]
    print(f"{text!r}: {len(responses)} peers answered, {len(folders)} folders in {round(time.time() - started)} s")
    for (user, folder), exts in best:
        print("   ", len(exts), "files", sorted(set(exts)), "|", folder[-70:])
    call("DELETE", f"/searches/{sid}")
