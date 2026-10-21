import 'dart:async';
import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:meta/meta.dart';

import '../../core/clock.dart';
import '../../core/logger.dart';
import '../../core/result.dart';
import '../api/opensubsonic/models.dart';
import '../api/opensubsonic/opensubsonic_client.dart';
import '../db/app_database.dart';
import 'db_lease.dart';
import 'fingerprint.dart';
import 'library_writer.dart';
import 'outbox.dart';
import 'pending_intent.dart';
import 'playlist_mutations.dart';
import 'sync_state_store.dart';

/// Why a sync was requested (used for scheduling decisions and diagnostics).
enum SyncReason { appStart, resume, connectivity, scheduled, manual, mutation }

/// Coarse phases reported to the UI / diagnostics.
enum SyncPhase {
  idle,
  probing,
  artists,
  albums,
  songs,
  playlists,
  starred,
  finishing,
}

@immutable
class SyncProgress {
  const SyncProgress(this.phase, {this.done = 0, this.total});

  final SyncPhase phase;
  final int done;

  /// Total when known (hint only).
  final int? total;

  double? get fraction =>
      (total == null || total == 0) ? null : (done / total!).clamp(0.0, 1.0);

  @override
  String toString() => 'SyncProgress($phase $done/${total ?? '?'})';
}

@immutable
class SyncOptions {
  const SyncOptions({
    this.pageSize = 500,
    this.maxLibraryAge = const Duration(hours: 24),
    this.smartPlaylistTtl = const Duration(hours: 6),
    this.pinnedSmartPlaylistTtl = const Duration(hours: 1),
    this.maxPlaylistFetchesPerRun = 24,
    this.autoFetchSmartMaxSongs = 300,
    this.shrinkGuardRatio = 0.5,
    this.shrinkGuardMinTracks = 50,
    this.shrinkGuardMinGroups = 10,
    this.shrinkConfirmRuns = 3,
    this.shrinkAutoAcceptFloor = 0.1,
  });

  final int pageSize;

  /// Even when the server reports no change, do a full verification this often.
  final Duration maxLibraryAge;

  /// Re-fetch cadence of unpinned smart playlists whose `changed` is stable.
  final Duration smartPlaylistTtl;
  final Duration pinnedSmartPlaylistTtl;
  final int maxPlaylistFetchesPerRun;

  /// Large smart playlists (e.g. "Phone Everything", ~4000 songs) are only
  /// fetched when pinned or opened; fetching them eagerly costs megabytes of
  /// JSON for something the user may never open.
  final int autoFetchSmartMaxSongs;

  /// If a "complete" dump returns fewer than `ratio` of the previous live
  /// tracks (and there were at least `minTracks`), nothing is tombstoned: an
  /// empty/partial server answer must never wipe the user's library.
  final double shrinkGuardRatio;
  final int shrinkGuardMinTracks;

  /// The same rule for albums and artists, which have far fewer rows.
  final int shrinkGuardMinGroups;

  /// A "too small" answer is believed after this many runs in a row gave
  /// exactly the same one (a real deletion is stable; a glitch is not)...
  final int shrinkConfirmRuns;

  /// ...but only when it is at least this share of what was there. An empty
  /// or near-empty answer (a music drive unplugged on the server) is never
  /// accepted automatically; only the person can ("Follow the server").
  final double shrinkAutoAcceptFloor;
}

@immutable
class SyncStats {
  const SyncStats({
    this.artists = 0,
    this.albums = 0,
    this.tracks = 0,
    this.playlistsFetched = 0,
    this.tombstonedTracks = 0,
    this.staleDownloads = 0,
    this.libraryPhaseRan = false,
    this.shrinkGuardTripped = false,
  });

  final int artists;
  final int albums;
  final int tracks;
  final int playlistsFetched;
  final int tombstonedTracks;
  final int staleDownloads;
  final bool libraryPhaseRan;
  final bool shrinkGuardTripped;
}

sealed class SyncOutcome {
  const SyncOutcome();
}

final class SyncCompleted extends SyncOutcome {
  const SyncCompleted(this.stats);
  final SyncStats stats;
}

final class SyncFailed extends SyncOutcome {
  const SyncFailed(this.failure);
  final AppFailure failure;
}

final class SyncCancelled extends SyncOutcome {
  const SyncCancelled();
}

