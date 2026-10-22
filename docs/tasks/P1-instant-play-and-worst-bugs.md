# P1 — Instant play, and stop the worst bugs

Goal: a song you don't own is audible in ~2–3 s (≤ 10 s worst) and the player never gets stuck; offline and covers work.
This phase changes today's architecture as little as possible: the YouTube code is written as a **reusable package** that P3
moves into the single server unchanged.

Paths below are in the **old layout** (`old-app/…`); after P0-04 prefix app paths with `app/` and server paths with `server/legacy/`.

Three lanes can run in parallel: **Server** (P1-01 → P1-02 → P1-03, P1-05), **Player** (P1-08, P1-09, P1-11), **UI** (P1-07,
P1-10, P1-12). P1-04 and P1-06 connect them.

---

## P1-01 — The lean resolver (server) — Size M
* **Status 2026-10-22: implemented** in `server/legacy/encore-fetch` (`lean.py`, `direct.py`; 62 new tests incl. real recorded YouTube Music answers). Measured: search 13.5 s → 0.5 s median, tap to audio-ready 38 s → 4.3–8.7 s (`../09` §7). Left for later tasks: stream proxy without any download (P1-02), separate interactive/background pools and pacing (P1-03), preparing ahead (P1-04).
* **Why.** B1, B2, B3: 33–35 s of "searching" per song; up to 8 `yt-dlp` processes and 5 watch-page extractions per song.
* **Context.**
  * Today: `server/encore-fetch/encore_fetch/resolve.py` (`YtDlpResolver`: `plain_candidates` = `ytsearch8` subprocess, then
    `music_candidates` = YTM search page + up to 5 `yt-dlp -j` subprocesses in parallel; scoring in pure functions `best()`,
    `Candidate`, `Want` — keep these, they are well tested), `download.py` (`YtDlpDownloader.extract/download` = more subprocesses),
    `run_command()` = `subprocess.run` per call; `cookies.py`/`accounts.py` leases add cookies args (keep the interface, optional).
  * Measured lean path (`../09` §2.3, script `../evidence/scripts/fastpath.py`): `ytmusicapi.YTMusic().search(q, filter="songs")`
    0.4–2.0 s; `yt_dlp.YoutubeDL(...).extract_info(url, download=False)` in a warm process 0.9–2.5 s; first byte 0.1–0.3 s.
    5/5 right picks. Long content (recitations, DJ sets, podcasts) is often a "video", not a "song": search `filter="videos"`
    when "songs" has no candidate within the scoring threshold.
  * The container has yt-dlp 2026.08.19, yt-dlp-ejs 0.8.0 and Deno 2.9.7; yt-dlp's user config contains `--js-runtimes node`
    while node is absent (Deno is used anyway): set the runtime explicitly in options.
* **Do.**
  1. New package `server/encore_sources_youtube/` (pure Python, typed, its own tests): `Searcher` (ytmusicapi, songs then videos,
     maps results to the existing `Candidate`), `Resolver` (scores with the existing `best()`; returns `video_id` + metadata),
     `StreamLocator` (yt_dlp library, **one `YoutubeDL` per worker thread**, `cachedir` on the data volume so player code is reused,
     format `bestaudio[acodec=opus]/bestaudio`, returns `url`, `http_headers`, `filesize`, `expires_at` parsed from the URL's
     `expire=` parameter), an in-memory URL cache (until 10 min before `expires_at`).
  2. Pin `ytmusicapi` in the service's requirements; record its licence (MIT) in the PR.
  3. Wire the package into `encore-fetch` in place of `YtDlpResolver` and `YtDlpDownloader.extract` (keep the old classes until P1-02
     lands, behind a setting `RESOLVER=lean|legacy`, default `lean`).
  4. Log stage times per job: `search_ms`, `extract_ms`, `first_byte_ms`.
* **Don't.** Spawn a process per look-up (a unit test must fail if `subprocess.run` is called on the lean path). Remove the scoring
  rules (version words, Topic preference, length check). Run more than 10 live look-ups per test run (`../06` §8).
