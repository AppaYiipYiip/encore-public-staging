# 23 — Downloads, audio formats, lyrics and notifications

Why: these four decide how Encore feels day to day on a phone, and each had a hidden problem: downloads go stale when a file is
upgraded or fixed, nothing says which format a phone gets on mobile data, lyrics are fetched by the phone from outside services, and
Encore has no push service, so "notifications" cannot simply arrive.

## 1. Audio formats

| Where | Format | Why |
|-------|--------|-----|
| Kept from YouTube | the original Opus stream remuxed into Ogg (`.opus`, ~130–160 kbps), **never re-encoded**, ReplayGain tags added (P1-13) | best available from that source, no quality loss |
| The Host's own files | untouched (FLAC, MP3, AAC, …) | read-only |
| Quality tier (P4-04) | FLAC from Lidarr/Soulseek | lossless |
| **Streaming at home on Wi-Fi** | the original file | the LAN is fast |
| **Streaming on mobile data / away from home** | **the person picks, as in Spotify** (Settings > Playback > streaming quality per network: Original, High Opus 160, Normal Opus 96, Data saver Opus 48); the Host may cap it for away from home in the admin (`design/00` W-07), and only then does the app say so (the capabilities rule, ADR-R42 point 8) | the Host's upload and the listener's data plan |
| **Data saver** | Opus 48 kbps (what the app defines in `audio_quality.dart`) | one switch (U13) |
| **Downloads to the phone** | setting: Normal = **Opus 96** (default, ~0.7 MB/min; what the app defines in `audio_quality.dart`), High = Opus 160, Original | phone storage |
Gapless: Opus and FLAC files carry the encoder delay/padding; the player uses it (test with a live album in P4-12).

## 2. Downloads

* **What can be downloaded:** anything, owned or not. Downloading a song the server does not keep yet **asks the server to keep it
  first** (D-3) with priority above imports (`04` §10 gains a `download` priority between `prepare` and `match`), then the phone copies
  it from the server. At home, if the server's copy is not ready yet, the phone may fetch the stream directly at full line speed with an
  address the server resolved (proved from a PC, X-5) and the server keeps its own copy in the background.
* **The download manifest:** `GET downloads/manifest?since=` lists, per downloaded ref, the file the phone should have (id, format,
  size, sha256). When a ref's preferred file changes (quality upgrade, a "Wrong song?" fix, a re-tag), the manifest changes, the old
  download stays playable and is **replaced on the next Wi-Fi** (fixes stale downloads, hidden risk H37).
* **Writing safely:** temporary file → size and checksum check → rename; interrupted downloads resume with Range (H19); low space stops
  new downloads with a message (H20).
* **Covers and lyrics are part of a download** (P1-10, §3), never evicted while the song is downloaded.
* **Smart downloads:** "Download" on Liked Songs or any playlist keeps it in sync (new songs download on Wi-Fi, removed ones are deleted)
  (U8). Storage limit setting; "Remove all downloads".

## 3. Lyrics

* The **server** finds lyrics once per song ref and caches them for everyone: (1) embedded tags and `.lrc` next to the file,
  (2) LRCLIB by artist/title/album/duration, (3) none ("No lyrics for this song", quietly). The phone stops calling LRCLIB directly.
* Synced lyrics full screen (R-02) with tap-to-seek; right-to-left lyrics render right-to-left; a per-person timing offset (±) when
  a version's intro differs; lyrics travel with downloads.

## 4. Notifications without a push service

> **Amended 2026-10-24 (`11` ADR-R44, owner: "we all hate those"):** the table and the channel list below describe what *can* arrive. By default **nothing is posted to the phone**: news (a new release, an invitation used, an import finished) goes to the in-app bell (What's new); Settings > Notifications offers at most two opt-in phone categories, both off; the permission is asked only when one is switched on.

Encore has no Google push (no central service, by design), so delivery depends on whether the app is running:

| Situation | How it arrives | Delay |
|-----------|----------------|-------|
| App open or playing (media service alive) | live channel event → local notification | immediate |
| App in the background, not playing | periodic background check (`GET notifications?since=`) | ≤ 6 h (battery budget, `00` R-12) |
| Jam invitation to someone not online | they see it next time they open Encore; the inviter sees "Nina isn't online right now — she'll see it when she opens Encore" | honest |
| Later, optional | self-hosted UnifiedPush through the Host's server (P6) | immediate without Google |

Channels (each switchable in Settings → Notifications): Playback (required by Android), Downloads, Imports, Friends & Jams, New
releases (one daily digest, never one per song), Server (owners only: "needs you" items, `22` §5). Permission is asked the first time a
channel would notify (P1-12).
