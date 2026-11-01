# 03a — User stories (v1)

Format: **As a … I want … so that …**, then acceptance criteria a tester can check on a phone, with numbers. Story IDs are stable;
tasks and tests cite them. Personas are defined in `03` §2. "Catalogue song" = a song not on the server yet.

## Getting started

**US-01 Host installs the server.** As a Host with a spare PC running Linux, I want to install Encore with one command and finish
setup in my browser, so that I don't need to understand Docker. Every page is drawn in `15` §1–2.
* One command from the website installs everything (installs Docker if missing, after asking), prints an address and a QR code.
* The browser wizard asks only: my name and password (I become the owner), where my music folder is (optional; empty is fine),
  the server's name. It finishes in ≤ 5 minutes on a Raspberry Pi 4.
* It measures the machine and line once (CPU, free disk, download/upload speed, YouTube reachability) and shows the results in
  plain words ("Songs from YouTube: working", "Away from home: not set up yet").
* Works on Ubuntu/Debian on x86-64 and ARM64; the guide says which systems were actually tested.

**US-02 Host sets up away-from-home.** As a Host, I want my family to listen outside the house without opening router ports.
* The wizard walks through Tailscale Funnel with screenshots and one sign-in (there is no key to paste, `11` ADR-R25); it checks the result itself and shows the public
  address.
* It warns 14 days before the computer's Tailscale sign-in would expire and says how to stop it from expiring.

**US-03 Host invites someone.** As a Host, I want to invite a person with a link or a QR code, so that they never type an address.
* "Invite" on the admin page and in the app makes a link + QR, valid 7 days, usable once.
* The Listener's phone: tapping the link opens the Encore app (or the download page if not installed); the app shows "Join
  <server name>, invited by <Host>", asks for a name and a password, and is signed in. No browser round trip.

**US-04 Listener joins.** As a Listener, I want to be listening within a minute of installing the app.
* First screen: "Scan an invite" and "I have an invite link". Manual server address is under "Other ways to connect".
* After joining, Home is never empty: it shows "Start with something" (popular songs from the catalogue) until I have my own.
* No permission is asked until it is needed (the notification permission is asked only when I switch a notification on, `11` ADR-R44).

**US-05 First run: bring your music (owner asked 2026-10-21).** As a new Listener coming from Spotify or YouTube Music, I want to
be offered to bring my playlists right after joining, so that Encore feels like *my* music from minute one.
* After joining, one welcome screen: "Bring your music" with **From Spotify**, **From YouTube Music**, and **Skip for now**.
  It appears once per person (not per device).
