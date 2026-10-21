# 03 — The product

## 1. One sentence

**Encore is a free music server you install on any spare computer, plus an Android app, that plays almost any song instantly,
keeps the music you love on your own disk forever, and lets your family and friends use it too, with no subscription.**

## 2. Who it is for

| Persona | Who | What they want | What they will not do |
|---------|-----|----------------|-----------------------|
| **The Host** | Someone with a spare PC or mini-PC who can follow a guide: install Linux, paste one command. Any country, any hardware from a Raspberry Pi 4 upward, any line from 5 Mbit/s ADSL upward. | Stop paying Spotify for the household; own the music; be the "music person" for family and friends. | Edit config files, open router ports, buy a domain, read Docker docs, sign their Google account into a program. |
| **The Listener** | A family member or friend who gets an invite link. Not technical. Compares everything to Spotify. | Install, tap the invite, listen. Search anything, play it, make playlists, download for the plane, bring their Spotify playlists. | Learn what a "server" is, type addresses, wait minutes for a song. |
| **The Tinkerer** | Homelab person with Docker, maybe Navidrome/Lidarr already. | A great Android app, bring-your-own parts, compose file they can edit, Subsonic compatibility for other apps. | Accept a black box that fights their setup. |

The Host is also a Listener. Design for the Listener first, the Host second, the Tinkerer third (through an "Advanced" door).

## 3. Why someone would choose Encore (positioning)

| Instead of | They get today | Encore must be better at |
|------------|----------------|--------------------------|
| **Spotify** ($12.99/month US, Feb 2026; lossless included) | Everything plays instantly, great UX, social, import-free | Free, owned music that never disappears, family/friends at no cost, privacy. Must match: search → sound in about 1–2 s, playlists, offline, lyrics, lock screen, Android Auto. |
| **Plexamp** (needs Plex Pass for remote: $69.99/yr or $249.99 lifetime per the 2025 prices, 2026 Remote Watch Pass $2.99/mo) | Beautiful player for music you already own | Plays music you *don't* own yet, imports Spotify playlists, free, no Plex account. |
| **Free YouTube Music clients** (Metrolist, Spotube; OuterTune discontinued) | Free, instant, the whole catalogue, no server | Your music stays when YouTube removes it; one library across your devices and family; works with your own files; no Google account. |
| **Navidrome + a Subsonic app** (Symfonium, Substreamer) | Your own files, solid | Everything above, plus one install and an app that feels like Spotify. |

"Good enough that nobody says *just use Plexamp*" means: the player itself (UI, gapless, lock screen, offline, Auto) is on par
with Plexamp, and Encore adds what Plexamp cannot (catalogue, import, free).

## 4. The promises, with numbers

Every number is checked on the **reference setups** in `07` §2 (a slow one and a typical one), not only on the owner's.

| # | Promise | Target (typical setup) | Hard limit (slow setup) |
|---|---------|------------------------|-------------------------|
| N1 | Tap a song **on your server** → sound | ≤ 0.7 s at home, ≤ 1.5 s away | ≤ 3 s |
| N2 | Tap a song **you don't own** → sound | **≤ 2 s** p50, ≤ 4 s p95 | **≤ 10 s** (owner, 2026-10-21) |
| N3 | Same, when the app could prepare it (top search result, next in queue, songs of an open page) | ≤ 1 s | ≤ 3 s |
| N4 | Import a playlist → the whole list is on screen and every song plays on tap | ≤ 5 s for 200 songs | ≤ 15 s |
| N5 | Pause at m:ss on one device → resume at the same second on another (including songs from YouTube) | resume within 1 s of the paused position | ≤ 2 s off |
| N6 | Start playing on device B while A plays → A stops | ≤ 2 s | ≤ 5 s |
| N7 | Search updates as you type | ≤ 300 ms after the last key (catalogue), ≤ 50 ms (on-phone library) | ≤ 1 s |
| N8 | Cold start to usable Home, offline | ≤ 0.7 s mid-range phone | ≤ 1.5 s low-end |
| N9 | A change on one device shows on the others | ≤ 2 s (live channel) | ≤ 30 s |
| N10 | Fresh Linux machine → first song on a phone | ≤ 15 min, one command + a web wizard | ≤ 30 min |
| N11 | Nothing anyone does in normal use gets the Host's internet address flagged by YouTube | paced, backs off automatically | — |

