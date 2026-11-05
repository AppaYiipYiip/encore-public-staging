# Install Encore on a fresh computer (the install test)

> **This is the command door (D-61).** A button installer is the other door (P3-23, designed in P3-21); until it exists this is the only way in, and gate 2 (P3-18) waits for the button door. It also needs a GitHub login while the image is private (audit B-1; P3-26 decides what a person without one does).

This is the guide for the first real install, done the way a user would do it. It is an **install test**, not the daily-driver release:
the setup wizard, the admin pages, backups, update rollback and ARM computers are not built yet (list at the bottom). Things that go
wrong are what this test is for: write down what you see, even small things.

## What you need

* A **fresh computer or VM with Ubuntu Server or Debian**, 64-bit Intel/AMD, **2 GB memory or more**, **6 GB free disk or more**, on the
  internet. Nothing else has to be installed; the installer asks before it installs anything. On a computer below a limit the installer stops at the very start, before it
  installs anything, and says in one sentence what is short, for example "This computer has 1024 MB of memory; Encore needs at least 2 GB." or "There is 4 GB of free space where
  Encore keeps its files; it needs at least 6 GB." (`deploy/install.sh` lines 135-140; the same goes for a system that is not Ubuntu or Debian or a computer that is not 64-bit Intel/AMD).
* Your **GitHub login** (the Encore download is private for now, so the installer signs in as you).
* About **10 to 15 minutes**, nearly all of it downloads (about 330 MB, plus Docker if it has to be installed): on a quick line it is 5 to 6 minutes, on a slow
  one longer. The measured times are in the table at the end.

## The steps

**1. Sign in to GitHub on that computer.** In its terminal:

```
sudo apt-get update && sudo apt-get install -y gh
gh auth login --scopes read:packages
```

Choose *GitHub.com*, *HTTPS*, *Login with a web browser*. It shows a one-time code and a link: open the link on any device, type the code,
approve. (`read:packages` is the permission to download Encore's image.)

**2. Download the installer and run it.**

```
gh api -H "Accept: application/vnd.github.raw" "repos/AppaYiipYiip/encore/contents/server/encore_server/deploy/install.sh?ref=main" > install.sh
sudo bash install.sh
```

(It uses the GitHub login from step 1: the person who typed `sudo`. **The installer keeps that sign-in for the image** (root's Docker login for `ghcr.io`), because `encore update` needs it while the image is private. To remove it: `sudo docker logout ghcr.io` and `gh auth logout`; after that `encore update` cannot download until you sign in again.)

It asks, in this order:

| Question | What to answer |
|----------|----------------|
| What should this server be called? | Anything; people you invite see it. |
| Your username / a password (twice) | Your own Encore login. 8 or more characters. |
| Where is your music? | A folder with your music (it is only read), or press Enter for `/srv/music` and add music later. |
| Install Docker? (only if it is missing; **asked last**, after the music folder) | Yes. Docker is what runs Encore. It takes a minute or two, so stay until it is done. |

Then it downloads Encore, starts it and prints the address and your username to type into the app, the commands for looking after the server (there is no admin page in the browser yet), and what `encore funnel on` is for (optional; it needs a free Tailscale account). It prints no QR code: the one it used to print opened the music server's own page in a phone's browser and the app cannot scan it; a code that carries an Encore setup link comes with the pairing link (AUDIT F16).

**3. Sign in on the Encore app.** On a phone on the same Wi-Fi: Encore app, *Connect*, the address it printed (like `192.168.1.23:4533`),
your username and your password. Your library arrives in a few seconds.

**4. Try the things that matter.**

* Search for a song you do not have and play it (it streams from the web in a few seconds; playing does not save it).
* Like a song, make a playlist; then open the app on a second phone with the same login: they show up there within a couple of seconds.
* *Your server > Invite someone* makes a link. (On the home network only until step 5 is done; the dialog says so.)
* Import a playlist from Spotify or YouTube Music: **a short one, 10 songs or fewer**, please. Many look-ups in a row get your home internet
  address refused by YouTube for a day.

**5. Use it away from home (optional, needs your Tailscale login).**

```
encore funnel on
```

It installs Tailscale if the computer has none, shows a link to sign in, and then gives you an `https://…ts.net` address that works from
anywhere. On an Encore server the signed-in phone learns that address from the server by itself when the app next starts, and invitation links
use it (close and open Encore again; if you run a plain music server, add the address under *Your server > Add an address*). Your Tailscale account must have
HTTPS and Funnel switched on (https://login.tailscale.com/admin/dns): if not, the command says so. **This step ran for real once, on 2026-11-03** (`docs/evidence/c05`): the command installed Tailscale, printed a sign-in link, and the public address answered; a phone on mobile data has not been tried. Tell me exactly what it printed.

## Looking after it

```
encore status                  is it running, at which address
encore logs                    what the server says (Ctrl-C to stop)
encore update                  the newest version (a backup is made first)
encore backup                  a copy of your accounts, playlists and likes, now (also made every night)
encore restore FILE            put such a copy back (what is there now is set aside, not deleted); you type  restore  to confirm, or add --yes in a script
encore uninstall               remove Encore; your music and Encore's data stay
encore uninstall --everything  remove Encore's data too (never your music)
```

Backups are in `/opt/encore/backups` (the newest 7, readable by the administrator only; each holds a login that Encore needs, so keep copies
private). Your **music** is not in them: it is your own folder, which Encore only reads. A backup is also what moves Encore to another
computer: copy the backup file **and your music folder** (with the `Encore/` folder inside it, where songs Encore kept are), install Encore there
pointing at that folder, then `encore restore FILE`. `encore uninstall --everything` also deletes the backups, so copy them away first if you want to keep them.

Running the installer again is safe: what is there is kept and brought up to date.

**Songs from YouTube keep working by themselves.** The part of Encore that fetches songs from YouTube (yt-dlp) breaks now and then when YouTube changes.
Once a day the server looks for a newer version, tries it on one open film (it asks YouTube for the film's sound and reads 64 KB of it; that counts as one of the
server's look-ups) and, only if that works, switches to it. The switch is a restart of about 2 seconds, and it happens only after **a full minute in which nothing is
playing, downloading or being worked on**; phones reconnect by themselves. It never happens while somebody is listening, and at most once per new version.
`encore logs` says what it did (`encore logs | grep yt-dlp`). To turn it off (you want to choose versions yourself, or the server has no internet except
for songs), add the line `ENCORE_AUTO_TOOLS=0` to `/opt/encore/.env` and run `encore update`; Encore then uses the yt-dlp that came with the image.

## If something goes wrong

If the window is closed or the connection drops, the install carries on by itself; if the power goes or you press Ctrl-C, run the same two lines again:
the installer notices that your account was not made yet and asks only for your username and password. Every message says what to do. The full record of an install is `/var/log/encore-install.log` (only the administrator can read it, so  `sudo cat /var/log/encore-install.log`; it never contains a password). Send me that
file and what you saw. To start over completely: `encore uninstall --everything`, then step 2 again.

## What is not in this test

The browser setup wizard (questions are asked in the terminal instead), the admin pages, update with rollback, ARM
computers (Raspberry Pi), `encore.local` (use the numbers address), and everything in phases P3 to P5 of `docs/tasks`. The decisions
behind what is here are `docs/11-decision-log.md`, ADR-R19 to R32.

## Measured on a clean VM (Ubuntu 26.04, 2 vCPU, 3 GB)

See the table filled in by the proof runs: `docs/evidence/README.md#c01`.
