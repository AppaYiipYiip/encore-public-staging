# 15 — Setup and first run, on paper (every page before code)

Owner, 2026-10-21: *"did we already think of how many pages the setup would have, what each page would include? Everything should be
on paper before code."* This page is that paper. Agents build exactly these pages (tasks P3-05, P3-06, P2-10); a change to a page is
first a change here. Look and feel (art, motion, words): `16`. Stories: US-01…US-05.

Principles for every page: **one decision per page**; a sensible choice is already selected so "Continue" always works; every
optional page has "Skip for now"; plain words (no "Docker", "container", "port", "Navidrome", "Funnel"); a progress line
"Step 3 of 8"; back always possible; nothing is lost if the browser is closed (the wizard resumes where it stopped).

---

## 1. The Host's terminal (the command door)

> **D-61 (owner, 5 Nov 2026): this page describes the command door; the button door is designed in P3-21 and built in P3-23.** Nobody is required to open a terminal: the same installation can be made by an installer with buttons, and every Host action afterwards (update, back up, restore, reset a password, switch an add-on) is a button on the admin pages AND an `encore` command that calls the same operation. Both doors are first-class.

The website shows three steps: (1) install Ubuntu Server on the spare computer (link + video), (2) paste one line, (3) open the link it
gives you. What the terminal shows after pasting `curl -fsSL https://<get address> | sudo sh`:

```
  ♪  Encore — installing your music server

  ✓ This computer: 64-bit Intel/AMD, 8 GB memory, 412 GB free
  … Docker is not installed. Encore needs it to run. Install it now? [Y/n]     ← the only question (skipped with --yes)
  ✓ Docker installed
  ✓ Downloading Encore (about 600 MB) …… 100%
  ✓ Starting Encore
  ✓ Encore is running

  Now open this on your phone or computer (same Wi-Fi):

        http://encore.local/setup?code=7KQ-4MZ

        ██████████████        (QR code of the same link)
        ██ ▄▄▄▄▄ █▀ ██
        ...

  If that address doesn't open: http://192.168.1.23/setup?code=7KQ-4MZ
```
* The **setup code** (one-time, valid until setup is finished) stops anyone else on the Wi-Fi from claiming the server before the Host
  does (hidden risk H36). Without the code, `/setup` says "Use the link shown on the computer where you installed Encore".
* Errors are sentences with the fix: "This computer has 1 GB of memory; Encore needs at least 2 GB", "No internet connection: check the
  cable or Wi-Fi and run the same line again". Running the line again is always safe.

## 1b. The `encore` command: what each part prints (text, designed; owner 2026-10-24: the server side is on paper too)