Background work (keeping imported songs on the server) has **no promise to the person**: it is paced to stay safe on any line
and any address, and what you play goes first. The admin page shows how far along it is.

## 5. Scope

### v1 (the public release on the website)

**Server:** one install command, setup wizard in the browser, Navidrome + Encore server (+ optional Tailscale Funnel for away
from home), people and invitations (link + QR), password reset by the Host, the YouTube source (on by default, can be switched
off), keeping saved songs, imports (YouTube Music links, Spotify links ≤ 100, Spotify/YouTube data-export files), playback state
and single-device playback, live updates to phones, admin pages: People, Storage, Remote access, Health, Updates.

**App (Android):** sign-in by invite link/QR (manual address only behind "Other ways to connect"), Home, Search (with Top result,
songs/artists/albums/playlists, owned or not looks the same), Your Library (playlists, liked songs, albums, artists, downloads),
full player and mini-player, queue, lyrics (full screen), likes and playlists that hold any song, downloads for offline (with
covers), resume anywhere + "playing on another device", import, settings (short), Year in Music, Android Auto, lock screen and
notification, in-app update check.

**Also in the first version (owner, 2026-10-21: "everything will be in the first version even if it means delaying the release by
months"):** recommendations with a **profile per person** (Home mixes, "because you play…", radio/smart shuffle, new releases from
artists you love); **Jam** (listen together), **with people on the same server or on other servers**; **friend activity** (opt-in per
person); **friends on other Encore servers**; **your devices** (control the tablet from the phone: play/pause, seek, queue, **volume**;
hand playback over at the same second); **one account per person, servers that talk to each other**; **tablet layout**; the **quality tier** (better copies via
Lidarr + Soulseek, switched on by the Host); **Year in Music**; the Spotify-class extras of `14` section 1. They are built in phase P4
on the new design, after the core works. Design: `13`.

**Not decided now (owner: "let's not worry about website, name and things like that"):** the final product name, the website and
its address. "Encore" stays the working name.

### Later (after the first public version)

iOS, web/desktop client (the server API is built for it from day one; devices and playback state already work across clients),
casting to Chromecast/TV speakers, audiobooks/podcasts, localisation beyond English (French and Arabic first), a flashable
"Encore OS" image.

### Never by default

A Google account inside the server; torrents; any paid service; a cloud relay run by the Encore project; sending anyone's
listening data off their server.

## 6. Principles (how to decide when this page is silent)

1. **Copy Spotify's behaviour** where people have muscle memory; invent nothing they must learn (owner, 2026-10-16).
2. **Nobody waits on the network for something the app could have known.** The screen comes from the phone's database; the
   network fills it in.
3. **Play is not save is not download, but the server remembers what you love.** Saving (like, playlist, album, import) and
   downloading make the server keep the song; so does coming back to it: a song a person plays on **2 different days** is kept
   (owner: "if someone plays a song today and tomorrow and the day after, we need to keep it"). Each song is stored **once** for
   everybody; playlists, likes, history and the recommendation profile are per person.
4. **Works for everyone, not only the owner's machine**: slow lines, weak PCs, other countries, blocked or flagged addresses,
   non-Latin text. Defaults are conservative and adapt to what was measured on the machine.
5. **Never put the Host at risk**: their internet address (YouTube pacing), their accounts (no Google sign-in), their disk
   (space limits), their family's bandwidth (a speed limit setting).
6. **Honest and plain**: one-sentence explanations, no jargon ("Navidrome", "OPUS 136", "Subsonic" never on a Listener screen),
   real counts, real states.
7. **Simple to run**: one server program, one port, one database, published images, one update command.
8. **Free.** No feature depends on a paid account anywhere.

## 7. How we know v1 is good (exit criteria)

* The promises N1–N11 measured on both reference setups (`07` §2) and on two real phones.
* The journeys in [`03a-user-stories.md`](03a-user-stories.md) walked by a person-like QA agent on the device matrix (`07` §4)
  with no S1/S2 bug open.
* A person who has never seen Encore installs the server from the website guide on a clean machine and gets a friend listening,
  without help (filmed or logged).
* The owner daily-drives it for 5 days and does not open Spotify.
