-- Lyrics on the server (docs/tasks P2-14, docs/11 ADR-R38): what the lyrics service said about a song, kept per song reference so that every client gets
-- the same words and a miss is asked about again on a sensible schedule (AUDIT F22), not after a fixed day.

CREATE TABLE lyrics (
  ref        TEXT PRIMARY KEY REFERENCES song_ref(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (kind IN ('synced', 'plain', 'instrumental', 'none')),
  body       TEXT,                                -- synced: json [{ms, text}]; plain: json string; otherwise null
  source     TEXT NOT NULL,                       -- where it came from (lrclib)
  fetched_at INTEGER NOT NULL,                    -- ms: when the service was last asked
  retry_at   INTEGER,                             -- ms: when to ask again (null: never needed)
  misses     INTEGER NOT NULL DEFAULT 0           -- in a row, for a growing pause
);
