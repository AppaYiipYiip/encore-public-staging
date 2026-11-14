import 'dart:async';

import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart';

import '../../core/clock.dart';
import '../../core/logger.dart';
import '../../domain/audio_quality.dart';
import '../../domain/storage_guard.dart';
import '../db/app_database.dart';
import '../repos/downloads_repository.dart';
import 'disk_space.dart';
import 'download_planner.dart';
import 'download_transport.dart';
import 'download_verify.dart';

/// Builds the URL for a track at a quality (original -> `download`).
typedef DownloadUrlBuilder = Future<Uri> Function(
  String trackId, {
  AudioQuality quality,
  String? sourceSuffix,
  int? sourceBitRate,
});

/// Thrown by a [DownloadUrlBuilder] for a song the server does not keep yet (D-21: a release was saved and the server is still getting
/// its songs). The song WAITS: it is not failed, it does not use up a slot, and it starts by itself once the server has it.
class SongNotKeptYet implements Exception {
  const SongNotKeptYet();

  @override
  String toString() => 'The server does not keep this song yet';
}

/// Policy the manager reads each time it schedules work.
@immutable
class DownloadPolicy {
  const DownloadPolicy({
    this.wifiOnly = true,
    this.onWifi = true,
    // Each transfer is a server-side transcode: stay gentle on a home server.
    this.maxInFlight = 4,
    this.orphanGrace = const Duration(hours: 24),
    this.limitBytes,
    this.minFreeBytes = StorageGuard.defaultMinFreeBytes,
    this.dataSaver = false,
  });

  final bool wifiOnly;

  /// Data saver is in force (P4-24): the person's switch is on and the phone is on mobile data. A transfer started now is made at the quality
  /// the cap leaves of the wanted one ([qualityFor]); nothing else about downloading changes, and nothing at all while this is false.
  final bool dataSaver;

  /// The quality a transfer is made at: [wanted], held to Data saver quality while [dataSaver] is in force. The pin keeps the person's own
  /// choice; only the copy is lower.
  AudioQuality qualityFor(AudioQuality wanted) =>
      dataSaver ? wanted.cappedForDataSaver() : wanted;

  /// The user's cap for offline music (`null` = none).
  final int? limitBytes;

  /// Free space on the phone that downloads never go below.
  final int minFreeBytes;

  /// The phone is on Wi-Fi/Ethernet right now.
  final bool onWifi;
  final int maxInFlight;
  final Duration orphanGrace;

  bool get mayTransfer => !wifiOnly || onWifi;
}

/// Makes the files on this phone match what the user pinned (ADR-038):
/// reconcile (pure planner) -> apply -> hand work to the transport -> record
/// results. Everything observable goes through the database, so the UI is
/// just streams over `downloads`.
class DownloadManager {
  DownloadManager({
    required AppDatabase db,
    required this.serverId,
    required DownloadsRepository repository,
    required DownloadTransport transport,
    required DownloadUrlBuilder urlBuilder,
    required DownloadPolicy Function() policy,
    DiskSpace? diskSpace,
    Clock clock = const SystemClock(),
  })  : _db = db,
        _repo = repository,
        _transport = transport,
        _urlBuilder = urlBuilder,
        _policy = policy,
        _disk = diskSpace,
        _clock = clock;

  final AppDatabase _db;
  final int serverId;
  final DownloadsRepository _repo;
  final DownloadTransport _transport;
  final DownloadUrlBuilder _urlBuilder;
  final DownloadPolicy Function() _policy;
  final DiskSpace? _disk;
  final Clock _clock;

  final Set<String> _inFlight = <String>{};

  /// Estimated size of each running transfer, for the storage guard.
  final Map<String, int> _estimates = {};
  StorageVerdict _verdict = StorageVerdict.ok;
  final StreamController<StorageVerdict> _verdicts =
      StreamController<StorageVerdict>.broadcast();

