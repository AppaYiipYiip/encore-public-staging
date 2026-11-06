import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart';

import '../../core/clock.dart';
import '../../domain/audio_quality.dart';
import '../db/app_database.dart';
import '../downloads/download_planner.dart';

/// What a "Download" toggle can point at.
enum PinTargetType { playlist, album, artist, liked, track }

/// Id used for the single "Liked Songs" pin.
const String kLikedPinId = 'liked';

/// Where a pinned target is on its way to being fully offline.
enum PinPhase {
  /// Not pinned.
  off,

  /// Pinned, waiting for members to be known or for the first file.
  preparing,

  /// Pinned, and it holds no songs (an empty playlist): nothing to wait for. Songs added later download by themselves.
  empty,

  /// Some files are on the phone, others still coming.
  downloading,

  /// Every member is available offline.
  complete,

  /// Pinned, but at least one file failed and nothing is in flight.
  attention,
}

@immutable
class PinState {
  const PinState({
    this.pinned = false,
    this.total = 0,
    this.done = 0,
    this.active = 0,
    this.failed = 0,
    this.bytes = 0,
    this.confirmedEmpty = false,
  });

  static const PinState none = PinState();

  final bool pinned;
  final int total;
  final int done;
  final int active;
  final int failed;
  final int bytes;

  /// The members were counted and there are none, as opposed to songs that have not reached this phone yet (a pinned song whose row has
  /// not synced, a release the server is still getting, a playlist whose entries were not fetched): only the first is "nothing to download".
  final bool confirmedEmpty;

  PinPhase get phase {
    if (!pinned) return PinPhase.off;
    if (total == 0) return confirmedEmpty ? PinPhase.empty : PinPhase.preparing;
    if (done >= total) return PinPhase.complete;
    if (active == 0 && failed > 0) return PinPhase.attention;
    if (done == 0 && active == 0) return PinPhase.preparing;
    return PinPhase.downloading;
  }

  /// 0..1 for progress rings.
  double get progress => total == 0 ? 0 : (done / total).clamp(0.0, 1.0);

  @override
  bool operator ==(Object other) =>
      other is PinState &&
      other.pinned == pinned &&
      other.total == total &&
      other.done == done &&
      other.active == active &&
      other.failed == failed &&
      other.bytes == bytes &&
      other.confirmedEmpty == confirmedEmpty;

  @override
  int get hashCode =>
      Object.hash(pinned, total, done, active, failed, bytes, confirmedEmpty);

  @override
  String toString() => 'PinState($phase, $done/$total, active: $active, '
      'failed: $failed)';
}

/// A song the phone could not take, with what the downloader recorded (never shown as it is: see `phoneFailureWords`).
@immutable
class FailedSong {
  const FailedSong(
      {required this.ref,
      required this.title,
      required this.artist,
      this.error});

  final String ref;
  final String title;
  final String artist;
  final String? error;
}

@immutable
class StorageSummary {
  const StorageSummary({this.tracks = 0, this.bytes = 0});

  final int tracks;
  final int bytes;

  @override
  bool operator ==(Object other) =>
      other is StorageSummary && other.tracks == tracks && other.bytes == bytes;

  @override
  int get hashCode => Object.hash(tracks, bytes);
}

/// Database side of offline downloads: what the user pinned, what is on the
/// phone, and the bookkeeping the reconciler needs. Pure data access - the
/// file transfers live in `DownloadManager`.
class DownloadsRepository {
  DownloadsRepository(
    this._db,
    this.serverId, {
    Clock clock = const SystemClock(),
  }) : _clock = clock;

  final AppDatabase _db;
  final int serverId;
  final Clock _clock;

  int get _nowMs => _clock.now().millisecondsSinceEpoch;

  // ----------------------------------------------------------------- members

