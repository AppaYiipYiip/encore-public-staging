-- When the server last looked for a picture for a song that had none (so a song nobody has a picture for is not asked about every hour).
ALTER TABLE song_ref ADD COLUMN cover_tried_at INTEGER;
