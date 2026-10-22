import 'dart:convert';

import 'package:drift/drift.dart';

import '../../core/logger.dart';
import '../../core/result.dart';
import '../db/app_database.dart';
import '../sync/sync_state_store.dart';
import 'encore_api.dart';
import 'encore_sync.dart';

/// What an upgrade did, in numbers (shown once, and in the log).
class UpgradeReport {
  const UpgradeReport({
    this.songsMoved = 0,
    this.songsResolved = 0,
    this.songsDropped = 0,
    this.playlistsReplaced = 0,
    this.likesOnServer = 0,
    this.playlistsOnServer = 0,
  });

  /// Songs whose id on the phone became the server's ref id.
  final int songsMoved;

  /// Songs the server did not know by their file, found by name instead.
  final int songsResolved;

  /// Songs nothing of the person's pointed at and the server has no file of, forgotten.
  final int songsDropped;
  final int playlistsReplaced;
  final int likesOnServer;
  final int playlistsOnServer;

  @override
  String toString() =>
      'moved $songsMoved songs (+$songsResolved by name, $songsDropped dropped), $playlistsReplaced playlists, server now has $likesOnServer likes and $playlistsOnServer playlists';
}

/// Moves a phone that has been talking to a plain music server onto an Encore server, once (docs/18 section 4), keeping everything: the likes,
/// the playlists, the downloads, the history, the saved queue.
///
/// Before: every song is keyed by the music server's id. After: by the Encore server's **ref** id (same on every device), and the music
/// server's id is only where the file is. The steps are written so that stopping in the middle (the app is killed, the line drops) and
/// running again is safe; the person's own work is never deleted until the new copy of it is in place.
///
/// 1. nothing may be waiting to be sent the old way (it would name ids that are about to change);
/// 2. the Encore server reads the person's stars and playlists from the music server as them and keeps them (`POST /migrate/navidrome`);
/// 3. the server's list of files says which ref each music-server id became;
/// 4. every row of the phone that names a song is moved to that ref id: the songs, playlist entries, downloads, history, lyrics, single-song
///    pins and the saved queue; a song the server did not know by its file is found by what it is called;
/// 5. the person's library is pulled; the old playlists are replaced by the server's (the pins on them move too).
class EncoreUpgrade {
  EncoreUpgrade({
    required AppDatabase db,
    required EncoreApi api,
    required this.serverId,
    required String ownerName,
    required this.pendingEdits,
  })  : _db = db,
        _api = api,
        _sync = EncoreSync(
            db: db, api: api, serverId: serverId, ownerName: ownerName),
        _state = SyncStateStore(db, serverId);

  final AppDatabase _db;
  final EncoreApi _api;
  final EncoreSync _sync;
  final SyncStateStore _state;
  final int serverId;

  /// How many edits still wait to be sent the old way (after one more try to send them).
  final Future<int> Function() pendingEdits;

  static const doneKey = 'encoreUpgradeDone';

  Future<bool> isDone() async => (await _state.get(doneKey)) == '1';

  Future<Result<UpgradeReport>> run({void Function(String step)? onStep}) =>
      guard(() async {
        onStep?.call('Checking that nothing is waiting to be sent');
        if (await pendingEdits() > 0) {
          throw const NetworkFailure(
              'Some of your changes have not reached the server yet. Connect and try again.');
        }

        onStep?.call('Bringing your likes and playlists over');
        final migrated = (await _api.migrateFromNavidrome()).getOrThrow();

        onStep?.call('Matching your songs');
        final map = await _fileMap();
        final fileIds = map.keys
            .toSet(); // these ids are the music server's own: they stay as the file of the song
        final resolved = await _resolveUnmapped(map);

        onStep?.call('Updating this phone');
        final moved = await _rekey(map, fileIds);
        final dropped = await _dropUnused();

        onStep?.call('Getting your library');
        await _sync.reset();
        (await _sync.pull()).getOrThrow();
        final replaced = await _replaceLegacyPlaylists();

        await _state.set(doneKey, '1');
        final report = UpgradeReport(
          songsMoved: moved,
          songsResolved: resolved,
          songsDropped: dropped,
          playlistsReplaced: replaced,
          likesOnServer: migrated.likes,
          playlistsOnServer: migrated.playlists,
        );
        Log.info('encore-upgrade', '$report');
        return report;
      });

  // ------------------------------------------------------------------ 3: which ref each music-server id became

  /// The music server's song id -> the ref that file is attached to, from the server's whole list of files.
  Future<Map<String, String>> _fileMap() async {
    final map = <String, String>{};
    var cursor = '0';
    while (true) {
      final page = (await _api.files(since: cursor, limit: 500)).getOrThrow();
      for (final ref in page.refs) {
        final id = ref.file?.navidromeSongId;
        if (id != null) map[id] = ref.id;
      }
      final moved = page.cursor != cursor;
      cursor = page.cursor;
      if (!page.more || !moved) break;
    }
    return map;
  }

