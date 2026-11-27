-- P3-34 slice 2a (audit B-56): the server's memory of "a device it already knows", kept across a restart.
--
-- A login the music server ACCEPTED within the last day is remembered so that it is not held up by the guess limits while a stranger is being slowed (docs/21). A restart (every update,
-- every crash) used to clear it, and a scripted guesser then locked the owner's app out within seconds of the server coming back. What is kept is a keyed digest (an HMAC; its key is in the
-- server's own `setting` table, like the key that signs song addresses), never a token, a salt or a password: the digest of `name, token, salt` can only be tested by someone who has all
-- three. `name` (lower case) is kept in the clear only so that a person's rows can be dropped when their password changes, they are locked or removed; `at` is UTC milliseconds of the last
-- use (renewed at most once an hour).
CREATE TABLE login_vouch (
  digest BLOB PRIMARY KEY,
  name   TEXT NOT NULL,
  at     INTEGER NOT NULL
);
CREATE INDEX login_vouch_name ON login_vouch(name);
