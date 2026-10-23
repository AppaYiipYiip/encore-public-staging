# C-02 — Backup and restore on real machines (2026-10-23)

**What.** `encore backup`, `encore restore FILE`, `encore autobackup`, and the backup that `encore update` takes first (`docs/11` ADR-R37).
**Where.** VM 107 (Ubuntu 26.04, 2 vCPU, 3 GB), installed from the branch image by the guide's steps, then the same VM reset to a clean snapshot
and installed again as a "new computer". The databases were marked with two small things each (an Encore playlist and an invitation; a music-server
playlist), made through the servers' own APIs, never by editing files. Passwords were never printed.

## What was proved

| Check | Result |
|-------|--------|
| The installer switches the nightly backup on and makes the first one | timer enabled (`encore-backup.timer`, about 03:30 with up to 10 minutes of chance); the first archive existed when the installer ended; `encore status` shows "Last backup" |
| The timer's own service, started by hand | exit 0, a new archive; the service carries `ENCORE_DIR` (an install outside `/opt/encore` is found) |
| What an archive holds | `encore.db`, `navidrome.db`, `env`, `manifest.txt`: no `-wal` or `-shm` files (the first run had them: fixed, with a test that fails without the fix) |
| Who owns what | the backups folder 700 and the archives 600, root only; the live `encore.db` stays owned by the server's user and the music server's files by root, before, during and after a backup |
| **Backups in the middle of writes** | a loop of 162 rounds (make and delete an Encore playlist, make a music-server playlist) with 3 backups run during it: **0 failures**, all 3 backups exit 0 |
| Same machine: make marks, back up, change things, `encore restore` | 9.6 s; the marks made before the backup are back in **both** databases, the changes made after it are gone, the invitation count is right |
| Writes after a restore | possible in both servers (the restored `encore.db` has the server user as owner: a root-owned copy would have been read-only to the server) |
| Only the newest 7 are kept | after more than 7 backups, 7 files, the oldest gone |
| A damaged archive, a file that is not a backup, a backup with a damaged database inside | each refused in a sentence, **before** anything is stopped or moved; the install keeps running and nothing is set aside |
| **Another computer** | backup copied off the VM; the VM reset to the clean snapshot and Encore installed on it with the **same username and a different password**; `encore restore` there (9.8 s): the **original** password signs in, the install-time password is refused (HTTP 401), the marks are all there, **a device token made on the old machine is still accepted** (a phone stays signed in after a move), writes work |
| `encore update` | takes a backup first and says so (5.7 s when there is nothing newer) |

## Found by these runs, and fixed

| Found | Fix |
|-------|-----|
| The archive held `-wal` and `-shm` files: a restore that puts back only the database files would silently lose whatever was still in the log | every copy is converted to one self-contained file (journal mode back to the default) before it is checked and packed |
| The copy ran as root next to live databases: a root-owned `-wal`/`-shm` created in a race with the server would stop the server writing | one run per database, each as the account that owns it |
| A restore made by root would give the server a database it cannot write to | the restored database gets the owner of the file it replaces |
| `uninstall --everything` removes the backups too, without saying so | it says so; the guide says to copy them away first |
| The nightly service ignored an install that is not in `/opt/encore` | the unit carries `ENCORE_DIR` |

## Times worth knowing

The installer took **9 min 40 s** (the branch image, interactive) and **14 min 17 s** on the second, "new computer" install, against 5 min 30 s on the
unattended runs of 2026-10-22. The cause was measured (see `c01`): the host's total download is held to 10 Mbit by the owner's dashboard and shared with
other downloads, so a fresh install got about 0.5 MB/s. The installer now says how big each download is and logs the time of each phase.

## Not proved here

The nightly timer firing by itself at night (it is armed and the service run by hand works; the first night on the owner's server is the real test);
a second copy of the backups off the computer (the hypervisor's VM backup covers it today); restoring a backup from an older Encore version into a
newer one with a changed database layout (no such change exists yet; `restore` refuses an archive format it does not know).
