import 'dart:async';

import '../../core/logger.dart';
import '../../data/db/app_database.dart';
import 'playback_facade.dart';

/// Lets the UI start immediately while the audio engine initialises in the
/// background (startup budget, R-03/R-07): state is "idle" until the inner
/// facade is ready; commands wait for it.
class DeferredPlaybackFacade implements PlaybackFacade {
  DeferredPlaybackFacade(Future<PlaybackFacade> inner) {
    _ready = inner.then<PlaybackFacade>(_attach).catchError(_startFailed);
  }

  PlaybackFacade _attach(PlaybackFacade f) {
    _inner = f;
    // Disposed before the engine arrived: nothing may subscribe to it now (the
    // four subscriptions below used to be added anyway and leaked; B13).
    if (_disposed) return f;
    _snapshot = f.snapshot;
    _queue = f.queue;
    _sleep = f.sleepTimer;
    _subs
      ..add(f.snapshots.listen((s) {
        _snapshot = s;
        if (!_snapshots.isClosed) _snapshots.add(s);
      }))
      ..add(f.queueStream.listen((q) {
        _queue = q;
        if (!_queues.isClosed) _queues.add(q);
      }))
      ..add(f.sleepTimerStream.listen((s) {
        _sleep = s;
        if (!_sleeps.isClosed) _sleeps.add(s);
      }))
      ..add(f.notices.listen((n) {
        if (!_noticeStream.isClosed) _noticeStream.add(n);
      }));
    if (!_snapshots.isClosed) _snapshots.add(_snapshot);
    if (!_queues.isClosed) _queues.add(_queue);
    if (!_sleeps.isClosed) _sleeps.add(_sleep);
    return f;
  }

  /// The engine could not start (damaged data, a platform failure). The UI
  /// stays up with a quiet player and one plain notice; commands do not throw
  /// into the screens (B14).
  PlaybackFacade _startFailed(Object error, StackTrace stack) {
    Log.error('playback', 'the playback engine did not start', error, stack);
    final quiet = NoopPlaybackFacade();
    _inner = quiet;
    if (!_noticeStream.isClosed) {
      _noticeStream.add(const PlaybackNotice(
        'Playback is not available right now. Close the app and open it again.',
        isError: true,
      ));
    }
    return quiet;
  }

  late final Future<PlaybackFacade> _ready;
  PlaybackFacade? _inner;
  bool _disposed = false;
  final List<StreamSubscription<Object?>> _subs = [];
  PlaybackSnapshot _snapshot = PlaybackSnapshot.idle;
  QueueSnapshot _queue = QueueSnapshot.empty;
  SleepTimerStatus _sleep = SleepTimerStatus.off;
  final StreamController<PlaybackSnapshot> _snapshots =
      StreamController<PlaybackSnapshot>.broadcast();
  final StreamController<QueueSnapshot> _queues =
      StreamController<QueueSnapshot>.broadcast();
  final StreamController<SleepTimerStatus> _sleeps =
      StreamController<SleepTimerStatus>.broadcast();
  final StreamController<PlaybackNotice> _noticeStream =
      StreamController<PlaybackNotice>.broadcast();

  @override
  PlaybackSnapshot get snapshot => _snapshot;

  @override
  Stream<PlaybackSnapshot> get snapshots => _snapshots.stream;

  @override
  Stream<Duration> get positionStream async* {
    final f = await _ready;
    yield* f.positionStream;
  }

  @override
  QueueSnapshot get queue => _queue;

  @override
  Stream<QueueSnapshot> get queueStream => _queues.stream;

  @override
  SleepTimerStatus get sleepTimer => _sleep;

  @override
  Stream<SleepTimerStatus> get sleepTimerStream => _sleeps.stream;

  @override
  Stream<PlaybackNotice> get notices => _noticeStream.stream;

  @override
  double get speed => _inner?.speed ?? 1;

  @override
  Future<void> playTracks(
    List<TrackRow> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
    bool shuffle = false,
    bool skipUnavailable = false,
  }) async =>
      (await _ready).playTracks(tracks,
          startIndex: startIndex,
          sourceName: sourceName,
          sourceId: sourceId,
          shuffle: shuffle,
          skipUnavailable: skipUnavailable);

  @override
  Future<void> togglePlayPause() async => (await _ready).togglePlayPause();
  @override
  Future<void> play() async => (await _ready).play();
  @override
  Future<void> pause() async => (await _ready).pause();
  @override
  Future<void> seek(Duration position) async => (await _ready).seek(position);
  @override
  Future<void> skipNext() async => (await _ready).skipNext();
  @override
  Future<void> skipPrevious() async => (await _ready).skipPrevious();
  // Not futures, so they used to be dropped before the engine was ready, while
  // every other command waited: now they wait too, in order (B13).
  @override
  void toggleShuffle() {
    final inner = _inner;
    if (inner != null) {
      inner.toggleShuffle();
    } else {
      unawaited(_ready.then((f) => f.toggleShuffle()));
    }
  }

  @override
  void cycleRepeat() {
    final inner = _inner;
    if (inner != null) {
      inner.cycleRepeat();
    } else {
      unawaited(_ready.then((f) => f.cycleRepeat()));
    }
  }

  @override
  void setRepeat(RepeatKind kind) {
    final inner = _inner;
    if (inner != null) {
      inner.setRepeat(kind);
    } else {
      unawaited(_ready.then((f) => f.setRepeat(kind)));
    }
  }

  @override
  Future<void> addToQueue(TrackRow track) async =>
      (await _ready).addToQueue(track);
  @override
  Future<void> playNext(TrackRow track) async => (await _ready).playNext(track);
  @override
  Future<void> playStreamed(
    List<StreamedTrack> tracks, {
    int startIndex = 0,
    String? sourceName,
    String? sourceId,
  }) async =>
      (await _ready).playStreamed(tracks,
          startIndex: startIndex, sourceName: sourceName, sourceId: sourceId);
  @override
  Future<void> addStreamToQueue(StreamedTrack track) async =>
      (await _ready).addStreamToQueue(track);
  @override
  Future<void> jumpToQueueIndex(int index) async =>
      (await _ready).jumpToQueueIndex(index);
  @override
  Future<void> removeFromQueue(int index) async =>
      (await _ready).removeFromQueue(index);
  @override
  Future<void> moveInQueue(int from, int to) async =>
      (await _ready).moveInQueue(from, to);
  @override
  Future<void> clearUpNext() async => (await _ready).clearUpNext();
  @override
  Future<void> stopAndClear() async => (await _ready).stopAndClear();
  @override
  Future<void> setSleepTimer(Duration? duration) async =>
      (await _ready).setSleepTimer(duration);
  @override
  Future<void> setSleepAtEndOfTrack(bool enabled) async =>
      (await _ready).setSleepAtEndOfTrack(enabled);
  @override
  Future<void> setSpeed(double speed) async => (await _ready).setSpeed(speed);

  Future<void> dispose() async {
    _disposed = true;
    for (final s in _subs) {
      await s.cancel();
    }
    await _snapshots.close();
    await _queues.close();
    await _sleeps.close();
    await _noticeStream.close();
  }
}
