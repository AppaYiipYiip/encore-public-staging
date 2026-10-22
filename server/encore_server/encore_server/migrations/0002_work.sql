-- The work the server does in the background (docs/04 section 10, docs/18 section 1): matching a song to an upload, keeping a copy,
-- measuring loudness. It lives in the database so that a restart resumes where it was.

CREATE TABLE work_item (
  id          TEXT PRIMARY KEY,                   -- wk_...
  kind        TEXT NOT NULL CHECK (kind IN ('play', 'prepare', 'download', 'match', 'keep', 'measure')),
  ref         TEXT NOT NULL REFERENCES song_ref(id) ON DELETE CASCADE,
  priority    INTEGER NOT NULL,                   -- 0 is first: play, prepare, download, match, keep, measure
  state       TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'done', 'failed', 'cancelled')),
  attempts    INTEGER NOT NULL DEFAULT 0,
  next_try_at INTEGER NOT NULL,
  error       TEXT,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
-- Single flight: one active item per kind and song, however many people want it.
CREATE UNIQUE INDEX work_item_active ON work_item(kind, ref) WHERE state IN ('queued', 'running');
CREATE INDEX work_item_next ON work_item(state, priority, next_try_at);

-- Who wants an item (round-robin between people, and Stop cancels only what nobody else needs).
CREATE TABLE work_item_person (
  item   TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
  person TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  PRIMARY KEY (item, person)
);
CREATE INDEX work_item_person_person ON work_item_person(person);
