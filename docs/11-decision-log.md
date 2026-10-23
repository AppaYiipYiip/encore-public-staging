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
  the same YouTube budget. *Amended 2026-10-23:* the dev server is left switched on (it only asks YouTube when somebody plays or imports on it, and
  nobody does between test runs); every test run still keeps to 10 look-ups, and the real use is on the owner's server.


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

### ADR-R37 — How Encore backs itself up, and what a restore puts back
* **Context.** A friend will depend on the owner's server (R33, R34). Everything a person cannot recreate lives in two SQLite databases: the Encore
  server's (accounts, devices, playlists, likes, saved items, imports, the key it signs addresses with) and the music server's (its accounts and
  their playlists, play counts). The music itself is the owner's own folder.
* **Options.** (a) Only the hypervisor's whole-machine backup (Proxmox `daily-ssd`): exists already, but is the owner's setup, restores a whole
  machine to a past state, and does not exist for anybody on a plain computer. (b) The music server's own nightly copy (`ND_BACKUP_*`, already
  switched on): covers only its half. (c) Copying the database files with `cp`/`tar` while the servers run: can catch a file mid-write. (d) Stopping
  both servers for a minute every night and copying: always consistent, but a nightly outage. (e) **SQLite's online backup, run by a throwaway
  container of the Encore image, one run per database, each as the account that owns the database**, then packed with the settings file.
