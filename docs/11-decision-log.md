# 11 — Decision log (the reset decisions, ADR-R1 …)

Format: Context → Options → Decision → Why it beats the others → Consequences → Revisit when. In the new repository each becomes
`docs/adr/00NN-*.md`. The 109 old ADRs (`old docs/03`) are history; where one is reversed, it is named.

---

### ADR-R1 — A fresh repository; nothing from the old project
* **Context.** Old repo: passwords in history (on GitHub), 50 APKs (238 MB), the upstream project's 900+ commits, tags, name, icon, licence; owner:
  "drop anything related to [the old project]".
* **Options.** Clean in place; rewrite history with `git filter-repo`; **new repository from a cleaned tree**.
* **Decision.** New repository `encore`, one initial commit, layout of `05` §2; old repo archived as `old-repo`, deleted on the
  owner's go after password rotation.
* **Why.** Only a new history guarantees no secrets/binaries/upstream history; rewriting is error-prone; cleaning in place keeps all three.
* **Consequences.** Line history of 5 days lives only in the archive/bundle. Must check no upstream-derived file remains (icon, Android
  files, vendored plugin) before dropping the credit.
* **Revisit when.** Never.

### ADR-R2 — YouTube stays as a contained source; no Google accounts; no bulk dependence
* **Context.** `02` Q1, Q5. Free + plays anything requires YouTube; it is fragile, per-address limited, terms-breaking.
* **Options.** YouTube as core (today); YouTube as a contained module; Soulseek/torrents; paid-service ripping; no catalogue.
* **Decision.** A `sources/youtube` module behind an interface, paced and backing off, no account sign-in, an honest notice and a
  switch; the product must work without it.
* **Why.** The only option meeting "free" and "plays anything" while protecting the Host.
* **Revisit when.** YouTube blocks server-side resolution broadly (then X-3 on-device fallback), or a free licensed catalogue appears.
* **Reverses** ADR-103's account sign-in direction and the admin Google sign-in (`old docs/50`).

### ADR-R3 — One Encore server program, one port
* **Context.** Seven programs, six ports, duplicated clients and auth (C1, C2).
* **Options.** Keep services; one program with modules (**chosen**); move into Navidrome plugins (impossible: no custom HTTP
  endpoints in Navidrome 0.60+ plugins).
* **Why.** One owner, one machine: simplicity, one auth, transactions across modules, one update.
* **Consequences.** Existing Python code is moved into modules; the Dart hub returns later as module `jam` (or stays a sidecar if
  porting costs more than it saves).
* **Reverses** ADR-087's separate people service, ADR-094's per-service routes, ADR-106's separate admin container.

### ADR-R4 — Songs are references; files are attached; Encore owns each person's library
* **Context.** C3, C11: songs without files cannot be liked or listed; file swaps break likes; resume-anywhere needs state for any song.
* **Options.** Patch Navidrome (today); stub files in the library; **reference model in the Encore server with a one-way mirror to
  Navidrome**; replace Navidrome.
* **Why.** The only model where like/play/import/resume work the same for every song, and a file change never touches a person's
  data; keeps Navidrome for what it is good at.
* **Consequences.** App data layer moves to song refs (P2-02); migration of existing likes/playlists; Tinkerers' edits in other
  Subsonic apps are not read back in v1.
* **Reverses** ADR-093 (pending likes), ADR-102 (instant playlist page), ADR-107's upgrade map, ADR-066 (fetched = in library).

### ADR-R5 — Play is not save is not download
* **Decision.** Playing streams; saving keeps on the server; downloading puts it on the phone; repeated listening (2 different
  days) also keeps (owner D-3, ADR-R14). **Reverses** ADR-066.

### ADR-R6 — YouTube work is single-flight, prioritised, fair and paced
* **Decision.** `04` §5 and §10: one look-up/fetch per video id, priorities play > prepare > match > keep, round-robin per person,
  one shared paced budget with back-off, no bursts. Two worker pools (interactive, background) sized from the machine.
* **Why.** Taps never wait behind imports (measured: shared workers made each look-up 9 s instead of 2 s); one person cannot
  starve another; the Host's address stays safe on any line.

### ADR-R7 — Install: one command + browser wizard; Docker hidden
* **Options.** Docker guide (today); **script + wizard**; flashable OS image; desktop GUI installer; native packages; Windows.
* **Why.** One paste then buttons, any Debian/Ubuntu x86/ARM, updates by one command; an OS image is friendlier but means
  maintaining an operating system (candidate after v1).
* **Reverses** the "Docker is the contract" guide style of ADR-084 (Docker stays the contract *underneath*; Hosts never see it).

### ADR-R8 — Many people at once: four objects, five rules
* **Decision.** `04` §10 (song ref, audio state, fetch session, work item; single flight, reuse, priorities, fair share, shared budget).
* **Why.** Every multi-user case the owner listed is one of these rules instead of a special case.

### ADR-R9 — Playback state and one active device live on the server
* **Context.** Owner 2026-10-21: resume at the exact second on any device, including YouTube songs; one device plays at a time;
  future web/PC client.
