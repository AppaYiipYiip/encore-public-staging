#!/usr/bin/env bash
# E2E on the dev VM, step 2: what is true after the swap, and what a phone does with the upgrade map.
set -euo pipefail
. ~/encore-creds.txt
OLD=$(cat /tmp/e2e_song_id); PL=$(cat /tmp/e2e_playlist_id)
sub() { salt=$(openssl rand -hex 6); tok=$(printf '%s%s' "$2" "$salt" | md5sum | cut -d' ' -f1); curl -s "http://localhost:4533/rest/$3.view?u=$1&t=$tok&s=$salt&v=1.16.1&c=e2e&f=json&$4"; }

echo "=== the files"
ls -li "/srv/music/Kevin MacLeod/Calming/" | tail -n +2
echo "(the way back:)"; find /srv/music/.encore/replaced -type f | sed 's#/srv/music/##'
echo "(the pool:)";    find /srv/music/.encore/pool -type f | sed 's#/srv/music/##' | head -3; echo "pool files: $(find /srv/music/.encore/pool -type f | wc -l)"
echo "disk used by the pool: $(du -sh /srv/music/.encore/pool | cut -f1)"

echo "=== the music server (sam's view)"
sub "$GUEST" "$GUEST_PW" search3 "query=Autumn%20Day&songCount=10" | python3 -c '
import sys, json
for s in json.load(sys.stdin)["subsonic-response"]["searchResult3"]["song"]:
    if s["artist"] == "Kevin MacLeod": print("  id=%s suffix=%s bitRate=%s starred=%s" % (s["id"], s["suffix"], s.get("bitRate"), "starred" in s))'
echo "sam's likes before the phone acts:"
sub "$GUEST" "$GUEST_PW" getStarred2 "" | python3 -c 'import sys,json; print("  ", [(s["id"][:6], s["suffix"]) for s in json.load(sys.stdin)["subsonic-response"]["starred2"].get("song", [])])'
echo "sam's playlist before the phone acts:"
sub "$GUEST" "$GUEST_PW" getPlaylist "id=$PL" | python3 -c 'import sys,json; p=json.load(sys.stdin)["subsonic-response"]["playlist"]; print("  entries:", [(e["id"][:6], e["suffix"]) for e in p.get("entry", [])])'

echo "=== the upgrade map (what the phone reads)"
~/q.sh guest GET "/api/quality/upgrades?after=0" | head -1 | tee /tmp/map.json | cut -c1-300

echo "=== the phone acts on it: likes the new song, unlikes the old, moves the playlist place"
python3 - <<'PY'
import json, subprocess
m = json.load(open("/tmp/map.json"))
open("/tmp/map_pairs", "w").write("\n".join(f'{u["old"]} {u["new"]}' for u in m["upgrades"]))
PY
while read -r old new; do
  [ "$old" = "$OLD" ] || continue
  sub "$GUEST" "$GUEST_PW" star "id=$new" >/dev/null
  sub "$GUEST" "$GUEST_PW" unstar "id=$old" >/dev/null
  sub "$GUEST" "$GUEST_PW" updatePlaylist "playlistId=$PL&songIdToAdd=$new" >/dev/null
  idx=$(sub "$GUEST" "$GUEST_PW" getPlaylist "id=$PL" | python3 -c 'import sys,json; p=json.load(sys.stdin)["subsonic-response"]["playlist"]; print([i for i,e in enumerate(p.get("entry", [])) if e["id"]=="'"$old"'"][0])')
  sub "$GUEST" "$GUEST_PW" updatePlaylist "playlistId=$PL&songIndexToRemove=$idx" >/dev/null
done < /tmp/map_pairs
echo "sam's likes after:"
sub "$GUEST" "$GUEST_PW" getStarred2 "" | python3 -c 'import sys,json; print("  ", [(s["id"][:6], s["suffix"]) for s in json.load(sys.stdin)["subsonic-response"]["starred2"].get("song", [])])'
echo "sam's playlist after:"
sub "$GUEST" "$GUEST_PW" getPlaylist "id=$PL" | python3 -c 'import sys,json; p=json.load(sys.stdin)["subsonic-response"]["playlist"]; print("  entries:", [(e["id"][:6], e["suffix"]) for e in p.get("entry", [])])'
