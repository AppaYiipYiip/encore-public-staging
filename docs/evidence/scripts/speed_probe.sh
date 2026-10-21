set -u
# Runs on the dev VM. Line speed, YouTube range speed, a full song download, all timed.
curl -s -o /dev/null -w 'cloudflare 8MB down: %{speed_download} B/s in %{time_total}s\n' "https://speed.cloudflare.com/__down?bytes=8000000"
C=encore-fetch
VID=AWCVHllzG9Y
s=$(date +%s%N)
URL=$(docker exec $C yt-dlp --no-warnings -f 'bestaudio[acodec=opus]/bestaudio' -g "https://music.youtube.com/watch?v=$VID" 2>/dev/null | head -1)
e=$(date +%s%N); echo "yt-dlp -g (resolve stream url): $(( (e-s)/1000000 )) ms"
curl -s -o /dev/null -r 0-1048575 -w 'googlevideo 1MB range: %{speed_download} B/s, first byte %{time_starttransfer}s\n' "$URL"
s=$(date +%s%N)
docker exec $C sh -c "cd /tmp && rm -f sp.* && yt-dlp --no-warnings --no-progress -f 'bestaudio[acodec=opus]/bestaudio' -o 'sp.%(ext)s' 'https://music.youtube.com/watch?v=$VID' >/dev/null 2>&1; ls -l sp.* | awk '{print \$5}'; rm -f sp.*"
e=$(date +%s%N); echo "full song download (7.6 MiB, 7:44): $(( (e-s)/1000000 )) ms"
