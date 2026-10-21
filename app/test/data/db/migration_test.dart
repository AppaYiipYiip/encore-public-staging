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

  for (final from in const [1, 2, 3, 4]) {
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
      expect(lists['stored']!.entriesStamp, '1700000000000|3');
      expect(lists['never']!.entriesStamp, isNull);
      await db.close();
    });
  }

  test('a fresh install has exactly the current schema', () async {
    final db = AppDatabase(NativeDatabase.memory());
    await verifier.migrateAndValidate(db, current);
    await db.close();
  });
}
