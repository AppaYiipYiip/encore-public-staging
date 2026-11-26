"""P3-30 proof on a THROWAWAY Navidrome 0.64.2 (the version the compose file pins), never on a real install:
what happens to the stored Subsonic passwords when ND_PASSWORDENCRYPTIONKEY is set on an install that never had one, changed, or when an
old backup is put under a custom key. Usage: python nd_key_proof.py <navidrome.exe> <empty work dir>"""
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

EXE = Path(sys.argv[1]).resolve()
WORK = Path(sys.argv[2]).resolve()
PORT = 4598
BASE = f"http://127.0.0.1:{PORT}"
PW = {"admin": "admin-pass-1234", "nina": "nina-pass-5678"}
K1 = secrets.token_hex(24)
K2 = secrets.token_hex(24)
music = WORK / "music"
music.mkdir(parents=True, exist_ok=True)


def start(data: Path, key: str | None, logname: str) -> subprocess.Popen:
    data.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "ND_DATAFOLDER": str(data), "ND_MUSICFOLDER": str(music), "ND_ADDRESS": "127.0.0.1", "ND_PORT": str(PORT),
           "ND_LOGLEVEL": "debug", "ND_ENABLEINSIGHTSCOLLECTOR": "false", "ND_SCANSCHEDULE": "0", "ND_BACKUP_SCHEDULE": ""}
    env.pop("ND_PASSWORDENCRYPTIONKEY", None)
    if key:
        env["ND_PASSWORDENCRYPTIONKEY"] = key
    log = open(WORK / logname, "wb")
    proc = subprocess.Popen([str(EXE)], env=env, cwd=str(data), stdout=log, stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            urllib.request.urlopen(f"{BASE}/ping", timeout=2).read()
            return proc
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise SystemExit(f"navidrome did not start; see {logname}")


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(1)


def post(path: str, body: dict, token: str | None = None) -> dict:
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **({"X-ND-Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"{}")


def ping(user: str) -> str:
    salt = secrets.token_hex(4)
    token = hashlib.md5((PW[user] + salt).encode()).hexdigest()
    url = f"{BASE}/rest/ping?u={user}&t={token}&s={salt}&v=1.16.1&c=proof&f=json"
    try:
        body = json.loads(urllib.request.urlopen(url, timeout=10).read())["subsonic-response"]
        return "ok" if body["status"] == "ok" else f"FAILED({body.get('error', {}).get('code')})"
    except Exception as error:  # noqa: BLE001
        return f"ERROR({type(error).__name__})"


def both() -> str:
    return " ".join(f"{u}={ping(u)}" for u in PW)


def interesting(logname: str) -> list[str]:
    text = (WORK / logname).read_text(encoding="utf-8", errors="replace").splitlines()
    return [line[:200] for line in text if any(w in line.lower() for w in ("encrypt", "passwordencryptionkey", "password"))][:6]


results: list[str] = []


def record(label: str, value: str) -> None:
    results.append(f"{label}: {value}")
    print(results[-1], flush=True)


# 1. An install that never had a key (the default key): make the owner and a person.
d1 = WORK / "install-default"
p = start(d1, None, "log1.txt")
made = post("/auth/createAdmin", {"username": "admin", "password": PW["admin"]})
token = made["token"]
post("/api/user", {"userName": "nina", "name": "Nina", "email": "", "password": PW["nina"], "isAdmin": False}, token)
record("1 default key, fresh", both())
stop(p)
shutil.copytree(d1, WORK / "backup-default-era")  # the 'old backup': made before any custom key existed

# 2. The same install, restarted with a custom key (what an existing Host gets from `encore update`).
p = start(d1, K1, "log2.txt")
record("2 same install, custom key K1 set for the first time", both())
for line in interesting("log2.txt"):
    print("   log:", line)
stop(p)

# 3. Restarted again with the same key (the normal life afterwards).
p = start(d1, K1, "log3.txt")
record("3 restart with K1 again", both())
stop(p)

# 4. The key is lost or changed: a different key.
p = start(d1, K2, "log4.txt")
record("4 restart with a DIFFERENT key K2", both())
stop(p)

# 5. No key at all after K1 was set (the .env was lost, a restore on a new computer without the key).
p = start(d1, None, "log5.txt")
record("5 restart with NO key after K1 was set", both())
stop(p)

# 6. K1 back: is it recoverable?
p = start(d1, K1, "log6.txt")
record("6 K1 back again", both())
stop(p)

# 7. An OLD backup (made under the default key) put on an install that uses K1 (restore of a pre-key backup).
p = start(WORK / "backup-default-era", K1, "log7.txt")
record("7 old default-era backup started under K1", both())
for line in interesting("log7.txt"):
    print("   log:", line)
stop(p)

# 8. A new install made with a custom key from the start, then restored under the default (no key).
d8 = WORK / "install-custom-from-start"
p = start(d8, K1, "log8.txt")
made = post("/auth/createAdmin", {"username": "admin", "password": PW["admin"]})
post("/api/user", {"userName": "nina", "name": "Nina", "email": "", "password": PW["nina"], "isAdmin": False}, made["token"])
record("8 fresh install with K1 from the start", both())
stop(p)
p = start(d8, None, "log8b.txt")
record("8b that install started with NO key", both())
stop(p)
print("\n".join(["", "SUMMARY"] + results))
