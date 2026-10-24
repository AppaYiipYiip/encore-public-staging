# B-04 — The server goes away while a song is asked for or playing (2026-10-24, G-1, build 120 from `task/G-1-wait-for-the-server`)

Second walk in the record shape of `07` §12, and the first with **a fault produced on purpose** (ADR-R41 T4): a Toxiproxy between the emulator and the dev server takes the server away and back (`tools/journeys/fault_walk.py`). Rows checked: `33` PB-F7, PB-F8 (and `31` CN-14, the strip). Expected comes from those rows: *the song waits, nothing hops, it carries on by itself when the server answers, within 5 s* (`07` J-07).

| Row | Setup | Steps | Expected | Got | Verdict | Evidence | If Fail |
|-----|-------|-------|----------|-----|---------|----------|---------|
| PB-F7 (old behaviour, from the code) | main before G-1 | a song fails while the phone has a network and the server does not answer | (the row's "Wanted") wait like PB-F1, do not hop | not walked on the old build: the code treated it as a bad song, one quiet retry, "Couldn't play …", the next song (docs/33 as written on 2026-10-23) | **Fail** (by reading the code, not by a walk) | `33` as of `73486fb` | S3 (a run of error notices and a stopped queue on every server restart) → G-1 |
| PB-F7 | **New build.** Emulator A signed in through the proxy (the only saved address is `http://192.168.50.133:4550`; the server's `ENCORE_HOME_URL` points at the proxy so the phone learns no way round it). The proxy is **down** before the tap | Home, open the album *The Dark Side of the Moon*, tap *Breathe (In the Air)* | A sentence once, not an error; the song stays; no "Couldn't play …"; no hop; the strip says "Can't reach your server." | **"Waiting for your server." on screen 3.7 to 4.3 s after the tap** (4 runs: 3.5, 3.7, 3.8, 4.3 s), the play button paused, the title unchanged for the 8 s more the server stayed away, no error notice, the strip "Can't reach your server." over the album | **Pass** | `fault_walk.py pb-f7` timeline (below) | — |
| PB-F7 → resume | the same, the proxy brought **up** | wait | Plays by itself within 5 s of the server being back (`07` J-07) | Audible **11.1 s** after the server was back with retries at 2, 4, 8, then every 15 s; **6.3 s** with 1, 2, 3, then every 5 s; **7.5 s** with the final 1, 1, 2, then every 3 s but sampled only every 3.7 s (the screen read); then **4.9 s** on the final build sampled every 0.7 s (retries at 1, 1, 2, then every 3 s) | **Pass** on the final build (4.9 s, within the 5 s bound; the margin is small: one retry step of up to 3 s, one look at the addresses and the load of the song) | `fault_walk.py pb-f7`, final run | — |
| PB-F8 | Final build. The proxy cuts every connection after 300 kB (so a short song cannot be buffered whole), then goes **down** 3 s after the sound starts | Tap *Brain Damage* (3:48), wait for sound, take the server away for 8 s after the music stops, bring it back | The buffered seconds play; then "Waiting for your server."; **the song does not change**; when the server is back the song carries on | The buffer lasted **75 s** (110 s in an earlier run; the player's own retries then give up). Then "Waiting for your server.", the title stayed *Brain Damage* for the whole 8 s, and the sound was back **4.7 s** after the server was | **Pass** (the position the song resumed at could not be read on the phone: the media session's position is not a live clock; it is pinned in the unit test, `+42s`) | `fault_walk.py pb-f8` timeline | — |
| PB-F8 (first build of G-1) | Same, before the fix below | same | same | **Fail:** after the failure the Android player **moved to the next song by itself** (*Brain Damage* became *Breathe (In the Air)* while "Waiting for your server." was on screen), and when the server returned it played *Breathe* | **Fail** → fixed in the next commit | the timeline of that run (below) | S3 (a hop that skips a song on every server restart) → `playback_engine.dart` `_onBackendIndex` now ignores an index event once the engine has unloaded the window; test `PB-F8: the platform player hopping to the next source after the failure does not move the song` (fails without the fix: `t2` instead of `t1`) |

## What the walk found that no test could

On Android, `just_audio` (ExoPlayer) answers a failed source by `seekTo(next); prepare(); play()`. The engine's `_onBackendIndex` cannot tell that from a song that ended and moved on (a gapless advance), so the queue followed the player to the next song. Every unit test used a fake backend that never did this. The fake now has `failCurrentAndHop()` and the case is pinned. This is the kind of thing T4 exists for.

## Timeline of the first PB-F8 run (the hop), abridged

```
[ 16.6s] proxy DOWN
[ 27.0s] player PLAYING  audible=True   'Brain Damage'  screen: Can't reach your server.      (the buffer plays; the strip is honest)
[145.0s] player BUFFERING audible=False 'Brain Damage'  screen: Waiting for your server.
[149.1s] player BUFFERING audible=False 'Breathe (In the Air)'                                   <- the hop
[160.2s] proxy UP
[167.4s] player PLAYING  audible=True   'Breathe (In the Air)'
```

## Final PB-F7 run

```
[  0.4s] proxy DOWN
[  8.1s] tap 'Breathe'
[ 12.6s] screen: Waiting for your server. | Can't reach your server.        (4.3 s after the tap)
[ 15.4s] player PAUSED  'Breathe (In the Air)'
[ 21.9s] proxy UP
[ 26.8s] player PLAYING audible=True 'Breathe (In the Air)'                  (4.9 s after the server was back)
```

## Setup in detail

| | |
|-|-|
| Phone | emulator A (`emulator-5556`), x64 release build of the branch, **signed in again** after `pm clear` through `192.168.50.133:4550` (so the new typed form, the key check and trust on first use ran for real); notifications allowed |
| Server | the dev VM's Encore server with slice A (same id `l2tkw2ujmhueoyz263qgicxfyu`), person `newtester` |
| Fault proxy | `ghcr.io/shopify/toxiproxy:2.12.0` as the container `toxiproxy` on the dev VM (host network, control API on `127.0.0.1:8474`), proxy `encore`: listen `0.0.0.0:4550`, upstream `127.0.0.1:4540`; "down" is `enabled:false` (connections refused at once); the 300 kB cut is a `limit_data` toxic. The server's `ENCORE_HOME_URL` was `http://192.168.50.133:4550` for the walk, so the phone cannot learn a way round the proxy (a first attempt with the direct address left the phone reaching the server whatever the proxy did: the learned address at work, `evidence/b03`) |
| Measuring | `fault_walk.py` reads the media session and the audio system as `play_timing.py` does ("audible" = PLAYING and a started AudioTrack), the screen only every 3 s (a screen read costs about 3 s); **times of things only the screen shows are good to 3 s, times the player shows to about 1 s** |
| Songs | owned (the server's own library); no YouTube look-ups |

## Findings that are not rows

* **F-1: the stall is noticed late.** The buffered part of a song keeps playing for 75 to 110 s after the server went away, then the player's own retries give up and the engine learns of it. During that time the strip says "Can't reach your server." and the music plays; this is honest, and the player's own retries are better placed to recover a short outage than ours. A quicker "Waiting for your server." while the buffer drains was considered and not done (it would second-guess ExoPlayer's retries).
* **F-2: the media session's position reads 0 or stale on the phone** (`dumpsys media_session` is not a live clock), so "carries on from where it stopped" is proved by the unit test, not by the walk. A cheap way to read the real position on a device (the app's own diagnostics) would make it checkable (open).
* **F-3: the first walk attempts failed for setup reasons worth keeping:** the direct address learned from the server bypassed the proxy; the album's lowest rows sit under the mini player so their taps never land (use rows 1 to 4); an 8 to 15 s retry delay made the resume 11 s. A screen dump taken after typing into the wrong field **printed part of the dev test account's password**; it was rotated at once (`tools/rotate_password.py`, never prints it) and the form is now filled with TAB between fields.

## Not covered

The server restarting at the same time as a network change (Wi-Fi to mobile); the Away (Funnel) address; a slow server rather than an absent one (the 12 s load limit, PB-F6, has unit tests only); a Jam song; a song from the catalogue that the server fetches (it needs YouTube look-ups); a real phone; resume after the app was killed while waiting.

## YouTube look-ups spent

None.
