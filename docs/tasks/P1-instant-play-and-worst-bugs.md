# P1 — Instant play, and stop the worst bugs

Goal: a song you don't own is audible in ~2–3 s (≤ 10 s worst) and the player never gets stuck; offline and covers work.
This phase changes today's architecture as little as possible: the YouTube code is written as a **reusable package** that P3
moves into the single server unchanged.

Paths below are in the **old layout** (app files at the repository root); after P0-04 prefix app paths with `app/` and server paths with `server/legacy/`.

Three lanes can run in parallel: **Server** (P1-01 → P1-02 → P1-03, P1-05), **Player** (P1-08, P1-09, P1-11), **UI** (P1-07,
P1-10, P1-12). P1-04 and P1-06 connect them.

---

## P1-01 — The lean resolver (server) — Size M
* **Order.** Needs: none.
* **Addendum 2026-10-22:** the in-process extractor now tries yt-dlp's `visionos` client first for a visitor: 1.3 s instead of 3.7 s, and its address opens at once. Fallback to yt-dlp's own choice, no second look-up for a block or a gone video, a breaker rests it for an hour after three failures in a row; `YT_FAST_CLIENTS` (empty switches it off). `../09` 7.3.
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
* **Order.** Needs: none.
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
* **Order.** Needs: none.
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
* **Order.** Needs: none.
* **Re-read 2026-10-24 (paper, before code):** (1) **the next songs of the queue are already prepared** by the player: it preloads the next source, which makes the server look the song up while the current one plays (`PlaybackEngine._syncWindowTail`, `GET /encore/stream/{ref}`), so "the next 2 of the queue" is not missing code; only a third song ahead is not. (2) In **Encore mode `prepare` only resolves a row** (`EncoreInstantBackend.prepare`): the look-up at YouTube waits for the tap, which is the cost left on the first tap of an opened album. (3) A real prepare is **two YouTube operations per song** (the match search and the stream address, kept 50 minutes in `StreamProxy._info`), and the home address was refused after about 35 look-ups in a few minutes (2026-10-22). So the missing part is a **server-side `POST /refs/prepare {ids ≤ 3}` that goes through the background pacer** (`sources/youtube/pace.py`, a slot every ~12 s), is skipped while YouTube is resting, dedupes in-flight ids, caps at 20 per hour per server, and **only when a person has opened a list and stayed 400 ms**; the app calls it for the first 3 songs of an opened album, playlist or imported playlist, and does nothing to cancel (a stale prepare costs one paced slot). **Not built**: it spends the owner's YouTube budget, so it needs the measured N2 first (`play_timing.py` on the dev VM, ≤ 10 look-ups per run) to show it is worth it.
* **Why.** N3: ≤ 1 s for likely taps.
* **Context.** `POST /api/prepare` exists (resolve + park 20 min). The app prepares the top search result and the first song of an
  open catalogue album (ADR-058/060).
* **Do.** Server: prepare = resolve only (URL cache, no download). App: prepare the **Top result** 400 ms after typing stops, the
  first 3 songs of an opened album/playlist/imported playlist, and the **next 2 songs in the queue**. Cancel stale prepares.
  Prepares use the interactive pool but are dropped first under back-off.
* **Acceptance.** Tapping a prepared song: audible ≤ 1 s p50 (12 runs); a 10-song catalogue album played through: each change ≤ 1 s.

## P1-05 — Imported songs use the video id they came with (server) — Size S
* **Order.** Needs: none.
* **Why.** B6: '00s Hip Hop songs were searched again (7–35 s each) although the playlist gave each video id.
* **Context.** `imports.py`, `playlists.py` (YTM playlists via yt-dlp `--flat-playlist`; replace with `ytmusicapi.get_playlist`,
  which returned 189 songs in 2.1–3.2 s with video ids).
* **Do.** Use the given video id directly for YouTube-sourced entries; for Spotify-sourced entries resolve through P1-01 with a strict
  match (normalised artist + title, duration ± 3 s) and keep the chosen video id with the entry.
* **Acceptance.** Importing '00s Hip Hop: zero search calls in the server log; tapping song 57 right after the import starts is
  audible ≤ 3 s.

