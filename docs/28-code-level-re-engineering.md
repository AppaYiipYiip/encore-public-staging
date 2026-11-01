# 28 — Code-level re-engineering (the app and the server)

Owner, 2026-10-21: *"stay technical: how to improve the code, the program, the server side."* This page says, module by module,
what the code does today (read on 2026-10-21), what is structurally wrong, and the target shape an implementing agent should build.
It complements `04` (system design) with the inside of each part. Evidence: `26` §1 (deep read), `01`, test runs in `29`.

## 1. What is already good (keep it)

* Start-up order: database first, `runApp` immediately, network after the first frame (`lib/app/bootstrap.dart`); no network on the
  critical path.
* The phone's database (drift, indexes, tombstones, fingerprints) as the screen's single source; repositories over it.
* Typed failures (`Result`, `Failure` subclasses) instead of exceptions crossing layers; an architecture test that forbids `features/`
  imports from `data/` and ratchets catch-all handlers (no empty `catch` found in `lib/`).
* Downloads written to a temporary file, size-checked, then renamed.
* The server's Python is well tested (846 tests, all passing) and careful with secrets (`.env` mode 600, random keys, hashed invite codes).

## 2. The app

### 2.1 Playback engine (`lib/playback/playback_engine.dart`, 1,182 lines) → an explicit state machine

**Today.** Correctness is held together by many counters and flags (`_generation`, `_intent`, `_opIntent`, `_loadSerial`, `_loadAttempt`,
`_handledErrorAttempt`, `_completedSerial`, `_expectedIndex`, `_lastIndex`, `_loadingToPlay`, `_nextWaitingSince`…) plus a
first-in-first-out command chain (`_run`). It works for the cases tested (73 engine tests with a fake backend), but: a load that **hangs**
(offline) blocks every later command (H40); the failure rule "skip to the next song" fires for *availability* failures too, which makes
the offline skip cascade (E2); the saved queue keeps only ids and loses catalogue songs on restore (H39); the Jam wraps it from outside (C8).

**Target.**
* An explicit state machine: `Idle → Loading(item, op) → Ready → Playing ⇄ Paused → Ended`, plus `Failed(item, reason)` and
  `WaitingForNetwork(item, position)`. Every transition is a pure function `(state, event) → (state, effects)` with exhaustive tests
  (the "property" level of `07` §6).
