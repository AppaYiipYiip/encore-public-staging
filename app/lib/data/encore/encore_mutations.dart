import 'dart:convert';

import 'package:drift/drift.dart';

import '../../core/client_id.dart';
import '../../core/clock.dart';
import '../db/app_database.dart';
import '../sync/playlist_mutations.dart';

/// The outbox kinds of an Encore server's playlist edits. Every one names the things it touches by ids the phone made (`pl_`, `pe_`), so
/// delivering it twice is the same as once, and no id ever has to be swapped for one the server made.
abstract final class EncoreOutboxKind {
  /// `{ "id": "pl_...", "name": "...", "entries": [{ "ref": "sr_...", "id": "pe_..." }] }`
  static const playlistCreate = 'e.playlist.create';

  /// `{ "playlistId": "pl_...", "entries": [{ "ref": "sr_...", "id": "pe_..." }] }`
  static const playlistAdd = 'e.playlist.add';

  /// `{ "playlistId": "pl_...", "entryIds": ["pe_..."] }`
  static const playlistRemove = 'e.playlist.remove';

  /// `{ "playlistId": "pl_...", "name": "..." }`
  static const playlistRename = 'e.playlist.rename';

  /// `{ "id": "pl_..." }`
  static const playlistDelete = 'e.playlist.delete';

  static bool isEncore(String kind) => kind.startsWith('e.');
}

/// Local-first playlist editing against an Encore server: the same five operations as [PlaylistMutations], simpler, because the ids are the
/// phone's own from the first moment (docs/17 section 5). The local database changes first, the outbox delivers in order.
class EncorePlaylistEditor implements PlaylistEditor {
  EncorePlaylistEditor({
    required AppDatabase db,
    required this.serverId,
    Clock clock = const SystemClock(),
    this.ownerName,
    void Function()? onQueued,
  })  : _db = db,
        _clock = clock,
        _onQueued = onQueued;

  final AppDatabase _db;
  final Clock _clock;
  final int serverId;
  final String? ownerName;
  final void Function()? _onQueued;

  @override
  Future<String> create(String name, {List<String> trackIds = const []}) async {
    final nowMs = _clock.now().millisecondsSinceEpoch;
    final id = newClientId('pl', atMs: nowMs);
    final title = name.trim().isEmpty ? 'New playlist' : name.trim();
    final entries = [
      for (final t in trackIds) (ref: t, id: newClientId('pe', atMs: nowMs))
    ];
    await _db.transaction(() async {
      final seconds = await _durationOf(trackIds);
      await _db.into(_db.playlists).insert(PlaylistsCompanion.insert(
            serverId: serverId,
            id: id,
            name: title,
            owner: Value(ownerName),
            songCount: Value(entries.length),
            durationSec: Value(seconds),
            createdAtMs: Value(nowMs),
            changedAtMs: Value(nowMs),
            entriesFetchedAtMs: Value(nowMs),
          ));
      if (entries.isNotEmpty) {
        await _db.batch((b) => b.insertAll(_db.playlistEntries, [
              for (var i = 0; i < entries.length; i++)
                PlaylistEntriesCompanion.insert(
                  serverId: serverId,
                  playlistId: id,
                  position: i,
                  trackId: entries[i].ref,
                  entryId: Value(entries[i].id),
                  serverPosition: Value(i + 1.0),
                ),
            ]));
      }
      await _enqueue(EncoreOutboxKind.playlistCreate, {
        'id': id,
        'name': title,
        'entries': [
          for (final e in entries) {'ref': e.ref, 'id': e.id}
        ],
      });
    });
    _onQueued?.call();
    return id;
  }

  @override
  Future<bool> addTracks(String playlistId, List<String> trackIds) async {
    if (trackIds.isEmpty) return true;
    if (!await _editable(playlistId)) return false;
    final nowMs = _clock.now().millisecondsSinceEpoch;
    final entries = [
      for (final t in trackIds) (ref: t, id: newClientId('pe', atMs: nowMs))
    ];
    await _db.transaction(() async {
      final last = await _db.customSelect(
        'SELECT COALESCE(MAX(position), -1) AS p, COALESCE(MAX(server_position), 0) AS s '
        'FROM playlist_entries WHERE server_id = ?1 AND playlist_id = ?2',
        variables: [Variable<int>(serverId), Variable<String>(playlistId)],
        readsFrom: {_db.playlistEntries},
      ).getSingle();
      final maxPosition = last.read<int>('p');
      final maxServer = last.read<double>('s');
      await _db.batch((b) => b.insertAll(_db.playlistEntries, [
            for (var i = 0; i < entries.length; i++)
              PlaylistEntriesCompanion.insert(
                serverId: serverId,
                playlistId: playlistId,
                position: maxPosition + 1 + i,
                trackId: entries[i].ref,
                entryId: Value(entries[i].id),
                serverPosition: Value(maxServer + 1 + i),
              ),
          ]));
      await _touch(playlistId,
          countDelta: entries.length,
          durationDelta: await _durationOf(trackIds));
      await _enqueue(EncoreOutboxKind.playlistAdd, {
        'playlistId': playlistId,
        'entries': [
          for (final e in entries) {'ref': e.ref, 'id': e.id}
        ],
      });
    });
    _onQueued?.call();
    return true;
  }

