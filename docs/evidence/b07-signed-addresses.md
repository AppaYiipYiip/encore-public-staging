# B-07 — In Encore mode a song and a picture come by the server's signed address, with no login of the music server in either (2026-10-25, P2-20 slice 2)

Fourth walk in the record shape of `07` §12. Rows: `tasks/P2-songs-as-references.md` P2-20 slice 2 ("Proof"): songs, pictures, the quality extras, and the time to sound (N1).

| Row | Setup | Steps | Expected | Got | Verdict | Evidence |
|-----|-------|-------|----------|-----|---------|----------|
| Songs, no `/rest/stream` | Emulator A (`emulator-5556`, release build of the branch over the old build, signed in as `newtester`), dev VM server with the branch's code and its access log switched on **in the dev copy only** (restored afterwards) | Cold start; Your Library, Liked Songs; tap each of the five kept songs, twice round | every play asks `GET /refs/{ref}/stream-url` at most once per song and then plays `GET /encore/stream/{ref}`; no `/rest/stream`, no `/rest/download` | 5 `stream-url` for 5 songs (the second round asked none: the address was remembered), 38 `/encore/stream/{ref}` (26 `206`, 12 `200`), **0** `/rest/stream`, **0** `/rest/download` | Pass | request summary below |
| Pictures, no `/rest/getCoverArt` | same, the app's caches trimmed (`pm trim-caches`) and the app force-stopped, then started | Home opens; wait 20 s | one ticket (`GET /covers/pass`), every picture by `GET /encore/cover/{id}` with that ticket | 1 `covers/pass`, **80** `/encore/cover/{id}` (all `200`), **0** `/rest/getCoverArt` | Pass | request summary below |
| Pictures on screen | same | look at Home | covers are drawn, not letters | Home shows the covers of the albums, playlists and the mini player (screenshot `new-home3`) | Pass | the screen |
| The address carries no login | unit and session tests | write a picture address and a song address | no `u`, `t`, `s` parameter | `session_encore_test` ("P2-20: in Encore mode a picture is asked for with the cover ticket…", "…a song is played from the server's signed address…"); the request summary shows the phone sent no `/rest/stream`, `/rest/download` or `/rest/getCoverArt` at all | Pass | tests; request summary |
| Quality extras | server test | `maxBitRate=128&format=mp3&estimateContentLength=true` on a kept song's address | passed on to the music server; a bad value refused in words | `tests/test_kept_files.py` (3 tests) | Pass | tests |
| N1, tap to sound, kept song | same phone, same five songs, ten taps | `tools/journeys` timing of tap to "audible" (the media session says PLAYING and the audio system has a started track) | not worse than before | **before** (the build on the phone before the install): median 1.42 s, min 1.32, max 2.05; **after**: median 1.40 s, min 0.99, max 4.20 (the first tap of the run; see F-1) | Pass (median); F-1 open | timing script output below |
| N1, first tap after a cold start | force-stop, start, wait 20 s, Liked Songs, tap | one tap on a kept song | not measured before (the old build was overwritten) | 2.14 s and 2.35 s | Recorded, no baseline | — |

## Request summary of the phone (dev server, masked; paths with ids written as `ID`/`REF`)

```
 80 GET /encore/cover/ID 200
 26 GET /encore/stream/REF 206
 12 GET /encore/stream/REF 200
 10 GET /rest/scrobble 200
  7 GET /encore/api/v1/info 200
  5 GET /encore/api/v1/refs/REF/stream-url 200
  4 GET /rest/getScanStatus 200
  4 GET /encore/api/v1/library/changes 200
  1 GET /encore/api/v1/server 200
  1 GET /encore/api/v1/library/files 200
  1 GET /encore/api/v1/covers/pass 200
```

What still goes to the music server's `/rest` from this phone in Encore mode, and so is the work of the next slices: `getScanStatus` (the browse index probe), `scrobble` (the "now playing" mark, ten calls), and what is not in this list because it was not done in the walk (`getArtists`/`getAlbumList2` when the library changed, playlists of the old path, `getSong`/`search3` of the instant-play resolver).

## Timing

```
before (old build, 2 rounds of 5)            after (this build, 2 rounds of 5)
round 1: 2.05 1.67 1.45 1.84 1.53            round 1: 4.20 2.17 1.12 0.99 1.39
round 2: 1.38 1.32 1.38 1.37 1.35            round 2: 1.99 1.36 1.41 0.99 1.43
n=10 median 1.42 s (min 1.32, max 2.05)      n=10 median 1.40 s (min 0.99, max 4.20)
```

## Findings

* **F-1: one slow first tap (4.2 s) after the install.** The three runs after it (the second round, and two cold starts at 2.14 s and 2.35 s) did not repeat it. It is the first tap of the run, right after a long idle of the emulator; the likely cause is the cold engine plus the first signed address (a round trip), not the address itself (the server answers it in milliseconds on the LAN). Not proved; `play.audible` spans (P1-06) in a profile build would say. Watch it in the five-day use.
* **F-2: this branch predates #29**, so the build asked for Android's notification permission at first start. Not a defect of this change (main has the three alerts off); the walk dismissed it.
* **F-3: `pm clear --cache-only` hangs on this emulator image**; `pm trim-caches 999G` works and was used.
* **F-4: the server's access log is off by design** (it would hold titles and logins); for this walk it was switched on in the dev VM's copy of `__main__.py` and put back by deploying the branch's code again. Credentials were masked in everything read.

* **F-5: an address now runs out (6 hours), a `/rest` token address never did.** Read, not walked: (1) *the player*: a song that fails because its address ran out goes through `_onBackendError`, whose one quiet retry calls `_loadCurrent`, which asks the resolver again, which asks `StreamAddresses.forRef`: the remembered address has run out by then, so a new one is fetched (a pause overnight resumes after a retry of a second). The quiet retry is given back once a song has played (`_retried.remove`). (2) *The phone's clock*: the expiry is the server's own `expiresAt - serverTime` counted on the phone's clock (`EncoreApi._expiry`, test "an address lives as long as the server says it does…"), so a phone whose clock is hours out neither keeps a dead address nor drops a good one. (3) *Downloads*: the address is built when a download is started (`_startOne`), and only when the policy allows a transfer (Wi-Fi), so it is fresh; a transfer that the system stops and resumes for more than 6 hours on the same task would fail and need the person's retry (the manager re-queues only `queued` rows). Accepted for now, to watch in the five-day use.
* **F-6: covers drawn before the ticket arrives.** The placeholder address and the real one share one cache key, and `CachedNetworkImageProvider` is equal for equal keys, so the image would have stayed as it was. The resolver now says `ready`, and the image widget is keyed on it (`test/features/cover_pass_widget_test.dart`: the key changes once, when the ticket arrives, and not at each rebuild; a ticket renewed later does not rebuild the pictures).

## Not covered

A kept song downloaded for offline (the code path is the same signed address with the quality extras; unit-tested only); a signed address that expires during a song (the margin is 10 minutes of the 6 hours; unit-tested); a cover ticket that expires while the app is open (renewed on return to the app; unit-tested); the phone away from home on the public address; the impostor server (`b03`) run against this build.

## YouTube look-ups spent

None (all songs were kept songs).
