# Design 00 — Every screen, today and later, with the states each one must show

Owner, 2026-10-24: *"we haven't started with a design in Figma or so; can you make a design for all pages and future pages?"* This is the list that design works from. It is built from the router (`app/lib/app/router.dart`), the feature folders, the stories (`../03a`), the first-run paper (`../15`), `../16`, the Jam/people/import tasks (`../tasks/P4`) and the state tables (`../31` to `../34`). **A screen that is not here is not designed; a state that is not named here is not drawn.** Add the row first. (Since D-43, 2026-10-31: where the app already has a screen, the built screen is the reference and the old drawings are history; a page is drawn only when it is new and about to be built. This list is the inventory of what exists or is planned.)

## How to read it

**Layout classes** (ADR-R42): **C** compact (phone, 360 dp wide, portrait), **M** medium (tablet, foldable, phone landscape, 600 to 839 dp), **X** expanded (browser or desktop, 840 dp and up, mouse and keyboard), **T** ten-foot (TV, 1920x1080 at 2x density = 960x540 dp, a D-pad and a visible focus, no hover, no long press, back always works).

**States** (the same words as the tables): **L** loading (a skeleton, never a spinner on an empty page), **E** empty (nothing yet, with the one thing to do), **Z** first-ever use, **O** offline (`31` CN-1), **U** the server does not answer (CN-14), **W** another server answers at this address (CN-11), **X** an error with one plain sentence and a retry, **P** partly loaded (some of it shows, the rest still loads), **S** signed out or the session has ended, **D** in progress with a number, **B** buffering or waiting for the server (`33` G-1), **C** a conflict or an edit that was refused (`34`), **F** focus (T and X only: where the focus is drawn).

A new screen is drawn at **C** and **X** before it is built (**M and T are parked**: D-18, confirmed for tablets by D-48 a on 2026-11-01; the Classes column below keeps them as the history of what was drawn, and M was the C layout with the X grid rules); every colour comes from a token; every string is words (never inside a picture); every layout is checked at text scale 2.0 and right-to-left.

"Today" says where it lives; "new" means no screen exists yet. **Anchor** screens (★) are drawn first in three directions so a direction can be chosen before the rest is drawn.

## First run and connecting (`31`, `32`, `15`)

| ID | Screen | Today | States to draw | Classes | |
|----|--------|-------|----------------|---------|---|
| S-01 | **Welcome: find my server** (invitation or QR first; "this phone found a server nearby"; "Other ways to connect" holds the typed address) | `features/onboarding/connect_screen.dart` (asks for an address today, which `15` A1 forbids) | Z, searching, found one, found several, found none, W, scanning (camera permission asked and refused), pairing code, typed address | C, X, T | ★ |
| S-02 | **Join an invitation** ("Join <server>, invited by <name>") | `join_screen.dart` | L, who invited, choose name and password, W ("not the server that invited you"), code expired or used, O, U, success | C, X | |
| S-03 | **Sign in** (an account that already exists) | `connect_screen.dart` | form, wrong password, U, W, "sign in with a code from another device" | C, X, T | |
| S-04 | **Sign in again** (the session ended) | `/sign-in-again` | S, wrong password, U | C, X | |
| S-05 | **Who is listening** (profiles on one phone) and add a profile | `profiles_screen.dart` | one, several, add, remove with a reason | C, M | |
| S-06 | **Bring your music** (from Spotify, from YouTube Music, skip) | new (story US-05) | Z, three ways per source, skipped | C, X | |
| S-07 | **Pick a server** (a person on two servers; `31` O-3) | new | one, two, a server that is away | C, X, T | |
| S-08 | **Sign in on a TV with a code** (Quick Connect) | new | code shown, waiting, signed in, expired | T (and the phone side in C) | |

## Home, search and browsing

