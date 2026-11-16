import 'dart:async';

import '../../core/logger.dart';
import '../../domain/download_card.dart';
import '../../domain/download_card_words.dart';

export '../../domain/download_card.dart'
    show CardKind, CardPost, DownloadCardSink, kRunningCardId, resultCardId;

/// Decides WHEN the one card of the downloads is posted, refreshed, switched, ended (docs/design S-95, P2-29). No Flutter and no Riverpod: it is
/// handed the jobs and whether the app is in front, and talks to a [DownloadCardSink]; `download_card_wiring.dart` feeds it.
///
/// * **One card, one id.** While anything runs there is ONE running card on [kRunningCardId]: refreshed in place (never stacked), and only when it
///   changed. A job that is over leaves one result card of its own.
/// * **In front of the person (the app is open): the live card**, S-16's line word for word, posted with a time to live ([liveTimeout]) and re-posted
///   every [heartbeat] while nothing changes. A killed app refreshes nothing, so the card goes away by itself instead of showing numbers that stopped
///   being true.
/// * **Outside the app: the dated card**, on the SAME id, with no time to live: it says what the server had ready and when, so that freezing when the
///   process is killed leaves it true (the owner's "no notification" complaint of 6 Nov 2026 is what a card that is only right while refreshes keep
///   coming would bring back). It is refreshed for as long as the phone lets the app run; no reason ("resting until", "waiting for Wi-Fi") is ever
///   said outside the app.
/// * Nothing is posted without the notification permission, and a card is never posted faster than [minGap] (the phone drops what comes faster).
class DownloadCardPresenter {
  DownloadCardPresenter({
    required DownloadCardSink sink,
    required DateTime Function() now,
    DownloadCardWords words = const DownloadCardWords(),
    this.liveTimeout = const Duration(minutes: 3),
    this.heartbeat = const Duration(minutes: 1),
    this.minGap = const Duration(seconds: 1),
  })  : _sink = sink,
        _now = now,
        _words = words;

  final DownloadCardSink _sink;
  final DateTime Function() _now;
  final DownloadCardWords _words;

  /// How long a live card lives when nothing refreshes it.
  final Duration liveTimeout;

  /// How often an unchanged live card is posted again (a third of [liveTimeout]: two refreshes can be lost before it would time out).
  final Duration heartbeat;
  final Duration minGap;

  final ProgressFloor _floor = ProgressFloor();
  List<CardJob> _jobs = const [];
  bool _foreground = true;
  bool _disposed = false;

  /// What the running card says now (as last handed to the notification manager), or `null` when there is none.
  CardSpec? _shown;
  DateTime? _lastPostAt;
  Timer? _later;
  Timer? _beat;
  Future<void> _queue = Future<void>.value();

  /// Looks at the jobs again. Completes when what this look asked for has been handed to the notification manager (a card held back to keep the
  /// pace completes later, by itself).
  Future<void> update({
    required List<CardJob> jobs,
    required bool foreground,
  }) {
    if (_disposed) return _queue;
    final results = resultsBetween(_jobs, jobs, _words);
    final left = foreground != _foreground;
    _jobs = jobs;
    _foreground = foreground;
    for (final result in results) {
      _enqueue(() => _postResult(result));
    }
    // Leaving the app (or coming back) is posted at once and not paced: the process can be killed any moment, and the card that stays then must be
    // the dated one.
    _decide(force: left);
    return _queue;
  }

  void dispose() {
    _disposed = true;
    _later?.cancel();
    _later = null;
    _beat?.cancel();
    _beat = null;
  }

  // ------------------------------------------------------------------------------------------------------------------ the running card

  void _decide({required bool force}) {
    if (_disposed) return;
    CardSpec? wanted;
    if (_foreground) {
      final live = liveCard(_jobs, _words);
      if (live != null) {
        final keys = {
          for (final j in _jobs)
            if (j.running) j.key
        };
        final progress =
            live.progress == null ? null : _floor.apply(keys, live.progress!);
        wanted = CardSpec(
          title: live.title,
          body: live.body,
          expanded: live.expanded,
          progress: progress,
          route: live.route,
        );
      }
    } else {
      wanted = datedCard(_jobs, _now(), _words);
    }
    if (wanted == null && !_jobs.any((j) => j.running)) _floor.reset();

    if (wanted == null) {
      _later?.cancel();
      _later = null;
      _beat?.cancel();
      _beat = null;
      if (_shown != null) {
        _shown = null;
        _enqueue(() => _sink.cancel(kRunningCardId));
      }
      return;
    }
    if (!force && _shown?.signature == wanted.signature) return;

    // Not faster than the phone allows: the newest look waits for its turn, and is the one that is shown.
    final last = _lastPostAt;
    if (!force && last != null && minGap > Duration.zero) {
      final wait = minGap - _now().difference(last);
      if (wait > Duration.zero) {
        _later ??= Timer(wait, () {
          _later = null;
          _decide(force: false);
        });
        return;
      }
    }
    _later?.cancel();
    _later = null;
    final spec = wanted;
    final foreground = _foreground;
    _lastPostAt = _now();
    // Counted as shown at once: a second look before the first card has gone out must not post it twice (undone below when nothing can be shown).
    _shown = spec;
    _enqueue(() => _postRunning(spec, foreground));
  }

  Future<void> _postRunning(CardSpec spec, bool foreground) async {
    if (_disposed) return;
    if (!await _sink.canPost()) {
      _shown = null;
      return;
    }
    if (_disposed) return;
    await _sink.post(CardPost(
      id: kRunningCardId,
      kind: CardKind.running,
      spec: spec,
      timeoutAfter: foreground ? liveTimeout : null,
    ));
    _armHeartbeat(foreground);
  }

  /// A live card nothing changes would time out while the person looks at the app: post it again now and then. Outside the app there is no beat:
  /// the dated card does not expire, and nothing is gained by waking the phone.
  void _armHeartbeat(bool foreground) {
    _beat?.cancel();
    _beat = null;
    if (!foreground || _disposed) return;
    _beat = Timer.periodic(heartbeat, (_) {
      if (_disposed || !_foreground || _shown == null) return;
      _decide(force: true);
    });
  }

  // --------------------------------------------------------------------------------------------------------------------- result cards

  Future<void> _postResult(CardResult result) async {
    if (_disposed) return;
    if (!await _sink.canPost()) return;
    await _sink.post(CardPost(
      id: resultCardId(result.key),
      kind: CardKind.result,
      spec: CardSpec(
        title: result.title,
        body: result.body,
        route: result.route,
      ),
    ));
  }

  void _enqueue(Future<void> Function() step) {
    _queue = _queue.then((_) async {
      try {
        await step();
      } on Object catch (error) {
        // A notification is a convenience: it never breaks what it reports on.
        Log.warn('notify', 'the download card could not be shown', error);
      }
    });
  }
}
