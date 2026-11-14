# 18 — Data model and the migration from today's installs

Why: P2 changes where a person's library lives (`04` §3). Without a written schema and a migration path, an agent would either break
the owner's existing data or keep the old model alongside the new one forever.

## 1. The Encore server's database (SQLite, WAL, one file `/data/encore.db`)

| Table | Key columns | Notes |
|-------|-------------|-------|
| `person` | id, navidrome_user, display_name, role (`owner`, `member`), invited_by, created_at, locked, explicit_ok, federation_ok, failed_logins | Navidrome keeps the password; Encore keeps everything else |
| `device` | id, person, name, kind, token_hash, app_version, created_at, last_seen, revoked_at, available, shared, always_ready, volume | `13` §2 |
| `song_ref` | id, title, artists (json), album, album_artist, track_no, disc_no, year, duration_ms, isrc, mbid, deezer_id, ytm_video_id, cover_url, thumb_url (the source's thumbnail, served as the cover only while `cover_url` is empty: P1-26), explicit, norm_key, created_at, cover_tried_at, missing_reason, missing_at, missing_tried_at, missing_rev | `norm_key` = normalised artist+title+duration bucket (`19` §2); unique on isrc, on ytm_video_id, on deezer_id where present; `cover_tried_at` = when the server last looked for a picture, so a song nobody has one for is not asked about every hour; `missing_*` (N-13, migration 0013) = what the server remembers about a song it cannot get: reason (`not_found`, `removed`, `age_restricted`), when first learned, when last tried (the 7-day window counts from here) and the matcher revision that made the answer; cleared when a file, an upload or a description finds the song (`17`) |
| `song_file` | id, ref, navidrome_song_id, path, codec, bitrate_kbps, loudness_lufs, source (`library`, `youtube`, `quality`), preferred, added_at, meta (json: the music server's ids for the album, artist and cover, size, suffix, replay gain) | one ref may have several files; `preferred` chosen by quality; the old file kept 14 days after an upgrade. **A file (one id of the music server) belongs to one ref:** the row says which, and the library scan keeps to that ref instead of describing the file again from its tags (a file the keeper saved is the ref the import described; N-11). Nothing in the schema forbids a second ref yet: a unique index on `navidrome_song_id` waits for the repair of the rows the old scan doubled |
| `library_item` | person, kind (`like`, `saved_album`, `follow_artist`), target, at | per-person set; tombstones in `change_log` |
| `saved_album_ref` | person, album (the same id as the `saved_album` row's `target`), ref | the songs of a saved release, stored with the save (migration 0009, P2-22 part 1) so `POST keep/progress` can count how many the server has ready; removed with the save |
| `playlist` / `playlist_entry` | id, owner, name, cover, collaborative, created_at, updated_at, deleted_at, source_id (`nd:<the music server's playlist id>`, so bringing a library over is done once per source playlist) / id, playlist, position (fractional index), ref, added_by, at, deleted_at | fractional positions make concurrent moves mergeable (`17` §5) |
| `play_event` | id (made by the phone: a retried report is one play), person, ref, at, ms_played, device, context | Year in Music, history, recommendations |
| `playback_state` | person, ref, position_ms, queue (json of refs), idx, context, shuffle, repeat, playing, active_device, rev, updated_at | `13` §2, ADR-R9 |
| `work_item` / `work_item_person` | id, kind (`play`, `prepare`, `download`, `match`, `keep`, `measure`), ref, priority, state (`queued`, `running`, `done`, `failed`, `cancelled`), attempts, next_try_at, error / item, person | the scheduler of `04` §10 lives here, so a restart resumes. One active item per kind and song (single flight); `work_item_person` says who wants it, so Stop cancels only what nobody else needs (built in `server/encore_server/encore_server/scheduler.py`) |
| `import` / `import_entry` | id, person, source (`youtube`, `spotify`, `file`), url, name, playlist, state (`running`, `done`, `stopped`, `failed`), truncated, error, created_at, updated_at / import, position, ref, state (`pending`, `matched`, `not_found`), video | the counts a person sees are counted from `import_entry`, not stored |
| `change_log` | seq, person, kind (`like`, `saved_album`, `follow_artist`, `playlist`, `entry`), target, at | feeds `library/changes` cursors: a row says "this thing was touched"; the current state is read from the tables (a deleted playlist or entry keeps its row with `deleted_at`), so a phone that misses a row or asks twice still ends right |
| `file_log` | seq, ref, at | which songs' files changed, in order: the feed of `GET /library/files?since=` |
| `ref_merge` | seq, old_id (unique), into_id, at, norm_key, isrc, deezer_id, ytm_video_id, duration_ms | song refs that were merged into another (migration 0011, N-11 part B; the old id and its identifying fields are kept). `into_id` has no foreign key and always names a live ref (the repair re-points it when that ref is merged in turn). Read by `refs.canonical` (an old id still resolves), `refs.find` (a song described the way the deleted ref was finds the survivor) and the phone's merges list (`GET library/files?mergesSince=`, its own cursor `seq`). Written only by the start-up repair (`refmerge.py`) |
| `artist_picture` | artist_id (the music server's id), name, tried_at, outcome (`found`, `none`), source (`deezer`), source_url | artists the music server listed with no picture that the server looked for one for (migration 0012, N-15, ADR-R46): a `none` is not asked again for a week; a look-up the catalogue could not answer writes nothing |
| `invite` / `reset_code` | id, code_hash, role, created_by, note, created_at, expires_at, used_by, used_at, revoked_at / id, person, code_hash, created_at, expires_at, used_at | `21`; only the hash of a code is kept, the code is shown once |
| `notification` | id, person, kind (`release`, `jam`, `invite_used`, `import_done`), title, body, route, dedupe, created_at, read_at | the bell (ADR-R44): news kept per person and said in words, the same news told twice is made once |
| `idempotency_key`, `setting` | person, key, response, status, at / key, value | `idempotency_key` is created by migration 0001 and **no code uses it yet** (the `Idempotency-Key` header is a target, `17` section 1, register B-63); `setting` holds settings |
| `profile` | person, vectors (json), updated_at | **planned, no migration yet**: recommendations (`20`) |
| `friend` / `remote_server` | person, remote_handle, server, state / server, public_key, first_seen, allowed | **planned, no migration yet**: federation (`13` §4) |
| `session_code`, `problem_report` | | **planned, no migration yet** |

Migrations: numbered SQL files run at start-up inside a transaction, with a backup copy of the database taken first
(`/data/backups/encore-<version>-<time>.db`); a failed migration restores it and the server refuses to start with a plain message.

**After the migrations, at every start (`refmerge.repair`, N-11 part B).** Song refs that hold one file of the music server (the same `song_file.navidrome_song_id`) are one song that the old library scan made twice: the one whose file was attached first survives and takes everything the other had (likes, playlist entries, plays, imports, queued work, the songs of a saved release, the saved queue, the files merged key by key), then the other is deleted and a row of `ref_merge` remembers it. It runs before any thread starts, as one transaction after its own copy of the database (`/data/backups/encore-before-ref-merge-<time>.db`, kept, the path logged), changes nothing and takes no copy when there is nothing to merge, and a failure rolls back, is logged and does not stop the server. Pairs that name different source items (different video, ISRC or Deezer id) or that one playlist holds both of are **held**: never merged, written to the log at INFO on every start, and expected. It is code and not a migration because a migration cannot do it (the held pairs share a file for good, so a unique index on `song_file.navidrome_song_id` cannot exist, and the repair needs the survivor's rules).

## 2. The phone's database (drift)

Drift, schema 7 (`app/lib/data/db/tables.dart`, `app/lib/data/db/app_database.dart`), additive migrations only: every shipped version has a frozen snapshot in `app/drift_schemas/` and an upgrade test that keeps its rows (`app/test/data/db/migration_test.dart`, `app/test/generated_migrations/`).
* **The Encore song references did not get tables of their own.** One `tracks` table carries both a plain music server's songs and an Encore server's song references: for a reference, `is_ref` is true, `id` is the ref id (`sr_...`, the same on every device) and `file_id` is the music server's id of the kept file when the server holds one (null: the song plays from the server's stream by ref); `video_id`, `artists_json`, `cover_url` and `explicit` carry what a catalogue song brings with it (schema 6). There is no `SongRefs` or `SongFiles` table.
* A like is `tracks.starred_at_ms` (saved albums and followed artists the same way on `albums` and `artists`); `pins` and `downloads` are keyed by the track id, which is the ref id on an Encore server; `playlist_entries` keeps the server's entry id and its fractional position next to the phone's own order.
* `outbox` holds the operation kinds of `17` section 5; `sync_state` holds the cursors of `library/changes` and `library/files` and the saved queue.
* **A song's artist link points at an artist the phone lists, whenever its album's artist is listed** (audit B-118). The music server lists only album artists in its artist index, and a song tagged `Post Malone, Swae Lee` belongs for it to an artist of that whole name that has no album and is not in the index; the song's `artistId` points at it, so the phone never receives that row (on a freshly signed-in phone: 382 of 4,719 songs, 145 such artists, 159 of the songs showing a single artist name because a reference carries its own first artist). `LibraryWriter.linkSongsToListedArtists` moves such a song to the artist of its album, after every write of songs and at the start of every sync run; a song with no such album keeps its link and the artist page then looks the artist up by name. A page of one thing the phone has no row for (artist, album, playlist) is never a bare spinner: after a moment it says so and keeps its Back.
* `albums`, `artists` and the rest of `tracks` are the browse index of the server's files. `requests` is the old homelab request portal (P2-07 removes it).

## 3. What exists today and must survive

This section and section 4 are the migration of task P2-11 (now Later). The machines named in the table, CT 104 and the dev VM, were destroyed on 2026-11-03 (`06`); the table records what that migration had to preserve. A real old install is the test input when P2-11 is scheduled.

| Where | What | Owner's data? |
|-------|------|---------------|
| CT 104 (`/opt/encore`, Navidrome 0.64.2 + people + fetch + hub) | accounts `owner`, `tester`, `mia`, `nina`, `friend`, `encore-admin`; roles in the people service's data folder; per-person folders under `/srv/music/<person>` with fetched songs; the owner's collection mounted read-only; likes/playlists/plays in Navidrome's database; running import queues in `/work/imports` | `owner` is the owner's own account; the rest are test accounts |
| dev VM | the same plus quality and recommendations data | test only |
| Phones (owner's phone, his friend's phone, emulators) | local databases with likes, playlists, downloads, saved queue | yes (owner, friend) |

## 4. The migration (task P2-11, runs once per server when the new Encore server first starts next to Navidrome)

1. **Back up** Navidrome's database, the people service's data folder and the fetch service's work folder (to `/data/backups/`).
2. **People:** every Navidrome user except the hidden administrator becomes a `person`; roles and "invited by" come from the people
   service's data.
3. **Files:** scan the libraries Navidrome knows; every song gets a `song_ref` (matched by ISRC/MBID tags if present, else `norm_key`)
   and a `song_file`. The same recording found in several per-person folders becomes **one ref with several files**; the duplicates
   report (`19` §6) lets the Host delete extra copies later (D-2: one copy per song). New keeps go to `/music/Encore/`.
4. **Likes, playlists, plays:** read per person from Navidrome. Preferred: through the gateway's trusted header acting as each user
   (experiment X-2); fallback: each phone uploads its own library on its first launch after the update (P2-02). Navidrome play
   counts and scrobble history become `play_event`s, so Year in Music continues.
5. **Running imports:** finished ones become playlists of refs; unfinished ones are re-created as imports of refs (their list is in
   the work folder) so nothing waits for downloads anymore.
6. **Check:** counts per person (likes, playlists, entries, plays) before and after are printed; any difference stops the switch.
7. **Switch:** the app talks to the new server only after the check passes; the old services stop (not deleted) for 14 days.
* Proof (when P2-11 is scheduled): run it first on a copy of a real old install on the test VM 108; only then on anybody's server, with their go and a backup first.
