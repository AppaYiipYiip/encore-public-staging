import 'dart:async';

import 'package:drift/drift.dart';
import 'package:flutter/foundation.dart';

import '../../core/clock.dart';
import '../../core/logger.dart';
import '../../domain/audio_quality.dart';
import '../../domain/download_line.dart' show kDownloadStoppedReason;
import '../../domain/storage_guard.dart';
import '../db/app_database.dart';
import '../repos/downloads_repository.dart';
import 'disk_space.dart';
import 'download_planner.dart';
import 'download_transport.dart';
import 'download_verify.dart';

export '../../domain/download_line.dart' show kDownloadStoppedReason;

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

  /// True while [start] counts what the downloader still runs: nothing is handed to the downloader before that is done, or the in-flight limit
  /// (`DownloadPolicy.maxInFlight`) would be counted from an empty set while songs run, and [start] would wait for the server's addresses.
  bool _starting = false;

  /// Songs whose address could not be made because the server does not keep them yet, as of this pass: they stay queued, and the next
  /// pass (a pin change, a finished sync, a finished transfer) asks again.
  final Set<String> _waitingForServer = <String>{};

  /// For each task id, how many attempts the person's own Stop interrupted whose LAST word has not come yet (N-39, review of PR 119). The downloader
  /// ends a task it cancels with a last word (`canceled` for a cancel that reached it; `failed` or `complete` when the transfer ended in the very moment
  /// of the cancel; for an id that was cancelled before it may send more than one `canceled`, which the second layer absorbs while the song is stopped
  /// and N-45 makes exact), and it can arrive AFTER Resume has started the song again under the same task id: a word about the old attempt, read against a row
  /// that says "downloading" for the new one. Without this it was read as a cancel from outside: the new transfer's row failed with a back-off, and the
  /// place it gave away let another song start over the limit. A word spends one, the first that comes (see [_spendStoppedAttempt]); in memory only: a
  /// word that outlives the process is replayed to a manager that starts with the row stopped, and the task id per attempt in the row (N-45) is what
  /// would make this exact for good. Bounded: one entry per attempt that was in flight at a Stop, gone with its word.
  final Map<String, int> _stoppedAttempts = {};

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
    // What the downloader kept while the app was not running (a finished file, a cancel pressed on a card of an older build) is handled first: it
    // says why a row's task is gone, and the rows whose task is gone with no word at all are only then put back in the queue (N-39: a cancelled song
    // was started again by the next start of the app).
    // The replayed updates end a finished or cancelled song with a pass over the queue: no pass hands anything out before the loop below has
    // counted the tasks that still run (a replayed song that finished or was cancelled used to start four more beside the two that were running).
    _starting = true;
    try {
      await settled();
      // Rows left "downloading" by a previous run whose task is gone go back
      // to the queue.
      final active = await _transport.activeTaskIds();
      // A song the person stopped is never fetched: a task that a kill left running for a song that is held (a kill between the Stop being stored and
      // its cancel, or a song that became held after the Stop, see [_holdBackTransfers]) is cancelled now, and its row is put where a held song stands
      // FIRST, so its answer finds a row that is not downloading and changes nothing (a refresh in flight is the old copy again, not a queued row).
      final stopped = await _repo.heldTrackIds();
      final running = [
        for (final id in active)
          if (stopped.contains(_trackIdOf(id))) id
      ];
      await _repo.parkHeld([for (final id in running) _trackIdOf(id)!]);
      for (final id in running) {
        active.remove(id);
        await _cancelForStop(id);
      }
      final stuck = await _repo.rowsInState(DownloadState.downloading);
      for (final row in stuck) {
        if (!active.contains(_taskId(serverId, row.trackId))) {
          await _repo.markQueued(row.trackId);
        } else {
          _inFlight.add(row.trackId);
        }
      }
    } finally {
      _starting = false;
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
    _stoppedAttempts.clear();
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
    final suffixes = await _suffixesOf(trackIds);
    for (final id in trackIds) {
      await _transport.cancel(_taskId(serverId, id));
      // The song is gone, so is the attempt of it the Stop interrupted: no word of it matters now, and one kept would shield the next attempt of the
      // same task id from a real cancel.
      _stoppedAttempts.remove(_taskId(serverId, id));
      _inFlight.remove(id);
      final path = existing[id]?.localPath;
      if (path != null) {
        try {
          await _transport.deleteFile(path);
        } on Object catch (error) {
          Log.warn('downloads', 'could not delete $path', error);
        }
      }
      await _deleteRefreshLeftovers(id, copyPath: path, suffix: suffixes[id]);
    }
    await _repo.deleteRows(trackIds);
  }

  /// The source suffix of each of these songs (what a download of it at the original quality is named by).
  Future<Map<String, String?>> _suffixesOf(List<String> trackIds) async {
    final result = <String, String?>{};
    for (var from = 0; from < trackIds.length; from += 500) {
      final to = from + 500 > trackIds.length ? trackIds.length : from + 500;
      final rows = await (_db.select(_db.tracks)
            ..where((t) =>
                t.serverId.equals(serverId) &
                t.id.isIn(trackIds.sublist(from, to))))
          .get();
      for (final row in rows) {
        result[row.id] = row.suffix;
      }
    }
    return result;
  }

  /// REMOVE is the one path that deletes (N-39), so it takes the half-made `.new` file of a refresh too: a Stop that came in the middle of one leaves
  /// it on the phone (a Stop deletes nothing), and nothing else would ever delete it. Only files of THIS song, only the names this manager can have
  /// written: the one it planned in this process, the copy's own name with `.new`, and the name for each extension a transfer of the song is made
  /// with (a refresh at another quality is named by another extension). After a restart the manager's plan is gone and the row no longer says
  /// what the refresh asked for (a Stop ends it), so the names are worked out, not remembered; a name with no file behind it deletes nothing.
  Future<void> _deleteRefreshLeftovers(String trackId,
      {String? copyPath, String? suffix}) async {
    final candidates = <String>{};
    final planned = _plannedPath.remove(trackId);
    if (planned != null && planned.endsWith('.new')) {
      candidates.add(await _transport.absolutePath(planned));
    }
    // Only a song that has a copy can have a refresh in progress.
    if (copyPath != null && copyPath.isNotEmpty) {
      candidates.add('$copyPath.new');
      final base = _relativeBase(trackId);
      for (final ext in {
        for (final q in AudioQuality.values)
          q.fileExtension(sourceSuffix: suffix)
      }) {
        candidates.add(await _transport.absolutePath('$base.$ext.new'));
      }
    }
    for (final file in candidates) {
      try {
        if (await _transport.fileSize(file) != null) {
          await _transport.deleteFile(file);
        }
      } on Object catch (error) {
        Log.warn('downloads', 'could not delete $file', error);
      }
    }
  }

  /// Starts queued rows, up to the in-flight budget and the storage guard.
  Future<void> _pump() async {
    // The pass that ends [start] hands the work out, once the tasks that still run are counted.
    if (_starting) return;
    final policy = _policy();
    // THE INVARIANT comes before anything that can end the pass early (no connection, every place taken): a held song has no live transfer.
    final stopped = await _repo.heldTrackIds();
    await _holdBackTransfers(stopped);
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
    // Songs the person's Stop holds (N-39) are queued rows too, and nothing starts them: not this pass, not a restart, not a sync. They do not use
    // up the places, so the rows behind them still start.
    final queued = [
      for (final row in await _repo.rowsInState(DownloadState.queued,
          limit:
              slots + _waitingForServer.length + held.length + stopped.length))
        if (!_waitingForServer.contains(row.trackId) &&
            !held.contains(row.trackId) &&
            !stopped.contains(row.trackId))
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
        // The downloader keeps it with the task and hands it back with the last word: what the file IS, whatever the row says by then.
        qualityId: quality.id,
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
    final base = '${_relativeBase(row.trackId)}.$ext';
    return _isRefresh(row) ? '$base.new' : base;
  }

  /// The name of a song's file without its extension: one place for what a download writes and what Remove looks for.
  String _relativeBase(String trackId) => 'downloads/$serverId/$trackId';

  Future<void> _onUpdate(TransferUpdate update) async {
    final trackId = _trackIdOf(update.taskId);
    if (trackId == null || _disposed) return;
    switch (update.status) {
      case TransferStatus.complete:
        // The cancel lost the race to the file: this IS the last word of the attempt the Stop interrupted. A finished file is a song, never swallowed
        // (a swallowed word that was the new attempt's own would leave its row "downloading" with no task, the bug N-39 is about): it is spent and
        // handled as a completion. When Resume has started the song again since, the transfer that runs now (same task id) is work already done: it is
        // cancelled the way the Stop cancels (its own last word is remembered and swallowed) BEFORE the completion hands its place to the next song,
        // or the pump would start one song more than the limit beside it (measured in the stop test, and a place that was kept for it would never be
        // given back: the completion of a song that already has its copy is ignored as a stale word). What else an old word can do to a newer attempt
        // of the same id is N-45's (a task id per attempt in the row).
        if (_spendStoppedAttempt(update.taskId) &&
            _inFlight.contains(trackId)) {
          await _cancelForStop(update.taskId);
        }
        await _onComplete(trackId, update.relativePath,
            qualityId: update.qualityId);
      case TransferStatus.failed:
        // FIRST layer, before anything is touched (the place of a transfer that runs is [_inFlight]'s): the transfer the Stop cancelled failed in the
        // very moment of the cancel, and its last word is this one. It is not a failed song with a wait, deletes nothing, and a song Resume has
        // started again since keeps its place and its row.
        if (_spendStoppedAttempt(update.taskId)) return;
        _inFlight.remove(trackId);
        // The song waits for Resume and this transfer ended with nothing owed to our own Stop for it (the pass that would have cancelled it had not
        // run yet, or the downloader had no such task when it did): not a failed song with a wait, and it deletes nothing (not the half of a refresh
        // either). The row must not stay "downloading" with no task behind it: it goes where a held song stands, and Resume starts it.
        if (await _isStopped(trackId)) return _endedForHeldSong(trackId);
        await _onAttemptEnded(trackId, update.error ?? 'Download failed',
            reportedPath: update.relativePath);
      case TransferStatus.canceled:
        // FIRST layer, before anything is touched: the acknowledgement of the cancel the person's Stop sent is the last word of the attempt it
        // interrupted. It may arrive after Resume has started the song again under the same task id: it is then no cancel from outside, and it must
        // not give away the place of the transfer that runs (`_inFlight`) nor fail its row. Exactly one word is spent for each cancel sent.
        if (_spendStoppedAttempt(update.taskId)) return;
        _inFlight.remove(trackId);
        // Second layer, for a word that is not the acknowledgement of a Stop's cancel (one of something else, or one after the memory above was
        // spent): the Stop is stored first and the row no longer says "downloading", so the branch below would not see it either; this stays right
        // if a row ever does. It also catches a word that is not about any cancel of ours and reaches a song that is held (see [_endedForHeldSong]).
        if (await _isStopped(trackId)) return _endedForHeldSong(trackId);
        // The manager cancels in one place, `_delete`, and deletes the row in the same pass (the update is handled after it): no row. A row that
        // still says "downloading" was cancelled by something else (the Cancel button of the downloader's card of an older build, a reset of the
        // downloader, an update the downloader kept while the app was closed), and no task is behind it any more. It is an attempt that ended, not a
        // download that never does: it was forgotten here, so the pin and the card waited for ever, the place stayed empty and the next start of the
        // app started the song again at once (N-39, audit row B-134). It is a failed attempt with its back-off: not started again at once, not in a
        // loop, and "Try again" starts it now. A row in any other state is waiting for nothing: a stale word changes nothing.
        final rows = await _repo.rowsFor([trackId]);
        if (rows.isNotEmpty && rows.first.state == DownloadState.downloading) {
          await _onAttemptEnded(trackId, kDownloadStoppedReason,
              reportedPath: update.relativePath);
        }
      case TransferStatus.enqueued:
      case TransferStatus.running:
      case TransferStatus.paused:
        break;
    }
  }

  /// A transfer that ended without a file. A refresh (an upgrade of a Data saver copy, or a changed song) leaves the copy that is on the phone
  /// playable: it is not a failed download, and the old file is never lost to a retry (a first download is retried from scratch, a refresh is not).
  Future<void> _onAttemptEnded(String trackId, String reason,
      {String? reportedPath}) async {
    final rows = await _repo.rowsFor([trackId]);
    if (rows.isNotEmpty && _isRefresh(rows.first)) {
      // The half-made `.new` file: where this process planned it, or where the task says it wrote (the downloader tells it with every update, also
      // for a task of a process that has ended). Only a `.new` path is ever deleted here: the copy that is on the phone is not.
      final partial = _plannedPath.remove(trackId) ??
          (reportedPath != null && reportedPath.endsWith('.new')
              ? reportedPath
              : null);
      if (partial != null) {
        await _transport.deleteFile(await _transport.absolutePath(partial));
      }
      await _giveUp(trackId, true, reason);
    } else {
      await _repo.markFailed(trackId, reason);
      await _pump();
    }
  }

  Future<void> _onComplete(String trackId, String? reportedPath,
      {String? qualityId}) async {
    final rows = await _repo.rowsFor([trackId]);
    // A song that has a copy on the phone (a refresh in flight, one waiting in the queue, or a song that is done) is only ever completed by a `.new`
    // file. A completion that names another file is the copy that is on the phone, from the acknowledgement of an older task with the same id (item
    // N-45): it is not about any transfer that runs, and it must neither check that copy against what the refresh asked for and delete it when it does
    // not pass, nor record the refresh as made, nor give away the place of a transfer that still runs. Found on 17 Nov 2026 while looking for every
    // other place that deletes, after the review's `.new` guard of `_onAttemptEnded`; a second layer that stays correct once a task id per attempt
    // (N-45) keeps such words from arriving.
    if (rows.isNotEmpty &&
        _isRefresh(rows.first) &&
        reportedPath != null &&
        !reportedPath.endsWith('.new')) {
      Log.warn('downloads',
          'ignored a completion that names the copy on the phone, not the refresh of $trackId');
      return;
    }
    _inFlight.remove(trackId);
    final planned = _plannedPath.remove(trackId);
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
    // The task knows where it wrote, even after the app was killed (B21), and what it was asked at: the downloader keeps both with the task. What a
    // refresh made is what the FILE is. The row's own reading (`refreshQuality`, else `quality`) is only the fallback for a task handed over without
    // one: by the time a refresh completes the row may no longer say what it was asked at (the person's Stop ended its intent, `refreshQuality` is null
    // again), and the old copy's quality was recorded for the new file; the next pass planned the upgrade again and fetched it twice (N-39, review of PR
    // 119, round 2).
    final made = AudioQuality.byId(qualityId, fallback: _transferQuality(row));
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

  /// Whether the person's Stop holds this song (every pin that wants it is stopped).
  Future<bool> _isStopped(String trackId) async =>
      (await _repo.heldTrackIds()).contains(trackId);

  /// THE INVARIANT: A HELD SONG HAS NO LIVE TRANSFER (N-39, review of PR 119, round 2). The Stop cancels the transfers of the songs held AT ITS
  /// MOMENT, but a song can become held later: its other pin goes away (a one-song Remove), it joins a stopped release, a sync takes it out of the
  /// playlist that wanted it. Its transfer would then run for a song nothing wants fetched, and its last word (failed, canceled) would find a row nobody
  /// ends. So every pass, the reconcile and the pump alike, ends such a transfer the way the Stop does: the row goes where a held song stands (stored
  /// FIRST, so the cancel's answer never finds a row that says "downloading"), then the task is cancelled through the same counted path
  /// ([_cancelForStop]: its own `canceled` is the one acknowledgement it owes, spent once). Runs before anything that can end the pass early.
  Future<void> _holdBackTransfers(Set<String> held) async {
    if (held.isEmpty || _inFlight.isEmpty) return;
    final running = [
      for (final id in _inFlight)
        if (held.contains(id)) id
    ];
    if (running.isEmpty) return;
    Log.info('downloads',
        'held songs still had a transfer: ${running.length} cancelled');
    await _repo.parkHeld(running);
    await _cancelHeld(running);
  }

  /// Gives up the place of each of these songs that is in flight and cancels its transfer through the counted path (the Stop, and
  /// [_holdBackTransfers]). The rows are already where a held song stands.
  Future<void> _cancelHeld(Iterable<String> trackIds) async {
    for (final id in trackIds) {
      _estimates.remove(id);
      if (_inFlight.remove(id)) await _cancelForStop(_taskId(serverId, id));
    }
  }

  /// The last word of a transfer that ended for a song that is held, with nothing owed to our own Stop for it (the second layer under
  /// [_holdBackTransfers]): the pass that cancels such a transfer had not run yet, or the downloader had no such task when it did (the transfer had
  /// ended on its own: nothing was promised for that cancel). It is not a failed song with a wait and deletes nothing; the song waits for Resume, so the
  /// row goes where a held song stands (not "downloading" with no task behind it, which nothing ends: the next start of the app was the only thing that
  /// did), its place is free for the next song, and Resume starts it. The word is not proof that the task is over: the downloader sends one `canceled`
  /// for EVERY unfinished work it holds under a task id that was cancelled before (see `DownloadTransport.cancel`), and a word of an older attempt can
  /// come while the newest still runs. So a transfer that is still live for the held song is cancelled here through the counted path before its place
  /// goes to another song (nothing is sent, and nothing is owed, when the downloader has no such task): the place is never handed on while the task
  /// still runs, which would put one transfer over the limit.
  Future<void> _endedForHeldSong(String trackId) async {
    _estimates.remove(trackId);
    await _repo.parkHeld([trackId]);
    await _cancelForStop(_taskId(serverId, trackId));
    await _pump();
  }

  /// Spends one of the Stop's memories of [taskId] (see [_stoppedAttempts]): `true` when the word that is being handled is the last word of an
  /// attempt the Stop interrupted.
  bool _spendStoppedAttempt(String taskId) {
    final left = _stoppedAttempts[taskId];
    if (left == null) return false;
    if (left <= 1) {
      _stoppedAttempts.remove(taskId);
    } else {
      _stoppedAttempts[taskId] = left - 1;
    }
    return true;
  }

  /// Cancels the transfer of a song the person's Stop holds and remembers that a last word of that attempt is still to come (see
  /// [_stoppedAttempts]). Called for a task that is believed to be in flight (a song in [_inFlight], a task the downloader still lists), and by
  /// [_endedForHeldSong] for a task whose word just arrived and that may well be over: then the downloader answers that it has no such task, nothing is
  /// sent and nothing stays owed. The memory is written BEFORE the cancel (the start of the app does not wait in the FIFO, so a word can be handled while the cancel is still on its
  /// way) and is taken back when the downloader says it had no such task: nothing was sent, no word will come, and a memory kept for it would
  /// swallow the next attempt's own failure and leave its row "downloading" with no task behind it. The same when the cancel itself fails: nobody
  /// knows whether a word is coming, and a failed song with a wait (Retry is there) is the failure that can be seen and mended, a stuck row is not.
  Future<void> _cancelForStop(String taskId) async {
    final before = _stoppedAttempts[taskId] ?? 0;
    _stoppedAttempts[taskId] = before + 1;
    var promised = false;
    try {
      promised = await _transport.cancel(taskId);
    } on Object catch (error) {
      // The song is held and its answers are ignored, so a cancel that did not go through changes nothing else here.
      Log.warn('downloads', 'could not cancel $taskId', error);
    }
    // Only our own memory is taken back: one that a word spent in the meantime is already gone (the count is back to what it was).
    if (!promised && (_stoppedAttempts[taskId] ?? 0) > before) {
      _spendStoppedAttempt(taskId);
    }
  }

  /// One step of the FIFO that hands its failure to the caller instead of breaking the chain behind it.
  Future<void> _serialized(Future<void> Function() body) async {
    Object? failure;
    final step = _serial.then((_) async {
      try {
        await body();
      } on Object catch (error, stack) {
        Log.error('downloads', 'a step of the person failed', error, stack);
        failure = error;
      }
    });
    _serial = step;
    await step;
    final error = failure;
    if (error != null) throw error;
  }

  /// THE PERSON'S STOP (N-39): the phone's copy of these pins stops and waits for [resume]. The files on the phone stay and play and NOTHING is
  /// deleted (Remove is the one thing that deletes). In this order, inside the FIFO: the stop is stored in the pins and the songs it holds are put
  /// out of the way (a song in flight goes back to the queue, a refresh in flight is the old copy again) and only then are their transfers
  /// cancelled, so the downloader's acknowledgement is never read as a cancel from outside (PR 113's back-off, PB-F22). From then on no pass, restart,
  /// sync, reconnection or passing of time starts, refreshes or tries again a song that every pin that wants it has stopped. Songs added to a stopped
  /// list wait too. Stopping again changes nothing; the first moment is kept. It throws only when the stop could not be stored (nothing changed).
  Future<void> stop(Iterable<PinKey> pins) {
    final keys = pins.toList();
    return _serialized(() async {
      if (_disposed) return;
      final held = await _repo.stopPins(keys);
      await _cancelHeld(held);
    });
  }

  /// Takes the Stop off these pins and plans again: the songs that were not on the phone are asked for, in their old order, and the ones added
  /// while it was stopped follow them.
  Future<void> resume(Iterable<PinKey> pins) {
    final keys = pins.toList();
    return _serialized(() async {
      if (_disposed) return;
      await _repo.clearStopped(keys);
      await _reconcileOnce(false);
    });
  }

  /// Retry failed rows now (user pressed "Try again"). A song of a download the person stopped is left as it is: it stays counted as one that did
  /// not come, and Retry is back after Resume.
  Future<void> retryFailed() async {
    final stopped = await _repo.heldTrackIds();
    final failed = await _repo.rowsInState(DownloadState.failed);
    for (final row in failed) {
      if (stopped.contains(row.trackId)) continue;
      await _repo.markQueued(row.trackId);
    }
    await reconcile();
  }

  @visibleForTesting
  Set<String> get debugInFlight => Set.unmodifiable(_inFlight);

  @visibleForTesting
  Map<String, int> get debugStoppedAttempts =>
      Map.unmodifiable(_stoppedAttempts);
}
