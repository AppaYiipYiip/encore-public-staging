-- Song refs that were merged into one (N-11 part B). Two refs that held the same file of the music server were one song shown twice; the start-up repair
-- (`refmerge.py`) keeps the ref whose file was attached first, moves everything a person has onto it and deletes the other. This table remembers what
-- became of the deleted ref, for three readers:
--   * a client that still names the old id (an old app, an edit queued offline, a signed address issued before the repair): `refs.canonical`;
--   * `refs.find`: a song described again the way the deleted ref was (its ISRC, catalogue or video id, or its artist + title + length) finds the
--     survivor instead of making the duplicate again, which is why the deleted ref's identifying fields are kept here;
--   * the phone: `GET /library/files` lists the merges after a cursor (`seq`), so it can fold its own copy of the old ref into the survivor.
-- `into_id` has NO foreign key on purpose: a survivor that is merged away later must not take its tombstones with it (the repair re-points them).

CREATE TABLE ref_merge (
  seq          INTEGER PRIMARY KEY AUTOINCREMENT,
  old_id       TEXT NOT NULL UNIQUE,              -- the song ref that no longer exists
  into_id      TEXT NOT NULL,                     -- the song ref that took its place (always a live ref: re-pointed when that one is merged in turn)
  at           INTEGER NOT NULL,
  norm_key     TEXT,                              -- the old ref's identifying fields, as they were when it was merged
  isrc         TEXT,
  deezer_id    TEXT,
  ytm_video_id TEXT,
  duration_ms  INTEGER
);
CREATE INDEX ref_merge_into ON ref_merge(into_id);
CREATE INDEX ref_merge_norm ON ref_merge(norm_key);
CREATE INDEX ref_merge_isrc ON ref_merge(isrc);
CREATE INDEX ref_merge_deezer ON ref_merge(deezer_id);
CREATE INDEX ref_merge_video ON ref_merge(ytm_video_id);

-- The repair (and `library.touch_ref_holders`, `library.played_on_days`) look rows up BY SONG, which these tables could only answer by reading every row:
-- fine for a few thousand, minutes at start-up for a big library with years of plays. The two partial ones hold only the likes (a few rows beside the
-- many entries a change log keeps).
CREATE INDEX playlist_entry_ref ON playlist_entry(ref);
CREATE INDEX play_event_ref ON play_event(ref);
CREATE INDEX library_item_like_target ON library_item(target) WHERE kind = 'like';
CREATE INDEX change_log_like_target ON change_log(target) WHERE kind = 'like';
