-- People (docs/21): invitations, password resets, and the count of wrong passwords that locks an account.

CREATE TABLE invite (
  id         TEXT PRIMARY KEY,                    -- iv_...
  code_hash  TEXT NOT NULL UNIQUE,                -- sha256 of the code; the code is shown once
  role       TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'member')),
  created_by TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  note       TEXT,                                -- what the owner called it ("for Sara")
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  used_by    TEXT REFERENCES person(id) ON DELETE SET NULL,
  used_at    INTEGER,
  revoked_at INTEGER
);
CREATE INDEX invite_creator ON invite(created_by, created_at);

CREATE TABLE reset_code (
  id         TEXT PRIMARY KEY,                    -- rc_...
  person     TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  code_hash  TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at    INTEGER
);

ALTER TABLE person ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0;
