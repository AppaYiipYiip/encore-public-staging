-- N-31 (N-27 slice 2d): the songs of deleted playlists, removed entries and old imports are cleaned away too (`tombstone_purge.py`). Three additions, no row removed.
--
-- 1. change_log.parent: for a log row of kind 'entry', the playlist the entry belongs to (NULL for every other kind). A removed entry is purged 90 days after
--    the removal, and the feed then answers `{id, playlist, deleted: true}` for the entry the log still names: the phone skips an entry that names no playlist
--    (`encore_writer.dart`), so the log must remember which playlist it was. An entry never moves to another playlist, so any log row of it says the same.
--    The log rows already there are filled from the entries that still exist (nothing has ever purged one). An entry that was deleted for good before this
--    (a person removed from the server) keeps NULL: nobody can name its playlist, and the phone treats it as it always did.
--    `change_log` is NEVER pruned: the rows are what lets a phone that was away for months learn that something is gone (the 90 and 60 days are a margin of
--    support, not what keeps the phone correct). If a prune of the log is ever written, it must come with a way for a phone to know its cursor is too old.
-- 2. Two partial indexes, so that the hourly purge reads only the tombstones and never scans the playlists or their entries.
-- 3. import.entries_purged_at and import.final_*: an import's counts (the total, how many were matched, not found, still waiting, and kept on the server)
--    were counted from its entries on every read. When the entries of an import that finished more than 60 days ago are purged, the counts are stored here
--    in the same transaction. NULL in entries_purged_at means: count the entries, as before.

ALTER TABLE change_log ADD COLUMN parent TEXT;

UPDATE change_log
   SET parent = (SELECT playlist_entry.playlist FROM playlist_entry WHERE playlist_entry.id = change_log.target)
 WHERE kind = 'entry';

CREATE INDEX playlist_entry_removed ON playlist_entry(deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX playlist_deleted ON playlist(deleted_at) WHERE deleted_at IS NOT NULL;

ALTER TABLE import ADD COLUMN entries_purged_at INTEGER;
ALTER TABLE import ADD COLUMN final_total INTEGER;
ALTER TABLE import ADD COLUMN final_matched INTEGER;
ALTER TABLE import ADD COLUMN final_unmatched INTEGER;
ALTER TABLE import ADD COLUMN final_pending INTEGER;
ALTER TABLE import ADD COLUMN final_kept INTEGER;
