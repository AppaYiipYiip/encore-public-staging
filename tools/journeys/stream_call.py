"""stream_call.py LOGIN_FILE ARTIST TITLE [DURATION_SEC] [--range=a-b] [--video=ID] [--read=BYTES]

Asks the fetch service to stream a song (GET /api/stream) as the person in LOGIN_FILE and says how long the first byte took, the
status, the headers a player needs and how many bytes were read (default 256 KiB, then it stops: nothing is saved). The password is
never printed. In Git Bash set MSYS_NO_PATHCONV=1."""
import hashlib, os, sys, time, urllib.error, urllib.parse, urllib.request

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = dict(f[2:].split("=", 1) for f in sys.argv[1:] if f.startswith("--") and "=" in f)
cfg = {}
for line in open(args[0], encoding="utf-8"):
    if ":" in line and not line.startswith(" "):
        k, v = line.split(":", 1)
        cfg[k.strip()] = v.strip()
salt = "p" + hashlib.md5(os.urandom(6)).hexdigest()[:8]
query = {"u": cfg["user"], "t": hashlib.md5((cfg["password"] + salt).encode()).hexdigest(), "s": salt}
if "video" in flags:
    query["videoId"] = flags["video"]
else:
    query.update({"artist": args[1], "title": args[2]})
if len(args) > 3:
    query["durationSec"] = args[3]
url = cfg["address"].rstrip("/") + "/fetch/api/stream?" + urllib.parse.urlencode(query)
headers = {"Range": "bytes=" + flags["range"]} if "range" in flags else {}
started = time.time()
try:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        first = response.read(1)
        first_byte = time.time() - started
        data = first + response.read(int(flags.get("read", 256 * 1024)) - 1)
        print(f"{response.status} first byte after {first_byte:.1f} s; read {len(data)} bytes in {time.time() - started:.1f} s")
        for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
            print(f"  {name}: {response.headers.get(name)}")
except urllib.error.HTTPError as error:
    print(error.code, f"after {time.time() - started:.1f} s", error.read()[:300].decode("utf-8", "replace"))
