#!/usr/bin/env bash
# E2E for suggestions on the dev VM: sam plays and likes the six real songs, then Made for you is built from the REAL public services.
set -euo pipefail
. ~/encore-creds.txt
sub() { salt=$(openssl rand -hex 6); tok=$(printf '%s%s' "$2" "$salt" | md5sum | cut -d' ' -f1); curl -s "http://localhost:4533/rest/$3.view?u=$1&t=$tok&s=$salt&v=1.16.1&c=recs&f=json&$4"; }

echo "--- sam's listening: star and play each of the library's songs"
ids=$(sub "$GUEST" "$GUEST_PW" search3 "query=%20&songCount=50" | python3 -c '
import sys, json
r = json.load(sys.stdin)["subsonic-response"]["searchResult3"].get("song", [])
for s in r:
    if s["artist"] not in ("Kevin MacLeod", "Pool Artist"): print(s["id"], s["artist"], "|", s["title"])')
echo "$ids"
echo "$ids" | while read -r id rest; do
  [ -z "$id" ] && continue
  sub "$GUEST" "$GUEST_PW" star "id=$id" >/dev/null
  for i in 1 2; do sub "$GUEST" "$GUEST_PW" scrobble "id=$id&submission=true" >/dev/null; done
done

echo "--- the owner asks for a rebuild"
~/qs.sh encore-recs 8705 owner POST /api/admin/recs/rebuild "{}" | tail -1
for i in $(seq 1 60); do
  s=$(~/qs.sh encore-recs 8705 owner GET /api/admin/recs | head -1 | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["rebuilding"])')
  [ "$s" = "False" ] && break; sleep 5
done
~/qs.sh encore-recs 8705 owner GET /api/admin/recs | head -1 | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("owner sees:", {k: d[k] for k in ("enabled", "peopleWithLists", "lastRun", "surfaces")})'
