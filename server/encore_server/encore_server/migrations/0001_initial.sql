-- The Encore server's database (docs/18 section 1). Songs are references; files are attached.

CREATE TABLE person (
  id            TEXT PRIMARY KEY,                 -- pn_...
  navidrome_user TEXT NOT NULL UNIQUE,            -- the music server keeps the password; Encore keeps everything else
  display_name  TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'member')),
  invited_by    TEXT,
  created_at    INTEGER NOT NULL,
  locked        INTEGER NOT NULL DEFAULT 0,
  explicit_ok   INTEGER NOT NULL DEFAULT 1,
  federation_ok INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE device (
  id          TEXT PRIMARY KEY,                   -- dv_...
  person      TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'phone',
  token_hash  TEXT NOT NULL UNIQUE,               -- sha256 of the device token; the token itself is shown once
  app_version TEXT,
  created_at  INTEGER NOT NULL,
  last_seen   INTEGER,
  revoked_at  INTEGER,
  available   INTEGER NOT NULL DEFAULT 1,
  shared      INTEGER NOT NULL DEFAULT 0,
  always_ready INTEGER NOT NULL DEFAULT 0,
  volume      REAL
);
CREATE INDEX device_person ON device(person);

-- One row per real-world recording Encore knows about. Created the moment anyone sees a song (search, import, recommendation).
CREATE TABLE song_ref (
  id           TEXT PRIMARY KEY,                  -- sr_...
  title        TEXT NOT NULL,
  artists      TEXT NOT NULL,                     -- json array of names, the first one is the main artist
  album        TEXT,
  album_artist TEXT,
  track_no     INTEGER,
  disc_no      INTEGER,
  year         INTEGER,
  duration_ms  INTEGER,
  isrc         TEXT,
  mbid         TEXT,
  deezer_id    TEXT,
  ytm_video_id TEXT,
  cover_url    TEXT,
  explicit     INTEGER NOT NULL DEFAULT 0,
  norm_key     TEXT NOT NULL,                     -- normalised artist + title + length bucket (docs/19)
  created_at   INTEGER NOT NULL
);
CREATE UNIQUE INDEX song_ref_isrc ON song_ref(isrc) WHERE isrc IS NOT NULL;
CREATE UNIQUE INDEX song_ref_video ON song_ref(ytm_video_id) WHERE ytm_video_id IS NOT NULL;
CREATE UNIQUE INDEX song_ref_deezer ON song_ref(deezer_id) WHERE deezer_id IS NOT NULL;
CREATE INDEX song_ref_norm ON song_ref(norm_key);

-- A file the server keeps for a ref (or found in the Host's folder). Replacing a file only changes this table: likes and playlists never move.
CREATE TABLE song_file (
  id                 TEXT PRIMARY KEY,
  ref                TEXT NOT NULL REFERENCES song_ref(id) ON DELETE CASCADE,
  navidrome_song_id  TEXT,
  path               TEXT,
  codec              TEXT,
  bitrate_kbps       INTEGER,
  loudness_lufs      REAL,
  source             TEXT NOT NULL DEFAULT 'library' CHECK (source IN ('library', 'youtube', 'quality')),
  preferred          INTEGER NOT NULL DEFAULT 1,
  added_at           INTEGER NOT NULL
);
CREATE INDEX song_file_ref ON song_file(ref);

-- A person's likes, saved albums and followed artists: a set per person.
CREATE TABLE library_item (
  person TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  kind   TEXT NOT NULL CHECK (kind IN ('like', 'saved_album', 'follow_artist')),
  target TEXT NOT NULL,                           -- a song ref id, or the catalogue's album / artist id
  at     INTEGER NOT NULL,
  PRIMARY KEY (person, kind, target)
);

CREATE TABLE playlist (
  id            TEXT PRIMARY KEY,                 -- pl_... (made by the client, so a create can be retried)
  owner         TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  cover         TEXT,
  collaborative INTEGER NOT NULL DEFAULT 0,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL,
  deleted_at    INTEGER
);
CREATE INDEX playlist_owner ON playlist(owner);

-- Positions are fractional (a REAL between its neighbours), so two devices' concurrent moves merge.
CREATE TABLE playlist_entry (
  id         TEXT PRIMARY KEY,                    -- pe_...
  playlist   TEXT NOT NULL REFERENCES playlist(id) ON DELETE CASCADE,
  position   REAL NOT NULL,
  ref        TEXT NOT NULL REFERENCES song_ref(id),
  added_by   TEXT NOT NULL REFERENCES person(id),
  at         INTEGER NOT NULL,
  deleted_at INTEGER
);
CREATE INDEX playlist_entry_playlist ON playlist_entry(playlist, position);

CREATE TABLE play_event (
  id        TEXT PRIMARY KEY,                     -- made by the client: a retried report is one play
  person    TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  ref       TEXT NOT NULL REFERENCES song_ref(id),
  at        INTEGER NOT NULL,
  ms_played INTEGER NOT NULL,
  device    TEXT,
  context   TEXT
);
CREATE INDEX play_event_person ON play_event(person, at);

CREATE TABLE playback_state (
  person        TEXT PRIMARY KEY REFERENCES person(id) ON DELETE CASCADE,
  ref           TEXT,
  position_ms   INTEGER NOT NULL DEFAULT 0,
  queue         TEXT NOT NULL DEFAULT '[]',       -- json array of refs
  idx           INTEGER NOT NULL DEFAULT 0,
  context       TEXT,
  shuffle       INTEGER NOT NULL DEFAULT 0,
  repeat        TEXT NOT NULL DEFAULT 'off',
  playing       INTEGER NOT NULL DEFAULT 0,
  active_device TEXT,
  rev           INTEGER NOT NULL DEFAULT 0,
  updated_at    INTEGER NOT NULL
);

-- What changed for a person, in order: feeds `library/changes` cursors. A row says "this thing was touched"; the current state is read
-- from the tables, so a client that misses an event (or asks twice) still ends up right.
CREATE TABLE change_log (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,
  person  TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  kind    TEXT NOT NULL CHECK (kind IN ('like', 'saved_album', 'follow_artist', 'playlist', 'entry')),
  target  TEXT NOT NULL,
  at      INTEGER NOT NULL
);
CREATE INDEX change_log_person ON change_log(person, seq);

-- A write that is not naturally idempotent remembers its answer for 7 days (the `Idempotency-Key` header).
CREATE TABLE idempotency_key (
  person   TEXT NOT NULL,
  key      TEXT NOT NULL,
  response TEXT NOT NULL,
  status   INTEGER NOT NULL,
  at       INTEGER NOT NULL,
  PRIMARY KEY (person, key)
);

CREATE TABLE setting (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
