# 04 — Target architecture (system design)

What runs where, how the parts talk, and why each choice beats the alternatives. Decisions are summarised in
[`11-decision-log.md`](11-decision-log.md) as ADR-R1…; this page is the picture.

## 1. The whole system on one page

```
 PHONE (Android app, later web/PC client)                          THE HOST'S COMPUTER (any spare PC, Linux, Docker hidden)
 ┌──────────────────────────────────────┐                          ┌──────────────────────────────────────────────────────────┐
 │ UI (Flutter)                         │   one address:           │  encore-server  (one container, Python, port 4533)        │
 │  ├─ local database (drift/SQLite)    │   http://encore.local    │   ├─ gateway: /encore/* here, everything else → Navidrome  │
 │  │   = what the screen shows          │   or https://x.ts.net   │   ├─ accounts & devices (tokens; passwords never stored)   │
 │  ├─ sync: library, playback state ◄──┼──── websocket live ─────►│   ├─ library: likes, playlists, saved albums = song refs   │
 │  ├─ player (just_audio)              │──── HTTPS / HTTP ───────►│   ├─ playback: position, queue, which device plays          │
 │  │   kept file  → /rest/stream (ND)  │                          │   ├─ catalogue: search (Deezer metadata + YouTube Music)    │
 │  │   catalogue  → /encore/stream/…   │                          │   ├─ sources/youtube: resolve (yt-dlp in process), stream   │
 │  │   downloaded → local file         │                          │   │     proxy with Range, URL cache, pacing + back-off      │
 │  └─ downloads (files + covers)       │                          │   ├─ keeper: background copy of saved songs → music folder  │
 └──────────────────────────────────────┘                          │   ├─ imports: links/files → playlists of song refs          │
                                                                   │   ├─ people: invites, roles, password resets                │
                                                                   │   ├─ admin web app + setup wizard                           │
                                                                   │   └─ encore.db (SQLite)                                     │
                                                                   │  navidrome  (container, not published)                     │
                                                                   │   files → scan → Subsonic API, streaming, transcoding      │
                                                                   │  tailscale  (optional container: public HTTPS → gateway)   │
                                                                   │  /music (the Host's folder; kept songs in /music/Encore/)  │
                                                                   └──────────────────────────────────────────────────────────┘
                                         YouTube / YouTube Music, Deezer API, LRCLIB (lyrics), MusicBrainz (tags)
```

Two containers by default (+ Tailscale for away from home; + Lidarr, slskd, Soularr when the Host switches the quality tier on).
One published port. One database file plus Navidrome's own.

## 2. Server: one program with modules (ADR-R3)

**Encore server** = one Python 3.12 process: Starlette/FastAPI on uvicorn (async), SQLite (WAL) at `/data/encore.db`, published as
a multi-arch image (amd64, arm64) on GitHub Container Registry. Modules are folders inside one package with clear interfaces;
they share one HTTP client, one database, one auth check, one config.