  // ------------------------------------------------------------------ the songs the server did not know by their file

  /// Songs of the phone that the person uses (a like, a playlist, a download, a listening) and the server has no file for: found by name.
  Future<int> _resolveUnmapped(Map<String, String> map) async {
    final rows = await _db.customSelect(
      'SELECT t.id AS id, t.title AS title, t.artist AS artist, t.album AS album, t.duration_sec AS duration, t.isrc AS isrc, '
      't.music_brainz_id AS mbid, t.track_no AS track_no, t.year AS year FROM tracks t WHERE t.server_id = ?1 AND t.is_ref = 0 '
      'AND t.deleted_at_ms IS NULL AND (t.starred_at_ms IS NOT NULL '
      'OR EXISTS (SELECT 1 FROM playlist_entries e WHERE e.server_id = t.server_id AND e.track_id = t.id) '
      'OR EXISTS (SELECT 1 FROM downloads d WHERE d.server_id = t.server_id AND d.track_id = t.id) '
      'OR EXISTS (SELECT 1 FROM play_history h WHERE h.server_id = t.server_id AND h.track_id = t.id))',
      variables: [Variable<int>(serverId)],
      readsFrom: {
        _db.tracks,
        _db.playlistEntries,
        _db.downloads,
        _db.playHistory
      },
    ).get();
    final loose = [
      for (final r in rows)
        if (!map.containsKey(r.read<String>('id'))) r
    ];
    var found = 0;
    for (var i = 0; i < loose.length; i += 400) {
      final chunk =
          loose.sublist(i, i + 400 > loose.length ? loose.length : i + 400);
      final answered = (await _api.resolve([
        for (final r in chunk)
          {
            'title': r.read<String>('title'),
            'artists': [r.readNullable<String>('artist') ?? ''],
            'album': r.readNullable<String>('album'),
            if (r.readNullable<int>('duration') != null)
              'durationMs': r.read<int>('duration') * 1000,
            'isrc': r.readNullable<String>('isrc'),
            'mbid': r.readNullable<String>('mbid'),
            'trackNo': r.readNullable<int>('track_no'),
            'year': r.readNullable<int>('year'),
          },
      ]))
          .getOrThrow();
      for (var k = 0; k < chunk.length && k < answered.length; k++) {
        map[chunk[k].read<String>('id')] = answered[k].id;
        found++;
      }
    }
    return found;
  }

  // ------------------------------------------------------------------ 4: moving every row to the ref id

  Future<int> _rekey(Map<String, String> map, Set<String> fileIds) async {
    if (map.isEmpty) return 0;
    var moved = 0;
    await _db.transaction(() async {
      await _db.customStatement(
          'CREATE TEMP TABLE IF NOT EXISTS encore_idmap (old TEXT PRIMARY KEY, new TEXT NOT NULL, keep INTEGER NOT NULL DEFAULT 1, file INTEGER NOT NULL DEFAULT 1)');
      await _db.customStatement('DELETE FROM encore_idmap');
      await _db.batch((b) {
        for (final e in map.entries) {
          b.customStatement(
              'INSERT OR REPLACE INTO encore_idmap (old, new, file) VALUES (?, ?, ?)',
              [e.key, e.value, fileIds.contains(e.key) ? 1 : 0]);
        }
      });
      // Only songs the phone has: the rest of the map is for the server's own pull.
      await _db.customStatement(
          'DELETE FROM encore_idmap WHERE old NOT IN (SELECT id FROM tracks WHERE server_id = $serverId AND is_ref = 0)');
      // Two music-server songs that are one recording share a ref: one of them leads (the one with a download, a like or the smallest id).
      await _db.customStatement('''
UPDATE encore_idmap SET keep = 0 WHERE old != (
  SELECT m2.old FROM encore_idmap m2 JOIN tracks t ON t.server_id = $serverId AND t.id = m2.old
  WHERE m2.new = encore_idmap.new
  ORDER BY (EXISTS (SELECT 1 FROM downloads d WHERE d.server_id = $serverId AND d.track_id = m2.old AND d.state = 2)) DESC,
           (t.starred_at_ms IS NOT NULL) DESC, m2.old LIMIT 1)''');
      final count = await _db
          .customSelect('SELECT COUNT(*) AS n FROM encore_idmap')
          .getSingle();
      moved = count.read<int>('n');

      Future<void> pointAt(String table, String column, {String extra = ''}) =>
          _db.customStatement(
            'UPDATE OR IGNORE $table SET $column = (SELECT new FROM encore_idmap WHERE old = $table.$column) '
            'WHERE server_id = $serverId AND $column IN (SELECT old FROM encore_idmap) $extra',
          );
      // Everything that names a song, to the ref (rows that would collide with the leading song's own are left, and removed below).
      await pointAt('playlist_entries', 'track_id');
      await pointAt('downloads', 'track_id');
      await pointAt('play_history', 'track_id');
      await pointAt('lyrics', 'track_id');
      await pointAt('pins', 'target_id', extra: "AND target_type = 'track'");
      for (final table in const ['downloads', 'lyrics']) {
        await _db.customStatement(
            'DELETE FROM $table WHERE server_id = $serverId AND track_id IN (SELECT old FROM encore_idmap)');
      }
      await _db.customStatement(
          "DELETE FROM pins WHERE server_id = $serverId AND target_type = 'track' AND target_id IN (SELECT old FROM encore_idmap)");
      // The songs themselves: the leading row of each ref takes the ref's id and remembers the music server's id as its file.
      await _db.customStatement(
        'UPDATE OR IGNORE tracks SET id = (SELECT new FROM encore_idmap WHERE old = tracks.id), is_ref = 1, file_id = CASE WHEN (SELECT file FROM encore_idmap WHERE old = tracks.id) = 1 THEN tracks.id END '
        'WHERE server_id = $serverId AND id IN (SELECT old FROM encore_idmap WHERE keep = 1)',
      );
      await _db.customStatement(
          'DELETE FROM tracks WHERE server_id = $serverId AND is_ref = 0 AND id IN (SELECT old FROM encore_idmap)');
      await _rekeyQueue(map);
      await _db.customStatement('DROP TABLE IF EXISTS encore_idmap');
    });
    return moved;
  }

