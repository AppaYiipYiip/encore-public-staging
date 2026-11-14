-- Artists the music server lists with no picture (N-15): when the server last looked for a picture and what came of it.
-- A miss is remembered so the catalogue is not asked again at every pass; a catalogue that could not be asked is never written here.
CREATE TABLE artist_picture (
  artist_id  TEXT PRIMARY KEY,                    -- the music server's own id for the artist
  name       TEXT NOT NULL,                       -- as the music server spells it when last looked for
  tried_at   INTEGER NOT NULL,                    -- the last real look-up
  outcome    TEXT NOT NULL CHECK (outcome IN ('found', 'none')),
  source     TEXT,                                -- where a found picture came from ('deezer')
  source_url TEXT                                 -- the address it was taken from
);
