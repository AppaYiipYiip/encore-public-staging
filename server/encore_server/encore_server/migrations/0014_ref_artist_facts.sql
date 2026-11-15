-- How a song's artist was decided, and who uploaded the video it came from (N-26 slice 2; design `docs/tasks/P2-songs-as-references.md`, section "N-26").
-- An imported YouTube upload is not a song of a catalogue artist: YouTube Music lists the UPLOADING CHANNEL as its artist. The importer reads the title
-- (`imports/uploads.py`) and these two columns keep the FACTS of that reading, so that a name which is only a channel never gets an artist picture, and a later,
-- better rule can re-derive offline instead of guessing.
--   artist_basis  declared | title | channel | unknown
--                   declared: the source says so (a song of the catalogue, a Spotify list, an official video's credit)
--                   title:    the title names the performer ("Artist - Song")
--                   channel:  nothing names a performer; the uploader stays as the artist, flagged (the one named stop-gap, removed by N-28)
--                   unknown:  nobody is named; the song is filed under the placeholder "Unknown Artist"
--                 NULL: **as before**, never `channel`. A ref made before this migration, by a phone, by the library scan, or from a file import has no
--                 facts and is treated as it always was (its artist is a performer). Nothing below ever derives a value for an old row.
--   uploader      the channel that uploaded the video this ref plays from, when the song came from an upload (a fact about the VIDEO: it is stored only
--                 with the video it belongs to). NULL for a song of the catalogue and for every old row.
-- Set only by the importer (keyword arguments of `refs.resolve`), never read from a client's JSON. Not shown to phones (`docs/17` does not change).
-- Only adds two nullable columns: no DEFAULT (an old row would read as that value), no CHECK (a fifth basis would cost a table rebuild: the value is
-- checked in `refs`), no UPDATE.
ALTER TABLE song_ref ADD COLUMN artist_basis TEXT;
ALTER TABLE song_ref ADD COLUMN uploader TEXT;
