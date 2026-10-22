-- Where a playlist came from, so bringing a person's library over from the music server is done once per source playlist
-- (`nd:<the music server's playlist id>`), however often it runs and from whichever phone.
ALTER TABLE playlist ADD COLUMN source_id TEXT;
CREATE UNIQUE INDEX playlist_source ON playlist(owner, source_id) WHERE source_id IS NOT NULL;
