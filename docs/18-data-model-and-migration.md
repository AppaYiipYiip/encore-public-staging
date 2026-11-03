# 18 — Data model and the migration from today's installs

Why: P2 changes where a person's library lives (`04` §3). Without a written schema and a migration path, an agent would either break
the owner's existing data or keep the old model alongside the new one forever.

## 1. The Encore server's database (SQLite, WAL, one file `/data/encore.db`)

| Table | Key columns | Notes |
|-------|-------------|-------|
| `person` | id, navidrome_user, display_name, role (`owner`, `member`), invited_by, created_at, locked, explicit_ok, federation_ok, failed_logins | Navidrome keeps the password; Encore keeps everything else |
| `device` | id, person, name, kind, token_hash, app_version, created_at, last_seen, revoked_at, available, shared, always_ready, volume | `13` §2 |
| `song_ref` | id, title, artists (json), album, album_artist, track_no, disc_no, year, duration_ms, isrc, mbid, deezer_id, ytm_video_id, cover_url, explicit, norm_key, created_at, cover_tried_at | `norm_key` = normalised artist+title+duration bucket (`19` §2); unique on isrc, on ytm_video_id, on deezer_id where present; `cover_tried_at` = when the server last looked for a picture, so a song nobody has one for is not asked about every hour |
| `song_file` | id, ref, navidrome_song_id, path, codec, bitrate_kbps, loudness_lufs, source (`library`, `youtube`, `quality`), preferred, added_at, meta (json: the music server's ids for the album, artist and cover, size, suffix, replay gain) | one ref may have several files; `preferred` chosen by quality; the old file kept 14 days after an upgrade |
| `library_item` | person, kind (`like`, `saved_album`, `follow_artist`), target, at | per-person set; tombstones in `change_log` |
| `playlist` / `playlist_entry` | id, owner, name, cover, collaborative, created_at, updated_at, deleted_at, source_id (`nd:<the music server's playlist id>`, so bringing a library over is done once per source playlist) / id, playlist, position (fractional index), ref, added_by, at, deleted_at | fractional positions make concurrent moves mergeable (`17` §5) |
| `play_event` | id (made by the phone: a retried report is one play), person, ref, at, ms_played, device, context | Year in Music, history, recommendations |
| `playback_state` | person, ref, position_ms, queue (json of refs), idx, context, shuffle, repeat, playing, active_device, rev, updated_at | `13` §2, ADR-R9 |
| `work_item` / `work_item_person` | id, kind (`play`, `prepare`, `download`, `match`, `keep`, `measure`), ref, priority, state (`queued`, `running`, `done`, `failed`, `cancelled`), attempts, next_try_at, error / item, person | the scheduler of `04` §10 lives here, so a restart resumes. One active item per kind and song (single flight); `work_item_person` says who wants it, so Stop cancels only what nobody else needs (built in `server/encore_server/encore_server/scheduler.py`) |
| `import` / `import_entry` | id, person, source (`youtube`, `spotify`, `file`), url, name, playlist, state (`running`, `done`, `stopped`, `failed`), truncated, error, created_at, updated_at / import, position, ref, state (`pending`, `matched`, `not_found`), video | the counts a person sees are counted from `import_entry`, not stored |
| `change_log` | seq, person, kind (`like`, `saved_album`, `follow_artist`, `playlist`, `entry`), target, at | feeds `library/changes` cursors: a row says "this thing was touched"; the current state is read from the tables (a deleted playlist or entry keeps its row with `deleted_at`), so a phone that misses a row or asks twice still ends right |
| `file_log` | seq, ref, at | which songs' files changed, in order: the feed of `GET /library/files?since=` |
| `invite` / `reset_code` | id, code_hash, role, created_by, note, created_at, expires_at, used_by, used_at, revoked_at / id, person, code_hash, created_at, expires_at, used_at | `21`; only the hash of a code is kept, the code is shown once |
| `notification` | id, person, kind (`release`, `jam`, `invite_used`, `import_done`), title, body, route, dedupe, created_at, read_at | the bell (ADR-R44): news kept per person and said in words, the same news told twice is made once |
| `lyrics` | ref (the song reference), kind (`synced`, `plain`, `instrumental`, `none`), body (synced: json `[{ms, text}]`; plain: json string), source (`lrclib`), fetched_at, retry_at, misses | lyrics on the server (P2-14, migration `0009`): what the lyrics service said about a song, per song reference; a miss is asked about again after 1 h, 6 h, 24 h, 7 d; a plain answer is looked at again after 14 days for a synced one |
| `idempotency_key`, `setting` | person, key, response, status, at / key, value | a write that is not naturally idempotent remembers its answer for 7 days (the `Idempotency-Key` header); settings |
| `profile` | person, vectors (json), updated_at | **planned, no migration yet**: recommendations (`20`) |
| `friend` / `remote_server` | person, remote_handle, server, state / server, public_key, first_seen, allowed | **planned, no migration yet**: federation (`13` §4) |
| `session_code`, `problem_report` | | **planned, no migration yet** |

Migrations: numbered SQL files run at start-up inside a transaction, with a backup copy of the database taken first
(`/data/backups/encore-<version>-<time>.db`); a failed migration restores it and the server refuses to start with a plain message.

## 2. The phone's database (drift)

Keep the existing tables where they still fit; the changes:
* New `SongRefs` (mirror of `song_ref` for the refs this person uses) and `SongFiles` (only the server file ids needed to stream).
* `Likes`, `PlaylistEntries`, `Pins` (downloads), `PlayHistory`, the saved queue: keyed by **ref id** instead of Navidrome id.
* `Tracks`/`Albums`/`Artists` stay as the **browse index of the server's files** (for the Library's Albums/Artists views of kept music).
* New `Outbox` operation types (`17` §5), `SyncState.cursor` for `library/changes`.
* Every schema version has a drift migration with a test that upgrades a real database captured from build 40 (P2-02).

## 3. What exists today and must survive

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
* Proof: run it first on a copy of CT 104's data on the dev VM; then on CT 104 itself with the owner's go.
