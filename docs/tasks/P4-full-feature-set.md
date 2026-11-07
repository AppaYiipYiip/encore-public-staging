# P4 — Full feature set (in the first version, owner 2026-10-21)

Goal: the features that make Encore more than a player, built **on the new design** (song refs, the Encore server modules, the
live channel), not as wrappers around the old one. Stories: US-60 … US-64 (`../03a`). Old code to learn from (not to copy blindly)
is in `server/legacy/` (`encore-recs`, `hub`, `encore-quality`) and the app's `lib/features/jam`, `lib/features/year`,
`packages/encore_session`; their old designs: `old docs/47` (recommendations), `30` (Jam), `46` (two-speed library), `35` (people
and activity).

---

## P4-01 — A listening profile and recommendations per person — Size L
* **Order.** Needs: P2-12 [i], P4-20 [d], P4-23 [p]. Why: P4-20 chooses how suggestions are made (a ready-made engine or our own) before any of this is built; the candidate sources (similar artists via Deezer, MusicBrainz and ListenBrainz) are server-side lookups, and outside services go through the server (ADR-R38)..
* **Where it sits (2026-11-03).** Right after Jam (Discover): it is what makes daily use compelling for every user from the first day, which the cross-server features are not. The suggestions, smart shuffle (about one suggestion in five while shuffling, marked, one tap to keep or skip: `../20`), song radio, "New from artists you love" and "Not for me" are all in this task; following artists and the release notification are P4-18.
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
  two people with different tastes on two emulators get different rows; the owner rates his own Home after a week. Smart shuffle marks about one song in five as a suggestion with a one-tap keep or skip; song radio plays; "Not for me" on a suggested song or band removes it from that person's rows only.

