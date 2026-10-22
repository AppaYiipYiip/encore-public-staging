import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:drift/drift.dart';

import '../../core/clock.dart';
import '../../core/logger.dart';
import '../../core/result.dart';
import '../api/opensubsonic/models.dart';
import '../api/opensubsonic/opensubsonic_client.dart';
import '../db/app_database.dart';
import '../encore/encore_api.dart';
import '../encore/encore_delivery.dart';
import 'db_lease.dart';
import 'playlist_mutations.dart';

/// Kinds of queued local mutations (payload formats documented inline).
abstract final class OutboxKind {
  /// `{ "songIds": [], "albumIds": [], "artistIds": [] }`
  static const star = 'star';
  static const unstar = 'unstar';

  /// `{ "id": "...", "rating": 0..5 }`
  static const rating = 'rating';

  /// `{ "id": "...", "submission": true, "timeMs": 123 }`
  static const scrobble = 'scrobble';

  /// `{ "name": "...", "songIds": [], "localId": "local-..." }` - `localId`
  /// is replaced by the server's id once delivered.
  static const playlistCreate = 'playlist.create';

  /// `{ "playlistId": "...", "name"?, "comment"?, "add": [], "removeIdx": [],
  /// "removeIds": [] }` - removals are resolved by track id against the
  /// server's current list when delivered (indexes only act as a hint).
  static const playlistUpdate = 'playlist.update';

  /// `{ "id": "..." }`
  static const playlistDelete = 'playlist.delete';
}

/// Delivers queued mutations to the server, in order, with backoff.
///
/// Guarantees: at-least-once delivery, original order per queue, a failing
/// network stops the queue (so order is preserved), a permanently rejected
/// item is parked as `failed` instead of blocking everything behind it.
class OutboxProcessor {
  OutboxProcessor({
    required AppDatabase db,
    required OpenSubsonicClient client,
    required this.serverId,
    Clock clock = const SystemClock(),
    this.baseBackoff = const Duration(seconds: 20),
    this.maxBackoff = const Duration(minutes: 30),
    this.maxServerAttempts = 12,
    DbLease? lease,
    this.busyRetryDelay = const Duration(seconds: 5),
    EncoreApi? encore,
  })  : _db = db,
        _lease = lease ?? DbLease(db, clock: clock),
        _client = client,
        _encore = encore,
        _clock = clock;

  /// Set for an Encore server: the edits go to its API instead of the music server's.
  final EncoreApi? _encore;

  final AppDatabase _db;
  final OpenSubsonicClient _client;
  final Clock _clock;
  final int serverId;
  final Duration baseBackoff;
  final Duration maxBackoff;

  /// How many times the *server* may fail the same item (a 5xx, or the generic
  /// Subsonic code 0) before it is parked as failed. Being offline never counts.
  final int maxServerAttempts;

  /// Who else may be delivering (the other engine in this app).
  final DbLease _lease;

  /// When another engine holds the queue, look again after this long.
  final Duration busyRetryDelay;

  Future<int>? _inFlight;

  /// Number of items still waiting (for diagnostics UI).
  Stream<int> watchPending() {
    final count = _db.outbox.id.count();
    final q = _db.selectOnly(_db.outbox)
      ..addColumns([count])
      ..where(_db.outbox.serverId.equals(serverId) &
          _db.outbox.status.equals('pending'));
    return q.watchSingle().map((r) => r.read(count) ?? 0);
  }

  /// Delivers everything that is due. Returns how many items were delivered.
  /// Concurrent calls share one pass.
  Future<int> flush() =>
      _inFlight ??= _flush().whenComplete(() => _inFlight = null);

  /// How long the delivery lease lasts without being renewed (renewed before
  /// every item; a request has a 30 s timeout).
  static const Duration leaseTtl = Duration(seconds: 60);

  String get _leaseName => 'outbox:$serverId';

  Timer? _retryTimer;

  /// Another engine is delivering. It may already have looked at the queue
  /// when this edit was added, so look once more shortly.
  void _retryLater() {
    _retryTimer ??= Timer(busyRetryDelay, () {
      _retryTimer = null;
      unawaited(flush());
    });
  }

  bool _disposed = false;

