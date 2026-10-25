-- The bell (docs/tasks P2-15, ADR-R44): news kept per person and said in words, so every client shows the same list.

CREATE TABLE notification (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  person     TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (kind IN ('release', 'jam', 'invite_used', 'import_done')),
  title      TEXT NOT NULL,
  body       TEXT,
  route      TEXT,                                -- where a tap goes in the app (/settings/import), or none
  dedupe     TEXT,                                -- the same news told twice is made once
  created_at INTEGER NOT NULL,
  read_at    INTEGER
);
CREATE INDEX notification_person ON notification(person, id);
CREATE UNIQUE INDEX notification_dedupe ON notification(person, dedupe) WHERE dedupe IS NOT NULL;
