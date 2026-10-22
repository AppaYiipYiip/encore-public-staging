import 'dart:async';
import 'dart:math';

import 'package:meta/meta.dart';

import '../../core/clock.dart';
import '../../core/logger.dart';
import '../../core/result.dart';
import 'endpoint_resolver.dart';
import 'sync_engine.dart';

/// Observable summary of the sync system (for Settings > Library & sync; never
/// shown as a banner - ADR-008/ADR-023).
@immutable
class SyncStatus {
  const SyncStatus({
    this.isSyncing = false,
    this.progress,
    this.lastSuccessAt,
    this.lastFailure,
    this.initialSyncDone = false,
  });

  final bool isSyncing;
  final SyncProgress? progress;
  final DateTime? lastSuccessAt;
  final AppFailure? lastFailure;

  /// `false` until the first complete library sync finished (drives the
  /// Library header card "Getting your music ready").
  final bool initialSyncDone;

  SyncStatus copyWith({
    bool? isSyncing,
    SyncProgress? progress,
    bool clearProgress = false,
    DateTime? lastSuccessAt,
    AppFailure? lastFailure,
    bool clearFailure = false,
    bool? initialSyncDone,
  }) =>
      SyncStatus(
        isSyncing: isSyncing ?? this.isSyncing,
        progress: clearProgress ? null : (progress ?? this.progress),
        lastSuccessAt: lastSuccessAt ?? this.lastSuccessAt,
        lastFailure: clearFailure ? null : (lastFailure ?? this.lastFailure),
        initialSyncDone: initialSyncDone ?? this.initialSyncDone,
      );
}

/// Decides *when* to sync (docs/02-architecture.md section 5.5).
///
/// Pure Dart: lifecycle and connectivity are fed in by the app layer, timers
/// are injectable, so behaviour is unit-testable.
class SyncScheduler {
  SyncScheduler({
    required SyncEngine engine,
    required EndpointResolver endpoints,
    Clock clock = const SystemClock(),
    this.foregroundInterval = const Duration(minutes: 10),
    this.minResumeGap = const Duration(minutes: 5),
    this.startDelay = const Duration(seconds: 2),
    this.maxBackoff = const Duration(minutes: 15),
    this.baseBackoff = const Duration(seconds: 30),
    Timer Function(Duration, void Function())? timerFactory,
    Timer Function(Duration, void Function())? probeTimerFactory,
    bool initialSyncDone = false,
    this.liveProbe = false,
    this.probeFast = const Duration(seconds: 3),
    this.probeMetered = const Duration(seconds: 30),
    this.probeQuiet = const Duration(seconds: 20),
    this.quietAfterProbes = 40,
    this.minPokeGap = const Duration(seconds: 2),
    this.probeLive = const Duration(seconds: 60),
  })  : _engine = engine,
        _endpoints = endpoints,
        _clock = clock,
        _timer = timerFactory ?? ((d, cb) => Timer(d, cb)),
        _probeTimer =
            probeTimerFactory ?? timerFactory ?? ((d, cb) => Timer(d, cb)),
        _status = SyncStatus(initialSyncDone: initialSyncDone) {
    _progressSub = _engine.progress.listen((p) {
      if (p.phase == SyncPhase.idle) return;
      _setStatus(_status.copyWith(isSyncing: true, progress: p));
    });
  }

  final SyncEngine _engine;
  final EndpointResolver _endpoints;
  final Clock _clock;
  final Duration foregroundInterval;
  final Duration minResumeGap;
  final Duration startDelay;
  final Duration maxBackoff;
  final Duration baseBackoff;
  final Timer Function(Duration, void Function()) _timer;
  final Timer Function(Duration, void Function()) _probeTimer;

  /// Check for changes made on other devices every few seconds while the app is
  /// open (ADR-071, layer L1). Off by default so the timing tests of the full
  /// passes stay simple; the real session turns it on.
  final bool liveProbe;

  /// Probe cadence on Wi-Fi / Ethernet, on mobile data, and after
  /// [quietAfterProbes] unchanged probes in a row (two minutes at the fast
  /// cadence: a screen nobody touches).
  ///
  /// The numbers come from a measurement (docs/10 section 7, docs/23 B40): a
  /// change from another device showed after the wait for the next probe plus
  /// about 2 s to fetch, write and draw. With a 5 s wait the worst case was
  /// 7.4 s against the 5 s budget (R-16), so the fast wait is 3 s; and the old
  /// back-off (60 s after 50 s of nothing) meant an edit made while the phone
  /// lay on a table could take a minute, so it now starts after two minutes
  /// and tops out at 20 s. The screen is on in all of these cases, which
  /// costs far more than one small request.
  final Duration probeFast;
  final Duration probeMetered;
  final Duration probeQuiet;
  final int quietAfterProbes;

  /// A touch or a navigation may probe at once, but not more often than this.
  final Duration minPokeGap;

