# encore-fetch

A small companion service for the **Encore** music app. When a person taps a
song that the music server does not have, the app asks this service; the
service finds the song on YouTube Music, downloads the best audio stream
(untouched), tags it, puts it into the music library next to the album's other
songs, asks the music server to rescan, and tells the app when the song can
be played. The song then *stays* in the library like any other.

* Python 3.11+, **standard library only** for the service itself; `yt-dlp`
  (command line) and optionally `mutagen` (tags + cover) are the only
  dependencies. `ffmpeg` is needed by yt-dlp for the remux.
* No database. A job lives in memory; the result is a file in the library.
* No second login: the app sends the music server's own Subsonic token and the
  service checks it with the music server (`ping`). Nothing is stored.

## What it does and does not do

| It does | It does not |
|---------|-------------|
| find an official upload (album version vs radio edit vs live) by track, artist, album and length | pick "something close": below a score of 4 the answer is *not found* |
| keep YouTube's best audio-only stream as it is (Opus, about 120-135 kbps VBR; AAC 256 with a Premium cookie) | transcode, or claim lossless: a lossless copy still comes from Lidarr/Soulseek |
| tag title, artist, album, track/disc number, year, cover | rewrite other files, delete anything, touch Lidarr |
| refuse to write outside the library, follow the library's `Artist/Album/NN - Title` layout | overwrite: a name clash gets ` (2)` |

## API

```
GET  /api/info                -> {"service":"encore-fetch","version":1,"features":["play-now"],"formats":["opus","m4a"]}
POST /api/play                -> 202 {"id":"...","state":"queued"}   (200 when it is already in the library)
GET  /api/play/<id>           -> {"id","state","detail?","error?","message?","songId?","path?","codec?","bitrateKbps?","stream?"}
GET  /api/play/<id>/audio     -> the song itself: the growing file while it downloads (live tail),
                                 then the finished file (Range supported)
```

`stream` appears in the job as soon as the first 24 KiB have arrived (and stays
when it is ready): a player can start on it long before the download or the
library scan has finished. It is a path on this service; the app adds the same
`u`/`t`/`s` query.

Authentication: `?u=<user>&t=<md5(password+salt)>&s=<salt>` (the Subsonic
token scheme) or the headers `X-Encore-User`, `X-Encore-Token`, `X-Encore-Salt`.

`POST /api/play` body (JSON, at most 8 KB):

```json
{"artist":"Opeth","title":"Windowpane","album":"Damnation",
 "trackNumber":5,"discNumber":1,"discTotal":1,"year":2003,
 "durationSec":467,"coverUrl":"https://cdn-images.dzcdn.net/...",
 "priority":"now"}
```

`priority` is `now` (default: somebody is waiting for this song) or `bulk`
(one of many songs being added in the background). Three workers; `bulk` jobs
may use at most two of them, so a tapped song never waits behind an album.

States: `queued -> searching -> downloading -> tagging -> indexing -> ready`, or
`failed` with `error` = `not_found | unavailable | age_restricted | blocked |
download_failed | too_big | timeout | disk_full | rate_limited | internal`.
`songId` is the id the music server gave the song (the app plays that).

## Limits and safety

* Per person: 1,000 taps a day, 3 at a time (`USER_DAILY_LIMIT`, `USER_ACTIVE_LIMIT`). **Imports are paced by the server, not counted** (ADR-100): at most `IMPORT_MAX_PER_HOUR` songs an hour from YouTube (default 200; YouTube lets a visitor without a login fetch about 300 videos an hour from one address and refuses beyond that), less for a while after a refusal.
* A song longer than 15 minutes or larger than 80 MB is refused; the library
  volume must have `MIN_FREE_GB` free (default 20).
* Input is data, never a command: no user-supplied URL is ever fetched (the
  cover may only come from a short allow-list of image hosts), every external
  command gets its arguments after `--`, file and folder names are sanitised
  and the target is verified to be inside the library.
* No access log (tokens travel in the query string); 8 KB request bodies.
* It reaches YouTube the way any yt-dlp does. That is a grey area of
  YouTube's terms, and music licensing differs by country: this is meant for
  a person's own server and own use, like the rest of the *arr stack.

## Run it locally in "fake mode" (no network, no library)

```
cd server/encore-fetch
FAKE_MODE=1 FAKE_SONG_ID=<a real song id of your server> PORT=8701 python -m encore_fetch
```

