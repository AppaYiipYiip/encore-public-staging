# 27 — Story map: everything each person does, and what is still missing

A story map lays out, left to right, the big activities of a person, and under each the steps they take. Marking each step as
designed (✓ with its story/task), partly designed (◐) or missing (✗) shows the holes at a glance. Missing steps found here became
tasks (marked **new**).

## 1. The Listener

| Get started | Find music | Listen | Save and organise | Share and together | Look after myself |
|-------------|------------|--------|-------------------|--------------------|-------------------|
| ✓ Install the APK (P5-07 guide) | ✓ Search anything (US-10, P1-07, P2-12) | ✓ Play/pause/seek/skip (P1-08) | ✓ Like anything (US-20) | ✓ Invite a friend to my server (US-03) | ✓ Devices list, revoke (P3-10) |
| ✓ Join by invite or QR (US-04) | ✓ Artist, album pages (U4) | ✓ Queue, play next, reorder | ✓ Playlists of any song (P2-01) | ✓ Friends on other servers (US-72) | ✓ Change my password (people module; **ensure an app screen**, P3-09) |
| ✓ Bring my music (US-05) | ✓ Home made for me (US-60) | ✓ Shuffle, repeat, smart shuffle (P4-01) | ✓ Save albums, follow artists (U3) | ✓ Jam with anyone (US-73) | ✓ Settings follow me (P3-10) |
| ✓ Pick some artists (A5) | ✓ Radio from any song/artist (P4-01) | ✓ Lyrics full screen (P2-14) | ◐ Organise: sort, filter, pins, folders, cover (U7, P4-12) — **descriptions missing → added to P4-15** | ✓ Share a song/playlist (U5) | ✓ Privacy switches (US-41, `21`) |
| ✓ First Home not empty (US-04) | ✗→**new** Browse: charts of my country, moods/genres, editorial playlists (P4-15) | ✓ Gapless; crossfade designed (U9), not built (audit B-8) | ✓ Downloads, smart downloads (P2-13) | ✓ Collaborative playlists (U6) | ✓ Explicit filter (`21` §5) |
| | ✓ New releases from artists I love (P4-01) | ✓ Sleep timer, speed, equaliser (exist) | ✗→**new** Recently played: a full history screen (P4-15) | ✓ Friend activity (US-62) | ✓ Export / delete my data (`21` §6) |
| | ✓ "Wrong song?" (P4-14) | ✓ One volume, even loudness (US-76) | ✓ Year in Music (US-64) | | ✓ Report a problem (P4-13) |
| | | ✓ Lock screen, notification, headset, calls (US-15, H13, H14) | | | ✗→**new** What's new after an update, in-app help (P5-08) |
| | | ✓ Car / Android Auto (U10) | | | ✓ Update the app (P5-02) |
| | | ✓ Control my other devices (US-70/71) | | | |
| | | ✓ Resume anywhere, one device at a time (US-12/13) | | | |
| | | ✓ Offline, data saver (US-14, U13) | | | |

## 2. The Host

| Install | Bring people | Run it | Care for the library | Share beyond the house | Change or leave |
|---------|-------------|--------|----------------------|------------------------|-----------------|
| ✓ One command (`15` §1) | ✓ Invite, QR (US-03) | ✓ Health page (US-51) | ✓ Music folders, scan (`15` §4) | ✓ Away from home (US-02) | ✓ Move to a new computer (`22` §4) |
| ✓ Wizard (`15` §2) | ✓ Roles, reset, lock, remove (US-40) | ✓ Updates with rollback (`22` §1) | ✓ Duplicates, nobody-saved cleanup (`19` §6) | ✓ Other servers on/off (D-13) | ✓ Second owner, hand over (P3-10) |
| ✓ Pair my phone (`15` page 8) | ✓ Storage per person (U14) — ✗→**new** a per-person storage cap and what happens when it is reached (P3-09) | ✓ YouTube freshness (`22` §2) | ✓ Fix wrong songs and metadata (P4-14) | ✓ Allow copies to other servers (D-16) | ✓ Retire: everyone exports (`26` §6) |
| | | ✓ Backups and restore (`22` §3) | ✓ Best quality (P4-04) | | ✓ Locked out: CLI reset (P3-10) |
| | | ✓ Disk health (P3-10) | ✓ Self-healing after disk loss (P2-16) | | |
| | | ✓ Problems from phones (P4-13) | | | |

## 3. The Tinkerer

| Install their way | Use their tools | Customise |
|-------------------|-----------------|-----------|
| ✗→**new** Attach Encore to an **existing Navidrome** instead of installing one (P3-11) | ✓ Other Subsonic apps see mirrored playlists (P3-03) | ✗→**new** Own domain + reverse proxy (Caddy/Traefik/nginx) behind the gateway, documented (P3-11) |
| ✗→**new** Install with plain Docker Compose, no script (P3-11) | ◐ Navidrome's own web UI through the gateway (`21` §3) | ✓ Advanced settings: pace, speed limits, cookies file (`15` §4) |
| | ✗→**new** A documented API for their own scripts (the OpenAPI file of `17`, published) (P3-11) | |

## 4. What the map changed

* New tasks: **P4-15** (Browse with charts, moods and editorial playlists; a Recently played screen; playlist descriptions),
  **P3-11** (the Tinkerer's door: existing Navidrome, plain Compose, own reverse proxy and domain, published API), **P5-08**
  (what's new and in-app help), and a storage cap inside **P3-09**.
* Every ✓ links to a story or task, so a missing link is visible in review: the planning agent re-checks this map at the end of each phase.
