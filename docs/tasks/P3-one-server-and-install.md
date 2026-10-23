# P3 — One server, one-command install

Goal: one Encore server program (+ Navidrome, + optional Tailscale), one port, device logins, published images, a one-command
installer and a browser wizard that a person who never used Docker can follow. Read `../04` §2, §5–§7, §9 and ADR-R3, R7.

## P3-01 — Move people, sources, keeper and admin into the Encore server; the gateway is the only door — Size L
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

## P3-02 — Published multi-arch images — Size S
* **Do.** `server/Dockerfile` (slim Python, ffmpeg, Deno pinned per arch, yt-dlp pinned and updated by the daily check), built in CI for
  amd64 and arm64, pushed to `ghcr.io/<owner>/encore-server:<version>`; compose uses pinned tags; image size target ≤ 450 MB.
* **Acceptance.** `docker compose pull && up -d` on a clean amd64 VM and an arm64 VM; no local build.

## P3-03 — Device tokens; the gateway signs requests to Navidrome; the one-way mirror — Size M
* **Why.** C9: the app keeps the password and sends Subsonic tokens in URLs.
* **Do.** Run X-2 first. `POST /encore/api/auth/login {user, password, deviceName}` → long-lived device token (stored hashed; revocable
  from the app and the admin). If X-2 passes: the gateway forwards requests to Navidrome with the trusted reverse-proxy header (secret
  header name, `ND_EXTAUTH_TRUSTEDSOURCES` = the gateway only) so the app never stores the password. If it fails: keep Subsonic tokens
  for proxied Navidrome calls only. Then the **one-way mirror**: Encore playlists and likes → Navidrome playlists/stars for songs with
  files, acting as each user via the header.
* **Acceptance.** The app's secure storage holds no password after sign-in; revoking a device signs it out ≤ 15 s; a Subsonic app (e.g.
  Symfonium) sees the mirrored playlists.

## P3-04 — Remove Docker-socket control, Firefox, Google sign-in; park the rest — Size S
* **Why.** C5, C6, Q5/Q6 in `../02`.
* **Do.** No Docker socket mounted anywhere; no browser container; no Google/YouTube account pages; a cookies file remains an
  Advanced environment setting documented with the risk. Quality, recommendations and the Jam hub are not in the default compose file yet:
  phase P4 brings them back as modules (their old code is in `server/legacy/`).
* **Acceptance.** `grep -r docker.sock server/deploy` empty; admin pages have no YouTube account section.

## P3-05 — Install script, `encore.local`, `encore` CLI — Size M
* **Why.** ADR-R7; owner has never used Docker and does not expect users to.
* **Do.** `server/deploy/install.sh` (served at a stable URL): checks 64-bit Linux (Debian/Ubuntu first), CPU arch, RAM ≥ 2 GB, disk
  ≥ 20 GB; asks before installing Docker from Docker's own repository; creates `/opt/encore` (compose + generated `.env` with
  secrets); asks for the music folder (default `/srv/music`, created if missing; existing folders are mounted read-only for scanning
  and `/music/Encore` read-write for kept songs); pulls images, starts, waits for health; enables mDNS (`avahi`) so the server answers
  at `encore.local`; prints the address and a terminal QR code. `encore` CLI: `status`, `update`, `logs`, `backup`, `restore`,
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
* **Acceptance.** On a fresh Ubuntu 26.04 VM (x86-64) and an ARM64 VM: one command → wizard reachable at `http://encore.local` from a
  phone on the same Wi-Fi in ≤ 10 minutes (download speed noted).

## P3-06 — Setup wizard and admin pages — Size L
* **Paper first:** build exactly the pages of `../15` §2 and §4; first add drawings of each page in the design tokens with the
  illustrations of `../16` to the PR and get the owner's OK on the drawings before code. The setup code of `../15` §1 is required.
* **Why.** US-01, US-02, US-03, US-40, US-42, US-51.
* **Do.** Wizard: owner account (creates the Navidrome admin and the owner as a person), server name, music folder check, machine and
  line test (CPU, disk, download/upload, YouTube reachability) with plain results, optional away-from-home (Tailscale Funnel with
  screenshots, key paste, self-check, key-expiry warning), first invitation (link + QR). Admin pages: Home (health in plain words),
  People (invite, reset password, lock, remove, devices), Storage (space, kept songs, free-space floor, "remove songs nobody saved"),
  Away from home, Updates (version, "run `encore update`"), Advanced (YouTube pace, background speed limit, cookies note).
  Reuse the design tokens (`app/lib/design/tokens.dart` → CSS, as the old admin did).
* **Acceptance.** J-14; every page passes the screen checklist (`../07` §10) at 360 px width and on a desktop browser.

## P3-07 — Clean-machine proof — Size S
* **Do.** Follow the website guide word for word on fresh VMs (x86-64 Ubuntu 26.04, Debian 13, ARM64), a SLOW-profile VM, and once
  with the line throttled to 10/1 Mbit/s; time each step; fix the guide where reality differs.
* **Acceptance.** J-14 ≤ 15 minutes on TYPICAL, ≤ 30 on SLOW; the guide matches what happened.

