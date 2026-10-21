import 'dart:async';
import 'dart:collection';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

/// One second of how the app is drawing, for the on-screen counter (docs/22
/// section 6). Pure numbers so the maths is tested without a screen.
@immutable
class FrameSummary {
  const FrameSummary({
    required this.fps,
    required this.buildAvgMs,
    required this.buildMaxMs,
    required this.rasterAvgMs,
    required this.rasterMaxMs,
    required this.jank,
  });

  static const FrameSummary none = FrameSummary(
    fps: 0,
    buildAvgMs: 0,
    buildMaxMs: 0,
    rasterAvgMs: 0,
    rasterMaxMs: 0,
    jank: 0,
  );

  /// Frames drawn in the last second.
  final double fps;

  /// Time the UI thread spent building a frame (average / worst).
  final double buildAvgMs;
  final double buildMaxMs;

  /// Time the raster thread spent drawing it (average / worst): the closest
  /// thing to GPU load that an app can read without root.
  final double rasterAvgMs;
  final double rasterMaxMs;

  /// Frames in the last second that took longer than the frame budget.
  final int jank;
}

/// Keeps the last second of frame timings.
class FrameStats {
  FrameStats({this.budgetMs = 16.7});

  /// What a frame may take before it is a visible stutter (60 Hz).
  final double budgetMs;

  final Queue<({int at, double build, double raster})> _frames = Queue();

  /// Records one frame that finished at [atMs] (a monotonic clock).
  void add({required int atMs, required double buildMs, double rasterMs = 0}) {
    _frames.addLast((at: atMs, build: buildMs, raster: rasterMs));
  }

  FrameSummary summary(int nowMs) {
    while (_frames.isNotEmpty && nowMs - _frames.first.at > 1000) {
      _frames.removeFirst();
    }
    if (_frames.isEmpty) return FrameSummary.none;
    var buildSum = 0.0, buildMax = 0.0, rasterSum = 0.0, rasterMax = 0.0;
    var jank = 0;
    for (final f in _frames) {
      buildSum += f.build;
      rasterSum += f.raster;
      if (f.build > buildMax) buildMax = f.build;
      if (f.raster > rasterMax) rasterMax = f.raster;
      if (f.build > budgetMs || f.raster > budgetMs) jank++;
    }
    final n = _frames.length;
    return FrameSummary(
      fps: n.toDouble(),
      buildAvgMs: buildSum / n,
      buildMaxMs: buildMax,
      rasterAvgMs: rasterSum / n,
      rasterMaxMs: rasterMax,
      jank: jank,
    );
  }
}

/// Share of one CPU core this process used since the last look, from
/// `/proc/self/stat` (Android and Linux). `100` = one core fully busy; a phone
/// has eight, so values above 100 are possible and mean several threads.
class CpuMeter {
  CpuMeter({
    String Function()? readStat,
    this.ticksPerSecond = 100,
  }) : _read = readStat ?? _readProc;

  final String Function() _read;
  final int ticksPerSecond;

  int? _lastTicks;
  int? _lastAtMs;

  static String _readProc() => File('/proc/self/stat').readAsStringSync();

  /// CPU ticks (user + system) in a `/proc/<pid>/stat` line, or `null`.
  static int? ticksIn(String stat) {
    final close = stat.lastIndexOf(')');
    if (close < 0) return null;
    final fields = stat.substring(close + 1).trim().split(RegExp(r'\s+'));
    // After the "(name)": state is field 0, utime 11, stime 12.
    if (fields.length < 13) return null;
    final user = int.tryParse(fields[11]);
    final system = int.tryParse(fields[12]);
    if (user == null || system == null) return null;
    return user + system;
  }

  /// Percent of one core since the previous call; `null` the first time or
  /// when the platform has no `/proc`.
  double? percent(int nowMs) {
    int? ticks;
    try {
      ticks = ticksIn(_read());
    } on Object {
      return null;
    }
    if (ticks == null) return null;
    final previousTicks = _lastTicks;
    final previousAt = _lastAtMs;
    _lastTicks = ticks;
    _lastAtMs = nowMs;
    if (previousTicks == null || previousAt == null) return null;
    final elapsedMs = nowMs - previousAt;
    if (elapsedMs <= 0) return null;
    final seconds = (ticks - previousTicks) / ticksPerSecond;
    return 100 * seconds / (elapsedMs / 1000);
  }
}