/// The result of the cheap check the app runs every few seconds while it is
/// open (ADR-071, layer L1): `getScanStatus` plus the playlist list, fetching
/// only the playlists whose stamp moved.
sealed class ProbeOutcome {
  const ProbeOutcome();
}

/// Nothing to do: two small requests and no changes.
final class ProbeUnchanged extends ProbeOutcome {
  const ProbeUnchanged();
}

/// [playlists] were fetched again, added or removed.
final class ProbeUpdated extends ProbeOutcome {
  const ProbeUpdated(this.playlists);
  final int playlists;
}

/// The library itself changed (or is due): the caller should run a normal
/// pass; the probe never dumps the library.
final class ProbeNeedsFullPass extends ProbeOutcome {
  const ProbeNeedsFullPass();
}

/// A sync, or another probe, is already working here or in the other engine.
final class ProbeBusy extends ProbeOutcome {
  const ProbeBusy();
}

final class ProbeFailed extends ProbeOutcome {
  const ProbeFailed(this.failure);
  final AppFailure failure;
}

/// Another engine (the open app or the background job) holds the sync lease:
/// nothing was done here, and nothing needs to be.
final class SyncBusy extends SyncOutcome {
  const SyncBusy();
}

/// Incremental, non-destructive library synchronisation (ADR-006).
///
/// Single-flight: concurrent `run()` calls share the in-flight result.
class SyncEngine {
  SyncEngine({
    required AppDatabase db,
    required OpenSubsonicClient client,
    required this.serverId,
    Clock clock = const SystemClock(),
    this.options = const SyncOptions(),
    OutboxProcessor? outbox,
    DbLease? lease,
  })  : _db = db,
        _lease = lease ?? DbLease(db, clock: clock),
        _client = client,
        _outbox = outbox,
        _clock = clock,
        _writer = LibraryWriter(db),
        _state = SyncStateStore(db, serverId);

  final AppDatabase _db;
  final OpenSubsonicClient _client;
  final Clock _clock;
  final OutboxProcessor? _outbox;
  final DbLease _lease;
  final LibraryWriter _writer;
  final SyncStateStore _state;
  final int serverId;
  final SyncOptions options;

  final StreamController<SyncProgress> _progress =
      StreamController<SyncProgress>.broadcast();
  Future<SyncOutcome>? _inFlight;
  bool _cancel = false;

  Stream<SyncProgress> get progress => _progress.stream;
  bool get isRunning => _inFlight != null;

  /// Cooperative cancellation, honoured between requests/pages.
  void cancel() => _cancel = true;

  /// Stops a run in progress (it ends at its next page) and waits for it, so
  /// the database can be closed without the run still writing to it. Sign-out
  /// and a server switch used to leave the run going (B33).
  Future<void> dispose() async {
    _cancel = true;
    final running = _inFlight;
    final probing = _probeInFlight;
    // `run` never throws: it reports failures as outcomes.
    if (running != null) await running;
    if (probing != null) await probing;
    await _progress.close();
  }

  Future<SyncOutcome> run({
    SyncReason reason = SyncReason.manual,
    bool force = false,
    bool acceptShrink = false,
  }) {
    return _inFlight ??= _run(reason, force, acceptShrink).whenComplete(() {
      _inFlight = null;
      _cancel = false;
      _emit(const SyncProgress(SyncPhase.idle));
    });
  }

  void _emit(SyncProgress p) {
    if (!_progress.isClosed) _progress.add(p);
  }

  bool get _cancelled => _cancel;

  /// How long a sync lease lasts without being renewed. Renewed between every
  /// page and every playlist, so only a request in flight (30 s timeout) can
  /// outlast a renewal.
  static const Duration leaseTtl = Duration(seconds: 90);

  String get _leaseName => 'sync:$serverId';

  /// One sync at a time across BOTH engines of the app (the open screen and
  /// the background job). A field like [_inFlight] only protects one engine
  /// object; the job has its own database connection and its own engine, so
  /// two dumps could interleave and remove each other's rows (docs/23, B2).
  Future<SyncOutcome> _run(
    SyncReason reason,
    bool force,
    bool acceptShrink,
  ) async {
    // A probe of this engine may be writing playlists; the lease cannot tell
    // (same owner), so wait for it.
    final probing = _probeInFlight;
    if (probing != null) await probing;
    if (!await _lease.tryAcquire(_leaseName, ttl: leaseTtl)) {
      Log.info('sync', 'another engine is syncing; nothing to do here');
      return const SyncBusy();
    }
    try {
      return await _runLeased(reason, force, acceptShrink);
    } finally {
      await _lease.release(_leaseName);
    }
  }