  /// Fallback only: the transport reports where each task wrote (B21), which
  /// survives a process restart; this map does not.
  final Map<String, String> _plannedPath = {};
  StreamSubscription<TransferUpdate>? _updates;
  StreamSubscription<List<PinRow>>? _pins;
  Timer? _debounce;
  Future<void> _serial = Future<void>.value();
  bool _disposed = false;

  /// Songs whose address could not be made because the server does not keep them yet, as of this pass: they stay queued, and the next
  /// pass (a pin change, a finished sync, a finished transfer) asks again.
  final Set<String> _waitingForServer = <String>{};

  static String _taskId(int serverId, String trackId) =>
      'enc:$serverId:$trackId';

  String? _trackIdOf(String taskId) {
    final prefix = 'enc:$serverId:';
    return taskId.startsWith(prefix) ? taskId.substring(prefix.length) : null;
  }

  /// Why the queue is not moving, as of the last scheduling pass.
  StorageVerdict get verdict => _verdict;

  /// Changes of [verdict] (the UI shows "downloads paused: ...").
  Stream<StorageVerdict> get verdicts => _verdicts.stream;

  void _setVerdict(StorageVerdict value) {
    if (value == _verdict) return;
    _verdict = value;
    if (!_verdicts.isClosed) _verdicts.add(value);
  }

  /// Starts listening (pins, transport). Safe to call once.
  Future<void> start() async {
    _updates = _transport.updates.listen(_enqueueUpdate);
    await _transport.resume();
    // Rows left "downloading" by a previous run whose task is gone go back
    // to the queue.
    final active = await _transport.activeTaskIds();
    final stuck = await _repo.rowsInState(DownloadState.downloading);
    for (final row in stuck) {
      if (!active.contains(_taskId(serverId, row.trackId))) {
        await _repo.markQueued(row.trackId);
      } else {
        _inFlight.add(row.trackId);
      }
    }
    // A pin that goes (a playlist deleted, a download switched off) is the person's own act: what only it held leaves the phone now. The
    // grace period is for songs that merely left a list that is regenerated (field test 2026-10-31: "x songs downloaded" a day after the
    // playlist was deleted). The first emission is the pins as they were at the start, not an act, and a pin that is only added or written
    // again changes nothing for the songs that left a list: only a pin that is gone counts.
    Set<String>? known;
    _pins = _repo.watchPins().listen((pins) {
      final now = {for (final p in pins) '${p.targetType}:${p.targetId}'};
      final removed = known != null && known!.difference(now).isNotEmpty;
      known = now;
      requestReconcile(immediateRemoval: removed);
    });
    requestReconcile();
  }

  Future<void> dispose() async {
    _disposed = true;
    _debounce?.cancel();
    await _updates?.cancel();
    await _pins?.cancel();
    await _verdicts.close();
  }