## P1-06 — Measure what a person experiences (app + tools) — Size S
* **Order.** Needs: none.
* **Why.** `../07` §3: the media session said PLAYING while nothing played; numbers were best cases.
* **Do.** Request ids and the app's log ring buffer as in `../24` §1 (`X-Request-Id`, `X-Device-Id`, structured server logs).
  App: a perf span `play.audible` = tap → player position first > 200 ms (log `[perf] play.audible ms=… source=file|stream|download id=…`).
  `tools/journeys/play_timing.py`: drives the emulator (search → type → tap Top result) for N songs from a pool file, reads the
  spans from logcat, and prints p50/p95/max with the setup header. Keep a per-server "used songs" list so songs are never reused.
* **Acceptance.** The script reproduces today's ~38 s on build 40 (sanity check) and is used for every number in P1.

## P1-07 — Search: a Top result and one list (app) — Size M
* **Order.** Needs: none.
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
* **Order.** Needs: none.
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
* **Order.** Needs: none.
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
* **Order.** Needs: none.
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
* **Order.** Needs: none.
* **Why.** E6 (force-stop while playing a catalogue song lost the song and queue; a normal kill while paused restored correctly),
  E20 (media session position stayed at its start value).
* **Context.** `PlaybackEngine` persists every 15 s (`persistEvery`) and has `restore()`. **Root cause found (`../26` H39):**
  `_restoreSaved` looks the saved ids up in the phone's `Tracks` table (`_lookupTracks`), which does not know a song fetched from
  YouTube until the next library sync, so the restored queue is empty.
* **Do.** Persist queue + index + position on every track change, pause, seek, and every 5 s while playing, including catalogue items
  (store what is needed to play them again: video id/song ref, title, artist, cover). Restore shows the mini-player paused at the
  saved second. Verify the lock-screen seek bar on the emulator and one real phone; push position updates if it drifts.
