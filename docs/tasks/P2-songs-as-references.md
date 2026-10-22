# P2 — Songs as references (the new library)

Goal: like, add to a playlist, import, queue and resume **any** song, owned or not; imports in seconds; one device at a time.
Read `../04` §2, §3, §8, §10 and ADR-R4, R5, R8, R9, R11, R14 first. Owner decisions D-2 (one copy per song, personal libraries)
and D-3 (keep on save, download, or plays on 2 different days) are decided.

## The API both lanes build against (v1 sketch; P2-01 turns it into an OpenAPI file in `server/api/openapi.yaml`)

Auth in P2: the existing Subsonic token (`u`,`t`,`s`) validated with Navidrome and cached 10 min; P3-03 replaces it with device tokens.

```
GET    /encore/api/info                                  → {version, name, features, youtube: ok|busy|paused-until|unreachable}
POST   /encore/api/refs/resolve        [{title, artists[], album?, durationMs?, isrc?, deezerId?, videoId?, coverUrl?}] → [{ref, …}]
GET    /encore/api/library/changes?since=<cursor>        → {refs[], likes[], playlists[], entries[], savedAlbums[], removed[], cursor}
PUT    /encore/api/likes/{ref}         DELETE /encore/api/likes/{ref}
POST   /encore/api/playlists {name}    PATCH /encore/api/playlists/{id} {name?, cover?}    DELETE /encore/api/playlists/{id}
POST   /encore/api/playlists/{id}/entries {refs[], at?}  DELETE …/entries {entryIds[]}   PUT …/order {entryIds[]}
POST   /encore/api/plays {ref, at, msPlayed, deviceId}
GET    /encore/api/playback            PUT /encore/api/playback {ref, positionMs, queue[], index, context, shuffle, repeat, playing, deviceId, rev}
POST   /encore/api/playback/claim {deviceId}   → {leaseId}   (P2-09)
POST   /encore/api/imports {url} | multipart file  → {importId, playlistId, count, unmatched}
GET    /encore/api/imports/{id}        POST /encore/api/imports/{id}/stop
GET    /encore/stream/{ref}            → audio (P1-02 stream, now addressed by ref)
WS     /encore/live                    → events: library.changed{cursor}, playback.changed, device.takeover, import.progress
```
Every write is idempotent (client-generated ids for playlists/entries) so the app's outbox can retry safely.

---

## P2-01 — Encore server skeleton, song refs and the library API (server) — Size L
* **Why.** C3, C11, ADR-R3/R4. This is the first piece of the single server (P3 moves the rest in).
* **Context.** Old services are stdlib-only Python (`server/encore-*`), each with its own Navidrome client and token check. The YouTube
  package from P1-01 is reusable as is.
* **Do.** `server/encore_server/` (Python 3.12, FastAPI/Starlette on uvicorn, SQLite WAL via a small repository layer, Alembic or
  hand-written migrations, ruff + mypy strict), modules `accounts` (token check only, for now), `catalogue` (ref creation and
  matching: ISRC, video id, normalised artist+title+duration ±3 s, reusing `textnorm.py`), `library`, `playback`, `live`
  (websocket), `imports` (P2-04), `sources/youtube` (P1 package), `keeper` (keep jobs into `/music/Encore/Artist/Album/NN - Title.opus`,
  tags with ISRC/MBID when known, Navidrome scan, attach `file_id`), the work scheduler of `../04` §10 (in SQLite). Docker image;
  run it **next to** the old services on the dev VM, on its own port, behind `/encore` in the Funnel `serve.json` and at home.
  Scanner link: songs already in the Host's library get refs on first sync (match by MBID/ISRC tags, else artist+title+duration).
* **Acceptance.** Contract tests from `openapi.yaml`; integration test with real Navidrome in Docker: like a catalogue song → keep
  job → file appears → ref gets `file_id` → like unchanged; **rename/re-tag/replace the file → like and playlist entry unchanged**;
  the scheduler tests of P1-03 still pass inside the new server; restart mid-import resumes (J-12).