* **Acceptance.** On TYPICAL, 12 never-resolved songs from the pool (`../07` §8): search p95 ≤ 1.5 s, extract p95 ≤ 3 s, total
  p50 ≤ 2.5 s. A labelled set of 40 real queries (artist + title as people type them, incl. Arabic/French/Japanese titles, covers,
  live versions) picks the right recording ≥ 38/40 using **recorded** YouTube Music responses (fixtures), not live calls.
* **Tests.** Unit (scoring on YTM-shaped candidates), fixture-based resolver tests, one live canary test marked `live` (≤ 3 look-ups).
* **Evidence.** Stage-time table for the 12 songs; the 40-query result table.

## P1-02 — Stream first; length limits only for keeping; fault flags (server + app) — Size M
* **Why.** B1; a 2-hour audio recording must play. Today the app polls a job every 1.2 s and starts on a growing file after 24 KiB of a
  `yt-dlp` download; songs > 45 min or > 80 MB are refused (`config.py` `MAX_DURATION_S=2700`, `MAX_FILE_MB=80`).
* **Context.** Measured: 2:21:21 recitation (163 MB) ready in 2.7 s, jump to 90 % in 0.4 s via Range (`../09` §2.5). Stream URLs are
  bound to the server's public IP, so the server must proxy them (except X-5).
* **Do.**
  1. `GET /api/stream?videoId=…` or `?artist=&title=&album=&durationSec=` (same auth as today): resolves inside the request
     (P1-01), then **proxies** the googlevideo bytes to the app with `Range` support and the right `Content-Type`
     (`audio/webm` for Opus-in-WebM), as one **fetch session** per video id: the bytes are also written to a cache file; a second
     reader joins the session; a Range beyond what is written is proxied from upstream with its own Range request.
  2. Hard timeout: if no audio byte can be sent within 10 s, answer `504` with `{error, message}` in plain words.
  3. Length/size limits apply only when *keeping* a file in the library; streaming has no length limit.
  4. Fault-injection flags for tests: `ENCORE_FAULT=youtube_refuse|slow_extract:<ms>|no_results` (off in production builds).
  5. App (`lib/features/instant/instant_controller.dart`, `lib/data/fetch/fetch_client.dart`, `lib/playback/`): play the stream URL
     directly (no job polling before sound); keep the job/keep path for "add to library" only. Tune the player start buffer
     (X-6: try `bufferForPlaybackMs` 1,000).
* **Acceptance.** J-02 on TYPICAL: p50 ≤ 2.5 s, p95 ≤ 4 s, max ≤ 10 s (12 songs, measured by P1-06); J-10 (2-hour recitation):
  audible ≤ 4 s, seek to 2:00:00 audible ≤ 2 s; with `youtube_refuse` a tap fails in ≤ 10 s with one sentence and the player stays usable.
* **Depends on.** P1-01, P1-06. 

## P1-03 — Two pools, single flight, pacing and back-off (server) — Size M
* **Why.** ADR-R6, ADR-R8; measured: 6 shared workers made each look-up 9 s instead of 2 s.
* **Context.** `jobs.py` has priorities `now` / `prep` / `bulk` with 3 workers and "bulk may use at most two"; imports have their own
  pacing (`IMPORT_MAX_PER_HOUR`, back-off after refusals) in `imports.py`; `classify_failure()` maps yt-dlp errors to codes.
* **Do.** An **interactive pool** (taps, prepares; size = max(2, cores/2)) and a **background pool** (import matching, keeping;
  size 1–2) that never share workers; **single flight** keyed by video id (and by normalised query for searches); one server-wide
  **budget**: background look-ups ≤ 120/hour (setting), random spacing 5–20 s; on `blocked`/429/"confirm you're not a bot":
  background paused 30 min, doubling to 24 h; interactive continues at ≤ 1 look-up per 5 s; `GET /api/info` reports
  `youtube: ok|busy|paused-until|unreachable` in plain words.
* **Acceptance.** Unit tests of the scheduler (fair share, single flight, back-off); with a background import running, J-02 numbers
  are unchanged (≤ 10 % worse).

