# 10 — Decisions for the owner, and open experiments

## Part A — Owner decisions

### Decided (2026-10-21, in chat)

| # | Question | Decision | Consequence in the plan |
|---|----------|----------|-------------------------|
| **D-2** | Storage | **Each song is stored once on the server** ("HDD space is expensive"); each person has their own playlists, likes, history and **recommendation profile** | Shared pool `/music/Encore/` (`04` §3); per-person library and profile |
| **D-3** | When the server keeps a song | **Saved** (like, playlist, album, import), **downloaded**, or **played on 2 different days** (owner: "plays a song today and tomorrow and the day after, we need to keep it") | Keeper triggers (`04` §3, P2-03); the "2 days" threshold is a server setting |
| **D-4** | First version scope | **Everything**: recommendations (per-person profile), Jam, friend activity, quality tier, Year in Music, "even if it means delaying the release by months" | New phase **P4 Full feature set** before **P5 Public release** (`08`, `tasks/P4-full-feature-set.md`) |
| **D-5**, **D-9** | Name, website | **Not now** ("let's not worry about website, name and things like that") | "Encore" stays the working name; P5-05 waits |
| **D-7** | Old GitHub repository | **New repository, yes**; old one renamed and archived; **no password changes** needed (temporary test passwords) | P0-04, P0-07 |
| **D-10** | The app's signing key | **Agreed**: an agent creates one release key, GitHub signs every release with it, the owner keeps one backup copy; one-time reinstall when switching from the debug key | `12-app-signing-key.md`, P5-01 |
| **D-11** | The homelab's 3 Mbit/s cap | Raised to 15 Mbit/s with the owner's permission | — |

### Still open (defaults apply until the owner says otherwise)

| # | Question | Default | Why | Blocks |
|---|----------|---------|-----|--------|
| **D-1** | Licence | **GPL-3.0** | Keeps Encore free; compatible with GPL libraries; CC BY-NC-SA is not a software licence | P0-05 (default used) |
| **D-6** | YouTube songs on by default | **On**, with a one-time notice and a switch | Otherwise Encore cannot play what you don't own | — |
| **D-8** | Let agents push to GitHub | **Needed**: the owner adds `"Bash(git push:*)"`, `"Bash(gh pr create:*)"`, `"Bash(gh pr ready:*)"`, `"Bash(gh pr merge:*)"`, `"Bash(gh release create:*)"` to `permissions.allow` in `C:\Users\you\.claude\settings.json` | Pushes were blocked before (46 commits stuck on the laptop); agents cannot change their own permissions | P0-07 and every task's "push often" rule |
| **D-12** | Quality tier default | **Off until the Host switches it on** in the admin, with the risks in plain words | Soulseek shares files (legal exposure varies by country); three extra containers | P4-04 |
| **D-13** | May this server talk to other Encore servers? | **On** by default, one Host switch; each connection also needs both people to accept; no directory or search | Owner: "servers communicating with each other? opt in?"; opt-in per relationship keeps it private (`13` section 4) | P4-09, P4-10 |
| **D-15** | Can someone with **no Encore server at all** join a Jam? | **Yes, as a Jam-only guest seat**: no account, no library, gone when the Jam ends | Otherwise a friend without a server cannot listen with you; it is not "inviting them to your server" | P4-10 |
| **D-16** | May connected servers keep copies of songs from this server (e.g. after a friend likes a Jam song)? | **Off** by default, one Host switch | Copying files between households is the Host's call (`13` section 5) | P4-10 |
| **D-17** | Android developer verification / paying to publish | **Decided by the owner (2026-10-21): distribute on GitHub only, pay nothing; not now.** If Google's rule blocks installs later, revisit (a free limited account covers 20 devices) | Owner: "let's leave it at GitHub, I don't want to pay anything" | P5-07 parked |
| **D-14** | "Always ready to play" (a device your other devices can wake) | **Off by default**, one switch per device, battery cost explained | Android needs a persistent notification for it (`13` H1) | P4-07 |