  /// The session is going away (sign-out, switching server): no new delivery
  /// starts, the one in flight finishes its current request and stops, and this
  /// completes only then, so the caller can close the database without a
  /// delivery still touching it afterwards.
  Future<void> dispose() async {
    _disposed = true;
    _retryTimer?.cancel();
    _retryTimer = null;
    final running = _inFlight;
    if (running != null) {
      await running.then<void>(
        (_) {},
        onError: (Object error) =>
            Log.debug('outbox', 'a delivery ended with an error: $error'),
      );
    }
  }

  /// One engine delivers at a time across the app (the open screen and the
  /// background job share one database but not memory), so the same queued
  /// edit is never sent twice (duplicate songs, duplicate playlist, double
  /// play count; docs/23, B2).
  Future<int> _flush() async {
    if (_disposed) return 0;
    if (!await _lease.tryAcquire(_leaseName, ttl: leaseTtl)) {
      _retryLater();
      return 0;
    }
    try {
      return await _drain();
    } finally {
      await _lease.release(_leaseName);
    }
  }

  Future<int> _drain() async {
    var delivered = 0;
    while (true) {
      if (_disposed) return delivered;
      // Renew before every item; if it was lost, stop and let the other engine
      // carry on from the row after the last one this engine finished.
      if (!await _lease.tryAcquire(_leaseName, ttl: leaseTtl)) return delivered;
      final nowMs = _clock.now().millisecondsSinceEpoch;
      // Strict FIFO: the head of the queue gates everything behind it, so a
      // failed item can never be overtaken by a later one (playlist edits
      // depend on order). A permanently rejected head is parked as `failed`
      // and stops gating.
      final next = await (_db.select(_db.outbox)
            ..where(
                (o) => o.serverId.equals(serverId) & o.status.equals('pending'))
            ..orderBy([(o) => OrderingTerm.asc(o.id)])
            ..limit(1))
          .getSingleOrNull();
      if (next == null || next.nextAttemptAtMs > nowMs) return delivered;

      // Adding ten songs one by one is ten queued edits but one request.
      // Merged here - at delivery, from rows already read - and not when the
      // edit is queued, so a row being sent can never be modified under it.
      final batch = await _batchWith(next);
      final result = await _deliver(batch.row);
      switch (result) {
        case Ok():
          await (_db.delete(_db.outbox)..where((o) => o.id.isIn(batch.ids)))
              .go();
          delivered += batch.ids.length;
        case Err(:final failure):
          // The server itself answered with an error (not "no signal", not
          // "sign in again"): only these count toward the bound, so a week
          // offline can never park an edit.
          final serverSide = failure is ServerFailure;
          final transient = failure is NetworkFailure ||
              failure is AuthFailure ||
              (failure is ServerFailure && failure.isRetryable);
          final serverErrors = next.serverErrors + (serverSide ? 1 : 0);
          final exhausted =
              transient && serverSide && serverErrors >= maxServerAttempts;

          if (transient && !exhausted) {
            // Back off and stop so ordering is preserved.
            final attempts = next.attempts + 1;
            final delay = Duration(
              milliseconds: min(
                baseBackoff.inMilliseconds * pow(2, min(attempts, 8)).toInt(),
                maxBackoff.inMilliseconds,
              ),
            );
            await (_db.update(_db.outbox)..where((o) => o.id.equals(next.id)))
                .write(OutboxCompanion(
              attempts: Value(attempts),
              serverErrors: Value(serverErrors),
              nextAttemptAtMs: Value(nowMs + delay.inMilliseconds),
              lastError: Value(failure.message),
            ));
            return delivered;
          }

          // A permanent rejection, or a server that keeps failing the same
          // request: park it so it stops gating everything behind it, and keep
          // draining the rest. Parked items are shown to the person (B1).
          final reason = exhausted
              ? 'Gave up after $serverErrors tries: ${failure.message}'
              : failure.message;
          Log.warn('outbox', '${next.kind} parked: $reason');
          await (_db.update(_db.outbox)..where((o) => o.id.equals(next.id)))
              .write(OutboxCompanion(
            status: const Value('failed'),
            serverErrors: Value(serverErrors),
            lastError: Value(reason),
          ));
      }
    }
  }

