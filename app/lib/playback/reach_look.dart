import 'dart:async';

import '../core/clock.dart';
import '../core/logger.dart';

/// One look at the server for everybody who needs to know whether a song that is not downloaded can be asked for.
///
/// The player's answer to "can I reach the server" is what was last found out; a server that was out of reach may be back (data returned on
/// the same network is not a network change). So before a song is refused the server is asked, once: callers that arrive while the look is
/// running wait for the same look (and get its answer), and after a look that found nobody nothing asks again for [memo], so a playlist of
/// songs that are not downloaded costs one look and not one per song.
class ReachLook {
  ReachLook({
    required Future<bool> Function() look,
    required Clock clock,
    this.memo = const Duration(seconds: 5),
  })  : _look = look,
        _clock = clock;

  final Future<bool> Function() _look;
  final Clock _clock;
  final Duration memo;

  Future<bool>? _running;
  DateTime? _missedAt;

  Future<bool> call() {
    final running = _running;
    if (running != null) return running;
    final missed = _missedAt;
    if (missed != null && _clock.now().difference(missed) < memo) {
      return Future<bool>.value(false);
    }
    return _running = _ask();
  }

  Future<bool> _ask() async {
    var answered = false;
    try {
      answered = await _look();
    } on Object catch (error) {
      Log.warn('playback', 'the look at the server failed', error);
      answered = false;
    } finally {
      _missedAt = answered ? null : _clock.now();
      _running = null;
    }
    return answered;
  }
}
