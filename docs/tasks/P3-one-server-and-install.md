# P3 — One server, one-command install

Goal: one Encore server program (+ Navidrome, + optional Tailscale), one port, device logins, published images, a one-command
installer and a browser wizard that a person who never used Docker can follow. Read `../04` §2, §5–§7, §9 and ADR-R3, R7.

## P3-01 — Move people, sources, keeper and admin into the Encore server; the gateway is the only door — Size L
* **Order.** Needs: none.
* **Why.** C1, C2. After P2-01 the new server exists next to the old services.
* **Context.** Old services: `encore-fetch` (P1 already moved its YouTube part into a package), `encore-people` (invites, roles, password
  reset, activity), `encore-admin` (pages Today/People/Quality/Suggestions/YouTube/Parts). Their tests (people 140, admin 137, fetch
  355) are the specification of behaviour worth keeping.
* **Do.** Port `people` into a module (keep invites, roles, reset, lock/remove; **drop** friend activity for v1, D-4). The gateway
  serves `/encore/*` and proxies everything else to Navidrome (Subsonic API, covers, streams, Navidrome UI) with streaming responses;
  the compose file publishes **only** the Encore server's port (4533 by default, so existing app addresses keep working) and Navidrome
  becomes internal. The app uses one base URL per server (home + public, raced): delete `ServiceFinder`/port probing. Keep the old
  test suites' behaviours as tests of the modules; delete `server/legacy/`.
* **Acceptance.** `docker ps`: `encore-server`, `navidrome`, optionally `encore-tailscale`; one published port; all journeys of P1/P2
  still pass through the gateway at home and through the public address.

## P3-02 — Published server images for Intel and AMD computers — Size S
* **Order.** Needs: none.
* **Do.** `server/Dockerfile` (slim Python, ffmpeg, Deno pinned per arch, yt-dlp pinned and updated by the daily check), built in CI for
  amd64 (Intel and AMD), pushed to `ghcr.io/<owner>/encore-server:<version>`; compose uses pinned tags; image size target ≤ 450 MB.
* **Acceptance.** `docker compose pull && up -d` on a clean amd64 VM; no local build.

## P3-03 — Device tokens; the gateway signs requests to Navidrome; the one-way mirror — Size M
* **Order.** Needs: none.
* **Why.** C9: the app keeps the password and sends Subsonic tokens in URLs.
* **Do.** Run X-2 first. `POST /encore/api/auth/login {user, password, deviceName}` → long-lived device token (stored hashed; revocable
  from the app and the admin). If X-2 passes: the gateway forwards requests to Navidrome with the trusted reverse-proxy header (secret
  header name, `ND_EXTAUTH_TRUSTEDSOURCES` = the gateway only) so the app never stores the password. If it fails: keep Subsonic tokens
  for proxied Navidrome calls only. Then the **one-way mirror**: Encore playlists and likes → Navidrome playlists/stars for songs with
  files, acting as each user via the header.
* **Acceptance.** The app's secure storage holds no password after sign-in; revoking a device signs it out ≤ 15 s; a Subsonic app (e.g.
  Symfonium) sees the mirrored playlists.

## P3-04 — Remove Docker-socket control, Firefox, Google sign-in; park the rest — Size S
* **Order.** Needs: none.
* **Why.** C5, C6, Q5/Q6 in `../02`.
* **Do.** No Docker socket mounted anywhere; no browser container; no Google/YouTube account pages; a cookies file remains an
  Advanced environment setting documented with the risk. Quality, recommendations and the Jam hub are not in the default compose file yet:
  phase P4 brings them back as modules (their old code is in `server/legacy/`).
* **Acceptance.** `grep -r docker.sock server/deploy` empty; admin pages have no YouTube account section.