* Choosing a source shows the 3 ways for it in plain words (share a playlist to Encore from the other app / paste a link /
  Spotify's data file for everything) with a 10-second illustration each; the share route is first.
* After an import the person lands on Home with the imported playlist(s) in the first row, playable at once (N4).
* If skipped: Home shows an "Import your playlists" card (dismissible) until the first import; Settings → Import is always there.
* Never blocks: the person can search and play from the welcome screen's top bar.

## Listening

**US-10 Search and play anything.** As a Listener, I want to type a song and hear it at once, whether or not the server has it.
* The song I typed is the **Top result** when it exists (artist + title match), above albums and covers.
* Owned and catalogue songs look the same in results; nothing says "not in your library".
* Tap → sound: ≤ 2 s typical, ≤ 10 s worst (N2); the top result plays in ≤ 1 s (N3).
* While it loads, the row and the mini-player show a spinner, and the previous song stops at once (not after the new one loads).
* If it cannot be played (not on YouTube, blocked in my country, YouTube refusing), I see one plain sentence within 10 s and the
  player is in a normal state (play button works).

**US-11 Play an album or playlist through.** As a Listener, I want Play on any album or playlist to play every song in order,
including songs the server doesn't have yet.
* Next is never disabled while songs remain; catalogue songs in the queue are prepared ahead (the next 2) so the change is gapless
  or ≤ 1 s.
* Shuffle and repeat behave like Spotify.

**US-12 Resume anywhere.** As a Listener, I want to pause on my phone at 2:31 and continue at 2:31 later, on this phone or another
device, including songs from YouTube.
* Opening the app (or another device) shows the last song in the mini-player, paused at the same second (N5).
* Works after the app was killed by the system or a battery saver, after a reboot, and after a day.

**US-13 One device at a time.** As a Listener, I want playback to move to the device I'm using, like Spotify.
* Starting playback on device B pauses device A within 2 s (N6); A shows "Playing on <B's name>" with a button "Play here".
* Two different people never affect each other.

**US-14 Offline.** As a Listener on a plane, I want my downloads to play, and everything else to say clearly that it needs a
connection.
* Downloaded songs play with their covers, everywhere (rows, mini-player, full player, lock screen).
* Songs that aren't downloaded are greyed out; tapping one says "Not downloaded" once, and the player does not skip through the
  playlist.
* No permanent offline banner. When the connection returns, everything works again within 5 s, without tapping anything.

**US-15 Lock screen, notification, headset, car.** As a Listener, I want to control music without opening the app.
* Notification and lock screen show the cover, title, artist, a correct seek bar, previous/play-pause/next.
* Headset button and Bluetooth controls work; unplugging headphones pauses; a phone call pauses and resumes.
* Android Auto shows Home shortcuts, playlists, downloads and search.

**US-16 Lyrics.** As a Listener, I want synced full-screen lyrics when they exist, and a quiet "No lyrics for this song" when not.

## My library

**US-20 Save anything.** As a Listener, I want to like a song or add it to a playlist whether or not the server has it.
* The like and the playlist entry appear at once on every device (N9) and survive any later change to the file (format upgrade,
  re-tag, move).
* Saving a catalogue song makes the server keep a copy in the background; I don't have to wait for it.

**US-21 Play is not save.** As a Listener, I want songs I only tried not to fill my library.
* Playing a catalogue song never adds it to Your Library. "Recently played" shows it.

**US-22 Download for offline.** As a Listener, I want to download a playlist or album with one tap.
* Progress is shown per item and overall; covers are downloaded with the songs.
* At home, catalogue songs are fetched as fast as my line allows; when the server already kept them, they come from the server.
* A storage limit setting; downloads only on Wi-Fi by default.

## Bringing music in

**US-30 Import a playlist in seconds.** As a Listener coming from Spotify or YouTube Music, I want my playlists in Encore right away.
* Paste/share a link: the playlist, with its cover and the right count, is in Your Library in ≤ 5 s (N4), and every song plays on tap.
* Songs that could not be matched are listed ("3 songs not found") with a way to search for each.
* The server keeps the audio in the background; a small line shows progress; Stop stops it at once (no new songs start).
* Spotify links are honest about the 100-song limit and offer the file import (or, if X-4 succeeds, signing in to Spotify on the
  phone) for the rest and for Liked Songs.

**US-31 Import everything from Spotify.** As a Listener, I want my Liked Songs and all playlists, including private ones.
* From Spotify's data export file (today) or a Spotify sign-in on my phone (after X-4): all playlists + Liked Songs, no 100 limit.

## Sharing the server

**US-40 Host manages people.** As a Host, I want to see who has an account, reset a password, lock or remove someone.
**US-41 Privacy.** As a Listener, I want my library and listening to be private unless I choose to share. The Host cannot see
what I play either.
**US-42 Host's safety.** As a Host, I want Encore never to get my internet address blocked or my disk filled.
* Background work is paced; after a refusal from YouTube it pauses and says so on the admin page.
* A free-space floor (default 10 GB) stops keeping songs; the admin page shows space used by kept songs and a "remove songs
  nobody saved" button.

## Discovery and together (in the first version, owner 2026-10-21)

**US-60 Recommendations made for me.** As a Listener, I want Home to suggest music from *my* taste, not my friends'.
* Each person has their own profile built from their own plays, likes and skips (never another person's); the Host cannot read it.
* Home shows "Made for you", "Because you play <artist>", "New from artists you love"; a song radio and smart shuffle are one tap away.
* Suggestions include songs not on the server; they play like any other (N2). "Not for me" removes a suggestion and teaches the profile.
* A new person gets useful rows after their first import or ~20 plays.

**US-61 Jam.** As a Listener, I want to listen together with friends: start a Jam, share a code/QR, everyone adds songs and controls
playback like Spotify's Jam; the Jam uses my normal player and queue; leaving the Jam returns me to my own queue.

**US-62 Friend activity.** As a Listener, I can choose to share what I'm playing with friends on the same server, and see what those
who share are playing. Off by default; turning it off removes it at once.

**US-63 Best quality.** As a Host, I can switch on "Best quality": songs people keep are upgraded to lossless copies when available
(Lidarr + Soulseek), with the risks explained in plain words. As a Listener, an upgraded song keeps its likes, playlists and position
(nothing moves, ADR-R4).

**US-64 Year in Music.** As a Listener, I want my year (and month) in music from my own plays, including songs played from YouTube.

**US-65 Compare tastes (owner, 2026-10-24; later, opt-in).** As a Listener on a server with other people, I can choose to compare my listening with another person's: "you both like X, your favourite genre is Y", and a playlist made from what we both like (the pattern is Spotify's Blend).
* **Off by default.** Nothing is compared, shown or even computed for a person who has not switched it on, and nobody sees that they could be compared.
* **Both sides opt in** before either sees anything; **either can withdraw at any moment** and the comparison disappears at once (no copy is kept by the other).
* Listening marked **private** is never counted.
* Between people on the same server first; with a friend on another server only when the server allows connecting with other servers (`../design/03` row 5).
* The server computes it; the other phone gets the result and nothing about individual plays.

## Devices and friends everywhere (owner 2026-10-21; design `13`)

**US-70 Control my other device.** As a Listener with the same account on a phone and a tablet, I want to control what the tablet
plays from my phone: play/pause, next/previous, seek, queue, like.
* The phone's Devices sheet lists my devices; the tablet answers within 1 s at home, 2 s away.

**US-71 Volume of my other device.** As a Listener, I want to raise or lower the tablet's volume from my phone, with the slider and
with the phone's own volume buttons, and see the tablet's slider follow.
* One volume per device: Android's media volume; no hidden in-app volume.

**US-72 Friends on other servers.** As a Listener whose friend runs their own Encore, I want to add them as a friend with a QR code or
link. I keep one account on my own server; my server talks to theirs. Both of us must accept; nobody can find me without my code.

**US-73 Jam with anyone.** As a Listener, I want to start a Jam with people on my server or on other servers (a Jam code is enough;
no friendship and no account on my server needed), and play songs that are on my server, on theirs, or on nobody's, all in one
queue, in sync. Each phone only talks to its own server.

**US-74 One account is enough.** As a Listener, I never need a second account: everything I do with people on other servers goes
through my own server (owner, 2026-10-21: two accounts on one phone is "stupid and lazy").

**US-75 Tablet (parked: D-18, D-48 a).** As a Listener on a tablet, I want a layout made for a big screen, in portrait and landscape. Not built until it is asked for; the phone layout scales meanwhile (`tasks/P6-later.md`).

**US-76 Even loudness.** As a Listener, I want songs to play at a similar loudness whatever their source, and the phone's volume
buttons to be the only volume I ever need.

## Keeping it running

**US-50 Updates.** As a Host, I want to update with one command and see when an update exists. As a Listener, I want the app to
tell me when a new version is available and install it in two taps.
**US-51 Health.** As a Host, I want one page that says in plain words what works and what does not, and what to do.
**US-52 Backups.** As a Host, I want my people, playlists and likes backed up automatically (database only, small), with a restore
command.