  /// Probe cadence while the server's live channel is connected: the server tells this phone when something changed, so the probe is only
  /// a safety net for an event that never arrived.
  final Duration probeLive;

  final StreamController<SyncStatus> _statusController =
      StreamController<SyncStatus>.broadcast();
  late final StreamSubscription<SyncProgress> _progressSub;
  SyncStatus _status;
  Timer? _pending;
  Timer? _probePending;
  bool _probing = false;
  bool _metered = false;
  bool _live = false;

  /// The server said something changed while a probe or a pass was working: ask again as soon as it is done.
  bool _probeAgain = false;
  int _quietProbes = 0;
  DateTime? _lastProbeAt;

  /// Connectivity came back while the app was in the background: the sync it
  /// calls for waits for the next resume instead of waking the radio (B18).
  bool _syncOnResume = false;
  bool _foreground = true;
  bool _online = true;
  bool _disposed = false;
  int _consecutiveFailures = 0;
  DateTime? _lastAttempt;

  SyncStatus get status => _status;
  Stream<SyncStatus> get statusStream => _statusController.stream;

  void _setStatus(SyncStatus s) {
    _status = s;
    if (!_statusController.isClosed) _statusController.add(s);
  }

  /// Called once after the first frame: resolve the endpoint, then sync.
  void start() => _schedule(startDelay, SyncReason.appStart);

  void onForeground() {
    _foreground = true;
    final last = _lastAttempt;
    final stale = last == null || _clock.now().difference(last) >= minResumeGap;
    if (_syncOnResume) {
      _syncOnResume = false;
      _schedule(Duration.zero, SyncReason.connectivity);
    } else if (stale) {
      _schedule(Duration.zero, SyncReason.resume);
    }
    // Whatever changed while the app was away is found at once.
    _quietProbes = 0;
    _scheduleProbe(Duration.zero);
  }

  void onBackground() {
    _foreground = false;
    _pending?.cancel();
    _pending = null;
    _probePending?.cancel();
    _probePending = null;
  }

  void onConnectivityChanged({required bool online}) {
    final regained = online && !_online;
    _online = online;
    if (regained) {
      _consecutiveFailures = 0;
      if (!_foreground) {
        // A flapping radio with the screen off must not start full syncs.
        _syncOnResume = true;
        return;
      }
      // Debounce flapping radios.
      _schedule(const Duration(seconds: 2), SyncReason.connectivity);
    }
  }

  /// Mobile data is slower to wake and costs the person's plan: probe less often.
  void setMetered(bool metered) {
    _metered = metered;
    _engine.metered = metered;
  }

  /// Something happened that makes "is it current?" worth asking now (the person
  /// opened a screen, the app came back). Probes at once, at most once per
  /// [minPokeGap], and returns to the short cadence.
  void poke() {
    if (!liveProbe) return;
    _quietProbes = 0;
    final last = _lastProbeAt;
    if (last != null && _clock.now().difference(last) < minPokeGap) return;
    _scheduleProbe(Duration.zero);
  }

  /// The server's live channel connected or dropped. While it is up the probe slows to [probeLive]; when it drops the short cadence
  /// returns at once, so a phone without the channel (an old proxy, a blocked socket) is no worse off than before it existed.
  void setLive(bool connected) {
    if (_live == connected) return;
    _live = connected;
    _quietProbes = 0;
    if (!connected) _scheduleProbe(Duration.zero);
  }

  bool get isLive => _live;

  /// The server pushed "something changed" (or this phone has just connected): probe now, however recently the last probe was, and if a
  /// probe or a pass is already working, once more right after it.
  void liveEvent() {
    if (!liveProbe || _disposed) return;
    _quietProbes = 0;
    if (_probing || _engine.isRunning || _status.isSyncing) {
      _probeAgain = true;
      return;
    }
    _scheduleProbe(Duration.zero);
  }

  bool get isProbing => _probing;

  Duration get _probeDelay => _live
      ? probeLive
      : _quietProbes >= quietAfterProbes
          ? probeQuiet
          : (_metered ? probeMetered : probeFast);

  /// When to probe next: at once if the server said something changed meanwhile, otherwise the normal cadence.
  Duration _nextProbeDelay() {
    if (!_probeAgain) return _probeDelay;
    _probeAgain = false;
    return Duration.zero;
  }

  void _scheduleProbe(Duration delay) {
    // Nothing to compare with before the first sync has finished.
    if (!liveProbe || _disposed || !_foreground || !_status.initialSyncDone) {
      return;
    }
    _probePending?.cancel();
    _probePending = _probeTimer(delay, () => unawaited(_probeNow()));
  }

