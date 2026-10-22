"""import_call.py LOGIN_FILE --list            the person's imports and how far they are
import_call.py LOGIN_FILE URL --read          only reads the playlist and says how long it took and what each song came with
import_call.py LOGIN_FILE URL [N] [--kind=playlist|liked] [--watch]

Reads the playlist at URL through the fetch service as the person in LOGIN_FILE, hands the first N songs (default all) to
the import queue (`POST /api/import`) and, with --watch, prints how far it is every 20 seconds until it finishes. Prints
no password. In Git Bash set MSYS_NO_PATHCONV=1 and PYTHONIOENCODING=utf-8."""
import hashlib, json, os, sys, time, urllib.error, urllib.parse, urllib.request

args = [a for a in sys.argv[1:] if not a.startswith('--')]
flags = [a for a in sys.argv[1:] if a.startswith('--')]
login = args[0]
link = '--list' if '--list' in flags else args[1]
count = int(args[2]) if len(args) > 2 else None
kind = next((f.split('=', 1)[1] for f in flags if f.startswith('--kind=')), 'playlist')

cfg = {}
for line in open(login, encoding='utf-8'):
    if ':' in line and not line.startswith(' '):
        k, v = line.split(':', 1)
        cfg[k.strip()] = v.strip()


def call(method, route, body=None):
    salt = 'p' + hashlib.md5(os.urandom(6)).hexdigest()[:8]
    q = {'u': cfg['user'], 't': hashlib.md5((cfg['password'] + salt).encode()).hexdigest(), 's': salt}
    url = cfg['address'].rstrip('/') + '/fetch' + route + '?' + urllib.parse.urlencode(q)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


if link == '--list':
    status, listing = call('GET', '/api/import')
    for i in listing.get('imports', []):
        print(i['id'], i['state'], f"{i['done']}/{i['total']}", 'added', i['added'], 'missing', i['missing'],
              'eta', i.get('etaSec'), i.get('paused', ''), '|', i['name'])
    sys.exit(0)

started = time.time()
status, playlist = call('POST', '/api/playlist', {'url': link})
seconds = time.time() - started
if status != 200:
    print(status, playlist)
    sys.exit(1)
if '--read' in flags:
    tracks = playlist['tracks']
    print(f"read '{playlist['name']}' ({playlist['source']}) in {seconds:.1f} s: {playlist['count']} songs, "
          f"{sum(1 for t in tracks if t.get('videoId'))} with a video id, {sum(1 for t in tracks if t.get('official'))} official, "
          f"{sum(1 for t in tracks if t.get('album'))} with an album, truncated={playlist['truncated']}")
    for t in tracks[:5]:
        print('  ', t)
    sys.exit(0)
songs = playlist['tracks'][:count]
print(f"read '{playlist['name']}' ({playlist['source']}): {playlist['count']} songs, truncated={playlist['truncated']}; importing {len(songs)}")
status, imp = call('POST', '/api/import', {'name': playlist['name'], 'kind': kind, 'source': playlist['source'], 'tracks': songs})
print(status, {k: v for k, v in imp.items() if k != 'missingSongs'})
if '--watch' in flags and status == 202:
    while True:
        time.sleep(20)
        status, now = call('GET', '/api/import/' + imp['id'])
        print(time.strftime('%H:%M:%S'), now.get('state'), 'done', now.get('done'), '/', now.get('total'),
              'added', now.get('added'), 'missing', now.get('missing'), 'eta', now.get('etaSec'),
              now.get('paused', ''), 'playlist', now.get('playlistId', '-'), flush=True)
        if now.get('state') != 'running':
            print(json.dumps({k: v for k, v in now.items()}, ensure_ascii=False)[:1500])
            break
