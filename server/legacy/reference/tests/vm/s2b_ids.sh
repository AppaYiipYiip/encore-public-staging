#!/usr/bin/env bash
# S2b + S1 on the dev VM: (A) is a dot-folder in the music folder ignored by the music server? (B) does a delivered link show up once?
# (C) when a quick copy (m4a/opus) is replaced by a quality copy (flac) with the same tags, does the song id, the like and a playlist place stay?
set -euo pipefail
. ~/encore-creds.txt
IMG=encore-server-encore-fetch
POOL="/music/.encore/pool/Pool Artist/Linked Album (2020)"
DELIVER="/music/Encore/Pool Artist/Linked Album (2020)"
run() { docker run --rm -u 1000:1000 --entrypoint sh -v /srv/music:/music "$IMG" -c "$1"; }
auth() { salt=$(openssl rand -hex 6); tok=$(printf '%s%s' "$OWNER_PW" "$salt" | md5sum | cut -d' ' -f1); echo "u=$OWNER&t=$tok&s=$salt&v=1.16.1&c=s2b&f=json"; }
api() { curl -s "http://localhost:4533/rest/$1.view?$(auth)&$2"; }
scan() {
  api startScan "fullScan=true" > /dev/null
  for i in $(seq 1 40); do
    st=$(api getScanStatus "" | python3 -c 'import sys,json; print(json.load(sys.stdin)["subsonic-response"]["scanStatus"]["scanning"])')
    [ "$st" = "False" ] && break; sleep 2
  done
}
songs() { api search3 "query=Pool%20Artist&songCount=20" | python3 -c '
import sys, json
r = json.load(sys.stdin)["subsonic-response"]["searchResult3"]
for s in r.get("song", []): print("  id=%s title=%s suffix=%s starred=%s" % (s["id"], s["title"], s.get("suffix"), "starred" in s))
print("  count:", len(r.get("song", [])))'; }
tags="-metadata artist='Pool Artist' -metadata album='Linked Album' -metadata title='One' -metadata track=1 -metadata date=2020"

echo "=== A: only the pool copy exists (inside the dot-folder)"
run "mkdir -p '$POOL' && ffmpeg -loglevel error -y -f lavfi -i 'sine=frequency=440:duration=3' -c:a flac $tags '$POOL/01 - One.flac'"
scan; songs

echo "=== B: a QUICK copy (m4a, like YouTube) in the person's folder"
run "mkdir -p '$DELIVER' && ffmpeg -loglevel error -y -f lavfi -i 'sine=frequency=440:duration=3' -c:a aac -b:a 128k $tags '$DELIVER/01 - One.m4a'"
scan; songs
ID=$(api search3 "query=Pool%20Artist&songCount=5" | python3 -c 'import sys,json; print(json.load(sys.stdin)["subsonic-response"]["searchResult3"]["song"][0]["id"])')
echo "like it and put it in a playlist"
api star "id=$ID" > /dev/null
PL=$(api createPlaylist "name=S1test&songId=$ID" | python3 -c 'import sys,json; print(json.load(sys.stdin)["subsonic-response"]["playlist"]["id"])')

echo "=== C: the quality copy arrives (hard link of the pool FLAC) and the quick copy moves aside"
run "mkdir -p /music/.encore/replaced && mv '$DELIVER/01 - One.m4a' /music/.encore/replaced/ && ln '$POOL/01 - One.flac' '$DELIVER/01 - One.flac'"
scan; songs
echo "playlist after the swap:"
api getPlaylist "id=$PL" | python3 -c '
import sys, json
p = json.load(sys.stdin)["subsonic-response"]["playlist"]
print("  entries:", [(e["id"], e["title"], e.get("suffix")) for e in p.get("entry", [])])'
echo "starred list:"
api getStarred2 "" | python3 -c '
import sys, json
r = json.load(sys.stdin)["subsonic-response"]["starred2"]
print("  ", [(s["id"], s["title"], s.get("suffix")) for s in r.get("song", [])])'
echo "=== cleanup"
api deletePlaylist "id=$PL" > /dev/null
[ -n "$ID" ] && api unstar "id=$ID" > /dev/null || true
run "rm -rf /music/.encore /music/Encore"
scan
