import 'dart:async';
import 'dart:collection';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/scheduler.dart';

/// Frame and span timing that is cheap enough to leave on in release builds
/// (docs/05-testing-and-quality.md section 5, budgets in docs/00-requirements).
///
/// * Frame timings come from the engine's own `FrameTiming` callback - no
///   per-frame work on the UI thread beyond appending to a ring buffer.
/// * Spans measure user-visible latencies ("tap play -> audio running").
/// * Everything is also written to logcat with a `[perf]` prefix so a phone
///   can be profiled with `adb logcat -s flutter | grep perf` and so the
///   Diagnostics screen can show it.
class PerfMonitor {
  PerfMonitor._();

  static final PerfMonitor instance = PerfMonitor._();

  static const int _capacity = 900; // ~15 s at 60 fps

  final ListQueue<_Frame> _frames = ListQueue<_Frame>();
  final List<SpanResult> _spans = <SpanResult>[];
  final Map<String, Stopwatch> _open = <String, Stopwatch>{};
  bool _started = false;

  /// One-shot timer that writes the next `[perf]` line. It exists only while
  /// frames are being produced: an idle or backgrounded app has no timer at
  /// all (a periodic one cost a wake-up every 5 s forever).
  Timer? _logTimer;
  Duration _logEvery = Duration.zero;

  // Lifetime counters (the ring buffer above is windowed and reset).
  int _totalFrames = 0;
  int _jankFrames = 0;
  int _severeFrames = 0;
  int _worstBuildUs = 0;
  int _worstRasterUs = 0;

  /// Set to false to silence logcat output (tests).
  bool logToConsole = true;

  /// Starts collecting frame timings. Idempotent.
  void start({Duration logEvery = const Duration(seconds: 5)}) {
    if (_started) return;
    _started = true;
    _logEvery = logEvery;
    SchedulerBinding.instance.addTimingsCallback(_onTimings);
  }

  void _scheduleLog() {
    if (_logEvery <= Duration.zero || _logTimer != null) return;
    _logTimer = Timer(_logEvery, () {
      _logTimer = null;
      final s = summary();
      if (s.frames > 0) {
        _log('frames ${s.describe()}');
        // Windowed: each line covers the last interval only.
        reset();
      }
    });
  }

  void stop() {
    if (!_started) return;
    _started = false;
    SchedulerBinding.instance.removeTimingsCallback(_onTimings);
    _logTimer?.cancel();
    _logTimer = null;
  }

  void _onTimings(List<ui.FrameTiming> timings) {
    final budget = frameBudget().inMicroseconds;
    for (final t in timings) {
      _totalFrames++;
      final build = t.buildDuration.inMicroseconds;
      final raster = t.rasterDuration.inMicroseconds;
      // The work a thread did, not the time since the screen's tick: a frame
      // that started late (the app was busy with something else, or the
      // display was idle) but drew in 5 ms is not slow drawing.
      final slowest = math.max(build, raster);
      if (slowest > budget) _jankFrames++;
      if (slowest > budget * 2) _severeFrames++;
      _worstBuildUs = math.max(_worstBuildUs, build);
      _worstRasterUs = math.max(_worstRasterUs, raster);
      _frames.addLast(_Frame(
        build: build,
        raster: raster,
        late: t.vsyncOverhead.inMicroseconds,
      ));
      while (_frames.length > _capacity) {
        _frames.removeFirst();
      }
    }
    _scheduleLog();
  }

  /// Feeds frames to the monitor without the engine (tests).
  @visibleForTesting
  void addTimingsForTest(List<ui.FrameTiming> timings) => _onTimings(timings);

  /// Frame budget for the current display (16.7 ms at 60 Hz).
  static Duration frameBudget() {
    final views = ui.PlatformDispatcher.instance.views;
    final rate = views.isEmpty ? 60.0 : views.first.display.refreshRate;
    return Duration(microseconds: (1e6 / (rate <= 0 ? 60 : rate)).round());
  }

  /// Summary of the frames collected since the last [reset].
  FrameSummary summary({Duration? budget}) {
    final b = (budget ?? frameBudget()).inMicroseconds;
    if (_frames.isEmpty) return FrameSummary.empty(b);
    final work = [for (final f in _frames) f.build + f.raster]..sort();
    final late = [for (final f in _frames) f.late]..sort();
    int pct(List<int> sorted, double p) =>
        sorted[math.min(sorted.length - 1, (sorted.length * p).floor())];
    var jank = 0;
    var severe = 0;
    var worstBuild = 0;
    var worstRaster = 0;
    for (final f in _frames) {
      final slowest = math.max(f.build, f.raster);
      if (slowest > b) jank++;
      if (slowest > b * 2) severe++;
      worstBuild = math.max(worstBuild, f.build);
      worstRaster = math.max(worstRaster, f.raster);
    }
    return FrameSummary(
      frames: _frames.length,
      jank: jank,
      severe: severe,
      workP50: Duration(microseconds: pct(work, 0.50)),
      workP90: Duration(microseconds: pct(work, 0.90)),
      workP99: Duration(microseconds: pct(work, 0.99)),
      lateStartP90: Duration(microseconds: pct(late, 0.90)),
      worstBuild: Duration(microseconds: worstBuild),
      worstRaster: Duration(microseconds: worstRaster),
      budget: Duration(microseconds: b),
    );
  }