## P2-02 — The app's data layer on song refs (app) — Size L
* **Why.** C3. Today local tables are keyed by Navidrome ids (`lib/data/db/tables.dart`: `Tracks`, `Playlists`, `PlaylistEntries`,
  `Pins`, `PlayHistory`…) and synced from Subsonic (`lib/data/sync/sync_engine.dart`, `outbox.dart`, `playlist_mutations.dart`).
* **Do.** Add a `SongRefs` table (ref id, metadata, optional `fileId`), point likes, playlist entries, pins (downloads), history and
  the queue at refs; keep the Navidrome-file index for streaming kept files. The library sync reads `/library/changes` (cursor) and
  listens to `library.changed` on `/encore/live`; the outbox sends the new endpoints. **Migration on first launch after the update:**
  the phone uploads its current likes and playlists (it has them locally) through `refs/resolve` + the library endpoints,
  idempotently; then switches source. One-way mirror back to Navidrome is P3-03's job.
* **Don't.** Drop the local database (people would lose downloads); rewrite screens (they read the same repositories).
* **Acceptance.** Upgrade test on a copy of a real phone database (tester on CT 104): every like and playlist entry present after
  migration, counts identical; a like made on device A appears on device B ≤ 2 s (N9).

## P2-03 — Play is not save; albums and playlists play through catalogue songs (app + server) — Size M
* **Why.** A3, E4, ADR-R5. Today a tap adds the song to the library (ADR-066) and Play on "Lateralus" (2 of 13 owned) plays 2 songs.
* **Do.** Playing a catalogue song never creates a like/library entry; "Recently played" records it (history). The queue builder takes
  every song of an album/playlist as refs and plays each by its playability (P1-09): kept file, else stream, with the next 2 prepared
  (P1-04). Saving (like / add to playlist / save album / import), downloading, or playing the same song on **2 different days** (server
  setting `keep_after_play_days`, default 2) triggers a keep job (D-3). A song is kept once for everybody.
* **Acceptance.** J-03; the Library does not change after playing 10 catalogue songs; liking one shows it in Liked Songs at once and
  the server keeps it in the background; a song played yesterday and today is kept (test with a controllable clock); two people
  keeping the same song produce one file.

## P2-04 — Imports in seconds (server + app) — Size M
* **Why.** B5, B6, E9; owner: "in Spotify it's 5 seconds".
* **Context.** Measured list reads: YTM 189 songs in 2.1–3.2 s (`ytmusicapi.get_playlist`, all with video ids); Spotify embed ≤ 100
  songs in 2.2–3.5 s (`__NEXT_DATA__` → `props.pageProps.state.data.entity.trackList`); file imports exist in the app
  (`lib/domain/import_file.dart`: Spotify data zip, Exportify CSV, YouTube Music CSV).
* **Do.** `POST /imports`: read the list, create refs in bulk (video ids attached when known), create the playlist (cover = source
  thumbnail), return; queue matching (Spotify-sourced, priority P2, visible rows first) and keeping (P3 priority; if D-3 keeps
  imports). The app shows the playlist from the response at once; counts come only from the server's import record (one source).
  Unmatched entries show "Not found" with a "Find it" search. Share-to-Encore from Spotify/YouTube Music opens the import directly.
* **Acceptance.** J-04 (189 songs in Your Library ≤ 5 s, right count, song 57 audible ≤ 3 s); a 1,000-song Spotify export file:
  playlist visible ≤ 15 s.

## P2-05 — Import stop, progress and consistent counts (server + app) — Size S
* **Why.** E8, E9.
* **Do.** Stop cancels the person's queued work at once and running work for them alone within 2 s; shared work continues (`../04`
  §10). Progress on `import.progress` events. Notification texts by end state: "All 189 songs are ready offline" / "Import stopped:
  all 189 songs are in your playlist; 5 are kept on your server" / "3 songs could not be found".
* **Acceptance.** After Stop, the server log shows no new work for that import; texts match the state; Home, the card and the playlist
  show the same numbers.