### Decided by the advisor (2026-10-30, reversible)

The user said the advisor owns the product decisions. After the first real install (`tasks/AUDIT.md`, owner's findings of 2026-10-30):

| # | Question | Decision | Why |
|---|----------|----------|-----|
| **D-18** | Which surfaces are designed and built now | **The phone app and the PC only.** The PC surface is the installer and wizard, the admin, and the front page and invitation page a browser or QR opens. The admin is PC-only. **Parked** (`tasks/P6-later.md`): a web player on a PC, TV, tablet-specific layouts, an admin on a phone or TV | The installer and admin are used from a computer; drawing and coding surfaces nobody has asked for is waste |
| **D-19** | A Soulseek choice at install | The wizard has a **"Where songs come from"** step: YouTube on by default; the higher-quality (Soulseek) source is an explicit, **off-by-default** choice with the plain-words legal note; the same switch in the admin; until P4-04 exists it shows as a grey "later" line, neither hidden nor faked | Supersedes D-12's "only in the admin": the owner expected to choose at install; the legal exposure still needs an explicit, informed switch |
| **D-20** | A YouTube sign-in | **None in v1 and none in the wizard.** The wizard says: "No YouTube account needed. Songs you don't have are fetched gently in the background." Revisit only if X-1 or real use shows refusals hurting someone | The account can be banned, it is the person's Gmail and photos, yt-dlp's OAuth sign-in no longer works (`02` Q5). The felt slowness of downloads was a bug (AUDIT F21) |

### Decided by the advisor after the owner's second report (2026-10-30, reversible)

| # | Question | Decision | Why |
|---|----------|----------|-----|
| **D-23** | The player's menu (F35) | **No "Playback speed" in the music player** (any saved speed is forced back to 1.0 on upgrade, or someone stays at 1.25x with no control); **no "Private listening" in the player** (it stays in Settings > Privacy & your music); the sleep timer stays in the ⋯ menu. Supersedes `design/03` row 9 on these lines | People rarely change the speed of a song; a switch that is always there and almost never wanted is noise (owner, 2026-10-30) |
| **D-24** | A tap and the 30-second preview (F33) | **Never a silent snippet.** On an Encore server, or while it is still being checked, a tap means the full song: while the instant backend loads the row shows a ring and "Getting ready", the tap waits and then plays the full song; if the server really cannot get it (YouTube off or resting, a failed look-up) a sentence says why, never a preview. A preview plays only from an explicit long-press, labelled "Preview (30 s)". On a plain music server previews stay, but every row and Play say "Preview". One helper starts previews; a test fails if `playPreviewRun` is called from anything but a long-press | The owner's phone played 30 seconds of every song: "the app is unusable" |
| **D-25** | The build says which build it is (F34) | About, Diagnostics and the copied report show `0.1.0 (build 123 · abc1234)`, the commit injected with `--dart-define` ("commit unknown" when absent, never nothing); every APK handed to the owner gets a new build number, the archive README maps build to commit; release candidate 1 is build 123 or higher; the server says its commit in `/info` and on `encore status` when that is small, else the image's `sha-` tag goes into `b11` | Every build since 2026-10-22 said "0.1.0"; nobody could say which APK a bug was on |
| **D-26** | Menus and selection (F31, F32) | **In release candidate 1: wire the menus that already exist.** A long-press and a visible ⋯ on every Library row open `collection_menu` (rename and delete for a playlist); a long-press on every song row opens `track_menu` (Add to playlist). **In RC2, drawn first (P2-21):** a playlist's description and picture, and multi-select | Reuses tested sheets, adds no screen, so "drawings first" holds |
| **D-27** | After the owner's third report (F38 to F44) | **F41:** one control for "my music / the whole server", on the Library page; first check what the Settings copy also governs (if it decides what Home shows, one setting that both follow, the control only on the Library page). **F43, friends:** P4, not RC1 or RC2 (following a person on your server or another Encore server, their activity, Jam together); for RC1 **hide every friend surface that does not work on an Encore server** (the Home friends shelf depends on the old people service). **F43, profile:** RC1: the avatar on Home opens one "You" page that gathers what exists (name, server, switch user, sign out); RC2, drawn first: edit name and picture (check whether the profile frames drawn in #25 already cover it). **F38, F40, F42:** approved as written. **F39:** the message is not red; it says that someone on your Wi-Fi can join without an extra address, names the fix that exists today (on the server computer `encore funnel on`, which needs a free Tailscale account) and explains Tailscale in one sentence in the Add-an-address dialog | Advisor, 2026-10-30, reversible |
| **D-28** | The player's device icon and the output (F45, F36) | **Release candidate 1 removes the icon**: it opens Android's system-wide chooser, so choosing there moves every app's sound. Encore's own **Devices** sheet comes with P4-07: this phone's outputs applied to Encore's player only, and the account's other devices with "Play here". Bluetooth switch-back (F36) is judged on that sheet, on a real phone and headset | A control that moves the whole phone's audio is worse than none |

## Part B — Experiments (questions only a test can answer)

Run by an implementing agent before or inside the task named. Each must stay small and safe (`06` §8).

| # | Question | How | Decides | Before |
|---|----------|-----|---------|--------|
| **X-1** | What background YouTube pace is safe over days on a home address? | Run the keeper at 120/h on the dev VM for 7 days with real saves; log refusals; then 200/h for 7 days | The default pace (`04` §5) | P2 exit |
| **X-2** | Can the gateway authenticate users itself and pass them to Navidrome with the reverse-proxy header for the **Subsonic API** too (streams, covers)? | Navidrome 0.64.2 on the dev VM with `ND_EXTAUTH_TRUSTEDSOURCES` = the gateway, a secret header; call `/rest/stream`, `/rest/getCoverArt` without `u/t/s` | Device tokens without storing passwords (P3-03); else keep Subsonic token pass-through | P3-03 |
| **X-3** | Is on-device extraction worth it as a fallback when the server cannot reach YouTube? | NewPipeExtractor via a Kotlin platform channel in a throw-away branch; measure APK size, tap → audible on mobile data, and count its breakages over the last 12 months | Whether to add it after v1 | P5 |
| **X-4** | Can the app read a person's Spotify playlists and Liked Songs by signing in on Spotify's own page inside the app (no developer app)? | WebView sign-in on the emulator with a real throwaway Spotify account; read the web player's library calls; check ToS wording and token lifetime | Spotify import beyond 100 songs (P2-06) | P2-06 |
| **X-5** | Does the "phone at home downloads directly" trick work on a phone (not only the PC)? | Emulator on the home network: server resolves 5 songs, the app downloads the addresses directly; then on mobile data (expect 403 → fallback) | Faster offline downloads at home | P2 (downloads) |
| **X-6** | How fast does the Android player start on the gateway's proxied stream (WebM/Opus, Range)? | just_audio/ExoPlayer on profiles A/B; measure `play.audible` for 12 songs; try `bufferForPlaybackMs` 1,000 vs default 2,500 | Player buffer settings (P1-02) | P1 exit |
| **X-7** | Do websockets work through Tailscale Funnel, and for how long? | Live channel through the public address for 2 h with a phone on mobile data | Live channel away from home (P2-08) | P2-08 |
| **X-8** | How does a Raspberry Pi 4 (or a 2-vCPU VM) cope? | Extraction time (Deno JS challenge), RAM of the stack, 3 people streaming | Minimum hardware on the website; worker sizing | P3 exit |
| **X-9** | Does the PO-token provider (bgutil) reduce refusals or unlock more clients? | Sidecar on the dev VM; compare clients and refusal counts over X-1 | Whether to ship it as an option | P3 |
| **X-10** | How accurately do Spotify songs match YouTube Music songs? | 100 real songs from the owner's Spotify playlists: match by ISRC (via Deezer) → YTM search; measure exact/wrong/missing by hand | Matching rules and the "Not found / Find it" UI | P2-04 |