## P4-02 — Jam on the live channel — Size L
* **Order.** Needs: P2-08 [d], P2-09 [d], P3-18 [p], P3-28 [d], P4-23 [p]. Why: D-61 (replaces D-53): the invitation comes AFTER Jam, so Jam can no longer wait for the first friend. It is walked through the owner's real address (the setup is gate 2, P3-18).
* **D-53 is replaced by D-61 (`10`, owner 2026-11-05): the setup pages and a button installer come BEFORE Jam and before any friend. The Order line below still shows the old order until the three-gates draft is applied (PR #151, after its hidden needs are added); do not plan from the old order.**
* **Order (D-61, owner 2026-11-05, replaces D-53).** The setup pages (P3-06) come BEFORE Jam, and Jam comes before the invitation (gate 3, P3-24). **First step: check ADR-083's recorded Tailscale Funnel limits against two listeners at the bitrate used for a Jam** (an owner on a PC browser and a friend on a phone, each on its own connection); if the limits do not hold, say so on the board before building.
* **Why.** US-61; finding C8 (today the Jam wraps every play).
* **Context.** `packages/encore_session` (Jam engine, 145 tests) and the Dart hub worked end to end on two emulators (old journeys
  E-60, E-63) and had real bugs only two real phones found (B48, B49). Field-test expectation: the Jam *is* the normal player.
* **Design.** `../13` section 5 (joining, clock, where each phone gets audio). This task builds the same-server Jam; P4-10 adds
  people on other servers on top of it, so keep descriptors and grants in mind from the start.
* **Acceptance (D-61).** The owner's PC browser and a phone, each on its own internet connection, through the away-from-home address, stay in step for a whole session, smooth, with seek, pause and a song change from either side.
* **Do.** Module `jam` in the Encore server on `/encore/live` (or keep the Dart hub as a sidecar if porting `encore_session` costs
  more than it saves — decide with a one-page comparison in the PR first). In the app, a Jam is a **session layer** that the normal
  player follows while in a Jam; outside a Jam the player has no Jam code on its path. Catalogue songs work in a Jam (each phone
  streams by song ref; the host's next songs are prepared).
* **Acceptance.** The old two-phone Jam journeys rewritten for the new design pass on two emulators, plus: leave/rejoin, host hands
  the speaker over, a catalogue song in the Jam, a network drop on one phone.
* **Audit B-20.** The app's Jam client targets the old hub on port 8703, which the shipped product does not run, and the Encore server has no Jam module. Decide first where the hub lives (the protocol, reducer and clock of `packages/encore_session` ported to the server, or the existing Dart hub run behind the server's own websocket); two implementations of one protocol must never exist at once.

## P4-03 — Friend activity — Size M
* **Order.** Needs: none.
* **Why.** US-62.
* **Do.** Opt-in per person (off by default); "what my friends who share are playing now / recently"; on the live channel; the Host
  sees nothing unless they are a friend who shares.
* **Acceptance.** Two emulators: sharing on → the other sees it ≤ 2 s; off → disappears at once.

## P4-04 — Quality tier on song refs — Size L
* **Order.** Needs: none.
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
* **D-61.** The lossless sources are an add-on of the model of the add-ons document that P3-20 writes (to be numbered 35): off by default with its plain risk text, switched on by a button or by `encore`, and either run by Encore or pointed at the person's own containers. Do not design a second switch here.

## P4-05 — Year in Music from the server's play history — Size S
* **Order.** Needs: none.
* **Why.** US-64; today it reads Navidrome's scrobbles, which miss plays of songs without files (old bug B46).
* **Do.** Read `play_event` from the Encore server; keep the screen; add songs played from YouTube.
* **Acceptance.** The numbers match an independent count from the database for one test person.

## P4-06 — Walk the whole app again — Size M
* **Order.** Needs: P4-02 [p], P4-07 [p], P4-09 [p], P4-10 [p], P4-01 [p], P4-04 [p], P6-02 [p]. Why: the walk covers US-60 to US-64 and the new journeys and, from 2026-11-04, the browser version (P6-02), so it follows the features it walks; it is the last task of the feature set..
* **Do.** All journeys of `../07` §7 plus the new ones for US-60 … US-64 on profiles A–C and two emulators; fix S1/S2.
* **Acceptance.** No open S1/S2; the QA report lists what was not run and why.

## P4-07 — Encore Connect: your devices, handover and remote volume — Size L
* **Order.** Needs: P2-08 [d], P2-09 [d], P4-23 [p]. Why: crossfade (P4-23) changes the player's engine, which this item also changes, so it is done first (audit B-8; a rule of the plan, not a hard need).
* **Why.** Owner: "increase the sound of the music playing on the tablet from my phone, as long as it's the same account … play/pause".
  US-70, US-71; design `../13` §2; risks H1, H5, H6, H10, H15.
* **Context.** The player's "Devices" button opened Android's output switcher; D-28 took it out on 2026-10-30, so this task adds Encore's own sheet to an empty place (the old call was `AudioOutput.showSwitcher()` in
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
* **Owner, 7 Nov 2026 (D-66):** "pick where to play this music: a Bluetooth device, headphones, the phone speaker, a browser, or another phone (both connected to the same account, you can test it with the real phone and the emulator)". The first two sections of the Devices sheet are split: **This phone** is `P1-25`, **Your other devices** is this task, in the same sheet. A first test needs only two apps on one account (the A35 and an emulator); a browser device needs the web client, which is not planned in Now. The owner may want this nearer the top of the list than position 76: his to move on the board.

## P4-08 — Home-server relay: the app only talks to its own server — Size M
* **Order.** Needs: P4-09 [i]. Why: the relay is the layer through which the home server calls the other server, and its acceptance is a capture of a cross-server Jam, which needs P4-09 and P4-10..
* **Why.** Owner: one person, one account; no second account in the app (`../13` section 3, ADR-R17).
* **Do.** In the Encore server, a relay layer: cross-server features (friends, activity, Jam, shared songs) are requested by the app
  from its own server, which calls the other server and returns or streams the result. The app never stores another server's address
  or token. Remove any multi-account idea from the app.
* **Acceptance.** A network capture of a guest phone during a cross-server Jam shows connections only to its own server.

## P4-09 — Connecting with people on other servers (federation core) — Size L
* **Order.** Needs: P0-09 [d], P4-03 [d], P4-19 [d].
* **Before it merges (2026-11-03).** An ultrareview (`/code-review ultra`, run by the owner) of the signed server-to-server code: it is the riskiest code in the plan.
* **Why.** Owner: "how can I add a friend who is on a different server" / "maybe servers communicating with each other? opt in?".
  US-72, `../13` section 4, H8, ADR-R16. Opt-in at two levels: the Host's switch (D-13) and both people accepting.
* **Do.** Server identity (key pair, `/.well-known/encore`), signed server-to-server requests, friend links via one-time QR/link codes,
  friends list in the app (same-server and other-server friends together), remove friend, the Host's switch "Allow friends from other
  servers", rate limits per remote server. Friend activity (P4-03) and Jam invitations work for both kinds of friends.
* **Acceptance.** Two servers (dev VM + a second clean VM, both with public addresses): people on each become friends by QR in
  ≤ 30 s; removing the friendship stops all sharing at once; a forged request (wrong signature) is refused (test).

## P4-10 — Jam across servers, sharing, collaborative playlists — Size L
* **Order.** Needs: P4-02 [d], P4-09 [d].
* **Why.** Owner: "jam with him songs I have on my server, he has on his server, none of us have". US-73, U5, U6, `../13` §5, H2–H4,
  H7, H9, H24.
* **Do.** A guest's home server joins the Jam on the host's server (server-to-server; a Jam code is enough, no friendship needed) and
  relays it to its own phones; a Jam-only guest seat for people with no Encore server if the owner keeps D-15; portable song
  descriptors in the Jam queue; each home server finds the audio for its phones (own file → own YouTube source with the adder's
  video id → the other server's Jam-scoped grant, cached only for the Jam, transcoded Opus 96–128);
  the ±1.5 s version rule; per-phone offset reporting; the Host's switch for cross-server Jams. Share a song/playlist as a link
  (resolved on the receiver's server); collaborative playlists with members on the same or other servers.
* **Acceptance.** J-18 passes; a guest whose own server is offline still hears every song (via grants); the host's upload use is shown.

## P4-11 — Tablets and large screens — Size M (un-parked by D-54)
* **Order.** Needs: P5-06 [p], P6-02 [d], P6-08 [d]. Why: the tablet reuses the large-screen layouts that the browser player (P6-02) builds (D-58); the layouts are drawn first (D-43), which is P6-08; and docs/tasks/P6-later.md says the tablet layouts need "the phone app proven in daily use", which is the public release..
* **Un-parked (2026-11-03, D-54, amending D-18).** It is the first of the three last items (tablet, then TV, then iPhone).
* **Why.** U1: the owner uses a tablet; Android 16 ignores orientation/resizability locks on screens ≥ 600 dp for apps targeting SDK 36.
* **Do.** Adaptive layout: navigation rail, list + detail panes, player as a side panel in landscape; keyboard and mouse basics.
* **Acceptance.** Profile E and a landscape tablet emulator: every screen usable in both orientations and split-screen; screenshots in the PR.

## P4-12 — Android Auto: browse your music and play by voice from the car screen — Size S
* **Order.** Needs: none. Why: U2. **Split 7 Nov 2026 (roadmap grooming, the owner said yes): this item was four unrelated features in one Large task (Android Auto, the home-screen widget, crossfade, the Data saver switch); it keeps Android Auto, the widget is P4-22, crossfade is P4-23, the Data saver switch is P4-24. They differ in size, in risk and in what must be decided first, so each is walked and marked on its own; the friend gate (P3-24) waits for all four.** Reduced on 2026-11-05 (D-61): the owner asked for these before his friend is invited.
* **What exists (audit, `AUDIT-BUILT-2026-11-05.md` feasibility table).** The browse tree and `playFromSearch` (voice search) are already in `playback/encore_audio_handler.dart`; the car app description is declared in the manifest. Never tried in a car or on the desktop head unit.
* **Decide first.** (1) D-18 parked car frames; the owner's request of 5 Nov (D-61) asks for Android Auto before the invitation, so write that down in `10` when this is started. (2) **The distribution risk (audit B-26):** Android Auto hides apps that were not installed from the Play Store unless the phone's Android Auto developer setting "Unknown sources" is on, which collides with GitHub-only distribution (D-56): say in the install guide (P5-07) what a person does, or accept that the car screen needs that setting, and write which.
* **Do.** Walk the browse tree and voice search in Google's desktop head unit (DHU) and, if the owner has a car, in the car; fix what that shows; add what the install guide must say.
* **Acceptance.** In the desktop head unit: browse Home, Library and Playlists with big touch targets, start a song from the list and by voice ("play Fairuz"), see the cover and title, pause and skip from the car screen, and the same on the owner's car if there is one; the install guide says the Unknown-sources step.
* **Size.** S for the code, the rest is the two decisions.

## P4-22 — A home-screen widget: what is playing, with play, pause and next — Size M
* **Order.** Needs: none. Why: U3. Split out of P4-12 on 7 Nov 2026. The audit found no widget code at all (the Kotlin side is `MainActivity.kt`, small channels only), no drawing (D-43: drawn before built), and no conflict with any rule.
* **Do.** (0) **Drawn first** and approved by the owner: a small widget (cover, title, play and pause) and a wide one (cover, title, artist, previous, play and pause, next), in the app's look (`16`); what the widget shows when nothing is playing, when the phone is offline and when the app has never been opened. (1) An `AppWidgetProvider`, the layout and a plugin such as `home_widget`; (2) the current song, cover and state come from the audio handler (it runs in the app's own process, so the state is readable); the buttons send media commands and open the app on a tap on the cover.
* **Acceptance.** On the A35: add the widget to the home screen; start a song; the widget shows its title and cover within 2 s and its button pauses and resumes the song with the app closed; next skips; a tap on the cover opens the player; after the app is force-stopped the widget shows its empty state in words, not a blank box.
* **Size.** M.

## P4-23 — Crossfade between songs, with gapless kept — Size L
* **Order.** Needs: none. Why: U7. Split out of P4-12 on 7 Nov 2026. **The riskiest of the four (audit B-8):** the player is one `just_audio` player on one gapless `ConcatenatingAudioSource`, and the engine's window and index logic (`_expectedIndex`, the next-song preparation of P1-04) assume exactly that. A crossfade needs a second player overlapped with the first, which changes how the next song is prepared and how skip, seek and the end of a list behave: a real risk to "the player never gets stuck" (P1-08). **Do it before the features that add more engine behaviour (Jam P4-02, Connect P4-07, smart shuffle P4-01), not after: those three carry a policy need on this item.**
* **Do.** A setting "Crossfade" (off, or 1 to 12 seconds; off by default; gapless between the songs of one album stays gapless, as in Spotify); decide with a one-page comparison first (a second player against a fade at the audio-focus level) and write the choice in the PR; the sleep timer's existing 10-second fade is reused for the curve.
* **Acceptance.** On the A35 and an emulator: two songs with a 6 s crossfade: the audio track is sampled and the outgoing volume falls while the incoming rises, without a gap or a jump; Next, Previous, seek, pause and a lost network during the fade leave the player in a state it says (J-07 and the rapid-Next run still pass; no PLAYING-while-silent); off means the same gapless behaviour as today (a test pins it); the song list's end and repeat-one do not crossfade a song into itself.
* **Size.** L, with real risk.

## P4-24 — One Data saver switch for slow or metered connections — Size S
* **Order.** Needs: none. Why: U9. Split out of P4-12 on 7 Nov 2026. **Decide first what the switch means:** "Data saver" is already one of the quality levels (Opus 48 kbps, `domain/audio_quality.dart`, chosen in Settings > Playback), so the planned single switch may only duplicate it. Proposed meaning: one switch that, when on and only while the phone is on mobile data, caps streaming and new downloads at the Data saver level, stops preparing the songs after the next one on the phone's side, loads small pictures, and syncs less often (P1-14 "Less syncing" holds the sync half; do them together or say which half is which).
* **Do.** The switch in Settings (one line, with the plain words of what it does); the four effects above behind it; nothing changes while it is off or while the phone is on Wi-Fi.
* **Acceptance.** Measured with the phone's own per-app data counter on mobile data: with the switch on, a four-minute song streams in about 1.5 MB or less (48 kbps), a Home page of pictures loads in less than half the bytes, and the idle sync moves less than before; with it off, or on Wi-Fi, the numbers equal today's.
* **Size.** S.

## P4-13 — Problem reports and battery-saver guidance — Size M
* **Order.** Needs: none.
* **Why.** U15, H12.
* **Do.** Opt-in crash/problem reports stored on the Host's own server (stack trace, app version, device model, Android version, last
  20 log lines without personal data), an admin "Problems" page with export; detect aggressive battery savers by manufacturer and show
  a one-time guide.
* **Acceptance.** A forced crash on the emulator appears in the admin within 1 minute; nothing is sent anywhere else (network capture).
* **Idea to engineer first (owner, 2026-10-22): a message to the server owner, for any user of any server.** A person types a note in the app
  (a problem, a request "please add this album", a question); it goes to the server he signed in to and the owner sees it in an inbox in Your
  server, with a live-channel nudge; the technical details are an opt-in tick; the owner can answer in the app. It replaces "message him on
  WhatsApp" only where the owner is not somebody you can message, so it is worth building when a server has more than a few people. Open: spam
  and abuse limits per account, what the owner may read (never listening, R33), whether answers are shared. A share-sheet-only version was
  built and put on hold (`parked/in-app-report`, ADR-R35): it did not need a server, but it did not help anybody who can already message the owner.

## P4-14 — "Wrong song?" and the Host's metadata fixes (server + app + admin) — Size M
* **Order.** Needs: P2-12 [i]. Why: the alternatives and previews of the "Wrong song?" sheet come from the catalogue module..
* **Why.** `../19` §5, H23: wrong versions will happen and today nothing can fix them.
* **Do.** The "Wrong song?" sheet with up to 5 alternatives and previews; server-wide apply with history and Host undo; re-keep the chosen
  version as a new file (likes stay); Admin → Music: edit a ref's title/artist/album/cover, recent fixes, duplicates.
* **Acceptance.** A live version replaced by the studio version keeps its likes, playlist places and downloads (which update on Wi-Fi).

## P4-15 — Browse, history and playlist details (app + server) — Size M
* **Order.** Needs: P2-17 [d].
* **Why.** `../27` §1: holes in "Find music" and "Organise".
* **Do.** Browse: charts of the server's country (Deezer charts), moods and genres, editorial playlists (public YouTube Music/Spotify
  editorial lists imported with "Follow the original", P2-17); a full **Recently played** screen from `play_event`; playlist descriptions.
