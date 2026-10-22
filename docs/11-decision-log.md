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

---

## Decisions of 2026-10-22 (implementation phase; owner: "write down every decision and why")

### ADR-R19 — Start the installer now, as a narrow slice (the stronger model's call; the owner delegated it)
* **Context.** The owner wants to install Encore himself, as a user would, on a fresh VM first and on his real Proxmox server later. The
  installer is hours to days of work; other improvements (lyrics sources, the Spotify gap list, the build-tool upgrade) were open too.
* **Options.** Fix the small open items first and build the installer later; build the whole of P3 (wizard, admin pages, backups,
  rollback, arm64) now; **build only the part that gets a working server onto a machine now, and leave the rest**.
* **Decision.** The narrow slice: image, compose file, `install.sh`, the `encore` command, the first-run account step, a proof on a clean
  VM. The other items wait until after the owner has installed.
* **Why.** Away-from-home use, friends joining and the 5-day trial all wait on an installable server: it is the critical path. The open
  items do not block the owner. The whole of P3 would delay the handover by weeks; the slice can be proven in a day.
* **Consequences.** The wizard, admin pages, updates with rollback, backups, the security matrix and arm64 stay open (listed in the
  PR). The guide tells the owner plainly that this is an install test, not the daily-driver release.

### ADR-R20 — The first slice asks its questions in the terminal, not in the browser wizard
* **Context.** `15` describes a nine-page browser wizard drawn on paper and not yet approved as drawings.
* **Options.** Build the wizard first (large, needs the owner's OK of the drawings); no questions at all (a generated owner password
  printed once); **terminal questions: owner name, password (hidden, asked twice), music folder, server name**.
* **Why.** It gives the owner a real first install now; the wizard can replace the questions later without changing what the install
  does; a generated password printed in a terminal is worse than one the person chose.
* **Consequences.** The terminal is the only interface of this slice; unattended runs use `--yes`, `--owner` and
  `ENCORE_OWNER_PASSWORD`. Passwords never appear on a command line (they travel on standard input from a file only root can read).

### ADR-R21 — The installation files travel inside the server image
* **Context.** The installer must put a compose file and the `encore` command on the machine, and `encore update` must replace them
  together with the server so they never disagree.
* **Options.** Download them from the repository at install time (needs the repository to be reachable, and the right ref); embed them in
  one long `install.sh` (drifts from the compose file in the repository); **put them in the image (`/app/deploy`) and extract them with
  `docker run --entrypoint cat`**.
* **Why.** The image is already being downloaded; what runs is exactly what that version was tested with; one source of truth.
* **Consequences.** The deployment files live in `server/encore_server/deploy/` (inside the Docker build context) and not in a top-level
  `server/deploy/` as `05` sketched. Changing them means publishing a new image.

### ADR-R22 — The first install pulls the private image with the owner's GitHub login
* **Context.** The repository and the image are private until the full feature set is done (`05`); a fresh machine cannot download
  from them anonymously. Owner, 2026-10-22: "I'll login, it's my GitHub account."
* **Options.** Make the image (and a tiny installer repository) public now; copy the files and build the image on the machine (about ten
  extra minutes, not what a user does); make the whole repository public; **keep everything private and sign in with GitHub**.
* **Decision.** The installer is fetched with `gh api` after `gh auth login --scopes read:packages`; it signs Docker in to `ghcr.io` with
  that token (`GH_TOKEN`, or `gh auth token`, or a pasted token) when the first pull is refused.
* **Why.** Nothing becomes public before the owner decides; the owner already has the account; the same installer will later skip the
  sign-in when the image is public (the first pull simply succeeds).
* **Consequences.** The token's login stays in root's Docker configuration on that machine (acceptable for a test machine, noted in the
  guide). `encore update` needs the same sign-in.

