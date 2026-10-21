import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../core/logger.dart';
import '../../core/result.dart';
import 'people_client.dart';

/// What a friend may be told about the song playing right now. The player's
/// own types stay in the UI layer; `features/people/listening.dart` turns a
/// player snapshot into this (or into `null` when there is nothing to share,
/// such as a 30-second sample).
@immutable
class ListeningState {
  const ListeningState({
    required this.id,
    required this.title,
    required this.playing,
    this.artist,
    this.album,
    this.coverUrl,
  });

  /// Only used to tell one song from the next on this phone; never sent.
  final String id;
  final String title;
  final String? artist;
  final String? album;

  /// A public picture address, or `null` (a library cover needs this person's
  /// login and is never shared).
  final String? coverUrl;
  final bool playing;

  String get _key => '$id|$playing';
}

/// Tells the server what this person is listening to, so friends can see it
/// (docs/35, section 4).
///
/// * **Only when the person chose to** ([sharing] is the person's choice and
///   "private listening" together). Otherwise not even a timer is started.
/// * **Only once they have settled on a song**: skipping through five songs is
///   one report, for the song they stopped on.
/// * **Nothing that points into a library**: the report holds a title, an
///   artist, an album, a public picture and "playing or paused" (see
///   [NowPlayingReport]).
/// * **Best effort**: a service that is away or a request that fails is never
///   an error for the person; the next change, or the reminder below, tries
///   again.
class ActivityPublisher {
  ActivityPublisher({
    required Stream<ListeningState?> listening,
    required ActivitySink? Function() sink,
    required bool Function() sharing,
    this.settle = const Duration(seconds: 2),
    this.heartbeat = const Duration(minutes: 5),
    Timer Function(Duration delay, void Function() callback) timer = _realTimer,
  })  : _sink = sink,
        _sharing = sharing,
        _makeTimer = timer {
    _subscription = listening.listen(_onListening);
  }

  static Timer _realTimer(Duration delay, void Function() callback) =>
      Timer(delay, callback);

  /// How long a song must stay before it is reported.
  final Duration settle;

  /// While a song plays the service is reminded this often, so a long song or
  /// a long mix does not fade from the friends' list (it forgets after 30
  /// minutes of silence).
  final Duration heartbeat;

  final ActivitySink? Function() _sink;
  final bool Function() _sharing;
  final Timer Function(Duration delay, void Function() callback) _makeTimer;

  late final StreamSubscription<ListeningState?> _subscription;
  Timer? _timer;
  ListeningState? _latest;

  /// What the latest state would be reported as (`null`: nothing to share).
  String? _wantedKey;

  /// What the service was last told successfully.
  String? _sent;

  /// The service may be holding something of mine that must be cleared.
  bool _published = false;
  bool _disposed = false;

  void _onListening(ListeningState? state) {
    _latest = state;
    final key = state?._key;
    if (key == _wantedKey) return; // a position tick, not a change
    _wantedKey = key;
    if (_sharing()) _arm(settle);
  }

  /// Call when the person's choice changed (sharing or private listening), or
  /// when the service became reachable.
  void refresh() {
    if (_disposed) return;
    _timer?.cancel();
    _timer = null;
    if (_sharing()) {
      _sent = null;
      _arm(settle);
    } else if (_published) {
      _forget();
    }
  }

  void dispose() {
    if (_disposed) return;
    _disposed = true;
    _timer?.cancel();
    _timer = null;
    unawaited(_subscription.cancel());
    if (_published) _forget();
  }

  void _arm(Duration delay, {bool force = false}) {
    _timer?.cancel();
    _timer = _makeTimer(delay, () => unawaited(_flush(force: force)));
  }

  void _forget() {
    _published = false;
    _sent = null;
    final sink = _sink();
    if (sink != null) unawaited(_send(sink.clear));
  }

  Future<void> _flush({required bool force}) async {
    _timer = null;
    if (_disposed || !_sharing()) return;
    final sink = _sink();
    if (sink == null) return;

    final state = _latest;
    if (state == null) {
      if (_published) {
        _published = false;
        _sent = null;
        await _send(sink.clear);
      }
      return;
    }
    final key = state._key;
    if (key == _sent && !force) return;

    final result = await _send(() => sink.report(NowPlayingReport(
          title: state.title,
          artist: state.artist ?? '',
          album: state.album ?? '',
          coverUrl: state.coverUrl,
          playing: state.playing,
        )));
    if (_disposed) return;
    _published = true;
    _sent = result.isOk ? key : null;
    // A newer change has its own timer already; otherwise keep a playing song
    // alive, and try again later when the report did not arrive.
    if (_timer == null && (state.playing || !result.isOk)) {
      _arm(heartbeat, force: true);
    }
  }

  Future<Result<void>> _send(Future<Result<void>> Function() call) async {
    try {
      final result = await call();
      if (!result.isOk) {
        Log.debug('people', 'activity not delivered (will try again later)');
      }
      return result;
    } on Object catch (error) {
      Log.debug('people', 'activity not delivered: ${error.runtimeType}');
      return Result.err(UnexpectedFailure('Activity failed', cause: error));
    }
  }
}