* **Commands cancel, they don't queue:** every user command carries an operation id; starting a new `play`/`skip`/`seek` cancels the
  in-flight load (a `CancelToken` passed to the source resolver and to the backend's `setAudioSource`); loads have hard time limits
  (stream 10 s, file 3 s).
* **Two kinds of failure:** `ItemFailure` (this song is broken → retry once → skip, as today) and `AvailabilityFailure` (no network /
  server unreachable → `WaitingForNetwork`, never skip; resume automatically when connectivity returns).
* **Queue items are self-sufficient:** each item stores a song ref + what is needed to play it (title, artists, cover, duration, the
  file id or "stream by ref"), so restore never depends on another table (H39).
* **Sources are resolved by one `TrackSource` resolver:** downloaded file → server file (stream URL) → catalogue stream by ref; the
  engine never knows about YouTube, jobs or polling (removes `instant_controller`'s run/look-ahead machinery, 444 lines).
* The Jam becomes a **session layer** that feeds the engine commands; the engine has no Jam code path.

### 2.2 Sync (`lib/data/sync/`, 3,348 lines) → a change feed

**Today.** A full library dump (artists, albums paged, every song paged via an empty `search3`) whenever the server's scan time moves,
probed every 3 s while open (H38: 8.6 MB per pass for 6,731 songs). A "shrink guard" exists because full dumps can be partial during
scans; leases stop the background job and the open app from syncing at once.
**Target.** `GET library/changes?since=cursor` (`17` §1) for the person's library and playlists, pushed by `library.changed` on the live
channel; a separate, rare, paged **browse index** of the server's files (Albums/Artists views) refreshed by `updatedAt` cursors, not dumps.
The shrink guard and most of the probe logic can then go. The outbox keeps its role but sends operations (`17` §5).

### 2.3 Providers and features

**Today.** 170 Riverpod providers; `lib/features/providers.dart` alone declares 24 across unrelated features (playback, library reads,
lyrics, Jam); screens of 600–730 lines (`detail_screens.dart`, `import_screen.dart`, `settings_screens.dart`, `now_playing_screen.dart`,
`library_screen.dart`, `catalogue_screens.dart`); two import screens (P2-07).
**Target.** One folder per feature with `data/` (clients, repositories), `application/` (controllers/notifiers, pure logic) and
`presentation/` (screens ≤ ~300 lines, widgets); providers live with their feature; a shared `design/components/` library (cover,
song row, section header, sheet, empty state, error state) used everywhere, each with golden tests on profiles A and B (`07` §4).

### 2.4 Covers (`lib/app/providers.dart` `CoverArtResolver`, `lib/features/common/cover_art.dart`)

**Today.** A URL per requested size, so each size is a separate cache entry (offline letter tiles, E3); downloads do not store covers;
catalogue songs often have no cover URL. **Target:** one canonical image per album/ref, a disk cache keyed by ref, downscaled locally;
covers part of downloads; notification art via a content URI (P1-10).

### 2.5 Volume (`lib/playback/replay_gain.dart`) — see `13` §1 and P1-13.

### 2.6 Errors and logs

Map server error codes (`17` §2) to the app's `Failure` types one-to-one; every failure shown to a person uses the server's message or a
message from one strings file; logs become structured with request ids (`24` §1).

### 2.7 Platform settings

`minSdk` 24 → 26 (**not applied yet**: the build still uses Flutter's default, 24; see `02` Q18); target SDK 36 keeps edge-to-edge (insets everywhere, P1-12); declare the media-playback foreground-service type;
notification channels as in `23` §4; keep `androidStopForegroundOnPause` but add the "available" window and "Always ready" (H42).

## 3. The server

### 3.1 One package instead of seven programs (`04` §2)

**Today.** Seven programs with their own HTTP servers (Python standard library `http.server`, threads), their own Navidrome clients
(`navidrome.py` ×4), their own text normalisation (×2), their own config parsing and auth checks; one in Dart (the hub).
**Target layout** (`server/encore_server/`):
```
encore_server/
  app.py            ASGI app (FastAPI/Starlette), routers mounted per module, OpenAPI generated
  config.py         one typed settings object (pydantic-settings) from env/.env
  db/               SQLite access (one connection pool, WAL), migrations/NNN_*.sql, repositories per table
  clients/          navidrome.py (one), deezer.py, ytmusic.py, musicbrainz.py, lrclib.py — each with timeouts, retries, caching, rate limits
  scheduler/        work items, priorities, single flight, fair share, pacing (04 §10)
  modules/          gateway, accounts, catalogue, library, playback, live, sources/youtube, keeper, imports, people, recs, jam, quality,
                    federation, admin, problems — each: router.py, service.py (pure logic), models.py, tests/
  messages/         plain sentences per error code and language
```
* Async everywhere (httpx for outgoing calls, streaming responses for audio); CPU-heavy work (yt-dlp extraction, loudness measuring)
  in a bounded thread/process pool sized from the machine.
* Static typing (`mypy --strict`), `ruff`, and the existing unit tests moved with their code; new property tests for the matcher and the
  scheduler; contract tests from the OpenAPI file; integration tests against a real Navidrome container.

### 3.2 The YouTube source (`encore-fetch` today)

**Today.** CLI subprocess per call, watch-page scoring, download-before-play, per-person copies, a job model the app must poll.
**Target.** P1-01/P1-02: library calls in warm workers, search API, stream-first proxy with Range, one fetch session per video id,
URL cache, pacing/back-off, a runtime-updated yt-dlp (`22` §2), fault-injection flags.

### 3.3 Things to delete when their replacement lands

Per-person folder logic (`PEOPLE`, `PERSON_FOLDERS`), the upgrade map, pending likes, the instant-playlist special page, the "one answer"
capability endpoint and the app's `ServiceFinder`, the Docker-socket client, the Firefox sign-in, the portal client — each deletion is
part of the task that replaces it, never left behind as dead code.

## 4. Order (fits the roadmap)

P1 changes the engine (2.1 partly: cancellation, failure kinds, self-sufficient items), covers (2.4), volume (2.5) and the YouTube source
(3.2) inside today's structure; P2 introduces the server package (3.1) and the change feed (2.2); P3 moves the remaining services in and
deletes (3.3); the feature-folder restructuring (2.3) happens screen by screen as each screen is touched, never as a big-bang rewrite.
