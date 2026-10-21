import 'package:drift/drift.dart';

import '../db/app_database.dart';

/// Typed access to the per-server key/value `sync_state` table.
class SyncStateStore {
  SyncStateStore(this._db, this.serverId);

  final AppDatabase _db;
  final int serverId;

  static const lastScanMs = 'lastScanMs';
  static const lastScanCount = 'lastScanCount';
  static const lastFullSyncAtMs = 'lastFullSyncAtMs';
  static const lastRunId = 'lastRunId';
  static const lastRunAtMs = 'lastRunAtMs';
  static const lastError = 'lastError';
  static const lastPlaylistsAtMs = 'lastPlaylistsAtMs';

  /// The shrink guard's memory (docs/23, B6): the last answer that looked far
  /// too small (`tracks|albums|artists`), how many runs in a row gave exactly
  /// that, and the sentence shown to the person while the guard holds.
  static const shrinkAnswer = 'shrinkAnswer';
  static const shrinkRuns = 'shrinkRuns';
  static const shrinkNotice = 'shrinkNotice';

  /// When the periodic background job last finished a pass, and how it
  /// ended (`ok` or a short reason), so Settings can show it.
  static const lastBackgroundRunAtMs = 'lastBackgroundRunAtMs';
  static const lastBackgroundResult = 'lastBackgroundResult';

  Future<String?> get(String key) async {
    final row = await (_db.select(_db.syncState)
          ..where((s) => s.serverId.equals(serverId) & s.key.equals(key)))
        .getSingleOrNull();
    return row?.value;
  }

  /// The value of [key] as it changes (`null` while unset).
  Stream<String?> watch(String key) => (_db.select(_db.syncState)
        ..where((s) => s.serverId.equals(serverId) & s.key.equals(key)))
      .watchSingleOrNull()
      .map((row) => row?.value);

  Future<int?> getInt(String key) async {
    final v = await get(key);
    return v == null ? null : int.tryParse(v);
  }

  Future<void> set(String key, String? value) async {
    if (value == null) {
      await (_db.delete(_db.syncState)
            ..where((s) => s.serverId.equals(serverId) & s.key.equals(key)))
          .go();
      return;
    }
    await _db.into(_db.syncState).insertOnConflictUpdate(
          SyncStateCompanion.insert(
            serverId: serverId,
            key: key,
            value: value,
          ),
        );
  }

  Future<void> setInt(String key, int? value) => set(key, value?.toString());

  Future<Map<String, String>> all() async {
    final rows = await (_db.select(_db.syncState)
          ..where((s) => s.serverId.equals(serverId)))
        .get();
    return {for (final r in rows) r.key: r.value};
  }
}