  /// Extends the lease; stops the run when it was lost (it expired and the
  /// other engine took over).
  Future<void> _keepLease() async {
    if (!await _lease.tryAcquire(_leaseName, ttl: leaseTtl)) {
      throw const _LeaseLost();
    }
  }

  Future<SyncOutcome> _runLeased(
    SyncReason reason,
    bool force,
    bool acceptShrink,
  ) async {
    Log.info('sync', 'run start (${reason.name}, force=$force)');
    try {
      _emit(const SyncProgress(SyncPhase.probing));

      // Push local intent first so the server's view includes it (and so the
      // star reconciliation below never fights a pending mutation).
      await _outbox?.flush();

      final scanResult = await _client.getScanStatus();
      final scanFailure = scanResult.failureOrNull;
      if (scanFailure is NetworkFailure || scanFailure is AuthFailure) {
        await _state.set(SyncStateStore.lastError, scanFailure!.message);
        return SyncFailed(scanFailure);
      }
      final scan = scanResult.valueOrNull; // null = server has no scan status

      final nowMs = _clock.now().millisecondsSinceEpoch;
      // A server without a scan status cannot say whether anything changed, so
      // the full pass re-reads the library (the probe does not: it runs often).
      final needLibrary = force || scan == null || await _libraryDue(scan);

      var stats = const SyncStats();

      if (needLibrary) {
        final libraryOutcome = await _libraryPhase(
          scan: scan,
          nowMs: nowMs,
          acceptShrink: acceptShrink,
        );
        switch (libraryOutcome) {
          case _Cancelled():
            return const SyncCancelled();
          case _Failed(:final failure):
            await _state.set(SyncStateStore.lastError, failure.message);
            return SyncFailed(failure);
          case _Done(stats: final s):
            stats = s;
        }
      }
      if (_cancelled) return const SyncCancelled();

      // Volatile phase: cheap and always run.
      final playlistsFetched = await _playlistPhase();
      if (_cancelled) return const SyncCancelled();
      await _starredPhase();
      await _homeListsPhase();

      _emit(const SyncProgress(SyncPhase.finishing));
      final stale = await _writer.markStaleDownloads(
        serverId: serverId,
        nowMs: _clock.now().millisecondsSinceEpoch,
      );

      await _state.setInt(
          SyncStateStore.lastRunAtMs, _clock.now().millisecondsSinceEpoch);
      await _state.set(SyncStateStore.lastError, null);

      final result = SyncStats(
        artists: stats.artists,
        albums: stats.albums,
        tracks: stats.tracks,
        playlistsFetched: playlistsFetched,
        tombstonedTracks: stats.tombstonedTracks,
        staleDownloads: stale,
        libraryPhaseRan: needLibrary,
        shrinkGuardTripped: stats.shrinkGuardTripped,
      );
      Log.info(
          'sync',
          'run done: tracks=${result.tracks} playlists=${result.playlistsFetched} '
              'stale=${result.staleDownloads}');
      return SyncCompleted(result);
    } on _LeaseLost {
      Log.warn('sync', 'lost the sync lease; the other engine continues');
      return const SyncBusy();
    } on AppFailure catch (failure) {
      Log.warn('sync', 'run failed: ${failure.message}');
      await _state.set(SyncStateStore.lastError, failure.message);
      return SyncFailed(failure);
    } on Object catch (error, stackTrace) {
      Log.error('sync', 'run crashed', error, stackTrace);
      return SyncFailed(UnexpectedFailure(
        'Sync crashed: ${error.runtimeType}',
        cause: error,
        stackTrace: stackTrace,
      ));
    }
  }

  // ----------------------------------------------------------- library dump