These are the outputs as `server/encore_server/deploy/install.sh` and `server/encore_server/deploy/encore` print them today, plus the one change decided in ADR-R40 (the installer's last screen offers a **pairing link and QR** instead of "Address: ... Username: ...", once P2-20 is built). Plain words, no "Docker" except where the Host must act; every error is a sentence with the fix.

```
$ encore status
  Encore 0.1.0 (version main)
  ✓ Encore server: running (healthy)
  ✓ Music server: running (healthy)
  ✓ It answers on port 4540

        On your home network:  192.168.1.23:4540
        Away from home:        not set up (encore funnel on)
        Music folder:          /home/host/Music
        Last backup:           2026-10-24 03:12
```
```
$ sudo encore update
  ✓ A backup was made first
  … Looking for a newer version
  ✓ Encore is up to date (was 0.1.0, now 0.1.1)
```
```
$ sudo encore funnel on
  ✓ Away from home: https://our-music.tail1234.ts.net
    Phones that are signed in learn this address by themselves, and invitations carry it.
```
```
$ sudo encore backup
  … Copying the databases
  ✓ Backup made: /opt/encore/backups/encore-backup-20261024-031200.tar.gz (14M)
    It holds the accounts, playlists and likes, and a login this install needs: keep it private. Your music is not in it.
```
```
$ sudo encore pair                      (after P2-20; ADR-R40 slice B)
  Open this on the phone where you want to be signed in (valid 10 minutes, works once):

        https://our-music.tail1234.ts.net/encore/pair/7KQ4-MZ8P-2RTV?id=mw3am46w5weex4a4fqrc3avnua
        ██████████████        (QR code of the same link)
```
The installer's last screen, once pairing exists: "Encore is ready. Open the Encore app on your phone and scan this: (QR)", then the two lines about `encore funnel on` and `encore status | update | uninstall`. Nothing in these outputs shows a password or a pairing code in a log (ADR-R40 D7).

## 2. The setup wizard in the browser (8 steps)

Served by the Encore server at `http://encore.local/setup`. Works on a phone screen (the Host may only have their phone at hand) and
on a computer. Language picker in the corner (English first).

### Page 1 — Welcome
```
  [illustration: a small house with music notes coming out of the window]
  Welcome to Encore
  Your own music service, running on this computer. It takes about 5 minutes.
  You'll choose: your account, where your music is, and who can listen.
                                                       [ Let's start ]
```
Nothing to fill. Shows the computer's name and that it is ready.

### Page 2 — You (owner account + server name)   *Step 1 of 8*
```
  Your name            [ Riley          ]
  Username             [ riley          ]   (used to sign in)
  Password             [ ••••••••••      ]   ▂▄▆ strong
  Name your server     [ Our music       ]   shown to people you invite: a place, not a person ("Our music", "Home", "The flat")
  Pick a colour        ● ● ● ● ●
                                             [ Continue ]
```
* **The server's name is the household's, never one person's** (owner, 2026-10-24: "why would I call a server that is not meant for one person by my name?"): the field is pre-filled with "Our music", the hint shows two more place names, and a person's own name appears only in "invited by Riley" and in the greeting.
* Password rules: 8 to 128 characters (`32` AC-1, the same as the app and the server); a strength line; "show password" eye. *(Corrected 2026-10-24: this said 10; the code and `32` say 8, and the code wins.)*
* Creates the Host as owner (an administrator of the music server is made behind the scenes with a generated password that nobody
  types; the Host's own account is a normal person with the owner role).
* Error: username taken / invalid characters, in words, next to the field.

### Page 3 — Your music   *Step 2 of 8*
```
  Where is your music?
  ( ) Music folder on this computer   /home/host/Music       2,340 songs found   38 GB
  ( ) Another disk                    /mnt/disk2/music       5,616 songs found   49 GB
  ( ) A different folder…             [ browse ]
  (•) I don't have music files yet — start empty (songs you play and save will be kept here)

  New songs you save will be stored on:  [ This disk — 412 GB free ▾ ]
                                             [ Continue ]
```
* The server lists real disks and folders it can see, counts audio files quickly (a sample scan, then the real scan runs in the
  background), never changes existing files (read-only), and keeps new songs in its own folder on the chosen disk.
* Warnings in words: "This disk is almost full (3 GB free)".

### Page 4 — Checking this computer   *Step 3 of 8* (automatic)
```
  ✓ Internet: 18 Mbit/s down, 7 Mbit/s up
      About 40 people can listen away from home at the same time.
  ✓ Songs from YouTube can be reached from here
  ✓ Storage: 412 GB free — room for about 80,000 songs
  ✓ Speed of this computer: good
  ! The clock is 4 minutes off — fixed automatically
                                             [ Continue ]
```
* Runs once, ~20 s, with live ticks. Each warning says what it means for a person and what to do. Results are kept for the admin
  Home page. If YouTube is unreachable (blocked country, network): "Songs you don't have can't be played from here; your own
  music works normally."

### Page 5 — Songs you don't have   *Step 4 of 8* (optional, preselected)
```
  [illustration: a search bar with a note]
  Play songs that aren't on your server
  When someone searches for a song you don't have, Encore can play it from YouTube and keep it here if they save it.
  (•) Yes, turn this on (recommended)
  ( ) No, only play music that's on this server

  Downloads in the background:  [ Automatic ▾ ]   (Automatic · Gentle — leaves room for others at home · Only at night)
  ⓘ Where songs come from and your responsibility                           [ Skip ]  [ Continue ]
```
* "Where songs come from" opens a short plain text (the legal note of `09` §5).

### Page 6 — Away from home   *Step 5 of 8* (optional)
```
  [illustration: a suitcase with headphones]
  Listen outside your home, and invite friends who live elsewhere
  Encore uses a free Tailscale account to give your server a safe web address. No router settings.
     1. Create a free Tailscale account          [ Open Tailscale ]   ✓ done
     2. Turn on two settings (2 clicks)          [ Show me how ]      (screenshots in a side panel)
     3. Sign in to Tailscale on this computer    (a link opens; there is no key to paste)
                                                 [ Check ]  → ✓ Your address: https://our-music.tail1234.ts.net
                                             [ Do this later ]  [ Continue ]
```
* The check is automatic and explains failures (today `encore funnel on` says "It needs HTTPS and Funnel enabled for your tailnet"). The 180-day key expiry is turned off
  in step 2's instructions; the admin warns 14 days before if not.
* Since ADR-R25 there is no key and no second Tailscale node: the sign-in is the one of the computer's own Tailscale (`encore funnel on` shows the link and installs Tailscale
  if it is absent). **OPEN (needs owner/advisor; advisor, 2026-11-01: stays open, tied to the owner's public-address question, D-48 f):** whether this page runs that step itself or shows the Host the command `encore funnel on` to run on the computer. **Also OPEN, same reason:** the wizard pages do not yet carry D-19 (the "Where songs come from" step with the off-by-default Soulseek choice and its plain-words legal note) or D-20 ("No YouTube account needed. Songs you don't have are fetched gently in the background."), and the rows that still say "quality tier only in the admin" (`10` D-12, README) are older than D-19.

### Page 7 — Friends on other Encore servers   *Step 6 of 8* (optional, **Yes preselected**)
```
  [illustration: two little houses with a music note travelling between them]
  Listen with people who have their own Encore
  People on your server can add friends who run their own Encore, listen together in a Jam, and share songs.
  Nothing is shared until two people both agree. Nobody can find your server without a code.
  (•) Yes, allow it (recommended)
  ( ) No, keep this server to itself
  ⓘ Each person can still turn this off for themselves.
                                             [ Continue ]
```
* If page 6 was skipped: "This needs away-from-home access. You can turn it on later." (the choice is saved and takes effect then).

### Page 8 — Your phone and your people   *Step 7 of 8*
```
  Get Encore on your phone
  1. Install the app      [QR: download page]
  2. Open it and scan     [QR: one-time sign-in for Riley — no password typing, valid 10 minutes]
  ✓ Riley's phone is signed in

  Invite someone (optional)
  [ Create an invitation ]  → link + QR, valid 7 days, for one person
                                             [ Skip ]  [ Continue ]
```
* The sign-in QR pairs the Host's phone with a device token (P3-03); the page turns green when the phone signs in.

### Page 9 — All set   *Step 8 of 8*
```
  [the Host's own album covers fill the background as a slowly drifting mosaic; empty server: illustration]
  Our music is ready 🎉
  ✓ Ready for your first songs   ✓ Away from home: on   ✓ Friends on other servers: allowed   ✓ 1 phone
  (With a music folder chosen on page 3 it reads "✓ 2,340 songs" instead; the drawing starts empty, as page 3 preselects.)
  Manage your server any time at  http://encore.local   (bookmark it)
                                             [ Open my server's page ]
```

## 3. The Listener's first run in the app (Android)

| # | Page | Content | Notes |
|---|------|---------|-------|
| A1 | **Welcome** | Logo animation; "Listen to your music, and everything else" ; **[Scan an invite]** **[I have an invite link]**; small "Other ways to connect" | Background: slow mosaic of album art (bundled generic artwork for the very first screen) |
| A2 | **Join** | "Join **Our music** — invited by Riley" (server colour); your name, username, password (or, for the Host's pairing QR: "Sign in as Riley?" → one tap) | Errors in words; the invite's expiry shown if close |
| A3 | **How songs reach you** (only if the server's YouTube source is on) | One card: "Songs that aren't on Riley's server come from YouTube. When you save them, they're kept on the server for everyone." [Got it] | Shown once per person |
| A4 | **Bring your music** (US-05) | "From Spotify" / "From YouTube Music" / "Skip for now" | Import starts here; list appears in ≤ 5 s |
| A5 | **Pick some artists** (recommendations' cold start, US-60) | A grid of artist photos (from the import if any, else popular in the server's country); "Pick 3 or more" ; [Done] / [Skip] | Feeds the person's profile |
| A6 | **Home** | Imported playlists, picks from A5, "Start with something" shelf | No permission asked until needed |

Manual connection ("Other ways to connect"): address + username + password, for Tinkerers and the Host's own debugging only.

**Order of the first screen, decided 2026-10-23 (`11` ADR-R40; not built, the app still shows the address form first, `evidence/b02`):** 1. a link or a QR code (the installer and `encore pair` print a one-time pairing link and QR for the owner's own phone); 2. **"Servers on this Wi-Fi"**, found by the server's own advertisement and shown by name; 3. "Other ways to connect". No "address", "IP" or "port" on the first screens. The phone recognises its server by a key, not by an address, so another Wi-Fi, a new router or a new computer (restored from a backup) do not matter.

## 4. The admin site (the Host's pages after setup)

At `http://encore.local` (home network only by default; never on the public address). Sign in with the Host's normal account.

The eight pages below are the ones **drawn** (`design/directions/screens-server-and-browser.html`, W-02 to W-08; decided 2026-10-25, `design/03`). They replace the nine-row grouping this section had before, which split one switch per page.

| Page | What it shows / does |
|------|----------------------|
| **Home** | "Everything is working." in words, then one plain row per part (music server, songs from YouTube, away-from-home address with the days the key has left, disk, last backup, Encore's version, people, today's counts); "needs you" rows come first; counts only, never titles |
| **People** | Who has an account, role, invited by, last seen, devices; invite, reset-password link, unlock a locked person, remove with its reason; pending invitations |
| **Library** | Music folders with counts (read-only, said in words), scan now, what Encore itself kept (count, size, where), duplicates, "songs nobody saved" with a Remove button that asks first |
| **Away from home** | Address, status, key expiry, re-run the Tailscale steps |
| **Backups** | Last backup (when, size, where), how often, what is in it and what is not, Back up now, **Restore as a button** that first backs up what is there and asks the Host to type the server's name (D-61; `encore restore` is the other door) |
| **Updates** | Versions (Encore, music server, fetching tool), an **Update button with its way back** (D-61; `sudo encore update` is the other door), update automatically at night (off by default) |
| **Settings** | The server's name ("Our music"), friends on other servers (D-13), recommendations (a grey "later" line until they exist), best quality with its plain risk text (D-12), plays any song (YouTube), the highest quality away from home (a cap, only mentioned by the app when set), songs from YouTube status and background downloads |
| **Logs** | What the server has been saying in the last hour, in plain words (no password, login or song title), filtered by part; copy or download for a bug report; the versions. Opt-in problem reports from phones (P4-13) are not drawn yet |

Each admin page is drawn on paper the same way before its task starts (P3-06 begins by adding them here).
