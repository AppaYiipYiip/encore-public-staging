# c06: the install by the guide, on a bare machine (3 November 2026)

**What this is.** The first measured install of Encore by `docs/guides/install-test.md`, on a VM that had only Ubuntu 26.04.1 (no Docker, no `gh`, no Encore), reached from a PC on the same network. The terminal was driven by a script, because the installer reads its answers from `/dev/tty`; a person would type the same answers. **Not walked here:** step 1's browser sign-in (a token was piped over ssh stdin instead and removed afterwards), step 3 (a phone connecting), step 5 (`encore funnel on`), an update to a really newer image. It is one part of the release-candidate walk (`b11`), not the whole of it.

## Result: the install by the guide on a bare VM (3 Nov 2026, Ubuntu 26.04.1, 2 vCPU, 3 GiB, image :main from 589d8e4)

**The install worked, by the guide, from a bare machine: exit 0, "Encore is ready", 9 min 51 s** (the time answering is in it; the terminal was driven by a script, `drive_install.py`, because the installer reads from /dev/tty). Not walked: step 1's browser sign-in (a token over ssh stdin was used instead, see Step 1), step 3 (a phone connecting), step 5 (`encore funnel on`).

| Measure | Value |
|---|---|
| step 1 (apt install gh, token sign-in) | 40 s |
| step 2a download installer | 1 s |
| install | 9 min 51 s; last screen word for word in `install-output.txt` |
| memory at the end | 554 MB used of 2,967 MB (2.4 GB cache), 2.4 GB available |
| disk after install | 3.9 GB used, 27 GB free; images: encore-server 937 MB, navidrome 348 MB |
| answers at the printed address | yes: `GET :4533/encore/api/v1/info` 200 from another machine (name, version, yt-dlp 2026.10.26, YouTube state ok; no people, no music) |
| a stranger's browser | `/` redirects to `/app/`, the music server's own login page, title "Navidrome", no word "Encore" (as the installer's last screen warns; D-41 holds) |
| `encore status` | running (healthy) x2, port 4533 answers, last backup shown |
| `encore backup` | 3 s, 36 KB, mode 600 root |
| `encore restore` | 10 s; proof with data a person made: playlist P1 before the backup, P2 after; after the restore P1 present, P2 gone, old state set aside in `before-restore-*`, a session made after the backup is invalid and a new login works |
| `encore update` | 6 s: backup first, "up to date (0.1.0)"; a real newer image was **not** tested (none exists) |
| secrets | the install log has no password and no token (0 hits); after the test: `gh auth logout`, `docker logout ghcr.io`, password file and driver deleted; `hosts.yml` 3 bytes, Docker auths `[]` |

### Findings (what the guide or installer got wrong, missing or confusing)
- **F1 (guide wrong).** The guide's question table lists "Install Docker?" first. The installer asks **name, username, password, password again, music folder, and Docker last** (install.sh:195-214). My driver, written from the guide, hung 11 minutes. A person just answers what is asked, but the table is wrong, and the Docker question coming last means a person may have walked away during the long Docker install.
- **F2 (guide incomplete).** "The full record of an install is /var/log/encore-install.log ... Send me that file": the file is root-only (mode 600); a person gets "Permission denied" without `sudo`. Say `sudo cat`.
- **F3 (design, private-image era).** The installer **leaves a GitHub token on the machine for good**: root's Docker credential for ghcr.io (written during the install; `encore update` depends on it). With the broad token used here it held more power than the installer needs. The guide does not say the sign-in stays, how to remove it (`sudo docker logout ghcr.io`, `gh auth logout`), or that after removing it `encore update` cannot pull. With a public image none of this exists; until then say it in the guide. Also: my cleanup check by text search (`gho_`) cannot see this credential (it is base64): check the `auths` list.
- **F4 (message).** `encore restore FILE` with no terminal dies with a raw bash line ("/dev/tty: No such device or address") then "Nothing was changed" (safe). `--yes` / `-y` exists (encore:258) but the guide never mentions it. Say "type restore to confirm; scripts: --yes", and make the no-terminal message plain.
- **F5 (small).** After `encore update` reports "up to date", the containers show an uptime of seconds: check whether an up-to-date update still restarts them.
- **Not findings:** the VM clock runs about 45 s ahead of this PC's, which made fresh containers look restarted (restart count 0).
