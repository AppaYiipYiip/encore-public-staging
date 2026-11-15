-- P3-35: every page of the library link asks which file row holds each of 500 ids of the music server (`refs.file_holders`: `WHERE navidrome_song_id IN (...)`).
-- Only `ref` had an index, so each page read every row of `song_file`: the cost of a pass grew with the SQUARE of the library. Measured on this PC, nothing changed
-- since the last pass, music server faked: 7,200 songs 0.7 s, 50,000 songs 11 s, 200,000 songs 147 s (0.09, 0.22 and 0.74 ms a song). The link now also runs after
-- every scan that changed something, so the pass has to be cheap on a big library. A partial index: the rows with no id (a file kept before the music server had
-- listed it) are never asked for by id.
CREATE INDEX song_file_music_server_id ON song_file(navidrome_song_id) WHERE navidrome_song_id IS NOT NULL;
