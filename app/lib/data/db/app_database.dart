import 'package:drift/drift.dart';

import 'tables.dart';

part 'app_database.g.dart';

/// The single local database (ADR-003/ADR-004).
///
/// Opened on a background isolate in production (see `open_database.dart`);
/// tests use an in-memory executor.
@DriftDatabase(
  tables: [
    Servers,
    Artists,
    Albums,
    Tracks,
    Playlists,
    PlaylistEntries,
    Pins,
    Downloads,
    Outbox,
    PlayHistory,
    Lyrics,
    SyncState,
    RecommendationsCache,
    Requests,
    CoverFallbacks,
    PlaylistAliases,
    Leases,
  ],
)
class AppDatabase extends _$AppDatabase {
  AppDatabase(super.executor);

  /// Bump together with a migration step *and* a schema snapshot
  /// (`dart run drift_dev schema dump ...`) so migrations are testable.
  @override
  int get schemaVersion => 6;

  @override
  MigrationStrategy get migration => MigrationStrategy(
        onCreate: (m) async {
          await m.createAll();
          await _createSearchIndex();
        },
        onUpgrade: (m, from, to) async {
          // Additive migrations only (never destroy user data).
          if (from < 2) {
            // v2: download orphan grace period + retry counter.
            await m.addColumn(downloads, downloads.orphanedAtMs);
            await m.addColumn(downloads, downloads.attempts);
          }
          if (from < 3) {
            // v3: catalogue artwork for albums without a server cover.
            await m.createTable(coverFallbacks);
          }
          if (from < 4) {
            // v4: local playlist id -> server id after delivery.
            await m.createTable(playlistAliases);
          }
          if (from < 5) {
            // v5: outbox items remember how often the server itself failed them.
            await m.addColumn(outbox, outbox.serverErrors);
            // v5: which server stamp the stored playlist songs belong to. Rows
            // that already have songs start with the stamp their metadata
            // shows (the best that can be known).
            await m.addColumn(playlists, playlists.entriesStamp);
            // v5: named leases between the app and the background job.
            await m.createTable(leases);
            await customStatement(
              'UPDATE playlists SET entries_stamp = '
              "COALESCE(CAST(changed_at_ms AS TEXT), 'null') || '|' || song_count "
              'WHERE entries_fetched_at_ms IS NOT NULL',
            );
          }
          if (from < 6) {
            // v6: songs as references (docs/18 section 2): the id of a row may be the server's ref id, and a kept file
            // is one more column; an entry knows its own id on the Encore server.
            await m.addColumn(tracks, tracks.isRef);
            await m.addColumn(tracks, tracks.fileId);
            await m.addColumn(tracks, tracks.artistsJson);
            await m.addColumn(tracks, tracks.videoId);
            await m.addColumn(tracks, tracks.coverUrl);
            await m.addColumn(tracks, tracks.explicit);
            await m.addColumn(playlistEntries, playlistEntries.entryId);
            await m.addColumn(playlistEntries, playlistEntries.serverPosition);
          }
        },
        beforeOpen: (details) async {
          await customStatement('PRAGMA foreign_keys = ON');
          // WAL: readers never block the sync writer (and vice versa).
          await customStatement('PRAGMA journal_mode = WAL');
          await customStatement('PRAGMA synchronous = NORMAL');
          // The background sync job and the app may write at the same time:
          // wait up to 5 s for the other writer rather than failing.
          await customStatement('PRAGMA busy_timeout = 5000');
          // Idempotent: also repairs a database created before FTS existed.
          await _createSearchIndex();
        },
      );

