import json, time, urllib.request, urllib.parse
UA = "encore-recs-experiment/1 (research on the owners own dev VM)"
def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=40)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]
    except Exception as e:
        return 0, str(e)
opeth = "c14b4180-dc87-481e-b17a-64e4150f90f6"
print("1. MusicBrainz artist search:")
s, d = get("https://musicbrainz.org/ws/2/artist/?query=" + urllib.parse.quote('artist:"Gojira"') + "&fmt=json&limit=3")
print("  ", s, [(a["name"], a["id"][:8], a["score"], a.get("disambiguation", "")) for a in (d.get("artists", []) if isinstance(d, dict) else [])])
time.sleep(1.2)
print("2. ListenBrainz similar artists (labs):")
algo = "session_based_days_9000_session_300_contribution_5_threshold_15_limit_50_skip_30"
s, d = get("https://labs.api.listenbrainz.org/similar-artists/json?artist_mbids=%s&algorithm=%s" % (opeth, algo))
print("  ", s, type(d).__name__, (d[:6] if isinstance(d, list) else str(d)[:300]))
if isinstance(d, list) and d:
    print("   keys:", sorted(d[0].keys()))
time.sleep(1)
print("3. ListenBrainz popularity top recordings:")
s, d = get("https://api.listenbrainz.org/1/popularity/top-recordings-for-artist?artist_mbid=" + opeth)
print("  ", s, type(d).__name__, len(d) if isinstance(d, list) else str(d)[:200])
if isinstance(d, list) and d:
    print("   keys:", sorted(d[0].keys())); print("   first:", [(x["recording_name"], x.get("release_name"), x.get("total_listen_count")) for x in d[:4]])
time.sleep(1.2)
print("4. MusicBrainz release groups:")
s, d = get("https://musicbrainz.org/ws/2/release-group?artist=%s&type=album&limit=100&fmt=json" % opeth)
if isinstance(d, dict):
    rgs = sorted(d.get("release-groups", []), key=lambda x: x.get("first-release-date", ""), reverse=True)
    print("  ", s, d.get("release-group-count"), [(x["title"], x.get("first-release-date")) for x in rgs[:4]])
else:
    print("  ", s, d)
