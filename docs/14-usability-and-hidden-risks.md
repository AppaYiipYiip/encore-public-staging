# 14 — Usability gaps and hidden bugs not covered elsewhere

Owner, 2026-10-21: *"there are still many things not yet mentioned … think design, think usability, think hidden bugs."* This page is
the backlog of everything a Spotify user expects or a real phone will do that the plan did not yet cover. Each item: what, why it
matters, what to do, and which phase/task owns it (new tasks are listed in `tasks/`). IDs: **U** = usability, **H** = hidden bug or
risk (H1–H10 are in `13` §6).

## 1. Usability: what people will expect

| ID | What | Why it matters | Do | Owner |
|----|------|----------------|----|-------|
| U1 | **Tablet and large-screen layout** | The owner uses a tablet; Android 16 (target SDK 36) ignores orientation and resizability locks on large screens, so a stretched phone UI *will* appear | Adaptive layout ≥ 600 dp: navigation rail, two panes (library + content), player side panel; test landscape and split-screen | P4-11 |
| U2 | **Search that understands people** | Users type "fairouz", "فيروز", "Fairuz"; typos; transliteration matters for Arabic and French users | Unicode normalisation (NFKC, diacritics/hamza folding), transliteration aliases from the catalogue (Deezer/MusicBrainz aliases), typo tolerance in the phone's full-text search, search history | P1-07 (normalisation), P4-12 (aliases, history) |
| U3 | **Follow artists** | Feeds "New from artists you love", recommendations and release notices; Spotify users expect a Follow button | Follow on artist pages; per person; used by `recs` | P4-01 |
| U4 | **Artist pages like Spotify** | Popular songs, full discography (owned and not, one list), "Fans also like", about | Catalogue data + library; same row look for owned and not | P2-03 / P4-01 |
| U5 | **Share a song or playlist** | "Listen to this" to a friend is a core social action | Share link opens in Encore (same server: the song; other server: a portable descriptor resolved on their server, `13` §5); others get a normal web link | P4-10 |
| U6 | **Collaborative playlists** | Spotify has them; friends on the same server, and friends across servers | Playlist members with add/remove rights; across servers via the federation link | P4-10 |
| U7 | **Library organisation** | Large libraries become unusable without it | Sort (recent, alphabetical, creator), filters, pinned items, playlist folders, custom playlist cover | P4-12 |
| U8 | **"Download Liked Songs" and smart downloads** | Spotify users download Liked Songs and expect new likes to follow | Pin Liked Songs; new likes download on Wi-Fi; storage limit; "Remove all downloads" | P2-03 follow-up, P4-12 |
| U9 | **Crossfade and gapless** | Spotify has crossfade; Plexamp's transitions are a selling point | Gapless for kept/downloaded files (already partly), crossfade 0–12 s setting, never across a live/classical album marked gapless | P4-12 |
| U10 | **Voice and car** | "Hey Google, play X on Encore"; Android Auto search | Android Auto search + `MEDIA_PLAY_FROM_SEARCH` intent; voice search in the app | P4-12 |
| U11 | **Home-screen widget** | Spotify-class expectation; quick play/pause | A Glance widget (now playing, play/pause, next) | P4-12 |
| U12 | **Casting to TVs and speakers** | People own Chromecast/Google speakers | Later decision (P6); "Devices" shows only Encore devices in v1 | P6 |
| U13 | **Data saver** | Mobile data is expensive in many countries | Quality per network (exists in settings) + "Data saver" one switch; prepares/prefetch respect it | P1-04 / P4-12 |
| U14 | **The Host's view** | A Host must understand storage per person without seeing what they listen to | Admin Storage: total, kept by everyone, per-person *counts and sizes only*; a per-person storage cap option | P3-06 |
| U15 | **Problem reports** | Agents need real crash data; people won't write bug reports | Opt-in crash and problem reports sent **to the Host's own server** (never to the project), visible in admin and exportable for a bug report | P4-13 |
| U16 | **Errors and empty states in plain words everywhere** | Today some states are accidental | Every screen designed for loading / empty / offline / error (`07` §10) | P1-12, P4-06 |

## 2. Hidden bugs and risks to test for (and design against)

