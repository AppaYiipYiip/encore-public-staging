"""people_call.py LOGIN_FILE METHOD PATH [JSON_BODY] [--base=URL]
Calls the people service as the person in LOGIN_FILE (Subsonic token: the password is never printed or sent). In Git Bash set
MSYS_NO_PATHCONV=1, or a path such as /people/api/me is rewritten into a Windows path."""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

args = [a for a in sys.argv[1:] if not a.startswith("--")]
base = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--base=")), "http://127.0.0.1:8712")
path, method, route = args[0], args[1], args[2]
body = args[3] if len(args) > 3 else None

cfg = {}
for line in open(path, encoding="utf-8"):
    if ":" in line and not line.startswith(" "):
        k, v = line.split(":", 1)
        cfg[k.strip()] = v.strip()
salt = "p" + hashlib.md5(os.urandom(6)).hexdigest()[:8]
q = {"u": cfg["user"], "t": hashlib.md5((cfg["password"] + salt).encode()).hexdigest(), "s": salt}
req = urllib.request.Request(
    base + route + ("&" if "?" in route else "?") + urllib.parse.urlencode(q),
    data=body.encode() if body else None,
    method=method,
    headers={"Content-Type": "application/json"} if body else {},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(r.status, (r.read() or b"").decode() or "(no content)")
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