  Future<_LibraryOutcome> _libraryPhase({
    required SsScanStatus? scan,
    required int nowMs,
    required bool acceptShrink,
  }) async {
    final runId = ((await _state.getInt(SyncStateStore.lastRunId)) ?? 0) + 1;
    await _state.setInt(SyncStateStore.lastRunId, runId);
    final before = await _writer.liveCounts(serverId);

    // Artists (single request).
    _emit(const SyncProgress(SyncPhase.artists));
    final artistsResult = await _client.getArtists();
    if (artistsResult case Err(:final failure)) return _Failed(failure);
    final artists = artistsResult.getOrThrow();
    await _writer.upsertArtists(serverId, runId, artists);
    await _keepLease();
    if (_cancelled) return const _Cancelled();

    // Albums (paged).
    var albumCount = 0;
    for (var offset = 0;; offset += options.pageSize) {
      _emit(SyncProgress(SyncPhase.albums, done: albumCount));
      final page = await _client.getAlbumList2(
        size: options.pageSize,
        offset: offset,
      );
      if (page case Err(:final failure)) return _Failed(failure);
      final albums = page.getOrThrow();
      await _writer.upsertAlbums(serverId, runId, albums);
      albumCount += albums.length;
      if (albums.length < options.pageSize) break;
      await _keepLease();
      if (_cancelled) return const _Cancelled();
    }

    // Songs (paged empty-query dump).
    var songCount = 0;
    for (var offset = 0;; offset += options.pageSize) {
      _emit(SyncProgress(SyncPhase.songs, done: songCount, total: scan?.count));
      final page = await _client.search3(
        songCount: options.pageSize,
        songOffset: offset,
      );
      if (page case Err(:final failure)) return _Failed(failure);
      final songs = page.getOrThrow().songs;
      await _writer.upsertTracks(serverId, runId, songs);
      songCount += songs.length;
      if (songs.length < options.pageSize) break;
      await _keepLease();
      if (_cancelled) return const _Cancelled();
    }

    // The dump is complete. Decide, per table, whether removals are trustworthy.
    final seen = await _writer.seenCounts(serverId, runId);
    bool shrunk(int was, int now, int min) =>
        was >= min && now < was * options.shrinkGuardRatio;
    final tracksShrunk =
        shrunk(before.tracks, seen.tracks, options.shrinkGuardMinTracks);
    final albumsShrunk =
        shrunk(before.albums, seen.albums, options.shrinkGuardMinGroups);
    final artistsShrunk =
        shrunk(before.artists, seen.artists, options.shrinkGuardMinGroups);
    final anyShrunk = tracksShrunk || albumsShrunk || artistsShrunk;

    var tombstoned = const TombstoneCounts(tracks: 0, albums: 0, artists: 0);
    var guardTripped = false;
    if (scan?.scanning ?? false) {
      // The server is mid-scan: its answer may be partial. Be conservative,
      // and do not count this run toward believing a smaller answer.
      Log.info('sync', 'server is scanning; skipping removals');
    } else {
      var believe = !anyShrunk;
      if (anyShrunk) {
        believe = acceptShrink ||
            await _believeSmallerAnswer(
              before: before,
              seen: seen,
              suspect: (
                tracks: tracksShrunk,
                albums: albumsShrunk,
                artists: artistsShrunk,
              ),
            );
        if (!believe) {
          guardTripped = true;
          Log.warn(
              'sync',
              'shrink guard: server returned ${seen.signature} '
                  '(tracks|albums|artists), had ${before.signature}; keeping '
                  'what is guarded');
          await _state.set(SyncStateStore.shrinkNotice,
              '${seen.tracks} of ${before.tracks} songs');
        }
      }
      if (believe) {
        await _state.set(SyncStateStore.shrinkNotice, null);
        await _state.set(SyncStateStore.shrinkAnswer, null);
        await _state.set(SyncStateStore.shrinkRuns, null);
      }
      tombstoned = await _writer.tombstoneUnseen(
        serverId: serverId,
        runId: runId,
        nowMs: nowMs,
        // A guarded table keeps its rows; the others follow the server.
        tracks: believe || !tracksShrunk,
        albums: believe || !albumsShrunk,
        artists: believe || !artistsShrunk,
      );
    }

    // Only record the watermark when the answer is trustworthy, so a skipped
    // or suspicious run is retried next time instead of being "remembered".
    if (!guardTripped && !(scan?.scanning ?? false)) {
      await _state.setInt(SyncStateStore.lastScanMs, scan?.lastScanMs);
      await _state.setInt(SyncStateStore.lastScanCount, scan?.count);
      await _state.setInt(SyncStateStore.lastFullSyncAtMs, nowMs);
    }

    return _Done(SyncStats(
      artists: artists.length,
      albums: albumCount,
      tracks: songCount,
      tombstonedTracks: tombstoned.tracks,
      libraryPhaseRan: true,
      shrinkGuardTripped: guardTripped,
    ));
  }