## P3-08 — Updates with rollback, yt-dlp freshness, backups, moving computers — Size L
* **Why.** `../22`.
* **Do.** `encore update` with automatic rollback; the runtime yt-dlp/ytmusicapi/Deno updater with the 24-hour rule, hashes and the
  canary; nightly backups (databases, settings, federation key) with retention; `encore backup/restore`, `--full` and installer
  `--restore`; CI that restores a real backup nightly; owners' in-app "needs you" notices; `encore stats`.
* **Acceptance.** A forced bad update rolls back by itself; a yt-dlp release that fails the canary is not used; moving the dev VM's
  server to a fresh VM keeps phones signed in and friends on other servers connected.
* **Slices (L task, split 2026-10-23).** **P3-08a done:** the weekly from-scratch image rebuild (PR #7). **P3-08b built and run for real (PR #9, `../evidence/c04-ytdlp-self-update.md`):** the in-server yt-dlp updater as designed in `../11` ADR-R39
  (pointer + child-process canary on the production path, restart only when quiet and at most once per version, one way to run yt-dlp); it reaches a server with the next `encore update`. Later slices: `encore update` with automatic rollback; the same pattern for
  `ytmusicapi`; `encore stats`; the in-app "needs you" notices.

## P3-09 — Security and privacy as written (server + app) — Size M
* **Why.** `../21`.
* **Do.** Roles and the privacy matrix enforced server-side with one test per cell; credential rules (device tokens, one-time codes,
  rate limits, locks); route exposure per §3; "Your data" export and "Delete my account"; the explicit-songs setting; an optional
  per-person storage cap (when reached: that person's new saves stay playable by streaming but are not kept, and the Host is told); a fresh-agent
  security review against `../21` before P5.
* **Acceptance.** Every privacy-matrix test passes; a scripted attacker run (wrong passwords, admin over the public address, forged
  federation request, reused invite) is refused as specified.

## P3-10 — Devices, settings and the Host's safety nets (server + app) — Size M
* **Why.** `../26` §4–6, H46.
* **Do.** "Add a device" QR from a signed-in device; settings stored per person on the server (device-only ones excepted); on a new
  device "Download the same playlists as on <old device>?"; revoke a lost device from another device or the admin (downloads stop
  playing after revocation); `encore reset-password <name>` for a Host locked out; the wizard and admin suggest a second owner; weekly
  disk health (SMART) with plain warnings.
* **Acceptance.** A new phone signed in by QR from the old one has the same settings and offers the same downloads; a revoked phone stops
  playing within one app start; a simulated failing disk (SMART test data) shows the warning.

## P3-11 — The Tinkerer's door — Size M
* **Why.** `../27` §3; persona "Tinkerer" (`../03` §2).
* **Do.** Attach Encore to an **existing Navidrome** (URL + an administrator login; Encore then needs read access to the music folders and
  write access to its own `Encore/` folder) instead of starting its own; an install path with plain Docker Compose and a documented
  `.env`; documented examples for an own domain behind Caddy, Traefik and nginx; publish the OpenAPI file of `../17` with the docs.
* **Acceptance.** On the dev VM, Encore attaches to a separately installed Navidrome 0.64.2 and all P2 journeys pass; the Compose-only
  path works from the docs alone.

## P3-12 — The first outside user (a friend on the owner's server) — Size M
* **Why.** Owner, 2026-10-22: a friend will use Encore daily from outside the owner's home and report bugs and dislikes (`../11` ADR-R33).
* **Do.** (1) Prove `encore funnel on` end to end on the real deployment and that an invitation made there opens for somebody who is not on the
  home network. (2) `encore backup` and a nightly backup of the Encore database (SQLite online backup, seven kept, outside the container's
  own volume), `encore restore`, and a restore tried on a clean machine. (3) *On hold (R35):* an in-app report; the friend messages the owner and can paste Diagnostics > Copy report. (4) A one-page friend's guide (`docs/guides/friend.md`): get the app, tap the
  link, sign in, what to expect, how to report. (5) Measure what two daily users do to the single home address YouTube sees: count the
  look-ups per day per person; the pacing and the rest already protect it; write the next step (a cookie or another way out, `../04` §5).
* **Done so far.** Item (2): `encore backup`, `encore restore`, `encore autobackup` and the Python copy tool are written with tests; not yet run on a machine. Item (2) is proved on real machines (`docs/evidence/c02-backup-restore.md`). Item (1): `encore funnel on|off|status` was rewritten after reading a real Tailscale 1.98.9 client's help (no per-site `off`: it resets only when Encore is the only site, otherwise changes nothing and says so) and its control flow was run against a stand-in `tailscale` on the VM in 11 situations (free 443, 443 taken, all public ports taken, Funnel not enabled on the tailnet, already on, off, never on); the text it reads is tested against Tailscale's documented output; **not yet run with a real sign-in** (the owner's). Item (5): the server counts how many times it asks YouTube per day and tells the log every 25th time (`encore logs | grep look-ups`), and when YouTube refuses; no person, no song; the five days of two people's use will say what the number is. Item (3): built, then put on hold (branch `parked/in-app-report`). Item (4): `docs/guides/friend.md` is a draft.
* **Don't.** Show the owner what the friend listens to. Update the server while he is likely to be listening without saying so.
* **Acceptance.** The friend installs the app, joins by the link from outside the owner's home, listens for a week; a backup of his data is
  restored on a second machine and his playlists are all there; his first problem report reaches the owner with the report attached.
* **Depends on.** P3-05 (done as a slice), the owner's Tailscale sign-in. **Size.** M.

