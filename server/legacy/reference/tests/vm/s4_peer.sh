#!/usr/bin/env bash
# S4 helper on the dev VM: a stand-in Soulseek peer that shares ONE synthetic album (silence, named and tagged after the real album's
# track list from MusicBrainz via Lidarr). Nothing copyrighted is shared; only the test's own downloader will ask for it.
set -euo pipefail
SHARE=/srv/encore/peer/share
ALBUM="$SHARE/Kevin MacLeod - Calming (2014) [FLAC]"
mkdir -p /srv/encore/peer/config "$ALBUM"
python3 - <<'PY'
import json, subprocess
tracks = json.load(open("/tmp/calming.json"))
album = "/srv/encore/peer/share/Kevin MacLeod - Calming (2014) [FLAC]"
for t in tracks:
    name = "%02d - %s.flac" % (t["n"], t["title"].replace("/", "-"))
    cmd = ["docker", "run", "--rm", "-u", "1000:1000", "--entrypoint", "ffmpeg", "-v", "/srv/encore/peer:/srv/encore/peer", "encore-server-encore-fetch",
           "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(t["sec"]), "-c:a", "flac",
           "-metadata", "artist=Kevin MacLeod", "-metadata", "albumartist=Kevin MacLeod", "-metadata", "album=Calming",
           "-metadata", "title=" + t["title"], "-metadata", "track=%d/%d" % (t["n"], len(tracks)), "-metadata", "date=2014",
           album + "/" + name]
    subprocess.run(cmd, check=True)
print(len(tracks), "files")
PY
ls "$ALBUM" | head -3
du -sh "$ALBUM"
if ! docker ps -a --format '{{.Names}}' | grep -qx encore-peer; then
  PW=$(openssl rand -hex 8); KEY=$(openssl rand -hex 16); USERN="encore-peer-$(openssl rand -hex 3)"
  docker run -d --name encore-peer --network encore-exp_default -u 1000:1000 \
    -e SLSKD_REMOTE_CONFIGURATION=false -e SLSKD_SLSK_USERNAME="$USERN" -e SLSKD_SLSK_PASSWORD="$PW" \
    -e SLSKD_USERNAME=admin -e SLSKD_PASSWORD="$PW" -e SLSKD_API_KEY="role=ReadWrite;cidr=0.0.0.0/0,::/0;$KEY" \
    -e SLSKD_SHARED_DIR=/share -e SLSKD_SLSK_LISTEN_PORT=50301 -e SLSKD_DOWNLOADS_DIR=/tmp/peer-dl -e SLSKD_INCOMPLETE_DIR=/tmp/peer-inc \
    -p 5031:5030 -v /srv/encore/peer/config:/app -v "$SHARE":/share:ro slskd/slskd:0.26.1 >/dev/null
  umask 077; printf 'PEER_KEY=%s\n' "$KEY" > /srv/encore/peer/.env
  echo "peer started as $USERN"
fi