  /// Whether the library pass is due: never done, older than the maximum age,
  /// or the server's scan status moved. A server without a scan status cannot
  /// say, so only the age and a first run count as due for it.
  Future<bool> _libraryDue(SsScanStatus? scan) async {
    final lastFullMs = await _state.getInt(SyncStateStore.lastFullSyncAtMs);
    if (lastFullMs == null) return true;
    final nowMs = _clock.now().millisecondsSinceEpoch;
    if (nowMs - lastFullMs > options.maxLibraryAge.inMilliseconds) return true;
    if (scan == null) return false;
    final savedScanMs = await _state.getInt(SyncStateStore.lastScanMs);
    final savedCount = await _state.getInt(SyncStateStore.lastScanCount);
    return scan.lastScanMs != savedScanMs || scan.count != savedCount;
  }

  Future<void>? _probeInFlight;

  /// The cheap check for changes made on other devices (ADR-071, layer L1):
  /// `getScanStatus` and the playlist list, a few kilobytes, then only the
  /// playlists whose stamp moved are fetched. Meant to run every few seconds
  /// while the app is open; never dumps the library (it says so instead).
  Future<ProbeOutcome> probe() async {
    if (_inFlight != null || _probeInFlight != null) return const ProbeBusy();
    final done = Completer<void>();
    _probeInFlight = done.future;
    try {
      if (!await _lease.tryAcquire(_leaseName, ttl: leaseTtl)) {
        return const ProbeBusy();
      }
      try {
        final scanResult = await _client.getScanStatus();
        final scanFailure = scanResult.failureOrNull;
        if (scanFailure is NetworkFailure || scanFailure is AuthFailure) {
          return ProbeFailed(scanFailure!);
        }
        if (await _libraryDue(scanResult.valueOrNull)) {
          return const ProbeNeedsFullPass();
        }
        final list = await _client.getPlaylists();
        if (list case Err(:final failure)) return ProbeFailed(failure);
        final applied = await _applyPlaylists(list.getOrThrow());
        final changed = applied.fetched + applied.removed;
        return changed == 0 ? const ProbeUnchanged() : ProbeUpdated(changed);
      } on AppFailure catch (failure) {
        return ProbeFailed(failure);
      } on _LeaseLost {
        return const ProbeBusy();
      } finally {
        await _lease.release(_leaseName);
      }
    } finally {
      _probeInFlight = null;
      done.complete();
    }
  }

  /// Whether a server answer that looks far too small is the new truth.
  ///
  /// Believed only when the SAME answer came back in [SyncOptions.shrinkConfirmRuns]
  /// runs in a row (a real deletion is stable; a glitch or a half-finished
  /// scan is not) AND each suspect table kept at least
  /// [SyncOptions.shrinkAutoAcceptFloor] of its rows. Zero is never believed
  /// here: a music drive unplugged on the server must not empty the phone.
  /// Before this, nothing ever believed a shrink, so after a genuine big
  /// deletion every run re-downloaded the whole library for ever (B6).
  Future<bool> _believeSmallerAnswer({
    required LibraryCounts before,
    required LibraryCounts seen,
    required ({bool tracks, bool albums, bool artists}) suspect,
  }) async {
    final answer = seen.signature;
    final same = await _state.get(SyncStateStore.shrinkAnswer) == answer;
    final runs =
        same ? (await _state.getInt(SyncStateStore.shrinkRuns) ?? 0) + 1 : 1;
    await _state.set(SyncStateStore.shrinkAnswer, answer);
    await _state.setInt(SyncStateStore.shrinkRuns, runs);

    bool floorOk(bool isSuspect, int was, int now) =>
        !isSuspect || (now > 0 && now >= was * options.shrinkAutoAcceptFloor);
    return runs >= options.shrinkConfirmRuns &&
        floorOk(suspect.tracks, before.tracks, seen.tracks) &&
        floorOk(suspect.albums, before.albums, seen.albums) &&
        floorOk(suspect.artists, before.artists, seen.artists);
  }

  // ------------------------------------------------------------- playlists

