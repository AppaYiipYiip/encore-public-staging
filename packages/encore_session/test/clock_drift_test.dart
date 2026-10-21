import 'dart:math';

import 'package:encore_session/src/clock.dart';
import 'package:encore_session/src/drift.dart';
import 'package:test/test.dart';

/// A pretend network between a device and the hub: the hub's clock is
/// `device clock + skew`; each direction takes `base + random jitter`.
class FakeLink {
  FakeLink({
    required this.skewMs,
    required this.baseMs,
    required this.jitterMs,
    required int seed,
  }) : _random = Random(seed);

  final int skewMs;
  final int baseMs;
  final int jitterMs;
  final Random _random;

  int _leg() => baseMs + (jitterMs == 0 ? 0 : _random.nextInt(jitterMs + 1));

  ClockSample ask(int localNowMs) {
    final out = _leg();
    final back = _leg();
    final hubAtArrival = localNowMs + out + skewMs;
    return ClockSample(
      sentMs: localNowMs,
      receivedMs: localNowMs + out + back,
      hubMs: hubAtArrival,
    );
  }
}

void main() {
  group('clock estimator', () {
    test('a symmetric link gives the exact offset', () {
      final e = ClockEstimator();
      final link = FakeLink(skewMs: 7000, baseMs: 20, jitterMs: 0, seed: 1);
      for (var i = 0; i < 5; i++) {
        e.add(link.ask(1000 + i * 1000));
      }
      expect(e.isReady, isTrue);
      expect(e.offsetMs, 7000);
      expect(e.hubNow(50000), 57000);
    });

    test('with jitter the estimate is within the jitter, over many seeds', () {
      var worst = 0;
      for (var seed = 0; seed < 200; seed++) {
        final e = ClockEstimator();
        final link =
            FakeLink(skewMs: -2500, baseMs: 30, jitterMs: 120, seed: seed);
        for (var i = 0; i < 5; i++) {
          e.add(link.ask(i * 1000));
        }
        worst = max(worst, (e.offsetMs - -2500).abs());
      }
      // The doc's promise: players converge within 150 ms even on a bad link.
      expect(worst, lessThan(150), reason: 'worst error was $worst ms');
    });

    test('a slow, lopsided round trip does not drag the estimate', () {
      final e = ClockEstimator();
      final link = FakeLink(skewMs: 100, baseMs: 10, jitterMs: 0, seed: 1);
      for (var i = 0; i < 4; i++) {
        e.add(link.ask(i * 1000));
      }
      // One awful sample: the request took 10 ms, the answer 900 ms.
      e.add(const ClockSample(sentMs: 5000, receivedMs: 5910, hubMs: 5110));
      expect((e.offsetMs - 100).abs(), lessThan(5));
    });

    test('not ready until it has a few samples; reset forgets', () {
      final e = ClockEstimator();
      e.add(const ClockSample(sentMs: 0, receivedMs: 10, hubMs: 5));
      expect(e.isReady, isFalse);
      e.reset();
      expect(e.sampleCount, 0);
      expect(e.offsetMs, 0);
    });

    test('a sample from a clock that went backwards is ignored', () {
      final e = ClockEstimator();
      e.add(const ClockSample(sentMs: 100, receivedMs: 50, hubMs: 80));
      expect(e.sampleCount, 0);
    });
  });

  group('drift controller', () {
    const c = DriftController();

    test('close enough: hold', () {
      expect(c.decide(playerMs: 1020, targetMs: 1000, speed: 1), isA<Hold>());
    });

    test('far off: seek to where the hub says', () {
      final a = c.decide(playerMs: 5000, targetMs: 4000, speed: 1);
      expect(a, isA<SeekTo>());
      expect((a as SeekTo).targetMs, 4000);
    });

    test('a little ahead slows down, a little behind speeds up, within 2 %',
        () {
      final slow =
          c.decide(playerMs: 1100, targetMs: 1000, speed: 1) as SetSpeed;
      expect(slow.speed, lessThan(1));
      final fast =
          c.decide(playerMs: 900, targetMs: 1000, speed: 1) as SetSpeed;
      expect(fast.speed, greaterThan(1));
      final most =
          c.decide(playerMs: 1240, targetMs: 1000, speed: 1) as SetSpeed;
      expect(most.speed, closeTo(0.98, 1e-9));
    });

    test('back in line: return to normal speed, once', () {
      final back = c.decide(playerMs: 1005, targetMs: 1000, speed: 0.99);
      expect(back, isA<SetSpeed>());
      expect((back as SetSpeed).speed, 1.0);
      expect(c.decide(playerMs: 1005, targetMs: 1000, speed: 1), isA<Hold>());
    });

    test('in the grey zone between settled and nudging it does not flap', () {
      expect(
          c.decide(playerMs: 1030, targetMs: 1000, speed: 0.99), isA<Hold>());
    });

    test('simulated: any start within the seek limit converges in 30 s', () {
      for (final start in [-240, -100, -45, 45, 100, 240]) {
        var player = 100000 + start; // ms
        var target = 100000;
        var speed = 1.0;
        for (var t = 0; t < 30000; t += 2000) {
          final action =
              c.decide(playerMs: player, targetMs: target, speed: speed);
          if (action is SeekTo) player = action.targetMs;
          if (action is SetSpeed) speed = action.speed;
          player += (2000 * speed).round();
          target += 2000;
        }
        expect((player - target).abs(), lessThan(40),
            reason: 'start $start ended at ${player - target}');
      }
    });
  });
}
