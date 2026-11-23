-- N-34 slice 2: what the server remembers about WHICH ALBUM A SONG IS ON, asked of the catalogue (`album_pass.py`, `album_finder.py`). Four plain nullable columns on
-- `song_ref`, no default, no check, no table: NULL means "never asked", which is what every row is today. Nothing is derived for an old row. (The journal table
-- of the repair that moves files is slice 5's, `refile_log`: not here.)
--   identity_tried_at   when the catalogue was last asked and ANSWERED (milliseconds). A `none` or a `held` is asked again 7 days later.
--   identity_rev        the revision of the rule that made the answer (`album_finder.IDENTITY_REVISION`): a better rule asks the `none` and `held` songs again at once.
--   identity_outcome    matched | none | held: the three answers that are FACTS about the song and the catalogue. "Could not ask" (the catalogue down or resting,
--                       no length, a name with nothing to compare) is never stored (audit B-124); the value is checked in `album_pass`, so a fourth one needs no rebuild.
--   identity_reason     the short code of the step that decided (`no_same_recording`, `latin_spelling_only`, `single_before_album`, `compilation_title`,
--                       `deezer_id_held`, `twin_held`, ...): "none or held, with a reason", so the songs the catalogue could not place can be counted by cause from the
--                       database itself, without asking again.
ALTER TABLE song_ref ADD COLUMN identity_tried_at INTEGER;
ALTER TABLE song_ref ADD COLUMN identity_rev INTEGER;
ALTER TABLE song_ref ADD COLUMN identity_outcome TEXT;
ALTER TABLE song_ref ADD COLUMN identity_reason TEXT;