  /// Fetches (or re-fetches) one playlist's entries on demand: used when the
  /// user opens a playlist that was skipped by the lazy policy and by the
  /// download reconciler for pinned playlists.
  Future<Result<void>> refreshPlaylist(String playlistId) async {
    // Edits made on this phone and not delivered yet are newer than the
    // server's copy; the outbox delivers them first (ADR-046).
    if (PlaylistMutations.isLocalId(playlistId) ||
        (await PlaylistMutations.pendingPlaylistIds(_db, serverId))
            .contains(playlistId)) {
      return const Result.ok(null);
    }
    final detail = await _client.getPlaylist(playlistId);
    if (detail case Err(:final failure)) return Result.err(failure);
    final playlist = detail.getOrThrow();
    // The stamp of the list entry these songs belong to: what the metadata
    // phase last stored, read before anything below rewrites it.
    final listed = await (_db.select(_db.playlists)
          ..where((p) => p.serverId.equals(serverId) & p.id.equals(playlistId)))
        .getSingleOrNull();
    final stamp = listed == null
        ? _stampOf(playlist)
        : '${listed.changedAtMs}|${listed.songCount}';
    try {
      await _db.into(_db.playlists).insertOnConflictUpdate(
            PlaylistsCompanion.insert(
              serverId: serverId,
              id: playlist.id,
              name: playlist.name,
              comment: Value(playlist.comment),
              owner: Value(playlist.owner),
              isPublic: Value(playlist.isPublic),
              readonly: Value(playlist.readonly),
              validUntilMs: Value(playlist.validUntilMs),
              coverArt: Value(playlist.coverArt),
              createdAtMs: Value(playlist.createdAtMs),
              deletedAtMs: const Value(null),
            ),
          );
      await _replaceEntries(playlist, _clock.now().millisecondsSinceEpoch,
          stamp: stamp);
      return const Result.ok(null);
    } on Object catch (error, stackTrace) {
      return Result.err(StorageFailure('Could not store playlist',
          cause: error, stackTrace: stackTrace));
    }
  }

  Future<int> _playlistPhase() async {
    _emit(const SyncProgress(SyncPhase.playlists));
    final listResult = await _client.getPlaylists();
    if (listResult case Err(:final failure)) {
      Log.warn('sync', 'playlists unavailable: ${failure.message}');
      return 0;
    }
    return (await _applyPlaylists(listResult.getOrThrow())).fetched;
  }

  /// Brings the stored playlists in line with the server's list: refreshes the
  /// metadata, fetches the songs of the playlists whose stamp moved, and marks
  /// the ones that vanished. Shared by the full pass and the live probe.
  Future<({int fetched, int removed})> _applyPlaylists(
    List<SsPlaylist> remote,
  ) async {
    final nowMs = _clock.now().millisecondsSinceEpoch;

    final existingRows = await (_db.select(_db.playlists)
          ..where((p) => p.serverId.equals(serverId)))
        .get();
    final existing = {for (final p in existingRows) p.id: p};

    final pinnedRows = await (_db.select(_db.pins)
          ..where((p) =>
              p.serverId.equals(serverId) & p.targetType.equals('playlist')))
        .get();
    final pinned = {for (final p in pinnedRows) p.targetId};
    // Playlists with edits waiting in the outbox keep their local state: the
    // server's copy is older until the edit is delivered.
    final edited = await PlaylistMutations.pendingPlaylistIds(_db, serverId);

    var fetches = 0;
    for (final r in remote) {
      await _keepLease();
      if (_cancelled) break;
      if (edited.contains(r.id)) continue;
      final e = existing[r.id];

      // Metadata is always refreshed (cheap, no entries).
      await _db.into(_db.playlists).insertOnConflictUpdate(
            PlaylistsCompanion.insert(
              serverId: serverId,
              id: r.id,
              name: r.name,
              comment: Value(r.comment),
              owner: Value(r.owner),
              isPublic: Value(r.isPublic),
              readonly: Value(r.readonly),
              validUntilMs: Value(r.validUntilMs),
              coverArt: Value(r.coverArt),
              songCount: Value(r.songCount),
              durationSec: Value(r.durationSec),
              createdAtMs: Value(r.createdAtMs),
              changedAtMs: Value(r.changedAtMs),
              deletedAtMs: const Value(null),
            ),
          );

      final isPinned = pinned.contains(r.id);
      if (!_needsEntries(r, e, isPinned, nowMs)) continue;
      if (fetches >= options.maxPlaylistFetchesPerRun && !isPinned) continue;

      final detail = await _client.getPlaylist(r.id);
      if (detail case Err(:final failure)) {
        Log.warn('sync', 'playlist ${r.id} failed: ${failure.message}');
        continue;
      }
      fetches++;
      await _replaceEntries(detail.getOrThrow(), nowMs, stamp: _stampOf(r));
    }

    // Playlists that vanished on the server (and are not already marked).
    final remoteIds = {for (final r in remote) r.id};
    // Playlists created on this phone and not delivered yet are not "gone".
    final gone = [
      for (final e in existing.values)
        if (e.deletedAtMs == null &&
            !remoteIds.contains(e.id) &&
            !PlaylistMutations.isLocalId(e.id))
          e.id,
    ];
    if (gone.isNotEmpty && !_cancelled) {
      await (_db.update(_db.playlists)
            ..where((p) => p.serverId.equals(serverId) & p.id.isIn(gone)))
          .write(PlaylistsCompanion(deletedAtMs: Value(nowMs)));
    }
    return (fetched: fetches, removed: gone.length);
  }

