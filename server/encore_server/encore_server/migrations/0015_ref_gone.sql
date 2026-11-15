-- N-27 slice 2c: the refs the server retired (`ref_janitor.py`), so that a phone that was away can be told which ids are gone. The precedent is `ref_merge`:
-- a tiny table, never purged (a row is about sixty bytes; a phone that comes back after a year still hears it), read through its own cursor
-- (`GET /library/files?goneSince=`, feature `ref-gone`). The janitor writes one row for EVERY ref it retires, in the transaction that deletes it.
--   seq     the order, and the phone's cursor
--   ref_id  the song ref that no longer exists; no foreign key on purpose (there is nothing to point at), unique: one tombstone per ref
--   at      when the janitor retired it (milliseconds)
-- This migration takes the number 0015 on purpose: N-26 slice 2 (0014) was written beside it, and two branches that start from one main both see the next
-- number as free.
CREATE TABLE ref_gone (
  seq    INTEGER PRIMARY KEY AUTOINCREMENT,
  ref_id TEXT NOT NULL UNIQUE,
  at     INTEGER NOT NULL
);
