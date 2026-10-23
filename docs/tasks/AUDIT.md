# Audit — what is not finished, or only partly (kept honest)

Owner, 2026-10-22: *"I would expect you double-checking everything after being done. If something was only partially implemented, go back
and fix it, and also try things from beginning to end, like a new user: fresh install of the server and of the Android app, import
playlists and use the app, invite friends, Jam, Jam with someone outside the server. Test every single feature from the UI."*

This page lists, task by task, everything a status line says is open, and the owner's findings of 2026-10-22 with where each stands.
Update it whenever a status changes; nothing is "done" while it is listed here. The journeys at the end are the final proof.

## Owner's findings, 2026-10-22

| # | Finding | State |
|---|---------|-------|
| F1 | A tap plays only a 30-second snippet (0:29 track) | **Fixed** (`7099a8e`): one failed look for the instant-play service was remembered for the session, so every tap fell back to the Deezer preview. Now a service found once is assumed to be there, a service never found is looked for again, the look waits longer. **Re-walked on the new server (builds 103-107):** a catalogue song never seen before streams in full (0:22 of 5:42) 2.8 s after the tap, a kept one in about a second; there is no 30-second fallback on that path. |
| F2 | An imported playlist shows letters ("OD"), not a picture | **Fixed on an Encore server:** the server gives the playlist its source's picture at once, the app shows a picture address as a picture, and a playlist without one gets a collage of its songs' covers (the cover finder fills songs that have none). Walked on the emulator. Still open for the legacy import page (goes away with P2-07). |
| F3 | No download button on an imported playlist page | **Fixed on an Encore server:** an import (paste or share) opens the ordinary playlist page, with the ordinary play and download buttons; the download of the 10-song import finished in 4 s. A download that cannot move now says "Waiting for Wi-Fi" (it said "Downloading 0 of 10" for ever when Wi-Fi only was on and the phone on mobile data; found by walking), and turning Wi-Fi only off starts it. |
| F4 | "Downloaded" shows one heap of songs, not playlists; same offline | **Fixed** (`5399414`): Library > Downloaded lists the playlists/albums/Liked Songs that were downloaded with their progress; offline the Library opens there. Walked on the emulator (build 101). |
| F5 | "Only my music" should be the default; "Show everything" makes no sense | **Fixed** (`5399414`): scope is mine / everything, default mine, wording "Show the whole server". |
| F6 | Offline shows every download, mine or not; shared tablets and TVs need switching users on a trusted device | **Built, first slice (build 108):** Who's listening? lists the people who signed in on the device, picking one needs no password and nothing of the others is touched, Add someone (sign in or invitation), Remove from this device, sign-out with others present returns to the picker (schema v7 stamps the profile used last). Walked on the emulator: a second person signed in on the same device, each has their own Home/library; switching is instant. Downloads are per profile (their folder is the profile's id). Still open from P4-16: the optional "ask who is listening when the app opens" switch for tablets/TVs, a PIN per profile, Guest, D-pad focus on a TV, two-profile offline walk with real downloads, stopping or handing over the player when switching. |
| F7 | Test with two phones: an import on one must appear on the other (same account) | **Proved on two real emulators signed in as one account (build 113, 2026-10-22; `evidence/b01-live-channel-two-phones.md`):** a playlist made, and a song liked, on one phone showed on the other **2.4-2.6 s after the tap** (an upper bound: reading the screen costs about a second), four times in a row, and again after the server was restarted (the phones reconnected by themselves). The app now keeps a live connection to the server instead of asking every 3 s (the check that remains is a 60 s safety net). Before: 3 s checks, worst case 7.4 s. Still open: an import and a resume on one phone appearing on the other (journey 4 in full). |
| F8 | Test like a new user, end to end, everything | Open: the journeys at the end of this page, to be run when P3/P4 are in; each earlier slice is walked on the emulator as it lands. |
| F9 | A random song by a random artist played quickly (liked). Lyrics did not show | **Not a bug in the app, a gap in the source.** The lyrics service (LRCLIB) has no entry for that song (Alonzo "DLG": a search finds nothing); for Gojira "Silvera" the same app shows synced lyrics, walked 2026-10-22. The empty screen says "We looked on your server and online". The fix is wider sources: P2-14 and `../29-spotify-gap-review.md` |
| F10 | "Can we change this screen?" (the volume and devices dialog from the player's Devices button) | That dialog is **Android's own output switcher**; an app cannot restyle it. Encore's own Devices sheet (this phone, other devices, a volume each) is P4-07; the system switcher stays one tap away for Bluetooth |
| F11 | An artist (Gojira) shows songs and albums together; wants a Popular songs section and a section for albums and EPs, "Spotify does this much better, and other things too" | **Built (build 112):** Popular (5, then "Show more"), Albums, Singles and EPs, Compilations, on the page of every artist; the old "More from" mix and the "not in your library" line are gone; an album the person owns that the catalogue does not list stays on the page. Tests: 8 new or changed. **Walked on the emulator (build 112, Gojira):** Popular with "Show more", Albums with Magma marked as in the library, Singles and EPs as their own section. The wider comparison is `../29-spotify-gap-review.md` |

## P0 — reset

* **GitHub is set up (2026-10-22):** the old repository was renamed, the new private `encore` exists, `main` and four pull requests (#1 to #4) are merged, and the
  five CI workflows exist (each filters by the paths a push touches; the latest run of each succeeded, 2026-10-23). **Still open from P0-07:** branch protection on `main` (checked 2026-10-23: not protected),
  the project board, one issue per task.
* P0-09 environments as code, P0-10 licence checks: not done.
* Before the repository goes public (P5-06): several plan documents still name the owner's own machines and containers; scrub them (see `../README.md`).
* Android build tooling warns that Gradle 8.14, AGP 8.11 and Kotlin 2.2.20 "will soon be dropped" by Flutter: upgrade before the first release.

## P1 — instant play and the worst bugs

* P1-03: random 5-20 s spacing of background look-ups, the doubling rest up to 24 h on the **legacy** server (the new server has it: `sources/youtube/rest.py`),
  "interactive at most one look-up per 5 s while resting", the comparison with an import running (J-02).
* P1-04: preparing the first 3 songs of an opened album/playlist and the next 2 of the queue, cancelling stale prepares, dropping prepares first under back-off.
* P1-06: the app's `play.audible` span (the server side logs are there).
* P1-07: keystroke-to-results timing; the miss of Oum Kalthoum's Arabic title. **Fixed 2026-10-22 (build 114): "Beach House Space Song"** - the catalogue's text
  search never lists Beach House's own song (not in its first 11 results), only covers and look-alike titles; when none of the results is a song by an
  artist named at one end of what was typed, the app now looks the artist up, searches its popular songs for the title and puts the hit first
  (`artist_aware_search.dart`, 14 tests, walked: Top result is now "Space Song, Beach House"; "Gojira Silvera" and "Radiohead House of Cards" unchanged).
* P1-10: covers of catalogue and imported songs, notification art.
* P1-12: system-bar steps 2, 3, 5, 6, 7 and right-to-left layouts.
* P1-13: loudness tags written by the server (the app side is done).
* A 30-second `bufferForPlaybackMs` tuning (X-6) and a walk of a real two-hour stream on the emulator.

## P2 — songs as references

* P2-01 server core: **done and proved** (refs, library, playback state, live channel, scheduler, keeper, scanner, imports, people, migration, gateway,
  the YouTube rest). Open: the OpenAPI file with contract tests, the catalogue/search endpoint (P2-12), saving an album keeps its songs, the keeper
  sharing bytes with a playing stream, the `/encore` route in the Funnel `serve.json` and at home, the wizard making the administrator (today an
  environment variable), `POST /refs/{id}/keep` for downloads of songs the server does not keep yet.
* P2-02 app data layer: schema v6, the API client, the two feeds, local-first edits and delivery, the move of an existing install, session Encore
  mode: **done, with 1,720+ tests, walked on the emulators** (fresh install to library in ~8 s). **Done 2026-10-22: the live channel in the app** (`encore_live.dart`, `encore_device.dart`; 18 tests). Open: the sign-in and join screens for an Encore
  server (invitation link/QR, the capability learned at "Test & continue"), a Home banner for the move (`session.upgrade`), Year in Music from the
  server's plays, covers from a playlist's picture URL, deleting the legacy `PlaylistMutations`/Subsonic paths once no server needs them, the walk on
  the emulator against the dev VM.
* **Done since:** P2-03 app part (a catalogue tap resolves to a ref and streams from the server, nothing is saved by playing: `EncoreInstantBackend`),
  P2-04 app part (the Import music page on an Encore server creates the import on the server's API and opens the ordinary playlist page; a list can be
  liked instead of made a playlist; Stop), people and invitations on an Encore server (owner makes a link and QR, a friend joins from a fresh install on
  a second emulator, owner sees people and invitations: journey 3 passed), pictures for songs without one (server cover finder + `cover.jpg` in the album
  folder + the keeper), a person whose music-server account had no library is healed (their songs answered "data not found").
* **Found by walking, now fixed (2026-10-22, build 111):**
  * The music server answers a blank record for an album without art and marks it `no-store`; the phone cached it for a year. The cover cache now refuses
    such an answer (`d69993d`), so the screen shows its own fallback and a later picture is fetched.
  * The `/encore/join/<code>` link is an Android app link (https, and http for a home network; no other http link is offered to Encore). Walking it found
    "Page Not Found" over the app (Flutter also routed the address itself): that is switched off in the manifest and guarded by a test. Walked on the emulator:
    Android offers Encore for the link and the app opens on its own screen; on a phone that already has an account on that server it says so.
    **Walked on a fresh install (second emulator):** tapped the link, "newtester invited you", chose a name and password, landed on Home with a
    library of its own, searched, and streamed a full 5:12 song. Found on the way: right after the emulator booted the join screen said
    "Can't reach ..." once (no network yet) and worked on "Try again"; **fixed 2026-10-23**: the look at the invitation is tried again by itself
    (after 2, 4 and 8 s, "Reaching the server...") before the failure screen; making the account is never retried by itself (3 tests).
  * The Your server page on an Encore server no longer speaks of a helper service: it says songs are fetched as they play, that playing does not save, shows
    "Taking a short rest" with the time left when the web asked the server to slow down, and hides the old "What does my server need?" block. The lyrics text no
    longer names LRCLIB or the music server. Walked on the emulator (9 tests).
  * The invite dialog already offers "A guest" / "Another owner" on an Encore server (the old role words only appear for the old service).
* **P1-03 on the new server:** background look-ups and downloads at YouTube are paced (a random ~12 s apart, a person's tap is not) and share one queue; deployed
  to the dev VM, unit-tested, not yet watched under a real import (the home address was refused earlier on 2026-10-22; the rest has since cleared).
* P2-03 .. P2-17: mostly not started (play is not save: done above; imports in the app: done above; import stop, Spotify beyond 100 songs, removing the portal code and the second
  import screen, playback state and resume anywhere in the app, one device at a time, invite-first sign-in, migrating today's installs on the server
  (the endpoint is built), catalogue module, downloads formats, lyrics on the server, notifications, a self-healing library, "follow the original").
* P2-18: server part belongs to P3-03.
* **Debts against the thin-client rule (ADR-R38, checked in the code 2026-10-23).** The audio path is server-side and web-ready. The phone still calls outside services itself:
  Deezer for search, artist and album pages, 30-second previews (the phone plays Deezer's file) and the background new-release alerts; LRCLIB for lyrics; outside picture
  addresses for some covers. A web client could not do these. They go away with P2-12 and P2-14 (and the covers served by the server); the table is in `../11` ADR-R38.
  **Enforced since 2026-10-23** for addresses written into the source: the outside-host ratchet in `app/test/architecture_test.dart` (baseline: the Deezer and LRCLIB clients, goal zero; `../30` §5;
  shown to fail on a new outside `baseUrl`). Not enforced for an address that arrives in data (a cover URL inside a record).

* **Found 2026-10-23, security S2 (ADR-R40, P2-19 slice A):** the app's address probe is a Subsonic `ping` that carries the person's login token, sent to every candidate address, requests use the first candidate before any probe, and "reachable but rejecting the login" counts as "this is the server". On a network that has the same address as the person's home server (a café, a work Wi-Fi) the token (md5 of password and salt, guessable offline) goes to whatever answers there. Low for the first friend (one https address); real for a phone that has a home address and roams. Fix: servers get a key as identity and credentials go only to an address that proved it (slice A).
* **Found 2026-10-23, the first screen asks for an IP address** (P2-19, `15` A1); the installer's QR is the bare address; the app has no QR scanner. Decided in ADR-R40 (the owner's question of the same day): a key as identity, the server's own address list, a link or QR first, "Servers on this Wi-Fi" by mDNS second, a typed address last. Slices A and B before P1-06, slice C when the owner's phone exists.

## P3 — one server and the install

**Built and proved (2026-10-22): the installer, first slice (P3-05, PR #1).** One command on a clean Ubuntu 26.04 VM: 5.5 to 6 minutes, a re-run 4 s, every
`encore` verb used, the music folder byte for byte untouched; a second person joined by link; `docs/evidence/c01-installer-clean-vm.md`. The image is private
and published by CI. **The first outside user (P3-12):** the friend's server is the owner's own, decided in ADR-R34; an in-app "Report a problem" was built, walked on an
emulator and then **put on hold** by the owner (the friend messages him; branch `parked/in-app-report`, ADR-R35, idea kept in P4-13).
**Built and proved (2026-10-23): backups (P3-12 item 2, PR #2).** `encore backup`, `encore restore`, a nightly timer the installer switches on, a backup before every
`encore update`; proved on real machines including a restore on a new computer with a different install-time password (`docs/evidence/c02-backup-restore.md`, ADR-R37).
Also: `encore funnel` hardened (free port, own address reused, never resets what is not Encore's; control flow run against a stand-in Tailscale, not yet a real one), the
server counts its YouTube look-ups per day in the log, the join screen retries the look at an invitation by itself, the installer logs the time of each phase.
**Built and proved (2026-10-23, later): the installer survives real installs (PR #4, `docs/evidence/c03-interrupted-install.md`).** A closed terminal does not stop it; an install cut short is finished by running it again (a marker before the settings file, removed after the owner's account; a different password the second time is refused in words); the music server's download has its own line with true sizes (238 MB and 94 MB); the music server's "too many sign-ins" (429) is waited out instead of reported as a refused account. The guide ran as written from `main` on a clean machine: 15 min 11 s on a line capped at 10 Mbit by the owner's dashboard (5 min 30 s uncapped), owner signs in, nightly backup on. **VM 107 `encore-home` (192.168.50.134) is reset clean for the owner's own install.**

Also from P2: the gateway, the accounts module (invites, join, reset, lock, rate limits), device tokens, the music-server administrator client.
**Open:** `encore funnel on` proven with a real Tailscale sign-in (the owner's), the friend's guide as a finished page (P3-12 item 4; a draft exists), the browser wizard
and admin pages, `encore.local`, device-token gateway signing (X-2), updates with rollback, arm64, the reuse-what-you-have install path, security/privacy tests per
cell of the matrix, devices and the Host's safety nets, the Tinkerer's door.
**Found 2026-10-23 (yt-dlp freshness, P3-08):** the server image installs the newest yt-dlp when it is built (`pip install ".[youtube]"`), and CI builds it only when server code
changes on `main` or by hand; the running server has no updater. When YouTube changes, songs the server does not have stop playing
until a new image is built and `encore update` is run on that server (nothing pulls it by itself; no updater was found in the server's code or scripts).
**First step done (2026-10-23, PR `task/P3-08a-weekly-image-rebuild`):** `server-image.yml` rebuilds from scratch every Monday 04:17 UTC and on request (`gh workflow run server-image.yml -f fresh=true`),
and every build writes the yt-dlp version it carries into the run page. Why from scratch: the layer cache reused the `pip install` step (the log showed `CACHED`, image carried
2026.10.21), the fresh build downloaded it again (not cached; same 2026.10.21, which was PyPI's newest that day). It only makes a newer yt-dlp *available*: a server gets it when
`encore update` is run on it. The scheduled build has no canary, so a bad yt-dlp release would also be inside `:main` (every build keeps its own `:sha-<commit>` tag to go back to).
**Second step built and run for real (2026-10-23, PR #9, `../evidence/c04-ytdlp-self-update.md`, ADR-R39):** the server checks PyPI daily, takes a release older than 24 hours, tests it on the song path in a child process and, on a pass,
switches to it at its next start, which it makes itself once nothing has gone through it for a minute (never forced, once per version). Seen on the dev VM: yt-dlp 2026.8.19 became 2026.10.21 by itself, 19.6 minutes after start, with 1 canary look-up
(4 extractions in all, including the diagnosis of a bad first choice of check video). Not seen: days, a never-quiet server, `degraded` against the real YouTube, VM 107 (it gets this with the next `encore update`, which the owner is told about first).

## P4 — full feature set

Not started: recommendations, Jam on the live channel, friend activity, the quality tier on refs, Year in Music from the server, walking the whole
app, Encore Connect (devices, handover, remote volume), the home-server relay, federation, Jam across servers, tablets and large screens,
Spotify-class extras, "wrong song?", browse and history. **Profiles for shared devices (F6): first slice built, see the table.**

## P5 — public release

Not started. GitHub, the signing key (plan agreed in `../12`), licences, the website (not now).

## The journeys that close the first version (owner's instruction)

Each is run from the UI on fresh machines, written up in `../evidence/`, and every defect is fixed before the next:

1. Fresh install of the server on a clean VM with the one command, the wizard, the owner's account, the first invitation.
2. Fresh install of the app on a clean emulator: sign in, import a Spotify and a YouTube Music playlist (a long one too), watch it appear at once with
   its picture, play, download a playlist, go offline, come back.
3. A friend joins by invitation on a second emulator; both use the same server; likes and playlists stay separate.
4. The same account on two emulators: an import, a like, a playlist edit and a resume on one appear on the other within seconds. **Walked 2026-10-23 (`../evidence/b02-journey4-two-phones.md`): import 3.3 s, like 2.2 s, rename 2.5 s (upper bounds); passed. Resume is not offered on the other phone: the app never calls the server's `/playback` (P2-08, P2-09 are open app work).**
5. A Jam on one server (host and guest), a catalogue song in the Jam, leave and rejoin, the host hands over.
6. A Jam with a person on another server (federation), and a guest seat for somebody with no server.
7. A shared tablet: two profiles, switch without signing out, separate downloads.
8. Updates and rollback, a backup and a restore, moving to another computer.
