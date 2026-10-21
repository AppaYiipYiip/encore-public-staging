#!/usr/bin/env python3
"""Tiny Subsonic caller for the Encore server. The password is read from a login file and never printed.
   python nd.py <login file> <method> [key=value ...]      -> prints the "subsonic-response" as JSON (shortened)
"""
import hashlib, json, os, sys, time, urllib.parse, urllib.request

path, method, *kv = sys.argv[1:]
cfg = {}
for line in open(path, encoding="utf-8"):
    if ":" in line and not line.startswith(" "):
        k, v = line.split(":", 1)
        if k in ("address", "user", "password"):
            cfg[k] = v.strip()
salt = "n" + hashlib.md5(os.urandom(6)).hexdigest()[:8]
params = {"u": cfg["user"], "t": hashlib.md5((cfg["password"] + salt).encode()).hexdigest(), "s": salt,
          "v": "1.16.1", "c": "nd.py", "f": "json"}
params.update(dict(x.split("=", 1) for x in kv))
url = cfg["address"].rstrip("/") + "/rest/" + method + "?" + urllib.parse.urlencode(params)
t0 = time.time()
with urllib.request.urlopen(url, timeout=60) as r:
    body = json.load(r)["subsonic-response"]
text = json.dumps(body, ensure_ascii=False)
print(text if len(text) < 1500 else text[:1500] + " ... [" + str(len(text)) + " chars]")
print(f"({time.time() - t0:.2f} s)")
