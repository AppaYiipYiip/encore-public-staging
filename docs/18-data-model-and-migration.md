# 18 — Data model and the migration from today's installs

Why: P2 changes where a person's library lives (`04` §3). Without a written schema and a migration path, an agent would either break
the owner's existing data or keep the old model alongside the new one forever.

## 1. The Encore server's database (SQLite, WAL, one file `/data/encore.db`)

| Table | Key columns | Notes |
|-------|-------------|-------|
| `person` | id, navidrome_user, display_name, role (`owner`, `member`), invited_by, created_at, locked, explicit_ok, federation_ok | Navidrome keeps the password; Encore keeps everything else |
| `device` | id, person, name, kind, token_hash, app_version, last_seen, available, shared, always_ready, volume | `13` §2 |
| `song_ref` | id, title, artists (json), album, album_artist, track_no, disc_no, year, duration_ms, isrc, mbid, deezer_id, ytm_video_id, cover_url, explicit, norm_key, created_at | `norm_key` = normalised artist+title+duration bucket (`19` §2); unique on isrc, on ytm_video_id, on deezer_id where present |
| `song_file` | id, ref, navidrome_song_id, path, codec, bitrate, loudness_lufs, source (`library`, `youtube`, `quality`), added_at | one ref may have several files; `preferred` chosen by quality; the old file kept 14 days after an upgrade |
| `library_item` | person, kind (`like`, `saved_album`, `follow_artist`), target, at | per-person set; tombstones in `change_log` |
| `playlist` / `playlist_entry` | id, owner, name, cover, collaborative / id, playlist, position (fractional index), ref, added_by, at | fractional positions make concurrent moves mergeable (`17` §5) |
| `play_event` | person, ref, at, ms_played, device, context | Year in Music, history, recommendations |
| `playback_state` | person, ref, position_ms, queue (json of refs), index, context, shuffle, repeat, playing, active_device, rev, updated_at | `13` §2, ADR-R9 |
| `work_item` | id, kind (`play`, `prepare`, `match`, `keep`, `measure`), ref, person, priority, state, attempts, next_try_at, error | the scheduler of `04` §10 lives here, so a restart resumes |
| `import` / `import_entry` | id, person, source, url, state, counts / import, position, raw (json), ref, state | |
| `change_log` | person, seq, kind, payload, at | feeds `library/changes` cursors and tombstones |
| `profile` | person, vectors (json), updated_at | recommendations (`20`) |
| `friend` / `remote_server` | person, remote_handle, server, state / server, public_key, first_seen, allowed | federation (`13` §4) |
| `invite`, `session_code`, `idempotency_key`, `problem_report`, `setting` | | |

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