* **Decision.** (e), plus (a) and (b) left as they are (they are different layers). `encore backup` writes `encore-backup-<time>.tar.gz` into
  `/opt/encore/backups` (mode 700, files 600; the folder can be changed with `ENCORE_BACKUP_DIR` in `.env`, e.g. to another disk), keeping the newest 7. It
  holds the two databases (each a single file, checked with SQLite's integrity check), `manifest.txt` and a copy of `.env`, because `.env` holds the
  music server administrator's login that the copied music-server database needs, and without it a restore on a new computer could not get back in.
  A systemd timer runs it every night about 03:30 (after the music server's own 03:00 copy; up to ten minutes later by chance), and the installer
  switches it on and makes the first one at once; `encore autobackup off` is remembered across re-installs. `encore restore FILE` checks the file,
  asks, stops the servers, **sets the current files aside** in `before-restore-<time>/` (never deletes them), puts the two databases back with the
  owner of the files they replace, takes only the administrator login from the archived settings (the port, the music folder and the name belong to
  the computer it is restored on), starts again and waits until it answers.
* **Why.** It is the only option that is consistent, needs no outage, works the same on any computer with Docker, and is built from the image the
  installer already put there (nothing more to install). The copy runs as the owner of each database because a root-owned `-wal` or `-shm` file
  left next to a live database would stop the server writing to it. Each copy is converted to one self-contained file because the first run of this
  proved otherwise: the archive held `-wal` and `-shm` files that are lost when only the database file is put back.
* **Consequences.** The archive holds a login: it is private, and the guide says so. **The music is not in it**, nor the songs Encore kept in
  `Encore/` inside the music folder: moving to another computer means moving that folder too, or playlist entries pointing at kept songs break.
  `encore uninstall --everything` removes the backups with the rest (said in its question). A restore needs the same Encore version or a newer one
  (`encore update` first). Not covered yet: a second copy off the computer (a different disk or a cloud folder), which is the owner's choice
  (ADR-077); the hypervisor's backup is that today.

### ADR-R38 — Clients are thin: every call to an outside service goes through the server (owner, 2026-10-23)
* **Context.** The owner asked where a song that is not on the server is fetched from, the phone or the server, and whether a web version would break it ("a browser cannot
  fetch it, it needs to be the server; always future-proof the engineering"). **The audio already comes from the server** (ADR-R2, `02` Q2): the app asks the server to resolve
  a song to a ref and plays the server's own stream (`EncoreInstantBackend`); YouTube, yt-dlp and the playlist readers (YouTube Music, Spotify) run only on the server. **But the phone
  still calls some outside services itself** (table below). A browser only talks to services that allow it (same-origin rules), so a web client could not do those calls; each call also
  shows the person's own internet address to that service, and a change in the service needs an app update on every client instead of one server update.
* **Options.** (a) Each client talks to outside services itself where it can (fastest to write; breaks for a browser, repeats the logic per client, spreads every person's address).
  (b) The server for audio, the clients for metadata (today's mix). (c) **The server is the only thing a client talks to; the server talks to the outside.**
* **Decision.** (c), as the rule for every new feature and the end state for the old ones:
  1. A client (the Android app, later web, desktop, iOS, a TV) talks only to its own Encore server. Search, the catalogue, covers, previews, lyrics, new-release checks, import reading
     and matching go through the server's API.
  2. Anything a media element fetches by itself (a stream, a cover, a preview, a download) must work **without custom headers**: a short-lived signed address. Built for streams
     (`GET /refs/{id}/stream-url`, signature checked on `/encore/stream/{id}`, `17` §1); to be built the same way for previews and covers.
  3. A client may have a **native-only shortcut** (X-3 on-device extraction, X-5 direct download at home) when it measurably helps, but the server's route stays complete and nothing in
     the client may depend on the shortcut being there.
  4. A feature that cannot go through the server needs its own ADR saying why, and what the web client does instead.
* **Why.** One place to fix when YouTube, Deezer or LRCLIB change (the server image); one cache shared by everybody on the server; one place where pacing and privacy are enforced
  (`04` §5, §10); thin clients are small, testable and portable; a web client (P6) becomes a new front end, not a rewrite of the data layer. Cost: server work for each call moved,
  one more hop, and the server must cache.
* **Where the phone still calls the outside itself (checked in the code on 2026-10-23), and what removes it.**

  | Call | Where | Goes away with |
  |------|-------|----------------|
  | Catalogue search, artist and album pages (Deezer) | `app/lib/data/catalogue/deezer_client.dart` | P2-12 (the catalogue module on the server) |
  | 30-second previews: the phone plays Deezer's file | `PreviewTrack.uri` in `features/catalogue/catalogue_widgets.dart` | P2-12 (a signed preview address from the server) |
  | New-release alerts in the background (Deezer) | `app/background_sync.dart` → `AlertsService` | P2-12, then the alert check on the server (`23` §4, notifications without push: P2-15) |
  | Lyrics (LRCLIB) | `app/lib/data/api/lrclib_client.dart` | P2-14 (lyrics on the server) |
  | Cover pictures by an outside address (Deezer covers, an import's source picture) | `CachedNetworkImage` in `features/common/cover_art.dart` | Covers served by the server (the cover finder already stores `cover.jpg`); **whether Flutter web can load outside pictures is unchecked: check when the web client starts** |

* **Consequences.** P6 "Web/desktop client" now lists these as prerequisites. The audio path needs no change for a browser (the server streams with Range support and signed
  addresses). Platform parts of the app (files, the phone's database, secure storage, background work) will need web versions behind interfaces: not examined yet. An
  architecture-test ratchet (2026-10-23) counts outside addresses written into `app/lib` (today two clients, goal zero), so the rule is enforced and not only written (`30` section 5);
  it cannot see an address that arrives in data, such as a cover URL.
* **Revisit when.** An outside service offers browser-safe access that is faster than a hop through the server **and** the owner accepts the privacy cost; or when the server
  cannot afford the extra traffic on a small machine (X-8).

### ADR-R39 — How a running server gets a newer yt-dlp by itself (P3-08, first slice) — DECIDED, built, run for real on the dev VM 2026-10-23 (`evidence/c04`)
* **Context.** The image carries the yt-dlp that was newest when it was built (not pinned; rebuilt weekly since PR #7). A server only gets it when `encore update` is run on it.
  YouTube changes often, and when it does, every song the server does not already have stops playing until someone runs that command (`30` §J, STATUS risk 3). `22` §2 designed
  an updater (daily PyPI check, releases older than 24 hours only, hash check, a canary, stay on the old copy on failure) and nothing of it exists. Facts that shape the choice, all read in
  the code on 2026-10-23:
  * **yt-dlp is used in three ways, not one.** In the server's own process (`sources/youtube/lean.py`, two `import yt_dlp` sites; one cached `YoutubeDL` per worker thread and client kind, and the
    code catches `yt_dlp.utils.DownloadError` by class). As a **command** (`imports/readers.py` `ytdlp_reader`, `argv = ["yt-dlp", "--flat-playlist", …]`, chosen by `shutil.which("yt-dlp")` in
    `imports/service.py`), the fallback that reads a playlist when YouTube Music's interface cannot; a command ignores whatever the server puts on `sys.path`. And a presence check
    (`api.py` `find_spec("yt_dlp")`).
  * The container is started by `entrypoint.sh` and restarted by Docker (`restart: unless-stopped`); `/data` is writable by the server's user and is **not** in the backups (they copy the named
    databases only, `backup.py`), so a restore on a new computer starts from the image's copy.
  * yt-dlp's wheel is pure Python with no required dependencies and **imports straight from the downloaded `.whl` file with no pip** (tried 2026-10-23, Python 3.13 on Windows: PyPI's sha256 matched,
    `YoutubeDL` constructed). GitHub's `SHA2-256SUMS` for the same release lists the zipapp and the sdist but **not the wheel**, so it cannot be a second check of what is downloaded.
  * A YouTube look-up has a shared budget (`Rest`, `Pacer`, the per-day counter); a child process has none of these. The server is one program that clients reconnect to by themselves (`evidence/b01`).
* **Options.**
  (a) **Swap in place**: load the new version into the running process (new `sys.path` entry, purge `yt_dlp*` from `sys.modules`, drop every thread's cached extractor). No restart,
  but the `except yt_dlp.utils.DownloadError` clauses would hold the *old* class after a swap and stop matching, a thread can be half-way through an extraction, the command in `readers.py` is not
  reached at all, and the module state of two versions can mix: a bug that shows up only on the day of an update, when it matters most.
  (b) **Prepare beside, check in a separate process, switch at the next start**: download the wheel into `/data/tools/yt-dlp/`, verify, run the **canary in a child process** whose import path
  starts with the new wheel (the running server is untouched), and only on a pass write the pointer. The server puts the pointer's wheel first on `sys.path` at start (before anything imports
  yt_dlp) and **restarts itself once nothing is going through it**; Docker starts it again. The old wheel stays, so a bad pointer returns to it by deleting one file.
  (c) **A warm child process per version** that speaks to the server over a pipe (what `04` §4 calls the warm worker): switching is starting a new child and draining the old one, with no restart of
  the server. The cleanest, but it replaces the extraction calls in `lean.py` and `stream.py` and their error handling: a task of its own, and a bigger change than the problem needs today.
  (d) **Keep `encore update` as the only route** (today). Zero code, and the friend's songs depend on the owner noticing.
* **Decision (proposed).** (b) now; (c) when the extraction moves out of process for its own reasons; never (a).
  1. **One way to run yt-dlp.** Every use follows the pointer. The playlist fallback stops calling the `yt-dlp` command and runs `[sys.executable, "-m", "yt_dlp", …]` with the pointer's wheel in
     `PYTHONPATH`; its availability check becomes `find_spec`. A test fails if an argv beginning with `"yt-dlp"` comes back.
  2. **Where from.** PyPI's JSON for `yt-dlp` (the server calling an outside service is the rule, ADR-R38), once a day at a random time; the wheel's URL and `sha256` come from that answer and the
     downloaded file must match. Only a release **older than 24 hours** is considered (a broken or hostile release is usually pulled within a day). Only a version **newer than the image's own**
     is used: the image's version is read with `importlib.metadata` (nothing is imported) and versions compare as integer tuples; copies older than the image's are deleted after an `encore update`.
  3. **The canary tests the path that plays songs.** The child imports the server's own `InProcessExtractor` with the same format selector, the same fast client list (`visionos` first) and the same
     `music.youtube.com/watch?v=` address, with a **temporary cache folder of its own**, on one fixed, long-lived video that is not music (Blender Foundation's open film "Big Buck Bunny", `aqz-KE-bpKQ`; the first choice, YouTube's first upload, answered "This video is unavailable" on this path in the first real run), then reads the first
     64 KB of the audio. If the candidate fails, the **running** copy runs the same canary, so "YouTube broke" and "the new release is bad" are told apart: only when the running copy passes is the release marked bad for good; when it fails too, YouTube is the problem and the release stays eligible (it may be the fix). Before the real run, the video is checked to
     satisfy the selector through this path (an old upload may not offer the audio format wanted); if it does not, another fixed video is chosen, not the selector loosened.
  4. **The canary is a look-up like any other, and the child cannot count it.** The **parent** waits for the `Pacer` and checks `Rest` before starting the child (resting: no check, no update), records
     the look-up in the per-day counter afterwards, and feeds a refusal into `Rest.blocked()`. At most **four** canary runs a day (a healthy day uses none or one; a day on which the candidate fails uses two, the candidate and then the running copy, and may retry once).
  5. **Switching.** On a pass: write the wheel's sha256 next to it, then the pointer (temp file, rename), keep the previous wheel, log `yt-dlp 2026.10.21 -> 2026.11.02`. The restart waits until
     **nothing is going through the server**: no stream of any kind (YouTube songs, owned songs proxied by the gateway, a playlist download), no import, no keep, for 60 s. **It waits as long as it
     takes and never forces**: the owner's rule is not to update while somebody is likely to be listening without saying so (P3-12). The log says "a newer yt-dlp is ready, waiting for a quiet
     moment" and `/encore/api/v1/info` says which version is running and which is waiting.
  6. **The loader never fails the start.** At start it re-checks the stored sha256; a pointer to a missing, partial or mismatching wheel (an interrupted write, a copied folder) logs one line, the
     image's own copy is used and **the pointer is removed**, so that nothing waits for a copy that cannot be used and the next daily check fetches the release again (found in the first real run:
     without this, `/info` kept saying "pending" and the server would have restarted every quiet minute for ever). A second guard for causes nobody thought of: **one restart per version**; a marker
     file (`restarted-for`) is written before the restart, and a server that comes back still pending for the same version logs it and does not restart for it again; staging a version anew
     (after a failed start dropped its pointer) clears the marker, so every staging gets exactly one restart. There is **no crash-loop marker**:
     yt-dlp is imported late, so a bad wheel would not fail the start, and the child canary before the switch is the check that matters.
  7. **When nothing works.** If the running copy fails the canary and no newer release exists, the server says so in the log and in `/info` (`youtube: degraded`) and retries hourly, within the budget of
     point 4; the app can show "songs from YouTube are not working right now" (the admin Home later). No fall-back to an older release: the older one is what broke.
  8. **Off switch.** `ENCORE_AUTO_TOOLS=0` for a Tinkerer who pins versions or has no outside access; the image's own yt-dlp is used as today.
  9. **Scope of this slice.** yt-dlp only. `ytmusicapi` (the search) breaks less often and has dependencies; it follows the same pattern later. Rollback of a whole server update (`encore update`) is another task.
* **Why (b) beats the others.** It never touches the running process until a restart, so there is no half-updated state and no stale exception class; the check happens in a process that can crash
  without taking the server with it; the rollback is "delete one file"; and it needs a pointer file, a loader at start and a child-process canary, so it can be tested without a network (a fake PyPI and a
  fake canary). (c) is better long term and larger now; (d) leaves the friend dependent on a manual step; (a) is the cheapest to write and the most likely to fail on exactly the day it is needed.
* **Costs and risks.** (1) A restart (about 5 s) once the server is quiet; a server that is never quiet never restarts and keeps the old copy (visible in `/info`). (2) The server downloads code from PyPI
  and runs it with access to `/data` and `/music`. yt-dlp already is such code; the new exposure is a hostile release inside the 24 h window, which the delay and the hash only partly cover (the hash comes
  from the same place as the file). A second, independent channel would be GitHub's zipapp checked against its `SHA2-256SUMS`: **open**, not planned. (3) One or two more YouTube look-ups a day from the
  Host's address, counted. (4) A future yt-dlp that needs a new dependency or a JavaScript runtime fails the canary and the server stays on the old copy: safe, but then only a new image helps. (5) The canary
  video could one day be removed: the updater then says "cannot check" and does nothing, the safe side.
* **Tests.** A fake PyPI (`httpx.MockTransport`) and a fake canary: the 24 h rule, a hash mismatch, a candidate that fails and one that passes, the running copy failing too (degraded), the pointer and the
  previous copy, a pointer to a missing or mismatching wheel, `Rest` resting, the pacer and the counter being used by the parent, the idle test (a stream open: no restart), the off switch, an older image
  after `encore update`, the playlist fallback's argv. One real run on the dev VM, last: at most 2 look-ups, the version before and after, the log lines, the restart at idle, a deliberately broken wheel refused.
* **For the owner.** Nothing to decide. It changes nothing a person sees, costs one or two look-ups a day, never restarts the server while something is playing, and can be switched off. When the `encore update`
  that first brings it to VM 107 is announced, it says so.
* **Revisit when.** The extraction moves out of process (then (c)); or YouTube starts treating a fixed canary video as a signal; or a Host reports a restart at a bad moment.

### ADR-R40 — How a person finds and reaches their server without knowing what an address is (owner, 2026-10-23) — DECIDED (the advisor model decided after the research below; nothing is built yet)
* **Context.** The owner, 2026-10-23: *"a non-technical user won't know what an IP address is. In Plex and other media apps the server is detected automatically on the same Wi-Fi. How would it work with several Wi-Fi networks, several music servers?"* and then *"how do Plex and Jellyfin work, can we learn and copy it, should we do it even better?"*
  * **Where we stand (checked in the code and on the emulators, 2026-10-23).**
    * The first screen asks for an address ("For example 192.168.1.10:4533", `evidence/b02`); `15` section 3 (A1) says the opposite (invitation or QR first, manual address under "Other ways to connect") and was never built.
    * The installer's terminal QR encodes only the bare address (`install.sh`); the app cannot scan a QR (no scanner library) but opens a join link from the phone's own camera or messages (`/encore/join/<code>` is an app link). The join stores **one** address (the link's host); the Connect form takes one typed address and an optional second.
    * The app already races several addresses of one server (`EndpointResolver`, staggered 350 ms, again after a network change). **But its probe is a Subsonic `ping` carrying the person's login token, sent to every candidate; requests use the first candidate before any probe has run; and "reachable but rejecting the login" counts as "this is the server".** An address recycled on somebody else's network (a café, a work Wi-Fi) receives the token (md5 of password and salt, guessable offline). **Security finding S2, independent of discovery.**
    * Nothing identifies a server: `/info` has no id, and the app's `serverId` is a local database row number (the same server entered twice is two servers, a changed address is another one).
    * The plan has `encore.local` (mDNS) for the **browser** wizard only (`04`, `15`), nothing for the app, nothing for several networks.
  * **What the others do** (primary sources read 2026-10-23):

    | | How the app finds the server | What it costs / where it breaks |
    |-|------------------------------|---------------------------------|
    | **Plex** | Mainly **the account**: the server sends its private and public address to plex.tv, apps fetch the list ([Plex: Remote Access](https://support.plex.tv/articles/200289506-remote-access/), [Why can't the app find my server](https://support.plex.tv/articles/204604227-why-can-t-the-plex-app-find-or-connect-to-my-plex-media-server/)). Same-network broadcast (GDM, UDP 32410-32414, [ports](https://support.plex.tv/articles/201543147-what-network-ports-do-i-need-to-allow-through-my-firewall/)) is secondary. Away from home: router port forwarding (UPnP/NAT-PMP), else a **Plex-run relay** ([Relay](https://support.plex.tv/articles/216766168-accessing-a-server-through-relay/)) | Needs plex.tv for ever; relay is slow (1 to 2 Mbps); its `plex.direct` secure names are broken by routers that block DNS rebinding (forum reports) |
    | **Jellyfin** | **UDP broadcast** to port 7359 ("Who is JellyfinServer?" answered with JSON: address, id, name), same subnet only ([Jellyfin networking](https://jellyfin.org/docs/general/post-install/networking/)); no account; away from home the person types the server's URL | **Fails behind Docker's bridge network** (broadcast replies are lost; host networking or an iptables workaround is advised: [Jellyfin forum](https://forum.jellyfin.org/t-jellyfin-auto-discovery-on-docker-bridge-network?pid=70564)), which is Encore's deployment; "no local servers found" is the classic complaint ([Swiftfin](https://github.com/jellyfin/Swiftfin/blob/main/Documentation/common_issues.md)) |
    | **Home Assistant** | **mDNS** `_home-assistant._tcp`, TXT with a stable `uuid` ("recognize an instance you have seen before, even when its address changes"), `internal_url`, `external_url`, `version` ([instance discovery](https://contributors.home-assistant.io/core/internals/instance-discovery/)) | Trusts the id; the page gives no way to verify the instance and no rule for choosing between the two URLs |
    | **Syncthing** | Static address, **local discovery** (broadcast), **global discovery servers** run by the project; the device id is **derived from the device's certificate and checked in the TLS handshake**, so a spoofed announcement can only misdirect, never impersonate ([Device IDs](https://docs.syncthing.net/dev/device-ids.html)) | Runs a global discovery service |
    | **Spotify Connect** | mDNS `_spotify-connect._tcp` plus an HTTP `getInfo` / `addUser`: a phone logs a speaker in **without typing a password** (a key exchange) ([ZeroConf API](https://developer.spotify.com/documentation/commercial-hardware/implementation/guides/zeroconf)) | |

    The pattern: everybody that works for ordinary people has **either an account that lists your servers (Plex) or a local advertisement with a stable id (Home Assistant, Jellyfin)**, plus a way to type a URL for the rest. Only Syncthing makes the identity something that **cannot be faked**.
  * **Android.** From target SDK 37 (Android 17) **all** local-network access needs one permission (`ACCESS_LOCAL_NETWORK`): outgoing TCP to a home address, UDP, multicast and `.local` names. Apps targeting 36 or lower get it implicitly, temporarily; the app targets 36 today. `NsdManager`'s system picker (`DiscoveryRequest.FLAG_SHOW_PICKER`) returns addresses that need no permission ([Android: Local network permission](https://developer.android.com/privacy-and-security/local-network-permission), read 2026-10-23; it says nothing about the emulator).
* **Options.**
  (a) **A directory run by the project** (an Encore account lists your servers, Plex style, with a relay). Best experience. Rejected: Encore would own a service, accounts and their privacy duties for ever, a single point of failure, against the premise (free, self-hosted, nothing the maintainers must keep running).
  (b) **A link or QR that carries the server** (invitation, or a one-time pairing link for the owner's own phone). Zero typing, works from anywhere, half built. Alone it does not help "I reinstalled the app at home and have no link".
  (c) **mDNS / DNS-SD `_encore._tcp` advertised by the host** (Home Assistant, Spotify, Chromecast). Standard, zero typing at home, **works with Docker's bridge** because the advertisement comes from the host, not the container.
  (d) **UDP broadcast** (Jellyfin, Plex GDM). Rejected: does not work behind Docker's bridge (above) and needs host networking.
  (e) **A subnet scan.** Costly, slow on large networks, needs the permission; at most a later fallback.
  (f) **`encore.local` resolved by the app.** Still typing; not something to rely on in an Android app (no source found either way: treated as "expected to fail, measure in slice C").
  (g) **A typed address.** Stays, under "Advanced".
* **Decisions** (D1 to D7).
  **D1. The server's identity is a key, from day one.** At first start the server makes an **Ed25519 key pair** and keeps it in its database (a backup restored on a new computer is the same server; this is also the "federation key" of `13`/P4-09, not a second key). `serverId` = a short base32 hash of the public key. `GET /encore/api/v1/info?challenge=<nonce>` (public) returns `serverId`, `publicKey` and a **signature over the nonce and the id**. The app **sends credentials or a token only to an address whose key hashes to the pinned id and whose signature verifies**; **invite and pairing links carry the id**, so even the first contact from a link is verified. Why now and not "an id first, a signature later": once discovery exists, anybody on a café or work Wi-Fi can advertise a copied id; an id-only check hands them the token. Plex, Jellyfin and Home Assistant trust ids or addresses; Syncthing's lesson is that the identity must be the key. **What this proves and what it does not:** it proves *who answers*, not that the path is private; cleartext http on the home network is the known and accepted limit (`21`). **Checked before deciding (2026-10-23):** Python `cryptography` is `Apache-2.0 OR BSD-3-Clause` (compatible with GPL-3.0) and publishes `abi3` wheels for manylinux x86-64 and aarch64 (about 4.7 MB; [PyPI](https://pypi.org/project/cryptography/)); Dart `cryptography` is Apache-2.0, supports Ed25519 and lists Android, iOS and **Web** ([pub.dev](https://pub.dev/packages/cryptography)). Both go into `25`. If either ever fails, the fallback is a per-device HMAC secret issued at sign-in (standard library only); that would come back to the advisor, not be switched silently.
  **D2. Discovery is mDNS `_encore._tcp` from `avahi` on the host, never a broadcast.** The TXT record holds `id`, `name`, `api` and **no URLs**. Discovery is unauthenticated, as in Syncthing, and D1 makes that harmless: an impostor's candidate fails the challenge and drops out of the race. On by default with a switch "Show this server on my home network" (wizard, admin, `encore discovery on|off`).
  **D3. The server's own https (Tailscale Funnel) name plays the role of plex.tv.** `GET /encore/api/v1/server` (signed in) returns `{serverId, name, addresses: [{kind: home|away, url}]}`; a phone that knows the away address can always fetch fresh home addresses, and the list is refreshed after every sign-in and whenever an address stops answering. Invite and pairing links carry the addresses too. **No project-run directory and no project relay** (Plex's relay is 1 to 2 Mbps anyway); home candidates race first. The owner's manual "Your server > Add an address" step disappears.
  **D4. Several Wi-Fi networks: the Wi-Fi name is never read** (it needs the location permission and nothing depends on it). On every network change, and at start, the phone races *last good address, the other known addresses, the away address, whatever discovery finds*; the **first that answers with the right key** wins. A guest network that isolates devices, work, mobile data: each ends in the best address that works there, or in "Can't reach your server from here" with the reason when known. No subnet scan now; revisit only if the real-phone proof shows mDNS blocked (Jellyfin's "no servers found" is why link/QR plus server-provided addresses stay the primary path).
  **D5. Quick Connect (Jellyfin-style) is slice D, recorded and not built.** A phone that found the server shows a 6-digit code; any signed-in device of the Host approves it. That is how a housemate joins without anybody dictating a password.
  **D6. The app does not move to target SDK 37 before slice C**, because the permission also gates ordinary home-network connections; slice C chooses between the system picker and the permission, on a real phone.
  **D7. A pairing code is a credential:** single use, valid 10 minutes, never written to `/var/log/encore-install.log` or any log.
* **The first screen, in this order** (`15` A1, plain words, no "address" or "IP"): **a link or a QR code** (the installer, and `encore pair [user]` on demand, print a one-time pairing link and QR for the owner's own phone; an invitation does the same for a friend; the phone's own camera opens it in the app, so **no scanner library is added unless that proves false on a real phone**); then **"Servers on this Wi-Fi"** (found servers shown by name; finding grants nothing, joining still needs a link, a login or, later, Quick Connect); then **"Other ways to connect"** (the typed address, in Host/Advanced words).
* **Several servers.** Under the thin-client and relay design (ADR-R38, `13`, P4-08/09) a person has **one home server** and reaches friends' servers through it, so "many servers" is the rarer case of belonging to two households. The app's data is per server (once keyed by the id); discovery lists every server found as a card by name, ones the phone has are marked; a **server switcher** ("Add another server") is a small later task. Not built now.
* **Legacy servers** (an older Encore image, a plain Navidrome): an unauthenticated Subsonic `ping` is answered with an error envelope ("missing parameter: 'u'", `type: navidrome`; checked on the dev VM's Navidrome 0.64.2 through both ports), which is enough to say "a Subsonic server is here" without sending any credential; the app keeps working as today and learns the key the first time the server can give one.
* **Why this beats the others.** It gets Plex's result (nothing to type, the server found again wherever the phone is, a stable name for a moved or re-addressed server) without Plex's directory: the key does what the account does, the server's own address list does what the plex.tv record does, the home Wi-Fi's mDNS does what the broadcast does. It avoids Jellyfin's Docker failure (D2), adds what Home Assistant lacks (a verifiable identity) and what Syncthing needs a service for (we use the Funnel name instead). (a) is better in one way and unaffordable; (b) alone leaves reinstall-at-home and housemates without a link; (c) alone fails on blocked multicast, a new network and away from home, and cannot say *which* server it found without D1; (d), (e), (f) cost more for the same.
* **Consequences and risks.** New `cryptography` dependencies on both sides (two rows in `25`); `serverId`, the challenge and `/server` are additive API (`17`); a migration of the app's server rows (an older row learns its key once); `avahi` on the host (one more package; the installer logs it); mDNS can be blocked (the link and the away address still work, the manual form remains); a host with several network cards advertises the wrong address (the TXT names no address: the app asks the address the advertisement came from, then `/server`); Android's permission model may change again; **discovery cannot be proved on the emulator** (expected, not measured: its network sits behind its own virtual router; measure first thing in slice C) and is proved on a **real phone on the owner's Wi-Fi**, which becomes one line in his five days of use.
* **Tests.** Server: the key is made once and survives a restart and a backup/restore (`c02` method); the challenge signature verifies with the published key; `/server` shape; `encore pair` is single use, expires and appears in no log. App (fakes): a candidate that answers with another key, or no signature, never receives a header, a query token or a body; the first candidate is not used before it has proved itself; of two candidates with the right key the quicker wins; a recycled address on another network is skipped; an older row learns its key once; the list is refreshed from `/server`; a typed address still works; a legacy server is recognised without credentials; the first screen shows link/QR and "servers on this Wi-Fi" before "other ways". Walks on the emulator: fresh install, open a pairing link with `adb shell am start -a android.intent.action.VIEW -d ...`, signed in with no typing (`evidence/b03`). Discovery: the server side with `avahi-browse -rt _encore._tcp` from a second VM on the same bridge; the app side on the owner's phone.
* **Slices** (`tasks/P2` P2-19): **A (M)** the key and identity, the identity-checked probe, `/server` and server-provided addresses, the app's server rows keyed by id; closes S2. **B (S-M)** `encore pair`, the installer's pairing QR, the first screen reordered and in plain words. **C (M)** avahi, in-app discovery, the permission-or-picker decision, the real-phone proof (waits for the owner's phone). **D (S-M)** Quick Connect. Later: the server switcher, a subnet-scan fallback if mDNS proves blocked. A and B touch the owner's own install and first phone; **the friend, who joins by an https link, does not wait for them**, and the owner's VM 107 install does not either (if he installs first he types the address once).
* **Revisit when.** mDNS turns out blocked on many home networks (then the scan, earlier); the project accepts running a directory service (then (a) for the away case); Android changes the permission again; a web client arrives (it is served by its own server and needs none of this).
