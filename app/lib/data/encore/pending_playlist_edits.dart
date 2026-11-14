import 'dart:convert';

import 'package:drift/drift.dart';

import '../db/app_database.dart';
import 'encore_mutations.dart' show EncoreOutboxKind;

/// The playlist edits of an Encore server that are still waiting in the outbox (P2-28, AUDIT B-61): what a pull must not write the server's older
/// value over (docs/34, section 1, rule 5). Parked (failed) edits are not included, as for likes: once an edit was turned down, the server's
/// truth should show.
class PendingPlaylistEdits {
  const PendingPlaylistEdits({
    this.renamed = const {},
    this.deleted = const {},
    this.removedEntries = const {},
  });

  /// Playlists with a rename waiting (the person's name is on the screen and not sent yet).
  final Set<String> renamed;

  /// Playlists with a delete waiting (the playlist is gone from the screen, the server still has it).
  final Set<String> deleted;

  /// Entry ids (`pe_...`) with a removal waiting. Exact, by the entry's own id: never matched by song.
  final Set<String> removedEntries;

  bool get isEmpty =>
      renamed.isEmpty && deleted.isEmpty && removedEntries.isEmpty;
}

Future<PendingPlaylistEdits> pendingPlaylistEdits(
    AppDatabase db, int serverId) async {
  final rows = await (db.select(db.outbox)
        ..where((o) =>
            o.serverId.equals(serverId) &
            o.status.equals('pending') &
            o.kind.isIn(const [
              EncoreOutboxKind.playlistRename,
              EncoreOutboxKind.playlistDelete,
              EncoreOutboxKind.playlistRemove,
            ])))
      .get();
  final renamed = <String>{};
  final deleted = <String>{};
  final removed = <String>{};
  for (final row in rows) {
    final Object? payload;
    try {
      payload = jsonDecode(row.payloadJson);
    } on FormatException {
      continue; // damaged: parked when its turn comes (B3), protects nothing
    }
    if (payload is! Map) continue;
    switch (row.kind) {
      case EncoreOutboxKind.playlistRename:
        final id = payload['playlistId'];
        if (id is String) renamed.add(id);
      case EncoreOutboxKind.playlistDelete:
        final id = payload['id'];
        if (id is String) deleted.add(id);
      case EncoreOutboxKind.playlistRemove:
        final ids = payload['entryIds'];
        if (ids is List) removed.addAll(ids.map((e) => e.toString()));
    }
  }
  return PendingPlaylistEdits(
      renamed: renamed, deleted: deleted, removedEntries: removed);
}
