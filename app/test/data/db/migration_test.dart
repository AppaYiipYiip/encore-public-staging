import 'package:drift/drift.dart' show driftRuntimeOptions;
import 'package:drift/native.dart';
import 'package:drift_dev/api/migrations_native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../generated_migrations/schema.dart';

/// Upgrading a database written by an older build must keep every row, and
/// the result must be exactly the schema the app expects (docs/23, B32).
///
/// The old test derived its fake "v1" from today's DDL and stripped columns by
/// hand, so a forgotten migration for any column nobody remembered to strip
/// still passed. These tests start from **frozen snapshots** of every version
/// (`drift_schemas/drift_schema_vN.json`, taken from the commits that
/// introduced them) and let drift compare the upgraded database with the
/// current snapshot: tables, columns and indexes.
///
/// When the schema changes: bump `schemaVersion`, add the migration step, then
///   dart run drift_dev schema dump lib/data/db/app_database.dart drift_schemas/
///   dart run drift_dev schema generate drift_schemas/ test/generated_migrations/
/// and these tests cover the new step without being edited.
void main() {
  driftRuntimeOptions.dontWarnAboutMultipleDatabases = true;

  late SchemaVerifier verifier;
  late int current;

  setUpAll(() async {
    verifier = SchemaVerifier(GeneratedHelper());
    final probe = AppDatabase(NativeDatabase.memory());
    current = probe.schemaVersion;
    await probe.close();
  });

  test('every shipped schema version has a frozen snapshot', () {
    expect(GeneratedHelper.versions.last, current,
        reason: 'schemaVersion was bumped without dumping a snapshot: run the '
            'two drift_dev commands in this file\'s header');
    expect(GeneratedHelper.versions, [
      for (var v = 1; v <= current; v++) v,
    ]);
  });

  // Every shipped version before the current one (v8 is in the list since N-39: its step to v9 adds the stopped mark of a pin; v9 since N-38: its step to v10 adds the
  // old-formula key a downloaded copy remembers, and v9 is the schema the phones have today).
  for (final from in const [1, 2, 3, 4, 5, 6, 7, 8, 9]) {
    test('v$from upgrades to the current schema and keeps its rows', () async {
      final schema = await verifier.schemaAt(from);

      // Rows that exist in every version's tables.
      schema.rawDatabase
        ..execute("INSERT INTO servers (name, username, endpoints_json, "
            "capabilities_json, created_at_ms) VALUES ('S', 'u', '[]', '{}', 0)")
        ..execute('INSERT INTO downloads (server_id, track_id, state, '
            "local_path, bytes, updated_at_ms) VALUES (1, 'old', 2, '/x/old', 99, 5)")
        ..execute('INSERT INTO outbox (server_id, kind, payload_json, '
            "created_at_ms) VALUES (1, 'star', '{}', 7)")
        // A download the person asked for before the upgrade (v9 gives it a stopped mark, empty).
        ..execute('INSERT INTO pins (server_id, target_type, target_id, '
            "created_at_ms) VALUES (1, 'playlist', 'p1', 9)")
        // One playlist whose songs were stored, one whose songs never were.
        ..execute('INSERT INTO playlists (server_id, id, name, song_count, '
            'changed_at_ms, entries_fetched_at_ms) '
            "VALUES (1, 'stored', 'Mine', 3, 1700000000000, 5)")
        ..execute('INSERT INTO playlists (server_id, id, name, song_count) '
            "VALUES (1, 'never', 'Empty', 9)");

      final db = AppDatabase(schema.newConnection());
      await verifier.migrateAndValidate(db, current);

      final downloads = await db.select(db.downloads).get();
      expect(downloads.single.trackId, 'old');
      expect(downloads.single.bytes, 99);
      expect(downloads.single.attempts, 0);
      expect(downloads.single.refreshQuality, isNull,
          reason: 'v8: a finished download has no refresh under way (P4-24)');
      expect(downloads.single.quality, 'original',
          reason:
              'the quality the copy was made at is not changed by the upgrade');
      expect(downloads.single.sourceLegacyKey, '',
          reason:
              'v10 (N-38): a copy made before remembers no old-formula key; the app treats that as nothing to compare');

      final pins = await db.select(db.pins).get();
      expect(pins.single.targetId, 'p1');
      expect(pins.single.stoppedAtMs, isNull,
          reason:
              'v9 (N-39): a download made before the upgrade is not stopped, so nothing that was coming is held back by the upgrade');
      expect(pins.single.createdAtMs, 9);

      final queued = await db.select(db.outbox).get();
      expect(queued.single.kind, 'star');
      expect(queued.single.createdAtMs, 7);
      expect(queued.single.serverErrors, 0,
          reason: 'an item queued before v5 starts with a clean count');

      // The stamp of the stored songs is backfilled from the metadata, so the
      // first sync after the upgrade does not refetch every playlist; a
      // playlist with no stored songs has no stamp and is fetched when seen.
      final lists = {
        for (final p in await db.select(db.playlists).get()) p.id: p,
      };
      expect(
          lists['stored']!.entriesStamp, from < 5 ? '1700000000000|3' : isNull,
          reason: 'only the step into v5 backfills the stamp');
      expect(lists['never']!.entriesStamp, isNull);

      // v6: songs as references. Nothing that exists is a ref until the app moves it, and the new columns start empty.
      final tracks = await db.select(db.tracks).get();
      expect(tracks.every((row) => !row.isRef && row.fileId == null), isTrue);
      await db.close();
    });
  }

  test('a fresh install has exactly the current schema', () async {
    final db = AppDatabase(NativeDatabase.memory());
    await verifier.migrateAndValidate(db, current);
    await db.close();
  });
}
