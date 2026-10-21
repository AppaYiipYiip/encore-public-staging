import 'dart:async';

import 'package:encore/playback/position_pump.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late Duration position;
  late List<Duration> emitted;
  late List<Duration> timerRequests;
  late List<void Function(Timer)> callbacks;
  late int cancelled;

  PositionPump build({Duration tick = const Duration(milliseconds: 200)}) =>
      PositionPump(
        read: () => position,
        emit: emitted.add,
        tick: tick,
        periodic: (interval, callback) {
          timerRequests.add(interval);
          callbacks.add(callback);
          return _FakeTimer(onCancel: () => cancelled++);
        },
      );

  setUp(() {
    position = Duration.zero;
    emitted = [];
    timerRequests = [];
    callbacks = [];
    cancelled = 0;
  });

  test('a paused or idle player has no timer at all', () {
    final pump = build();
    pump.update(running: false);
    pump.update(running: false);

    expect(timerRequests, isEmpty, reason: 'nothing to tick for');
    expect(pump.isRunning, isFalse);
  });

  test('ticks at the configured interval only while playing', () {
    final pump = build(tick: const Duration(milliseconds: 250));
    pump.update(running: true);
    pump.update(running: true); // state noise must not stack timers

    expect(timerRequests, [const Duration(milliseconds: 250)]);
    expect(pump.isRunning, isTrue);

    position = const Duration(seconds: 1);
    callbacks.single(_FakeTimer());
    position = const Duration(seconds: 2);
    callbacks.single(_FakeTimer());

    expect(emitted.last, const Duration(seconds: 2));
  });

  test('pausing stops the timer and reports where playback stopped', () {
    final pump = build();
    pump.update(running: true);
    position = const Duration(seconds: 42);
    pump.update(running: false);

    expect(cancelled, 1);
    expect(pump.isRunning, isFalse);
    expect(emitted.last, const Duration(seconds: 42));
  });

  test('an unchanged position is not emitted twice', () {
    final pump = build();
    position = const Duration(seconds: 5);
    pump.poke();
    pump.poke();
    pump.update(running: false);

    expect(emitted, [const Duration(seconds: 5)]);
  });

  test('a seek while paused is reported without starting a timer', () {
    final pump = build();
    pump.update(running: false);
    position = const Duration(seconds: 90);
    pump.poke();

    expect(emitted.last, const Duration(seconds: 90));
    expect(timerRequests, isEmpty);
  });

  test('after dispose nothing runs and nothing is emitted', () {
    final pump = build();
    pump.update(running: true);
    pump.dispose();
    final before = emitted.length;
    position = const Duration(seconds: 9);
    pump.poke();
    pump.update(running: true);

    expect(cancelled, 1);
    expect(emitted.length, before);
  });
}

class _FakeTimer implements Timer {
  _FakeTimer({this.onCancel});

  final void Function()? onCancel;
  bool _active = true;

  @override
  void cancel() {
    if (_active) onCancel?.call();
    _active = false;
  }

  @override
  bool get isActive => _active;

  @override
  int get tick => 0;
}
