# 26 — Lifecycles and processes (what happens over months and years)

Owner, 2026-10-21: *"dig deep in the project, understand processes, user stories … be curious."* Earlier pages designed features
for day one. This page follows each thing through its whole life (a song, a phone, a person, the server, an import) and the
background processes that keep them alive, and records what reading the code revealed. Findings continue the numbering of `14`
(H38…). New tasks are in `tasks/`.

## 1. What the code showed (2026-10-21 deep read)

| ID | Finding | Evidence | Fix |
|----|---------|----------|-----|
| **H38** S1 | **Sync storm.** While open, the app checks the server every 3 s; whenever the server's scan time moved, it **re-downloads the whole library listing at once**, with no minimum gap. The scan time moves for every song kept during anyone's import (Navidrome's watcher rescans that folder). One full pass for the owner's account = **18 requests, 8.6 MB** (6,731 songs), plus writing every row on the phone. During a friend's 200-song import, an open phone on mobile data can pull hundreds of MB to over a GB per hour | `sync_scheduler.dart` `_probeNow` → `ProbeNeedsFullPass` → `_schedule(Duration.zero)`; `sync_engine.dart` `_libraryDue` compares `lastScanMs`; measured with `fullpass_cost.py`; Navidrome log "Watcher: Scan completed" per kept song | P1-14 (guard now), P2 (`library/changes` cursors make it disappear) |
| — | *Checked and refuted:* the hourly scheduled scan does **not** move the scan time when nothing changed (lastScan 19:19, checked at 20:35) | `getScanStatus` | — |
| **H39** S1 | **A restored queue loses songs that came from YouTube.** The saved queue stores ids; restoring looks them up in the phone's local `Tracks` table, which only learns a fetched song at the next library sync, so the queue comes back empty after a hard kill (E6) | `playback_engine.dart` `_restoreSaved` → `_lookupTracks(ids)` | P1-11 (save what is needed to play the item, not only an id) |
| **H40** S1 | **One stuck load blocks every command.** All player commands run through one first-in-first-out chain (`_run`); a load waiting on a network that is gone has no own time limit, so taps on other songs and Play wait behind it (E1). The retry-once / stop-after-3 logic is right but never reached in time | `_run`, `_onBackendError`, `maxConsecutiveFailures = 3` | P1-08 |
| **H41** S2 | **Imports keep the person's password in the server's memory** to build playlists "as the person" (old ADR-101); a server restart pauses imports until the person's phone polls again | `encore-fetch` imports design | Gone with P2-04 (Encore owns playlists; no password needed) |
| **H42** S2 | **The media service stops when paused** (`androidStopForegroundOnPause: true`), so Android may kill a paused Encore within minutes: a paused tablet is soon unreachable for "control from the phone" | `bootstrap.dart` | P4-07 "available" window and "Always ready to play" (`13` H1) |
| **H43** S1 | **Android developer verification.** From 30 Sep 2026 (Indonesia, Singapore, Thailand) and **worldwide in 2027**, apps on certified phones must come from a **verified developer, wherever they are installed from** (website APKs included). Full account: $25 once + government ID; free "limited distribution" account: **20 devices**; unregistered apps only through an "advanced" install flow or a cable (ADB) | [Google help](https://support.google.com/android-developer-console/answer/16561738?hl=en), [Android Developers Blog 2026-03](https://android-developers.googleblog.com/2026/03/android-developer-verification-rolling-out-to-all-developers.html) | Owner decision D-17; P5-07 |
| **H44** S2 | **Installing an APK is hard for ordinary people**: "Install unknown apps" permission per browser/messenger, Play Protect warnings, different screens per brand | — (the friends' guide never showed it) | P5-07 guide with screenshots per brand; consider Obtainium/F-Droid as channels |
| **H45** S3 | **The fetch service asks for a full scan after each song** although Navidrome 0.64.2's watcher already rescans just the changed folder in 0.2–0.4 s | Navidrome log; `navidrome.py` `startScan` | Keeper relies on the watcher (`22` §7 verified) |
| **H46** S2 | **Settings are lost on reinstall or a new phone** (old B26, "frozen"); downloads must be chosen again on a new phone | old `docs/STATUS` B26 | P3-10 (settings per person on the server; "download the same as on your other phone") |

## 2. The life of a song

```
seen (search/import/recs) → ref → played (stream) → saved (like/playlist/import) → kept (file) → measured (loudness)
   → [fixed: "Wrong song?"] → [upgraded: quality tier] → [merged: duplicate] → nobody saves it any more → removable
   → [file lost: disk failure] → re-fetched (self-healing) / [removed from YouTube] → kept copy is safe; unkept → "unavailable"
```
**New: self-describing, self-healing library (P2-16).** Every kept file carries its identity in its tags: `ENCORE_REF`, the YouTube
video id, ISRC/MBID when known, plus cover and loudness. Consequences: (a) if the database is lost, a scan of the files rebuilds every
ref and its file exactly; (b) if a disk dies and the database is restored from backup, the keeper sees missing files and **re-fetches
every YouTube-sourced song by its video id**, paced (the Host's own rips can't be re-fetched; the admin lists them); (c) moving the music
to a new disk needs no matching.

## 3. The life of a playlist you imported

Imports are snapshots today: Spotify's "Today's Top Hits" or a friend's evolving playlist goes stale the day after.
**New: "Follow the original" (P2-17).** Each imported playlist has a switch (default **on** for public playlists): the server re-reads
the source daily (one small request), adds new songs, removes songs removed at the source unless the person added or reordered them
here (then it asks), and says what changed in a quiet line ("3 new songs from the original"). This is what makes free editorial
playlists possible without a Spotify subscription.

## 4. The life of a phone (device) and 5. The life of a person

Moved to **`32` (accounts, joining and devices)**, where every state and every way in is a table with its status and its test: first sign-in, a new phone, lost or stolen,
uninstalled, the forgotten password (including the Host's own: `encore reset-password <name>`, AC-28), the shared device, leaving. Connecting and signing in again are in `31`.

## 6. The life of the server

| Moment | Designed in |
|--------|-------------|
| Install, setup | `15` |
| Daily rhythm (below) | §7 |
| Update, rollback | `22` §1 |
| YouTube changes | `22` §2 |
| **Disk getting old** (new) | The server reads the disks' health (SMART) weekly and tells the Host in plain words before a disk fails ("The music disk is reporting errors; back up soon") (P3-10) |
| Disk full | `22`, H29 |
| Disk failed | restore the database from backup; self-healing re-fetches YouTube-sourced songs (§2) |
| Move to a new computer | `22` §4 |
| Host retires the server | export for everyone (each person downloads their data), "hand over to another owner" (a second owner can take it over), uninstall |

## 7. The server's day (one schedule, so jobs never pile up on a Raspberry Pi)

| Time | Job | Budget |
|------|-----|--------|
| Always | play, prepare, download (people waiting) | first, never delayed |
| Always, background | import matching, keeping, loudness measuring | yields to the above; paced (`04` §5) |
| 03:00 | database backups | minutes |
| 03:30 | recommendations for everyone | ≤ 2 s CPU per person |
| 04:00 | "Follow the original" playlist checks; new-release checks | one request per playlist/artist, spaced |
| 04:30 | yt-dlp/ytmusicapi/Deno update check + canary | 1 look-up |
| 05:00 | duplicates and "nobody saved" reports; cache trimming | light |
| Sunday 05:30 | disk health check; restore-test of last night's backup (if the Host enabled it) | light |
The Host can move the night window (default 03:00–06:00 local time); a job that cannot finish in the window continues at low priority.

## 8. The phone's processes and their battery budget

| Process | When it runs | Budget |
|---------|-------------|--------|
| Live channel | while the app is open or playing (and "Always ready" devices) | one socket, pings every 25 s |
| Library sync | on start, on `library.changed`, on pull-to-refresh | only changes (P2); never a full re-download unless asked |
| Outbox | after each edit, with back-off | small |
| Playback state reports | pause, seek, track change, every 15 s while playing | tiny |
| Downloads | Wi-Fi by default, foreground notification | user-started |
| Prepare/prefetch | while browsing/searching, next 2 in queue | resolves only; respects Data saver |
| Background check | every ≤ 6 h, network connected, battery not low | one request (`notifications?since`) + the changes cursor |
| Logs, image cache trimming | on start, at most daily | light |