  void reset() => _frames.clear();

  /// Totals since the process started (Diagnostics screen).
  String lifetimeSummary() {
    if (_totalFrames == 0) return 'no frames recorded';
    final pct = (_jankFrames * 100 / _totalFrames).toStringAsFixed(1);
    String ms(int us) => (us / 1000).toStringAsFixed(1);
    return 'frames=$_totalFrames jank=$_jankFrames ($pct%) '
        'severe=$_severeFrames worstBuild=${ms(_worstBuildUs)}ms '
        'worstRaster=${ms(_worstRasterUs)}ms';
  }

  // ------------------------------------------------------------------ spans

  /// Starts (or restarts) a named latency measurement.
  void begin(String name) {
    _open[name] = Stopwatch()..start();
  }

  /// Finishes [name]; returns the elapsed time, or `null` if it was not open.
  Duration? end(String name, {String? detail}) {
    final sw = _open.remove(name);
    if (sw == null) return null;
    sw.stop();
    final result = SpanResult(name, sw.elapsed, detail: detail);
    _spans.add(result);
    if (_spans.length > 200) _spans.removeAt(0);
    _log('span $name ${sw.elapsedMilliseconds} ms'
        '${detail == null ? '' : ' ($detail)'}');
    return sw.elapsed;
  }

  bool isOpen(String name) => _open.containsKey(name);

  // ------------------------------------------------------------- page opens

  /// A page was just asked for (a tap on a playlist, an artist, an album). Two spans run from here: `open.<page>.shell`, until the page
  /// draws its frame, and `open.<page>.full`, until it shows what it is for (the songs, the releases). The owner's "it loads" is the
  /// second one; the Diagnostics screen and `adb logcat -s flutter | grep "span open"` show both on a real phone.
  void pageOpening(String page) {
    begin('open.$page.shell');
    begin('open.$page.full');
  }

  /// The page has drawn its frame (no-op when no open is being timed, as on every later rebuild).
  void pageShell(String page) => end('open.$page.shell');

  /// The page shows what it is for (no-op when no open is being timed).
  void pageFull(String page, {String? detail}) =>
      end('open.$page.full', detail: detail);

  /// Drops an open span without recording it (the action was cancelled).
  void cancel(String name) => _open.remove(name);

  /// Times [body] as a span.
  Future<T> measure<T>(String name, Future<T> Function() body) async {
    begin(name);
    try {
      return await body();
    } finally {
      end(name);
    }
  }

  List<SpanResult> get spans => List.unmodifiable(_spans);

  /// Free-form measurement line (`[perf] ...`).
  void note(String message) => _log(message);

  void _log(String message) {
    if (logToConsole) debugPrint('[perf] $message');
  }
}

class _Frame {
  const _Frame({
    required this.build,
    required this.raster,
    required this.late,
  });

  final int build;
  final int raster;

  /// How long after the screen's tick the UI thread began this frame.
  final int late;
}

@immutable
class SpanResult {
  const SpanResult(this.name, this.duration, {this.detail});

  final String name;
  final Duration duration;
  final String? detail;
}

@immutable
class FrameSummary {
  const FrameSummary({
    required this.frames,
    required this.jank,
    required this.severe,
    required this.workP50,
    required this.workP90,
    required this.workP99,
    required this.lateStartP90,
    required this.worstBuild,
    required this.worstRaster,
    required this.budget,
  });

  FrameSummary.empty(int budgetUs)
      : frames = 0,
        jank = 0,
        severe = 0,
        workP50 = Duration.zero,
        workP90 = Duration.zero,
        workP99 = Duration.zero,
        lateStartP90 = Duration.zero,
        worstBuild = Duration.zero,
        worstRaster = Duration.zero,
        budget = Duration(microseconds: budgetUs);

  final int frames;

  /// Frames where building or drawing alone took longer than the display
  /// budget (the work was too slow, whatever the wait before it).
  final int jank;

  /// Frames where building or drawing took more than twice the budget (a
  /// visible stutter).
  final int severe;

  /// Building plus drawing, per frame (the work an app can reduce).
  final Duration workP50;
  final Duration workP90;
  final Duration workP99;

  /// How long after the screen's tick the app began a frame (90th percentile):
  /// high with low work means the UI thread was busy with something else, or
  /// the display was idle; it is not a drawing cost.
  final Duration lateStartP90;
  final Duration worstBuild;
  final Duration worstRaster;
  final Duration budget;

  double get jankRatio => frames == 0 ? 0 : jank / frames;

  String describe() {
    String ms(Duration d) => (d.inMicroseconds / 1000).toStringAsFixed(1);
    return 'n=$frames jank=$jank (${(jankRatio * 100).toStringAsFixed(1)}%) '
        'severe=$severe work p50=${ms(workP50)}ms p90=${ms(workP90)}ms '
        'p99=${ms(workP99)}ms late p90=${ms(lateStartP90)}ms '
        'worst(build=${ms(worstBuild)} raster=${ms(worstRaster)}) '
        'budget=${ms(budget)}ms';
  }
}
