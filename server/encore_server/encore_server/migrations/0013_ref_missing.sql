-- What the server remembers about a song it cannot get (N-13). A "no" that the source ANSWERED (a search that found nothing acceptable, an upload that is gone,
-- an age check) is kept on the ref for a window, so the next tap needs no look-up at YouTube and the app can mark the song before it is tapped
-- (`missing.py`, docs/17 "Songs the server cannot get"). Like `cover_tried_at`: a plain column, no table, nothing to join.
--   missing_reason     not_found | removed | age_restricted (NULL: the ref remembers nothing)
--   missing_at         when the server first learned it (milliseconds); kept across later tries, reset when the memory is cleared
--   missing_tried_at   the LAST real try; the window of 7 days counts from here
--   missing_rev        the matcher's revision (`sources/youtube/scoring.py: MATCHER_REVISION`) that made the answer: a better matcher voids older ones at once
ALTER TABLE song_ref ADD COLUMN missing_reason TEXT;
ALTER TABLE song_ref ADD COLUMN missing_at INTEGER;
ALTER TABLE song_ref ADD COLUMN missing_tried_at INTEGER;
ALTER TABLE song_ref ADD COLUMN missing_rev INTEGER;
