import 'dart:async';
import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:meta/meta.dart';

import '../db/app_database.dart';
import 'outbox.dart';

/// One queued edit the server turned down, described for a person.
@immutable
class FailedEdit {
  const FailedEdit({
    required this.id,
    required this.what,
    required this.why,
    required this.createdAtMs,
  });

  final int id;

  /// "Add songs to a playlist", "Like", ... (never a kind code).
  final String what;

  /// The server's own reason, or a plain fallback.
  final String why;
  final int createdAtMs;
}

/// What the person can do about edits that could not be saved (docs/23, B1).
///
/// Before this existed a parked item was invisible: the edit stayed on the
/// phone, the server never got it, and the next sync quietly undid it.
class OutboxFailures {
  OutboxFailures({
    required AppDatabase db,
    required this.serverId,
    Future<void> Function()? flush,
    Future<void> Function()? refresh,
  })  : _db = db,
        _flush = flush,
        _refresh = refresh;

  final AppDatabase _db;
  final int serverId;

  /// Delivers the queue now (after a retry).
  final Future<void> Function()? _flush;

  /// Re-reads the server's truth (after a discard, so the screen stops showing
  /// a change the server never accepted).
  final Future<void> Function()? _refresh;

  /// The parked edits of this account, oldest first.
  Stream<List<FailedEdit>> watch() {
    final query = _db.select(_db.outbox)
      ..where((o) => o.serverId.equals(serverId) & o.status.equals('failed'))
      ..orderBy([(o) => OrderingTerm.asc(o.id)]);
    return query.watch().map((rows) => [
          for (final r in rows)
            FailedEdit(
              id: r.id,
              what: describeEdit(r),
              why: r.lastError ?? 'The server turned it down.',
              createdAtMs: r.createdAtMs,
            ),
        ]);
  }

  /// Puts one parked edit back in the queue with a clean count. It keeps its
  /// place in the order (the queue is ordered by id), so edits that depend on
  /// each other are still delivered in the order they were made.
  Future<void> retry(int id) async {
    await _requeue((o) => o.id.equals(id));
    await _flush?.call();
  }

  Future<void> retryAll() async {
    await _requeue((o) => const Constant(true));
    await _flush?.call();
  }

  /// Forgets a parked edit.
  Future<void> discard(int id) async {
    await (_db.delete(_db.outbox)
          ..where((o) =>
              o.serverId.equals(serverId) &
              o.status.equals('failed') &
              o.id.equals(id)))
        .go();
    await _refresh?.call();
  }

  Future<void> _requeue(Expression<bool> Function($OutboxTable o) which) {
    return (_db.update(_db.outbox)
          ..where((o) =>
              o.serverId.equals(serverId) &
              o.status.equals('failed') &
              which(o)))
        .write(const OutboxCompanion(
      status: Value('pending'),
      attempts: Value(0),
      serverErrors: Value(0),
      nextAttemptAtMs: Value(0),
      lastError: Value(null),
    ));
  }

  /// A queued edit in words a person knows, without internal kind codes.
  static String describeEdit(OutboxRow row) {
    final p = _payload(row.payloadJson);
    int count(String key) => (p?[key] is List) ? (p![key] as List).length : 0;
    switch (row.kind) {
      case OutboxKind.star:
        return 'Like';
      case OutboxKind.unstar:
        return 'Remove a like';
      case OutboxKind.rating:
        return 'A star rating';
      case OutboxKind.scrobble:
        return 'A play for your history';
      case OutboxKind.playlistCreate:
        final name = p?['name'];
        return name is String && name.isNotEmpty
            ? 'Create the playlist "$name"'
            : 'Create a playlist';
      case OutboxKind.playlistUpdate:
        if (p?['name'] is String) return 'Rename a playlist';
        if (count('add') > 0) return 'Add songs to a playlist';
        if (count('removeIds') > 0 || count('removeIdx') > 0) {
          return 'Remove songs from a playlist';
        }
        if (p?['comment'] is String) return 'Change a playlist description';
        return 'Change a playlist';
      case OutboxKind.playlistDelete:
        return 'Delete a playlist';
      default:
        return 'A change';
    }
  }

  static Map<String, dynamic>? _payload(String json) {
    try {
      final decoded = jsonDecode(json);
      return decoded is Map ? decoded.cast<String, dynamic>() : null;
    } on FormatException {
      return null; // a damaged payload still gets a generic label
    }
  }
}
