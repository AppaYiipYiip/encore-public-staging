#!/usr/bin/env bash
# E2E on the dev VM, step 1: a quick copy exists and is liked and in a playlist; Soulseek is switched on; the guest asks for better quality.
set -euo pipefail
. ~/encore-creds.txt
IMG=encore-server-encore-fetch
D="/music/Kevin MacLeod/Calming"
sub() { salt=$(openssl rand -hex 6); tok=$(printf '%s%s' "$2" "$salt" | md5sum | cut -d' ' -f1); curl -s "http://localhost:4533/rest/$3.view?u=$1&t=$tok&s=$salt&v=1.16.1&c=e2e&f=json&$4"; }

echo "--- a quick copy of 'Autumn Day' (m4a, 184 s, tagged like the fetch service tags it)"
docker run --rm -u 1000:1000 --entrypoint sh -v /srv/music:/music "$IMG" -c "mkdir -p '$D' && ffmpeg -loglevel error -y -f lavfi -i 'sine=frequency=330:duration=184' -c:a aac -b:a 128k \
  -metadata artist='Kevin MacLeod' -metadata albumartist='Kevin MacLeod' -metadata album='Calming' -metadata title='Autumn Day' -metadata track=1 -metadata date=2014 '$D/01 - Autumn Day.m4a'"
sub "$OWNER" "$OWNER_PW" startScan "fullScan=true" >/dev/null
for i in $(seq 1 30); do st=$(sub "$OWNER" "$OWNER_PW" getScanStatus "" | python3 -c 'import sys,json; print(json.load(sys.stdin)["subsonic-response"]["scanStatus"]["scanning"])'); [ "$st" = "False" ] && break; sleep 2; done
ID=$(sub "$GUEST" "$GUEST_PW" search3 "query=Autumn%20Day&songCount=5" | python3 -c 'import sys,json; s=json.load(sys.stdin)["subsonic-response"]["searchResult3"]["song"]; print([x for x in s if x["artist"]=="Kevin MacLeod"][0]["id"])')
echo "song id: $ID"; echo "$ID" > /tmp/e2e_song_id
echo "--- sam likes it and puts it in a playlist"
sub "$GUEST" "$GUEST_PW" star "id=$ID" >/dev/null
PL=$(sub "$GUEST" "$GUEST_PW" createPlaylist "name=Calm%20evenings&songId=$ID" | python3 -c 'import sys,json; print(json.load(sys.stdin)["subsonic-response"]["playlist"]["id"])')
echo "$PL" > /tmp/e2e_playlist_id; echo "playlist: $PL"

echo "--- the owner switches Soulseek on"
~/q.sh owner PUT /api/admin/quality/settings '{"soulseek": true}' | tail -1
sleep 5
~/q.sh owner GET /api/admin/quality | python3 -c 'import sys,json; d=json.loads(sys.stdin.read().rsplit("\n[",1)[0]); print("soulseek:", d["health"]["soulseek"], "| connected:", d["health"]["slskd"]["connected"])'

echo "--- sam asks for better quality"
~/q.sh guest POST /api/quality/requests "{\"songId\": \"$ID\"}"
