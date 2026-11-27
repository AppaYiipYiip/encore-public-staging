-- P3-16 (docs/36 section 6): getting back in after a forgotten password, and the audit line every such act leaves.
--
-- recovery_key  one row per owner who has a recovery key: five groups of four letters and digits, made once (at the end of the first-run page, or by `encore recovery-key`),
--               shown ONCE, and kept only as a hash. Nothing here can show it again; a lost key is replaced, never recovered.
--   person     the owner it belongs to
--   key_hash   SHA-256 of the key without its dashes, in capitals. The key is 99 random bits, so a plain hash is enough: there is nothing to guess.
--   made_at    milliseconds
-- audit_log     what a Host did to the server from the computer, as plain facts (never a password, a key or a code): who it was done to, what, and how. The helper's actions
--               (docs/36 section 3) leave their lines here too. It is the Host's to read and nobody's to rewrite, so no route writes it and nothing edits a row.
--   at         milliseconds
--   kind       reset_password | recovery_key | ... (a word, not a sentence)
--   subject    the person the act was about (their username), or ''
--   detail     one short sentence in plain words
CREATE TABLE recovery_key (
  person   TEXT PRIMARY KEY REFERENCES person(id) ON DELETE CASCADE,
  key_hash TEXT NOT NULL,
  made_at  INTEGER NOT NULL
);

CREATE TABLE audit_log (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  at      INTEGER NOT NULL,
  kind    TEXT NOT NULL,
  subject TEXT NOT NULL DEFAULT '',
  detail  TEXT NOT NULL
);
