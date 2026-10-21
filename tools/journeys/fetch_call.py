"""fetch_call.py LOGIN_FILE ROUTE JSON  - one call to the fetch service as the person in LOGIN_FILE (the password is never printed). In Git Bash set MSYS_NO_PATHCONV=1, or /api/... is rewritten into a Windows path."""
import hashlib, json, os, sys, urllib.error, urllib.parse, urllib.request

login, route, body = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = {}
for line in open(login, encoding='utf-8'):
    if ':' in line and not line.startswith(' '):
        k, v = line.split(':', 1)
        cfg[k.strip()] = v.strip()
salt = 'p' + hashlib.md5(os.urandom(6)).hexdigest()[:8]
q = {'u': cfg['user'], 't': hashlib.md5((cfg['password'] + salt).encode()).hexdigest(), 's': salt}
url = cfg['address'].rstrip('/') + '/fetch' + route + '?' + urllib.parse.urlencode(q)
req = urllib.request.Request(url, data=body.encode(), method='POST', headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
        print(r.status)
except urllib.error.HTTPError as e:
    data = json.loads(e.read() or b'{}')
    print(e.code)
tracks = data.pop('tracks', None)
print({k: v for k, v in data.items()})
if tracks:
    for t in tracks[:6]:
        print('  ', t)
    print('   ...', len(tracks), 'tracks')
