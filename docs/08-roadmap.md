# 08 — Roadmap

Phases run in this order. Inside a phase, tasks without dependencies can run in parallel (one agent each). A phase ends only when
its exit criteria are met **with evidence** (`07` §11). Task details: [`tasks/`](tasks/).

Owner (2026-10-21): **everything goes into the first version**, even if the release waits months. So the full feature set (P4)
comes before the public release (P5); the core (P1–P3) comes first so those features stand on the new design.

| Phase | Goal in one line | Why at this point |
|-------|------------------|-------------------|
| **P0 Reset** | A clean, safe, honest repository and process | Everything later lands in it; secrets and the old project's leftovers leave before anything is pushed again |
| **P1 Instant play, stop the worst bugs** | A song you don't own plays in ~2–3 s; the player never gets stuck; offline and covers work | The core promise is broken today (38 s); the fixes are reusable in the new design |
| **P2 Songs as references (the new library)** | Like/playlist/import/resume any song, owned or not; imports in seconds; one device at a time | Removes the root cause of the spaghetti (C3); delivers resume-anywhere and single-device playback |
| **P3 One server, one-command install** | One Encore server program, one port, device logins, published images, installer + browser wizard | Makes Encore installable by strangers and maintainable by agents |
| **P4 Full feature set** | Recommendations per person, Jam (also across servers), friends on other servers, your devices with remote volume, one account per person with servers talking to each other, quality tier, Year in Music, Spotify-class extras | Owner: everything in the first version |
| **P5 Public release** | Signed APK with updates, full device matrix, field test, going public (website and name when the owner wants) | The first public version |
| **P6 Later** | iOS, web/desktop client, devices remote control, localisation, "Encore OS" image | After the first public version |

## P0 — Reset (no product changes)

Tasks: P0-01 secrets out of git · P0-02 homelab out · P0-03 workspace clutter · P0-04 the new repository (clean tree, new layout,
nothing of the old project) · P0-05 rename, re-icon, licence · P0-06 CI for app and server · P0-07 GitHub set-up · P0-08 agent files ·
P0-09 environments as code · P0-10 licence inventory and checks.
**Exit:** the new repo `encore` on GitHub with `main` protected, CI green on the moved code, no secret or binary in history
(`gitleaks` clean), no trace of the old project's name in the repository, the old repo renamed `old-repo` and archived.

## P1 — Instant play, stop the worst bugs

Tasks: P1-01 lean resolver · P1-02 stream first, limits only for keeping, fault flags · P1-03 two pools + YouTube pacing/back-off ·
P1-04 prepare (top result, page, queue) · P1-05 imported songs use their known video id · P1-06 measurement spans + harness ·
P1-07 search: Top result and one list · P1-08 the player never gets stuck · P1-09 offline without skipping (one calm strip, no permanent banner) ·
P1-10 covers everywhere, offline too · P1-11 resume after a hard kill; media-session position · P1-12 accessibility, insets, big
text, device-profile tests, small UX fixes · P1-13 one volume, consistent loudness · P1-14 stop the sync storm.
**Exit:** journeys J-02, J-03 (owned part), J-06, J-07, J-08, J-10, J-11 pass on profiles A and B on TYPICAL; J-02 also on SLOW
within the hard limits; no S1 open in the player, search, offline or covers.

## P2 — Songs as references (the new library)