  bool _needsEntries(
    SsPlaylist remote,
    PlaylistRow? existing,
    bool pinned,
    int nowMs,
  ) {
    if (existing == null || existing.entriesFetchedAtMs == null) {
      final tooBigToAutoFetch = remote.readonly &&
          !pinned &&
          remote.songCount > options.autoFetchSmartMaxSongs;
      return !tooBigToAutoFetch;
    }
    // Compared with the stamp of the songs actually stored, not with the
    // metadata columns (those were refreshed before the songs were fetched).
    final stale = existing.entriesStamp != _stampOf(remote);
    if (!remote.readonly) {
      // User playlists: trust the server's change marker.
      return stale;
    }
    // Smart playlists are regenerated by the server (and "Shuffled" ones
    // change order on every evaluation), so use a TTL rather than reacting to
    // every `changed` bump (ADR-025).
    final age = nowMs - existing.entriesFetchedAtMs!;
    final ttl =
        pinned ? options.pinnedSmartPlaylistTtl : options.smartPlaylistTtl;
    if (pinned) return age > ttl.inMilliseconds;
    return stale && age > ttl.inMilliseconds;
  }

  /// The stamp that says which version of the server's playlist [_replaceEntries]
  /// stored songs for (see `Playlists.entriesStamp`).
  static String _stampOf(SsPlaylist p) => '${p.changedAtMs}|${p.songCount}';

  Future<void> _replaceEntries(
    SsPlaylist playlist,
    int nowMs, {
    required String stamp,
  }) async {
    final entries = playlist.entries ?? const <SsSong>[];
    final ids = [for (final s in entries) s.id];
    final newHash = memberSetHashOf(ids);

    await _db.transaction(() async {
      // Tracks seen through a playlist: keep their library `syncRun` alone.
      await _writer.upsertTracks(serverId, null, entries);

      final row = await (_db.select(_db.playlists)
            ..where(
                (p) => p.serverId.equals(serverId) & p.id.equals(playlist.id)))
          .getSingleOrNull();
      final sameSet = row != null &&
          row.memberSetHash == newHash &&
          row.entriesFetchedAtMs != null;

      if (!sameSet) {
        await (_db.delete(_db.playlistEntries)
              ..where((e) =>
                  e.serverId.equals(serverId) &
                  e.playlistId.equals(playlist.id)))
            .go();
        await _db.batch((b) {
          b.insertAll(_db.playlistEntries, [
            for (var i = 0; i < ids.length; i++)
              PlaylistEntriesCompanion.insert(
                serverId: serverId,
                playlistId: playlist.id,
                position: i,
                trackId: ids[i],
              ),
          ]);
        });
      }

      await (_db.update(_db.playlists)
            ..where(
                (p) => p.serverId.equals(serverId) & p.id.equals(playlist.id)))
          .write(PlaylistsCompanion(
        memberSetHash: Value(newHash),
        entriesFetchedAtMs: Value(nowMs),
        entriesStamp: Value(stamp),
        songCount: Value(ids.length),
        changedAtMs: Value(playlist.changedAtMs),
      ));
    });
  }

  // ------------------------------------------------------- server home lists

  static const _homeListTtl = Duration(minutes: 15);