  /// [head] plus the consecutive pending "add songs" edits for the same
  /// playlist right behind it, as one request (at most 50 rows).
  Future<({OutboxRow row, List<int> ids})> _batchWith(OutboxRow head) async {
    final first = _pureAdd(head);
    if (first == null) return (row: head, ids: [head.id]);

    final followers = await (_db.select(_db.outbox)
          ..where((o) =>
              o.serverId.equals(serverId) &
              o.status.equals('pending') &
              o.id.isBiggerThanValue(head.id))
          ..orderBy([(o) => OrderingTerm.asc(o.id)])
          ..limit(50))
        .get();

    final ids = <int>[head.id];
    final songs = [...first.songs];
    for (final row in followers) {
      final add = _pureAdd(row);
      if (add == null || add.playlistId != first.playlistId) break;
      songs.addAll(add.songs);
      ids.add(row.id);
    }
    if (ids.length == 1) return (row: head, ids: ids);
    return (
      row: head.copyWith(
        payloadJson: jsonEncode({
          'playlistId': first.playlistId,
          'add': songs,
        }),
      ),
      ids: ids,
    );
  }

  /// `(playlistId, songs)` when [row] only appends songs to a playlist.
  ({String playlistId, List<String> songs})? _pureAdd(OutboxRow row) {
    if (row.kind != OutboxKind.playlistUpdate) return null;
    final Map<String, dynamic> p;
    try {
      p = (jsonDecode(row.payloadJson) as Map).cast<String, dynamic>();
    } on FormatException {
      return null; // not mergeable; delivered on its own, where it is parked
    } on TypeError {
      return null;
    }
    final id = p['playlistId'];
    final add = p['add'];
    final onlyKeys = p.keys.every((k) => k == 'playlistId' || k == 'add');
    if (id is! String || add is! List || add.isEmpty || !onlyKeys) return null;
    return (playlistId: id, songs: [for (final v in add) '$v']);
  }

  /// Whether an earlier attempt already created this playlist (and, if the
  /// server has it but the phone never recorded it, adopts it).
  ///
  /// The create reaches the server, then the process dies before the phone
  /// records the new id and removes the queued row; on the next start the row
  /// is still there, and sending it again made a second playlist and corrupted
  /// the alias (docs/23, B2). Two proofs, cheapest first:
  ///
  /// 1. the alias table already maps this local playlist to a server one;
  /// 2. the server lists a playlist with the same name and song count that is
  ///    not adopted by another local playlist and was created after this edit
  ///    was queued (five minutes of clock difference allowed). A playlist
  ///    without a creation time proves nothing and is ignored.
  Future<bool> _alreadyCreated(
    OutboxRow row,
    Map<String, dynamic> payload,
    int songCount,
  ) async {
    final localId = payload['localId'];
    if (localId is! String) return false;
    if (await PlaylistMutations.aliasFor(_db, serverId, localId) != null) {
      return true;
    }
    final name = payload['name'];
    if (name is! String) return false;
    final earlier = await _findCreated(
      name,
      songCount,
      since: row.createdAtMs - const Duration(minutes: 5).inMilliseconds,
      excluding: await PlaylistMutations.adoptedServerIds(_db, serverId),
    );
    if (earlier == null) return false;
    await PlaylistMutations.adoptServerId(
      _db,
      serverId,
      localId: localId,
      serverPlaylistId: earlier,
    );
    return true;
  }

  /// The id of the playlist we just created, found by name and size among
  /// the newest matches; `null` when the list does not show it.
  Future<String?> _findCreated(
    String name,
    int songCount, {
    int? since,
    Set<String> excluding = const {},
  }) async {
    final list = await _client.getPlaylists();
    if (list case Ok(:final value)) {
      final matches = [
        for (final p in value)
          if (p.name == name &&
              p.songCount == songCount &&
              !excluding.contains(p.id) &&
              (since == null || (p.createdAtMs ?? -1) >= since))
            p,
      ]..sort((a, b) => (b.createdAtMs ?? 0).compareTo(a.createdAtMs ?? 0));
      if (matches.isNotEmpty) return matches.first.id;
    }
    return null;
  }

  /// Shown to the person when a queued change cannot be delivered because its
  /// stored data is damaged or from a build this one does not understand.
  static const String unreadable =
      'This change was saved in a form the app cannot read.';

