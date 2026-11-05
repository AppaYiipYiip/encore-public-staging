-- The songs of a saved release (P2-22 part 1, docs/17 "Saving a release"). A saved album used to be one row in `library_item` (the catalogue's
-- album id) and the songs the phone named were only queued for keeping; nothing recorded which songs belong to the release. The phone's
-- Download screen needs "how many of this release's songs does the server have ready", so the members are stored, per person, with the save.

CREATE TABLE saved_album_ref (
  person TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  album  TEXT NOT NULL,                           -- the same id as library_item.target of kind 'saved_album'
  ref    TEXT NOT NULL REFERENCES song_ref(id) ON DELETE CASCADE,
  PRIMARY KEY (person, album, ref)
);
CREATE INDEX saved_album_ref_ref ON saved_album_ref(ref);
