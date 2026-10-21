# 13 — Devices, volume, Jam and friends across servers (system design)

Owner, 2026-10-21: *"the volume control of the app isn't synced with my phone … I need to increase the sound of the music playing on
the tablet from my phone, as long as it's the same account. I should be able to play/pause, jam with someone who is or isn't on the
same server as me. How can I add a friend who is on a different server, and jam with him songs I have on my server, songs he has on
his server, and songs none of us have?"* All of this is in the **first version** (phase P4). Decisions: ADR-R15, ADR-R16 (`11`).

## 1. Volume: what is wrong today

| Finding | Evidence | Consequence |
|---------|----------|-------------|
| **V1** The app has **no volume control of its own**; the player's "Devices" button opens Android's Bluetooth/speaker picker (`AudioOutput.showSwitcher()` in `now_playing_screen.dart`) | code, 2026-10-21 | Controlling another device's volume is impossible |
| **V2** "Volume levelling" (ReplayGain) is **on by default** and changes the player's **internal** volume per song (`replay_gain.dart`, `playback_engine.dart` `_backend.setVolume`); positive gains add up to **+9 dB** through a loudness enhancer | code; on the test server 2 of 182 songs had tags, both positive (+0.9, +11.1 dB) | Songs jump in loudness depending on whether they happen to carry tags; the phone's slider can't compensate; tagged songs can distort |
| **V3** Untagged songs (everything fetched from YouTube) get 0 dB; tagged ones are moved; streams from YouTube carry no tags at all | same | Inconsistent loudness between sources |
| **V4** The Jam protocol has a host `volume` (0–100) that **no phone applies** (`encore_session` `SetVolume`; no use in `lib/features/jam`) | code | A Jam "volume" that does nothing ("sometimes works") |
| **V5** The sleep-timer fade writes the internal player volume; an interrupted fade restores it in most paths, but internal volume is a second volume the person cannot see | code | Another source of "volume not in sync" |
| **Old report F12** "The volume slider is bugged, not in sync with my phone's slider, sometimes works" | `old-app/docs/39` | Never reproduced or answered |

**Rule from now on:** there is **one volume per device: Android's media volume** (the one the phone's buttons and system panel
control). Encore never uses the player's internal volume as "volume". Loudness levelling is a separate, gentle, consistent correction
(below). The Jam host's volume and remote volume both set the *target device's media volume*.

**Loudness levelling, fixed (task P1-13):** the server measures every kept file once (EBU R128 integrated loudness with `ffmpeg`
`loudnorm`/`ebur128`, or `rsgain`) and writes ReplayGain tags; streamed catalogue songs use the loudness YouTube reports in its player
response when available (verify), else a default; the app targets −14 LUFS like Spotify's "Normal", **never boosts** by default (cut
only; boost is an option "Loud" with a limiter), and the setting has three positions: Off / Normal (default) / Quiet environment.

## 2. Your devices ("Encore Connect")

Same account, several devices (phone, tablet, later a PC/web player). Spotify Connect is the yardstick.

