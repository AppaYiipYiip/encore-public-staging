import json, urllib.request, urllib.parse
env = dict(l.strip().split("=",1) for l in open("/srv/encore/.env") if "=" in l)
def call(m, p, body=None):
    req = urllib.request.Request("http://localhost:8686/api/v1" + p, method=m, data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Api-Key": env["LIDARR_KEY"], "Content-Type": "application/json"})
    try:
        raw = urllib.request.urlopen(req, timeout=90).read()
        return 200, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]
s, cmds = call("GET", "/command")
print("commands:", [(c["name"], c["status"], c.get("body", {}).get("artistId") or c.get("body", {}).get("artistIds")) for c in cmds if c["name"] == "RefreshArtist"])
s, n = call("GET", "/config/naming")
print("naming id", n.get("id"), "rename", n["renameTracks"])
n["renameTracks"] = True
s, r = call("PUT", "/config/naming/%d" % n["id"], n)
print("PUT naming ->", s, r["renameTracks"] if s == 200 else r)
s, m = call("GET", "/config/mediamanagement")
print("mm id", m.get("id"), {k: m[k] for k in m if "ardlink" in k or "copy" in k.lower() or "import" in k.lower()})
# add an artist straight from an album lookup result
s, res = call("GET", "/album/lookup?term=" + urllib.parse.quote("Opeth Blackwater Park"))
art = res[0]["artist"]
print("lookup artist keys:", sorted(art.keys())[:12], "id:", art.get("id"), "foreignArtistId:", art.get("foreignArtistId"))
