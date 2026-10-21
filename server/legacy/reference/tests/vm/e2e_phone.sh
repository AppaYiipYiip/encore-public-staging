#!/usr/bin/env bash
# E2E step 3: what a phone can and cannot see after a swap, and what it does with the upgrade map.
. ~/encore-creds.txt
OLD=$(cat /tmp/e2e_song_id); PL=$(cat /tmp/e2e_playlist_id)
NEW=$(python3 -c 'import json; print(json.load(open("/tmp/map.json"))["upgrades"][0]["new"])')
sub() { salt=$(openssl rand -hex 6); tok=$(printf '%s%s' "$2" "$salt" | md5sum | cut -d' ' -f1); curl -s "http://localhost:4533/rest/$3.view?u=$1&t=$tok&s=$salt&v=1.16.1&c=e2e&f=json&$4"; }
show() {
  echo "  likes:    $(sub "$GUEST" "$GUEST_PW" getStarred2 "" | python3 -c 'import sys,json; print([(s["id"][:6], s["suffix"]) for s in json.load(sys.stdin)["subsonic-response"]["starred2"].get("song", [])])')"
  echo "  playlist: $(sub "$GUEST" "$GUEST_PW" getPlaylist "id=$PL" | python3 -c 'import sys,json; p=json.load(sys.stdin)["subsonic-response"]["playlist"]; print([(e["id"][:6], e["suffix"]) for e in p.get("entry", [])], "songCount:", p.get("songCount"))')"
}
echo "old=$OLD new=$NEW"
echo "--- as the server shows it right after the swap"; show
echo "--- the phone likes the new song, unlikes the old one, adds the new one to the playlist"
sub "$GUEST" "$GUEST_PW" star "id=$NEW" | python3 -c 'import sys,json; print("   star ->", json.load(sys.stdin)["subsonic-response"]["status"])'
sub "$GUEST" "$GUEST_PW" unstar "id=$OLD" | python3 -c 'import sys,json; print("   unstar old ->", json.load(sys.stdin)["subsonic-response"]["status"])'
sub "$GUEST" "$GUEST_PW" updatePlaylist "playlistId=$PL&songIdToAdd=$NEW" | python3 -c 'import sys,json; print("   add new ->", json.load(sys.stdin)["subsonic-response"]["status"])'
show
echo "--- remove the old entry (index 0 of the full list)"
sub "$GUEST" "$GUEST_PW" updatePlaylist "playlistId=$PL&songIndexToRemove=0" | python3 -c 'import sys,json; print("   remove ->", json.load(sys.stdin)["subsonic-response"]["status"])'
show