### ADR-R23 — Where the installer runs, and how Docker gets there
* **Options.** Support every Linux; support Ubuntu and Debian only; install Docker from the distribution's older package; **Docker's
  own script (`get.docker.com`, which sets up Docker's apt repository), after asking**, on 64-bit Intel/AMD Ubuntu or Debian.
* **Why.** One tested path beats five untested ones; Docker's own repository is the version the compose file was tested with; asking
  first respects a machine that is not the installer's. arm64 under emulation in GitHub's runners is slow and eats the private
  repository's free minutes, so it comes later (a build matrix entry).
* **Consequences.** Other systems get a sentence that says so and nothing is changed.

### ADR-R24 — The owner is the first person; the installer makes a hidden music-server administrator
* **Context.** The Encore server signs people in through the music server's accounts and makes accounts for invited friends with the
  music server's account API, which needs an administrator.
* **Options.** Make the owner the music server's administrator (the owner's password then sits in the server's settings file and the
  owner could break the library by accident); **a separate administrator `encore-admin` with a generated password that only the
  install's `.env` knows, and the owner as an ordinary account (the first person to sign in on a server is its owner)**.
* **Why.** Matches `15` (an administrator "made behind the scenes with a generated password that nobody types"); a leaked server
  settings file does not give away the owner's own password; the owner's account can be reset like anyone's.
* **Consequences.** The name `encore-admin` is reserved. The first-run step is a command inside the server (`python -m encore_server
  setup`), so it reuses the tested account code instead of shell and `curl`; running it twice changes nothing.

### ADR-R25 — Away from home: the Tailscale already on the machine, and never replace what is there
* **Context.** `13` and ADR-083: Funnel is the guided way in. The owner also said (2026-10-22): someone who already has Tailscale,
  Plex and a music server must be able to try Encore without reinstalling anything.
* **Options.** A Tailscale sidecar container per install (a second node on the tailnet, needs an auth key); a reverse proxy and a
  domain (not free, not simple); **`encore funnel on` uses the machine's own Tailscale (offering to install it if absent) and picks the
  next free public https port instead of replacing a handler that is already there**.
* **Why.** No second node, no secrets in the compose file, and an existing Tailscale or `serve` setup is left as it was.
* **Consequences.** Written, not yet proven end to end: it needs the owner's Tailscale sign-in; the guide says so.

### ADR-R26 — Uninstall never touches the music
* **Options.** Remove the music folder with the install; ask each time; **`encore uninstall` keeps Encore's data, `--everything`
  removes Encore's own data too, and neither ever deletes anything inside the music folder (including the songs Encore kept in
  `Encore/`)**, with a typed confirmation and a refusal to delete an odd path.
* **Why.** A person's music is not the installer's to delete; kept songs are copies of what the person saved and may be all they have.

### ADR-R27 — The live channel: a device sign-in, pushes, and a slow safety net
* **Context.** Phones asked for changes every 3 s (worst case 7.4 s). The server already pushed `library.changed` on `/encore/live`.
* **Options.** Poll faster (battery, load); Firebase push (needs Google services, against "no cloud"); **a websocket per running app,
  authenticated with a device token, the old check kept as a 60 s safety net**.
* **Decision details.** The app signs in once as a device (token in secure storage, reused until the server refuses it, so the person's
  device list does not grow with every start); reconnect with a jittered pause (1 to 30 s); closed in the background; a push that
  arrives while a probe is working asks again right after it.
* **Why.** Measured on two emulators: 2.4 to 2.6 s from the tap on one phone to the other (an upper bound), also after a server
  restart; events never carry the truth, so a lost one costs at most a minute.

### ADR-R28 — An invitation link uses the address a friend can reach
* **Options.** Always the address in use; a setting the owner must fill; **the server's https address when it has one, else the one in
  use with a warning that it works only at home**.
* **Why.** A link with `http://192.168.x.x` cannot be opened by a friend away from home, and nobody notices until it is sent. "https"
  counts as reachable (a certificate means it was set up for the outside, as Funnel is); plain http to a home or Tailscale address does not.

