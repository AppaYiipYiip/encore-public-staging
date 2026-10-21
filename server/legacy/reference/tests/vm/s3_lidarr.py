"""S3 on the dev VM: Lidarr by API. Add an artist NOT monitored, monitor ONE album, root folder + quality + metadata profile.
Reads the key from /srv/encore/.env; prints facts, never the key."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

env = dict(line.strip().split("=", 1) for line in open("/srv/encore/.env") if "=" in line)
BASE = "http://localhost:8686/api/v1"
KEY = env["LIDARR_KEY"]


def call(method, path, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"X-Api-Key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:300]


what = sys.argv[1] if len(sys.argv) > 1 else "look"

if what == "look":
    for p in ("/rootfolder", "/qualityprofile", "/metadataprofile", "/downloadclient", "/config/mediamanagement", "/config/naming"):
        s, d = call("GET", p)
        if isinstance(d, list):
            print(p, s, [(x.get("id"), x.get("name") or x.get("path")) for x in d])
        else:
            print(p, s, {k: d[k] for k in list(d)[:14]} if isinstance(d, dict) else d)
    s, d = call("GET", "/qualitydefinition")
    print("qualities", [(x["quality"]["id"], x["quality"]["name"]) for x in d])

if what == "lookup":
    term = sys.argv[2]
    s, d = call("GET", "/artist/lookup?term=" + urllib.parse.quote(term), timeout=90)
    print(s, len(d) if isinstance(d, list) else d)
    for a in (d or [])[:5]:
        print(a.get("artistName"), a.get("foreignArtistId"), a.get("disambiguation"), a.get("status"))

if what == "profiles":
    s, d = call("GET", "/metadataprofile/1")
    print(json.dumps(d, indent=None)[:1500])
    s, d = call("GET", "/qualityprofile/2")
    print(json.dumps(d, indent=None)[:1800])
    s, d = call("GET", "/metadataprofile/schema")
    print(s, json.dumps(d)[:200])

QUALITY_ALLOWED = {6: "FLAC", 21: "FLAC 24bit", 4: "MP3-320", 2: "MP3-VBR-V0"}

if what == "wire":
    # 1. root folder (the pool)
    s, d = call("POST", "/rootfolder", {"name": "Encore pool", "path": "/data/pool", "defaultMetadataProfileId": 1,
                                         "defaultQualityProfileId": 1, "defaultMonitorOption": "none",
                                         "defaultNewItemMonitorOption": "none", "defaultTags": []})
    print("rootfolder", s, d if s >= 300 else d.get("path"))
    # 2. our quality profile
    s, schema = call("GET", "/qualityprofile/schema")
    leaves = []
    for it in schema["items"]:
        for leaf in (it["items"] if it.get("items") else [it]):
            leaves.append({"quality": leaf["quality"], "items": [], "allowed": leaf["quality"]["id"] in QUALITY_ALLOWED})
    schema.update({"name": "Encore", "upgradeAllowed": True, "cutoff": 6, "items": leaves})
    s, q = call("POST", "/qualityprofile", schema)
    print("quality profile", s, str(q)[:300] if s >= 300 else (q["id"], q["name"], q["cutoff"]))
    # 3. our metadata profile: every kind of release, so whatever a song came from can be wanted
    s, m = call("GET", "/metadataprofile/schema")
    for x in m["primaryAlbumTypes"]:
        x["allowed"] = True
    for x in m["secondaryAlbumTypes"]:
        x["allowed"] = True
    for x in m["releaseStatuses"]:
        x["allowed"] = x["releaseStatus"]["name"] in ("Official", "Promotion")
    m["name"] = "Encore"
    s, mp = call("POST", "/metadataprofile", m)
    print("metadata profile", s, mp if s >= 300 else (mp["id"], mp["name"]))

if what == "addartist":
    mbid = sys.argv[2]
    s, profiles = call("GET", "/qualityprofile")
    qid = next(p["id"] for p in profiles if p["name"] == "Encore")
    s, mprofiles = call("GET", "/metadataprofile")
    mid = next(p["id"] for p in mprofiles if p["name"] == "Encore")
    s, found = call("GET", "/artist/lookup?term=" + urllib.parse.quote("lidarr:" + mbid), timeout=90)
    artist = found[0]
    artist.update({"qualityProfileId": qid, "metadataProfileId": mid, "rootFolderPath": "/data/pool", "monitored": False,
                   "monitorNewItems": "none", "addOptions": {"monitor": "none", "searchForMissingAlbums": False}})
    t = time.time()
    s, a = call("POST", "/artist", artist, timeout=300)
    print("add artist", s, a if s >= 300 else (a["id"], a["artistName"], a["monitored"], a.get("monitorNewItems")), round(time.time() - t, 1), "s")

if what == "albums":
    aid = sys.argv[2]
    for _ in range(40):
        s, albums = call("GET", f"/album?artistId={aid}")
        if albums:
            break
        time.sleep(3)
    print(len(albums), "albums; monitored:", sum(1 for a in albums if a["monitored"]))
    for a in albums[:int(sys.argv[3]) if len(sys.argv) > 3 else 15]:
        print(a["id"], a["title"], a["albumType"], a.get("releaseDate", "")[:10], a["monitored"], a["statistics"]["trackCount"])

if what == "monitor":
    ids = [int(x) for x in sys.argv[2:]]
    s, d = call("PUT", "/album/monitor", {"albumIds": ids, "monitored": True})
    print("monitor", s)
    s, w = call("GET", "/wanted/missing?pageSize=50&monitored=true")
    print("wanted:", s, w["totalRecords"], [(r["id"], r["title"]) for r in w["records"]])
    s, arts = call("GET", "/artist")
    print("artists:", [(x["artistName"], x["monitored"]) for x in arts])
