import 'package:encore/core/perf_overlay.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('FrameStats', () {
    test('counts the frames of the last second, nothing older', () {
      final stats = FrameStats();
      for (var i = 0; i < 60; i++) {
        stats.add(atMs: 1000 + i * 16, buildMs: 3, rasterMs: 5);
      }
      expect(stats.summary(1960).fps, 60);
      // 1.5 s later only the frames of the last second are left.
      expect(stats.summary(2500).fps, lessThan(60));
      expect(stats.summary(5000).fps, 0);
      expect(stats.summary(5000), same(FrameSummary.none));
    });

    test(
        'says how long the UI and the raster threads took, average and '
        'worst', () {
      final stats = FrameStats();
      stats.add(atMs: 100, buildMs: 2, rasterMs: 4);
      stats.add(atMs: 200, buildMs: 4, rasterMs: 8);
      stats.add(atMs: 300, buildMs: 12, rasterMs: 6);
      final s = stats.summary(400);
      expect(s.buildAvgMs, closeTo(6, 0.001));
      expect(s.buildMaxMs, 12);
      expect(s.rasterAvgMs, closeTo(6, 0.001));
      expect(s.rasterMaxMs, 8);
      expect(s.jank, 0);
    });

    test('a frame over the budget on either thread is a stutter', () {
      final stats = FrameStats();
      stats.add(atMs: 100, buildMs: 20, rasterMs: 3); // UI too slow
      stats.add(atMs: 200, buildMs: 3, rasterMs: 40); // raster too slow
      stats.add(atMs: 300, buildMs: 3, rasterMs: 3);
      expect(stats.summary(400).jank, 2);
    });

    test('a faster screen has a tighter budget', () {
      final stats = FrameStats(budgetMs: 8.3); // 120 Hz
      stats.add(atMs: 100, buildMs: 10, rasterMs: 2);
      expect(stats.summary(200).jank, 1);
    });
  });

  group('the frame line', () {
    // "17 fps" in red was read as "the app can only do 17". A screen that does not
    // move draws only the few frames it needs, all of them fast. What says "slow" is
    // how many of the frames that WERE drawn missed their time.
    FrameSummary frames(int n, {int slow = 0}) => FrameSummary(
          fps: n.toDouble(),
          buildAvgMs: 1,
          buildMaxMs: 2,
          rasterAvgMs: 5,
          rasterMaxMs: 9,
          jank: slow,
        );

    test('an idle screen with a few fast frames is good, not red', () {
      final s = frames(6);
      expect(frameLine(s), startsWith('6 frames/s'));
      expect(frameLine(s), contains('slow 0%'));
      expect(slowColour(s), const Color(0xFF4ADE80));
    });

    test('says how many of the drawn frames were slow, and colours by it', () {
      expect(frameLine(frames(60, slow: 6)), contains('slow 10%'));
      expect(slowColour(frames(60, slow: 6)), const Color(0xFFFACC15));
      expect(slowColour(frames(60, slow: 3)), const Color(0xFF4ADE80));
      expect(slowColour(frames(60, slow: 20)), const Color(0xFFF87171));
    });

    test('no frames at all is neutral and says so', () {
      expect(frameLine(FrameSummary.none), startsWith('0 frames/s'));
      expect(slowColour(FrameSummary.none), Colors.white70);
    });

    test('names the two times plainly: build (the app) and draw (the screen)',
        () {
      final line = frameLine(frames(60));
      expect(line, contains('build 1.0/2'));
      expect(line, contains('draw 5.0/9 ms'));
      expect(line, isNot(contains('fps')));
    });
  });

  group('the memory line', () {
    // The owner read "ram 190/284 MB" as "the limit is 284 MB". It was the
    // use now and the highest so far. A label nobody can read is a defect.
    test('says what is used now and what the highest was, in words', () {
      expect(
        resourceLine(nowMb: 190.4, peakMb: 284.2, cpuPercent: 37.6),
        'memory 190 MB now, highest 284 MB  cpu 38%',
      );
    });

    test('says "?" for what could not be read, never a made-up number', () {
      expect(
        resourceLine(nowMb: null, peakMb: 0, cpuPercent: null),
        'memory ? MB now, highest 0 MB  cpu ?',
      );
    });

    test('never says "limit" or shows a bare slash that reads as one', () {
      final line = resourceLine(nowMb: 190, peakMb: 284, cpuPercent: 1);
      expect(line, isNot(contains('limit')));
      expect(line, isNot(contains('/')));
    });
  });

  group('CpuMeter', () {
    // /proc/<pid>/stat: "pid (name) state ppid ... utime stime ..."
    String line(int user, int system, {String name = 'app.encore.player'}) =>
        '4242 ($name) S 1 4242 4242 0 -1 4194560 100 0 0 0 '
        '$user $system 0 0 20 0 30 0 5000 1000000 100 18446744073709551615';

    test('reads user + system ticks', () {
      expect(CpuMeter.ticksIn(line(150, 50)), 200);
    });

    test('a process name with spaces and brackets does not shift the fields',
        () {
      expect(CpuMeter.ticksIn(line(7, 3, name: 'my (odd) app')), 10);
    });

    test('garbage is "unknown", not a crash', () {
      expect(CpuMeter.ticksIn(''), isNull);
      expect(CpuMeter.ticksIn('no brackets here'), isNull);
      expect(CpuMeter.ticksIn('1 (x) S 1 2'), isNull);
    });

    test('percent of one core between two looks', () {
      var ticks = 1000;
      final meter =
          CpuMeter(readStat: () => line(ticks, 0), ticksPerSecond: 100);
      expect(meter.percent(0), isNull, reason: 'nothing to compare with yet');
      ticks += 50; // half a second of CPU...
      expect(meter.percent(1000), closeTo(50, 0.001)); // ...in one second
      ticks += 400; // four seconds of CPU in one second: four cores busy
      expect(meter.percent(2000), closeTo(400, 0.001));
    });

    test('no /proc (another platform) is simply unknown', () {
      final meter = CpuMeter(readStat: () => throw StateError('no such file'));
      expect(meter.percent(0), isNull);
    });
  });

  testWidgets(
      'the counter draws two lines, does not take taps, and stops '
      'with its screen', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
      home: Stack(children: [
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => taps++,
          child: const SizedBox.expand(),
        ),
        const PerfOverlay(),
      ]),
    ));
    await tester.pump(const Duration(seconds: 1));
    expect(find.textContaining('frames/s'), findsOneWidget);
    expect(find.textContaining('memory'), findsOneWidget);
    expect(find.textContaining('cpu'), findsOneWidget);

    // A tap on the counter itself reaches the screen below it.
    final box = tester.getRect(find.textContaining('frames/s'));
    await tester.tapAt(box.center);
    expect(taps, 1, reason: 'the tap went through the counter');

    // Removing it leaves no timer behind (the test would fail on one).
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(seconds: 3));
  });
}