* **Acceptance.** J-08 (force-stop at 2:31 → reopen paused at 2:31 ± 2 s) for an owned song and a catalogue song; reboot case too.
* **6 Nov 2026, the walk found two defects in what was built (audit B-94), fixed in the pull request that marks this line:** `seek()` never saved the position (a seek to 2:28, then a kill 2 s later, brought the song back at 4:01, reproduced twice on the emulator), and the position was written every 15 s (the text above says 5 s and J-08 says ± 2 s). Now the position is a small record of its own (the current song's id and the position), written every 2 s while playing, at once on every seek and with every queue write; the queue snapshot is written only when the queue changes, so a long queue is not rewritten every 2 s. Five tests, each failing without its part of the fix.

## P1-12 — Accessibility, insets, big text, device-profile tests, small UX fixes (app) — Size L (split if needed)
* **Order.** Needs: P1-20 [d].
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
* **Order.** Needs: none.
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
* **Order.** Needs: none.
* **Why.** `../26` H38: an open phone re-downloads the whole library listing (8.6 MB, 18 requests for the owner's 6,731 songs) every time
  anyone's import keeps a song, with no minimum gap.
* **Do.** App: at most one full library pass per 30 minutes unless the person pulls to refresh; on metered networks at most one per 6 hours;
  between passes the cheap probe keeps playlists fresh. Server (fetch/keeper): stop calling `startScan` per song; rely on Navidrome's
  watcher. P2's `library/changes` replaces all of this.
* **Acceptance.** During a 50-song import on another account, an open phone's traffic (Android data usage) stays under 10 MB per hour.

## P1-16 — Search says when you are offline (draw first) — Size S
* **Order.** Needs: P1-15 [d], P1-17 [d]. Why: it uses the lasting offline state (`serverAwayProvider`) and the same words and look that P1-15 built.
* **Why.** P1-15 built the drawn offline look for Home, the Library and the song rows. **Search's own page has no offline state drawn** (S-11 the start page and S-12 the results; `docs/design/04` item 7), so nothing was built there beyond what the shared song row already does (a song result that is not downloaded is grey and says "Not downloaded"). A person who opens Search with no connection should see at once that it cannot look anything up, and what still works.
* **Do.** **Drawn 5 Nov 2026 (C and X; T stays parked), waiting for the advisor's look before any code:** the start page offline (the field's hint says "Search your music", the genre tiles dim, no line is added: the lasting-sign rules), the results offline (the phone's library; what is not on the phone is grey with "Not downloaded"; one quiet last line says what more cannot be done in the words of its cause: "More results need a connection." / "More results need your server."), no results offline ("Nothing in your music matches ...", "Connect to search more." / "Your server isn't answering, so only your music can be searched."; no "Closest", no "Ask for it") and the genre page offline ("Not available right now", "Browsing needs a connection." / "Browsing needs your server."). The words say what cannot be DONE, not what cannot be reached: they stay true before and after the catalogue moves to the server (D-51). Then build as drawn, with the one predicate (`serverAwayProvider`, `onPhoneProvider`) and the strip's two-way split (`phoneHasInternetProvider`). **"More results need your server." and "Browsing needs your server." are only true if, while the server is silent, the app really stops showing catalogue results and genre pages: today Deezer is called directly and may still answer (the ADR-R38 debt, D-51 moves it to the server), so the build gates those calls on `serverAwayProvider`, not on the network.**
* **Acceptance.** Drawn (C and X), looked at by the advisor, then built; airplane mode on: Search says what it can and cannot do, searches what is on the phone, and the words agree with the strip's on the same screen; airplane mode off: it goes by itself.
* **Size.** S.

## P1-15 — The app says when it is offline — Size S
* **Order.** Needs: none.
* **Why.** Round 2 (`history/README.md#audit` R2-F5, 2026-11-03): with airplane mode on, Home and Library show no sign of being offline; the only hint is the status bar's airplane icon, so a person cannot tell "offline" from "the server is down". US-14: everything that cannot work offline says so. D-29: no misleading states.
* **Do.** An offline state in the connection banner (`app/lib/app/connection.dart` already has the machinery for "Waiting for your server"): one calm line, no permanent banner (P1-09's rule), distinguishing "this phone has no network" from "your server does not answer". Drawn first.
* **Acceptance.** Airplane mode on: the strip appears after the 4 s grace of CN-1 (a blink is not news; the 3 s first written here was wrong) on Home and Library and says what still works (downloads), **and after the strip has gone the screens still show what cannot be played: grey, with "Not downloaded" in words (S-10, S-14, S-17, S-18), until the connection is back**; airplane mode off: all of it goes by itself; a phone whose server is stopped shows the other wording, "Can't reach your server.", **when Android found internet on its network**, and "You're offline..." when it found none (4G with no data, a sign-in page): CN-4b, D-45 amended; a tap on a song that is not downloaded says the same two things. **Built 5 Nov 2026 for Home, Library and the song rows (built, not walked); Search offline is not drawn and waits for its drawing.** The lasting look was already drawn (D-45 amended: the strip says it once, the sign stays).
* **Size.** S. **Triage (D-29):** RC1.

## P1-17 — One "can I reach my server" state in the app, replacing eleven (app) — Size L
* **Order.** Needs: none. Why: audit B-17: the app decides "can I reach the server" in eleven places that can disagree (and P1-15 added three), and "which kind of server" in three; every new feature that greys a row or refuses a tap (P1-16 Search offline, P2-22 parts 2 and 4) adds readers to a family of bugs. Build the one state first.
* **Do.** The target design is written in the audit (B-17): three raw facts (the link type, whether Android found internet on it, what the address probes found) and ONE derived state `serverReachabilityProvider` = `unknown | ok | offline | serverAway | wrongServer` that holds for as long as the outage does; the strip (D-45: said once, for 5 s) is a presenter over it, not a second definition; the strip, the player, the grey rows, the settings pages, People, imports and downloads all read it; one `serverKindProvider` (Encore / plain / detecting). **Delete, do not wrap,** the old notions (`serverReachableProvider`, the public `isKnownUnreachable`, `phoneOnlineProvider`, `canReachServerNow`, `connectivityProvider`, `connectionProblemProvider`, `serverAwayProvider`, `session.encoreMode`, `instantAvailableProvider`, `requestPortalOfferedProvider`).
* **Tests.** The state table `31` (CN-1, CN-4b, CN-11, CN-14) keeps its tests, re-pointed; one new test per state; a test that fails when two readers disagree about the same moment.
* **Acceptance.** `grep` finds none of the deleted names; an emulator walk of offline, server away and another server answering shows the same words in the strip, the rows, the player and Settings; nothing is greyed during the first 4 s grace. **Audit B-58 (proven, 6 Nov 2026):** the state's change to "reachable" also delivers the outbox at once (and the outbox schedules its own retry at the earliest `nextAttemptAtMs`): an edit made during a server-only outage reaches the server within 60 s of its answering (today it took 549 s, the next scheduled sync).
* **Size.** L.

## P1-18 — Check on a real phone: calls, headphones, a full phone and a long pause (quality) — Size M
* **Order.** Needs: none. Why: audit B-31: `33` lists as Open, never verified on a phone, a call or another app taking the sound (PB-F15), headphones or Bluetooth disconnecting (PB-F16), the phone's disk full (PB-F17), a damaged download (PB-F18), the 6-hour song address expiring after a long pause (PB-F9) and the server's reason never reaching the notice (PB-F10, PB-F11).
* **Do.** Walk each row on a real phone with the walk record of `07` section 12 (Expected from the row, Got, Verdict, evidence). For PB-F16 the expected result is certain: pause when the output goes away, never play from the speaker. For PB-F9 find out whether the one quiet retry asks for a new address; if not, fix it. Where a row fails, fix it at its source or open an item with the evidence.
* **Acceptance.** The seven rows have a verdict with evidence; the failing ones are fixed or have an item; `33` shows Built or Designed for each, not "not verified".
* **Size.** M.

## P1-19 — Every request carries an id, so a failure can be followed from the phone to the server — Size S
* **Order.** Needs: none. Why: audit B-32: P1-06 is marked built but its first half is missing; the app has the log ring buffer and the Diagnostics screen but sends no request id, and the server logs none (`24` section 1). `30` says a bug report without request ids is incomplete, which cannot be followed on a stranger's server.
* **Do.** `X-Request-Id` (a ULID) and `X-Device-Id` on every request from the app (`encore_api.dart`); the server reads them, puts them in its structured log lines (`time, level, module, request_id, device, person_id, event, ms, error_code`) and returns the id in the error body; never a title, password, token or signed address in a log.
* **Acceptance.** A song that fails to play shows the same request id in the app's Diagnostics and in `encore logs`; a test pins the log fields and that no secret reaches a line.
* **Size.** S.

## P1-20 — Every word the app shows lives in one place — Size M
* **Order.** Needs: none. Why: audit B-21 and B-23: ADR-R42 point 7 promised "every string reachable from one place"; there is no localisation layer (at least 313 words are written inline) and the same thing has several names ("Downloaded", "Downloads", "Plays offline", "On this phone"). Languages and right-to-left (P1-12) stay a translation job only if this is done before more screens are added.
* **Do.** `flutter gen-l10n` with one English file; move the strings out mechanically; settle one vocabulary for downloaded / saved things (`33` PB-35 already says "on this phone"); an architecture test that fails on a new inline user-facing string (a ratchet with a baseline, `30` section 5).
* **Acceptance.** The count of inline strings is the ratchet's baseline and only goes down; the words in the audit's list have one name each.
* **Size.** M.

## P1-21 — A finished list can be played again, and the player never says "playing" while it is silent — Size S
* **Order.** Needs: none. Why: audit B-51 (proven on an emulator, 6 Nov 2026): after a list has played to its end, pressing Play plays the last song once and then the player stays on "playing" with no sound (the media session says `PLAYING`, the mini player shows Pause, the phone's audio track is `stopped`). A daily user meets it the first time they finish an album and press Play on the lock screen; P1-08 is marked built and this is exactly the failure it is named after.
* **Do.** (1) `lib/playback/playback_engine.dart`: `_onCompleted` ignores a second end of the same load because `_completedSerial == serial` (line 1296) and `_loadSerial` changes only when a new load starts; clear the mark when the backend leaves the completed state (the root), not only on a new load. (2) `lib/features/detail/detail_screens.dart:111-112`: the Play button of a page whose list is the current source but has ended starts the list from its first song instead of toggling. (3) The snapshot may not say "playing" while the backend is idle (a check in the engine's own state-merging, with a log line if it ever happens). (4) A playback test with the fake backend: play to the end, press play, end again: paused at the start, snapshot not playing; and the same through the album page.
* **Acceptance.** On the emulator and on a real phone: a two-song list played to its end, then Play from the album page, the mini player and the lock screen in turn: each time music plays and, when it ends, the button shows Play within a second; the media session and the audio track agree. The test exists and fails without the fix.
* **Size.** S.
