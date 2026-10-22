# P4 — Full feature set (in the first version, owner 2026-10-21)

Goal: the features that make Encore more than a player, built **on the new design** (song refs, the Encore server modules, the
live channel), not as wrappers around the old one. Stories: US-60 … US-64 (`../03a`). Old code to learn from (not to copy blindly)
is in `server/legacy/` (`encore-recs`, `hub`, `encore-quality`) and the app's `lib/features/jam`, `lib/features/year`,
`packages/encore_session`; their old designs: `old-app/docs/47` (recommendations), `30` (Jam), `46` (two-speed library), `35` (people
and activity).

---

## P4-01 — A listening profile and recommendations per person — Size L
* **Why.** US-60; owner: "each one has his own … recommendation system profile tailored to him".
* **Context.** The old `encore-recs` built nightly lists from a copy of Navidrome's database plus MusicBrainz/ListenBrainz/Deezer
  (names only), 73 tests; it could not see plays of songs without files. Now every play (owned or not) is a `play_event` on a song
  ref (P2), so the profile sees everything. Navidrome 0.60+ has Instant Mix and `getSimilarSongs2` (free baseline).
* **Do.** Module `recs` in the Encore server: per-person profile (artist and tag weights from plays, completion, skips, likes,
  recency; private to the person; the Host sees only on/off and counts); candidate sources (similar artists via Deezer/MusicBrainz/
  ListenBrainz public data by *name only*, the person's own library, other songs on the server only if the person has played that
  artist); rows "Made for you", "Because you play X", "New from artists you love", "Deeper cuts"; song radio and smart shuffle;
  "Not for me" feedback; computed nightly + incrementally after 20 new plays; cached for offline. App: Home rows, radio, smart
  shuffle setting, "Not for me".
* **Don't.** Send any person's history to an outside service; let one person's taste shape another's rows.
* **Acceptance.** Unit tests on profile maths; journey: a new person imports a playlist and plays 20 songs → useful rows appear;
  two people with different tastes on two emulators get different rows; the owner rates his own Home after a week.

## P4-02 — Jam on the live channel — Size L
* **Why.** US-61; finding C8 (today the Jam wraps every play).
* **Context.** `packages/encore_session` (Jam engine, 145 tests) and the Dart hub worked end to end on two emulators (old journeys
  E-60, E-63) and had real bugs only two real phones found (B48, B49). Field-test expectation: the Jam *is* the normal player.
* **Design.** `../13` section 5 (joining, clock, where each phone gets audio). This task builds the same-server Jam; P4-10 adds
  people on other servers on top of it, so keep descriptors and grants in mind from the start.