**What a person can do (US-70, US-71):**
* See their devices in the player's **Devices** sheet: this phone, "Tablet", "Living-room PC"… with which one is playing.
* Tap a device → playback **moves there at the same second** (the queue and position move; the old device stops).
* While another device plays, this phone is a **remote**: play/pause, next/previous, seek, queue, like, and **volume**: a slider in
  the Devices sheet and the **phone's own volume buttons** control the tablet's volume (Android shows its usual volume panel
  labelled with the tablet's name).
* On the tablet, the volume changed from the phone moves the tablet's own media volume, so its slider and buttons stay in sync.

**How it works:**
```
phone (remote)                 Encore server (playback + live modules)                 tablet (active device)
 tap "Tablet" ───── PUT /playback/transfer {to: tablet} ──► lease → tablet ──── live: device.command{play at 1:10} ─► plays
 volume key ─────── POST /devices/{tablet}/command {setVolume: 60} ─────────────► live: device.command{volume 60} ─► AudioManager
 ◄── live: device.state {volume 60, playing, position} ◄────────────────────────────── reports state (on change + every 5 s)
```
* **Device registry** (server): id, person, name, kind (phone/tablet/web), app version, last seen, "available" flag, current volume.
* **Commands** go through the server (same path at home and away), not device-to-device: works across networks and NAT, one
  authority, ordered by a revision number; the active device acknowledges; the remote shows the confirmed state (optimistic UI
  with rollback after 2 s).
* **Volume on the target** = Android `AudioManager.setStreamVolume(STREAM_MUSIC, …)` through a small platform channel; the target
  reports its volume whenever it changes (the phone's buttons, the system panel, another remote).
* **The remote's volume buttons**: while a remote device is active, the app's media session switches to Android's *remote playback*
  mode (`audio_service` 0.18.19 `androidPlaybackInfo` = `RemoteAndroidPlaybackInfo`, callbacks `androidSetRemoteVolume` and
  `androidAdjustRemoteVolume`), so the hardware buttons and the system volume panel act on the tablet. Back to local when this
  phone plays again.

**The Android constraint nobody planned for (hidden risk H1):** a device can only be commanded if Encore is running on it. Android 12+
forbids starting playback (a foreground service) from the background on a plain network message, and Encore has no push service
(no Google Firebase, by design). So:
* A device is **available** while Encore is open or playing, and for 10 minutes after it was last used (the app keeps its live
  connection inside the existing media service while paused).
* A tablet that should always be ready (on a stand, a kitchen speaker) can turn on **"Always ready to play"**: a small persistent
  notification ("Encore is ready to play from your other devices") keeps the connection; the setting explains the battery cost.
* A device that is not available is shown greyed, "Open Encore on the tablet to play there".
* Optional later: a self-hosted push channel (UnifiedPush through the Host's server) to wake devices without the notification.

## 3. One person, one account, one home server (ADR-R17)

Owner, 2026-10-21: *"I don't want to have an account on 2 servers … 2 accounts, one phone, one user is stupid and lazy … I don't want to
invite someone to my server just for us to have a Jam session."*

**The rule:** every person has **exactly one account, on their home server**. Their app talks **only** to that server. Anything they
do with someone on another server, their home server does **on their behalf**, by talking to the other server. Email works this way:
one address, and you can write to anyone on any provider.

```
 Nina's phone ──► Nina's home server  ◄────── signed server-to-server calls ──────►  Mia's home server ◄── Mia's phone
 (only ever talks                                                                      (only ever talks
  to its own server)                                                                    to its own server)
```

What this removes: a second account, a second login, a second library, a second address in the app, inviting strangers into your
server, and the other server ever seeing your phone.

**Options considered.**

| Option | Verdict |
|--------|---------|
| Two accounts in one app (the previous draft) | **Rejected** (owner): pushes the complexity onto people; two libraries, two logins |
| Invite the friend onto my server for the Jam | **Rejected** (owner): an account just to listen together |
| The guest's phone connects directly to the host's server with a Jam pass | Works, but the phone must know and reach a second server, and that server sees the phone; replaced by the relay below |
| Phone-to-phone (WebRTC) | Fails behind carrier NAT without a relay server; would need a central relay |
| A central Encore service that connects servers | Against "no cloud", costs money, legal exposure for the project |
| Matrix (an existing open federation standard) | Proven, but a whole chat homeserver per Encore install; far heavier than the few calls needed |
| **Home servers talk to each other** (chosen) | One account each, nothing central, the app stays simple, privacy by default |

## 4. Connecting with people on other servers (ADR-R16)

**A choice at three levels** (owner, 2026-10-21: "not everyone would want his server to talk to other servers … on by default for
the basic setup and a choice for the normal user"):
1. **The Host, during setup:** a page of its own in the setup wizard (`15` §2, page 7) asks in plain words, with **Yes preselected**.
   Changeable any time in the admin. Off = the server never contacts or answers another server.
2. **Each person, for themselves:** Settings → Privacy → "People on other Encore servers can connect with me", **on by default**;
   off = their friend codes stop working and their server refuses requests for them, even if the Host allows it.
3. **Each relationship:** nothing happens until two people *both* agree. There is no directory and no search: you cannot be found,
   only given a code.

**How a person connects (US-72):** in the app, Friends → "Add a friend" shows a **QR code and a short link** (it holds
`mia@<her server's public address>` and a one-time code). Nina scans it in her own Encore app. Nina's server sends a signed request
to Mia's server. Mia sees "Nina (on another server) wants to connect" → Accept. Both servers store the link. Either can remove it
at any time; removing stops everything shared at once.

**Under the hood (kept small):** each server has a key pair published at `https://<server>/.well-known/encore` (public key, API
version, name); requests between servers are signed (HTTP Message Signatures) and keys are pinned on first contact; rate limits per
remote server; a friend link is the only thing that lets another server ask anything about a person. Both servers need a public
address (Tailscale Funnel or the Caddy option); a server without one shows "Friends on other servers need away-from-home access".

**What crosses between servers, only when a feature needs it:** display names and avatars of connected friends; activity if that
friend chose to share it; Jam state and the Jam queue's song descriptors; the audio of a song **only while it is in a live Jam**
(§5); a song or playlist a person explicitly sends. Never a library, a history, a profile or a playlist by itself.

## 5. Jam with anyone (US-73)

**Starting and joining.** The host taps "Start a Jam" and shows a QR code or sends a link.
* **Someone on the same server** joins directly, as before.
* **Someone on another Encore server** scans it in their own app. Their **home server joins the Jam for them** (server-to-server);
  their phone only talks to its own server. **No friendship is needed** for a Jam: the Jam code is the permission, valid until the
  Jam ends. (Friends can also be invited from the friends list without a code.)
* **Someone with no Encore server at all**: the only case that needs a seat on the host's server. It is a **Jam-only guest seat**:
  no account, no library, no password; the app (or, later, a web page) joins that one Jam and the seat disappears when the Jam ends.
  *(Open question for the owner, D-15: include this, or Jams only between people who have Encore?)*

**Who keeps time.** The host's server holds the Jam state and the clock. Each guest server relays the Jam to its own phones over their
normal live channel and forwards their actions (add, skip, pause) to the host's server. Each phone measures its clock offset to its
own server; each guest server measures its offset to the host's server; the two add up, so all phones stay within the sync budget.

**Where each phone gets the audio** (the owner's three cases). Every song in the Jam queue is a **portable song descriptor**
`{title, artists, album, durationMs, isrc?, mbid?, ytmVideoId?, origin: {server, ref}}` written by whoever added it. **Each phone asks
only its own home server**, which finds the best source:

| Song is… | Mia's phone (host, Mia's server) | Nina's phone (guest, Nina's server) |
|----------|----------------------------------|-------------------------------------|
| **On Mia's server** | plays Mia's file | Nina's server: has it? → plays it. Can get it from YouTube? → streams it. Neither → Nina's server **fetches it from Mia's server for this Jam** (a grant scoped to this song in this live Jam), streams it to Nina's phone, and keeps it only in a temporary Jam cache |
| **On Nina's server** | the mirror image: Mia's server fetches it from Nina's server for the Jam | plays Nina's file |
| **On nobody's server** | Mia's server streams it from YouTube using the **same video id** the adder picked | Nina's server does the same |

Each home server uses its own line and its own YouTube allowance, so a Jam spreads the load across homes.

**Keeping versions aligned (H2).** Two copies of "the same song" can differ (CD rip vs YouTube upload, radio edit vs album version).
A substitute copy is used only if its length is within ±1.5 s of the descriptor; otherwise the home server uses the adder's source
(the Jam grant or the same video id). Phones report the offset they measured; the host sees "out of sync" per person.

**Controls and rules:** like Spotify's Jam (owner: no invented rules). Everyone can add, reorder, remove and skip; the host can remove
people, end the Jam and set the **host device's** volume (media volume, §1). The Jam uses each person's normal player (field test).

**Liking a song you heard in a Jam** saves it in *your* library on *your* server. If your server can get its own copy (it already has
it, or from YouTube), it keeps it (D-3). If the song exists only on the other person's server, your like is kept as a reference that
plays when a source is available; copying files from someone else's server needs that server's Host to allow it ("Let connected
servers keep copies of songs from here", **off by default**, D-16).

## 6. Hidden risks found while designing this

| # | Risk | Handling |
|---|------|----------|
| H1 | A backgrounded or killed app cannot be woken to play (Android background limits, no push service) | "Available" window, "Always ready to play" option, greyed devices with an explanation; later UnifiedPush |
| H2 | Different copies of a song are not the same length | ±1.5 s rule, adder's source as the reference, measured offsets |
| H3 | A guest's own server is offline or not public | It cannot join through it (the phone only talks to its own server); the app says why; the Jam-only guest seat (D-15) is the fallback |
| H4 | The host's upload is small (ADSL 1 Mbit/s) and several guests stream from it | Guests prefer their own servers; grants transcode to Opus 96–128; the host sees "Jam is using your upload" |
| H5 | Two devices of the same person both think they are active (network split) | Server lease with revision numbers; the device without the lease pauses on its next check (≤ 15 s) |
| H6 | Remote commands arriving out of order (seek then pause) | Commands carry the state revision they were made from; stale ones are dropped |
| H7 | Clock differences between phones in a Jam | Server clock offset measured per phone (NTP-style ping exchange), as in `encore_session` |
| H8 | Federation spam or abuse (friend requests from strangers) | Friend links need a one-time code from a person; signed requests; the Host's switch; rate limits per remote server |
| H9 | Legal: streaming files to people outside the household | Only songs in an active Jam, to people the host invited, transcoded, never stored by the guest; plain text in the Jam screen; the Host can disable cross-server Jams |
| H10 | Volume commands on Android 15+ from the background | Verify `setStreamVolume` from a background app holding a media session (spike in P4-07) |
