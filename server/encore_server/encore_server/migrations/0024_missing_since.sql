-- P3-33 (audit B-40): when the library link first found a file of the music server MISSING from its listing.
--
-- A pass that sees at least half of what is linked removes what is absent at once; a pass that sees less (a disk that is not mounted, a share half there, a restart in the middle of a scan)
-- removes nothing the first time and only writes down when it first missed each file here; a file is removed only after it has been absent for a day and the music server lists something. A file
-- that is listed again has this cleared. NULL = not missed (every row, after this migration).
ALTER TABLE song_file ADD COLUMN missing_since INTEGER;