  /// A damaged change must never throw out of [flush]: the flush is the first
  /// step of every sync, so one bad row failed every sync for ever (B3). It is
  /// a permanent failure: retrying cannot repair the data.
  Future<Result<void>> _deliver(OutboxRow row) async {
    try {
      return await _deliverChecked(row);
    } on TypeError catch (error, stack) {
      return Result.err(
          UnexpectedFailure(unreadable, cause: error, stackTrace: stack));
    }
  }

  Future<Result<void>> _deliverChecked(OutboxRow row) async {
    final Map<String, dynamic> p;
    try {
      p = (jsonDecode(row.payloadJson) as Map).cast<String, dynamic>();
    } on FormatException catch (e) {
      return Result.err(UnexpectedFailure(unreadable, cause: e));
    }
    final encore = _encore;
    if (encore != null) {
      return deliverToEncore(encore, row, p, deviceId: encore.deviceId);
    }
    List<String> strings(String key) =>
        [for (final v in (p[key] as List? ?? const [])) v.toString()];

    switch (row.kind) {
      case OutboxKind.star:
        return _client.star(
          songIds: strings('songIds'),
          albumIds: strings('albumIds'),
          artistIds: strings('artistIds'),
        );
      case OutboxKind.unstar:
        return _client.unstar(
          songIds: strings('songIds'),
          albumIds: strings('albumIds'),
          artistIds: strings('artistIds'),
        );
      case OutboxKind.rating:
        return _client.setRating(p['id'] as String, p['rating'] as int);
      case OutboxKind.scrobble:
        return _client.scrobble(
          p['id'] as String,
          submission: (p['submission'] as bool?) ?? true,
          timeMs: p['timeMs'] as int?,
        );
      case OutboxKind.playlistCreate:
        if (await _alreadyCreated(row, p, strings('songIds').length)) {
          return const Result.ok(null);
        }
        final created = await _client.createPlaylist(
          name: p['name'] as String,
          songIds: strings('songIds'),
        );
        if (created case Ok(:final value)) {
          final localId = p['localId'];
          if (localId is String) {
            // Servers that do not answer with the new playlist: find it by
            // name in the list, otherwise forget the local copy so the next
            // sync brings the real one (never two playlists).
            final id = value ??
                await _findCreated(
                    p['name'] as String, strings('songIds').length);
            if (id != null) {
              await PlaylistMutations.adoptServerId(
                _db,
                serverId,
                localId: localId,
                serverPlaylistId: id,
              );
            } else {
              await PlaylistMutations.discardLocal(_db, serverId, localId);
            }
          }
          return const Result.ok(null);
        }
        return Result.err(created.failureOrNull!);
      case OutboxKind.playlistUpdate:
        final playlistId = p['playlistId'] as String;
        var removeIdx = [
          for (final v in (p['removeIdx'] as List? ?? const [])) v as int,
        ];
        final removeIds = strings('removeIds');
        if (removeIds.isNotEmpty) {
          // Another client may have reordered the playlist since the user
          // tapped: find the songs by id in the list as it is *now*.
          final detail = await _client.getPlaylist(playlistId);
          if (detail case Err(:final failure)) return Result.err(failure);
          removeIdx = resolveRemovalIndexes(
            serverTrackIds: [
              for (final s in detail.getOrThrow().entries ?? const <SsSong>[])
                s.id,
            ],
            wantedIds: removeIds,
            hints: removeIdx,
          );
        }
        final add = strings('add');
        final name = p['name'] as String?;
        final comment = p['comment'] as String?;
        if (add.isEmpty &&
            removeIdx.isEmpty &&
            name == null &&
            comment == null) {
          return const Result.ok(null); // nothing left to do
        }
        return _client.updatePlaylist(
          playlistId: playlistId,
          name: name,
          comment: comment,
          songIdsToAdd: add,
          songIndexesToRemove: removeIdx,
        );
      case OutboxKind.playlistDelete:
        return _client.deletePlaylist(p['id'] as String);
      default:
        return Result.err(UnexpectedFailure(unreadable));
    }
  }
}

/// Local-first mutations: update the database immediately (the UI reacts via
/// streams) and queue the server write.
class MutationService {
  MutationService({
    required AppDatabase db,
    required this.serverId,
    Clock clock = const SystemClock(),
    void Function()? onQueued,
  })  : _db = db,
        _clock = clock,
        _onQueued = onQueued;