  @override
  Future<bool> removeAt(String playlistId, int position) async {
    if (!await _editable(playlistId)) return false;
    final removed = await _db.transaction<bool>(() async {
      final entry = await (_db.select(_db.playlistEntries)
            ..where((e) =>
                e.serverId.equals(serverId) &
                e.playlistId.equals(playlistId) &
                e.position.equals(position)))
          .getSingleOrNull();
      final entryId = entry?.entryId;
      if (entry == null || entryId == null) return false;
      final seconds = await _durationOf([entry.trackId]);
      await (_db.delete(_db.playlistEntries)
            ..where((e) =>
                e.serverId.equals(serverId) &
                e.playlistId.equals(playlistId) &
                e.position.equals(position)))
          .go();
      // Close the gap in two steps so no intermediate state collides on the (playlist, position) key.
      await _db.customUpdate(
        'UPDATE playlist_entries SET position = -position WHERE server_id = ?1 AND playlist_id = ?2 AND position > ?3',
        variables: [
          Variable<int>(serverId),
          Variable<String>(playlistId),
          Variable<int>(position)
        ],
        updates: {_db.playlistEntries},
        updateKind: UpdateKind.update,
      );
      await _db.customUpdate(
        'UPDATE playlist_entries SET position = -position - 1 WHERE server_id = ?1 AND playlist_id = ?2 AND position < 0',
        variables: [Variable<int>(serverId), Variable<String>(playlistId)],
        updates: {_db.playlistEntries},
        updateKind: UpdateKind.update,
      );
      await _touch(playlistId, countDelta: -1, durationDelta: -seconds);
      await _enqueue(EncoreOutboxKind.playlistRemove, {
        'playlistId': playlistId,
        'entryIds': [entryId],
      });
      return true;
    });
    if (removed) _onQueued?.call();
    return removed;
  }

  @override
  Future<bool> rename(String playlistId, String name) async {
    final title = name.trim();
    if (title.isEmpty || !await _editable(playlistId)) return false;
    await _db.transaction(() async {
      await (_db.update(_db.playlists)
            ..where(
                (p) => p.serverId.equals(serverId) & p.id.equals(playlistId)))
          .write(PlaylistsCompanion(name: Value(title)));
      await _enqueue(EncoreOutboxKind.playlistRename,
          {'playlistId': playlistId, 'name': title});
    });
    _onQueued?.call();
    return true;
  }

  @override
  Future<void> delete(String playlistId) async {
    await _db.transaction(() async {
      await (_db.delete(_db.pins)
            ..where((p) =>
                p.serverId.equals(serverId) &
                p.targetType.equals('playlist') &
                p.targetId.equals(playlistId)))
          .go();
      await (_db.update(_db.playlists)
            ..where(
                (p) => p.serverId.equals(serverId) & p.id.equals(playlistId)))
          .write(PlaylistsCompanion(
              deletedAtMs: Value(_clock.now().millisecondsSinceEpoch)));
      await _enqueue(EncoreOutboxKind.playlistDelete, {'id': playlistId});
    });
    _onQueued?.call();
  }

  // ------------------------------------------------------------------ helpers

  /// A playlist of this person that is not deleted (the server makes no playlists of its own for a person to leave alone).
  Future<bool> _editable(String playlistId) async {
    final row = await (_db.select(_db.playlists)
          ..where((p) => p.serverId.equals(serverId) & p.id.equals(playlistId)))
        .getSingleOrNull();
    return row != null && row.deletedAtMs == null && !row.readonly;
  }

  Future<int> _durationOf(List<String> trackIds) async {
    if (trackIds.isEmpty) return 0;
    final rows = await (_db.select(_db.tracks)
          ..where((t) => t.serverId.equals(serverId) & t.id.isIn(trackIds)))
        .get();
    final byId = {for (final r in rows) r.id: r.durationSec ?? 0};
    return trackIds.fold<int>(0, (sum, id) => sum + (byId[id] ?? 0));
  }

  Future<void> _touch(String playlistId,
          {required int countDelta, required int durationDelta}) =>
      _db.customUpdate(
        'UPDATE playlists SET song_count = MAX(0, song_count + ?3), duration_sec = MAX(0, duration_sec + ?4), changed_at_ms = ?5 '
        'WHERE server_id = ?1 AND id = ?2',
        variables: [
          Variable<int>(serverId),
          Variable<String>(playlistId),
          Variable<int>(countDelta),
          Variable<int>(durationDelta),
          Variable<int>(_clock.now().millisecondsSinceEpoch),
        ],
        updates: {_db.playlists},
        updateKind: UpdateKind.update,
      );

  Future<void> _enqueue(String kind, Map<String, Object?> payload) =>
      _db.into(_db.outbox).insert(OutboxCompanion.insert(
            serverId: serverId,
            kind: kind,
            payloadJson: jsonEncode(payload),
            createdAtMs: _clock.now().millisecondsSinceEpoch,
          ));
}