* **Options.** Navidrome's `savePlayQueue` (library songs only, no device rule); per-device local state (no cross-device);
  **server `playback` module + live channel with an active-device lease**.
* **Consequences.** The app reports state on pause/seek/track change and every 15 s while playing; takeover over websocket; works
  for any client (web later).

### ADR-R10 — Tests are walks by people on many phones, with evidence
* **Decision.** `07`: device profiles A–E, network and life-cycle conditions, journeys with numbers, real data, a reviewing agent
  that re-runs acceptance criteria. **Supersedes** the "test counts as the gate" practice.

### ADR-R11 — Import copies the list, not the audio
* **Decision.** Import creates refs and the playlist in seconds; matching and keeping run in the background, paced; nobody waits.
* **Why.** Measured: lists read in 2–3.5 s; audio for 200 songs is bounded by YouTube's per-address allowance (hours on a cautious
  pace), which no parallelism fixes safely. **Reverses** ADR-100/101's download-first import.

### ADR-R12 — Spotify without a developer app
* **Decision.** Public link (≤ 100) + data-export file now; on-phone sign-in to Spotify's own page if X-4 passes. Never a Spotify
  developer app (Premium required since Feb 2026) and never a Spotify login on the server.
* **Reverses** ADR-101 item 4 (Spotify OAuth developer app).

### ADR-R13 — Everything in the first version (owner, 2026-10-21)
* **Context.** The reset plan proposed hiding Jam, friend activity, recommendations and the quality tier until after v1.
* **Decision (owner).** "Everything will be in the first version even if it means delaying the release by months." They are built in
  phase P4 on the new design, after the core (P1–P3); the public release becomes P5.
* **Consequences.** Longer road to the first public version; each feature is rebuilt on song refs and the live channel instead of the
  old wrappers (C8), which removes the upgrade map and the Jam-wraps-every-play problem.

### ADR-R14 — One copy per song; keep on save, download or repeated listening (owner, 2026-10-21)
* **Decision (owner).** A song is stored once for everybody ("HDD space is expensive"); playlists, likes, history and the
  recommendation profile are per person. The server keeps a song when it is saved, downloaded, or played on 2 different days
  ("today and tomorrow and the day after, we need to keep it"); the threshold is a setting.
* **Why it beats the alternatives.** Keeping on every play fills the disk with songs tried once; keeping only on explicit saves loses
  songs people clearly love but never liked.

### ADR-R15 — One volume per device; Encore Connect goes through the server
* **Context.** `13` sections 1–2: a hidden internal volume made the app "not in sync with the phone"; the owner wants to control the
  tablet's playback and volume from the phone.
* **Options.** Keep internal volume + add an in-app slider; device-to-device control on the LAN (mDNS); **commands through the Encore
  server's live channel, the target applies Android's media volume**.
* **Why.** One volume the person already knows; the same path works at home and away, through NAT and Funnel, with one authority for
  ordering and the active-device lease; LAN-only control would fail exactly when away from home.
* **Consequences.** Devices must be running to be commanded (H1): an "available" window and an opt-in "Always ready to play".

### ADR-R16 — Encore-to-Encore federation, minimal
* **Context.** Friends on other servers; Jams with songs from either server or neither (`13` sections 4–5).
* **Options.** Invite everyone as guests on one server (no shared Jams with their own music); a central Encore relay (a project-run
  service: against "no cloud", cost, legal); full ActivityPub; **a small Encore-only protocol: server keys, signed requests, friend
  links, Jam guest passes, per-song Jam stream grants**.
* **Why.** Enough for the owner's cases, no central service, nothing shared beyond what a feature needs at that moment.
* **Consequences.** Needs public addresses on both sides; a Host switch to turn it off; versioned (`/.well-known/encore` apiVersion).

### ADR-R17 — One account per person; home servers talk to each other
* **Context.** Owner 2026-10-21: two accounts in one app is "stupid and lazy"; no inviting people onto my server just to Jam.
* **Options.** Several accounts in one app; inviting guests as members; phones connecting to other servers with passes;
  phone-to-phone; a central Encore service; Matrix; **home servers acting for their people** (chosen).
* **Why.** One account, one login, one library; the app talks to one server; the other server never sees the phone; nothing central.
* **Consequences.** The Encore server gains a relay layer (P4-08); cross-server needs public addresses on both sides; people with no
  Encore server at all can only join as a Jam-only guest seat (D-15).

### ADR-R18 — Setup order and visual direction (owner delegated: "it's your decision")
* **Setup order.** "Away from home" (page 6) comes before "Friends on other servers" (page 7) because federation needs a public
  address; if page 6 is skipped, page 7's choice is saved and takes effect when away-from-home is switched on.
* **Visual direction.** "The music is the art" (covers, mosaics, colour from artwork, meaningful motion) plus ~12 licence-checked
  illustrations; **no mascot**. Options: a mascot/brand character (tied to the undecided name, expensive to change), illustrated
  themes everywhere (generic, heavy), plain UI (lifeless). Covers make Encore personal at no cost; illustrations are cheap to redo
  when the name and logo arrive (P5-05).
