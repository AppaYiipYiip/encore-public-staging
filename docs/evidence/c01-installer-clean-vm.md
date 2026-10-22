# C-01 — The installer on a clean machine (2026-10-22)

**Machine.** A VM made from the Ubuntu 26.04 cloud image (2 vCPU, 3 GB memory, 32 GB disk, no Docker, no `gh`), snapshotted clean and rolled
back before every run. The server image came from GitHub's container registry (private), pulled with the owner's GitHub login.
**What was followed.** `docs/guides/install-test.md`: install `gh`, sign in, download `install.sh` with `gh api`, run it.

## Times

| Run | What | Time |
|-----|------|------|
| 1 | From clean, unattended (`--yes`, password from a file) | **370 s** (6 min 10 s) |
| 2 | The same again from clean | **330 s** (5 min 30 s) |
| 3 | Installer run again on the installed machine | **4 s**, `.env` byte for byte unchanged, containers kept running |
| 4 | From clean, **interactive**, the guide followed as written (`ref=main`, no tag): `gh` installed and signed in, `install.sh` downloaded, every question answered in the order asked, the password typed at hidden prompts | **577 s** (9 min 37 s) for the installer, 10 min with the `gh` steps; exit 0 |
| 4b | The same machine, `encore uninstall` then the installer again over the kept data | **12 s**; the owner signs in with the same password; `.env` still mode 600 |
| app | Fresh sign-in on a phone to the new server | 6 s |
| app | The first song on a brand-new server (cold) | about 8 s from the tap to sound |

The two slow parts are Docker's own installation (about 2 minutes) and the download of the two images (about 1.2 GB on disk, roughly 500 MB
over the wire). Acceptance in `docs/tasks/P3-05` is "10 minutes at most": **met, but only just on the interactive run** (9 min 37 s against
5 min 30 s and 6 min 10 s on the two unattended runs earlier the same day). The extra four minutes were all before the containers started
(Docker and the image downloads), so it is the line, not the installer; on a slower line the 10 minutes will be missed, and the installer's
own "about 500 MB" line and the guide's "about 10 minutes" say so. The first interactive attempt did not finish because the test driver
answered the questions in the wrong order (it waited for the Docker question first); the installer itself was waiting correctly. Fixed in the
driver, not in the installer.
On the fresh install the app signed in in about 2 s, the empty Home said what to do next, a song the server did not have (searched as
"Beach House Space Song") played from the top result.

## The `encore` command, every verb, from an ordinary user

| Command | Result |
|---------|--------|
| `encore status` | both services running and healthy, the address, the music folder; asks for administrator rights by itself |
| `encore update` (nothing newer) | 3 s, "up to date", compose file and command replaced from the image |
| `encore stop` / `encore start` | 1 s / answering again after 8 s |
| `encore uninstall` | containers and the command removed in under a second; `/opt/encore` (data) kept |
| installer again over the kept data | 12 s, the owner is not asked for again |
| `encore uninstall --everything` | `/opt/encore`, the command and the Encore image removed |
| **The music folder** | a canary file in `/srv/music` and one in `/srv/music/Encore`: **byte for byte identical before and after** every step above |

## What the install leaves behind

* `/opt/encore/.env` and `/var/log/encore-install.log`: mode 600, root only. The owner's password is in **neither** (searched for: 0 matches).
* Only Encore's port (4533) is published; the music server is reached through Encore and has no port of its own.
* Docker, and the GitHub login in root's Docker settings (needed for `encore update` while the image is private), stay when Encore is removed.
  Disk: 1.26 GB of images; 26 of 28 GB still free on this VM.

## Found by these runs, and fixed (each has a test or a check)

| Found | Fix |
|-------|-----|
| Ubuntu 26.04's `sudo` ignores `-E`: the installer never saw its variables | it asks the person who typed `sudo` for their GitHub login itself; `--owner-password-file` |
| A missing password was noticed after two minutes of installing Docker | questions come first |
| A stray `/dev/tty` error line; Docker installed without saying so | fixed |
| The `encore` command needed `sudo` typed each time | it asks for administrator rights itself |
| **A brand-new, empty server never "synced": the music server answers an empty library with error 70 and the app treated that as a failure** ("We'll keep trying to reach your server", "Library not synced yet" for ever) | error 70 on the browse calls is an empty library (app, with a test) |
| The empty Home said a song "is added to your library" (it is not) and offered the old "What does my server need?" page | words fixed for Encore servers |
| A link to a **new** server tapped on a phone signed in on another server said "you already have an account here" | only a link to a server the phone already has an account on says that; any other opens the join screen |
| Joining made a device on the server that the app ignored, then signed in for a second one: two devices for one phone | the join's device is kept |
| `uninstall --everything` left the image behind | image name read before the settings file is removed |
| On GitHub: server tests could not find `tests` under plain `pytest`; two shell lines flagged by shellcheck; the secret scan lacked a permission on pull requests; the real-music-server tests hit the music server's sign-in limit; 12 screen-picture tests failed on Linux | all fixed (ADR-R31, `docs/tasks`) |

## Not proven here

`encore funnel on` (needs a Tailscale sign-in: the owner's), arm64 computers, installing next to an existing Navidrome/Plex/Tailscale (the
"try it beside what you have" constraint in P3-05), the browser wizard, backups and restore (P3-12).