## P2-06 — Spotify beyond 100 songs, and Liked Songs (app) — Size M
* **Why.** B8, E17; Spotify's developer route needs Premium (Feb 2026).
* **Do.** Polish the data-export path (plain steps with screenshots: where to request it, what arrives, pick the zip; all playlists +
  Liked Songs). Run experiment X-4 (sign in to Spotify's own page in a WebView on the phone, read playlists and Liked Songs); if it
  passes and the terms risk is acceptable to the owner, ship it as "Sign in to Spotify on this phone". Never on the server.
* **Acceptance.** The owner's real export imports every playlist with correct counts; X-4 report in the PR.

## P2-07 — Remove the homelab portal code and the second import screen (app) — Size S
* **Why.** A4.
* **Context.** `lib/data/requests/{portal_client,portal_discovery,request_service}.dart`, `lib/data/repos/request_repository.dart`,
  `lib/features/requests/{download_service_sheet,request_providers}.dart`, portal parts of `lib/app/alerts_wiring.dart` and
  `lib/data/auth/credential_store.dart`; two import screens: `lib/features/import/import_screen.dart` (keep) and
  `lib/features/settings/import_screen.dart` (remove, route to the first).
* **Acceptance.** `git grep -i portal -- app/lib` empty; no screen mentions port 8700; tests green; the drift migration drops the
  `Requests` table safely.

## P2-08 — Playback state and resume anywhere (server + app) — Size M
* **Why.** C11; owner: pause at x:xx, continue at x:xx on the same or another device, including YouTube songs; a web/PC client later.
* **Do.** Server `playback` module (one row per person, `rev` for optimistic concurrency). App: `PUT /playback` on pause, seek, track
  change, and every 15 s while playing; on cold start and on resume-to-foreground, `GET /playback` and show the mini-player paused at
  that point if it is newer than the local state.
* **Acceptance.** J-09 first half (B shows S paused at 1:10; Play → audible at 1:10 ± 1 s), for an owned and a catalogue song; works
  away from home through the public address (X-7).

## P2-09 — One device at a time (server + app) — Size M
* **Why.** Owner: "the user cannot be listening on his phone and a different device at the same time, same as Spotify".
* **Do.** `POST /playback/claim` when a device starts playing; the server pushes `device.takeover` on `/encore/live` to the previous
  holder, which pauses and shows "Playing on <device name>" with "Play here". Devices have names (set at sign-in, editable). A device
  whose websocket is down learns it on the next state check (≤ 15 s) and pauses.
* **Acceptance.** J-09 second half (A plays → B pauses ≤ 2 s); two different people never affect each other.

## P2-10 — Invite-first sign-in and "Bring your music" (app) — Size M
* **Paper first:** pages A1–A6 of `../15` §3, drawn in the tokens with the look of `../16` §3; the owner's OK on the drawings before code.
* **Why.** E14, US-04, US-05.
* **Context.** `lib/features/onboarding/connect_screen.dart`, `join_screen.dart`, `lib/domain/invite_link.dart`; QR scanning existed
  in the Jam/invite work (ADR-098).
* **Do.** First screen: "Scan an invite" and "I have an invite link" (paste/open); "Other ways to connect" reveals today's manual form.
  After joining: the "Bring your music" screen (US-05) once per person, then Home; Home shows an "Import your playlists" card until
  the first import or dismissal; "Start with something" shelf when the library is empty.
* **Acceptance.** J-01 on profile A; a person who skips import still has a non-empty Home.

## P2-11 — Migrate today's installs without losing anything (server) — Size L
* **Why.** `../18` §3–4: the owner's server (CT 104) and phones hold real likes, playlists, plays and kept files.
* **Do.** The migration of `../18` §4 (backup → people → files to refs, duplicates merged → likes/playlists/plays via the gateway header or
  the phones → running imports → count check → switch, old services stopped not deleted). Rehearse on a copy of CT 104's data on the dev
  VM first; run on CT 104 only with the owner's go.
* **Acceptance.** Per-person counts identical before/after on the rehearsal; Year in Music shows the same numbers before and after.

## P2-12 — The catalogue module: search, matching, duplicates (server + app) — Size L
* **Why.** `../19`: one identity engine for search, imports, keeper, Jam and recommendations; the phone stops calling Deezer/LRCLIB.
* **Do.** `textnorm` with the Arabic and featured-artist rules, the matching table of `../19` §3, the two-phase search endpoint and ranking
  of §4 (the app merges phone results + fast + full without jumping), aliases from MusicBrainz, automatic ref merges and the duplicates
  report (§6), the ≥ 200-pair labelled test set (§7).
* **Acceptance.** Precision ≥ 99 % / recall ≥ 90 % on the labelled set; search p50 ≤ 400 ms (fast phase) on TYPICAL; "fairouz",
  "fairuz" and "فيروز" find the same artist.

## P2-13 — Downloads: formats, manifest, stale-file replacement (server + app) — Size M
* **Why.** `../23` §1–2, H19, H20, H37.
* **Do.** Format policy per situation; download quality setting; `downloads/prepare` and `downloads/manifest`; temp-file + checksum +
  rename; resume with Range; replace outdated downloads on Wi-Fi; smart downloads for playlists and Liked Songs; the `download` priority.
* **Acceptance.** A downloaded song upgraded or fixed on the server is replaced on the phone on the next Wi-Fi without ever being
  unplayable; a download killed at 50 % resumes; Liked Songs stays in sync offline.

## P2-14 — Lyrics on the server (server + app) — Size S
* **Why.** `../23` §3.
* **Do.** Server-side lookup (tags, `.lrc`, LRCLIB), cache per ref, delivered with the song and with downloads; right-to-left rendering;
  per-person timing offset.
* **Acceptance.** 30 songs from the test pool: lyrics shown when LRCLIB has them, offline for downloaded ones, Arabic lyrics right-to-left.

## P2-15 — Notifications without push (server + app) — Size S
* **Why.** `../23` §4.
* **Do.** `GET notifications?since=`; live events → local notifications while running; periodic background check (≤ every 6 h);
  channels and the daily new-release digest; honest "not online" for Jam invites.
* **Acceptance.** Each channel can be switched off; no more than one background wake-up per 6 h (battery check in `dumpsys`).

## P2-16 — A self-describing, self-healing library (server) — Size M
* **Why.** `../26` §2: a lost database or a dead disk must not lose people's music where it can be recovered.
* **Do.** Write `ENCORE_REF`, the YouTube video id, ISRC/MBID, cover and loudness into every kept file; rebuild refs from tags when the
  database is missing; after a restore, re-fetch missing YouTube-sourced files by video id (paced, background) and list the files that
  cannot be recovered (the Host's own rips) in the admin.
* **Acceptance.** On the dev VM: delete `encore.db` → restart → likes and playlists come back from the backup and every kept file is
  re-linked; delete 20 kept files → they are re-fetched within the pace and play again with likes intact.

## P2-17 — "Follow the original" for imported playlists (server + app) — Size M
* **Why.** `../26` §3: imports go stale; following public and editorial playlists for free is a reason to leave Spotify.
* **Do.** Per imported playlist a switch (default on for public playlists); daily re-read in the night window; add new songs; remove songs
  removed at the source unless the person changed them here (then ask); a quiet line "3 new songs from the original"; works for YouTube
  Music and Spotify links (Spotify ≤ 100 songs, said plainly).
* **Acceptance.** A real public playlist that changes during a week stays in step; a person's own additions are never removed.

## P2-18 — A changed or expired login is a normal event (app + server) — Size M
* **Why.** `../01` E23, H30, `../21` §4 (device tokens): today a stale password breaks sync silently, produces a cryptic row message, and the only fix deletes the person's downloads.
* **Do.** One place that sees every authentication failure (any service, the live channel, streaming) and turns it into one state "Sign in again": a quiet banner on Home and a full-screen prompt on the next action, never a per-row sentence. **Sign in again** keeps the library, downloads and queue (only the credential is replaced; if the person signs in as someone else, then the old data is removed after asking). Sign out is separate and says plainly what it removes. With device tokens (P3-03) a password change on the server revokes devices explicitly and the app shows who revoked it.
* **Acceptance.** Rotate a test account's password on the server: within one app launch the person sees "Sign in again", signs in with the new password, and everything (downloads, queue, likes) is still there; journey J-21 (add to `../14` section 3).