* **Acceptance.** Browse is never empty on a brand-new server; Recently played matches the server's history for a test person.

## P4-17 — Compare tastes (opt-in on both sides) — Size M
* **Order.** Needs: P4-09 [d].
* **Why.** US-65 (owner, 2026-10-24: *"a listening-habits comparison between users of the same server, and between friends; but sometimes I don't want to share what I listen to, so it should be opt-in"*). Later: after the owner has used the app daily.
* **Do.** Server: a per-person switch `taste_sharing` (off by default) and a match computed from the plays of the two people who have **both** switched it on: artists and genres they share, a score, a shared playlist (the pattern is Spotify's Blend); listening marked private is excluded; withdrawing deletes the match at once. App: the switch in Settings > Privacy (one sentence on what is shared), the screen S-54 (`design/00`), and nothing at all for a person who has not agreed. Across servers only when the server allows connecting with other servers (P4-09).
* **Acceptance.** Two emulators: both off, nothing appears anywhere; one on, the other sees nothing and the first sees "waiting for <name>"; both on, the match shows within 5 s; one withdraws, it disappears on both within 2 s and the server holds no copy; a private play never changes the match (a test with a model: Hypothesis, `ADR-R41` T3).

## P4-16 — Profiles on a shared device (tablet, TV, a family phone) — Size L
* **Order.** Needs: P4-11 [d], P3-03 [d].
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

## P4-18 — Follow artists, and a notification when one of them releases something — Size S
* **Order.** Needs: P2-15 [i]. Why: the new-release alerts that this task shows come from the server-side check that P2-15 builds (ADR-R38 moves the check off the phone)..
* **Why.** The owner, 2026-11-03: "a notification when an artist I follow releases a song". The server already keeps a person's follows (`PUT/DELETE follows/{artistId}`, `17`), and the phone already has a new-release check and the in-app bell, but the check calls Deezer from the phone (an ADR-R38 debt, removed by P2-12 and P2-15) and following an artist is not a finished feature. "Follow artists" used to be a line of P4-12; it moved here because Discover needs it.
* **Do.** Follow and unfollow on the artist page and a Following list; a "New from artists you follow" shelf on Home; a new-release item in the bell (What's new); one opt-in phone notification category, "New music from artists you follow" (ADR-R44 allows at most two opt-in categories; this one and Jam invitations); nothing is sent for artists a person merely played, only for the ones followed.
* **Don't.** Send a person's follows or history to an outside service; post a phone notification by default (ADR-R44, D-52).
* **Acceptance.** Following an artist whose release shows up in the server's daily check gives a bell item within the check interval; the phone notification appears only when the category is on; unfollowing stops it; two people with different follows get different items.
* **Size.** S.

## P4-19 — Start Claude's deep security review before friends on other servers merge (owner) — Size S
* **Order.** Needs: none.
* **Owner's step (D-59).** One command typed by him (`/code-review ultra`, billed): the riskiest code of the plan (signed server-to-server requests) is reviewed before it merges. Claude writes the code on a branch first and tells him the exact command when it is time; P4-09 merges only after. Today: nothing to do yet.
* **Acceptance.** The review ran on the federation branch and every finding is fixed or accepted in writing.
* **Size.** S (his time, not counted).

## P4-20 — Choose how suggestions are made: a ready-made engine or our own (study) — Size S
* **Order.** Needs: P2-12 [i]. Why: suggestions need candidate sources that are server-side lookups, and the study uses them.
* **Why.** The owner wants a complete recommendation system: "implement one or use one that is already made". The advisor decides from numbers, not from taste (D-59).
* **Do.** Compare, on the owner's real plays and on the labelled set, at least: (1) a ready-made source of recommendations that the server can ask (for example ListenBrainz's), (2) an open-source recommender library run inside the server, (3) our own similar-artist and taste-profile model of P4-01. Measure: how many useful rows a new person gets in the first 20 songs, how different two people's rows are, what each needs to run on a small home server (memory, time), and what it sends outside (the server makes every outside call; no person's history leaves it). Write the numbers in an evidence file.
* **Acceptance.** An evidence file with the comparison and a one-paragraph decision by the advisor; P4-01's Do text names the chosen approach.
* **Size.** S.

## P4-21 — Library polish (split out of P4-12) — Size M
* **Order.** Needs: none. Why: P4-12 was one Large task for nine small ones. The owner (5 Nov 2026) asked for Android Auto, the home-screen widget, crossfade and the Data saver switch before his friend is invited; the rest of the list can come after.
* **Do.** Search aliases and transliteration and search history; library sort, filter, pins, folders and custom covers; Liked Songs download with new likes following. Start from `29-spotify-gap-review.md`.
* **Acceptance.** Each sub-task has its own journey; the owner compares side by side with Spotify on his phone and lists gaps.
* **Size.** M.
