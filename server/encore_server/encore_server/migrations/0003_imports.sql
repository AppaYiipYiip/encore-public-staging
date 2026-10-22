-- Imports (docs/tasks P2-04): a link or a file of songs becomes a playlist of refs in seconds. The counts a person sees come only from here.

CREATE TABLE import (
  id         TEXT PRIMARY KEY,                    -- im_... (made by the client, so a retried request is one import)
  person     TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  source     TEXT NOT NULL CHECK (source IN ('youtube', 'spotify', 'file')),
  url        TEXT,
  name       TEXT NOT NULL,
  playlist   TEXT REFERENCES playlist(id),
  state      TEXT NOT NULL DEFAULT 'running' CHECK (state IN ('running', 'done', 'stopped', 'failed')),
  truncated  INTEGER NOT NULL DEFAULT 0,          -- the list was longer than the server reads (or the source shows only its first hundred)
  error      TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX import_person ON import(person, created_at);

CREATE TABLE import_entry (
  import   TEXT NOT NULL REFERENCES import(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  ref      TEXT NOT NULL REFERENCES song_ref(id),
  state    TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'matched', 'not_found')),
  video    TEXT,                                  -- the video the source named: used when the song cannot be found by its name
  PRIMARY KEY (import, position)
);
CREATE INDEX import_entry_ref ON import_entry(ref);
