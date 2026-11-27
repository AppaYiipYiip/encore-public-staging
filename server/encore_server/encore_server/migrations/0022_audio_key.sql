-- N-38 (encore_server/audio_key.py, docs/tasks/N-38-audio-only-key.md): the audio-only key of a file, so that a rewrite of a kept file's TAGS does not make every phone download the song again.
--
-- song_file.audio_key       `a1:` + 32 hex digits of the SHA-256 of the file's first audio stream (never the tags). NULL = not made yet; '' = ffmpeg cannot read the file at audio_key_size.
-- song_file.audio_key_size  the file's size in bytes when the key was taken (or carried over a tag rewrite): when it differs from the music server's `meta.size` the file changed and the key is made again.
-- song_file.audio_key_tried_at  when the hourly errand last looked at the file (made a key, found it unreadable, could not find it, or was stopped by it): the errand takes the files it has NEVER
--                               looked at first, then the longest ago, so a file that cannot be keyed never keeps the others from it.
-- All three are NULL on every row until the keeper or the hourly errand makes them: a server that has not made a key serves none, and a phone then does what it did before.
ALTER TABLE song_file ADD COLUMN audio_key TEXT;
ALTER TABLE song_file ADD COLUMN audio_key_size INTEGER;
ALTER TABLE song_file ADD COLUMN audio_key_tried_at INTEGER;