## P1-04 — Prepare what the person will probably tap (app + server) — Size S
* **Status 2026-10-22: partly done.** The Top result of a search (or the first catalogue song) is prepared while the person reads (`SearchResultsView`); on the emulator a prepared Top result is audible 1.0-1.9 s after the tap. Not done: the first 3 songs of an opened album/playlist/imported playlist, the next 2 songs of the queue, cancelling stale prepares, dropping prepares first under back-off (P1-03).
* **Why.** N3: ≤ 1 s for likely taps.
* **Context.** `POST /api/prepare` exists (resolve + park 20 min). The app prepares the top search result and the first song of an
  open catalogue album (ADR-058/060).
* **Do.** Server: prepare = resolve only (URL cache, no download). App: prepare the **Top result** 400 ms after typing stops, the
  first 3 songs of an opened album/playlist/imported playlist, and the **next 2 songs in the queue**. Cancel stale prepares.
  Prepares use the interactive pool but are dropped first under back-off.
* **Acceptance.** Tapping a prepared song: audible ≤ 1 s p50 (12 runs); a 10-song catalogue album played through: each change ≤ 1 s.

## P1-05 — Imported songs use the video id they came with (server) — Size S
* **Status 2026-10-22: done on the server, walked in the app.** `playlists.py` lists YouTube / YouTube Music playlists through `ytmusicapi` (149 songs in 1.5 s on the server, 2.0 s through the public address; real title, artists, album, length and video id; yt-dlp stays as the fallback and for the "private" wording). Songs that are YouTube's own audio upload carry `official` and are used directly (no search; `jobs.py` already did this). Songs YouTube no longer has keep name and album and are searched by them. Walked in the app on the emulator with the 10-song In Rainbows album: link pasted → list on screen in 1.1 s → Import → playlist open and playable 1.3 s later → all 10 in the library about 2.5 min later (9 s a song, two at a time), 0 missing, server log shows no title search (the job label "searching" there is the stream look-up). Not done: Spotify entries keep the video id they were matched to (the resolutions memory already does this per song); the 57th-song-right-after-start check on the 189-song list.
* **Why.** B6: '00s Hip Hop songs were searched again (7–35 s each) although the playlist gave each video id.
* **Context.** `imports.py`, `playlists.py` (YTM playlists via yt-dlp `--flat-playlist`; replace with `ytmusicapi.get_playlist`,
  which returned 189 songs in 2.1–3.2 s with video ids).
* **Do.** Use the given video id directly for YouTube-sourced entries; for Spotify-sourced entries resolve through P1-01 with a strict
  match (normalised artist + title, duration ± 3 s) and keep the chosen video id with the entry.
* **Acceptance.** Importing '00s Hip Hop: zero search calls in the server log; tapping song 57 right after the import starts is
  audible ≤ 3 s.

## P1-06 — Measure what a person experiences (app + tools) — Size S
* **Why.** `../07` §3: the media session said PLAYING while nothing played; numbers were best cases.
* **Do.** Request ids and the app's log ring buffer as in `../24` §1 (`X-Request-Id`, `X-Device-Id`, structured server logs).
  App: a perf span `play.audible` = tap → player position first > 200 ms (log `[perf] play.audible ms=… source=file|stream|download id=…`).
  `tools/journeys/play_timing.py`: drives the emulator (search → type → tap Top result) for N songs from a pool file, reads the
  spans from logcat, and prints p50/p95/max with the setup header. Keep a per-server "used songs" list so songs are never reused.
* **Acceptance.** The script reproduces today's ~38 s on build 40 (sanity check) and is used for every number in P1.

