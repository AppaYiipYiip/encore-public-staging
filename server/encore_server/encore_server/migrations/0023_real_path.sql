-- N-53 (encore_server/real_paths.py, docs/tasks/N-53-real-place-of-library-files.md): is song_file.path the file's REAL place?
--
-- The `path` the music server's Subsonic API reports is built from the song's TAGS, not from where the file lies (measured on the real music server), and the scanner stores it. So a row's path is a
-- location only when the keeper placed the file or when the music server's native API named the place and the file is there.
--
-- song_file.path_real        1 = `path` is the file's real place relative to the music folder (the keeper placed it, or the errand checked it); 0 = unverified (the scanner's tag-built path,
--                            or not checked yet). Every row starts at 0 and the hourly errand checks them over a few passes: this is also the re-link of the rows that already exist.
-- song_file.path_checked_at  when the errand last looked at the row (milliseconds), or NULL: the rows never looked at come first, so a row that cannot be resolved cannot keep the others waiting.
ALTER TABLE song_file ADD COLUMN path_real INTEGER NOT NULL DEFAULT 0;
ALTER TABLE song_file ADD COLUMN path_checked_at INTEGER;

-- The keeper's own rows: the keeper writes the only `youtube` rows, with the place it put the file at, under its own folder. They are checked by construction (without this they would lose their audio
-- keys until the errand had verified them, and for ever where the administrator login of the music server fails).
UPDATE song_file SET path_real = 1 WHERE source = 'youtube' AND path LIKE 'Encore/%';
