import 'dart:async';

/// Emits the player position while - and only while - audio is playing.
///
/// `just_audio`'s own position stream runs a periodic timer for as long as
/// somebody listens, at 16 ms whenever the duration is unknown (nothing loaded,
/// a restored queue): about 60 wake-ups a second, forever, paused or not. That
/// kept a paused player at ~20% of a core (docs/15-resource-usage.md). This
/// pump ticks only in the one state where the position moves, and reports the
/// final position when it stops.
class PositionPump {
  PositionPump({
    required Duration Function() read,
    required void Function(Duration position) emit,
    this.tick = const Duration(milliseconds: 200),
    Timer Function(Duration interval, void Function(Timer) callback)? periodic,
  })  : _read = read,
        _emit = emit,
        _periodic = periodic ?? Timer.periodic;

  final Duration Function() _read;
  final void Function(Duration position) _emit;
  final Timer Function(Duration, void Function(Timer)) _periodic;

  /// Interval between updates while playing. 200 ms keeps a seek bar smooth
  /// (about one pixel per tick on a 3.5 minute song) and lyrics lines within a
  /// fifth of a second.
  final Duration tick;

  Timer? _timer;
  Duration? _last;
  bool _disposed = false;

  bool get isRunning => _timer != null;

  /// Call whenever the player's playing/processing state changes: runs the
  /// timer while [running], stops it otherwise and emits the resting position.
  void update({required bool running}) {
    if (_disposed) return;
    if (running) {
      _timer ??= _periodic(tick, (_) => poke());
      poke();
    } else {
      _timer?.cancel();
      _timer = null;
      poke();
    }
  }

  /// Emits the current position if it changed since the last emission (a seek
  /// while paused, the final position after a pause).
  void poke() {
    if (_disposed) return;
    final position = _read();
    if (position == _last) return;
    _last = position;
    _emit(position);
  }

  void dispose() {
    _disposed = true;
    _timer?.cancel();
    _timer = null;
  }
}
