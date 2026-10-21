set -u
C=encore-fetch
t() { local s=$(date +%s.%N); "$@" >/tmp/o.$$ 2>/tmp/e.$$; local rc=$?; local e=$(date +%s.%N); printf '%-40s rc=%s %6.2fs\n' "$LABEL" "$rc" "$(echo "$e - $s" | bc)"; }
LABEL="YT Music search page flat" t docker exec $C yt-dlp --no-warnings --flat-playlist -J "https://music.youtube.com/search?q=Gojira%20Stranded"
VID=$(python3 -c "import json,sys; d=json.load(open('/tmp/o.$$')); print([e['id'] for e in d['entries'] if e.get('ie_key')=='Youtube'][0])")
echo "first song hit: $VID"
LABEL="ytsearch3 flat (plain search)" t docker exec $C yt-dlp --no-warnings --flat-playlist -J "ytsearch3:Gojira Stranded"
LABEL="ytsearch8 flat again" t docker exec $C yt-dlp --no-warnings --flat-playlist -J "ytsearch8:Gojira Stranded"
LABEL="-j one watch page (extract)" t docker exec $C yt-dlp --no-warnings -f "bestaudio[acodec=opus]/bestaudio" -j "https://music.youtube.com/watch?v=$VID"
grep -o '"format_id": "[0-9a-z-]*"' /tmp/o.$$ | tail -1; tail -c 300 /tmp/e.$$; echo
LABEL="-j same again" t docker exec $C yt-dlp --no-warnings -f "bestaudio[acodec=opus]/bestaudio" -j "https://music.youtube.com/watch?v=$VID"
LABEL="download bestaudio to /tmp" t docker exec $C sh -c "cd /tmp && rm -f bench.* && yt-dlp --no-warnings --no-progress -f 'bestaudio[acodec=opus]/bestaudio' -o 'bench.%(ext)s' 'https://music.youtube.com/watch?v=$VID' && ls -la bench.*"
tail -2 /tmp/o.$$; tail -c 300 /tmp/e.$$; echo
LABEL="download again verbose (speed line)" t docker exec $C sh -c "cd /tmp && rm -f bench.* && yt-dlp --no-warnings --newline -f 'bestaudio[acodec=opus]/bestaudio' -o 'bench.%(ext)s' 'https://music.youtube.com/watch?v=$VID'"
grep -E '100%|Destination|player API' /tmp/o.$$ | tail -4
docker exec $C sh -c 'rm -f /tmp/bench.*'
echo "--- in-process: one python process, search + extract with the library"
cat > /tmp/inproc.py <<'PY'
import time, yt_dlp
t0=time.time()
o={'quiet':True,'no_warnings':True,'skip_download':True,'format':'bestaudio[acodec=opus]/bestaudio'}
with yt_dlp.YoutubeDL({**o,'extract_flat':True}) as y:
    r=y.extract_info('https://music.youtube.com/search?q=Opeth%20Windowpane',download=False)
ids=[e['id'] for e in r['entries'] if e.get('ie_key')=='Youtube']
t1=time.time(); print('search %.2fs'%(t1-t0), ids[:3])
with yt_dlp.YoutubeDL(o) as y:
    i=y.extract_info('https://music.youtube.com/watch?v='+ids[0],download=False)
t2=time.time(); print('extract1 %.2fs'%(t2-t1), i.get('track'), i.get('artist'), i.get('album'), i.get('duration'), i.get('format_id'), i.get('abr'))
with yt_dlp.YoutubeDL(o) as y:
    i=y.extract_info('https://music.youtube.com/watch?v='+ids[1],download=False)
t3=time.time(); print('extract2 (warm process) %.2fs'%(t3-t2), i.get('track'), i.get('format_id'))
PY
docker cp /tmp/inproc.py $C:/tmp/inproc.py >/dev/null 2>&1 || docker exec -i $C sh -c 'cat > /tmp/inproc.py' < /tmp/inproc.py
LABEL="in-process total" t docker exec $C python3 /tmp/inproc.py
cat /tmp/o.$$; tail -c 300 /tmp/e.$$
docker exec $C rm -f /tmp/inproc.py
rm -f /tmp/o.$$ /tmp/e.$$ /tmp/inproc.py