| Module | Owns | Talks to | Replaces (old) |
|--------|------|----------|----------------|
| `gateway` | One port; routes `/encore/*` to modules, proxies the rest to Navidrome (Subsonic API, covers, streams, Navidrome's own web UI for tinkerers); authenticates every request once | Navidrome (internal network) | Six ports, `ServiceFinder`, the "one answer" endpoint |
| `accounts` | Sign-in (checks the password with Navidrome once), **device tokens** (long-lived, revocable, per device), device names | Navidrome native API | Subsonic tokens with the password kept on the phone |
| `library` | Per person: likes, playlists, saved albums/artists, play history. Entries are **song refs** (§3) | `catalogue`, `keeper`, mirror to Navidrome | Navidrome as the store; "pending likes"; "instant playlist"; "upgrade map" |
| `playback` | Per person: current song ref, position, queue, context, repeat/shuffle, **active device lease** | `live` | nothing (new requirement) |
| `live` | One websocket per device: `playback.*`, `library.changed`, `import.progress`, `device.takeover`, later `jam.*` | every module | 3-second polling probe; the Jam hub's SSE |
| `catalogue` | Search (Deezer for clean metadata, ISRC, covers; YouTube Music for audio-backed song results), song ref creation, matching, cover URLs | Deezer API, `ytmusicapi` | the app's Deezer client + the fetch service's resolver |
| `sources/youtube` | Resolve a song ref to a stream (one YTM search if no video id, one yt-dlp extraction in a warm worker), stream proxy with Range, URL cache (~5 h), **pacing**, back-off, health | YouTube | `encore-fetch` resolve/download/jobs |
| `keeper` | Background copy of saved songs into `/music/Encore/Artist/Album/NN - Title.opus`, tags (incl. ISRC/MBID), asks Navidrome to scan, links ref → Navidrome song id, disk floor | `sources`, Navidrome | per-person folders, the import download queue |
| `imports` | Read a link or file (YTM playlist via `ytmusicapi`, Spotify embed ≤ 100, Spotify/YouTube export files), create the playlist of refs, queue matching and keeping | `catalogue`, `library`, `keeper` | `playlists.py`, `imports.py` |
| `people` | Invitations (link + QR), roles, password reset by the Host, lock/remove; creates Navidrome users with the admin login | Navidrome admin API | `encore-people` |
| `admin` | Setup wizard and admin pages (static web app served by the same process) | all modules | `encore-admin` without Docker control |
| `jam`, `recs`, `quality` | v1 modules built in phase P4 (`quality` is switched on by the Host) | `live`, `library`, Lidarr/slskd/Soularr | `hub`, `encore-recs`, `encore-quality` |

**Why one program beats services here.** A home server has one owner, one machine, no separate teams and no need to scale parts
separately. One process means one install, one update, one port, one log, one auth check and transactions across modules (a like
and its keep job are one write). Microservices bought only cost (C1, C2). A module can still be split out later if it ever needs
to be.

**Why Python.** yt-dlp is Python; running it *in the same process* (warm workers, cached player code) is the measured speed win
(B3). Most of the existing server code is Python and well-tested; it can be moved, not rewritten.

**Why SQLite.** One file, no admin, trivial backup (`VACUUM INTO`), fast enough for a household (thousands of songs, tens of
people). PostgreSQL would add a container and an administrator for no benefit.

## 3. The data model: songs are references; files are attached (ADR-R4)

```
song_ref (id: "enc_…")         one row per real-world recording Encore knows about
  title, artists[], album, duration_ms, isrc?, mbid?, deezer_id?, ytm_video_id?, cover_url?
  file_id? ──► navidrome_song_id (when the server keeps a copy), path, codec, bitrate
person_library(person, song_ref, kind: like|saved_album|…, at)
playlist(id, owner, name, cover?, …)   playlist_entry(playlist, position, song_ref, added_by, at)
play_event(person, song_ref, at, ms_played, device)          → Year in Music, history, "recently played"
playback_state(person, song_ref, position_ms, queue[], context, shuffle, repeat, active_device, updated_at)
device(id, person, name, token_hash, last_seen)
keep_job(song_ref, state, attempts, last_error, priority)     import(id, person, source, state, counts)
```

* A **song ref** exists the moment anyone sees a song (search, import, recommendation). It is the identity used everywhere:
  likes, playlists, queues, playback state, history.
* A **file** is attached when the server keeps the song (or it was already in the Host's folder: the scanner's songs get refs
  too, matched by ISRC/MBID/tags). Replacing a file (better quality later, re-tag, move) only changes `file_id`; likes and
  playlists never move. This removes the upgrade map, pending likes and the special imported-playlist page (C3).
* **Navidrome mirror (one-way):** for every playlist and like, the songs that have files are mirrored into Navidrome's playlists
  and stars, so Subsonic apps (Tinkerer persona) still see them. Edits made in other apps are not read back in v1 (stated in the
  docs; revisit if Tinkerers ask).
* **Shared pool, private libraries (owner decision D-2):** kept audio lives **once** in `/music/Encore/`; each person's library,
  history and recommendation profile are their own. The Host's existing collection is scanned as it is (read-only mount).
* **When a song is kept (D-3):** saved (like, playlist, album, import), downloaded to a phone, or played by someone on **2 different
  days** (setting `keep_after_play_days`). Nothing else fills the disk; the free-space floor stops keeping.

**Alternatives considered.** (a) Keep Navidrome as the store and patch around it: what exists today; each patch loses data in a
new way. (b) Silent stub files in the library for not-yet-kept songs, replaced in place later: keeps Navidrome as the store, but
puts fake files in people's music folders, confuses other apps, and depends on scan timing (rejected). (c) Replace Navidrome
entirely: months of work rebuilding scanning and streaming (rejected). The reference model is how Spotify works and the only one
where "like anything, play anything, keep it forever" is natural.

## 4. Playing a song (the path that must be fast)

**Length does not matter for starting** (owner asked about a 2-hour Surat Al-Baqarah): the player starts on the first chunk and
jumps are Range requests. Measured on the server for songs nobody had played there: a 2:21:21 recitation (163 MB) was ready to
play in **2.7 s** and a jump to 2:07:00 delivered audio in **0.4 s**; three obscure 3–4-minute songs were ready in **1.6–1.8 s**
(`09` §2.5). Today's code refuses anything over 45 minutes or 80 MB; those limits must apply only to *keeping*, never to playing.

```
tap ─► app: song ref has a local download? ── yes ─► play file (≤ 0.3 s)
        │ no
        ├─ has a server file? ── yes ─► GET /rest/stream?id=… via gateway (transcode to Opus 128 away from home)  (≤ 0.7 s LAN)
        │ no
        └─ GET /encore/stream/{ref}  (server):
              URL cache hit?  ── yes ─► proxy bytes from googlevideo (first byte ~0.2 s)
              no ─► interactive worker: [YTM search if no video id ~0.5–2 s] + [yt-dlp extract ~1.3–2.5 s] ─► proxy
              (the proxy also writes the bytes to the keeper's cache, so a later "save" needs no second download)
```

**Measured (`09` §2):** server, warm process, one search + one extraction → first audio byte in **3.0–4.0 s** under the old
3 Mbit/s cap; 188 of 189 songs of a real playlist resolved in 53 s with 6 workers once the cap was raised (per-song p50 1.6 s).
**Making it feel instant (N3):** the app asks the server to *prepare* (resolve, not download) the top search result after typing
pauses for 400 ms, the first 3 songs of a page that opens, and the next 2 songs of the queue. A prepared tap starts in ~0.5–1 s.

**Two pools on the server:** *interactive* (taps and prepares; never waits behind anything) and *background* (imports' matching
and the keeper). Measured: 6 parallel extractions made each one 9 s instead of 2 s on a 4-vCPU VM under the cap, so background
work must never share workers with taps. Worker counts are sized from the machine at start-up (CPU cores, measured extraction time).

**Optional optimisation at home (proved, `09` §2.4):** YouTube's stream address is tied to the home's public IP address; a phone on
the home Wi-Fi shares it, so for *downloads* the server can hand the phone the stream address and the phone fetches at full line
speed without going through the server (12 songs, 51.5 MB in 23 s from a PC on the same line). Away from home this fails (403)
and the app falls back to the server proxy. Use it for downloads only in v1; playback goes through the proxy (one path to debug).

## 5. YouTube safety: pacing for everyone, everywhere (ADR-R6)

Encore will run on residential lines, CGNAT addresses shared with strangers, VPS addresses YouTube distrusts, and in countries
where YouTube is slow or blocked. The source module must protect the Host's address and degrade honestly.

* **No bursts.** A token bucket per server: interactive look-ups always allowed at a human pace; background look-ups default to
  **≤ 120 per hour** with random spacing, configurable in Advanced. (One burst on 2026-10-21 passed without refusal; that is one
  sample on one address and not a basis for defaults.)
* **Back-off on the first sign of trouble** ("Sign in to confirm you're not a bot", HTTP 429, repeated 403): background stops for
  30 min, doubling up to 24 h; interactive continues at a trickle; the admin Health page says so in plain words.
* **Share work:** one resolution per video at a time (others wait on it), URL cache ~5 h, kept files reused by everyone.
* **No Google account on the server.** A cookies file exists only as an Advanced setting with a warning (throwaway account).
* **PO-token provider** (`bgutil-ytdlp-pot-provider`) as an optional sidecar if the default client stops working; keep yt-dlp
  updated automatically (daily check, pinned to releases older than 24 h).
* **Country and address reality:** on first start the server tests YouTube reachability; if blocked, the source is shown as
  "Not available here" and the app works as a library player (search shows only the server's songs).

## 6. Lines, machines and countries (designing for everyone)

| Variable | Range to support | What the design does |
|----------|------------------|----------------------|
| CPU / RAM | Raspberry Pi 4 (4 cores, 2–4 GB) → desktop | Worker counts from measured extraction time; target ≤ 600 MB RAM for the whole stack |
| Disk | One small SSD → many TB | Free-space floor (default 10 GB) stops the keeper; "remove songs nobody saved" |
| Download speed | 5 Mbit/s → 1 Gbit/s | Interactive streams need ~20 KB/s; background keeping has a speed limit setting (default: none; "polite" preset) |
| Upload speed | 0.5 Mbit/s → 1 Gbit/s | Away-from-home streams transcode to Opus 96–128 kbps by default; the wizard measures upload and says how many listeners it supports |
| Address | home, CGNAT, VPS, blocked | §5; Funnel works behind CGNAT |
| Country | YouTube allowed/blocked; songs geo-blocked | reachability test; "not available in your country" per song; Deezer search uses the server's country |
| Language | English first; Arabic, French, Spanish…; non-Latin titles | All matching uses Unicode-normalised text (already in `textnorm.py`); UI strings in one file from day one so translations are a later drop-in; RTL layout tested on one screen per release |

## 7. Installing and updating (what a Host experiences) (ADR-R7)

**v1:** a Linux install script, a browser wizard, a tiny CLI. Docker is used underneath and never mentioned to a Host.

1. **Website step 1 — "Install Ubuntu Server 26.04 LTS on the spare PC"** (link, 5-minute video). Any Debian-based 64-bit Linux works.
2. **Step 2 — paste one command:** `curl -fsSL https://get.encore.<domain> | sudo sh`
   * checks the system (64-bit, x86-64/ARM64, ≥ 2 GB RAM, ≥ 20 GB free), installs Docker from Docker's repository if missing
     (says so first), creates `/opt/encore` with `compose.yaml` and a generated `.env`, pulls published images, starts them, and
     enables `encore.local` on the network (mDNS) so nobody types an IP address;
   * ends with: "Open **http://encore.local** on your phone or computer" + a QR code in the terminal.
3. **Step 3 — the setup wizard in the browser** (owner account, music folder picker that lists the computer's disks, server name,
   checks, optional away-from-home, first invitation).
4. **Day to day:** the admin page; `encore` CLI for `status`, `update`, `logs`, `backup`, `restore`, `uninstall`.

**Options considered.** (a) *Docker commands in a guide* (today): fails "never used Docker". (b) **One command + web wizard**
(chosen): one paste, then buttons; works on any Debian/Ubuntu machine, x86 or ARM; easy to update. (c) *A flashable "Encore OS"
image* (like Home Assistant OS): the friendliest (download, write to a USB stick, boot), but Encore would maintain an operating
system (kernels, drivers, security updates); a candidate after v1 if the website shows Hosts struggling with step 1. (d) *A
desktop GUI installer (.deb/AppImage)*: only helps people with a desktop session, differs per distribution. (e) *Native install
without Docker*: ffmpeg/deno/Python versions differ per distribution; updates and rollback are harder; Docker hides that.
(f) *Windows*: many spare PCs run Windows; Docker Desktop is heavy and fragile; later, if asked for.

## 8. The app's architecture (what changes)

Keep: Flutter, Riverpod, drift (local DB as the screen's source), the outbox pattern, `just_audio` + `audio_service`, the design
tokens. Change:

| Area | Today | Target |
|------|-------|--------|
| Remote truth | Navidrome via Subsonic (stars, playlists) + several Encore services | **Encore API** for library, playback, imports, people; Subsonic only for streaming/covers of files (through the gateway) |
| Identity | Navidrome song id (+ Deezer id for catalogue) | `song_ref` id everywhere; local `Tracks` table keyed by ref with optional file id |
| Network discovery | probes ports and paths per service | one base URL per server (+ `encore.local` and the public address, raced) |
| Live updates | 3 s adaptive probe | websocket `live` channel; probe only as fallback |
| Playback | engine wrapped by `JamPlaybackFacade` | engine + `TrackSource` resolver (download / file / catalogue stream) + **playback sync** (state to server on pause/seek/track change and every 15 s; takeover handling); Jam later as a separate layer |
| Covers | URL per widget size; letter-tile fallback | one canonical cover per album/song ref, stored with downloads and in a bounded disk cache, resized locally; letter tiles only when no cover exists anywhere |
| Offline | banner + rows look playable | rows greyed when unavailable; no banner; engine never auto-skips on "unavailable" |
| Auth | password stored, Subsonic token per request | device token from `accounts`; password never stored |
| Removed | portal client/discovery/download-service sheet, second import screen, ServiceFinder, multi-service capability probing | |

**The client rule (ADR-R38, owner 2026-10-23).** Every client (the Android app, later a web, desktop, iOS or TV client) talks **only to its own Encore server**; the server talks to
YouTube, Deezer, LRCLIB and every other outside service. Audio, imports and matching already work this way. Search, previews, new-release checks, lyrics and some covers still
go from the phone to the outside; the list, the files and the tasks that remove them are in `11` ADR-R38. Anything a media element fetches by itself (stream, cover, preview,
download) uses a short-lived signed address, because a browser's audio element cannot send a login header (`17` §1). Phone-only shortcuts (X-3, X-5) are allowed as extras, never as the
only route. A new client should need no server change beyond ordinary additions to the API.

## 9. Remote access (unchanged choice, new shape)

Tailscale Funnel sidecar publishes **only the gateway** (`serve.json` → `encore-server:4533`). The wizard guides the two console
clicks and the key; health checks key expiry. Caddy with a domain stays an Advanced option. The websocket and audio streaming go
through the same address (verify websockets through Funnel: experiment X-7).

## 10. Many people at once: the rules that prevent spaghetti (ADR-R8)

Owner (2026-10-21): *"what if my friend imports a playlist and plays a song, what if a song is in the playlist but not loaded yet,
what if she imports songs I already have…"* Every one of these is answered by four objects and five rules, not by special cases.

**Objects**
* **Song ref**: one per real recording, shared by everybody on the server (§3).
* **Audio state of a song ref** (shared): `remote` (no file; playable by streaming) → `fetching` (one download in progress) →
  `kept` (file attached) — or `unavailable` (not found / blocked / removed, with the reason and a retry time).
* **Fetch session**: at most **one per video id** on the server. It downloads into a cache file; any number of *readers* (players,
  the keeper) read from it while it grows. A reader asking for bytes not downloaded yet (a jump near the end of a 2-hour
  recitation) gets those bytes proxied straight from YouTube by Range request, so nobody waits for the download to catch up.
* **Work item**: `{kind: play|prepare|match|keep, song_ref, person, priority}` in one scheduler.

**Rules**
1. **Single flight.** Before any look-up or download, check for an in-flight one with the same key (video id, or the normalised
   query for a match); if there is one, join it. Two people tapping the same new song cause one look-up and one download.
2. **Reuse before work.** A song ref that is `kept` plays from the file; a resolved stream address is reused until it expires
   (~5 h); a match found for one person's import is reused for everyone's (same ISRC, same video id, or same normalised artist +
   title + duration ±3 s).
3. **Priorities, strictly in this order:** `play` (someone pressed it) > `prepare` (likely next tap) > `download` (someone asked to
   download a song the server does not keep yet, `23` §2) > `match` (import rows on screen first) > `keep` (background copy) >
   `measure` (loudness, P1-13). A tap on a song whose keep job is queued or running is promoted to P0; if
   its fetch session exists, the player becomes a reader of it.
4. **Fair share inside a priority.** Work items of the same priority are taken round-robin **per person**, so a 2,000-song import
   cannot starve a friend's 20-song import, and two people tapping at once are served in turn. Per-person caps: 3 concurrent
   `play`, 1 concurrent import being matched.
5. **One shared YouTube budget** for the whole server (§5): interactive work is always allowed at a human pace; background work
   uses what is left, and stops first when YouTube pushes back.

**The owner's cases, answered**

| Situation | What happens |
|-----------|--------------|
| Friend imports a 200-song playlist | Her playlist (200 refs) exists in ≤ 5 s; matching runs at P2 (rows on her screen first), keeping at P3, both fair-shared with others |
| …and plays song 57 before it is loaded | P0: streams in ~2–3 s (the ref already has a video id from the import, so no search); the keep job for song 57 reuses the fetch session |
| …and 40 of her songs were already kept because I imported them | Those 40 refs are the same refs: `kept`; they play from the file at once; no work is queued for them; she learns nothing about my library (the song simply plays fast) |
| We both import playlists at the same time | Two imports, round-robin per person within each priority; overlapping songs are fetched once (rule 1) |
| We both tap the same never-heard song at the same second | One look-up, one fetch session, two readers |
| She presses Stop on her import | Her queued `match`/`keep` items are cancelled at once; items that another person also needs keep running for them; a running download for her alone is cancelled within 2 s |
| I delete a song from my playlist | Only my playlist changes; the file stays if anyone still saved the song; files nobody has saved for 30 days can be removed from the admin page (Host's choice) |
| YouTube refuses the server while imports run | Background (`match`, `keep`) pauses with back-off; taps still try at a trickle and say plainly if they fail; imports resume by themselves |
| A song in her import is not on YouTube | That entry becomes `unavailable` with "Not found" in her playlist and a "Find it" button (manual search); the rest are unaffected |
| The server restarts in the middle | Work items are rows in SQLite; on start, `play` items are dropped (the phone retries), `match`/`keep` resume; half-written cache files are discarded |

## 11. What is removed from the server

`encore-admin` Docker socket and Firefox sign-in (C5, C6); per-person folders; `server/migrate/owner-server/`;
`server/portal-patches/`; local image builds. (`encore-quality`, `encore-recs` and `hub` are not removed: phase P4 rebuilds them as
modules `quality`, `recs`, `jam`.)
