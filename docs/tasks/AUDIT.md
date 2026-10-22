# Audit — what is not finished, or only partly (kept honest)

Owner, 2026-10-22: *"I would expect you double-checking everything after being done. If something was only partially implemented, go back
and fix it, and also try things from beginning to end, like a new user: fresh install of the server and of the Android app, import
playlists and use the app, invite friends, Jam, Jam with someone outside the server. Test every single feature from the UI."*

This page lists, task by task, everything a status line says is open, and the owner's findings of 2026-10-22 with where each stands.
Update it whenever a status changes; nothing is "done" while it is listed here. The journeys at the end are the final proof.

## Owner's findings, 2026-10-22

| # | Finding | State |
|---|---------|-------|
| F1 | A tap plays only a 30-second snippet (0:29 track) | **Fixed** (`7099a8e`): one failed look for the instant-play service was remembered for the session, so every tap fell back to the Deezer preview. Now a service found once is assumed to be there, a service never found is looked for again, the look waits longer. Not yet re-walked on the emulator with a busy server. |
| F2 | An imported playlist shows letters ("OD"), not a picture | Server side **done** (`d217de0`: the playlist gets its source's picture at once). App side open: it needs P2-04 (import through the new API) so the picture is shown from the first second. |
| F3 | No download button on an imported playlist page | Open. The import page is the special page of ADR-102, which P2-04/P2-07 remove; an import becomes a normal playlist page with the normal download button. Until then: add the button to the import page if P2-04 slips. |
| F4 | "Downloaded" shows one heap of songs, not playlists; same offline | **Fixed** (`5399414`): Library > Downloaded lists the playlists/albums/Liked Songs that were downloaded with their progress; offline the Library opens there. Walked on the emulator (build 101). |
| F5 | "Only my music" should be the default; "Show everything" makes no sense | **Fixed** (`5399414`): scope is mine / everything, default mine, wording "Show the whole server". |
| F6 | Offline shows every download, mine or not; shared tablets and TVs need switching users on a trusted device | Open. Downloads are per server profile, so separate profiles solve it; the **profiles** feature (switch user without signing out, trusted device, picker) is not built — see P4-16 below. |
| F7 | Test with two phones: an import on one must appear on the other (same account) | Open: needs the live channel in the app (P2-02 remainder) and the import through the new API (P2-04). The second emulator `encore_friend` exists for this. |
| F8 | Test like a new user, end to end, everything | Open: the journeys at the end of this page, to be run when P3/P4 are in; each earlier slice is walked on the emulator as it lands. |

## P0 — reset

* GitHub repository creation, rename of the old one and the first push: **blocked on the owner's permission lines** (`git push`, `gh pr ...`,
  `gh release create` in `~/.claude/settings.json`). Nothing has ever been pushed; the CI workflows have therefore never run on GitHub (they pass
  locally: app gate, server unit tests, the integration suite with a real Navidrome in Docker on the dev VM).
* P0-09 environments as code, P0-10 licence checks: not done. `git grep -il old-app` still finds the history in 14 docs.
* Android build tooling warns that Gradle 8.14, AGP 8.11 and Kotlin 2.2.20 "will soon be dropped" by Flutter: upgrade before the first release.

## P1 — instant play and the worst bugs

* P1-03: random 5-20 s spacing of background look-ups, the doubling rest up to 24 h on the **legacy** server (the new server has it: `sources/youtube/rest.py`),
  "interactive at most one look-up per 5 s while resting", the comparison with an import running (J-02).
* P1-04: preparing the first 3 songs of an opened album/playlist and the next 2 of the queue, cancelling stale prepares, dropping prepares first under back-off.
* P1-06: the app's `play.audible` span (the server side logs are there).
* P1-07: keystroke-to-results timing; two known search misses (Beach House "Space Song", Oum Kalthoum's Arabic title).
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
  mode: **done, with 1,684 tests**. Open: the live channel in the app (events instead of probing), the sign-in and join screens for an Encore
  server (invitation link/QR, the capability learned at "Test & continue"), a Home banner for the move (`session.upgrade`), Year in Music from the
  server's plays, covers from a playlist's picture URL, deleting the legacy `PlaylistMutations`/Subsonic paths once no server needs them, the walk on
  the emulator against the dev VM.
* P2-03 .. P2-17: not started (play is not save, imports in the app, import stop, Spotify beyond 100 songs, removing the portal code and the second
  import screen, playback state and resume anywhere in the app, one device at a time, invite-first sign-in, migrating today's installs on the server
  (the endpoint is built), catalogue module, downloads formats, lyrics on the server, notifications, a self-healing library, "follow the original").
* P2-18: server part belongs to P3-03.

## P3 — one server and the install

Not started except what P2 needed: the gateway, the accounts module (invites, join, reset, lock, rate limits), device tokens, the music-server
administrator client. Open: the compose file and image publishing, device-token gateway signing (X-2), the installer and `encore.local`, the wizard
and admin pages, clean-machine proof, updates with rollback, backups, security/privacy tests per cell of the matrix, devices and the Host's safety
nets, the Tinkerer's door.

## P4 — full feature set

Not started: recommendations, Jam on the live channel, friend activity, the quality tier on refs, Year in Music from the server, walking the whole
app, Encore Connect (devices, handover, remote volume), the home-server relay, federation, Jam across servers, tablets and large screens,
Spotify-class extras, problem reports, "wrong song?", browse and history, **profiles for shared devices (new, F6)**.

## P5 — public release

Not started. GitHub, the signing key (plan agreed in `../12`), licences, the website (not now).

## The journeys that close the first version (owner's instruction)

Each is run from the UI on fresh machines, written up in `../evidence/`, and every defect is fixed before the next:

1. Fresh install of the server on a clean VM with the one command, the wizard, the owner's account, the first invitation.
2. Fresh install of the app on a clean emulator: sign in, import a Spotify and a YouTube Music playlist (a long one too), watch it appear at once with
   its picture, play, download a playlist, go offline, come back.
3. A friend joins by invitation on a second emulator; both use the same server; likes and playlists stay separate.
4. The same account on two emulators: an import, a like, a playlist edit and a resume on one appear on the other within seconds.
5. A Jam on one server (host and guest), a catalogue song in the Jam, leave and rejoin, the host hands over.
6. A Jam with a person on another server (federation), and a guest seat for somebody with no server.
7. A shared tablet: two profiles, switch without signing out, separate downloads.
8. Updates and rollback, a backup and a restore, moving to another computer.