  /// The saved queue names songs too: they are moved to their refs, so what was playing is still there after the upgrade.
  Future<void> _rekeyQueue(Map<String, String> map) async {
    const key = 'playback.state';
    final raw = await _state.get(key);
    if (raw == null) return;
    Object? walk(Object? node) {
      if (node is String) return map[node] ?? node;
      if (node is List) return [for (final v in node) walk(v)];
      if (node is Map) {
        return {for (final e in node.entries) e.key: walk(e.value)};
      }
      return node;
    }

    try {
      await _state.set(key, jsonEncode(walk(jsonDecode(raw))));
    } on FormatException {
      await _state.set(key, null); // a damaged snapshot is not worth keeping
    }
  }

  /// Rows of the music server's old kind that nothing of the person's points at: the server's own pull brings back what exists.
  Future<int> _dropUnused() async {
    final before = await _db.customSelect(
        'SELECT COUNT(*) AS n FROM tracks WHERE server_id = ?1 AND is_ref = 0',
        variables: [Variable<int>(serverId)]).getSingle();
    await _db.customStatement(
        'DELETE FROM tracks WHERE server_id = $serverId AND is_ref = 0');
    return before.read<int>('n');
  }

  // ------------------------------------------------------------------ 5: the playlists

  /// After the server's playlists arrived: the old ones go, and what pointed at an old playlist (a download pin) points at its replacement.
  Future<int> _replaceLegacyPlaylists() async {
    final fresh = <String,
        String>{}; // the music server's playlist id -> the Encore playlist id
    final response = await _api.changes(since: '0');
    for (final p in response.getOrThrow().playlists) {
      final source = p.sourceId;
      if (source != null && source.startsWith('nd:')) {
        fresh[source.substring(3)] = p.id;
      }
    }
    var replaced = 0;
    await _db.transaction(() async {
      // Playlists of the old kind: their ids are the music server's, not `pl_...`.
      final old = await _db.customSelect(
        "SELECT id FROM playlists WHERE server_id = ?1 AND id NOT GLOB 'pl_*'",
        variables: [Variable<int>(serverId)],
        readsFrom: {_db.playlists},
      ).get();
      for (final row in old) {
        final id = row.read<String>('id');
        final replacement = fresh[id];
        if (replacement != null) {
          await _db.customStatement(
            "UPDATE OR IGNORE pins SET target_id = ? WHERE server_id = ? AND target_type = 'playlist' AND target_id = ?",
            [replacement, serverId, id],
          );
          replaced++;
        }
        await (_db.delete(_db.playlistEntries)
              ..where(
                  (e) => e.serverId.equals(serverId) & e.playlistId.equals(id)))
            .go();
        await (_db.delete(_db.playlists)
              ..where((t) => t.serverId.equals(serverId) & t.id.equals(id)))
            .go();
      }
      await (_db.delete(_db.playlistAliases)
            ..where((a) => a.serverId.equals(serverId)))
          .go();
      await _db.customStatement(
        "DELETE FROM pins WHERE server_id = ? AND target_type = 'playlist' AND target_id NOT GLOB 'pl_*'",
        [serverId],
      );
    });
    return replaced;
  }
}