### ADR-R29 — Search finds an artist's own song through the artist
* **Context.** "Beach House Space Song" returned covers and look-alike titles; Beach House's own song was not in the catalogue's first
  11 results (it is that artist's most popular song).
* **Options.** Ask the catalogue for more results (it ranks by title text, so the song is not there); trust the catalogue's advanced
  syntax (`artist:"..." track:"..."`: returned nothing); **read the typed words as artist and title in every sensible way, look the artist
  up by name, and search its popular songs for the title**.
* **Guards.** Only when no result is already a song by an artist at one end of the query; at least three words; the artist needs
  1,000 fans (so "Space" the word is not a band); every title word must be found; look-ups are remembered (answers ten minutes,
  "nothing" half a minute) so typing a long query does not repeat requests.

### ADR-R30 — One artist page for every artist
* **Context.** Owner, 2026-10-22: songs and albums were mixed, no Popular section; "Spotify does this much better".
* **Decision.** Popular (five, then "Show more"), Albums, Singles and EPs, Compilations, for artists the library has and for ones it
  does not; an album the person owns that the catalogue does not list stays on the page; offline the page is the library's own albums.
* **Why.** The better layout already existed for artists the library lacked; two layouts for the same artist depending on how you
  arrived was the bug. Play on the page plays the popular songs, as everywhere else.

### ADR-R31 — Screen pictures are kept per operating system
* **Context.** The first run on GitHub failed 12 picture tests that passed on Windows (text is drawn a few pixels apart).
* **Options.** Tolerate a few percent difference (hides real changes); run those tests only locally (they would not guard `main`);
  **one set per system, the Linux set drawn by a workflow and looked at before it is committed**.

### ADR-R32 — Changes to the owner's homelab are logged outside the repository
* **Decision.** Every change to the owner's Proxmox host or containers is written in `local/homelab-changes-<date>.md` with the backup
  and the undo. Bandwidth was freed on request (2026-10-22); the number of look-ups at YouTube is **not** a bandwidth matter and stays
  limited (about ten per test run, spaced).
* **Why.** The homelab is the owner's separate project; the repository will be public and must not describe it.

### ADR-R33 — A real outside user from now on: what that makes urgent (owner, 2026-10-22)
* **Context.** A friend will use Encore as his main music app on the owner's server. He has no server of his own, is never in the owner's
  home, and will report what breaks and what he dislikes. The owner uses the same server at work, in the car and at home, at the same time.
* **Options.** Carry on in the planned order (the full feature set first); give him a copy of the test install with no promises; **move a
  small set of "a second person depends on this" items ahead of the rest** (chosen).
* **Decision.** Ahead of other P3/P4 work, as task P3-12: the public address proven end to end; a nightly backup of the Encore data with a
  restore that has been tried; (an in-app "Report a problem" was planned and then put on hold, R35); a friend's guide; a look at what two daily
  users do to the one home address that YouTube sees. The wizard, admin pages and the rest of P3 stay later.
* **Why.** His playlists and likes live only in the server's database (today only the music server keeps its own nightly copy); he cannot reach a
  home-network address; a person who is not technical will not find a developer screen; and one refused address (YouTube) stops both people.
* **Consequences.** The 5-day own-testing rule applies before he starts. The owner's privacy promise stays: the owner sees who is on the server,
  never what anybody listens to.

### ADR-R34 — Which server the first friend uses, and when (decided by the stronger model, the owner delegated it)
* **Context.** The owner will install Encore himself on a fresh VM first and later on his real Proxmox server (ADR-R19, R22); a friend will use
  the owner's server daily from outside (ADR-R33). Open: which machine, and from when.
* **Options.** The dev VM (redeployed all the time); the VM the installer was proven on, handed over as it is; the real Proxmox server (not
  installed yet, "all a mess"); **a VM of its own, installed by the owner from the guide, which then is never rolled back or used for tests**.
* **Decision.** The test VM `encore-ubuntu-test`-style VM 107 is cleaned one last time after the last proof run and becomes the owner's:
  autostart on, a fixed address, renamed `encore-home`. The friend starts on **that** server once these gates hold, in order: (1) the owner
  installed it himself from the guide and uses it; (2) `encore funnel on` works there and an invitation opens on a phone on mobile data (the
  Tailscale machine name is chosen now and kept when the owner later moves to the real server, so the friend's address never changes);
  (3) his data can come back: a nightly Proxmox backup of the VM now, then `encore backup`/`restore` with a restore tried on a throwaway VM
  (the later move to the real server is the same restore); (4) the friend's guide (the in-app "Report a problem" is on hold, R35: he messages the owner); (5) five days of the
  owner's own use. Not a fixed date.
* **Why.** A server a person depends on must not be the one that is rolled back, redeployed and tested; a VM of its own is a smaller change
  than moving the friend later, and the move to the real server becomes a rehearsed restore instead of a surprise. Gates are things that can
  be checked; a date is not.
* **Consequences.** Future installer proofs use a separate throwaway VM (the host has little memory to spare). While the friend's data is on
  it: no rollbacks, no `uninstall --everything`, no test runs, updates only after telling the owner. Every server on the home address spends
  the same YouTube budget: YouTube is switched off on the dev VM except during a test run.


### ADR-R35 — How a person tells us what went wrong (the in-app report) — ON HOLD
* **Status.** **On hold since 2026-10-22, not shipped.** Owner: "if my friend can just message me about it, what is the point?" The first friend has
  the owner's number, so a screen that opens a share sheet adds nothing for him; it would only earn its place if it worked for every user of
  every server, which is a different feature (a message to the server owner, P4-13). The finished code and its 9 tests are kept on the branch
  `parked/in-app-report`; the app's shipping code does not contain it. The friend sends the owner the text of Settings > About & credits >
  Diagnostics > Copy report when a problem needs details (that screen already exists).
* **Context.** The first outside user will report bugs and dislikes (ADR-R33). He has no way to reach the owner from inside the app, and the
  owner promised not to see what anybody listens to (R33).
* **Options.** A "send" button that posts to a server endpoint (needs an address, an inbox and a store of reports on the owner's server, and the
  reports would reach the owner without the friend deciding each time); an e-mail address built into the app (a fixed address, only works with a
  mail app); **the phone's own share sheet with the text prepared** (Messages, WhatsApp, e-mail: whatever the friend already uses).
* **Decision.** The share sheet. Settings > Help & about > "Report a problem or idea": the person's words, a switch for the technical details
  (on by default; the switch says in plain words what goes with it: phone, app version, server name, the song that was playing, the last few
  lines of what the app did, no passwords), server addresses replaced by `<address>` in the details, and the message copied if the phone has no
  share sheet. It lives under the renamed group "Help & about" so Settings keeps its nine groups (docs/06).
* **Why.** Nothing leaves the phone unless the person taps a share target he chose; no new server code, account or address; it works the same
  for every server (the friend's, the owner's, a stranger's), which a built-in inbox would not. The song that was playing stays in by default
  because bugs are nearly always about one song (lyrics, wrong match); it is named on the switch, so it is a visible choice.
* **Consequences.** Reports arrive wherever the friend sends them, not in one place; a "my reports" list on the server stays a later idea
  (P4). Addresses are removed by pattern, so an address written in an odd form could slip through: the person still reads the text in the chat or e-mail before
  sending it.

### ADR-R36 — How somebody the owner does not know reports a problem
* **Context.** The first friend messages the owner directly (R33, R35). Once the repository is public, strangers will install Encore, run their own
  servers and meet bugs. The owner asked how a stranger could tell him, and whether it should be e-mail.
* **Options.** A public e-mail address (spam, and the owner's address is published for ever); a server endpoint in Encore (the owner would run an
  inbox for other people's servers, and a stranger's app has no server of his to send to); a chat or forum (one more place to watch); **GitHub
  Issues** (the stranger needs a free GitHub account; the owner is e-mailed about every new issue by GitHub's default notifications; issues have
  forms, labels and a history; the project already has bug and feature forms and `SECURITY.md`).
* **Decision.** Two kinds of report, two places. A person on **somebody's server** reports to that server's owner (today by messaging him; an in-app
  message to the owner is the idea in P4-13): it is that owner's server and data, and only he can look at it. A bug in **Encore itself** is a GitHub issue; vulnerabilities go
  through GitHub's private reporting (`SECURITY.md`). No published e-mail address. The issue form asks for the technical details that Diagnostics > Copy
  report produces; a line in the app pointing at the issue page waits for the in-app report (R35, on hold) and for the repository to be public (P5-06).
* **Why.** It costs nothing, notifies the owner without any new service, keeps reports structured and public (one report helps every later
  reader), and keeps the owner's inbox private. Strangers without a GitHub account can still reach their own server's owner; they only cannot
  reach the project, which is acceptable for a free project.
* **Consequences.** Nothing to build before the repository goes public. At P5-06: Issues on, notification e-mail checked, private vulnerability
  reporting on. Reports that contain a stranger's server details are theirs to redact; the app already removes addresses.
