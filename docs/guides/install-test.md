# Install Encore on a fresh computer (the install test)

This is the guide for the first real install, done the way a user would do it. It is an **install test**, not the daily-driver release:
the setup wizard, the admin pages, backups, update rollback and ARM computers are not built yet (list at the bottom). Things that go
wrong are what this test is for: write down what you see, even small things.

## What you need

* A **fresh computer or VM with Ubuntu Server or Debian**, 64-bit Intel/AMD, **2 GB memory or more**, **6 GB free disk or more**, on the
  internet. Nothing else has to be installed; the installer asks before it installs anything.
* Your **GitHub login** (the Encore download is private for now, so the installer signs in as you).
* About **10 minutes**. The measured time is in the table at the end.

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

(It uses the GitHub login from step 1: the person who typed `sudo`.)

It asks, in this order:

| Question | What to answer |
|----------|----------------|
| Install Docker? (only if it is missing) | Yes. Docker is what runs Encore. |
| What should this server be called? | Anything; people you invite see it. |
| Your username / a password (twice) | Your own Encore login. 8 or more characters. |
| Where is your music? | A folder with your music (it is only read), or press Enter for `/srv/music` and add music later. |

Then it downloads Encore, starts it and prints the address, your username and a QR code.

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
anywhere. Add that address in the app under *Your server > Add an address*, and invitation links will use it. Your Tailscale account must have
HTTPS and Funnel switched on (https://login.tailscale.com/admin/dns): if not, the command says so. **This step is written but has not been
proven end to end yet**; tell me exactly what it printed.

## Looking after it

```
encore status                  is it running, at which address
encore logs                    what the server says (Ctrl-C to stop)
encore update                  the newest version
encore uninstall               remove Encore; your music and Encore's data stay
encore uninstall --everything  remove Encore's data too (never your music)
```

Running the installer again is safe: what is there is kept and brought up to date.

## If something goes wrong

Every message says what to do. The full record of an install is `/var/log/encore-install.log` (it never contains a password). Send me that
file and what you saw. To start over completely: `encore uninstall --everything`, then step 2 again.

## What is not in this test

The browser setup wizard (questions are asked in the terminal instead), the admin pages, backups and restore, update with rollback, ARM
computers (Raspberry Pi), `encore.local` (use the numbers address), and everything in phases P3 to P5 of `docs/tasks`. The decisions
behind what is here are `docs/11-decision-log.md`, ADR-R19 to R32.

## Measured on a clean VM (Ubuntu 26.04, 2 vCPU, 3 GB)

See the table filled in by the proof runs: `docs/evidence/c01-installer-clean-vm.md`.
