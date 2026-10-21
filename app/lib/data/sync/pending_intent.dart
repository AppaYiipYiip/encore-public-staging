import 'dart:convert';

import 'package:drift/drift.dart';

import '../db/app_database.dart';
import 'outbox.dart';

/// Ids with a like or unlike that is still waiting in the outbox.
///
/// The server's view of those ids is older than the person's intent, so no
/// sync phase may write the server's star state over them (docs/23, B7). Parked
/// (failed) edits are not included: once an edit was turned down, the server's
/// truth should show.
Future<Set<String>> pendingStarTargets(AppDatabase db, int serverId) async {
  final rows = await (db.select(db.outbox)
        ..where((o) =>
            o.serverId.equals(serverId) &
            o.status.equals('pending') &
            (o.kind.equals(OutboxKind.star) |
                o.kind.equals(OutboxKind.unstar))))
      .get();
  final ids = <String>{};
  for (final row in rows) {
    final Object? payload;
    try {
      payload = jsonDecode(row.payloadJson);
    } on FormatException {
      continue; // damaged: parked when its turn comes (B3), protects nothing
    }
    if (payload is! Map) continue;
    for (final key in const ['songIds', 'albumIds', 'artistIds']) {
      final list = payload[key];
      if (list is List) ids.addAll(list.map((e) => e.toString()));
    }
  }
  return ids;
}

/// Edits of this account that have not reached the server: waiting, or turned
/// down. Signing out deletes them, so the person is told how many (B31).
Future<int> unsentEditCount(AppDatabase db, int serverId) async {
  final count = db.outbox.id.count();
  final query = db.selectOnly(db.outbox)
    ..addColumns([count])
    ..where(db.outbox.serverId.equals(serverId));
  return (await query.getSingle()).read(count) ?? 0;
}
