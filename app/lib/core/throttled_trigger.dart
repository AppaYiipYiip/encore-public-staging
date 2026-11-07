import 'dart:async';

/// Runs [action] at most once every [every]: the first call at once, and one more at the end of the window when calls came meanwhile (so the last
/// call is never lost). For work that a stream of events asks for again and again and that does not need to run for each of them: the downloads
/// look again at the songs, which reads every pinned song, whenever the server says it kept another one (audit B-108 and the owner's "the app is
/// slow" of 7 Nov 2026: with a server keeping 14 songs a minute that was a pass over thousands of rows every 4 seconds).
class ThrottledTrigger {
  ThrottledTrigger(this.every, this.action, {DateTime Function()? clock})
      : _clock = clock ?? DateTime.now;

  final Duration every;
  final void Function() action;
  final DateTime Function() _clock;

  DateTime? _last;
  Timer? _later;

  void call() {
    final last = _last;
    final now = _clock();
    if (last == null || now.difference(last) >= every) {
      _later?.cancel();
      _later = null;
      _last = now;
      action();
      return;
    }
    _later ??= Timer(every - now.difference(last), () {
      _later = null;
      _last = _clock();
      action();
    });
  }

  void dispose() {
    _later?.cancel();
    _later = null;
  }
}
