#!/usr/bin/env python3
"""One call to the Jam hub as a person, with the music server login from a login file (never printed).

    python -I hub_call.py LOGIN_FILE METHOD PATH [JSON] [--base=URL]

    hub_call.py tester-login.txt GET  /api/info
    hub_call.py tester-login.txt POST /api/sessions
    hub_call.py mia-login.txt    POST /api/sessions/ABC234/join
    hub_call.py mia-login.txt    POST /api/sessions/ABC234/command '{"op":"add","trackId":"..."}'

The base is the login file's address plus /hub (the Funnel publishes the hub under /hub); override with --base=URL.
Run with MSYS_NO_PATHCONV=1 in Git Bash (it rewrites arguments that start with a slash).
"""
import hashlib
import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

args = [a for a in sys.argv[1:] if not a.startswith("--base=")]
base_override = next((a[7:] for a in sys.argv[1:] if a.startswith("--base=")), None)
login, method, path = args[0], args[1].upper(), args[2]
body = args[3] if len(args) > 3 else None

fields = {}
for line in open(login, encoding="utf-8"):
    m = re.match(r"(address|user|password):\s*(.*)", line.strip())
    if m:
        fields[m.group(1)] = m.group(2).strip()
base = (base_override or fields["address"].rstrip("/") + "/hub").rstrip("/")
salt = secrets.token_hex(6)
token = hashlib.md5((fields["password"] + salt).encode()).hexdigest()
query = urllib.parse.urlencode({"u": fields["user"], "t": token, "s": salt})
request = urllib.request.Request(
    f"{base}{path}?{query}", method=method,
    data=body.encode() if body else None,
    headers={"Content-Type": "application/json"} if body else {})
try:
    with urllib.request.urlopen(request, timeout=20) as response:
        print(response.status, response.read().decode()[:1500])
except urllib.error.HTTPError as error:
    print(error.code, error.read().decode()[:500])