## P3-05 — Install script, `encore.local`, `encore` CLI — Size M
* **Order.** Needs: none.
* **Why.** ADR-R7; owner has never used Docker and does not expect users to.
* **Do.** `server/deploy/install.sh` (served at a stable URL): checks 64-bit Linux (Debian/Ubuntu first), CPU arch, RAM ≥ 2 GB, disk
  ≥ 20 GB (**built as 6 GB**: `install.sh` refuses below 6 GB free, and `guides/install-test.md` says so); asks before installing Docker from Docker's own repository; creates `/opt/encore` (compose + generated `.env` with
  secrets); asks for the music folder (default `/srv/music`, created if missing; existing folders are mounted read-only for scanning
  and `/music/Encore` read-write for kept songs); pulls images, starts, waits for health; enables mDNS (`avahi`) so the server answers
  at `encore.local`; prints the address (**no QR code since F16**: it encoded the bare address and a phone opened the music server's page; a QR that carries the Encore setup link comes with the pairing link, P2-19 slice B). `encore` CLI: `status`, `update`, `logs`, `backup`, `restore`,
  `uninstall` (keeps the music unless `--everything`). Idempotent re-runs. Works without an interactive TTY (`--yes`, flags).
* **Don't.** Print secrets; touch existing Docker containers of the machine; open firewall ports to the internet.
* **Also a design constraint (owner, 2026-10-22, "keep in mind for the future"): trying Encore on a machine that already has a setup.**
  Somebody who already runs Plex, Navidrome, Tailscale and their own music folder just wants to *try* Encore. The install must not make
  them install again what they have, nor disturb it: it **finds and reuses** an existing Tailscale (asks before enabling Funnel for one
  more service; never logs the machine in again or changes its other serve rules), an existing Navidrome (asks for its address and an
  account instead of starting a second one, and says what Encore will add: songs it keeps go into one folder it owns, the rest stays
  read-only), an existing music folder (mounted read-only, scanned, never moved or retagged), and runs **beside** Plex and anything else
  on free ports with its own containers. It must also be removable in one command that leaves everything else as it was. To be designed
  on paper (`../15`) before code; acceptance journey: a machine with Plex + Tailscale + Navidrome + a music folder, Encore tried in under
  10 minutes with none of them touched (checked by comparing their configs before and after).
* **Acceptance.** On a fresh Ubuntu 26.04 VM (x86-64): one command → wizard reachable at `http://encore.local` from a
  phone on the same Wi-Fi in ≤ 10 minutes (download speed noted).

## P3-06 — Setup wizard and admin pages — Size L
* **Order.** Needs: P3-22 [d], P3-20 [d], P3-25 [d], P3-21 [i]. Why: D-53 (Jam before the setup pages) is replaced by D-61: the owner will not install anything that needs a terminal, so the setup pages come first. The pages are already drawn (W-01 to W-08); P3-22 changes only what the new rules change, and the owner approves exactly that. Update, Backup and Restore are buttons that use the helper (P3-25), and the add-ons come from the model of P3-20.
* **D-53 is replaced by D-61 (`10`, owner 2026-11-05): the setup pages and a button installer come BEFORE Jam and before any friend. The Order line below still shows the old order until the three-gates draft is applied (PR #151, after its hidden needs are added); do not plan from the old order.**
* **Order (D-61, owner 2026-11-05, replaces D-53):** the setup pages come BEFORE Jam and before any friend. The first friends do not use a terminal installer. "The admin Health page explains every state" is again a condition of the first friend (gate 2, P3-18). **Already built on the server:** the owner's first account (`setup.py`), the people, invitation and device routes, the join page (W-05). **Not built:** the pages themselves.
* **Paper first:** build exactly the pages of `../15` §2 and §4; the drawings exist; P3-22 changes the ones the new rules change and the owner approves them before code. The setup code of `../15` §1 is required.
* **Why.** US-01, US-02, US-03, US-40, US-42, US-51.
* **Do.** Wizard: owner account (creates the Navidrome admin and the owner as a person), server name, music folder check, machine and
  line test (CPU, disk, download/upload, YouTube reachability) with plain results, optional away-from-home (Tailscale Funnel with
  screenshots, key paste, self-check, key-expiry warning), first invitation (link + QR). Admin pages: Home (health in plain words),
  People (invite, reset password, lock, remove, devices), Storage (space, kept songs, free-space floor, "remove songs nobody saved"),
  Away from home, Updates (version, "run `encore update`"), Advanced (YouTube pace, background speed limit, cookies note).
  Reuse the design tokens (`app/lib/design/tokens.dart` → CSS, as the old admin did).
* **Acceptance.** J-14; every page passes the screen checklist (`../07` §10) at 360 px width and on a desktop browser. The Home page (health in plain words) explains every state of `../32` and what the Host does about it.
* **D-61 (owner, 2026-11-05): two doors to the same house.** Every action a Host takes exists twice, as a button on the admin pages AND as a command (`encore ...`), and both call the same operation. Neither is the "expert" path or the "beginner" path: some people prefer a terminal, some prefer buttons, and both are first-class, documented and tested. Nobody is ever required to open a terminal.

## P3-07 — Clean-machine proof — Size S
* **Order.** Needs: P3-02 [i], P3-23 [d]. Why: P3-02 publishes the image the fresh machine pulls; P3-23 is the button installer this task walks with no terminal (D-61).
* **Do.** **Walk both doors: the button installer (P3-23) with no terminal, and the one-line command.** Follow the website guide word for word on fresh VMs (x86-64 Ubuntu 26.04, Debian 13), a SLOW-profile VM, and once
  with the line throttled to 10/1 Mbit/s; time each step; fix the guide where reality differs.
* **Acceptance.** J-14 ≤ 15 minutes on TYPICAL, ≤ 30 on SLOW; the guide matches what happened.

## P3-08 — Updates with rollback, yt-dlp freshness, backups, moving computers — Size L
* **Order.** Needs: P3-14 [d].
* **Moved out (2026-11-03).** The slice "`encore update` with automatic rollback" is now **P3-14**: the first outside user needs it. What is left here is moving computers, `encore stats`, the nightly restore CI and the owner's "needs you" notices.
* **Why.** `../22`.
* **Do.** `encore update` with automatic rollback; the runtime yt-dlp/ytmusicapi/Deno updater with the 24-hour rule, hashes and the
  canary; nightly backups (databases, settings, federation key) with retention; `encore backup/restore`, `--full` and installer
  `--restore`; CI that restores a real backup nightly; owners' in-app "needs you" notices; `encore stats`.
* **Acceptance.** A forced bad update rolls back by itself; a yt-dlp release that fails the canary is not used; moving the dev VM's
  server to a fresh VM keeps phones signed in and friends on other servers connected.
* **Slices (L task, split 2026-10-23).** **P3-08a done:** the weekly from-scratch image rebuild (PR #7). **P3-08b built and run for real (PR #9, `../evidence/README.md#c04`):** the in-server yt-dlp updater as designed in `../11` ADR-R39
  (pointer + child-process canary on the production path, restart only when quiet and at most once per version, one way to run yt-dlp); it reaches a server with the next `encore update`. Later slices: `encore update` with automatic rollback; the same pattern for
  `ytmusicapi`; `encore stats`; the in-app "needs you" notices.

## P3-09 — Security and privacy as written (server + app) — Size M
* **Order.** Needs: none.
* **Split (2026-11-03).** The review of the internet-facing surface before the first outside user is **P3-15**. This task keeps the full privacy matrix, "Your data" and "Delete my account", and a last fresh-agent review before P5-06.
* **Why.** `../21`.
* **Do.** Roles and the privacy matrix enforced server-side with one test per cell; credential rules (device tokens, one-time codes,
  rate limits, locks); route exposure per §3; "Your data" export and "Delete my account"; the explicit-songs setting; an optional
  per-person storage cap (when reached: that person's new saves stay playable by streaming but are not kept, and the Host is told); a fresh-agent
  security review against `../21` before P5.
* **Acceptance.** Every privacy-matrix test passes; a scripted attacker run (wrong passwords, admin over the public address, forged
  federation request, reused invite) is refused as specified.

## P3-10 — Devices, settings and the Host's safety nets (server + app) — Size M
* **Order.** Needs: P2-19 [i]. Why: "Add a device" by QR from a signed-in device uses the pairing link that P2-19 slice B builds..
* **Why.** `../26` §4–6, H46.
* **Do.** "Add a device" QR from a signed-in device; settings stored per person on the server (device-only ones excepted); on a new
  device "Download the same playlists as on <old device>?"; revoke a lost device from another device or the admin (downloads stop
  playing after revocation); `encore reset-password <name>` for a Host locked out; the wizard and admin suggest a second owner; weekly
  disk health (SMART) with plain warnings.
* **Acceptance.** A new phone signed in by QR from the old one has the same settings and offers the same downloads; a revoked phone stops
  playing within one app start; a simulated failing disk (SMART test data) shows the warning.
* **Audit B-30.** The owner-made reset link (`32` AC-6) and the list of one's own devices (DV-3) are built on the server and have no screen in the app: a friend who is sent a reset link cannot use it, and nobody can sign out their own lost phone. This item builds both screens.

## P3-11 — The Tinkerer's door — Size M
* **Order.** Needs: none.
* **Why.** `../27` §3; persona "Tinkerer" (`../03` §2).
* **Do.** Attach Encore to an **existing Navidrome** (URL + an administrator login; Encore then needs read access to the music folders and
  write access to its own `Encore/` folder) instead of starting its own; an install path with plain Docker Compose and a documented
  `.env`; documented examples for an own domain behind Caddy, Traefik and nginx; publish the OpenAPI file of `../17` with the docs.
* **Acceptance.** On the dev VM, Encore attaches to a separately installed Navidrome 0.64.2 and all P2 journeys pass; the Compose-only
  path works from the docs alone.

## P3-12 — The first outside user (a friend on the owner's server) — Size M
* **Order.** Needs: P3-05 [d], P3-24 [d]. Why: gate 3 (P3-24) is the invitation itself and now carries every earlier need (the walk, the deep review, the update rollback, the password reset, the release key and the install guide); this task is what happens next: the friend's first week. (D-61 replaces D-53.) The owner's part stays: decide whether lyrics move to the server before the friend connects (D-51).
* **Why.** Owner, 2026-10-22: a friend will use Encore daily from outside the owner's home and report bugs and dislikes (`../11` ADR-R33).
* **Do.** (1) Prove `encore funnel on` end to end on the real deployment and that an invitation made there opens for somebody who is not on the
  home network. (2) `encore backup` and a nightly backup of the Encore database (SQLite online backup, seven kept, outside the container's
  own volume), `encore restore`, and a restore tried on a clean machine. (3) *On hold (R35):* an in-app report; the friend messages the owner and can paste Diagnostics > Copy report. (4) A one-page friend's guide (`docs/guides/friend.md`): get the app, tap the
  link, sign in, what to expect, how to report. (5) Measure what two daily users do to the single home address YouTube sees: count the
  look-ups per day per person; the pacing and the rest already protect it; write the next step (a cookie or another way out, `../04` §5).
* **Don't.** Show the owner what the friend listens to. Update the server while he is likely to be listening without saying so.
* **Acceptance.** The friend installs the app, joins by the link from outside the owner's home, listens for a week; a backup of his data is
  restored on a second machine and his playlists are all there; his first problem report reaches the owner with the report attached (the in-app report is on hold, ADR-R35: until it exists, he pastes Diagnostics > Copy report). (The old gate of the first friend: **five checks, in order** hold first: (1) the owner installed his own server by the guide, by hand, and uses it; (2) the away-from-home address answers a phone on mobile data, websockets included (X-7); (3) the data can come back; (4) the friend's guide is final; (5) five days of the owner's own use.)
* **Depends on.** P3-05 (done as a slice), the owner's Tailscale sign-in. **Size.** M.

## P3-13 — Storage: a budget the Host sets, visible in the app, and a plain "the server is full" (server + app + installer) — Size M
* **Order.** Needs: none.
* **Why.** The owner (2026-11-03): "reserve 100 GB for Encore's music so we do not run out of space"; friends will fill it. For a stranger the
  server has **one shared disk**. Today Encore has only a floor (`ENCORE_MIN_FREE_GB`, default 10: the keeper stops and retries every 30
  minutes) and the Host learns of a full disk from a failed song. A hand-made placeholder file on one machine is not an answer a stranger can use.
* **Do.** (1) Server: `ENCORE_MAX_KEPT_GB`, a cap on what Encore keeps (unset = only the floor), enforced by the keeper next to the floor;
  storage state in the owner's view of `/server`: kept, budget, free, and counts per person. (2) App, owner: a Storage row on Your server (kept,
  budget, free) and an in-app news item at 80 % and 95 %. (3) App, everybody: when the keeper refuses for space, the song says "The server is
  full; ask the owner" instead of failing silently. (4) Installer: say how much room the music folder has and warn under 20 GB; the guide gets a
  "Give Encore its own disk" section (format, mount at `/srv/music`). (5) The guide says plainly that music is not in the backup.
* **Don't.** Delete anything to make room. Reserve space with placeholder files.
* **Acceptance.** With a 2 GB budget on a test server the third GB of songs is refused with the plain message, the owner sees the 80 % and 95 %
  items and the Storage row, nothing already kept is touched, and raising the budget lets the retry continue.
* **Depends on.** The keeper (built). **Size.** M. **Triage:** later (RC2); the guide's dedicated-disk section covers it meanwhile.

## P3-14 — Update with automatic rollback (the slice of P3-08 the first outside user needs) — Size M
* **Order.** Needs: P3-25 [d], P3-27 [d], P3-30 [i], P2-24 [i]. Why: D-61: the Update button and `encore update` are two doors into the same helper (P3-25), which does the rollback; a web page may not hold control of the host computer (P3-04).
* **Why.** The first outside user is a daily user on a server the owner updates by hand (`encore update` makes a backup first, but has no way back). P3-12 itself says not to update while the friend is likely to be listening; a rollback makes that rule safe instead of lucky. `../22`.
* **Do.** `encore update` keeps the previous image tag and a copy of the data, starts the new version, probes it (`/info` and one real call) for a fixed time, and on failure returns to the previous version and data by itself, saying so in plain words; a failed update never leaves the server stopped.
* **Acceptance.** A forced bad update (an image that fails its probe) rolls back by itself in CI and on a real VM; the phones' sessions survive; the log says what happened.
* **Size.** M.
* **D-61.** An **Update button** on the admin pages and `encore update` do the same thing through the helper (P3-25) and both roll back by themselves. The terminal command stays a full door, not an expert path.

## P3-15 — Security review of the internet-facing surface, before the first outside user — Size M
* **Order.** Needs: P3-29 [d], P3-30 [d].
* **Why.** The first outside user connects over the internet (P3-12), but the only planned review (P3-09) was "before P5". Everything that faces the internet is reviewed before the first stranger-sized exposure: the gateway and `authorize_public`, sign-in and `LoginGuard`, invitations and join, signed addresses, the live channel, the Funnel path, the installer (it runs as root on other people's computers), backup and restore.
* **Do.** A fresh-agent review against `../21`; then the first Claude ultrareview (`/code-review ultra`, billed, started by the owner; the agent prepares the branch so the review sees the whole surface as one diff); a scripted attacker run (wrong passwords, the music server's door over the public address, a reused or forged invitation, a forged signed address); findings triaged by D-29.
* **Acceptance.** Every finding fixed or accepted in writing with the reason; the attacker run is refused as specified; the record is an evidence file.
* **Size.** M.

## P3-16 — The Host can recover a lost password — Size S
* **Order.** Needs: P3-25 [d], P3-21 [i]. Why: D-61: the Host who forgot his own password cannot press a button inside pages he cannot sign in to; P3-21 decides the proof of ownership that the button door uses (a recovery key shown once at install, or a button on the installer's own window on the server computer); `encore reset-password` stays the command door.
* **Why.** `local/credentials-map.md` says `encore reset-password <name>` "is not built yet", and the first real Host is the owner: forgetting the only owner's password today means reinstalling. QA-BACKEND B2 closed the other side (a stranger can no longer lock the owner out).
* **Do.** `encore reset-password <name>` run on the server's computer (shell access is the proof of ownership): sets a new password, revokes that person's other sessions, writes a line in the log; the app's sign-in says where to find it.
* **Acceptance.** Forget the password, run the command, sign in with the new one on a second device; the old sessions are refused.
* **Size.** S.
* **D-61.** Two doors: `encore reset-password <name>` (shell access is the proof) and a button door whose proof P3-21 decides. Resetting a **friend's** password is already a button (the admin People page, W-03, drawn).
* **Audit B-30.** A server whose only owner forgets the password has no way back in today (`encore reset-password` does not exist; `32` AC-28). Two doors, one operation (D-61); the proof is physical (a code printed on the server computer or the install's recovery file), never the web page alone.

## P3-17 — The server on ARM computers (Raspberry Pi and others) — Size M
* **Order.** Needs: P3-02 [d].
* **Decided (owner, 2026-11-04, D-58): later, not now.** He tried an ARM server and could not get it running, and wants the Intel/AMD server perfect first. This item is **Later** work: keep it possible, do not build it.
* **Keep it possible (cheap rules for the Now work):** no Intel-only pieces in the server (no x86-only binaries or wheels without an arm64 equivalent); the images are built so that adding `linux/arm64` is a change of the build, not of the code.
* **Do (when it is time).** Publish `linux/arm64` next to `linux/amd64` (multi-arch tag), run the installer on a fresh ARM64 VM and on a Raspberry Pi, and measure the slow-line install there.
* **Acceptance.** `docker compose pull && up -d` on a clean arm64 VM; the installer's one command works on a fresh ARM64 Ubuntu 26.04 VM in at most 15 minutes; the guide says what a Raspberry Pi can and cannot do.
* **Size.** M.

## P3-18 — Gate 2: you install your real server yourself, by clicking (owner) — Size S
* **Order.** Needs: P3-05 [d], P3-22 [d], P3-06 [d], P3-23 [d], P3-07 [d], P3-11 [d], P3-25 [d], N-05 [d], P3-16 [d], P3-14 [d], P3-26 [d], P3-29 [d], P3-30 [d], P3-27 [d], P3-33 [d]. Why: the second of the owner's three thresholds (D-61). He installs his own server, himself, only by clicking, the way a stranger who prefers buttons would (the command stays a full door for people who prefer it). It comes only after the add-ons model and the installer are designed, the changed setup pages are approved and built, the helper exists, Backup, Reset a password and Updates work as buttons AND as commands, an existing music server can be attached (his homelab already runs one: P3-11) and Claude has proved the button install on a clean machine (P3-07).
* **Owner's step (D-59).** He clicks; he types nothing he has not been told to. **The server runs on his homelab (a Proxmox machine);** Claude walks him through the clicks one small step at a time and verifies each result itself. Today: nothing to do yet.
* **Do.** Claude prepares the click-by-click guide for his machine (what to click, what he will see), runs the checks afterwards, removes the old Encore device from his Tailscale machines page together with him (it must go before the new server's address is turned on), and signs in for the away-from-home address by the wizard's own step.
* **Acceptance.** His own server is installed by the buttons, answers, and its address works from a phone on mobile data, websockets included (X-7). It stays his daily server.
* **Size.** S (his time, not counted in the estimate).

## P3-19 — Start Claude's deep security review before the first friend (owner) — Size S
* **Order.** Needs: P3-15 [d].
* **Owner's step (D-59).** One command typed by him: it starts Claude's deepest review (`/code-review ultra`), it is billed, and only he can start it. Claude prepares the branch and tells him the exact command when it is time. Today: nothing to do yet.
* **Acceptance.** The review ran on the prepared branch and every finding is fixed or accepted in writing (the record is an evidence file, P3-15).
* **Size.** S (his time, not counted in the estimate).

## P3-20 — Add-ons: built in, bring your own, or off (designed on paper first) — Size M
* **Order.** Needs: none. Why: the owner (5 Nov 2026): the optional-lossless and "bring your own containers" logic must be designed **before** the setup pages are changed or built. His own homelab already runs a music server and other tools that a stranger will not have.
* **Start from what exists, do not redo it:** wizard page 5 "Songs you don't have" and page 7 "Friends on other Encore servers" and admin **Settings** (W-07) in `15` and the drawings `screens-server-and-browser.html`; **D-19** (the higher-quality source is an explicit, off-by-default choice with a plain-words legal note), **D-20** (no YouTube account), **D-12** and **ADR-077** (optional things are off with safe defaults); **P3-11** (the Tinkerer's door: attach to an existing music server); **P4-04** (Lidarr, slskd, Soularr as an optional compose profile); the away-from-home address (ADR-083, wizard page 6); backups (`22`); "update automatically at night" (`22`).
* **Do.** Write the add-ons document (to be numbered 35): ONE model for all of them. Each add-on is in one of three states: *Encore runs it*, *Yours* (an address and a key for a container the person already runs, health-checked, with the plain words shown when it fails) or *Off*. For each: its default, the plain risk text shown **before** it is switched on, what the wizard page says, what the admin page shows, what the server stores, and how it is switched **both ways** (a button, and an `encore` command: D-61). It ends with **what an agent who adds the next add-on must write** (a manifest that the wizard, the admin pages and the command all read) and with the exact pages and states P3-22 must change.
* **Don't.** Build anything. Choose the installer (P3-21).
* **Acceptance.** The advisor has read it; the owner has read the one-page summary in plain words; the pages of `15` that mention an optional thing point to it; P3-11, P3-13, P4-04 and N-05 each point to it.
* **Size.** M.

## P3-21 — Two doors to the same installation: the button installer and the command (designed on paper first) — Size M
* **Order.** Needs: P3-28 [i], P3-26 [i]. Why: the owner (5 Nov 2026) will not install his own server until it is buttons, and he will not invite a friend before he has installed it himself (D-61). Today's front door is one pasted command (`15` §1, `install.sh`, built and walked on bare VMs: `evidence/c01`, `c03`, `c06`).
* **Start from what exists, do not redo it:** **ADR-R7** (the options were weighed: Docker guide, script plus wizard, a flashable OS image, a desktop installer, native packages, Windows; the script plus wizard won and the OS image was kept as "a candidate after v1" because it means maintaining an operating system: re-decide with the new rule, do not silently reverse it); `15` §1 and §1b; `install.sh` and the `encore` command (`status`, `update`, `funnel`, `backup`, `restore`, `autobackup`, `uninstall`, all built and tested); `guides/install-test.md`; **P3-04**, which says **no part of the server may hold control of the host computer (no Docker socket)**; the setup code (`15` §1, hidden risk H36).
* **The hard part, decided first: a button that updates, backs up or restores the server cannot be given the host computer.** A web page running inside the server may not be able to start and stop its own containers (that is exactly what P3-04 removed). The design must give the buttons and the `encore` command the same **small helper on the server computer** that does only a fixed list of things (update with a way back, back up, restore, change the away-from-home address), reachable only from the server itself, with no general control. P3-25 builds it.
* **Also decide:** (1) **the front door for a person who will not use a terminal:** research first, do not assume: what a Windows 11 Home PC needs today for containers (WSL2, virtualisation switched on in the computer's firmware), whether Docker Desktop's licence allows this use, and what the alternatives cost (another container engine, a ready-made virtual machine or appliance image that the person imports with the clicks of Proxmox's or Windows' own tools). Each wall the installer can hit is explained with a button or a picture; if it cannot be, the design picks another way. **First target: the owner's homelab** (a Proxmox machine where a music server and other tools already run, and where "bring your own", P3-20, matters); **second: a Windows PC**; then the rest. (2) **The Host who forgot his own password:** a button inside the admin pages cannot help someone who cannot sign in, so the proof of ownership must be something only the person at the server has (a recovery key shown once at install, or a button on the installer's own window on the server computer): P3-16. (3) The one-line command stays exactly as designed, as a full door.
* **Acceptance.** The advisor has read it and the owner has read the plain-words summary; it names the first target, every wall with its button or picture, the helper's fixed list of actions, and exactly what P3-23 and P3-25 build; it shows that the command door and the button door produce the same installation.
* **Size.** M.

## P3-22 — Change the drawn setup pages for the new rules, approved by you — Size S
* **Order.** Needs: P3-20 [d], P3-21 [d]. Why: the wizard (W-01, eight pages), the admin pages (W-02 to W-08) and the join page (W-05) are **already drawn and decided** (`screens-server-and-browser.html`, `15`, 24 and 25 Oct 2026). Only what the new rules change is drawn again, and the owner approves exactly those.
* **Do.** (1) The new front: the installer's own screens (P3-21). (2) Admin **Backups**: Back up now stays; **Restore becomes a button** (the drawn rule "never a button" is reversed by D-61) that first makes a backup of what is there and asks the Host to type the server's name to confirm. (3) Admin **Updates**: an Update button with its way back, replacing "run `sudo encore update`". (4) **Away from home**: the page runs the Tailscale steps itself (this closes the OPEN line of `15` page 6). (5) **Add-ons** from P3-20 on wizard page 5 and in W-07 Settings (D-19's off-by-default Soulseek choice and its plain-words note). (6) The Host who forgot his password (P3-21). Each changed page is drawn in the same design tokens (`16`) next to the old frame it replaces.
* **Acceptance.** The owner has approved exactly the changed drawings (his check is recorded on the board); `15` and the inventory (W-01 to W-08) say what changed.
* **Size.** S.

## P3-23 — Build the button installer — Size L
* **Order.** Needs: P3-21 [d], P3-02 [d], P3-25 [d], P3-27 [d], P3-26 [d]. Why: the build of what P3-21 designed, for the first target it names.
* **Do.** Build the installer exactly as designed; it produces the same installation as `install.sh` (so that walking one proves the other); the person never opens a terminal; every wall it can hit is explained with a button or a picture; the `install.sh` door keeps working and keeps its tests.
* **Acceptance.** On a clean machine of the first target the installer goes from download to the setup pages in the browser without a terminal and without a word from Claude (the proof is P3-07).
* **Size.** L.

## P3-24 — Gate 3: you invite your friend and jam with him (owner) — Size S
* **Order.** Needs: P3-18 [d], P5-07 [d], P4-02 [d], P6-02 [d], P2-10 [d], P2-19 [d], P3-10 [d], P2-08 [d], P2-09 [d], P4-12 [d], P4-04 [d], P4-01 [d], P2-14 [d], P4-05 [d], P4-07 [d], P3-15 [d], P3-19 [d], P3-26 [d], P3-28 [d], P2-24 [d], P3-29 [d], P3-30 [d], P3-32 [d]. Why: the third of the owner's three thresholds (D-61). He will share the app only when his friend gets the whole thing: the Jam, the browser version for his PC, Android Auto, the home-screen widget, crossfade, CD-quality sound, suggestions, lyrics, his Year in Music, control from another device, the install guide for the friend, and the security checks. He said yes to every line on 5 Nov 2026.
* **Owner's step.** He sends one link. His friend, in another city, taps it on his phone (or opens it in a browser), signs up with the invitation without typing an address, and the two start a Jam: the owner in the browser on his PC, the friend on his phone. **Claude prepares everything and walks him through it.**
* **Acceptance.** The Jam runs for a whole session between the owner's PC browser and his friend's phone, each on its own internet connection, through the away-from-home address; the friend can come back tomorrow and find his things.
* **Size.** S (his time, not counted in the estimate).

## P3-25 — Behind the scenes: a small helper on the server computer for the buttons and the command — Size M
* **Order.** Needs: P3-21 [d]. Why: the admin pages' Update, Backup and Restore buttons and the `encore` command are two doors into the same few actions; the web-facing server must not hold control of the host computer (P3-04). A small helper that does only a fixed list of actions, and is reachable only from the server computer, is the way both doors work without that control (D-61).
* **Do.** Build the helper as designed in P3-21: a fixed list of actions (update with a way back, back up, restore, change the away-from-home address), each checked before it runs, each writing a line to the log; the server and the command both ask it; **no Docker socket anywhere** (P3-04's check stays true); the existing `encore update|backup|restore|funnel` commands call it, keep their tests and keep working when the web server is down.
* **Acceptance.** The Update button and `encore update` do the same thing and both roll back by themselves when the new version does not start; the same for Back up and Restore; `grep -r docker.sock` still finds nothing; a request for anything not on the list is refused and logged.
* **Size.** M.

## P3-26 — Where the server and the app come from while the code is still private (designed first) — Size S
* **Order.** Needs: none. Why: audit B-1: the repository and the server image are private (a deliberate state: public later, owner 5 Nov 2026), so the installer asks for a GitHub token that may read packages and the invitation page links to an app a friend cannot download. A stranger without a GitHub account, and the owner's own button install (gate 2), both hit that wall.
* **Do.** Decide, and write down with the options compared: (a) whether the server **image alone** can be public while the code stays private (check GitHub's package visibility rules); (b) where the app file comes from for a friend (a public release of a separate repository that holds only the signed APK, or the Host's own server serving it from the invitation page, `ENCORE_APP_URL`); (c) if neither is acceptable yet, the exact click-by-click token step for the owner (a pink item, D-59). The advisor decides on the owner's behalf and records it in `10`.
* **Acceptance.** The decision exists; the installer (P3-23), the invitation page and the friend's guide (P5-07) each have the exact change listed.
* **Size.** S.

## P3-27 — A release channel that only moves when someone decides — Size M
* **Order.** Needs: P5-01 [d]. Why: audit B-2: every installed server follows the tag `main`, which every merged pull request republishes (three server pull requests on 5 Nov alone). `encore update` and the Update button (P3-14) would pull whatever was merged last, so the walked release-candidate pair cannot hold.
* **Do.** A `stable` tag that only a script moves, after the walk; `v*` tags made by the release pipeline (P5-01); the installer, the compose file and the Update button pin `stable` (or an exact version); `main` stays for developers and CI only. A CI check fails if the compose default is `main`.
* **Acceptance.** Merging a pull request changes nothing on an installed server; `encore update` moves to the newest `stable` and says which version it is.
* **Size.** M.

## P3-28 — Prove the away-from-home address with real music, from a phone on mobile data — Size S
* **Order.** Needs: none. Why: audit B-3: every friend and the Jam from another city depend on Tailscale Funnel, which is a beta service with a non-configurable bandwidth limit and has never run for real with music and a live connection (ADR-083 "written, not yet proven end to end"; `evidence/c05` proved only the command).
* **Do.** With the owner's Tailscale sign-in (his step arrives as its own pink item when it is needed: D-59), from a phone on mobile data: play three songs, keep the live connection open for 30 minutes, and measure the throughput with two listeners at the Jam bitrate. Record the limits that were found. Write down the alternatives that stay open (an own domain behind a small proxy, a tunnel service) so that a failure is a choice and not a rewrite.
* **Acceptance.** The numbers are in `evidence`; ADR-083 says "proven" or names the limit; P3-21 (the away-from-home page) and P4-02 (Jam) read it.
* **Size.** S.

## P3-29 — Server hygiene, so one slow request cannot freeze everyone — Size L
* **Order.** Needs: none. Why: audit B-10, B-18, B-19 (measured at 20 phones: some plain reads waited up to 12 s because signing in takes the database write lock; a slow music server froze the owner's read for 2.8 s), B-12, B-13, B-14. The owner's scale is 1 to 20 people or more.
* **Do.** (1) **B-10, B-18, B-19: drafted, measured and held** on the branch `held/server-db-lock` (a 20-phone load test `tests/bench/bench_users.py` and 9 regression tests; the worst read went from 12 s to 0.17 s). The owner said the audit records and does not correct, so merging it waits for his word; this item is that decision plus the rule it enforces: **no network call inside a database transaction, anywhere.** (2) B-12: the server refuses to start, in words, on a database newer than itself, and a rollback restores the pre-update copy. (3) B-13: compare the duration (and the track number when both have one) before trusting a file already in the folder. (4) B-14: mount the music folder read-only and `Encore/` read-write; the installer creates `Encore/` first.
* **Acceptance.** The 20-phone test: 95th percentile at most 135 ms and worst case at most 200 ms; each fix has the test that failed before it.
* **Size.** M.
* **Also (audit B-41, B-42, B-43, B-44, proven or read on 6 Nov 2026):** the music server's outage must not read as a wrong password nor count as a guess (a three-way answer, a 503); a non-ASCII `?sig=` is a 401, not a 500; a reset link must not unlock an account locked after it was made; concurrent refusals must not escalate YouTube's rest; `classify_failure` must not test the substring `age`; the stream caches evict; `YT_FAST_CLIENTS` exists as documented or the documents stop promising it; the websocket authenticates before it reads a large frame; the free-space floor (10 GB) and the installer's minimum (6 GB) are one rule that the installer says; the capacity ceiling (about 5 new songs a minute for the whole server, `ENCORE_YOUTUBE_PACE_S`) is in `docs/22` and on the Host's pages; the canary child gets a minimal environment and auto-update is a visible choice at install (B-43). Each with the test that fails first.

## P3-30 — A password key set at install, and a backup file that is itself secret — Size M
* **Order.** Needs: none. Why: audit B-27 (security): `21` section 4 promises an installer-generated `ND_PASSWORDENCRYPTIONKEY` and nothing sets it, so member passwords are stored under a key shared by every install (Navidrome: "just for the sake of obfuscation", findable in its code); every `encore backup` packs the music server's database and the install's `.env`, which holds the administrator login in plain text.
* **Do.** Two parts. (a) The installer generates a random key into `.env` (mode 600) before the first account exists and the compose file passes it on; for an install that already exists, set the option and restart (Navidrome re-encrypts every stored password; afterwards the key can never change, so it must never be lost). (b) A restore on another computer needs that same key, so the key travels in the backup: treat the backup as secret material, an archive encrypted with a passphrase the Host keeps that `restore` asks for, or decide openly that it stays plain and say so in the message `encore backup` prints. Both doors (D-61): the Backup button asks for the passphrase as the command does.
* **Acceptance.** A fresh install's `.env` holds the key; a restore on a new install accepts the old passwords with the archive's key; a backup archive cannot be opened without the passphrase (or the decision is written in `21` and in the message).
* **Size.** M.
* **Also (audit B-44 and the code pass):** the backup carries the server's private identity key and the song-signing secret (a stolen backup can impersonate the server to every phone and forge song addresses), and Navidrome's own nightly backup (`ND_BACKUP_*`) is a second copy of the password database. Both belong to the same decision: the backup is secret material.

## P3-31 — Split the one big server file into one file per area — Size M
* **Order.** Needs: P3-29 [d]. Why: audit B-11: `api.py` is 1,500 lines (sign-in, library, playlists, keep, playback, live channel, imports and `create_app`); reviews and merges collide in it, and the next server file is a third of its size.
* **Do.** A pure move into routers (accounts, library, playlists, keep, playback, live), one module each, the assembly alone in `api.py`; no behaviour change; the held lyrics branch (#131) is rebased on top.
* **Acceptance.** Every server test passes unchanged; no file over 500 lines; `docs/17` names the module of each route group.
* **Size.** M.

## P3-32 — Fair share between people holds at any queue size (server) — Size S
* **Order.** Needs: none. Why: audit B-39, proven: with one person's 2,000 songs queued first, another person's 20 run at positions 1,802 to 1,840. The owner's scale is 1 to 20 people.
* **Do.** Choose the person served longest ago first (a per-person window in SQL), then that person's oldest item at the best priority; stop the idle workers taking the write lock every second (read first, write only to claim) and do not start the `interactive` worker, which has no handler. Add `docs/07` section 6's own example as a test at full size (2,000 + 20: the 20 finish before item 100).
* **Acceptance.** The probe of the audit prints positions under 100 for the second person; the scheduler tests keep passing.
* **Size.** S.

## P3-33 — An empty answer from the music server never wipes the library link (server) — Size S
* **Order.** Needs: none. Why: audit B-40, proven: an empty library (a disk not mounted at boot, a restart mid-scan) prunes every file link in one pass.
* **Do.** Prune only after a pass that found a plausible library: never when it saw nothing while files are linked, and only for what is absent on two passes an hour apart (or when the pass saw at least half of what is linked). Tell the Host in words ("the music folder looks empty: is the disk mounted?") on the admin Health page and in `encore status`. Test with the audit's fake library.
* **Acceptance.** The probe of the audit ends with the same number of file rows as it began with.
* **Size.** S.