  /// SQL selecting the track ids a target contains, plus its variables.
  /// `?1` = server id, `?2` = target id (always bound so callers can reuse the
  /// same variable list).
  static String _membersSql(PinTargetType type) => switch (type) {
        PinTargetType.playlist =>
          'SELECT e.track_id AS id FROM playlist_entries e '
              'WHERE e.server_id = ?1 AND e.playlist_id = ?2',
        PinTargetType.album => 'SELECT t.id AS id FROM tracks t '
            'WHERE t.server_id = ?1 AND t.album_id = ?2 '
            'AND t.deleted_at_ms IS NULL',
        PinTargetType.artist => 'SELECT t.id AS id FROM tracks t '
            'WHERE t.server_id = ?1 AND t.artist_id = ?2 '
            'AND t.deleted_at_ms IS NULL',
        PinTargetType.liked => 'SELECT t.id AS id FROM tracks t '
            "WHERE t.server_id = ?1 AND ?2 = 'liked' "
            'AND t.starred_at_ms IS NOT NULL AND t.deleted_at_ms IS NULL',
        PinTargetType.track => 'SELECT t.id AS id FROM tracks t '
            'WHERE t.server_id = ?1 AND t.id = ?2 '
            'AND t.deleted_at_ms IS NULL',
      };

  /// Live state of one "Download" toggle.
  Stream<PinState> watchPinState(PinTargetType type, String targetId) {
    final id = type == PinTargetType.liked ? kLikedPinId : targetId;
    final sql = '''
WITH m AS (${_membersSql(type)})
SELECT
  (SELECT COUNT(*) FROM pins
     WHERE server_id = ?1 AND target_type = ?3 AND target_id = ?2) AS pinned,
  (SELECT COUNT(*) FROM m) AS total,
  (SELECT COUNT(*) FROM m JOIN downloads d
     ON d.server_id = ?1 AND d.track_id = m.id
    AND d.state = ${DownloadState.done} AND d.stale = 0) AS done,
  (SELECT COUNT(*) FROM m JOIN downloads d
     ON d.server_id = ?1 AND d.track_id = m.id
    AND d.state IN (${DownloadState.queued}, ${DownloadState.downloading})) AS active,
  (SELECT COUNT(*) FROM m JOIN downloads d
     ON d.server_id = ?1 AND d.track_id = m.id
    AND d.state = ${DownloadState.failed}) AS failed,
  (SELECT COALESCE(SUM(d.bytes), 0) FROM m JOIN downloads d
     ON d.server_id = ?1 AND d.track_id = m.id
    AND d.state = ${DownloadState.done}) AS bytes,
  (SELECT p.song_count FROM playlists p
    WHERE p.server_id = ?1 AND p.id = ?2 AND ?3 = 'playlist') AS declared
''';
    return _db
        .customSelect(
          sql,
          variables: [
            Variable.withInt(serverId),
            Variable.withString(id),
            Variable.withString(type.name),
          ],
          readsFrom: {
            _db.pins,
            _db.downloads,
            _db.tracks,
            _db.playlistEntries,
            _db.playlists,
          },
        )
        .watchSingle()
        .map((row) => PinState(
              pinned: (row.read<int>('pinned')) > 0,
              total: row.read<int>('total'),
              done: row.read<int>('done'),
              active: row.read<int>('active'),
              failed: row.read<int>('failed'),
              bytes: row.read<int>('bytes'),
              // A playlist is empty when the server says it holds no songs; "no entries on this phone yet" is a playlist whose songs are
              // still on their way (offline, or before its entries were fetched).
              confirmedEmpty: switch (type) {
                PinTargetType.track => false,
                PinTargetType.playlist =>
                  row.readNullable<int>('declared') == 0,
                // Songs added to the Liked Songs list come by themselves; an album or an artist does not gain songs by being added to, so
                // one whose songs have not reached the phone yet is on its way, not empty.
                PinTargetType.liked => true,
                _ => false,
              },
            ))
        .distinct();
  }

