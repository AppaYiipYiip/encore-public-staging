# P6 — The last items: large screens (tablet and browser), TV, iPhone, and what stays parked

The owner, 2026-11-03 (D-54, amending D-18): **the tablet, TV and iPhone versions come last in the plan**, and on 2026-11-03 he asked whether the browser comes before the tablet. A task id names a topic, never a time; the tablet task keeps its old id P4-11. The order below is the engineer's recommendation and the owner may re-order it:
1. **Large screens: the drawings, the tablet, the browser player.** They share their main cost, the large-screen layouts (a navigation rail, list and detail panes, a side player, keyboard and mouse). If the browser player is built from the same Flutter code, as recommended, the tablet layouts come first and the browser reuses them; the tablet task is done first.
2. **TV:** the same app with a different input model (the D-pad) and drawings that already exist.
3. **iPhone:** a new platform with a gate decided outside this project. The app is distributed on GitHub only (D-56): no App Store, no TestFlight, no Apple developer account, so it is last, and it starts with a verification task (P6-04) whose answer may well be "no".
All of them need the same foundation: the app talks only to its own server (the outside-host ratchet at zero, the API schema checked in CI, the device token instead of the music server's login) and a public release that proved the phone app in daily use.

## P6-01 — Browser design: the drawings for the browser player — Size S
* **Order.** Needs: none.
* **Why.** D-43: a page is drawn when it is new and about to be built. D-18 said "no separate drawings until asked"; the owner asked (D-54). The phone drawings (`docs/design`) are the starting point; the TV's ten-foot drawings already exist (ADR-R42).
* **Do.** Drawings for a tablet in portrait, landscape and split screen, and for a desktop browser window: a navigation rail, list and detail panes, the now-playing view as a side panel, keyboard and mouse basics, the state gallery of each screen. Drawn by the planning agent and approved by the owner before any code.
* **Acceptance.** The owner approves the drawings; every screen of the phone app has its desktop-browser counterpart or a written "scales as it is".

## P6-02 — Browser player (any desktop browser) — Size L
* **Order.** Needs: P6-01 [i], P2-19 [d], P2-23 [p], P2-20 [i], P2-12 [i], P2-14 [i]. Why: P2-19: the browser signs in with a code shown on its page and approved on a phone that is already signed in (slice D); built from the same Flutter code (recommended) it builds the large-screen layouts (size classes) that the tablet and the TV reuse later (D-55, D-58), from the drawings of P6-01; it is a client of the checked API schema (P2-23) that holds only a device token (P2-20) and calls no outside service (P2-12, P2-14: a browser cannot read Deezer, ADR-R38)..
* **Decide first (to ask the owner, D-55).** One code base compiled for the web (one design system, no second app to maintain for years; needs web-safe plugins and a web database) or a separate web app (a second code base for ever). The recommendation is the first. State the limits before building (to verify, not assumed): no background downloads or offline library in a tab, autoplay rules, lock-screen controls and background audio on phones, stream and cover addresses that work without custom headers (signed addresses, ADR-R38 point 2).
* **Why.** It is the proof that the thin-client rule holds: if a browser can use the server, so can every later client. A browser is also the nearest thing to an iPhone version that needs no store (see P6-04).
* **Do.** The Encore server serves the browser app itself from the same address (static files), so nothing else is installed; a browser signs in by an invitation link or with a code approved on a signed-in phone. Search, play, the queue, likes, playlists, lyrics, devices and Jam join, on the large-screen layouts; the same server, the same account.
* **First step (D-55, decided by the advisor on the owner's behalf: the same Flutter code).** A one-day proof with numbers in the PR: play, seek, media keys, a long list, and first load on TYPICAL. If it fails, the browser becomes a separate web app on the same API and this task is re-planned; the server does not change either way.
* **Acceptance.** The core journeys pass in a desktop browser; a network capture shows connections only to the home server; what a browser cannot do (offline downloads) is said in plain words on the screen.

## P6-03 — Android TV client (Android TV, Google TV, Fire TV) — Size L
* **Order.** Needs: P6-02 [i], P2-19 [d], P2-23 [p], P2-20 [p]. Why: the TV reuses the adaptive layouts that the browser player (P6-02) builds; P2-19 slice D is the sign-in by a code entered on a signed-in phone (`tasks/P6-later.md` names Quick Connect, ADR-R40 slice D, as a prerequisite); a new client is built against the checked API schema (P2-23) and holds only the device token (P2-20)..
* **Why.** Owner, 2026-11-03: a TV version. The ten-foot layouts are drawn in `docs/design` (ADR-R42); the six-digit TV code is drawn and not built (D-18).
* **Do.** A leanback launcher entry and banner, D-pad focus on every screen with a visible focus ring, the ten-foot layouts as drawn, sign-in by a code entered on a signed-in phone, playback and the queue, lyrics full screen. **No admin on a TV** (D-18: the admin is PC-only).
* **Don't.** Build a second app: it is the same Flutter code with its own entry point and layouts. Call any outside service.
* **Acceptance.** Every screen is operable with a D-pad only on an Android TV emulator and on one real TV or streamer; the playback journeys pass there; screenshots in the PR. A person signs in on the TV with a code approved on a phone that is already signed in.

## P6-04 — iPhone: can it be installed without Apple's store? (check first) — Size S
* **Order.** Needs: P2-23 [p], P2-20 [p], P2-12 [p], P2-14 [p], P5-06 [p]. Why: `tasks/P6-later.md` makes the schema checked in CI, the thin client and "after the first public version" the prerequisites of iOS, and the thin client is what P2-12, P2-14 and P2-20 deliver..
* **Why.** An iOS version is a new platform with gates decided by Apple. Encore is distributed on GitHub only (D-56): no App Store, no TestFlight, no Apple developer account. Find out *before* writing code whether an iPhone version can then reach anybody, and treat a "no" as a result, not as a delay.
* **Do.** Verify, with the source and the date for each: how an iPhone installs an app from outside the store (sideloading with a free Apple ID and its re-signing limit, the tools people use, the EU alternative-marketplace rules and what they demand); App Transport Security and local networking (the installer's address is plain `http` on the LAN; `NSAllowsLocalNetworking`); GitHub's macOS runner minute multiplier against the Actions minutes budget; background audio, local notifications, downloads and app links on iOS; a Flutter iOS audit of every plugin the app uses (`just_audio`, `audio_service`, `background_downloader`, `flutter_local_notifications`, drift, app links). **Also check what an iPhone's browser lets the browser player (P6-02) do** (background audio, lock-screen controls, notifications, adding it to the home screen): it decides how much native iPhone app is needed.
* **Acceptance.** A written go or no-go with every blocker named and its source; the owner decides.

## P6-05 — iPhone: the app — Size L
* **Order.** Needs: P6-04 [d].
* **Do.** Only if P6-04 says go: the Flutter iOS target, the platform-channel work the audit found, signing, a CI job on a macOS runner (inside the minutes budget), the journeys of `../07` on two iPhones. CarPlay only if asked.
* **Acceptance.** The core journeys (connect, search, play, like, playlists, download, offline, sign out) pass on two iPhones; screenshots in the PR.

## P6-06 — iPhone: how people install it from GitHub (sideloading) — Size S
* **Order.** Needs: P6-05 [d], P5-06 [p]. Why: the install route is only known after the app exists, and the first public release is what puts its files on GitHub.
* **Decided (owner, 2026-11-04, D-56).** No App Store and no TestFlight: this task replaces "TestFlight and the App Store".
* **Do.** Put the iPhone build on the GitHub Release in the form the route chosen at P6-04 needs, and write the install guide for it (what a person must install, how often it must be re-signed, what to do when it stops opening). The guide is honest about the limits.
* **Acceptance.** A non-technical person installs the iPhone build from the guide on a clean iPhone and plays a song; the guide states the re-signing limit in plain words.

## P6-07 — Casting to speakers that are not Encore devices — Size M
* **Order.** Needs: none.
* **Status.** Not scheduled: an owner decision. Encore's own devices are in v1 (P4-07).

## P6-08 — Tablet design: the drawings for the tablet — Size S
* **Order.** Needs: P6-01 [d].
* **Decided (owner, 2026-11-04, D-58): later.** The tablet comes after Android and the browser are complete.
* **Do (when it is time).** Draw the tablet layouts (both orientations, split screen) on top of the browser drawings of P6-01; the planning agent draws, the owner approves before any code (D-43).
* **Acceptance.** The owner approves the drawings; every browser screen has its tablet counterpart or a written "scales as it is".
* **Size.** S.
