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
* **Order.** Needs: none.
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
* **Order.** Needs: none.
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
* **Order.** Needs: none.
* **Why.** A3, E4, ADR-R5. Today a tap adds the song to the library (ADR-066) and Play on "Lateralus" (2 of 13 owned) plays 2 songs.
* **Do.** Playing a catalogue song never creates a like/library entry; "Recently played" records it (history). The queue builder takes
  every song of an album/playlist as refs and plays each by its playability (P1-09): kept file, else stream, with the next 2 prepared
  (P1-04). Saving (like / add to playlist / save album / import), downloading, or playing the same song on **2 different days** (server
  setting `keep_after_play_days`, default 2) triggers a keep job (D-3). A song is kept once for everybody.
* **Acceptance.** J-03; the Library does not change after playing 10 catalogue songs; liking one shows it in Liked Songs at once and
  the server keeps it in the background; a song played yesterday and today is kept (test with a controllable clock); two people
  keeping the same song produce one file.

## P2-04 — Imports in seconds (server + app) — Size M
* **Order.** Needs: none.
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
* **Order.** Needs: none.
* **Why.** E8, E9.
* **Do.** Stop cancels the person's queued work at once and running work for them alone within 2 s; shared work continues (`../04`
  §10). Progress on `import.progress` events. Notification texts by end state: "All 189 songs are ready offline" / "Import stopped:
  all 189 songs are in your playlist; 5 are kept on your server" / "3 songs could not be found".
* **Acceptance.** After Stop, the server log shows no new work for that import; texts match the state; Home, the card and the playlist
  show the same numbers.