* **Do.** Module `jam` in the Encore server on `/encore/live` (or keep the Dart hub as a sidecar if porting `encore_session` costs
  more than it saves — decide with a one-page comparison in the PR first). In the app, a Jam is a **session layer** that the normal
  player follows while in a Jam; outside a Jam the player has no Jam code on its path. Catalogue songs work in a Jam (each phone
  streams by song ref; the host's next songs are prepared).
* **Acceptance.** The old two-phone Jam journeys rewritten for the new design pass on two emulators, plus: leave/rejoin, host hands
  the speaker over, a catalogue song in the Jam, a network drop on one phone.

## P4-03 — Friend activity — Size M
* **Why.** US-62.
* **Do.** Opt-in per person (off by default); "what my friends who share are playing now / recently"; on the live channel; the Host
  sees nothing unless they are a friend who shares.
* **Acceptance.** Two emulators: sharing on → the other sees it ≤ 2 s; off → disappears at once.

## P4-04 — Quality tier on song refs — Size L
* **Why.** US-63; owner decision D-4; default D-12 (off until the Host switches it on).
* **Context.** The old `encore-quality` (139 tests) wired Lidarr 3.1 + slskd + Soularr, proved one album end to end in 13 s on a
  private Soulseek network; the real network found nothing for four obscure albums; Lidarr needs the artist monitored and the album
  marked after the refresh (8.5 min refresh for a 126-release artist); its "upgrade map" exists only because file ids changed. With
  song refs, an upgrade is just a new `file_id`.
* **Do.** Module `quality` + an optional compose profile (Lidarr, slskd, Soularr; no published ports; nothing shared to the network);
  admin switch with plain-words risk text; upgrade only kept songs (D-3 rules); attach the better file to the same song ref; keep the
  old file 14 days for a way back.
* **Acceptance.** On the dev VM (private Soulseek network as before): a kept song is upgraded to FLAC and its likes, playlist places,
  downloads and resume position are unchanged; switching the tier off stops all network activity of the three programs.

## P4-05 — Year in Music from the server's play history — Size S
* **Why.** US-64; today it reads Navidrome's scrobbles, which miss plays of songs without files (old bug B46).
* **Do.** Read `play_event` from the Encore server; keep the screen; add songs played from YouTube.
* **Acceptance.** The numbers match an independent count from the database for one test person.

## P4-06 — Walk the whole app again — Size M
* **Do.** All journeys of `../07` §7 plus the new ones for US-60 … US-64 on profiles A–C and two emulators; fix S1/S2.
* **Acceptance.** No open S1/S2; the QA report lists what was not run and why.

## P4-07 — Encore Connect: your devices, handover and remote volume — Size L
* **Why.** Owner: "increase the sound of the music playing on the tablet from my phone, as long as it's the same account … play/pause".
  US-70, US-71; design `../13` §2; risks H1, H5, H6, H10, H15.
* **Context.** The player's "Devices" button opens Android's output switcher (`AudioOutput.showSwitcher()` in
  `now_playing_screen.dart`). `audio_service` 0.18.19 supports remote playback info (`androidPlaybackInfo` with
  `RemoteAndroidPlaybackInfo`, callbacks `androidSetRemoteVolume`, `androidAdjustRemoteVolume`). P2-08/P2-09 give playback state
  and the active-device lease.
* **Do.** Server: device registry, device state (playing, position, volume, available), commands with revisions over `/encore/live`,
  transfer. App: Devices sheet (this phone + other devices, greyed when unavailable with the reason), transfer at the same second,
  remote controls (play/pause/next/prev/seek/queue/like/volume slider), media session in remote mode so the hardware volume keys and
  the system volume panel control the active remote device; on the target, a platform channel applies `AudioManager` media volume and
  reports changes (buttons, system panel). "Always ready to play" setting with a persistent notification. Spike first: H10 (setting
  volume from the background on Android 15/16).
* **Acceptance.** J-16, J-17 on two emulators (phone profile A, tablet profile E) at home and through the public address.

## P4-08 — Home-server relay: the app only talks to its own server — Size M
* **Why.** Owner: one person, one account; no second account in the app (`../13` section 3, ADR-R17).
* **Do.** In the Encore server, a relay layer: cross-server features (friends, activity, Jam, shared songs) are requested by the app
  from its own server, which calls the other server and returns or streams the result. The app never stores another server's address
  or token. Remove any multi-account idea from the app.
* **Acceptance.** A network capture of a guest phone during a cross-server Jam shows connections only to its own server.

## P4-09 — Connecting with people on other servers (federation core) — Size L
* **Why.** Owner: "how can I add a friend who is on a different server" / "maybe servers communicating with each other? opt in?".
  US-72, `../13` section 4, H8, ADR-R16. Opt-in at two levels: the Host's switch (D-13) and both people accepting.
* **Do.** Server identity (key pair, `/.well-known/encore`), signed server-to-server requests, friend links via one-time QR/link codes,
  friends list in the app (same-server and other-server friends together), remove friend, the Host's switch "Allow friends from other
  servers", rate limits per remote server. Friend activity (P4-03) and Jam invitations work for both kinds of friends.
* **Acceptance.** Two servers (dev VM + a second clean VM, both with public addresses): people on each become friends by QR in
  ≤ 30 s; removing the friendship stops all sharing at once; a forged request (wrong signature) is refused (test).

## P4-10 — Jam across servers, sharing, collaborative playlists — Size L
* **Why.** Owner: "jam with him songs I have on my server, he has on his server, none of us have". US-73, U5, U6, `../13` §5, H2–H4,
  H7, H9, H24.
* **Do.** A guest's home server joins the Jam on the host's server (server-to-server; a Jam code is enough, no friendship needed) and
  relays it to its own phones; a Jam-only guest seat for people with no Encore server if the owner keeps D-15; portable song
  descriptors in the Jam queue; each home server finds the audio for its phones (own file → own YouTube source with the adder's
  video id → the other server's Jam-scoped grant, cached only for the Jam, transcoded Opus 96–128);
  the ±1.5 s version rule; per-phone offset reporting; the Host's switch for cross-server Jams. Share a song/playlist as a link
  (resolved on the receiver's server); collaborative playlists with members on the same or other servers.
* **Acceptance.** J-18 passes; a guest whose own server is offline still hears every song (via grants); the host's upload use is shown.

## P4-11 — Tablets and large screens — Size M
* **Why.** U1: the owner uses a tablet; Android 16 ignores orientation/resizability locks on screens ≥ 600 dp for apps targeting SDK 36.
* **Do.** Adaptive layout: navigation rail, list + detail panes, player as a side panel in landscape; keyboard and mouse basics.
* **Acceptance.** Profile E and a landscape tablet emulator: every screen usable in both orientations and split-screen; screenshots in the PR.

## P4-12 — Spotify-class extras — Size L (split into sub-tasks when started)
* **Why.** U2, U3, U7–U11, U13.
* **Do.** Search aliases/transliteration and history; Follow artists; library sort/filter/pins/folders/custom covers; Liked Songs
  download with new likes following; crossfade setting (gapless kept); Android Auto search and `MEDIA_PLAY_FROM_SEARCH`; a home-screen
  widget; a single "Data saver" switch.
* **Acceptance.** Each sub-task has its own journey; the owner compares side by side with Spotify on his phone and lists gaps.

## P4-13 — Problem reports and battery-saver guidance — Size M
* **Why.** U15, H12.
* **Do.** Opt-in crash/problem reports stored on the Host's own server (stack trace, app version, device model, Android version, last
  20 log lines without personal data), an admin "Problems" page with export; detect aggressive battery savers by manufacturer and show
  a one-time guide.
* **Acceptance.** A forced crash on the emulator appears in the admin within 1 minute; nothing is sent anywhere else (network capture).

## P4-14 — "Wrong song?" and the Host's metadata fixes (server + app + admin) — Size M
* **Why.** `../19` §5, H23: wrong versions will happen and today nothing can fix them.
* **Do.** The "Wrong song?" sheet with up to 5 alternatives and previews; server-wide apply with history and Host undo; re-keep the chosen
  version as a new file (likes stay); Admin → Music: edit a ref's title/artist/album/cover, recent fixes, duplicates.
* **Acceptance.** A live version replaced by the studio version keeps its likes, playlist places and downloads (which update on Wi-Fi).

## P4-15 — Browse, history and playlist details (app + server) — Size M
* **Why.** `../27` §1: holes in "Find music" and "Organise".
* **Do.** Browse: charts of the server's country (Deezer charts), moods and genres, editorial playlists (public YouTube Music/Spotify
  editorial lists imported with "Follow the original", P2-17); a full **Recently played** screen from `play_event`; playlist descriptions.
* **Acceptance.** Browse is never empty on a brand-new server; Recently played matches the server's history for a test person.

## P4-16 — Profiles on a shared device (tablet, TV, a family phone) — Size L
* **Why.** Owner, 2026-10-22: *"In a shared tablet, Android TV, same app, same server, multiple users, we should implement switching users,
  after signing in I mean: you can leave the session, someone else signs in, but it is a trusted device, no need to sign out."* And: offline mode
  showed every download "mine or not".
* **Design.** A device can hold several **profiles**, one per person who signed in on it. A profile is what a server row already is: the person's
  account on a server, their library, their downloads, their queue, their credentials in secure storage. Today the app opens the lowest server id;
  this task makes the active profile a choice.
  * **Trusted device** (a switch in Settings, on by default on tablets and TVs, off on phones): the app opens on *Who's listening?* with the
    profiles' names and pictures, "Add someone" (sign in, or join with an invitation/QR) and "Guest" (one session that leaves nothing behind).
    Picking a profile needs no password on a trusted device (it is the sign-in that was done once); an optional 4-digit PIN per profile guards it.
  * **Switch user** from anywhere (the profile picture in Home and Settings): stops the player of the old profile (or hands the queue to the new
    one if it asks), swaps the session, keeps everything of the old profile exactly as it was.
  * **Leave the session** (the old "sign out" without deleting): returns to the picker; removing a profile and its downloads is a separate, asked step.
  * Downloads, queue, history, covers cache keys and Jam state are per profile; the files of a download live in the profile's folder; the library
    scope "mine" is therefore automatically the active profile's. A TV shows only what is on it or on the server for that profile.
  * Server side: nothing new is required (each profile is a person with its own device token); the owner can see a device's profile names in
    the device list.
* **Don't.** Share one login between people; keep a password on a trusted device after sign-in (device token only); mix two profiles' downloads.
* **Acceptance.** J-18 (new): two people on one emulator, each with their own playlists and downloads; switching takes ≤ 2 s; offline each sees only
  their downloads; the second person's sign-out/removal leaves the first's data; the picker works with the TV remote (D-pad focus) on the tablet AVD.
* **Depends on.** P2-02 (the session is per server row already), P3-03 (device tokens, so no password stays); sizes of the picker for tablets: P4-11.
