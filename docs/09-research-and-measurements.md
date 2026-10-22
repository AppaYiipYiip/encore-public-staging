# 09 — Research and measurements

Everything here was measured or looked up on **2026-10-21**. Measurement scripts are in [`evidence/scripts/`](evidence/scripts/)
(they are measurement tools, not product code). "Dev VM" = `encore-dev` (4 vCPU, 4.8 GB, Debian, Docker; on the owner's Proxmox
host); "CT 104" = the old Encore test server; "PC" = the owner's Windows laptop on the same home line.

## 1. The line and the server cap

| What | Result |
|------|--------|
| Homelab host shaping found | ingress CAKE **3 Mbit/s** on `ifbdown0` for everything the Proxmox host and its containers/VMs download (set from the owner's dashboard, `/var/lib/libdash/server-down-limit.json`); egress CAKE 5 Mbit/s by day / 8 at night for internet uploads; LAN unshaped |
| Under the 3 Mbit/s cap (dev VM) | Cloudflare 8 MB: 108–114 KB/s (70–74 s); googlevideo 1 MB range: 88–100 KB/s; a 7.6 MB song via yt-dlp: **71 s**; 4 MB song: 47–56 s at ~79 KB/s |
| Cap removed for 2 minutes | Cloudflare 8 MB: **1.58 MB/s (5.1 s)**; googlevideo: 1.77 MB/s; the 7.6 MB song: **5.5 s** |
| Upload (dev VM → Cloudflare, 2 MB) | 920 KB/s (~7.4 Mbit/s) |
| Now | The owner allowed changing it; set to **15 Mbit/s** (`in force 15000 kbit/s`); measured 1.94 MB/s |
| What else used the line during the tests | Proxmox `nic0` 366 KB/s in; the media-stack container 104 KB/s in / 236 KB/s out (the owner's other services); the family |

## 2. Playing a song the server does not have

### 2.1 Today's app and server (build 40, CT 104, 3 Mbit/s cap)

| Case | Result |
|------|--------|
| Search "Khruangbin Maria Tambien" → tap the song | **38.3 s** tap → audible; server: `searching +35.5 s`, then download |
| "Daft Punk – Instant Crush" | server `searching +33.3 s`, `downloading +40.7 s`, `ready +107.8 s` |
| A song whose page was open ~100 s before the tap (prepared) | ~3.5 s |
| A song fetched earlier by someone (server cache) | < 4 s |
| Imported YouTube Music song tapped ("Nelly – Dilemma") | server searched again for 7–15 s although the playlist gave its video id |

### 2.2 yt-dlp command-line costs (dev VM, 3 Mbit/s cap)

| Step | Time |
|------|------|
| `yt-dlp --version` (start-up) / `import yt_dlp` | 0.60 s / 0.61 s |
| `ytsearch8` flat (plain YouTube search) | 9.42 s first, 3.59 s later; `ytsearch3` 4.37 s |
| YouTube Music search page, flat | 2.70–2.89 s |
| `-j` one watch page (full extraction) | 3.8–4.5 s |
| Player clients without a PO token | only `visionos` returned audio; `web`, `web_music`, `android_vr`, `web_safari` → "Requested format is not available"; `tv` → "The page needs to be reloaded" |
| Configuration seen | yt-dlp 2026.08.19, yt-dlp-ejs 0.8.0, Deno 2.9.7 as JS runtime, no PO-token provider |

### 2.3 The lean path (one process, `ytmusicapi` search + `yt_dlp` library) — `fastpath.py`

| Song (never resolved before in that process) | Dev VM, 3 Mbit/s cap: search / extract / first byte / **total** | PC on the home line: total |
|------|------|------|
| Khruangbin – Maria También | 2055 / 1761 / 190 / **4.0 s** | 4.0 s |
| Daft Punk – Instant Crush | 1029 / 2056 / 180 / **3.3 s** | 4.3 s |
| Opeth – Windowpane | 1132 / 1960 / 203 / **3.3 s** | 2.0 s |
| Nas – N.Y. State of Mind | 1307 / 2272 / 325 / **3.9 s** | 2.0 s |
| Fairuz – Kifak Inta | 806 / 1906 / 246 / **3.0 s** | 2.1 s |

All five picks were the right recording (title, artist, album, length). Conclusion: the search step can drop from ~34 s to ~1 s,
and the server path is about as fast as a device fetching directly (YouTube's response time dominates).

### 2.4 Many songs: parallel look-ups and direct download — `proto_resolve.py`, `proto_download.py`

| Test | Result |
|------|--------|
| 40 songs of a real playlist, 6 workers, under the 3 Mbit/s cap | 40/40 in 52.4 s (46/min); per-song p50 **8.9 s** (contention: CPU for JS challenges + the cap) |
| 189 songs, 6 workers, 15 Mbit/s | 188/189 in 52.8 s (**214/min**), per-song p50 1.6 s; 1 failure = age-restricted ("Sign in to confirm your age"), not a block. **One sample on one address; not a basis for defaults (`04` §5)** |
| Afterwards, one look-up | normal (address not flagged) |
| Server downloads, 30 songs, 4 workers, 15 Mbit/s | 130.3 MB in 92.6 s = 1.41 MB/s |
| Stream addresses | contain `ip=<home public address>`; a **PC on the same line** downloaded server-resolved addresses directly: 1 song 4.0 MB in 1.8 s (2.25 MB/s); 12 songs 51.5 MB in 23.4 s (2.21 MB/s, line-bound) |

### 2.5 Hard cases — `hardcases.py` (dev VM, 15 Mbit/s, fresh process)

| Case | Size | Search / extract / first byte | Ready to play | Jump near the end |
|------|------|-------------------------------|---------------|-------------------|
| Surah Al-Baqarah, Mishary Alafasy, 2:21:21 | 163 MB | 1026 / 1489 / 86 ms | **2.7 s** | to 90 % (2:07:00): first byte 229 ms, 256 KB in 394 ms |
| Oum – Taragalte (obscure) | 3 MB | 457 / 895 / 220 ms | **1.65 s** | — |
| "Mehdi Nassouli Mogador" → top result was "Mimouna" | 4 MB | 414 / 924 / 189 ms | 1.63 s | — (wrong song: matching must check title) |
| Hindi Zahra – Kiss & Thrills | 4 MB | 480 / 948 / 317 ms | 1.83 s | — |

## 3. Importing: reading the list — `import_speed.py` (dev VM, 3 Mbit/s cap)

| Playlist (real) | Songs | Time to read the full list |
|------|------:|------|
| YouTube Music "'00s Hip Hop" (`RDCLAK5uy_n4g8XbXdlPTtik7Fwl4RU3Gij-63HBsmo`) | 189, all with video ids | 3.2 s (2.1 s later at 15 Mbit/s) |
| YouTube Music "Essential '90s Hip Hop" | 133, all with video ids | 2.4 s |
| Spotify `3dEfExamplePlaylistC03` (owner's) | 100 (embed limit) | 3.5 s |
| Spotify `3dEfExamplePlaylistB02` (owner's) | 100 (embed limit) | 2.4 s |
| Spotify `3dEfExamplePlaylistA01` (owner's) | 69 | 2.2 s |
| Today's app importing '00s Hip Hop | list in ~7 s, then "about 60 minutes", later "about **2.3 hours** left"; says "Import 200 songs" for 189 | |

## 4. External facts (with sources)

| Fact | Source |
|------|--------|
| yt-dlp PO-token table (last edited 2026-07-12): GVS tokens required for `web`, `web_safari`, `mweb`, `tv_simply`, `web_music`, `web_creator`, `android`, `ios`; not for `tv` (DRM without cookies), `web_embedded`, `android_vr` (no "made for kids"); recommended provider `bgutil-ytdlp-pot-provider`; tokens may last ~12 h | [yt-dlp PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide) |
| Guest limit guidance ~300 videos/hour (~1,000 page/player requests), accounts ~2,000/hour; suggested 5–10 s sleep between downloads | [yt-dlp wiki: Extractors](https://github.com/yt-dlp/yt-dlp/wiki/extractors) (page ~16 months old) |
| PO tokens and SABR explained; bgutil is the de-facto provider | [Big Iron guide](https://www.bigiron.cc/guides/yt-dlp-po-tokens-and-sabr-why-downloads-keep-breaking) |
| Spotify development mode (Feb 2026): app owner needs Premium, 5 users per app, several endpoints deprecated | [TechCrunch 2026-02-06](https://techcrunch.com/2026/02/06/spotify-changes-developer-mode-api-to-require-premium-accounts-limits-test-users/) |
| Spotify "moving away from the Client Credentials flow for metadata endpoints"; playlist fields renamed (`tracks` → `items`) | [rspotify issue #550](https://github.com/ramsayleung/rspotify/issues/550) (secondary report) |
| Spotify US Premium $12.99/month from Feb 2026; lossless (since Sept 2025) included | [TechRadar](https://www.techradar.com/audio/spotify/spotify-is-raising-its-prices-to-usd13-a-month-in-the-us-marking-the-companys-third-price-hike-in-three-years), [MusicTech](https://musictech.com/news/industry/spotify-premium-price-hike-2026/), [SoundGuys](https://www.soundguys.com/spotify-confirms-us-subscription-price-hike-151412/) |
| Plex: remote streaming needs Plex Pass or Remote Watch Pass; 2025 Plex Pass $6.99/mo, $69.99/yr, $249.99 lifetime; Remote Watch Pass $2.99/mo from June 2026; one unconfirmed report of a $750 lifetime price | [BetaNews 2025-03](https://betanews.com/2025/03/19/plex-2025-price-changes-remote-streaming-new-subscription/), [BetaNews 2025-11](https://betanews.com/2025/11/26/plex-is-clamping-down-on-free-remote-streaming/), [iphone-ticker](https://www.iphone-ticker.de/plex-verlangt-bald-mehr-fuer-remote-streaming-277410/), [Darko](https://darko.audio/2026/05/so-plex-wants-us750-now/) |
| Navidrome 0.60 (Feb 2026): WebAssembly plugin system, Instant Mix, pure-Go tag reader; plugins can be metadata agents, scrobblers, scheduled tasks, event handlers; **no custom HTTP endpoints** (so Encore cannot live inside Navidrome) | [AlternativeTo](https://alternativeto.net/news/2026/2/navidrome-0-60-adds-webassembly-based-plugin-system-new-instant-mix-feature-and-more), [Navidrome plugins](https://www.navidrome.org/docs/usage/features/plugins/) |
| Navidrome persistent ids `PID.Track` default `musicbrainz_trackid|albumid,discnumber,tracknumber,title`; multi-library since 0.58 | [Options](https://www.navidrome.org/docs/usage/configuration/options/), [Persistent IDs](https://navidrome.org/docs/usage/configuration/persistent-ids/), [Multi-library](https://www.navidrome.org/docs/usage/multi-library) |
| Lidarr's metadata server outage/rebuild; README notice | [Lidarr README](https://github.com/lidarr/lidarr) |
| Metrolist (YouTube Music client) in maintenance mode; OuterTune no longer developed | [Metrolist](https://github.com/MetrolistGroup/Metrolist) |
| Spotube 5.1: audio-source plugins; stopped using Spotify's API after pressure | [AlternativeTo](https://alternativeto.net/news/2025/11/spotube-5-1-released-with-audio-source-plugins-newpipe-integration-on-desktop-and-more) |
| NewPipeExtractor keeps up with YouTube (SABR fixes, n-parameter work) | [Releases](https://github.com/TeamNewPipe/NewPipeExtractor/releases) |

## 5. Legal and terms (not legal advice; for the website wording and the decisions)

* Downloading from YouTube breaks YouTube's Terms of Service everywhere; whether it is also unlawful depends on the country
  (private-copy exceptions differ; anti-circumvention rules may apply). yt-dlp, NewPipe and similar tools are openly published.
* Peer-to-peer (Soulseek, torrents) shares files with others, which is the riskiest part legally; in v1 but off until the Host switches it on (Q6 in `02`).
* Putting a person's Google account into an automated downloader risks that account (yt-dlp's own warning).
* The website must state plainly where songs come from, that the Host is responsible for using it lawfully where they live, and
  that the YouTube source can be switched off.

## 6. The app, walked (2026-10-21)

Findings E1–E20 with screenshots are in `01` §E. Additional measurements: cold start 3.7 s first after install, then 0.74–1.5 s
(emulator `encore_a07`); while stuck buffering the app rendered ~60 frames/s with 37–46 % janky frames, 16.8–17.2 ms/frame.

## 7. After P1-01 (2026-10-22): the lean resolver, in-process extraction and direct download, measured

All on the dev VM (4 vCPU) with the server's download cap at 15 Mbit/s, real songs never fetched there before. The VM has one YouTube
account configured from the old sign-in feature (it adds about 1 s to each extraction; a Host without one is faster).

| Measurement | Before (old resolver, one yt-dlp program per step) | After |
|-------------|-----------------------------------------------------|-------|
| Choosing the upload (search only), 3 songs, same machine and minute | 1.4 / 13.5 / 17.8 s (median **13.5 s**) | 0.44 / 0.50 / 1.00 s (median **0.50 s**) |
| Picked the right recording | "Maria También": picked a random re-upload ("Disclose Beauty") | picked the album track (title, artist, album, length all match) |
| Tap to "audio can start" (job shows a stream address), 8 songs | ~38 s in the app (33–35 s of it searching) | **4.3, 5.6, 5.9, 6.5, 8.7** s (the 4 before the direct download: 7.0–10.9 s) |
| Whole song kept on the server | 71 s under the 3 Mbit cap | 9.4–13.3 s |

Where the remaining seconds go (visitor, warm): search 0.5 s + extraction **2.0–2.4 s** (cold: 3.1–3.5 s; with an account 3.2–4.5 s) +
first bytes 0.5 s. The extraction is YouTube's own response time. **Rejected:** `player_skip=webpage` (saves the page fetch but YouTube
answers "Sign in to confirm you're not a bot"). The rest of the speed-up for likely taps comes from preparing ahead (task P1-04).

Real-answer fixtures (`server/legacy/encore-fetch/tests/fixtures/ytm`) showed two things worth remembering: YouTube Music answers
"artist title" and "title artist" differently (for one song only the second finds the studio recording), and a song result by a different
artist whose name merely contains the asked one ("Oum" / "Oum Dermam Stars") scored as acceptable under the old scoring, hence the strict
whole-name artist and title-similarity rules in `lean.py`.

### 7.1 In the app, on the emulator against the real test server (CT 104, a visitor, no account), 2026-10-22

`tools/journeys/play_timing.py`: search as a person would, tap the song, time until the player says PLAYING and the audio system has a
started track. Every song was a genuine fresh fetch (checked in the server log), never fetched on that server before.

| Song (search -> tap) | Tap to audible |
|----------------------|----------------|
| Gorillaz - Feel Good Inc. | 1.6 s |
| Arctic Monkeys - Do I Wanna Know? | 2.0 s |
| Lorde - Royals | 2.0 s |
| Billie Eilish - bad guy | 2.7 s |
| Tame Impala - Let It Happen | 4.1 s |
| The Weeknd - Blinding Lights (Remix) | 6.4 s |
| Cigarettes After Sex - Apocalypse | 7.4 s |

Median 2.7 s, slowest 7.4 s (was **38 s**). The fast ones are songs the app had already asked the server to *prepare* (search + extraction
done, 2.3-3.3 s) while the person looked at the results; the slow ones were tapped before that finished. The old build 40 app was used
unchanged: all of this comes from the server.

Two app findings while doing it (not yet in the plan's findings list): after the account's password changed, the app kept showing Home
and "Synced 3 d ago" with no prompt, and a song row said only "The instant-play service did not accept your music server login"; and
the only way to fix it was Sign out, which deletes all downloaded music (790 MB here) from the phone.

## 7.2 Reading a playlist and importing a small one (2026-10-22)

| What | Before | Now |
|---|---|---|
| Read a 149-song YouTube Music playlist (server) | yt-dlp flat listing, video titles taken apart (several seconds) | `ytmusicapi` 1.5 s on the server, 2.0 s through the public address; real artist/title/album/length/video id for 147 of 149 |
| Paste link, list on screen (app, emulator) | not measured | 1.1 s (10-song album) |
| Tap Import, playlist open and playable (app) | the list of what had arrived | 1.3 s, every row "play now" |
| Save 10 songs to the server | | about 2.5 min (about 9 s a song, two at a time; 0 missing); no title search in the server log |

A 150-song playlist therefore saves in about half an hour in the background at the same pace; that number is the pacing and
YouTube's mood, not something the person waits for (the playlist is playable at once).

## 7.3 The fast YouTube client, and streaming (2026-10-22)

Measured on CT 104 (visitor, no YouTube account), the same video, one look-up per row:

| yt-dlp `player_client` | Extraction | Does the address open at once? |
|---|---|---|
| default (yt-dlp's own choice: TV client) | 3.7 s | no: 403 for about 1.3 s here (2-4 s earlier) |
| `visionos` | **1.3 s** | **yes (0.2 s)** |
| `tv,web_safari` | failed ("The page needs to be reloaded") after 3.1 s | - |
| `android_vr` | 1.2 s, but an mp4 (itag 18) whose address never opened | no |

So the extractor tries `visionos` first for a visitor (accounts keep yt-dlp's choice) and falls back to yt-dlp's own choice.

`GET /api/stream` (first byte as the client sees it, through the public address; song found + address + first bytes in the server log):

| | before (TV client) | with `visionos` |
|---|---|---|
| fresh song, first byte | 5.3-7.5 s (found 0.9-1.1 s, address 3.3-3.9 s, wait for the address to open 1-2.5 s) | **1.9-3.5 s** (found 0.4-1.1 s, address 1.2-1.5 s) |
| 2 h 21 min recitation (163 MB), first byte | 5.7 s | **1.9 s** |
| the same, jump to 58 % / 90 %, first byte | 1.2 s / 1.1 s | 1.1 s |

In the app on the emulator (fresh songs, search, tap the Top result, audible): 2.2 s, 2.6 s, 2.9 s (three more were songs the server already
had: 0.9-1.1 s). J-10 (a two-hour recitation audible in 4 s, a seek in 2 s) holds on the server; the app plays a song of 40 minutes or more
from the stream, not yet walked on the emulator with a real long video.


## 7.4 YouTube refuses this address (2026-10-22, 06:08 UTC) and what the server now does

After about three hours of testing from the owner's home line (a few dozen look-ups and four downloads from this address, spread over the day),
the first import of a ten-song album on the new server (eight downloads started within seconds of each other, two workers) was answered
for **every** song with `Sign in to confirm you're not a bot`. Two hours earlier the same code had kept a song in 12 s. The refusal is about
the *address*, not the song or the client (`visionos` included).

What it taught:
* A refusal for one request is a refusal for all of them: the eight queued downloads each asked once more instead of waiting. Background work
  must stop at the first refusal. **Built** (`sources/youtube/rest.py`): one shared rest for the whole server (30 min, doubling for every
  refusal in a row up to a day, ended by one success, kept in the database across restarts); keeping and matching never ask while it lasts; a
  person's tap may probe once every 30 s; `GET /info` reports `youtube: {state: ok|resting, resumesInSec}` and a refused tap answers `503
  source_busy` with `retryAfterMs`.
* Testing from a home line has a cost. From now on: no YouTube traffic from the owner's address for at least two hours after a refusal, no
  imports that keep ten songs at once while testing (stop them after two or three), and every test that must hit YouTube says how many
  requests it makes.
* The old services (CT 104 and the dev VM's old stack) had no refusals in the same hours because nothing asked them; this is not a bug of the
  new server, it is what an address that has asked too much looks like. Whether the refusal ends by itself (it usually does within hours to a
  day) is measured here: the dev VM's rest was set to two hours by hand at 06:15 UTC and the first probe after it will be one look-up.