| ID | Risk | Likely symptom | Do | Owner |
|----|------|----------------|----|-------|
| H11 | **Volume levelling inconsistent; app quieter or louder than other apps** (`13` §1, owner's volume report) | Jumps between songs; "volume not in sync" | Server-side loudness tags for kept files; consistent target for streams; no boost by default | **P1-13** |
| H12 | **Battery savers kill playback** (Samsung, Xiaomi, Huawei, Oppo) | Music stops after the screen is off for a while; queue lost | Detect the manufacturer; a one-time guide to allow background activity (dontkillmyapp.com steps); persist state often (P1-11) | P1-11, P4-13 |
| H13 | **Audio focus and interruptions** | A call or navigation prompt does not pause/duck; music does not resume | Handle transient loss (duck), loss (pause), regain (resume only if paused by focus); test with a call on the emulator | P1-08 |
| H14 | **Headphones and Bluetooth** | Unplugging keeps playing loudly from the speaker; car head unit shows wrong title; BT buttons double-tap not working | `ACTION_AUDIO_BECOMING_NOISY` → pause; correct metadata to AVRCP; long-press/double-tap mapping | P1-08 |
| H15 | **Starting playback from the background** (Android 12+) | A Jam/remote command does nothing on a backgrounded device | `13` H1 design | P4-07 |
| H16 | **Server address changes** (DHCP gives the PC a new LAN address) | The app "can't reach the server" at home | the phone knows the server by its key and the server's own address list (`11` ADR-R40): a new address is found by mDNS or through the away address, nothing typed; `encore.local` stays for the browser wizard | P3-05, P2-19 |
| H17 | **Two devices edit the same playlist offline** | Lost or duplicated entries after reconnecting | Entry-level operations with ids (add/remove/move), server merges by operation order; test J-15 (new) | P2-02 |
| H18 | **Deleting things across devices** | A playlist deleted on the tablet reappears from the phone's outbox | Tombstones with timestamps; the outbox drops edits to deleted objects | P2-02 |
| H19 | **Downloads interrupted** (kill, reboot, storage full, Wi-Fi drop) | Half files that "play" then stop; downloads stuck at 99 % | Download to temp + verify size/hash + atomic rename; resume with Range; storage-full message | P2-03 follow-up |
| H20 | **Phone storage full** | App crashes or the database corrupts | Check free space before writes; keep a floor; clear image cache first | P1-10 |
| H21 | **Very large libraries** (50,000 songs, 10,000 likes) | Slow first sync, janky lists, memory | Paged sync, indexes, list virtualisation; perf test with a generated-from-real-metadata library | P2-02, P5-04 |
| H22 | **Duplicates**: the same song in the Host's collection and fetched from YouTube | Two rows for one song; likes split | Ref matching merges them (one ref, best file wins); "duplicate files" report in admin | P2-01 |
| H23 | **Wrong versions**: music video instead of the album track, explicit vs clean, live vs studio | Skits/intros, censored words, wrong length | Prefer YouTube Music "song" results (Topic/Art Track), explicit flag from the catalogue, duration check ±3 s | P1-01 |
| H24 | **Region blocks** | A song plays for one person and not another (different countries) | "Not available in your country" per song; Jam falls back to the adder's source | P1-02, P4-10 |
| H25 | **Server and app versions drift** | An old app breaks against a new server (or the reverse) | API versioning (`/encore/api/info` → `apiVersion`, `minAppVersion`); the server supports the last 2 app versions; the app shows "Update Encore" | P3-01, P5-02 |
| H26 | **Clock and time zones** | Year in Music in the wrong year/day; playback-state ordering wrong when a phone's clock is off | Server time is the authority for ordering; local time zone only for display | P2-08, P4-05 |
| H27 | **Unicode and odd names** | Files named with `/`, `:` or emoji fail on some disks; Arabic file names reversed | Safe file naming (already in `library.py`); test pool includes such titles | P2-01 |
| H28 | **Power loss on the server** | Half-written music files, database corruption | Temp + rename for files; SQLite WAL; backups (US-52); `encore restore` tested | P3-05 |
| H29 | **Running out of disk on the server** | Keeper fails silently; Navidrome database errors | Free-space floor stops keeping; admin warning at 90 %; music folder and data folder checked separately | P2-01, P3-06 |
| H30 | **Security on the home network** | Logins sent over plain HTTP on Wi-Fi at home | Device tokens instead of passwords (P3-03); offer HTTPS at home via the public name or a pinned certificate from the pairing QR | P3-03 |
| H31 | **Brute force on the public address** | Someone guesses passwords through Funnel | Gateway rate limits per person and per address; lock after repeated failures with Host unlock; Navidrome's limiter behind the gateway sees real addresses | P3-01 |
| H32 | **Invite links leaking** | A forwarded invite lets a stranger in | One-time use, 7-day expiry, Host sees who joined with which invite, can remove | P3-06 |
| H33 | **yt-dlp breaks overnight** | Every catalogue song fails | Daily yt-dlp update check (pinned to releases older than 24 h), canary look-up, admin Health shows it, the app says "Songs from YouTube are temporarily unavailable" | P1-03 |
| H34 | **Accessibility regressions** | New screens without labels | CI guideline tests on every screen (P1-12) | P1-12 |
| H35 | **Memory leaks during long sessions** | The app slows down after hours; images pile up | 8-hour soak test on the emulator with a long queue; image cache bound | P5-04 |
| H36 | **Someone else on the Wi-Fi claims a fresh server first** | A neighbour or housemate opens `/setup` before the Host and becomes the owner | One-time setup code printed by the installer, required by the wizard until the owner exists (`15` §1) | P3-05, P3-06 |
| H37 | **Stale downloads after a file changes on the server** (quality upgrade, "Wrong song?" fix, re-tag) | The phone keeps playing the old version forever, or a download breaks | The download manifest and replacement on Wi-Fi (`23` §2) | P2-13 |
| H47 | **The old admin's self-made HTTPS certificate** made every Host's browser show a frightening warning on the first visit; it existed only for the Google sign-in window, which is removed | First impression: "is this safe?" | Setup and admin over plain HTTP on the home network (protected by the setup code and device sessions); valid HTTPS through the server's Tailscale name for Hosts who use it | P3-06 |

## 3. New journeys for `07` §7 (added by this page)

* **J-15 Two devices edit one playlist offline.** Phone and tablet offline; phone adds 3 songs, tablet removes 1 and renames; both
  reconnect. Expect: one playlist with the rename, the removal and the 3 additions; no duplicates.
* **J-16 Control the tablet from the phone.** Same account on two emulators; tablet plays; phone moves it to 1:30, pauses, plays, sets
  volume with its hardware buttons. Expect: each action on the tablet ≤ 1 s at home, ≤ 2 s away; the tablet's own volume slider shows
  the new level.
* **J-17 Hand over.** Phone plays at 2:00; choose "Tablet" in Devices. Expect: tablet continues at 2:00 ± 1 s, phone stops, no gap > 2 s.
* **J-18 Jam across servers.** Two servers (dev VM + a second clean VM), one person each, friends via a friend QR; a Jam with: a song
  only on server A, a song only on server B, a song on neither. Expect: all three play on both phones within the sync budget; the
  server logs show each phone used its own server first.
* **J-19 Battery saver.** Profile D (battery saver, restricted standby bucket), screen off for 30 minutes during a playlist. Expect:
  music continues; if the system kills it anyway, reopening restores the song at the right second.
* **J-20 Call during playback.** Simulated incoming call (`adb emu gsm call 5551234`), accept, hang up. Expect: pause on ring, resume
  after hang-up.
* **J-21 The password was changed.** Change the test account's password on the server (`rotate_tester.py`-style: Navidrome's own API, as the
  account), open the app. Expect: within that launch Home shows the card "Sign in again" (no per-row sentence, no cryptic message); tapping
  it asks only for the password (the account is shown); a wrong password says so and stays; the right one returns to Home, the card is gone,
  and the library, playlists, downloads and the queue are still there. "Use a different account" is the only path that removes anything,
  and it says what it removes. Walked on the emulator 2026-10-22 (`evidence/2026-10-22-e23-sign-in-again-card.png`).
