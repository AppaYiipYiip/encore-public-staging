import 'dart:math';

import 'package:drift/drift.dart';

import '../../core/clock.dart';
import '../db/app_database.dart';

/// A named, expiring lock kept in the database file (docs/23, B2).
///
/// Two engines in one app (the open screen and the WorkManager job) share one
/// SQLite file but not their memory, so "single flight" held in a Dart field
/// protected nothing between them. SQLite serialises writers across
/// connections, which makes the one statement below a true mutual exclusion:
/// it inserts the lease, or takes it over only when it has expired or already
/// belongs to this owner. A process that is killed simply stops renewing, and
/// the lease frees itself when its time is up.
class DbLease {
  DbLease(this._db, {Clock clock = const SystemClock(), String? owner})
      : _clock = clock,
        owner = owner ?? _newOwner();

  final AppDatabase _db;
  final Clock _clock;

  /// Identifies this engine instance (random, new per instance).
  final String owner;

  /// Takes [name] for [ttl], or extends it when this owner already holds it.
  /// `false` when someone else holds it and it has not expired.
  Future<bool> tryAcquire(
    String name, {
    Duration ttl = const Duration(seconds: 60),
  }) async {
    final now = _clock.now().millisecondsSinceEpoch;
    final changed = await _db.customUpdate(
      'INSERT INTO leases (name, owner, until_ms) VALUES (?1, ?2, ?3) '
      'ON CONFLICT(name) DO UPDATE SET owner = excluded.owner, '
      'until_ms = excluded.until_ms '
      'WHERE leases.until_ms < ?4 OR leases.owner = excluded.owner',
      variables: [
        Variable<String>(name),
        Variable<String>(owner),
        Variable<int>(now + ttl.inMilliseconds),
        Variable<int>(now),
      ],
      updates: {_db.leases},
      updateKind: UpdateKind.insert,
    );
    return changed > 0;
  }

  /// Gives [name] back, but only if this owner still holds it.
  Future<void> release(String name) async {
    await (_db.delete(_db.leases)
          ..where((l) => l.name.equals(name) & l.owner.equals(owner)))
        .go();
  }

  static String _newOwner() {
    final random = Random.secure();
    return List.generate(
      16,
      (_) => random.nextInt(16).toRadixString(16),
    ).join();
  }
}
