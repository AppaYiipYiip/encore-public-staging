#!/usr/bin/env bash
# S2 + S8 on the dev VM: the pool lives inside the music folder (a dot-folder), people's folders get HARD LINKS of wanted tracks.
# Different containers share ONE mount. The music server must list the delivered link once and never the pool copy.
set -euo pipefail
. ~/encore-creds.txt
IMG=encore-server-encore-fetch
POOL="/music/.encore/pool/Pool Artist/Linked Album (2020)"
DELIVER="/music/Encore/Pool Artist/Linked Album (2020)"

echo "--- container A (like Lidarr) puts a tagged file in the pool"
docker run --rm -u 1000:1000 --entrypoint sh -v /srv/music:/music "$IMG" -c "
  mkdir -p '$POOL' &&
  ffmpeg -loglevel error -y -f lavfi -i 'sine=frequency=440:duration=3' -c:a flac \
    -metadata artist='Pool Artist' -metadata album='Linked Album' -metadata title='One' -metadata track=1 -metadata date=2020 '$POOL/01 - One.flac' &&
  ls -li '$POOL'"

echo "--- container B (like the songs service) links it into a person's folder"
docker run --rm -u 1000:1000 --entrypoint sh -v /srv/music:/music busybox:1.37.0 -c "
  mkdir -p '$DELIVER' && ln '$POOL/01 - One.flac' '$DELIVER/01 - One.flac' && ls -li '$DELIVER' && stat -c 'links=%h inode=%i' '$POOL/01 - One.flac'"

echo "--- the music server scans"
auth() { salt=$(openssl rand -hex 6); tok=$(printf '%s%s' "$OWNER_PW" "$salt" | md5sum | cut -d' ' -f1); echo "u=$OWNER&t=$tok&s=$salt&v=1.16.1&c=s2&f=json"; }
curl -s "http://localhost:4533/rest/startScan.view?$(auth)&fullScan=true" > /dev/null
for i in $(seq 1 30); do
  st=$(curl -s "http://localhost:4533/rest/getScanStatus.view?$(auth)" | python3 -c 'import sys,json; print(json.load(sys.stdin)["subsonic-response"]["scanStatus"]["scanning"])')
  [ "$st" = "False" ] && break; sleep 2
done
curl -s "http://localhost:4533/rest/search3.view?$(auth)&query=Pool%20Artist&songCount=20" | python3 -c '
import sys, json
r = json.load(sys.stdin)["subsonic-response"]["searchResult3"]
songs = r.get("song", [])
print("songs listed:", len(songs))
for s in songs: print(" ", s["title"], "|", s["path"], "|", s.get("suffix"), s.get("bitRate"))'

echo "--- deleting one name keeps the other"
docker run --rm -u 1000:1000 --entrypoint sh -v /srv/music:/music busybox:1.37.0 -c "
  rm '$DELIVER/01 - One.flac'; stat -c 'pool copy still there: links=%h size=%s' '$POOL/01 - One.flac'
  ln '$POOL/01 - One.flac' '$DELIVER/01 - One.flac'; rm '$POOL/01 - One.flac'; stat -c 'delivered copy after the pool one is gone: links=%h size=%s' '$DELIVER/01 - One.flac'"
echo "--- cleanup"
docker run --rm -u 1000:1000 --entrypoint sh -v /srv/music:/music busybox:1.37.0 -c "rm -rf /music/.encore /music/Encore"