  Future<void> _probeNow() async {
    if (_disposed || !_foreground || _probing) return;
    // Not before the first sync, not offline, not while a full pass runs.
    if (!_online ||
        !_status.initialSyncDone ||
        _status.isSyncing ||
        _engine.isRunning) {
      _scheduleProbe(_probeDelay);
      return;
    }
    _probing = true;
    _lastProbeAt = _clock.now();
    var fullPass = false;
    try {
      switch (await _engine.probe()) {
        case ProbeUnchanged():
          _quietProbes++;
        case ProbeUpdated():
          _quietProbes = 0;
        case ProbeNeedsFullPass():
          fullPass = true;
        case ProbeBusy():
          break;
        case ProbeFailed(:final failure):
          if (failure is AuthFailure) return; // like a full pass: not repeated
          if (failure is NetworkFailure) _endpoints.reportFailure();
          _quietProbes = quietAfterProbes; // do not hammer a failing link
      }
    } finally {
      _probing = false;
    }
    if (fullPass) {
      // The normal pass reschedules probing when it finishes.
      _schedule(Duration.zero, SyncReason.scheduled);
    } else {
      _scheduleProbe(_nextProbeDelay());
    }
  }

  /// User/pull-to-refresh or after a local mutation.
  ///
  /// [acceptShrink] is the person's explicit "follow the server" after the
  /// shrink guard held back a far smaller answer (docs/23, B6).
  void requestSync({
    SyncReason reason = SyncReason.manual,
    bool force = false,
    bool acceptShrink = false,
  }) {
    _schedule(Duration.zero, reason, force: force, acceptShrink: acceptShrink);
  }

  void _schedule(
    Duration delay,
    SyncReason reason, {
    bool force = false,
    bool acceptShrink = false,
  }) {
    if (_disposed) return;
    _pending?.cancel();
    _pending = _timer(
      delay,
      () =>
          unawaited(_runNow(reason, force: force, acceptShrink: acceptShrink)),
    );
  }

  Future<void> _runNow(
    SyncReason reason, {
    bool force = false,
    bool acceptShrink = false,
  }) async {
    if (_disposed) return;
    _lastAttempt = _clock.now();
    _setStatus(_status.copyWith(isSyncing: true));

    // Never block on the network for UI purposes - but a sync needs a URL.
    await _endpoints.resolve();
    final outcome = await _engine.run(
      reason: reason,
      force: force,
      acceptShrink: acceptShrink,
    );

    switch (outcome) {
      case SyncCompleted():
        _consecutiveFailures = 0;
        _setStatus(_status.copyWith(
          isSyncing: false,
          clearProgress: true,
          clearFailure: true,
          lastSuccessAt: _clock.now(),
          initialSyncDone: true,
        ));
        _scheduleNextForeground();
        _quietProbes = 0;
        _scheduleProbe(_nextProbeDelay());
      case SyncCancelled():
        _setStatus(_status.copyWith(isSyncing: false, clearProgress: true));
      case SyncBusy():
        // The other engine (the background job) is syncing: it writes the same
        // database, so the screen updates by itself. Keep the normal rhythm.
        _setStatus(_status.copyWith(isSyncing: false, clearProgress: true));
        _scheduleNextForeground();
        _scheduleProbe(_probeDelay);
      case SyncFailed(:final failure):
        _consecutiveFailures++;
        Log.info('scheduler',
            'sync failed (${_consecutiveFailures}x): ${failure.message}');
        _setStatus(_status.copyWith(
          isSyncing: false,
          clearProgress: true,
          lastFailure: failure,
        ));
        if (failure is NetworkFailure) _endpoints.reportFailure();
        if (failure is AuthFailure) {
          // Wrong credentials: repeating the same login will not help and can
          // trip the server's login limits. The person signs in again, or the
          // next resume tries once.
        } else if (failure.isRetryable) {
          _scheduleRetry();
        } else {
          // A rejection or a local problem that a fast retry cannot fix but
          // that may clear by itself (a freed disk, a repaired server): keep
          // the normal rhythm. Scheduling nothing here stopped periodic
          // syncing for good until the app was resumed after five minutes
          // (docs/23, B4).
          _scheduleNextForeground();
        }
    }
  }

  void _scheduleNextForeground() {
    if (!_foreground || _disposed) return;
    _pending?.cancel();
    _pending = _timer(
      foregroundInterval,
      () => unawaited(_runNow(SyncReason.scheduled)),
    );
  }

  void _scheduleRetry() {
    if (!_foreground || _disposed) return;
    final exp = min(_consecutiveFailures, 8);
    final delay = Duration(
      milliseconds: min(
        baseBackoff.inMilliseconds * pow(2, exp - 1).toInt(),
        maxBackoff.inMilliseconds,
      ),
    );
    _pending?.cancel();
    _pending = _timer(delay, () => unawaited(_runNow(SyncReason.scheduled)));
  }

  @visibleForTesting
  Duration get nextRetryDelay {
    final exp = min(max(_consecutiveFailures, 1), 8);
    return Duration(
      milliseconds: min(
        baseBackoff.inMilliseconds * pow(2, exp - 1).toInt(),
        maxBackoff.inMilliseconds,
      ),
    );
  }

  Future<void> dispose() async {
    _disposed = true;
    _pending?.cancel();
    _probePending?.cancel();
    await _progressSub.cancel();
    await _statusController.close();
  }
}
