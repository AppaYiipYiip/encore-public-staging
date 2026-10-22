-- What the app needs to play and show a kept song without asking the music server again (docs/18 section 2): the music server's ids for the
-- song's album, artist and cover, its size and suffix, its replay gain. Stored as the music server told us; the app picks what it needs.
ALTER TABLE song_file ADD COLUMN meta TEXT;

-- Which songs' files changed, in order: the feed of the server's files (`GET /library/files?since=`). A row says "look at this song again";
-- what a song's file is now is read from the tables, so a client that misses a row or asks twice still ends up right.
CREATE TABLE file_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ref TEXT NOT NULL,
  at  INTEGER NOT NULL
);
CREATE INDEX file_log_ref ON file_log(ref, seq);