  /// Full-text search tables + triggers (offline, diacritic-insensitive,
  /// prefix-capable). External-content FTS5 keeps the index small: it stores
  /// only the inverted index, not a second copy of the text.
  Future<void> _createSearchIndex() async {
    const tokenizer = "tokenize='unicode61 remove_diacritics 2'";

    await customStatement('''
CREATE VIRTUAL TABLE IF NOT EXISTS track_fts USING fts5(
  title, artist, album,
  content='tracks', content_rowid='rowid', $tokenizer, prefix='2 3'
)''');
    await customStatement('''
CREATE VIRTUAL TABLE IF NOT EXISTS album_fts USING fts5(
  name, artist,
  content='albums', content_rowid='rowid', $tokenizer, prefix='2 3'
)''');
    await customStatement('''
CREATE VIRTUAL TABLE IF NOT EXISTS artist_fts USING fts5(
  name,
  content='artists', content_rowid='rowid', $tokenizer, prefix='2 3'
)''');

    // Keep the indexes in sync. UPDATE triggers only fire when an indexed
    // value really changed, so metadata-neutral upserts stay cheap.
    await customStatement('''
CREATE TRIGGER IF NOT EXISTS tracks_fts_ai AFTER INSERT ON tracks BEGIN
  INSERT INTO track_fts(rowid, title, artist, album)
  VALUES (new.rowid, new.title, new.artist, new.album);
END''');
    await customStatement('''
CREATE TRIGGER IF NOT EXISTS tracks_fts_ad AFTER DELETE ON tracks BEGIN
  INSERT INTO track_fts(track_fts, rowid, title, artist, album)
  VALUES ('delete', old.rowid, old.title, old.artist, old.album);
END''');
    await customStatement('''
CREATE TRIGGER IF NOT EXISTS tracks_fts_au AFTER UPDATE ON tracks
WHEN old.title IS NOT new.title OR old.artist IS NOT new.artist
  OR old.album IS NOT new.album BEGIN
  INSERT INTO track_fts(track_fts, rowid, title, artist, album)
  VALUES ('delete', old.rowid, old.title, old.artist, old.album);
  INSERT INTO track_fts(rowid, title, artist, album)
  VALUES (new.rowid, new.title, new.artist, new.album);
END''');

    await customStatement('''
CREATE TRIGGER IF NOT EXISTS albums_fts_ai AFTER INSERT ON albums BEGIN
  INSERT INTO album_fts(rowid, name, artist)
  VALUES (new.rowid, new.name, new.artist);
END''');
    await customStatement('''
CREATE TRIGGER IF NOT EXISTS albums_fts_ad AFTER DELETE ON albums BEGIN
  INSERT INTO album_fts(album_fts, rowid, name, artist)
  VALUES ('delete', old.rowid, old.name, old.artist);
END''');
    await customStatement('''
CREATE TRIGGER IF NOT EXISTS albums_fts_au AFTER UPDATE ON albums
WHEN old.name IS NOT new.name OR old.artist IS NOT new.artist BEGIN
  INSERT INTO album_fts(album_fts, rowid, name, artist)
  VALUES ('delete', old.rowid, old.name, old.artist);
  INSERT INTO album_fts(rowid, name, artist)
  VALUES (new.rowid, new.name, new.artist);
END''');

    await customStatement('''
CREATE TRIGGER IF NOT EXISTS artists_fts_ai AFTER INSERT ON artists BEGIN
  INSERT INTO artist_fts(rowid, name) VALUES (new.rowid, new.name);
END''');
    await customStatement('''
CREATE TRIGGER IF NOT EXISTS artists_fts_ad AFTER DELETE ON artists BEGIN
  INSERT INTO artist_fts(artist_fts, rowid, name)
  VALUES ('delete', old.rowid, old.name);
END''');
    await customStatement('''
CREATE TRIGGER IF NOT EXISTS artists_fts_au AFTER UPDATE ON artists
WHEN old.name IS NOT new.name BEGIN
  INSERT INTO artist_fts(artist_fts, rowid, name)
  VALUES ('delete', old.rowid, old.name);
  INSERT INTO artist_fts(rowid, name) VALUES (new.rowid, new.name);
END''');
  }

  /// Rebuilds the FTS indexes from the content tables (maintenance / repair).
  Future<void> rebuildSearchIndex() async {
    await customStatement("INSERT INTO track_fts(track_fts) VALUES('rebuild')");
    await customStatement("INSERT INTO album_fts(album_fts) VALUES('rebuild')");
    await customStatement(
        "INSERT INTO artist_fts(artist_fts) VALUES('rebuild')");
  }
}