/// The first line of the counter. Frames per second is only how many frames the
/// screen needed (a still screen needs a few), so it says "frames/s" and no colour
/// or warning hangs on it: what says "slow" is the share of the drawn frames that
/// took longer than their time.
String frameLine(FrameSummary s) {
  String ms(double v, int digits) => v.toStringAsFixed(digits);
  return '${s.fps.round()} frames/s  '
      'build ${ms(s.buildAvgMs, 1)}/${ms(s.buildMaxMs, 0)}  '
      'draw ${ms(s.rasterAvgMs, 1)}/${ms(s.rasterMaxMs, 0)} ms  '
      'slow ${_slowPercent(s)}%';
}

int _slowPercent(FrameSummary s) =>
    s.fps <= 0 ? 0 : (100 * s.jank / s.fps).round();

/// Grey with nothing drawn; green up to 5 % slow (the budget in docs/36); yellow
/// up to 15 %; red above.
Color slowColour(FrameSummary s) {
  if (s.fps <= 0) return Colors.white70;
  final share = _slowPercent(s);
  if (share <= 5) return const Color(0xFF4ADE80);
  if (share <= 15) return const Color(0xFFFACC15);
  return const Color(0xFFF87171);
}

/// The second line of the counter. Words, not "190/284": that was read as "the
/// limit is 284 MB", and it is only the highest the app has used so far.
String resourceLine({
  required double? nowMb,
  required double peakMb,
  required double? cpuPercent,
}) =>
    'memory ${nowMb == null ? '?' : nowMb.round()} MB now, '
    'highest ${peakMb.round()} MB  '
    'cpu ${cpuPercent == null ? '?' : '${cpuPercent.round()}%'}';

/// A counter drawn over the whole app: frames per second, how long a frame
/// takes to build and to draw, memory, CPU. Off by default (Settings > About >
/// Diagnostics); costs nothing while off.
class PerfOverlay extends StatefulWidget {
  const PerfOverlay({super.key});

  @override
  State<PerfOverlay> createState() => _PerfOverlayState();
}

class _PerfOverlayState extends State<PerfOverlay> {
  final FrameStats _stats = FrameStats();
  final CpuMeter _cpu = CpuMeter();
  final Stopwatch _clock = Stopwatch()..start();
  Timer? _timer;

  FrameSummary _summary = FrameSummary.none;
  double? _cpuPercent;
  double? _rssMb;
  double _rssPeakMb = 0;

  @override
  void initState() {
    super.initState();
    SchedulerBinding.instance.addTimingsCallback(_onTimings);
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  @override
  void dispose() {
    _timer?.cancel();
    SchedulerBinding.instance.removeTimingsCallback(_onTimings);
    super.dispose();
  }

  void _onTimings(List<FrameTiming> timings) {
    final now = _clock.elapsedMilliseconds;
    for (final t in timings) {
      _stats.add(
        atMs: now,
        buildMs: t.buildDuration.inMicroseconds / 1000,
        rasterMs: t.rasterDuration.inMicroseconds / 1000,
      );
    }
  }

  void _tick() {
    if (!mounted) return;
    final now = _clock.elapsedMilliseconds;
    double? rss;
    try {
      rss = ProcessInfo.currentRss / (1024 * 1024);
    } on Object {
      rss = null;
    }
    setState(() {
      _summary = _stats.summary(now);
      _cpuPercent = _cpu.percent(now);
      _rssMb = rss;
      if (rss != null && rss > _rssPeakMb) _rssPeakMb = rss;
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = _summary;
    const mono = TextStyle(
      fontFamily: 'monospace',
      fontSize: 11,
      height: 1.25,
      color: Colors.white,
      decoration: TextDecoration.none,
      fontWeight: FontWeight.w500,
    );
    final cpu = _cpuPercent;
    final spike = (cpu != null && cpu > 80) || _slowPercent(s) > 15;
    return Positioned(
      top: MediaQuery.paddingOf(context).top + 4,
      left: 4,
      child: IgnorePointer(
        child: Semantics(
          label: 'Performance counter',
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: Colors.black.withValues(alpha: 0.72),
              borderRadius: BorderRadius.circular(6),
              border: spike
                  ? Border.all(color: const Color(0xFFF87171), width: 1)
                  : null,
            ),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
              child: Text.rich(
                TextSpan(style: mono, children: [
                  TextSpan(
                    text: '${frameLine(s)}\n',
                    style: TextStyle(
                        color: slowColour(s), fontWeight: FontWeight.w800),
                  ),
                  TextSpan(
                    text: resourceLine(
                      nowMb: _rssMb,
                      peakMb: _rssPeakMb,
                      cpuPercent: cpu,
                    ),
                  ),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
