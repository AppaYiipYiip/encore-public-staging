import 'dart:ui' as ui;

import 'package:encore/core/perf.dart';
import 'package:flutter_test/flutter_test.dart';

/// The measuring tool is held to the same standard as the app (docs/36 R6):
/// a number that cannot be trusted is worse than none. The owner's phone
/// "lagged" while the old numbers said a screen that only moved a progress bar
/// was 97 % janky: the numbers counted the time a frame waited for the screen's
/// next tick, not the work it did.
void main() {
  // One frame, in microseconds: how late its work started after the screen's
  // tick, how long the UI thread built it, how long the raster thread drew it.
  ui.FrameTiming frame({
    int lateUs = 0,
    int buildUs = 2000,
    int rasterUs = 3000,
    int at = 0,
  }) {
    final buildStart = at + lateUs;
    final buildFinish = buildStart + buildUs;
    final rasterFinish = buildFinish + rasterUs;
    return ui.FrameTiming(
      vsyncStart: at,
      buildStart: buildStart,
      buildFinish: buildFinish,
      rasterStart: buildFinish,
      rasterFinish: rasterFinish,
      rasterFinishWallTime: rasterFinish,
    );
  }

  late PerfMonitor monitor;
  setUp(() {
    monitor = PerfMonitor.instance
      ..logToConsole = false
      ..reset();
  });

  FrameSummary summaryOf(List<ui.FrameTiming> frames) {
    monitor.reset();
    monitor.addTimingsForTest(frames);
    return monitor.summary(budget: const Duration(microseconds: 16700));
  }

  test('a frame that did little work is not jank, however late it started', () {
    // The screen ticked, the app only woke 30 ms later, then drew in 5 ms.
    final s = summaryOf([for (var i = 0; i < 10; i++) frame(lateUs: 30000)]);

    expect(s.frames, 10);
    expect(s.jank, 0,
        reason: 'building took 2 ms and drawing 3 ms: that is not slow work');
    expect(s.workP90, const Duration(milliseconds: 5));
    expect(s.lateStartP90, const Duration(milliseconds: 30),
        reason: 'the wait is reported on its own, so it can be chased');
  });

  test('slow building or slow drawing is jank, whichever it is', () {
    final s = summaryOf([
      frame(buildUs: 20000, rasterUs: 1000), // the UI thread was too slow
      frame(buildUs: 1000, rasterUs: 25000), // the raster thread was too slow
      frame(buildUs: 8000, rasterUs: 8000), // fine: each thread had its time
    ]);

    expect(s.jank, 2);
    expect(s.severe, 0);
  });

  test('a frame of more than two budgets of work is a visible stutter', () {
    final s = summaryOf([frame(buildUs: 40000), frame()]);

    expect(s.severe, 1);
    expect(s.jank, 1);
  });

  test('says in its line how long the work took and how late it started', () {
    final line = summaryOf([
      frame(lateUs: 12000, buildUs: 4000, rasterUs: 6000),
    ]).describe();

    expect(line, contains('work p50=10.0ms'));
    expect(line, contains('late p90=12.0ms'));
  });

  test('nothing recorded says so with zeros, not a made-up figure', () {
    final s = summaryOf(const []);

    expect(s.frames, 0);
    expect(s.workP90, Duration.zero);
    expect(s.lateStartP90, Duration.zero);
  });
}
