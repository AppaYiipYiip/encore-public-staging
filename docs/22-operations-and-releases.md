# 22 — Running Encore for years: updates, freshness, backups, moving, capacity

Why: a Host installs Encore once and expects it to keep working for years without knowing anything about servers. None of this was
designed: the old stack updated by hand-run scripts, yt-dlp freshness depended on container restarts, and backups were an option.

## 1. Updating the server

* **`encore update`** (and a button-free notice in the admin: "Encore 1.3 is available — run `encore update` on the server"):
  1. back up the databases (§3) → 2. pull the new image → 3. start it; the server runs its migrations (`18` §1) → 4. wait until it answers (up to 3 minutes) → 5. on failure, say so:
  the old deployment file is kept as `compose.yaml.before-update` and the backup of step 1 is in the backup folder. **Planned, not built:** pinned image versions
  and an automatic roll back to the previous images and the pre-update backup.
* Releases: a **monthly** feature release, **hotfix** releases any time, never a breaking API change without the two-release overlap
  (`17` §1). Release notes in plain words.
* Optional "update automatically at night" (off by default; the Host chooses in the admin).

## 2. Keeping YouTube working (yt-dlp freshness) — the one part that cannot wait for a monthly release

YouTube changes often; a stale yt-dlp breaks "play anything" for every Host the same day.
* The image ships the newest yt-dlp at its build time (not pinned; rebuilt from scratch every week by CI, and each build's run page says which version it carries).
  The server also keeps a **runtime copy** in `/data/tools/yt-dlp/` that it updates itself (**built, P3-08b; decision and reasons: `11` ADR-R39**): a daily check of
  PyPI at a random time; only releases **older than 24 hours** (protects against a broken or malicious release); the wheel's sha256 must match PyPI's; stored beside the
  current one; a **canary** must pass before anything changes. The canary runs in a child process with the new wheel first on its path, through the server's own
  `YoutubeSource` (same format selector, same fast client), on one fixed, long-lived video that is not music (Blender Foundation's open film "Big Buck Bunny"; the first choice, YouTube's first upload, is not playable on the song path), and reads 64 KB of audio. It is a look-up like any other: it takes the pacer's
  turn, does not run while the server rests, is counted, and a refusal during it starts the rest; at most four runs a day. On a pass a pointer file is written and the
  server **restarts itself, but only once nothing has gone through it for a minute and never by force**; Docker starts it again on the new copy (`/info` says which
  version runs and which waits). On a fail the server stays on its copy; if the running copy fails the same canary, YouTube is the problem, the release stays eligible
  and the state is `degraded`. Every use of yt-dlp follows the pointer (the playlist reader runs `python -m yt_dlp`, not a `yt-dlp` command). `ENCORE_AUTO_TOOLS=0` switches it off.
  Run for real on the dev VM, including the failure drills: `evidence/c04-ytdlp-self-update.md`.
* If every copy fails the canary, the admin Home says "Songs from YouTube are not working right now; Encore will try again every
  hour", and the app says the same when a catalogue song fails.
* The same rule is meant for `ytmusicapi`, the PO-token provider (if enabled) and Deno (not built: the first slice is yt-dlp only).

## 3. Backups and restore

| What | When | Where | Size |
|------|------|-------|------|
| `encore.db` and Navidrome's database, each copied with SQLite's online backup (a throwaway container of the Encore image, one run per database, each checked with SQLite's integrity check), plus a copy of `.env` and `manifest.txt`, in one `encore-backup-<time>.tar.gz`. The server's own identity key (`11` ADR-R40) lives inside `encore.db`, so it is in the archive | nightly at about 03:30 (up to ten minutes later by chance; a systemd timer the installer switches on; `encore autobackup on\|off\|status`), the newest 7 are kept | `/opt/encore/backups` on the same disk (default, mode 700, files 600) or the folder `ENCORE_BACKUP_DIR` in `.env` names (another disk, a share) | MBs |
| Music files | never automatically (Host's choice, ADR-077) | — | GBs |
* `encore backup` makes one now; `encore restore <file>` checks it, asks, stops the servers, **sets the current files aside** in `before-restore-<time>/` (never deletes them),
  puts the two databases back, starts again and waits until the server answers. The decision and its reasons: `11` ADR-R37; run on real machines, including a move to another
  computer: `evidence/c02-backup-restore.md`. A backup is also taken before every `encore update`.
* **Planned, not built:** CI that restores a real backup every night on a fresh server and compares counts (today restore was proved by hand, `evidence/c02-backup-restore.md`).
* Backups contain secrets (`.env` holds the music server's administrator login): stored with owner-only permissions. **Planned, not built:** the admin warning when the backup folder is on
  a share others can read.

## 4. Moving to a new computer

Today: `encore backup` → copy the file **and the music folder** (the music is not in the backup, nor the songs Encore kept in `Encore/` inside it) → on the new computer install
Encore, then `encore restore <file>` (same Encore version or newer; the install-time password is replaced by the original one; a device sign-in made on the old computer is still accepted). The public address
(Tailscale) is set up again on the new computer with `encore funnel on`. **Planned, not built:** `encore backup --full` (databases + settings, optionally a list of the music
folders) and the installer's `--restore <file>` option in one step; a guide page with screenshots (P5).

## 5. Health and problems

* The admin Home shows each part (music server, YouTube, away-from-home address, disk, backups, updates) as OK / needs you / broken, in
  words, with the action.
* Owners also get an in-app notice on their phone for "needs you" items (disk 90 % full, backups failing, the Tailscale sign-in on the server's computer running out,
  YouTube not working for 24 h).
* Logs: rotated, capped (50 MB total), no personal data (`21` §2); `encore logs` shows the last hour in plain text.

## 6. Capacity: what a Host's machine can carry (to measure in X-8 and P3-07, then print on the website)

| Machine | Expected (to verify) |
|---------|----------------------|
| Raspberry Pi 4 (4 GB) / 2-vCPU VM | 5 people streaming at once, 1 import being matched, background YouTube look-ups spaced 6 to 18 s apart (about 300 an hour at most; an hourly cap is not built, see `04` §5), search ≤ 1 s |
| Mini-PC / old laptop (4 cores) | 20+ streaming, 3 imports, everything else comfortable |
| Away from home | limited by the Host's **upload**: about 1 listener per 150 kbit/s (Opus 128 + overhead); the wizard prints the number (`15` page 4) |
The keeper, the loudness measurer (P1-13) and recommendations run as **background** work that yields to people playing (`04` §10).

**Measured, 5 Nov 2026, for the owner's target of 1 to 20 people on one server (or more):** `docs/tasks/AUDIT-BUILT-2026-11-05.md` (B-10, B-18, B-19) has the numbers. With 20 simulated phones the server answers about 320 calls a second (one Python process is the limit), but **today's code lets some calls wait 2.5 s at the 95th percentile and up to 12 s**, because every signed-in call takes the database's write lock and SQLite does not queue waiting callers fairly; a drafted fix (held, not applied) brings that to 135 ms and 175 ms. The measuring tool is `server/encore_server/tests/bench/bench_users.py` on the branch `held/server-db-lock`. **Not measured:** audio streaming, YouTube look-ups, a large import running at the same time (X-8).

## 7. Scanning without storms

Navidrome rescans when files change. The keeper writes many files during an import, so: write each file to a temporary name and rename
it into place; batch kept files and ask Navidrome for **one** scan per batch (or rely on its file watcher: **verified on 0.64.2**, the log shows "Watcher: Scan completed" with a selective rescan of the changed
folder in 0.2–0.4 s); never trigger a full scan for one song.

## 8. The host machine itself

The installer offers (default yes) automatic security updates of the operating system (`unattended-upgrades` on Debian/Ubuntu) and
sets the clock to sync (NTP). Encore starts on boot (container restart policies). Power cuts: SQLite in WAL mode, files written by
rename, so nothing half-written is ever served.
