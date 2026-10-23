# B-02 — Journey 4: one person, two phones, an import, a like and an edit (2026-10-23, build 120)

Journey 4 of `tasks/AUDIT.md`: the same account on two emulators; what is done on one appears on the other. `b01` proved a new playlist and a like; this adds **an import** and **a playlist edit** and records what is **not** there (resume).

## Setup

| | |
|-|-|
| Phones | two Android emulators (720x1600, host GPU, API 36), fresh install of **build 120** (x64 release built from `main` at `52a7214`; `pm clear` before signing in), the same person signed in on both with the sign-in screen (address, username, password typed from the login file, never printed) |
| Server | the dev VM's Encore server (`encore-dev`, home network; an older image than `main`, no yt-dlp updater), the person `newtester` |
| Phone B | left on Your Library > Playlists, sorted "Recently added", so a new item shows without scrolling |
| Measuring | `tools/journeys/two_phone_timing.py`: taps the last step on A and polls B's screen. One screen read costs about a second, so every time is an **upper bound** |
| Content | the album *The Dark Side of the Moon* (10 songs) as a YouTube Music link, new to this account |

## Results

| Change on phone A | Shows on phone B after | Note |
|-------------------|------------------------|------|
| Import the 10-song album (tap Import) | **3.3 s** | the playlist row appears with "10 songs" at once (the songs play when tapped; the server saves them in the background) |
| Like the song that is playing (heart in the player) | **2.2 s** | B's Liked Songs went 4 -> 5 |
| Rename that playlist (Rename, Save) | **2.5 s** | the new name shows in B's list |
| The server saving the imported songs | 10 of 10 saved after about 2 min | the server log shows 10 stream look-ups from 21:41:35 to 21:43:36, 8 to 19 s apart (the pacing), each 1.0 to 2.2 s, none refused. A's import list ends with "10 songs, 10 saved on your server" |
| Playing a song on A | audio from the server, "OPUS 141", 2:49 long | |

## What is not there: resume on the other phone

While A played a song, B (Home and Library) showed **no mini player, no "continue", no sign of it**. This matches the code: the server has `GET/PUT /encore/api/v1/playback` and `/playback/claim`, and the app never calls them (only a mention in the live channel's comment and an upgrade key). It is app work: **P2-08** (playback state and resume anywhere) and **P2-09** (one device at a time), promise N5/N6. Not built inside this journey, on purpose. So journey 4 is **passed for import, like, playlist edit and new playlist; open for resume**.

## Found on the way

1. **The first screen asks a non-technical person for an IP address** ("For example 192.168.1.10:4533", "Ask whoever set it up for the address, your username and your password"). The plan says the opposite (`15` section 3, A1: scan an invite or paste a link first; manual address only under "Other ways to connect"). The owner raised the same point on 2026-10-23 (how does an ordinary person find a server, as Plex does, with several Wi-Fi networks and several servers?). Written up as **ADR-R40** (`11`) and task **P2-19** (`tasks/P2`), together with a security finding: the app sends the person's credentials to every candidate address before checking whose server it is (see ADR-R40).
2. **A text field's touch area looks smaller than its accessibility box.** On the Import page the field's node in the screen dump is 720x214 centred at y=499, but the field is drawn at y=400 to 486; a tap at the node's centre did not focus it, and the node overlaps the Import button's area (y=529 to 599). Not confirmed as a bug (the field is multi-line and grows); to be looked at with TalkBack in the accessibility task (P1-12).
3. Phone B's layout is about 45 px lower than A's on the same screens (different insets); coordinates cannot be reused between the two phones, so every tap here was taken from a fresh dump.
4. The tool `ui.py swipe x y x y 900` does not make a long press (the app saw a tap and started the song); a tool limit, not an app problem.

## Not covered

An import and an edit while B is in the background for hours; the same over the public address; a long list or a Spotify list; more than two phones; **resume** (above); a real phone (these are emulators).

## YouTube look-ups spent

10 stream look-ups by the server for the import (above) and a handful of `ytmusicapi` requests from this PC to find the album's playlist id (3 searches and 4 album pages). No refusal. With the 4 canary runs of `c04` earlier the same day, the home address saw a modest, spaced load.