## P1-07 — Search: a Top result and one list (app) — Size M
* **Status 2026-10-22: done and walked on the emulator.** `lib/domain/search_rank.dart` (pure ranking), `lib/features/search/search_assembly.dart`, `search_results.dart`; Top result, then songs (library and catalogue mixed, same look), artists, albums; no header about the library. Real answers recorded from Deezer (`tools/record_deezer_fixtures.py`, `test/fixtures/deezer/search.json`): the intended song is the Top result for 18 of 20 queries; the two misses are known (Deezer's eight results hold no Beach House song; an Arabic title cannot be matched with Latin letters yet, docs/19). Also fixed on the way: the server treated "(The Avener Rework)" as noise, so the plain song tapped played the library's rework (`version_signature`); covers rank below the artist's own versions; compilation repeats are folded. Not done: keystroke-to-results timing (≤ 300 ms) not measured on a device.
* **Why.** E5: the typed song came 6th, after albums and covers; a technical header splits owned/not owned.
* **Context.** `lib/features/search/search_screen.dart`, `lib/features/search/catalogue_section.dart` (header "Not in your library
  yet" + "It is added to your library first…"), Deezer client `lib/data/catalogue/deezer_client.dart`, local FTS search.
* **Do.** Merge library and catalogue results into one ranked list: **Top result** (best normalised artist+title match, owned or
  not), then Songs, Artists, Albums, Playlists (Spotify's order). Rank songs by match quality, then owned first, then Deezer rank.
  Owned and catalogue songs look identical (no section header, no explanation text). Rows of songs that cannot play right now
  (offline, not downloaded) are greyed (P1-09).
* **Acceptance.** For 20 real queries ("Daft Punk Instant Crush", "radiohead weird fishes", "fairuz kifak inta", "opeth windowpane",
  "nas ny state of mind", …) the intended song is the Top result in ≥ 19; keystroke → results ≤ 300 ms (catalogue) on TYPICAL.

## P1-08 — The player never gets stuck (app) — Size M
* **Status 2026-10-22: code done, tests green, walked on the emulator (`../evidence/2026-10-22-walk-e1-e2-e6.md`).** `PlaybackEngine`: a load that never ends is given up after 12 s (`loadTimeout`) with one plain notice and the same song waits to be played again; a newer "play this" ends a stuck load at once (latest wins, `_newGeneration`). Not done: the 3 s limit for local files, and the play/pause-control and frame-cost part (UI lane).
* **Why.** E1 (stuck after a network loss; play/pause replaced by a 1-px sliver; other taps ignored), E7 (spinner = full-frame cost).
* **Evidence (deep read, `../26` H40).** One first-in-first-out chain `_run` holds every command; a load waiting on a vanished network
  has no own time limit, so later taps wait behind it; the retry-once / stop-after-3 logic in `_onBackendError` is right but is not
  reached in time.
* **Context.** `lib/playback/playback_engine.dart`: every command runs through a serialiser `_run(...)`; `_loadCurrent` /
  `_loadCurrentBody` (line ~734) load sources; a comment near line 405 mentions a load timeout; `persistEvery` 15 s. The UI derives
  "loading" from the engine. While stuck, logcat showed `[perf] frames n≈310 jank≈40 % work p50≈17 ms` every few seconds.
* **Do.** Loads get a hard timeout (10 s for streams, 3 s for local files) and are **cancellable**: a newer play/skip/seek command
  cancels the in-flight load (latest wins) instead of queueing behind it. A failed load ends in a normal paused state with one
  plain message and a working play button (retry). The play/pause control is always present (spinner inside the button, never
  replacing it). Find the widget that animates expensively while loading (look for blur/shader/opacity animations behind the
  spinner) and make loading cost ≤ 2 ms/frame.
* **Acceptance.** J-07 and charter "Break the player" (`../07` §9) on profiles A and B: never stuck > 10 s, play/pause always
  works; while loading, frame work p50 ≤ 4 ms.

## P1-09 — Offline: no skipping, greyed rows, recovers by itself (app) — Size M
* **Status 2026-10-22: engine part done, tests green, walked on the emulator (same evidence file).** Offline a song that is not downloaded is not tried and nothing is skipped; Next goes to the next downloaded song or says so; the next song is preloaded only when it can play; a waiting song starts by itself when the network returns (`networkChanged`). Not done: greyed rows, covers offline (P1-10).
* **Why.** E2 (offline taps start a silent skip cascade every ~3 s through the playlist). The connection strip stays: the owner
  asked for it on 2026-10-17 (`../01` E10 corrected).
* **Context.** Banner: `lib/features/common/connection_banner.dart` ("You're offline. Downloaded music still plays."); connectivity in
  `lib/app/connection.dart`; downloads state in `lib/data/repos/downloads_repository.dart`.
* **Do.** A single `playability(songRef)` = downloaded | reachable-server | catalogue-online | unavailable, used by every row and by the
  queue builder. Unavailable rows are greyed and show "Not downloaded" on tap (once per session). The engine **never auto-advances
  on an availability error**; it pauses with a message. When the network returns, the current item is retried automatically.
  Keep the slim connection strip (owner's request); add a short message only when an action failed for lack of connection.
* **Acceptance.** J-06 and J-07 pass on profiles A and B; airplane-toggle charter: no duplicate plays, no skipping.

## P1-10 — Covers everywhere, offline too (app + server) — Size M
* **Status 2026-10-22: covers part done, walked on the emulator.** Two fetch sizes only (`lib/core/cover_sizes.dart`: small 256, large 768) instead of seven, the other size stands in when only one is cached (widgets and lock-screen art); a background fetch (`CoverPrefetcher`, `lib/app/cover_wiring.dart`) keeps the covers of playlists, downloaded and liked songs, the newest albums and the biggest artists in the disk cache (at start, after every sync, when the network returns; mobile data: small only, at most 120). Evidence: `../evidence/2026-10-22-e3-before-letters-offline.png` (new playlist a gradient, mini-player "IR") and `../evidence/2026-10-22-e3-after-covers-offline.png` (same state after the fix, offline, app restarted). Not done: catalogue/imported songs that have no library cover (`imageUrl` from the match), the media notification via a `content://` URI (B35), retry of failed image loads when the network returns (the stand-in handles the offline case), and the 30-imported-songs check.
* **Why.** E3 + owner: "the song icon disappeared and got replaced by a letter in offline mode; we need to download the icons as well".
* **Context.** `lib/app/providers.dart` `CoverArtResolver` builds `coverArtUrl(coverArtId, size: size)` **per widget size**, so each
  size is a separate cache entry (offline: album page had the cover, mini-player showed a letter for the same album, `a14`).
  `lib/features/common/cover_art.dart` (`CoverArt`, initials fallback, `_CatalogueCover`, `CoverMosaic`). Media notification art:
  `lib/playback/media_art.dart` passes a private `file://` path the system UI cannot read (old bug B35). Imported/catalogue songs
  have no cover URL (giant "D" for "Dilemma", `a12`); the imported playlist header shows "0H" (`a11`).
* **Do.** One canonical cover per album/song at one size (e.g. 600 px) in a bounded disk cache; widgets downscale with `cacheWidth`.
  Downloading a song/album/playlist also stores its covers next to the audio (never evicted while downloaded). Catalogue and imported
  songs carry a cover URL (Deezer album cover via the match; YouTube Music thumbnail as fallback); imported playlists use the
  source playlist's thumbnail, else a mosaic of the first 4 covers. Media notification art via a `content://` URI (FileProvider)
  or a scaled bitmap. Failed image loads are retried when the network returns (no sticky letter tiles).
* **Acceptance.** J-06 on profiles A/B: covers in rows, mini-player, full player, notification, lock screen; online: no letter tile
  for any song that has a cover in Deezer or YouTube (check 30 imported songs).

## P1-11 — Resume after any kill; correct lock-screen position (app) — Size S
* **Status 2026-10-22: queue part done, tests green, walked on the emulator (same evidence file).** The saved queue also stores artist/title/album of songs streamed from the catalogue (`named`) and `restore()` finds them in the library by that (`findByName`); those the library does not have are dropped and the rest of the queue comes back. Not done: the 5 s save while playing, the lock-screen position check, and songs the server did not keep (a song played once is not kept: the song-ref design in P2 re-prepares it by its catalogue id instead of dropping it).
* **Why.** E6 (force-stop while playing a catalogue song lost the song and queue; a normal kill while paused restored correctly),
  E20 (media session position stayed at its start value).
* **Context.** `PlaybackEngine` persists every 15 s (`persistEvery`) and has `restore()`. **Root cause found (`../26` H39):**
  `_restoreSaved` looks the saved ids up in the phone's `Tracks` table (`_lookupTracks`), which does not know a song fetched from
  YouTube until the next library sync, so the restored queue is empty.
* **Do.** Persist queue + index + position on every track change, pause, seek, and every 5 s while playing, including catalogue items
  (store what is needed to play them again: video id/song ref, title, artist, cover). Restore shows the mini-player paused at the
  saved second. Verify the lock-screen seek bar on the emulator and one real phone; push position updates if it drifts.
* **Acceptance.** J-08 (force-stop at 2:31 → reopen paused at 2:31 ± 2 s) for an owned song and a catalogue song; reboot case too.

## P1-12 — Accessibility, insets, big text, device-profile tests, small UX fixes (app) — Size L (split if needed)
* **Status 2026-10-22: steps 1 and 4 done, 6 partly, the rest open.** `showEncoreSheet` (`lib/features/common/encore_sheet.dart`) is used by all 14 bottom sheets (safe area, keyboard lift, drag handle, 90 % height). `test/support/device_profile.dart` + `test/features/device_profiles_test.dart` open every main screen, the player with its Speed / Sleep timer / Queue sheets, the track menu and the create menu under three profiles (3 buttons 48 dp, gesture 24 dp, small phone 360x640 with 2x text) and assert no overflow and nothing tappable under the system bar (lists scrolled to their end first); the check itself is tested against a plain bottom sheet (`test/support/device_profile_test.dart`). A new server is called "My music server", not "Navidrome". Open: step 2 (labels on every custom tappable, sign-in field labels, TalkBack walk), 3 (grow-with-text audit beyond the screens above), 5 (notification permission when first needed), the rest of 6 (codec chips, "Only your music" wording), 7 (back from an imported playlist), RTL profile, walking the profiles on the emulator with 3-button navigation.
* **Why.** E11–E13, E15, E16, E18; owner: "sometimes there are buttons under the 3 navigation buttons … we should be testing all cases".
* **Context.** Only 5 of 14 `showModalBottomSheet` calls pass `useSafeArea: true` (`playlist_actions.dart`, `track_menu.dart`,
  `jam/add_songs_sheet.dart`, `queue_sheet.dart`, `sleep_timer_sheet.dart`); target SDK 36 forces edge-to-edge. UI Automator showed
  the sign-in fields without labels and album Play/Download/rows as non-clickable. Notification permission is requested at start-up
  (`lib/app/notifications.dart` line ~134). Account card says "Navidrome"; player chips "OPUS 136"/"MP3 269".
* **Do.**
  1. One helper `showEncoreSheet()` (safe area + keyboard insets + max height) used by every sheet; same for dialogs and full-screen
     forms with bottom buttons.
  2. `Semantics(button: true, label: …)` (or proper `InkWell`/buttons) on every tappable custom widget; text fields with real labels.
  3. Text that can grow (tiles, chips, rows) has `maxLines` + ellipsis and containers that grow with the text scale.
  4. The device-profile test helper of `../07` §4 (3-button 48 dp / gesture 24 dp bottom inset, text scale 1.0/1.3/2.0, 360×640,
     RTL) + Flutter's `meetsGuideline(androidTapTargetGuideline | labeledTapTargetGuideline | textContrastGuideline)` on every screen,
     and the "no tappable rect inside the bottom inset" assertion.
  5. Ask for notification permission the first time a notification would be shown (or from Settings).
  6. Jargon: the account card shows the server's name; codec/bitrate only in a "Song info" sheet; rewrite "Only your music / Show
     everything".
  7. Back from an imported playlist returns to where the person came from.
* **Acceptance.** J-11 on profile C passes; widget tests run every screen under every profile in CI; TalkBack can sign in, search,
  play a song and add it to a playlist (screen-reader walk recorded as notes).

## P1-13 — One volume, consistent loudness (app + server) — Size M
* **Status 2026-10-22: app part done, server part open.** Levelling now only turns loud songs down by default (the loudness enhancer is off: `ReplayGainSettings.allowBoost`, setting "Quiet places" is the only boost; the preamp slider is gone), so the phone's volume buttons are the one volume; engine tests prove the player volume is exactly 1 with levelling off through play/next/previous/seek/pause/failure and that the levelled volume comes back after a sleep-timer fade. Open: measuring loudness on the server when a file is kept (ReplayGain tags), YouTube-reported loudness for streams, the 20-song loudness measurement, and asking the owner which slider he meant.
* **Why.** Owner's volume report (old F12 "not in sync with my phone's slider, sometimes works"; repeated 2026-10-21), `../13` §1
  findings V1–V5, H11.
* **Context.** `lib/playback/replay_gain.dart` (`planReplayGain`: cuts through the player's internal volume, boosts up to +9 dB through
  a loudness enhancer, untagged = 0 dB); default `ReplayGainMode.track` in `settings_controller.dart`; `playback_engine.dart` sets
  `_backend.setVolume(_gainVolume)` and fades it for the sleep timer. On CT 104, 2 of 182 random songs had tags (+0.9 and +11.1 dB);
  YouTube-fetched files have none. The Jam `SetVolume` (`packages/encore_session`) is applied by no phone.
* **Do.**
  1. Server: when a file is kept, measure loudness (EBU R128 with `ffmpeg -af ebur128` or `rsgain`) and write ReplayGain track/album
     tags; a one-off admin job measures the existing library (paced, CPU-light, resumable).
  2. Catalogue streams: use YouTube's reported loudness for the stream when the extractor provides it (check the player response
     `loudnessDb`); else assume the measured median of kept files.
  3. App: levelling targets −14 LUFS; **cut only** by default (no boost); setting Off / Normal (default) / Quiet environment (target
     −11 LUFS with a limiter, the only mode that boosts).
  4. The internal player volume is used only for levelling and fades, and is always restored after a fade, a seek, a skip, a pause
     and an error (tests for each path).
  5. Ask the owner which slider he meant (old F12) and reproduce it on his phone during the next beta.
* **Acceptance.** Playing 20 songs mixed from kept files, tagged files and YouTube streams: measured output loudness (record from the
  emulator's audio or analyse decoded PCM) within ±2 LU of each other with levelling on; with levelling off, the player's internal
  volume is exactly 1.0 for every song; the phone's volume buttons are the only thing that changes loudness.

## P1-14 — Stop the sync storm (app + server) — Size S
* **Status 2026-10-22: code done, unit-tested; the data-usage measurement is open.** App: a moved scan status no longer makes a full library pass due sooner than `SyncOptions.libraryPassGap` (1 hour; 6 hours on mobile data) after the last one; a pull to refresh ignores the gap; the cheap probe stops asking for a pass inside the gap. The task said 30 minutes: for the owner's 6,700 songs a pass is 8.6 MB, so 30 minutes would be 17 MB an hour against the 10 MB target; an hour gives about 9 MB. Server: the per-song `startScan` is now a fallback after `WATCHER_WAIT_S` (6 s) when Navidrome's own watcher has not listed the new file. Not done: the Android data-usage measurement during a 50-song import on another account; P2's change cursors make all of this disappear.
* **Why.** `../26` H38: an open phone re-downloads the whole library listing (8.6 MB, 18 requests for the owner's 6,731 songs) every time
  anyone's import keeps a song, with no minimum gap.
* **Do.** App: at most one full library pass per 30 minutes unless the person pulls to refresh; on metered networks at most one per 6 hours;
  between passes the cheap probe keeps playlists fresh. Server (fetch/keeper): stop calling `startScan` per song; rely on Navidrome's
  watcher. P2's `library/changes` replaces all of this.
* **Acceptance.** During a 50-song import on another account, an open phone's traffic (Android data usage) stays under 10 MB per hour.