## P2-06 — Spotify beyond 100 songs, and Liked Songs (app) — Size M
* **Order.** Needs: none.
* **Why.** B8, E17; Spotify's developer route needs Premium (Feb 2026).
* **Do.** Polish the data-export path (plain steps with screenshots: where to request it, what arrives, pick the zip; all playlists +
  Liked Songs). Run experiment X-4 (sign in to Spotify's own page in a WebView on the phone, read playlists and Liked Songs); if it
  passes and the terms risk is acceptable to the owner, ship it as "Sign in to Spotify on this phone". Never on the server.
* **Acceptance.** The owner's real export imports every playlist with correct counts; X-4 report in the PR.

## P2-07 — Remove the homelab portal code and the second import screen (app) — Size S
* **Order.** Needs: none.
* **Why.** A4.
* **Context.** `lib/data/requests/{portal_client,portal_discovery,request_service}.dart`, `lib/data/repos/request_repository.dart`,
  `lib/features/requests/{download_service_sheet,request_providers}.dart`, portal parts of `lib/app/alerts_wiring.dart` and
  `lib/data/auth/credential_store.dart`; two import screens: `lib/features/import/import_screen.dart` (keep) and
  `lib/features/settings/import_screen.dart` (remove, route to the first).
* **Acceptance.** `git grep -i portal -- app/lib` empty; no screen mentions port 8700; tests green; the drift migration drops the
  `Requests` table safely.

## P2-08 — Playback state and resume anywhere (server + app) — Size M
* **Order.** Needs: none.
* **Why.** C11; owner: pause at x:xx, continue at x:xx on the same or another device, including YouTube songs; a web/PC client later.
* **Do.** Server `playback` module (one row per person, `rev` for optimistic concurrency). App: `PUT /playback` on pause, seek, track
  change, and every 15 s while playing; on cold start and on resume-to-foreground, `GET /playback` and show the mini-player paused at
  that point if it is newer than the local state.
* **Acceptance.** J-09 first half (B shows S paused at 1:10; Play → audible at 1:10 ± 1 s), for an owned and a catalogue song; works
  away from home through the public address (X-7).

## P2-09 — One device at a time (server + app) — Size M
* **Order.** Needs: P2-08 [i]. Why: the active-device lease is taken against the person's playback state, which is the one row per person that P2-08 builds..
* **Why.** Owner: "the user cannot be listening on his phone and a different device at the same time, same as Spotify".
* **Do.** `POST /playback/claim` when a device starts playing; the server pushes `device.takeover` on `/encore/live` to the previous
  holder, which pauses and shows "Playing on <device name>" with "Play here". Devices have names (set at sign-in, editable). A device
  whose websocket is down learns it on the next state check (≤ 15 s) and pauses.
* **Acceptance.** J-09 second half (A plays → B pauses ≤ 2 s); two different people never affect each other.

## P2-10 — Invite-first sign-in and "Bring your music" (app) — Size M
* **Order.** Needs: P2-19 [d].
* **Paper first:** pages A1–A6 of `../15` §3, drawn in the tokens with the look of `../16` §3; the owner's OK on the drawings before code.
* **Why.** E14, US-04, US-05.
* **Context.** `lib/features/onboarding/connect_screen.dart`, `join_screen.dart`, `lib/domain/invite_link.dart`; **no QR scanner exists in the app today** (checked 2026-10-23: no scanner
  library; the phone's own camera opens a join link). How a person finds the server without an address, and the first screen's order, are decided in `../11` ADR-R40 and built in **P2-19**; this task is the
  rest of the first run (A2 to A6).
* **Do.** First screen: "Scan an invite" and "I have an invite link" (paste/open); "Other ways to connect" reveals today's manual form.
  After joining: the "Bring your music" screen (US-05) once per person, then Home; Home shows an "Import your playlists" card until
  the first import or dismissal; "Start with something" shelf when the library is empty.
* **Acceptance.** J-01 on profile A; a person who skips import still has a non-empty Home.

## P2-11 — Migrate today's installs without losing anything (server) — Size L
* **Order.** Needs: none.
* **Proposed: close (2026-11-03), the owner decides.** The installs this migrates (CT 104 and the legacy services) were destroyed at his word on 2026-11-03 and nobody else has one; the migration endpoint stays built. Reopen only if a real old install turns up.
* **Why.** `../18` §3–4: the owner's server (CT 104) and phones hold real likes, playlists, plays and kept files.
* **Do.** The migration of `../18` §4 (backup → people → files to refs, duplicates merged → likes/playlists/plays via the gateway header or
  the phones → running imports → count check → switch, old services stopped not deleted). Rehearse on a copy of CT 104's data on the dev
  VM first; run on CT 104 only with the owner's go.
* **Acceptance.** Per-person counts identical before/after on the rehearsal; Year in Music shows the same numbers before and after.

## P2-12 — The catalogue module: search, matching, duplicates (server + app) — Size L
* **Order.** Needs: none.
* **Why.** `../19`: one identity engine for search, imports, keeper, Jam and recommendations; the phone stops calling Deezer/LRCLIB.
* **Do.** `textnorm` with the Arabic and featured-artist rules, the matching table of `../19` §3, the two-phase search endpoint and ranking
  of §4 (the app merges phone results + fast + full without jumping), aliases from MusicBrainz, automatic ref merges and the duplicates
  report (§6), the ≥ 200-pair labelled test set (§7).
* **Also (ADR-R38, clients are thin):** the server, not the phone, calls Deezer. That covers search, artist and album pages, the 30-second previews (served as a short-lived signed
  address, so a browser can play them too) and the new-release check that today runs in the phone's background (`app/background_sync.dart`). When it lands, delete
  `app/lib/data/catalogue/deezer_client.dart`'s use in the app and lower the outside-host ratchet (`../30` §5).
* **Acceptance.** Precision ≥ 99 % / recall ≥ 90 % on the labelled set; search p50 ≤ 400 ms (fast phase) on TYPICAL; "fairouz",
  "fairuz" and "فيروز" find the same artist. The app no longer calls Deezer: the outside-host ratchet drops by one.
* **Found 2026-10-23 (owner, `history/reviews-2026-10-31.md#audit` F12 and F13), to be fixed here:** (1) **new releases**: Deezer lags (the EP KAIZEN of L'morphine was on YouTube Music and Spotify the day it came out and absent from Deezer, whose newest album for him was ten days older),
  so the catalogue takes artist pages, albums and search from **YouTube Music as well as Deezer**, merged by the matching rules, and a release that YouTube Music has appears on the artist's page the same day; (2) **names**: "lmorphine chrono",
  "l'morphine chrono" and "L'morphine - CHRONO" all find CHRONO first (Deezer finds none of them): an apostrophe, a space, a missing letter or the other order of artist and title never hides a song; (3) **several artists**: a song has an **ordered list** of artists
  (MESSI MARADONA: Aymane Haqqi, L'morphine), the app shows all of them on rows, in the player, on the lock screen and on the song's page, and the song is on **every** credited artist's page; the app never shows a different artist on a row than the page header
  it came from without saying why. Acceptance for these three: the pairs listed in `history/reviews-2026-10-31.md#audit` are in the labelled set and pass; a walk on the emulator shows KAIZEN on L'morphine's page and "Aymane Haqqi, L'morphine" under MESSI MARADONA.

## P2-13 — Downloads: formats, manifest, stale-file replacement (server + app) — Size M
* **Order.** Needs: none.
* **Why.** `../23` §1–2, H19, H20, H37.
* **Do.** Format policy per situation; download quality setting; `downloads/prepare` and `downloads/manifest`; temp-file + checksum +
  rename; resume with Range; replace outdated downloads on Wi-Fi; smart downloads for playlists and Liked Songs; the `download` priority.
* **Acceptance.** A downloaded song upgraded or fixed on the server is replaced on the phone on the next Wi-Fi without ever being
  unplayable; a download killed at 50 % resumes; Liked Songs stays in sync offline.

## P2-14 — Lyrics on the server (server + app) — Size S
* **Order.** Needs: none.
* **The owner's call (D-51).** Because the friend's phone still calls LRCLIB until this lands, the owner may pull the small lyrics part forward into M1; that changes only this line and the milestone table.
* **Why.** `../23` §3.
* **Do.** Server-side lookup (tags, `.lrc`, LRCLIB), cache per ref, delivered with the song and with downloads; right-to-left rendering;
  per-person timing offset. The phone stops calling LRCLIB (`app/lib/data/api/lrclib_client.dart`, ADR-R38) and the outside-host ratchet drops by one (`../30` §5).
  Also the answer to F9 (a song LRCLIB does not have): more sources are added on the server, once, for every client.
* **Acceptance.** 30 songs from the test pool: lyrics shown when LRCLIB has them, offline for downloaded ones, Arabic lyrics right-to-left. The app no longer calls LRCLIB: the outside-host ratchet drops by one.

## P2-15 — Notifications without push (server + app) — Size S
* **Order.** Needs: P2-12 [i]. Why: the ADR-R38 table sends new-release alerts through P2-12 first and then the server-side check that this task builds..
* **Why.** `../23` §4. **Amended 2026-10-24 (ADR-R44): the in-app bell is the channel; phone notifications are opt-in (at most two categories, off by default) and the permission is asked only then; remove today's permission prompt after sign-in and the default new-release alerts (`background_sync` > `AlertsService`).**
* **Do.** `GET notifications?since=`; live events → local notifications while running; periodic background check (≤ every 6 h);
  channels and the daily new-release digest; honest "not online" for Jam invites.
* **Acceptance.** Each channel can be switched off; no more than one background wake-up per 6 h (battery check in `dumpsys`). New-release checks run on the server, so the phone makes no catalogue call of its own for them: the outside-host ratchet drops by one.
* **Slice A (server), designed 2026-10-25 from the drawing S-24 "What's new" (`design/directions/screens-player-together-and-more.html`).** The drawing has four kinds of news and no others: a **release** from an artist the person plays, a **Jam invitation**, an **invitation of theirs that was used** (owners), an **import that finished**. The server keeps them per person (table `notification`: id, person, kind, title, body, route, `dedupe`, created, read) and says them in words, so any client (a browser, a TV) shows the same list (ADR-R42).
  * `GET /notifications?since=<id>&limit=50` answers `{items (newest first), unread, cursor}`; with `since` only what is newer. `POST /notifications/read {upTo: id}` marks everything up to an id read (idempotent; `upTo` omitted means all). Each item is `{id, kind, title, body, route, createdAt, read}`; `route` is where a tap goes in the app (`/settings/import`) or `null`.
  * The live channel says `notification.new {unread}` to the person's phones, so the bell's dot changes within a second; the list is fetched when the page opens and on return to the app (nothing polls).
  * `dedupe` (unique per person) makes a retry or a restart harmless: an import finishes once however often the server settles it. At most 200 per person and 90 days are kept; older ones go when a new one arrives.
  * **Produced now** (server events): `invite_used` for the owner who made the invitation ("Sara joined", "With the invitation you made."), `import_done` for the person whose import finished in the background ("Your import is ready", "Road trip: 47 of 48 songs", route `/settings/import`; an import that was finished before the person looked away is not announced: they watched it). **Later, by their own services** (the table accepts the kinds already): `release` (the recommendations/catalogue work, P4), `jam` (the Jam hub, when the invited person is not online).
  * **Not here:** the phone's own notification (ADR-R44: off by default, asked only when the person switches it on), the bell and the page in the app (slice B).

## P2-16 — A self-describing, self-healing library (server) — Size M
* **Order.** Needs: none.
* **Why.** `../26` §2: a lost database or a dead disk must not lose people's music where it can be recovered.
* **Do.** Write `ENCORE_REF`, the YouTube video id, ISRC/MBID, cover and loudness into every kept file; rebuild refs from tags when the
  database is missing; after a restore, re-fetch missing YouTube-sourced files by video id (paced, background) and list the files that
  cannot be recovered (the Host's own rips) in the admin.
* **Acceptance.** On the dev VM: delete `encore.db` → restart → likes and playlists come back from the backup and every kept file is
  re-linked; delete 20 kept files → they are re-fetched within the pace and play again with likes intact.

## P2-17 — "Follow the original" for imported playlists (server + app) — Size M
* **Order.** Needs: none.
* **Why.** `../26` §3: imports go stale; following public and editorial playlists for free is a reason to leave Spotify.
* **Do.** Per imported playlist a switch (default on for public playlists); daily re-read in the night window; add new songs; remove songs
  removed at the source unless the person changed them here (then ask); a quiet line "3 new songs from the original"; works for YouTube
  Music and Spotify links (Spotify ≤ 100 songs, said plainly).
* **Acceptance.** A real public playlist that changes during a week stays in step; a person's own additions are never removed.

## P2-18 — A changed or expired login is a normal event (app + server) — Size M
* **Order.** Needs: P3-03 [d].
* **Why.** `../01` E23, H30, `../21` §4 (device tokens): today a stale password breaks sync silently, produces a cryptic row message, and the only fix deletes the person's downloads.
* **Do.** One place that sees every authentication failure (any service, the live channel, streaming) and turns it into one state "Sign in again": a quiet banner on Home and a full-screen prompt on the next action, never a per-row sentence. **Sign in again** keeps the library, downloads and queue (only the credential is replaced; if the person signs in as someone else, then the old data is removed after asking). Sign out is separate and says plainly what it removes. With device tokens (P3-03) a password change on the server revokes devices explicitly and the app shows who revoked it.
* **Acceptance.** Rotate a test account's password on the server: within one app launch the person sees "Sign in again", signs in with the new password, and everything (downloads, queue, likes) is still there; journey J-21 (add to `../14` section 3).

## P2-19 — Find your server: a key, the server's own addresses, a first screen without an IP address (server + app + installer) — Size L (four slices)
* **Order.** Needs: P2-20 [d].
* **Why.** Owner, 2026-10-23: a non-technical person cannot be asked for an IP address; Plex and Jellyfin find the server by themselves; what about several Wi-Fi networks and several servers? Decision and research: `../11` **ADR-R40** (read it first). Also closes **S2** (the app sends credentials to unverified addresses, `history/reviews-2026-10-31.md#audit`), serves US-04 and `../15` A1, and the owner's own step "Your server > Add an address".
* **Context (checked 2026-10-23).** `app/lib/data/sync/endpoint_resolver.dart` (races candidates; probe = Subsonic `ping` with credentials, `app/lib/app/session.dart`, first candidate used before any probe), `features/onboarding/{connect,join}_screen.dart` (one or two typed addresses; the join stores one), `data/auth/server_setup_service.dart` (a server row = local autoincrement id), `features/settings/server_addresses.dart`; server `api.py` `/info`, `server/encore_server/deploy/{install.sh,encore}` (the terminal QR encodes the bare address); no QR scanner library in the app; Android target SDK 36. A legacy server answers an unauthenticated `ping` with an error envelope (`evidence`: ADR-R40).
* **Slice A (M): the key and the checked probe.** Server: an Ed25519 key pair made once at first start and kept in the database (so a restored backup is the same server); `serverId` = short base32 hash of the public key; `GET /encore/api/v1/info?challenge=<nonce>` returns `serverId`, `publicKey` and a signature over nonce and id; `GET /encore/api/v1/server` (signed in) returns `{serverId, name, addresses: [{kind, url}]}`; the installer records the home address, `encore funnel on` the away address. App: servers keyed by `serverId` (a new column; an older row learns the key once); the probe is the public `/info` with a fresh challenge, **no login, no token**, verified against the pinned id; **credentials and tokens go only to an address that has proved itself**, and the first candidate is not used before it has; the list of addresses comes from `/server` and is refreshed after each sign-in and when an address stops answering; join and pairing links carry the id and the addresses; legacy servers are recognised by the unauthenticated `ping` error envelope. `cryptography` (Python, Dart) added and listed in `../25`. **Done when:** S2 cannot be reproduced (a test server that answers with another key never sees a credential), and the owner never has to type "Add an address".
* **Slice B (S-M): zero typing for the owner's first phone and the first screen.** `encore pair [user]` and the installer's last screen print a one-time pairing link and QR (single use, 10 minutes, never logged); the join screen handles it (signs in without a password); the first screen shows "a link or a QR code", then "Servers on this Wi-Fi" (empty until slice C), then "Other ways to connect" (the typed form, Host words); plain words everywhere (`../15` A1); the phone's own camera opens the link in the app, and a scanner library is added **only** if that fails on a real phone. Paper first for the screen (`../15`), the owner's OK on the drawing (this is also P2-10's first screen).
* **Slice C (M): "Servers on this Wi-Fi".** `avahi` on the host advertises `_encore._tcp` (TXT: `id`, `name`, `api`; no URLs), on by default, `encore discovery on|off`, a switch in the wizard and admin; the app browses on the first screen and on network changes while its server is unreachable, behind an interface (a web client later has none), shows servers by name, marks the ones it has; **choose between `FLAG_SHOW_PICKER` and the `ACCESS_LOCAL_NETWORK` permission on a real phone before moving to target SDK 37**; measure first whether the emulator sees LAN multicast (expected: no). Proof: `avahi-browse -rt _encore._tcp` from a second VM on the bridge; then the owner's phone on his Wi-Fi (one line in his five days).
* **Slice D (S-M): Quick Connect.** A phone that found a server shows a 6-digit code; any signed-in device of the Host approves it; the new device gets its own token. How a housemate joins without anybody dictating a password.
* **Don't.** Read the Wi-Fi name. Send a credential, token or signed address to an address that has not proved its key. Advertise addresses, usernames or anything secret in the TXT record. Add a directory or relay service run by the project. Log a pairing code. Move to target SDK 37 before slice C.
* **Acceptance.** A: with a second server on another address that copies the first one's id, the app never sends it a header, a token or a query credential; moving the server to a new address (or a new computer by restore) is found again with nothing typed. B: on a fresh emulator install, opening the pairing link signs the owner in with **no typing** (`evidence/b03`); the first screen contains no "address" or "IP". C: a second VM sees the service with `id` and `name`; on the owner's phone the server appears by name within 5 s of opening the app on his Wi-Fi, and not on mobile data. D: a second emulator joins by code approved from the first.
* **Tests.** As listed in ADR-R40 (server: key, challenge, `/server`, `encore pair`; app with fakes: impostor, first candidate, race, row migration, refresh, legacy; golden pictures and the walk for the first screen; avahi from a second VM; the real phone).
* **Depends on / Size.** A needs nothing; B needs A (ids in the link) and, **for the pairing half, P2-20** (a pairing link gives a device token and no password, and today the app cannot work on a token alone); B's other half (the first screen without "address") needs the Welcome drawing and not P2-20; C needs A and the owner's phone; D needs C and P2-20. A and B come **before P1-06 and P1-04** because they touch the owner's own install and fix S2; the friend (an https link) does not wait for them.

## P2-20 — In Encore mode the app holds only the device token: no `/rest` calls, no music-server login on the phone (app + server) — Size L
* **Order.** Needs: P2-12 [d], P2-14 [d], P3-03 [i], P2-15 [p]. Why: P2-15: the release check is the last outside call the app makes, so the end state "the app calls no outside host" can only be asserted after it; P3-03's own text: the gateway forwards requests to Navidrome with a trusted header, which is what lets the app stop sending the music server's login in `/rest` URLs..
* **Why.** Found 2026-10-24 while building the owner's pairing code (P2-19 slice B). A pairing link, Quick Connect (AC-8), a TV signed in by a code (S-08) and a browser client all give a device a **device token and no password**. Today the app in Encore mode still signs every `/rest` call with the music-server login (`u`, `t` = md5 of password and salt, `s`), and the gateway forwards those calls to Navidrome, which checks them itself; a phone that holds only a device token cannot make them. This is also the clean end state of ADR-R38 (clients talk only to their own server) and ADR-R42 (the server decides, the client draws).
* **Rejected, on purpose:** (1) *reset the person's music-server password at pairing and give it to the phone*: it silently changes the owner's own password (which he also uses for the admin site and his other phones) and leaves every other phone with a stale password, which is the lockout of `evidence/b05` again; (2) *the gateway re-signs token requests with the administrator's login*: it lends admin rights to a device token and needs a fragile allowlist of paths.
* **Do.** In Encore mode (`serverCapabilities.encore`), every call the app makes goes to `/encore/api/v1` with `Authorization: Bearer <device token>` (the live channel already does), and what is still asked of the music server is served by the Encore server itself:

  | Music-server call today (`evidence/b03`'s old-build log and `app/lib` read 2026-10-24) | Why the app makes it | What replaces it |
  |------|------|------|
  | `ping`, `getOpenSubsonicExtensions` | the reachability probe (already replaced by `GET /info?challenge`, slice A) and a feature list | `GET /info` `features` (already there) |
  | `getScanStatus`, `startScan`, `isAdministrator` | the sync scheduler's quiet probe; the owner's "update now"; the role | the library feed's own cursor (`/library/changes`); `POST /library/rescan` (owner); `GET /me` role (already there) |
  | `getArtists`, `getAlbumList2`, `getAlbum`, `getSong`, `getPlaylists`, `getPlaylist`, `getStarred2`, `search3`, `getSimilarSongs2`, `getTopSongs`, `getLyricsBySongId` | the browse index and the old sync path (a plain server) | the Encore feeds (`/library/changes`, `/library/files`) for the phone's copy; search, artist pages, lyrics and similar songs on the server (P2-12, P2-14); a plain (non-Encore) music server keeps its own path and its own login, unchanged |
  | `star`/`unstar`, `setRating`, `createPlaylist`, `updatePlaylist`, `deletePlaylist`, `scrobble` | likes, playlists, plays | already `PUT /likes`, `/playlists`, `POST /plays` in Encore mode (check each is used and the `/rest` one is not) |
  | `stream` of a kept file, `download` | playing and downloading a song the server keeps | `GET /refs/{id}/stream-url` (signed, already there) for every song, kept or not; the signed address is the credential, not a query token |
  | `getCoverArt` | covers | a signed cover address from the server (the cover finder already stores `cover.jpg`); needed anyway for the web client (ADR-R38 consequence) |

* **Server slice 1, built 2026-10-24:** `/encore/stream/{ref}` serves the server's **kept file** through the music server as the Encore server's own account (Range, `maxBitRate`/`format` as validated unsigned extras; a missing file falls back to YouTube) and `GET /covers/{id}/url` + `/encore/cover/{id}` serve covers by signed address. Tests `tests/test_kept_files.py`. Not yet: the app using them, the browse/search/scrobble rows of the table, dropping the password from the phone.
* **Slice 2 (app + a little server), designed 2026-10-25: songs and covers by signed address.** Only the `stream`, `download` and `getCoverArt` rows of the table; browse, search and the password come later.
  * **Songs.** In Encore mode the app asks `GET /refs/{id}/stream-url` for **every** song, kept or not (the server picks its own file, then YouTube: `/encore/stream` already does). The signed address is **remembered per ref until ten minutes before it expires** (`expiresAt` is in the answer), so a tap on a song already asked for, the next song of a queue and a retry cost no round trip; a queue preloads the next address as it preloads the next song. The quality extras (`maxBitRate`, `format`) are appended to the address by the app, unsigned, as the server validates them. A download uses the same address (`download_providers.dart`), at "Original" quality.
  * **Covers.** A screen shows 30 covers at once, so one signed address per cover would be 30 round trips. Instead the server gives **one cover pass per device**: `GET /covers/pass` answers `{p, e, sig}`, a signature over the scope `covers` (not over one picture) valid for **7 days**, and `/encore/cover/{id}` accepts either that or the per-picture signature that exists today. The app keeps the pass in memory, renews it a day before it ends or on a `401` from a cover, and builds `/encore/cover/{id}?size=&p=&e=&sig=` by itself, so `CoverArtResolver.resolve` stays synchronous and the image cache keys do not change (`(server, id, size)`, ADR-017). Until the first pass arrives (a second after sign-in) covers show their letters, as offline does. A cover is a public picture of a record, not a secret: a pass lets its holder fetch pictures, nothing else.
  * **Not changed.** A plain (non-Encore) music server keeps `/rest` and its login. The catalogue's own picture addresses (`https://...`) stay what they are.
  * **Proof.** A fake server of the Encore kind: playing a kept song, showing a list of covers and downloading one song record **no** `/rest/stream`, `/rest/download` or `/rest/getCoverArt` request and no `u`/`t`/`s` parameter; the address is asked once for two plays of the same song; a pass that expired is renewed once and the cover loads; the quality extras reach the server's stream (server test with a fake music server). `N1` (tap to sound) does not get worse: measured on the emulator against the dev VM, 10 taps, before and after (`evidence/b07`).
* **Acceptance.** An emulator signed in by a device token alone (the sign-in screen's password is used once, to get the token, then **forgotten**: no password in secure storage in Encore mode) browses, searches, plays a kept song and a catalogue song, downloads, likes, edits a playlist, and the impostor server of `evidence/b03` records **no** `/rest` request and no `u`/`t`/`s` query parameter at all from this phone. Changing the person's music-server password (AC-25) no longer breaks the phone. Server: every route the app needs accepts the device token; tests per row of the table. The `architecture_test` ratchet gains: no `OpenSubsonicClient` use inside Encore mode. After this the outside-host ratchet's baseline in the app's `architecture_test` is empty: the app calls no Deezer, no LRCLIB and no other outside host.
* **Depends on / Size.** Needs P2-12 (catalogue and search on the server) and P2-14 (lyrics) for the last rows; the rest can start now. **Blocks the pairing half of P2-19 slice B**, P2-19 slice D (Quick Connect), S-08 (TV sign-in) and any web client. Parked meanwhile: `park/p2-19b-pairing-server` (the server half of the pairing code, unused).

## P2-21: Menus and selection, the RC2 part (app), Size M
* **Order.** Needs: none.
* **Why.** AUDIT F31 and F32: no way to change a playlist's picture or description, and no way to select several songs and add them to a playlist.
* **Do.** (1) A playlist's description and picture, set and shown. (2) Multi-select on song rows: pick several, then add to a playlist, add to the queue, download or remove. Draw both before building (D-43: a page is drawn when it is new and about to be built).
* **Acceptance.** Written when it is drawn.

## P2-22 — A download shows where it is: the server stage, the phone stage, and why it waits (server + app) — Size M
* **Order.** Needs: P1-17 [d].
* **Why.** Round 2, found by the owner on 2026-11-03 (`AUDIT` R2-F2): he pressed Download on two playlists (217 and 4 songs) and could not tell
  what was happening: no notification, only "N of M" on the phone and "Waiting for a connection". D-29 puts "download a song, album or playlist"
  in RC1 and forbids silent failures. Measured the same evening on the test server: the *server* needed about **46 minutes** to fetch a 217-song
  playlist from YouTube (paced, about 5 songs a minute, 223 look-ups, no refusal) before the phone could download any of it, and the app showed none
  of that stage.
* **What was wrong (two causes).** (a) The downloader's progress notification exists (`background_downloader_transport.dart`: "Downloading
  music", "Downloads finished") but Android 13 and newer drops it: ADR-R44 never asks for the notification permission (`POST_NOTIFICATIONS` is
  not granted). (b) The server stage is invisible: the app's only reasons for waiting are about the phone's network (`downloadsWaitProvider`).
* **Do.** (1) Server: publish keep progress per pinned target on the live channel: counts of queued, fetching, ready and failed, and the YouTube
  rest state (`resumesInSec`), so "the server is pausing for YouTube until 21:40" reads as that and not as "stuck". (2) App: show both stages and
  the real reason for any wait on the places a person looks (the Library rows, the playlist or album header, Settings > Downloads & storage);
  **drawn first**. (3) Notifications: ask for the permission once, in context, at the first Download, and only to show progress. Decided by the owner on 2026-11-03 (D-52: yes, once, at the first Download): it switches on no news alert, and ADR-R44 is amended by that one exception. (4) A song that failed says
  which one and why, with Retry.
* **Part (1), the request, is built (5 Nov 2026; branch `task/P2-22-keep-progress`): built, not walked, and nothing in the app calls it yet.** `POST keep/progress` (`server/encore_server/encore_server/keep_progress.py`, `keeper/failures.py`; contract in `17` "Keep progress"; `server/encore_server/tests/test_keep_progress.py`): one request answers for every pinned playlist, release and the liked songs; every song is in exactly one bucket (ready, keeping, queued, failed); a failure is named with its reason, written for the Host or for a member, and says whether Retry can work; YouTube's rest and `resumesInSec` come with it; a group the person cannot see is left out like one that does not exist. Three server changes it needed, each with a test: the server now **stores the songs of a saved release** (`saved_album_ref`, migration 0009: it never did, so it could not say how many were ready), `Scheduler.states_of` (one bulk read instead of a call per song), and a failed keep of a song somebody still has **is no longer forgotten by the scheduler's weekly cleanup** (it is the reason the phone shows). **Part (1b), the push, is built too (5 Nov 2026, `PUT keep/watch` and the live event `keep.progress`, `keep_watch.py`, `tests/test_keep_watch.py`): built, not walked.** **The Retry call is built too** (`POST keep/retry`, `tests/test_keep_retry.py`). **Still to build, each its own pull request:** (2) and (4) in the app (two numbers, the lines, the bar's two tones, Retry via `POST keep/retry`). **This item stays unmarked until all of them are built.**
* **Drawn (5 Nov 2026), waiting for the advisor's look before any code:** `design/` S-16 "the two stages" and "waiting: the phone's reason wins (offline)", S-17 "downloading" (class C only: the browser has no offline downloads, P6-02). One vocabulary for the lines under a title, **both numbers always, the phone's first** (the acceptance asks for how many songs the server has ready and how many are on the phone, and the stages overlap, PB-35): "12 of 217 on this phone · 40 ready on your server", "3 of 9 on this phone · your server is resting until 21:40", "Getting it on your server · 40 of 217 ready" (nothing on the phone yet), "Waiting its turn on your server", "Downloading to this phone · 30 of 40" (the server has it all); a two-tone bar (filled = on the phone, lighter = ready on the server); three reasons for a wait, **one cause for the whole screen**, the strip's own test ("waiting for Wi-Fi", "waiting for a connection", "waiting for your server"; the phone's reason replaces the server's half, which is stale offline); failures named with Retry ("3 songs did not come", PB-37). Part (1) publishes only what these lines need: queued, fetching, ready and failed per pinned target, and `resumesInSec`; nothing else is drawn. **The notification covers only the phone stage; the server stage is shown in the app (the advisor's decision: no foreground service while nothing transfers on the phone). Part (2) must also make sure "Downloads finished" is never shown while any pin still has songs not on the phone (`33` PB-38): suppress or reword it.** Build order: part (1) server, then parts (2) and (4) app, as separate pull requests; this item is marked built only after all of them.
* **Don't.** Poll one request per song. Change the default of the news alerts.
* **Acceptance.** Importing and downloading a 200-song playlist on a fresh install: at every moment a person can say how many songs the server
  has ready, how many are on the phone and why anything waits; the notification appears after the one permission prompt; in airplane mode the
  app says "Waiting for a connection" and claims nothing else. Measured, with the setup written in the PR.
* **Depends on.** The live channel (built). (P2-13, the downloads manifest, is related and not needed for this task.) **Size.** M. **Triage (D-29):** RC1.

## P2-23 — One API contract, checked in CI (ADR-R41 T5) — Size M
* **Order.** Needs: none.
* **Why.** ADR-R41 T5 and `history/reviews-2026-10-31.md#audit` P2-01 name it as open, and it is a task nowhere: "the API is the product", and every later client (a tablet layout, a TV, an iPhone, a web player) must be built against a checked schema, not against the Android app's habits (`tasks/P6-later.md`).
* **Do.** The server writes `openapi.json` into the repository and a server test fails when the file is out of date; `schemathesis` runs against a test instance in the server job (5xx and schema conformance only, to start); the Dart client's models are checked against the same file; a version field and a rule for breaking changes in `17`.
* **Acceptance.** Changing a route without regenerating the file fails CI; a contract test finds a deliberately broken response; `17` §3's table is generated from the same file.
* **Size.** M.

## P2-24 — The app and the server tell each other their versions (app + server) — Size S
* **Order.** Needs: P3-27 [i]. Why: audit B-29: `17` promises that the app refuses a server whose `apiVersion` major it does not know and says "Update Encore"; `31` CN-27 is Designed with no code and no test. The app reads `apiVersion` only to see that it is not empty. A stranger's server updates by itself while a friend's phone stays on an old app; with a release channel (P3-27) the skew is rarer, never impossible.
* **Do.** The server answers `minAppVersion` and `apiVersion` (already in `info`); the app compares both ways and shows one sentence with the one button that helps ("Update Encore" / "Ask the owner of <server> to update the server"); a contract test pins the sentence; `31` CN-27 becomes Built.
* **Acceptance.** An app older than `minAppVersion` and a server newer than the app both show the sentence instead of failing in a screen; the tests exist.
* **Size.** S.

## P2-25 — Songs in any alphabet are told apart and found (server) — Size M
* **Order.** Needs: none. Why: audit B-37, proven on 6 Nov 2026 (and end to end on a real music server): every Arabic, Cyrillic, Korean or Japanese name normalises to the empty string, so different songs become one, a Host's own non-Latin library collapses, and an exact Arabic match from YouTube Music is rejected. a standing rule: design for other countries; "design for other countries" is a standing rule.
* **Do.** (1) One Unicode-aware `textnorm`: NFKC, case-fold, strip only combining marks (so `é` is `e`), keep the letters and digits of every script, and the Arabic folds `19` section 2 already specifies (alef forms to ا, ى to ي, ة to ه, tatweel and harakat removed; the Persian and Urdu ی and ک variants). (2) No normalised key may be empty: when folding leaves nothing, keep the case-folded original. (3) Every comparison of text goes through it: `refs.norm_key`, `navidrome.pick_song`, `keeper/placement.find_existing`, `scoring`, `lean.title_matches` and `artist_matches`, `imports/readers._fold`. (4) A repair for databases already built: recompute every `norm_key`; refs that were merged cannot be told apart from the ref alone, so detach the library-linked files of refs whose old key was empty and let the next library pass attach each file to its own ref. (5) Tests with **native-script** titles (not transliterations): the labelled pairs of `19` section 7 in Arabic, Japanese, Russian and Korean; two Fairuz songs 1.5 s apart stay two songs; an exact Arabic match from YouTube Music is accepted; a Host library of Arabic and Russian files links one ref per file against a real music server (the integration suite). (6) `07` section 8's test pool gets native-script rows.
* **Acceptance.** `python docs/evidence/scripts/audit_probes.py scripts` and `python -X utf8 docs/evidence/scripts/audit_stack.py check library` (seven tagged files in Arabic, Cyrillic and Latin in a real music server's folder) both print PASS (seven songs, not three); the walk P0-13 has a native-script row (type an Arabic title, tap, hear it).
* **Size.** M.

## P2-26 — A hiccup is never taken for "YouTube has no copy" (server) — Size S
* **Order.** Needs: none. Why: audit B-38, proven: a timeout of the YouTube Music search becomes `unavailable`, which the keeper treats as final (no Retry offered), an import records as "not found" for good, and a tap reports as "removed".
* **Do.** In `LeanResolver.resolve_ranked` raise a transient code (`timeout` for a timeout, `download_failed` for the rest) instead of `unavailable`; keep `unavailable` for "YouTube answered and has no copy". Check every consumer that turns an error into a verdict (`keeper._download`, `imports.match`, `api._stream_error`) and the phone's wording ("YouTube did not answer just now" is not "removed"). One test per consumer with a searcher that times out.
* **Acceptance.** `python docs/evidence/scripts/audit_probes.py transient` and `python -X utf8 docs/evidence/scripts/audit_stack.py check transient` print PASS (a Retry after the five-minute pause, not a GiveUp); a song YouTube really does not have still ends the same way as before.
* **Size.** S.