The app (or `curl`) then sees a service that "downloads" in a few seconds and
reports that song id as the result. Used for the emulator tests.

## Tests

```
cd server/encore-fetch
python -m unittest discover -s tests -v
```

75 tests, no network: scoring, library placement, request parsing, tagging, the
whole pipeline against a fake yt-dlp and a fake music server, the live tail of a
growing file, the now/bulk dispatcher, the HTTP routing, and the compose-file
editing (also against a copy of the real compose file).

## Deploy

**On the owner's homelab (CT 102, the media stack)** - no build, no download:
the service runs on the LidaTube image that is already there (Python, yt-dlp
and ffmpeg are in it) with this package mounted read-only.

```
bash server/encore-fetch/deploy.sh --check   # read-only: what is there
bash server/encore-fetch/deploy.sh           # checks, shows the plan, asks "yes", does it
bash server/encore-fetch/undeploy.sh         # takes it away again
```

`deploy.sh` copies the package to `/opt/mediastack/encore-fetch`, inserts one
service block (`compose.homelab.yaml`) before the top-level `networks:` of
`/opt/mediastack/compose.yaml` (a `.bak` copy first), validates with
`docker compose config -q` and starts *only that service*. It uses the
homelab's own way in (`ssh proxmox "pct exec 102 -- ..."`).

**Anywhere else** (any Docker host that can reach the music server and see the
library folder): copy this folder next to your compose file, add the service
from `compose.example.yaml` (it builds `Dockerfile`: Python, ffmpeg, yt-dlp,
mutagen) and `docker compose up -d encore-fetch`.

Check: `curl http://<server>:8701/api/info`. In the app: *Settings > Your
server > Play any song* finds it by itself.

Rollback: `undeploy.sh` (or `docker compose rm -sf encore-fetch`). Songs it
already added stay (they are ordinary library files).

If YouTube starts asking the server to "confirm you are not a bot", export a
`cookies.txt` of a logged-in browser into the scratch folder and set
`YT_COOKIES_FILE`; restart the container (the Docker build also updates
yt-dlp on start).

## Configuration (environment)

| Variable | Default | Meaning |
|----------|---------|---------|
| `NAVIDROME_URL` | `http://navidrome:4533` | the music server |
| `MUSIC_DIR` | `/music` | the library root (read-write) |
| `WORK_DIR` | `/work` | scratch space |
| `PORT` | `8701` | |
| `MIN_FREE_GB` | `20` | stop fetching below this much free space |
| `MAX_DURATION_S` / `MAX_FILE_MB` | `900` / `80` | refuse mixes and loops |
| `USER_DAILY_LIMIT` / `USER_ACTIVE_LIMIT` | `1000` / `3` | per person (taps) |
| `IMPORT_WORKERS` / `IMPORT_GAP_S` / `IMPORT_MAX_PER_HOUR` | `2` / `2` / `200` | the import queue: songs at once, pause after each, songs an hour (everybody together, taps included) |
| `LOOKUP_ALBUMS` | `1` | fill in a song's album, cover, track number and year from Deezer's public catalogue when a playlist did not give them (`0` = never) |
| `YT_COOKIES_FILE` | none | a Netscape `cookies.txt` of a (throwaway) YouTube login: raises YouTube's allowance to about 2,000 videos an hour and lets age-restricted songs be fetched. Never commit it |
| `CACHE_MB` | `1500` | finished downloads kept (by upload) so a song one person fetched is there at once for the next; the oldest go first; `0` keeps none. Each person still gets their own copy and their own tags |
| `WORKERS` | `3` | parallel downloads (one is always kept free for a song somebody just tapped; an album being added uses the others) |
| `NAVIDROME_ADMIN_USER` / `_PASSWORD` | unset | lets the service ask for a scan when the person's account may not |
| `YT_COOKIES_FILE` | unset | cookies.txt for YouTube |
| `YTDLP` | `yt-dlp` | the command |
| `PEOPLE` | `0` | `1` = one library per person: a song goes to the requester's own folder under `MUSIC_DIR` (docs/26); a person with no folder is refused at once (`no_library`) |
| `PERSON_FOLDERS` | none | `owner=owner-added,sara=sara2`: a person whose folder is called differently (for example an existing collection mounted read-only) |
| `FAKE_MODE` | `0` | `1` = no YouTube, no library (tests) |
