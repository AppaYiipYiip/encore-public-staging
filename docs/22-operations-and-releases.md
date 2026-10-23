# 22 — Running Encore for years: updates, freshness, backups, moving, capacity

Why: a Host installs Encore once and expects it to keep working for years without knowing anything about servers. None of this was
designed: the old stack updated by hand-run scripts, yt-dlp freshness depended on container restarts, and backups were an option.

## 1. Updating the server

* **`encore update`** (and a button-free notice in the admin: "Encore 1.3 is available — run `encore update` on the server"):
  1. back up the databases (§3) → 2. pull the new pinned images → 3. start them; the server runs its migrations (`18` §1) → 4. health
  check for 2 minutes → 5. on failure, **roll back automatically** to the previous images and the pre-update backup, and say so.
* Releases: a **monthly** feature release, **hotfix** releases any time, never a breaking API change without the two-release overlap
  (`17` §1). Release notes in plain words.
* Optional "update automatically at night" (off by default; the Host chooses in the admin).

## 2. Keeping YouTube working (yt-dlp freshness) — the one part that cannot wait for a monthly release

YouTube changes often; a stale yt-dlp breaks "play anything" for every Host the same day.
* The image ships the newest yt-dlp at its build time (not pinned; rebuilt from scratch every week by CI, and each build's run page says which version it carries).
  The server also keeps a **runtime copy** in `/data/tools/` that it updates itself (**not built yet**, P3-08): daily check of
  PyPI; only releases **older than 24 hours** (protects against a broken or malicious release); hash-checked; installed beside the
  current one; a **canary** (one fixed, obscure, never-cached song: resolve + 64 KB) must pass, else it stays on the previous copy.
* If every copy fails the canary, the admin Home says "Songs from YouTube are not working right now; Encore will try again every
  hour", and the app says the same when a catalogue song fails.
* The same rule applies to `ytmusicapi`, the PO-token provider (if enabled) and Deno.

## 3. Backups and restore

| What | When | Where | Size |
|------|------|-------|------|
| `encore.db` (`VACUUM INTO`), Navidrome's database (its own backup), `.env` and the server's federation key | nightly 03:30, keep 7 + 4 weekly | `/data/backups/` on the same disk (default) or any folder the Host picks (another disk, a share) | MBs |
| Music files | never automatically (Host's choice, ADR-077) | — | GBs |
* `encore backup` makes one now; `encore restore <file>` restores and restarts; **CI restores a real backup every night** on a fresh
  server and compares counts, so restore is never untested.
* Backups contain secrets (`.env`, the federation key): stored with owner-only permissions; the admin warns when the backup folder is on
  a share others can read.

## 4. Moving to a new computer

`encore backup --full` (databases + settings + federation key, optionally a list of the music folders) → copy the file and the music
→ on the new computer run the installer with `--restore <file>`. The public address (Tailscale) and the federation identity move with
it, so friends on other servers and installed phones keep working. A guide page with screenshots (P5).

## 5. Health and problems

* The admin Home shows each part (music server, YouTube, away-from-home address, disk, backups, updates) as OK / needs you / broken, in
  words, with the action.
* Owners also get an in-app notice on their phone for "needs you" items (disk 90 % full, backups failing, Tailscale key ending,
  YouTube not working for 24 h).
* Logs: rotated, capped (50 MB total), no personal data (`21` §2); `encore logs` shows the last hour in plain text.

## 6. Capacity: what a Host's machine can carry (to measure in X-8 and P3-07, then print on the website)

| Machine | Expected (to verify) |
|---------|----------------------|
| Raspberry Pi 4 (4 GB) / 2-vCPU VM | 5 people streaming at once, 1 import being matched, keeping ≤ 120 songs/hour, search ≤ 1 s |
| Mini-PC / old laptop (4 cores) | 20+ streaming, 3 imports, everything else comfortable |
| Away from home | limited by the Host's **upload**: about 1 listener per 150 kbit/s (Opus 128 + overhead); the wizard prints the number (`15` page 4) |
The keeper, the loudness measurer (P1-13) and recommendations run as **background** work that yields to people playing (`04` §10).

## 7. Scanning without storms

Navidrome rescans when files change. The keeper writes many files during an import, so: write each file to a temporary name and rename
it into place; batch kept files and ask Navidrome for **one** scan per batch (or rely on its file watcher: **verified on 0.64.2**, the log shows "Watcher: Scan completed" with a selective rescan of the changed
folder in 0.2–0.4 s); never trigger a full scan for one song.

## 8. The host machine itself

The installer offers (default yes) automatic security updates of the operating system (`unattended-upgrades` on Debian/Ubuntu) and
sets the clock to sync (NTP). Encore starts on boot (container restart policies). Power cuts: SQLite in WAL mode, files written by
rename, so nothing half-written is ever served.