  /// Server-provided "recently played" / "most played" album ids (they include
  /// plays from the user's other clients). Throttled; cheap (2 requests).
  Future<void> _homeListsPhase() async {
    const lists = {'server.recent': 'recent', 'server.frequent': 'frequent'};
    final nowMs = _clock.now().millisecondsSinceEpoch;
    for (final entry in lists.entries) {
      if (_cancelled) return;
      final cached = await (_db.select(_db.recommendationsCache)
            ..where(
                (r) => r.serverId.equals(serverId) & r.key.equals(entry.key)))
          .getSingleOrNull();
      if (cached != null &&
          nowMs - cached.computedAtMs < _homeListTtl.inMilliseconds) {
        continue;
      }
      final result = await _client.getAlbumList2(
        type: entry.value,
        size: 20,
      );
      if (result case Err(:final failure)) {
        Log.debug(
            'sync', '${entry.value} list unavailable: ${failure.message}');
        continue;
      }
      final ids = [for (final a in result.getOrThrow()) a.id];
      await _db.into(_db.recommendationsCache).insertOnConflictUpdate(
            RecommendationsCacheCompanion.insert(
              serverId: serverId,
              key: entry.key,
              payloadJson: jsonEncode(ids),
              computedAtMs: nowMs,
            ),
          );
    }
  }

  // --------------------------------------------------------------- starred

  Future<void> _starredPhase() async {
    await _keepLease();
    _emit(const SyncProgress(SyncPhase.starred));
    final result = await _client.getStarred2();
    if (result case Err(:final failure)) {
      Log.warn('sync', 'starred unavailable: ${failure.message}');
      return;
    }
    final starred = result.getOrThrow();
    final pending = await pendingStarTargets(_db, serverId);
    final nowMs = _clock.now().millisecondsSinceEpoch;

    await _db.transaction(() async {
      await _upsertTracksFromStarred(starred.songs);
      await _reconcileStars(
        table: _db.tracks,
        remote: {for (final s in starred.songs) s.id: s.starredAtMs ?? nowMs},
        pending: pending,
      );
      await _reconcileStars(
        table: _db.albums,
        remote: {for (final a in starred.albums) a.id: a.starredAtMs ?? nowMs},
        pending: pending,
      );
      await _reconcileStars(
        table: _db.artists,
        remote: {for (final a in starred.artists) a.id: a.starredAtMs ?? nowMs},
        pending: pending,
      );
    });
  }

  Future<void> _upsertTracksFromStarred(List<SsSong> songs) =>
      _writer.upsertTracks(serverId, null, songs);

  /// Makes the local starred set equal the server's, except for ids with a
  /// pending local mutation.
  Future<void> _reconcileStars<T extends Table, D>({
    required TableInfo<T, D> table,
    required Map<String, int> remote,
    required Set<String> pending,
  }) async {
    final localStarred = await (_db.customSelect(
      'SELECT id FROM ${table.actualTableName} '
      'WHERE server_id = ?1 AND starred_at_ms IS NOT NULL '
      'AND deleted_at_ms IS NULL',
      variables: [Variable<int>(serverId)],
      readsFrom: {table},
    ).get());
    final localIds = {for (final r in localStarred) r.read<String>('id')};

    final toStar = remote.keys
        .where((id) => !pending.contains(id) && !localIds.contains(id));
    final toUnstar = localIds
        .where((id) => !pending.contains(id) && !remote.containsKey(id));

    for (final id in toStar) {
      await _db.customUpdate(
        'UPDATE ${table.actualTableName} SET starred_at_ms = ?1 '
        'WHERE server_id = ?2 AND id = ?3',
        variables: [
          Variable<int>(remote[id]!),
          Variable<int>(serverId),
          Variable<String>(id),
        ],
        updates: {table},
        updateKind: UpdateKind.update,
      );
    }
    for (final id in toUnstar) {
      await _db.customUpdate(
        'UPDATE ${table.actualTableName} SET starred_at_ms = NULL '
        'WHERE server_id = ?1 AND id = ?2',
        variables: [Variable<int>(serverId), Variable<String>(id)],
        updates: {table},
        updateKind: UpdateKind.update,
      );
    }
  }
}

// Internal result type for the library phase.
sealed class _LibraryOutcome {
  const _LibraryOutcome();
}

final class _Done extends _LibraryOutcome {
  const _Done(this.stats);
  final SyncStats stats;
}

final class _Failed extends _LibraryOutcome {
  const _Failed(this.failure);
  final AppFailure failure;
}

final class _Cancelled extends _LibraryOutcome {
  const _Cancelled();
}

/// The sync lease was lost mid-run (it expired and another engine took it).
class _LeaseLost implements Exception {
  const _LeaseLost();
}
