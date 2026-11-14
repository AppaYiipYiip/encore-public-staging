-- P1-26: the picture a song's SOURCE gave it (an import's YouTube thumbnail), kept apart from the real cover (`cover_url`) so that the
-- cover finder, which looks for songs whose `cover_url` is empty, still looks for a better picture. The API serves `cover_url` when there is
-- one and `thumb_url` until then.
ALTER TABLE song_ref ADD COLUMN thumb_url TEXT;
