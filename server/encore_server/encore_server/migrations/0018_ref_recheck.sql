-- P2-25 slices 2 and 3 (audit B-37): the keys of every song move to one fold for every alphabet (`textnorm.py`). This migration ONLY adds what the start-up
-- repair (`keyrepair.py`, which is Python, not SQL: it needs the fold) and the merge repair read and write. It rewrites nothing.
--
--   ref_recheck  the WORKLIST of the one-time repair: a song whose own artist or title did not survive the OLD ASCII fold AND that holds a library file, so
--                its files may belong to other songs (the old fold glued two different Arabic songs onto one ref). `keyrepair` fills it; `refmerge` HOLDS a
--                pair when either ref is on it (a file two refs hold may be on the wrong one: merging on its strength would put one song's likes on
--                another); the rehome of slice 4 (`rehome.py`) judges the files and empties it. No foreign key on purpose, like `file_log.ref` and
--                `ref_gone.ref_id`: a worklist is not a reason to keep a ref, and a row whose ref is gone is dropped by the pass.
--                STOP-GAP(P2-25 one-shot-repair): the table goes when it is empty on every install the project knows and one release has passed (N-36).
--   ref_merge.title, ref_merge.artist  what the merged-away ref was called, so the NEXT change of the fold can rewrite the tombstone's `norm_key`
--                (which cannot be derived from the key itself). Written by `refmerge` from now on; a row made before stays NULL (decision D10).
CREATE TABLE ref_recheck (
  ref   TEXT PRIMARY KEY,
  at    INTEGER NOT NULL,
  moved INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE ref_merge ADD COLUMN title TEXT;
ALTER TABLE ref_merge ADD COLUMN artist TEXT;