  /// The songs of one pinned target that the phone could not take, newest first (at most 20), live.
  Stream<List<FailedSong>> watchFailedSongs(
      PinTargetType type, String targetId) {
    final id = type == PinTargetType.liked ? kLikedPinId : targetId;
    final sql = '''
WITH m AS (${_membersSql(type)})
SELECT t.id AS id, t.title AS title, t.artist AS artist, d.last_error AS error
  FROM m
  JOIN downloads d ON d.server_id = ?1 AND d.track_id = m.id AND d.state = ${DownloadState.failed}
  JOIN tracks t ON t.server_id = ?1 AND t.id = m.id
 ORDER BY d.updated_at_ms DESC
 LIMIT 20
''';
    return _db
        .customSelect(
          sql,
          variables: [Variable.withInt(serverId), Variable.withString(id)],
          readsFrom: {
            _db.downloads,
            _db.tracks,
            _db.playlistEntries,
            _db.playlists
          },
        )
        .watch()
        .map((rows) => [
              for (final r in rows)
                FailedSong(
                  ref: r.read<String>('id'),
                  title: r.read<String>('title'),
                  artist: r.readNullable<String>('artist') ?? '',
                  error: r.readNullable<String>('error'),
                )
            ]);
  }

  /// The same for a list of songs (a catalogue release, whose songs the phone pinned one by one).
  Stream<List<FailedSong>> watchFailedSongsIn(List<String> trackIds) {
    if (trackIds.isEmpty) return Stream.value(const []);
    final q = _db.select(_db.tracks).join([
      innerJoin(
        _db.downloads,
        _db.downloads.serverId.equalsExp(_db.tracks.serverId) &
            _db.downloads.trackId.equalsExp(_db.tracks.id),
      ),
    ])
      ..where(_db.tracks.serverId.equals(serverId) &
          _db.tracks.id.isIn(trackIds) &
          _db.downloads.state.equals(DownloadState.failed))
      ..orderBy([OrderingTerm.desc(_db.downloads.updatedAtMs)])
      ..limit(20);
    return q.watch().map((rows) => [
          for (final r in rows)
            FailedSong(
              ref: r.readTable(_db.tracks).id,
              title: r.readTable(_db.tracks).title,
              artist: r.readTable(_db.tracks).artist ?? '',
              error: r.readTable(_db.downloads).lastError,
            )
        ]);
  }

  // -------------------------------------------------------------------- pins

  Stream<List<PinRow>> watchPins() => (_db.select(_db.pins)
        ..where((p) => p.serverId.equals(serverId))
        ..orderBy([(p) => OrderingTerm.desc(p.createdAtMs)]))
      .watch();

  Future<List<PinRow>> pins() =>
      (_db.select(_db.pins)..where((p) => p.serverId.equals(serverId))).get();

  Future<void> pin(
    PinTargetType type,
    String targetId, {
    AudioQuality quality = AudioQuality.original,
  }) async {
    final id = type == PinTargetType.liked ? kLikedPinId : targetId;
    await _db.into(_db.pins).insertOnConflictUpdate(PinsCompanion.insert(
          serverId: serverId,
          targetType: type.name,
          targetId: id,
          quality: Value(quality.id),
          createdAtMs: _nowMs,
        ));
  }

  Future<void> unpin(PinTargetType type, String targetId) async {
    final id = type == PinTargetType.liked ? kLikedPinId : targetId;
    await (_db.delete(_db.pins)
          ..where((p) =>
              p.serverId.equals(serverId) &
              p.targetType.equals(type.name) &
              p.targetId.equals(id)))
        .go();
  }

  /// Every pin of this server (signing out).
  Future<void> unpinAll() =>
      (_db.delete(_db.pins)..where((p) => p.serverId.equals(serverId))).go();

  // ----------------------------------------------------------------- planning

  /// Union of the members of every pin, each at the best quality any pin
  /// asked for.
  Future<Map<String, DesiredDownload>> desired() async {
    final result = <String, DesiredDownload>{};
    final pinRows = await pins();
    for (final pin in pinRows) {
      final type = PinTargetType.values.asNameMap()[pin.targetType];
      if (type == null) continue;
      final quality = AudioQuality.byId(pin.quality);
      final rows = await _db.customSelect(
        'SELECT m.id AS id, t.audio_key AS audio_key '
        'FROM (${_membersSql(type)}) m '
        'JOIN tracks t ON t.server_id = ?1 AND t.id = m.id '
        'AND t.deleted_at_ms IS NULL AND t.missing = 0',
        variables: [
          Variable.withInt(serverId),
          Variable.withString(pin.targetId),
        ],
        readsFrom: {_db.tracks, _db.playlistEntries},
      ).get();
      for (final row in rows) {
        final id = row.read<String>('id');
        final existing = result[id];
        final best = existing == null
            ? quality
            : AudioQuality.best(AudioQuality.byId(existing.quality), quality);
        result[id] = DesiredDownload(
          trackId: id,
          quality: best.id,
          audioKey: row.read<String?>('audio_key') ?? '',
        );
      }
    }
    return result;
  }