  /// Coalesces bursts of triggers (pin edits, sync completions).
  void requestReconcile({bool immediateRemoval = false}) {
    if (_disposed) return;
    // Sticky until the pass runs: a later, ordinary trigger inside the window must not turn the person's removal back into a grace period.
    _removeNow = _removeNow || immediateRemoval;
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), () {
      final now = _removeNow;
      _removeNow = false;
      unawaited(reconcile(immediateRemoval: now));
    });
  }

  bool _removeNow = false;

  /// Transport callbacks join the same FIFO as reconciles, so a completion
  /// can never race with a planning pass.
  void _enqueueUpdate(TransferUpdate update) {
    _serial = _serial.then((_) async {
      try {
        await _onUpdate(update);
      } on Object catch (error, stack) {
        Log.error('downloads', 'update handling failed', error, stack);
      }
    });
  }

  /// Completes when every queued reconcile/update has been handled.
  Future<void> settled() async {
    while (true) {
      final current = _serial;
      await current;
      if (identical(current, _serial)) return;
    }
  }

  /// One full pass. Serialised; never throws.
  Future<void> reconcile({bool immediateRemoval = false}) {
    _serial = _serial.then((_) => _reconcileOnce(immediateRemoval));
    return _serial;
  }

  Future<void> _reconcileOnce(bool immediateRemoval) async {
    if (_disposed) return;
    _waitingForServer.clear();
    try {
      final policy = _policy();
      final desired = await _repo.desired();
      final existing = await _repo.existing();
      final plan = planDownloads(
        desired: desired,
        existing: existing,
        nowMs: _clock.now().millisecondsSinceEpoch,
        graceMs: immediateRemoval ? 0 : policy.orphanGrace.inMilliseconds,
        // A copy that Data saver made smaller is made again at the person's own quality, on Wi-Fi only (P4-24).
        upgradeCapped: policy.onWifi && !policy.dataSaver,
      );
      if (!plan.isEmpty) {
        Log.info('downloads', 'plan: $plan');
        await _repo.applyPlan(plan, desired);
        await _delete(plan.toDelete, existing);
      }
      await _pump();
    } on Object catch (error, stack) {
      Log.error('downloads', 'reconcile failed', error, stack);
    }
  }

  Future<void> _delete(
    List<String> trackIds,
    Map<String, DownloadRow> existing,
  ) async {
    for (final id in trackIds) {
      await _transport.cancel(_taskId(serverId, id));
      _inFlight.remove(id);
      final path = existing[id]?.localPath;
      if (path != null) {
        try {
          await _transport.deleteFile(path);
        } on Object catch (error) {
          Log.warn('downloads', 'could not delete $path', error);
        }
      }
    }
    await _repo.deleteRows(trackIds);
  }

  /// Starts queued rows, up to the in-flight budget and the storage guard.
  Future<void> _pump() async {
    final policy = _policy();
    if (!policy.mayTransfer) return;
    final slots = policy.maxInFlight - _inFlight.length;
    if (slots <= 0) return;
    // Rows already handed to the transport stay `downloading`, so the first
    // `slots` queued rows are always fresh work.
    // Songs waiting for the server are skipped, and do not count against the slots, so the ones behind them still start.
    // A queued upgrade (a copy Data saver made smaller, made again at the person's own quality) is a Wi-Fi job: off Wi-Fi it stays queued, and
    // does not take the place of a song that could start.
    final held = policy.onWifi
        ? const <String>{}
        : {
            for (final row in await _repo.rowsRefreshing())
              if (_isPendingUpgrade(row)) row.trackId
          };
    final queued = [
      for (final row in await _repo.rowsInState(DownloadState.queued,
          limit: slots + _waitingForServer.length + held.length))
        if (!_waitingForServer.contains(row.trackId) &&
            !held.contains(row.trackId))
          row
    ].take(slots).toList();
    if (queued.isEmpty) {
      _setVerdict(StorageVerdict.ok);
      return;
    }

    final waitingBefore = _waitingForServer.length;
    final guard = StorageGuard(
      limitBytes: policy.limitBytes,
      minFreeBytes: policy.minFreeBytes,
    );
    final used = await _repo.usedBytes();
    final free = await _disk?.freeBytes();
    var running = 0;
    for (final id in _inFlight) {
      running += _estimates[id] ?? 0;
    }

    for (final row in queued) {
      if (_disposed) return;
      if (_inFlight.length >= policy.maxInFlight) break;
      if (_inFlight.contains(row.trackId)) continue;

      final next = await _estimateFor(row, policy);
      final verdict = guard.check(
        usedBytes: used,
        inFlightBytes: running,
        nextBytes: next,
        freeBytes: free,
      );
      if (verdict != StorageVerdict.ok) {
        // The rest of the queue stays queued (not failed): it resumes when
        // the limit is raised or space is freed.
        Log.info(
            'downloads',
            'paused: $verdict '
                '(used=$used running=$running free=$free)');
        _setVerdict(verdict);
        return;
      }
      await _startOne(row, policy);
      if (_inFlight.contains(row.trackId)) {
        _estimates[row.trackId] = next;
        running += next;
      }
    }
    _setVerdict(StorageVerdict.ok);
    // Rows found waiting just now took the places of ones that could have started: look at the rows behind them.
    if (_waitingForServer.length > waitingBefore) await _pump();
  }

  /// The quality a transfer of [row] is asked at, as recorded: a refresh of a copy is asked at `refreshQuality` (the copy keeps its own
  /// `quality` until the new file is in place); a first download is made at `quality`.
  AudioQuality _transferQuality(DownloadRow row) =>
      AudioQuality.byId(row.refreshQuality ?? row.quality);

  bool _isRefresh(DownloadRow row) =>
      row.localPath != null && row.localPath!.isNotEmpty;

  /// A refresh that would give a copy a higher quality than it has: Data saver's copy made again at the person's own choice.
  bool _isPendingUpgrade(DownloadRow row) =>
      _isRefresh(row) &&
      row.refreshQuality != null &&
      _transferQuality(row).rank > AudioQuality.byId(row.quality).rank;

  Future<int> _estimateFor(DownloadRow row, DownloadPolicy policy) async {
    final track = await (_db.select(_db.tracks)
          ..where(
              (t) => t.serverId.equals(serverId) & t.id.equals(row.trackId)))
        .getSingleOrNull();
    return estimateDownloadBytes(
      quality: policy.qualityFor(_transferQuality(row)),
      sourceSize: track?.size,
      durationSec: track?.durationSec,
      sourceBitRate: track?.bitRate,
    );
  }

  Future<void> _startOne(DownloadRow row, DownloadPolicy policy) async {
    final track = await (_db.select(_db.tracks)
          ..where(
              (t) => t.serverId.equals(serverId) & t.id.equals(row.trackId)))
        .getSingleOrNull();
    if (track == null || track.deletedAtMs != null) {
      await _repo.markFailed(row.trackId, 'Track is no longer on the server');
      return;
    }
    final wanted = _transferQuality(row);
    // Data saver in force: the copy is made at the capped quality, and the row says so from now on (the completion, a restart and the storage
    // guard all read it back). The pin keeps the person's own choice.
    final quality = policy.qualityFor(wanted);
    final upgrade =
        _isRefresh(row) && quality.rank > AudioQuality.byId(row.quality).rank;
    try {
      if (quality != wanted) {
        await _repo.setTransferQuality(row.trackId,
            quality: quality.id, refresh: _isRefresh(row));
      }
      final url = await _urlBuilder(
        row.trackId,
        quality: quality,
        sourceSuffix: track.suffix,
        sourceBitRate: track.bitRate,
      );
      // A refresh downloads next to the old copy and swaps afterwards.
      final target = _relativeFor(row, track.suffix, quality);
      _plannedPath[row.trackId] = target;
      _inFlight.add(row.trackId);
      await _repo.markDownloading(row.trackId);
      await _transport.start(TransferRequest(
        taskId: _taskId(serverId, row.trackId),
        url: url,
        relativePath: target,
        // An upgrade is only ever fetched on Wi-Fi, whatever the person allowed for downloads: if the link changes mid-way it waits instead of
        // going on over mobile data at full quality.
        requiresWifi: policy.wifiOnly || upgrade,
      ));
    } on SongNotKeptYet {
      _inFlight.remove(row.trackId);
      _waitingForServer.add(row.trackId);
    } on Object catch (error) {
      _inFlight.remove(row.trackId);
      await _repo.markFailed(row.trackId, '$error');
    }
  }

  /// Where a download of [row] is written: `downloads/<server>/<track>.<ext>`,
  /// with `.new` appended while a refresh sits next to the copy it replaces.
  String _relativeFor(
      DownloadRow row, String? sourceSuffix, AudioQuality quality) {
    final ext = quality.fileExtension(sourceSuffix: sourceSuffix);
    final base = 'downloads/$serverId/${row.trackId}.$ext';
    return _isRefresh(row) ? '$base.new' : base;
  }

  Future<void> _onUpdate(TransferUpdate update) async {
    final trackId = _trackIdOf(update.taskId);
    if (trackId == null || _disposed) return;
    switch (update.status) {
      case TransferStatus.complete:
        await _onComplete(trackId, update.relativePath);
      case TransferStatus.failed:
        _inFlight.remove(trackId);
        final reason = update.error ?? 'Download failed';
        final rows = await _repo.rowsFor([trackId]);
        if (rows.isNotEmpty && _isRefresh(rows.first)) {
          // A refresh that did not arrive (an upgrade of a Data saver copy, or a changed song) leaves the copy that is on the phone playable:
          // it is not a failed download, and the old file is never lost to a retry (a first download is retried from scratch, a refresh is not).
          final partial = _plannedPath.remove(trackId);
          if (partial != null) {
            await _transport.deleteFile(await _transport.absolutePath(partial));
          }
          await _giveUp(trackId, true, reason);
        } else {
          await _repo.markFailed(trackId, reason);
          await _pump();
        }
      case TransferStatus.canceled:
        _inFlight.remove(trackId);
      case TransferStatus.enqueued:
      case TransferStatus.running:
      case TransferStatus.paused:
        break;
    }
  }

  Future<void> _onComplete(String trackId, String? reportedPath) async {
    _inFlight.remove(trackId);
    final planned = _plannedPath.remove(trackId);
    final rows = await _repo.rowsFor([trackId]);
    final track = await (_db.select(_db.tracks)
          ..where((t) => t.serverId.equals(serverId) & t.id.equals(trackId)))
        .getSingleOrNull();
    if (rows.isEmpty) {
      // Unpinned while it was downloading: throw the file away.
      final path = reportedPath ?? planned;
      if (path != null) {
        await _transport.deleteFile(await _transport.absolutePath(path));
      }
      return;
    }
    final row = rows.first;
    // The task knows where it wrote, even after the app was killed (B21).
    final made = _transferQuality(row);
    final relative =
        reportedPath ?? planned ?? _relativeFor(row, track?.suffix, made);
    final absolute = await _transport.absolutePath(relative);
    final isRefresh = relative.endsWith('.new');

    final size = await _transport.fileSize(absolute);
    final reason = size == null
        ? 'Downloaded file is empty'
        : verifyDownload(
            path: absolute,
            size: size,
            head: await _transport.readHead(absolute, 16),
            expectedBytes: track?.size,
            original: made.isOriginal,
          );
    if (size == null || reason != null) {
      await _transport.deleteFile(absolute);
      await _giveUp(trackId, isRefresh, reason ?? 'Downloaded file is empty');
      return;
    }

    var finalPath = absolute;
    if (isRefresh) {
      finalPath = absolute.substring(0, absolute.length - '.new'.length);
      try {
        // One step: the old copy is replaced or left alone, never missing.
        await _transport.rename(absolute, finalPath);
      } on Object catch (error) {
        Log.warn('downloads', 'swap failed for $trackId', error);
        await _transport.deleteFile(absolute);
        await _giveUp(trackId, true, 'Could not replace the old copy');
        return;
      }
      final old = row.localPath;
      if (old != null && old != finalPath) {
        await _transport.deleteFile(old);
      }
    }

    await _repo.markDone(
      trackId,
      localPath: finalPath,
      bytes: size,
      audioKey: track?.audioKey ?? '',
      // What the file is made at: the quality the transfer was asked at (Data saver may have lowered the wanted one), recorded for the upgrade.
      quality: made.id,
    );
    await _pump();
  }

  /// A finished transfer that cannot be kept. A refresh leaves the old copy
  /// playable; a first download is a failure with a back-off.
  Future<void> _giveUp(String trackId, bool isRefresh, String reason) async {
    if (isRefresh) {
      await _repo.restoreDone(trackId, reason);
    } else {
      await _repo.markFailed(trackId, reason);
    }
    await _pump();
  }

  /// Retry failed rows now (user pressed "Try again").
  Future<void> retryFailed() async {
    final failed = await _repo.rowsInState(DownloadState.failed);
    for (final row in failed) {
      await _repo.markQueued(row.trackId);
    }
    await reconcile();
  }

  @visibleForTesting
  Set<String> get debugInFlight => Set.unmodifiable(_inFlight);
}