  final AppDatabase _db;
  final Clock _clock;
  final int serverId;
  final void Function()? _onQueued;

  Future<void> setTrackStarred(String trackId, bool starred) =>
      _setStarred('songIds', _db.tracks, trackId, starred);

  Future<void> setAlbumStarred(String albumId, bool starred) =>
      _setStarred('albumIds', _db.albums, albumId, starred);

  Future<void> setArtistStarred(String artistId, bool starred) =>
      _setStarred('artistIds', _db.artists, artistId, starred);

  Future<void> _setStarred<T extends Table, D>(
    String payloadKey,
    TableInfo<T, D> table,
    String id,
    bool starred,
  ) async {
    final nowMs = _clock.now().millisecondsSinceEpoch;
    await _db.transaction(() async {
      await _db.customUpdate(
        'UPDATE ${table.actualTableName} SET starred_at_ms = ?1 '
        'WHERE server_id = ?2 AND id = ?3',
        variables: [
          Variable<int>(starred ? nowMs : null),
          Variable<int>(serverId),
          Variable<String>(id),
        ],
        updates: {table},
        updateKind: UpdateKind.update,
      );

      // A pending opposite operation for the same id cancels out.
      final opposite = starred ? OutboxKind.unstar : OutboxKind.star;
      final pending = await (_db.select(_db.outbox)
            ..where((o) =>
                o.serverId.equals(serverId) &
                o.status.equals('pending') &
                o.kind.equals(opposite)))
          .get();
      for (final row in pending) {
        final p = (jsonDecode(row.payloadJson) as Map).cast<String, dynamic>();
        final ids = [
          for (final v in (p[payloadKey] as List? ?? const [])) '$v'
        ];
        if (ids.length == 1 && ids.first == id) {
          await (_db.delete(_db.outbox)..where((o) => o.id.equals(row.id)))
              .go();
          return;
        }
      }

      await _db.into(_db.outbox).insert(OutboxCompanion.insert(
            serverId: serverId,
            kind: starred ? OutboxKind.star : OutboxKind.unstar,
            payloadJson: jsonEncode({
              payloadKey: [id],
            }),
            createdAtMs: nowMs,
          ));
    });
    _onQueued?.call();
  }

  /// Records a play locally and queues the scrobble (offline-safe).
  Future<void> recordPlay({
    required String trackId,
    required int listenedMs,
    String? source,
    bool scrobble = true,
  }) async {
    final nowMs = _clock.now().millisecondsSinceEpoch;
    await _db.transaction(() async {
      await _db.into(_db.playHistory).insert(PlayHistoryCompanion.insert(
            serverId: serverId,
            trackId: trackId,
            playedAtMs: nowMs,
            listenedMs: Value(listenedMs),
            source: Value(source),
          ));
      if (scrobble) {
        await _db.into(_db.outbox).insert(OutboxCompanion.insert(
              serverId: serverId,
              kind: OutboxKind.scrobble,
              payloadJson: jsonEncode({
                'id': trackId,
                'submission': true,
                'timeMs': nowMs,
                'listenedMs': listenedMs,
                if (source != null) 'source': source,
              }),
              createdAtMs: nowMs,
            ));
      }
    });
    if (scrobble) _onQueued?.call();
  }
}

/// Indexes (in the server's current list) of the entries the user removed.
///
/// [wantedIds] are the track ids that were removed, [hints] the positions
/// they had on the phone. A song may appear several times in a playlist, so
/// each id is matched to the unused occurrence nearest to its hint. Songs that
/// are no longer in the list (removed elsewhere meanwhile) are skipped.
List<int> resolveRemovalIndexes({
  required List<String> serverTrackIds,
  required List<String> wantedIds,
  required List<int> hints,
}) {
  final used = <int>{};
  final result = <int>[];
  for (var i = 0; i < wantedIds.length; i++) {
    final hint = i < hints.length ? hints[i] : 0;
    int? best;
    for (var pos = 0; pos < serverTrackIds.length; pos++) {
      if (serverTrackIds[pos] != wantedIds[i] || used.contains(pos)) continue;
      if (best == null || (pos - hint).abs() < (best - hint).abs()) best = pos;
    }
    if (best != null) {
      used.add(best);
      result.add(best);
    }
  }
  result.sort();
  return result;
}