  Future<Map<String, DownloadRow>> existing() async {
    final rows = await (_db.select(_db.downloads)
          ..where((d) => d.serverId.equals(serverId)))
        .get();
    return {for (final r in rows) r.trackId: r};
  }

  /// Writes the database side effects of [plan]. File deletion is the
  /// caller's job (it must happen *before* [deleteRows]).
  Future<void> applyPlan(
    DownloadPlan plan,
    Map<String, DesiredDownload> desired,
  ) async {
    final now = _nowMs;
    await _db.transaction(() async {
      Future<void> queue(String id, {bool keepFile = false}) async {
        final want = desired[id];
        await _db.into(_db.downloads).insert(
              DownloadsCompanion.insert(
                serverId: serverId,
                trackId: id,
                state: const Value(DownloadState.queued),
                quality: Value(want?.quality ?? AudioQuality.original.id),
                updatedAtMs: now,
              ),
              onConflict: DoUpdate(
                (old) => DownloadsCompanion(
                  state: const Value(DownloadState.queued),
                  quality: Value(want?.quality ?? AudioQuality.original.id),
                  lastError: const Value(null),
                  orphanedAtMs: const Value(null),
                  updatedAtMs: Value(now),
                  // Keep the old file (and `stale`) until the new one lands.
                  localPath:
                      keepFile ? const Value.absent() : const Value(null),
                ),
              ),
            );
      }

      for (final id in plan.toQueue) {
        await queue(id);
      }
      for (final id in plan.toRefresh) {
        await queue(id, keepFile: true);
      }
      if (plan.toOrphan.isNotEmpty) {
        await (_db.update(_db.downloads)
              ..where((d) =>
                  d.serverId.equals(serverId) &
                  d.trackId.isIn(plan.toOrphan) &
                  d.orphanedAtMs.isNull()))
            .write(DownloadsCompanion(orphanedAtMs: Value(now)));
      }
      if (plan.toRescue.isNotEmpty) {
        await (_db.update(_db.downloads)
              ..where((d) =>
                  d.serverId.equals(serverId) & d.trackId.isIn(plan.toRescue)))
            .write(const DownloadsCompanion(orphanedAtMs: Value(null)));
      }
    });
  }

  Future<List<DownloadRow>> rowsFor(Iterable<String> trackIds) {
    final ids = trackIds.toList();
    if (ids.isEmpty) return Future.value(const []);
    return (_db.select(_db.downloads)
          ..where((d) => d.serverId.equals(serverId) & d.trackId.isIn(ids)))
        .get();
  }

  Future<void> deleteRows(Iterable<String> trackIds) async {
    final ids = trackIds.toList();
    if (ids.isEmpty) return;
    await (_db.delete(_db.downloads)
          ..where((d) => d.serverId.equals(serverId) & d.trackId.isIn(ids)))
        .go();
  }

  Future<List<DownloadRow>> rowsInState(int state, {int? limit}) {
    final q = _db.select(_db.downloads)
      ..where((d) => d.serverId.equals(serverId) & d.state.equals(state));
    if (limit != null) q.limit(limit);
    return q.get();
  }

  Future<void> markDownloading(String trackId) => _update(
      trackId,
      DownloadsCompanion(
        state: const Value(DownloadState.downloading),
        updatedAtMs: Value(_nowMs),
      ));

  Future<void> markDone(
    String trackId, {
    required String localPath,
    required int bytes,
    required String audioKey,
    required String quality,
  }) =>
      _update(
        trackId,
        DownloadsCompanion(
          state: const Value(DownloadState.done),
          localPath: Value(localPath),
          bytes: Value(bytes),
          expectedBytes: Value(bytes),
          sourceAudioKey: Value(audioKey),
          quality: Value(quality),
          stale: const Value(false),
          lastError: const Value(null),
          attempts: const Value(0),
          updatedAtMs: Value(_nowMs),
        ),
      );

