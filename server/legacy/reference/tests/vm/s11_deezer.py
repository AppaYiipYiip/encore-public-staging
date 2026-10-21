import json, time, urllib.request, urllib.parse
def get(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "encore-recs-experiment/1"}), timeout=40)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:120]
s, d = get("https://api.deezer.com/search/artist?q=" + urllib.parse.quote('"Porcupine Tree"') + "&limit=3")
print("search:", s, [(a["name"], a["id"], a.get("nb_fan")) for a in d["data"]])
aid = d["data"][0]["id"]
s, d = get("https://api.deezer.com/artist/%d/top?limit=30" % aid)
print("top:", s, len(d["data"]), sorted(d["data"][0].keys())[:20])
for t in d["data"][:5] + d["data"][-2:]:
    print("  ", t["title"], "|", t["artist"]["name"], "|", t["album"]["title"], "| rank", t["rank"], "| dur", t["duration"], "| id", t["id"])
# does it accept a MusicBrainz-free exact-name check? and how fast?
t = time.time()
for _ in range(10):
    get("https://api.deezer.com/artist/%d" % aid)
print("10 calls in %.1fs" % (time.time() - t))