| ID | Screen | Today | States | Classes | |
|----|--------|-------|--------|---------|---|
| S-10 | **Home** (greeting, shortcuts, "New from artists you play", your playlists, Year in Music card) | `features/home/home_screen.dart` | Z ("Start with something"), loaded, L, P, O, U, W, S, refreshing | C, X, T | ★ |
| S-11 | **Search** (empty: recents, genres, "type a song") | `search_screen.dart` | E, Z, typing, voice (later), **O (offline, drawn 5 Nov 2026, P1-16: the field's hint says "Search your music" (the phone's own copy of the library, which is why results can be grey), the genre tiles are dimmed, nothing is added to the page; the page is the same for both causes, only the X sidebar's server chip differs)** | C, X, T | ★ |
| S-12 | **Search results** (Top result, songs, albums, artists, playlists; owned and catalogue look the same, **with no marker of what is on the server**; rows carry only Spotify's icons: downloaded, liked, explicit) | `search_results.dart` | L, P (the library answers first, the catalogue second), loaded, no results, **O (drawn 5 Nov 2026, P1-16, replaces "said once": the phone's library answers, what is not on the phone is grey with "Not downloaded", one quiet last line says what more cannot be done in the words of its cause, "More results need a connection." / "More results need your server."; no results offline says "Nothing in your music matches ..." with the same two-way split; no "Closest" and no "Ask for it")**, U, X | C, X, T | ★ |
| S-13 | **Genre or mood page** | `catalogue/genre_screen.dart` | L, loaded, E, **O (drawn 5 Nov 2026, P1-16: "Not available right now", "Browsing needs a connection." when no internet is found, "Browsing needs your server." when internet is found and the server is silent)** | C, X, T | |
| S-14 | **Your Library** (Playlists, Albums, Artists, Downloads; sort and filter) | `library/library_screen.dart` | E per tab, loaded, O (only what is on the phone is not greyed), L | C, X, T | |
| S-15 | **Liked Songs** | `liked` | E, loaded, O | C, X, T | |
| S-16 | **Downloaded** | `downloaded` | E, loaded, D, storage full, **the two stages (drawn 5 Nov 2026, P2-22 parts 1, 2 and 4: one vocabulary for the server stage, the phone stage, a wait and a failure) and the wait where the phone's reason wins (offline)**. **Class C only for these: the browser has no offline downloads (P6-02), so it has no Download to show.** | C, X | |
| S-17 | **Playlist** (mine, shared with me, one I may edit) | `playlist/:id` | E, loaded, editing, C (an edit refused, `34`), O, a song that cannot play, **downloading (the stage line under the playlist's own line, drawn 5 Nov 2026, P2-22 part 2; albums S-18 use the same words)**, **find in a playlist (drawn 13 Nov 2026, N-25: Spotify's "Find in playlist" field sits between the header lines and the buttons (C) or ends the button row (X) on every playlist that has songs; tapped, on C the header goes up and the field takes the top, built like Search's own field (arrow, field, clear); the list narrows as the person types, with the same matching as Search restricted to this playlist; no match says "Couldn't find '...' in this playlist."; offline the finding still works and a found song that is not downloaded is grey with "Not downloaded"; a tap on a result plays it from its place in the playlist, as a tap in the full list does; not shown for an empty playlist or while editing)** | C, X, T | |
| S-18 | **Album** (owned or from the catalogue) | `album/:id`, `catalogue/album/:id` | L, loaded, partly on the server (`album_gap`), O, "not on your server yet" | C, X, T | |
| S-19 | **Artist** (Shuffle and the green Play under the name: every song of the artist the server holds, or on a catalogue artist its Popular list (N-24, `33` PB-42); credits of every artist on a song, new releases, "Songs", "Albums", "Appears on") | `artist/:id`, `catalogue/artist/:id` | L, loaded, a new release (the owner's F12), a song with two artists (F13), E, O | C, X, T | ★ |
| S-20 | **Imported playlist** (progress per song) | `import/:id` | D, saved, a song that could not be found, failed | C, X | |
| S-21 | **Discography / Show all** (all of an artist's albums, singles and EPs, "Appears on", a long shelf of any kind: a vertical list or grid with the same filter chips as the artist page) | new | L, loaded, E, O | C, X, T | |
| S-22 | **Create** (the "+" menu: New playlist, Import a playlist, Start a Jam) and **New playlist** (name it, optionally add songs; a name that is taken) | new | closed, the menu open, naming, refused (`34`), created | C, X | |
| S-23 | **Recently played** (history, newest first, grouped by day) | new (`P2` history) | E, loaded, O, private listening is not listed | C, X | |
| S-24 | **What's new, the one channel for "news"** (the bell: X released a song, an invitation was used, an import finished, a Jam invitation; **nothing of this reaches the phone's notification shade unless the person switched that on**, `11` ADR-R44) | `features/news/` (built, #35) | E, loaded, a notification that no longer applies | C, X | |
| S-25 | **Song credits** (the ⋯ menu's "Show credits": artists, writers, source) | new | L, loaded, partly known | C, X | |
| S-26 | **A person's profile** (name, picture, what they chose to share: playlists, what they play now; "Invite" or nothing else; nothing at all for a person who shares nothing) | new (`P4-03`) | loaded, shares nothing, a person on another server (only when the server allows it) | C, X | |
| S-27 | **The profile menu** (the avatar at the top left of Home: Add account / switch profile, What's new, Recently played, Settings, Your server, Sign out) | `features/home/you_drawer.dart` (built, #60; D-34: only rows whose screen exists, so no "View profile" and no "Recently played" yet) | the menu open, one profile, several profiles on a shared device | C, X, T | |
| S-28 | **Your account / Edit profile** (from the profile menu): the picture (choose from the gallery or take one, remove it; the server stores a small avatar), the display name, change password, **your devices** (this phone and the others, sign one out: `32` DV-3), private listening, sign out, delete my account (later, `21` §6) | new (`32` DV-3; the avatar is a server item of `P3-01`) | loaded, a picture change in progress, a picture refused (too big, not a picture), a wrong current password, devices: one / several / one unreachable | C, X | |

## Playing

| ID | Screen | Today | States | Classes | |
|----|--------|-------|--------|---------|---|
| S-30 | **Mini player** (and the strip above it) | `player/mini_player.dart`, `connection_banner.dart` | playing, paused, B, waiting for the server, cannot play ("one plain sentence"), another device plays (`33`), the connection strip O/U | C (X and T use the bar) | ★ |
| S-31 | **Now playing, as Spotify's mobile screen** (down chevron, "Playing from …", ⋯ menu; a large cover; title and artist left, heart right; scrubber with times; shuffle, previous, big play, next, repeat; a bottom row: **where the sound goes on the left (a small speaker or headset icon and the name, in the accent colour; a tap opens Encore's own Devices sheet: "This phone" with Android's list one tap away, and "Your other devices" saying it is not built yet until P4-07; D-66, `P1-25`), Share and the queue icon on the right (`P1-24`)**; the spare height of a tall screen goes between the sections, never as an empty area under the controls (`P1-22`); **the Lyrics card under the bottom row is always there, the same size in every state (the lyrics, "Looking for lyrics...", "No lyrics for this song", "Lyrics (not synced)"), so the screen never jumps from one song to the next (owner, 7 Nov 2026, `P1-23`); it peeks at the bottom edge and the page scrolls up to it**; the sleep timer in the ⋯ menu (**no speed**, D-23); **no "Next:" card, no lyrics button, no 30-second preview variant (D-64)**; **shuffle is Spotify's three states: off, shuffle, Smart Shuffle (shuffle with a small sparkle), the third only when the server has recommendations on**) | `now_playing_screen.dart` | playing, paused, B, waiting for the server (G-1), cannot play, another device plays, ended, a Jam song | C, X, T | ★ |
| S-32 | **Lyrics** (synced, plain, none yet, "from the web") | `lyrics_screen.dart` | L, synced, plain, none, O | C, X, T | |
| S-33 | **Queue, as Spotify's**: "Now playing", then sections whose **header words say where the songs come from**: "Next in queue" (added by the person), "Next from <playlist or album>", and, only when the server has recommendations on, a recommended section ("Recommended based on what you play"); **a recommended song carries a small sparkle in its row and one tap removes it** (the header words are what tell the person; the sparkle is secondary); reorder, remove, a song that is not ready | `queue_sheet.dart` | E, loaded, a song that is not ready, reordering | C, X, T | |
| S-34 | **Song menu** (more options) and **Add to playlist** | `track_menu.dart`, `playlist_actions.dart` | loaded, E (no playlists), O (what still works) | C, X | |
| S-35 | **Sleep timer**, **Equalizer** (**Speed** was taken out of the player, D-23) | `sleep_timer_sheet.dart`, `equalizer_screen.dart` (`speed_sheet.dart` is still in the code, with its test, but no menu opens it) | off, on, a value | C, X | |
| S-36 | **Devices: play here, play there** (the other phone, the TV) | new (P4-07, `33`) | one device, several, one is unreachable, take over | C, X, T | |
| S-37 | **Share** (a song, a playlist, "listening now") | `people/share_listening_tile.dart` | loaded, O | C | |

## Together (`32`, P4)

| ID | Screen | Today | States | Classes | |
|----|--------|-------|--------|---------|---|
| S-50 | **Jam** (lobby, in a Jam as host or guest, reconnecting) | `jam_screen.dart` | not in one, lobby, in a Jam, reconnecting, ended, U | C, X, T | |
| S-51 | **People on this server** (nobody has to "add" them; what they share is opt-in, `../03a` US-62) and **Invite someone** (link and QR). Friends on *other* servers appear only when the server allows it (`03` row 5) | `people_screen.dart`, `invite_dialog.dart` | E, loaded, invite made, invite used, O | C, X | |
| S-52 | **Year in Music** (a designed, shareable sequence) | `year_screen.dart` | L, E (too little listening), the sequence, share | C, X, T | |
| S-53 | **Friend activity** (later; opt-in, `../03a` US-62) | new (P6) | E, loaded | C, X | |
| S-54 | **Taste match** (later; opt-in on both sides, `03` row 8): what two people both like, their favourite genres, a shared playlist (Spotify's Blend is the pattern); the switch to take part and to withdraw | new (P4-17) | off (the default: the switch and one sentence on what is shared), waiting for the other person, matched, withdrawn at once, the other has not agreed (nothing is shown) | C, X | |

## Import and requests

| ID | Screen | Today | States | Classes | |
|----|--------|-------|--------|---------|---|
| S-60 | **Import** (Spotify, YouTube Music, paste a link, a file) | `import/import_screen.dart`, `encore_import_screen.dart` | Z, link recognised, D, done, a list that cannot be read, X | C, X | |
| S-61 | **Requests** (ask for music the server does not have) | `requests/` | E, sent, D, done, refused | C, X | |

## Settings

| ID | Screen | Today | States | Classes | |
|----|--------|-------|--------|---------|---|
| S-70 | **Settings** (the list) | `settings_page.dart` | loaded, the server card in each of O/U/W | C, X, T | |
| S-71 | **Your server**, with the personality of the Welcome pages: a hero card (name, colour, a small illustration, one sentence of status), "How this phone reaches it" (At home, Away from home), each address checks itself when the page opens and shows its own answer beside it (**no test button** since 2026-10-30, F40; `03` row 6 drew one), typed addresses under "Other ways to connect" (`03` row 6) | `your_server_screen.dart`, `server_addresses.dart` | Working, O, U, W, checking, learned addresses (`31` O-8) | C, X | ★ |
| S-72 | The settings pages, each drawn with these contents (the sections of Spotify's own settings, made smaller): **Playback** (crossfade, gapless, autoplay, volume levelling, equalizer, mono audio, offline mode, **streaming quality per network** and the best-quality tier when the Host switched it on); **Downloads and storage** (download quality, Wi-Fi only, used space, clear the cache, delete downloads); **Library and sync** ("Play adds a song to my library" on or off, update now, fix a library that looks wrong); **Home** (what Home shows); **Notifications** (**at most two opt-in phone categories, both off, one sentence each, e.g. "Jam invitations"**; Android's permission is asked only when one is switched on; the app has three switches for now, trimmed to two in RC2, D-48 d); **Lyrics**; **Appearance** (theme, black background, text size); **Privacy and social** (private listening, share what I play, taste match: all opt-in); **Devices** (this phone and the others, sign one out, DV-3) | `settings/*` | each: loaded, a value changed, a value the server refuses | C, X | |
| S-73 | **People and household** (the owner: add, remove, roles) | `household_settings_screen.dart` | loaded, adding, removing with a reason | C, X | |
| S-74 | **About and diagnostics** | `diagnostics_screen.dart` | loaded, a log copied | C | |
| S-75 | **Language** and **Accessibility options** | new, later (`../tasks/P6-later.md`) | drawn once the owner asks; the layouts already allow them | C, X, T | |

## Around the app (the system and the strip)

| ID | Screen | Today | States | Classes | |
|----|--------|-------|--------|---------|---|
| S-90 | **Connection strip**: one calm sentence for every outage (`../31` CN-1, D-45): "You're offline. Downloaded music still plays." or, with nothing downloaded, "You're offline. Nothing can play until you reconnect."; an address that answers as another server: "Another server answers at <host>." (O-6); a Jam that is listening again: "Reconnecting to the Jam…" | `connection_banner.dart` | O and U say the same sentence; W (another server answers) says "Another server answers at <host>." (`../31` O-6); Jam reconnecting; a cross to dismiss it, no Try again; said once per outage, gone by itself after 5 s | C, X, T | |
| S-91 | **Failed edits** (`34`) | `failed_edits.dart` | E, one, several, retry | C | |
| S-92 | **A permission is needed** (notifications, camera for a QR, storage) | platform, with our sentence before | asked, refused once, refused for ever (how to allow it); **notifications for download progress: asked once, the first time the person presses Download (D-52; drawn 5 Nov 2026), "Not now" or the phone's "Don't allow" ends it with no second question** | C | |
| S-93 | **Update needed** (the server needs a newer app, or the app a newer server) | `shrink_notice.dart` partly | the app is too old, the server is too old | C, X, T | |
| S-94 | **Lock screen, notification and car** | platform (`encore_audio_handler.dart`) | playing, paused, B, cannot play | platform | |

## In the browser (the server's own site, and later the web player)

*The browser pages (W-01 to W-08) are drawn in a fourth batch, after the app screens, so that the installer, the admin and the join page are on paper too before any of them is built (owner, 2026-10-24).*

| ID | Screen | Today | States | Classes | |
|----|--------|-------|--------|---------|---|
| W-01 | **Installer wizard** (`15` section 2: name and password, music folder, measuring, away from home, "all set") | server (`encore_server/setup`) | each page: Z, working, done, a step that failed with what to do | X (and C: the wizard is opened from a phone) | |
| W-02 | **Admin: health** (YouTube working, disk, last backup, version, yt-dlp updated) | `encore_admin` site | all good, a warning (key expires in 14 days), a failure | X | |
| W-03 | **Admin: people and invitations** | admin | E, loaded, invite made, removing with a reason | X | |
| W-04 | **Admin: library, away from home, backups, updates** | admin | each: loaded, working, failed | X | |
| W-05 | **Join page** for a person without the app (`/encore/join/<code>`) | server | valid, used, expired, the app is not installed (download), the app opens | C | |
| W-06 | **The web player** (everything in S-10 to S-52 at class X) | new (P6) | as the app | X | |
| W-07 | **Admin: settings** (the server's name and colour, the feature switches the app follows: "Friends on other servers", recommendations, the quality tier, plays any song; YouTube state and rest) | admin | loaded, a switch changed, a switch the server cannot honour (said in words) | X | |
| W-08 | **Admin: logs and diagnostics** (what the server has been saying, a copy to send to somebody, the versions) | admin | loaded, empty, a long log | X | |
| T-01 | **The terminal** (text, not drawn: the installer's output from the first line to "Encore is ready" with the pairing link and QR, and what each `encore` command prints) | `server/encore_server/deploy/install.sh`, `encore` | written in `15` §1 and §1b | text | |

## What this list does not contain, on purpose

The logo and the name (`../16`: P5-05); the home-screen widget, Android Auto and casting UI (platform surfaces, decided with their tasks); a payments or accounts directory (there is none, ADR-R40 option a).