  /// A refresh did not work out: the old copy is still on disk and still the
  /// one to play, so the row goes back to `done` and says why (B22). The
  /// planner tries the refresh again at the next pass.
  Future<void> restoreDone(String trackId, String error) async {
    final row = await rowsFor([trackId]);
    final attempts = row.isEmpty ? 1 : row.first.attempts + 1;
    await _update(
      trackId,
      DownloadsCompanion(
        state: const Value(DownloadState.done),
        lastError: Value(error),
        attempts: Value(attempts),
        updatedAtMs: Value(_nowMs),
      ),
    );
  }

  Future<void> markFailed(String trackId, String error) async {
    final row = await rowsFor([trackId]);
    final attempts = row.isEmpty ? 1 : row.first.attempts + 1;
    await _update(
      trackId,
      DownloadsCompanion(
        state: const Value(DownloadState.failed),
        lastError: Value(error),
        attempts: Value(attempts),
        updatedAtMs: Value(_nowMs),
      ),
    );
  }

  Future<void> markQueued(String trackId) => _update(
        trackId,
        DownloadsCompanion(
          state: const Value(DownloadState.queued),
          updatedAtMs: Value(_nowMs),
        ),
      );

  Future<void> _update(String trackId, DownloadsCompanion values) => (_db
          .update(_db.downloads)
        ..where((d) => d.serverId.equals(serverId) & d.trackId.equals(trackId)))
      .write(values);

  // ---------------------------------------------------------------- read side

  /// Bytes of finished downloads (what the storage guard counts).
  Future<int> usedBytes() async {
    final bytes = _db.downloads.bytes.sum();
    final q = _db.selectOnly(_db.downloads)
      ..addColumns([bytes])
      ..where(_db.downloads.serverId.equals(serverId) &
          _db.downloads.state.equals(DownloadState.done));
    return (await q.getSingle()).read(bytes) ?? 0;
  }

  Stream<StorageSummary> watchStorage() {
    final count = _db.downloads.trackId.count();
    final bytes = _db.downloads.bytes.sum();
    final q = _db.selectOnly(_db.downloads)
      ..addColumns([count, bytes])
      ..where(_db.downloads.serverId.equals(serverId) &
          _db.downloads.state.equals(DownloadState.done));
    return q.watchSingle().map((r) => StorageSummary(
          tracks: r.read(count) ?? 0,
          bytes: r.read(bytes) ?? 0,
        ));
  }

  /// Downloaded tracks, newest first, for the "Downloaded" library view.
  Stream<List<TrackRow>> watchDownloadedTracks() {
    final q = _db.select(_db.tracks).join([
      innerJoin(
        _db.downloads,
        _db.downloads.serverId.equalsExp(_db.tracks.serverId) &
            _db.downloads.trackId.equalsExp(_db.tracks.id),
      ),
    ])
      ..where(_db.tracks.serverId.equals(serverId) &
          _db.downloads.state.equals(DownloadState.done))
      ..orderBy([OrderingTerm.desc(_db.downloads.updatedAtMs)]);
    return q
        .watch()
        .map((rows) => [for (final r in rows) r.readTable(_db.tracks)]);
  }

  /// Local file for a track when it is downloaded and current.
  Future<String?> localPathFor(String trackId) async {
    final rows = await rowsFor([trackId]);
    if (rows.isEmpty) return null;
    final row = rows.first;
    if (row.state != DownloadState.done) return null;
    return row.localPath;
  }

  /// Tracks of one pin target (for "download all" queues and counts).
  Future<List<String>> memberIds(PinTargetType type, String targetId) async {
    final id = type == PinTargetType.liked ? kLikedPinId : targetId;
    final rows = await _db.customSelect(
      _membersSql(type),
      variables: [Variable.withInt(serverId), Variable.withString(id)],
      readsFrom: {_db.tracks, _db.playlistEntries},
    ).get();
    return [for (final r in rows) r.read<String>('id')];
  }
}