Tasks: P2-01 Encore server skeleton + song refs + library API · P2-02 the app's data layer on song refs · P2-03 play ≠ save,
keep-on-save and keep-on-repeat, albums/playlists play through catalogue songs · P2-04 imports in seconds · P2-05 import stop,
progress, consistent counts · P2-06 Spotify beyond 100 songs · P2-07 remove homelab portal code and the second import screen ·
P2-08 playback state and resume anywhere · P2-09 one device at a time · P2-10 invite-first sign-in and "Bring your music" ·
P2-11 migrate today's installs · P2-12 catalogue: search, matching, duplicates · P2-13 downloads, formats, manifest ·
P2-14 lyrics on the server · P2-15 notifications without push · P2-16 self-describing, self-healing library ·
P2-17 "Follow the original" playlists · P2-18 a changed or expired login is a normal event · P2-19 find your server (a key, the server's own addresses, a first screen without an IP address) · P2-20 Encore mode: the app holds only the device token. Design: `17`, `18`, `19`, `23`, `26`.
**Exit:** J-01, J-03, J-04, J-05, J-09, J-12 pass; a like on a catalogue song survives the song being kept, re-tagged and moved
(integration test); migration from an existing install keeps every like and playlist (test on a copy of CT 104's database).

## P3 — One server, one-command install

Tasks: P3-01 people, sources, keeper, admin moved into the Encore server; the gateway as the only door · P3-02 published multi-arch
images · P3-03 device tokens, the gateway signs requests to Navidrome, one-way mirror · P3-04 remove Docker-socket control, Firefox,
Google sign-in · P3-05 install script, `encore.local`, `encore` CLI · P3-06 setup wizard and admin pages · P3-07 clean-machine proof ·
P3-08 updates with rollback, yt-dlp freshness, backups, moving computers · P3-09 security and privacy as written ·
P3-10 devices, settings and the Host's safety nets · P3-11 the Tinkerer's door · P3-12 the first outside user. Design: `15`, `21`, `22`, `26`.
**Exit:** J-14 passes on a fresh Ubuntu 26.04 VM (x86) and on an ARM64 machine or VM, in ≤ 15 min; one published port; the admin
Health page explains every state in plain words.
**Order (D-53, owner 2026-11-03): P3-06, the browser setup wizard and admin pages (PC-only), comes after Jam (P4-02).** The first friends use the terminal installer and the app.

## P4 — Full feature set

Tasks: P4-01 listening profile and recommendations per person · P4-02 Jam on the live channel · P4-03 friend activity ·
P4-04 quality tier on song refs · P4-05 Year in Music from the server's play history · P4-06 the whole app walked again ·
P4-07 Encore Connect (devices, handover, remote volume) · P4-08 home-server relay (the app only talks to its own server) ·
P4-09 connecting with people on other servers (federation core) · P4-10 Jam across servers, sharing, collaborative playlists · P4-11 tablets and large screens (parked, D-18) ·
P4-12 Spotify-class extras · P4-13 problem reports and battery-saver guidance · P4-14 "Wrong song?" and metadata fixes · P4-15 Browse, history and playlist details · P4-16 profiles on a shared device · P4-17 compare tastes (US-65, opt-in).
Design: `13`, `14`, `16`, `19`, `20`.
**Order (D-53, owner 2026-11-03): Jam (P4-02) goes first within this phase and ahead of P3-06.** It needs the device model (P2-08, P2-09) and the friend milestone (P3-12) before it.
**Decided (advisor, 2026-11-01, reversible, D-48 a): D-18 holds everywhere.** Tablet-specific layouts are parked: P4-11 stays in `tasks/P4-full-feature-set.md` marked parked and is listed in `tasks/P6-later.md`; `03`, `03a` US-75, `14` U1 and ADR-R42 point 5 say so. The phone layout scales on a large screen (Android 16 shows it stretched anyway, `14` U1) until a tablet layout is asked for.
**Exit:** US-60 … US-64 and US-70 … US-76 pass as journeys (incl. J-15 … J-20 of `14` section 3) on profiles A and B with two people on two emulators; recommendations judged by the owner
on his own account after a week of listening ("does Home know me?"); the quality tier upgrades a kept song on the dev VM without
moving any like, playlist entry or resume position.

## P5 — Public release

Tasks: P5-01 release signing key and CI signing · P5-02 in-app update check · P5-03 full device matrix + 5-day field test (owner +
one friend) · P5-04 cold start ≤ 0.7 s mid-range · P5-05 website, name, legal texts (**when the owner wants**; not now) ·
P5-06 go public (repo, images, first release) · P5-07 Android developer verification and the install guide (parked, D-17) · P5-08 what's new and in-app help.
**Exit:** every promise N1–N11 (`03` §4) measured on SLOW and TYPICAL and on two real phones; the owner does not open Spotify for
5 days.

## P6 — Later

iOS · web/desktop client (the API is ready from P2) · casting to Chromecast/TV speakers · localisation (French, Arabic first) ·
flashable "Encore OS" image (if Hosts struggle to install Linux).

## Rough size and parallelism

| Phase | Parallel lanes | Rough effort |
|-------|----------------|--------------|
| P0 | 2 (repo/GitHub; CI) | 1–2 days |
| P1 | 3 (server resolver P1-01..05; player/offline P1-08..11; UI/search/a11y P1-07, P1-12) | 4–6 days |
| P2 | 2 (server P2-01, P2-04, P2-08/09; app P2-02, P2-03, P2-10) | 8–12 days |
| P3 | 2 (server consolidation; install/wizard) | 6–8 days |
| P4 | 4 (recommendations + extras; devices + accounts; federation + Jam + friends; quality tier + Year in Music; tablet parked) | 25–35 days |
| P5 | 2 | 4–6 days + 5-day field test |
