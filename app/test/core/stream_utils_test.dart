import 'dart:async';

import 'package:encore/core/stream_utils.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('first event passes immediately, bursts collapse to the latest',
      () async {
    final source = StreamController<int>(sync: true);
    final seen = <int>[];
    final sub = source.stream
        .throttleLatest(const Duration(milliseconds: 60))
        .listen(seen.add);

    source.add(1);
    await pumpEventQueue();
    expect(seen, [1]);

    for (var i = 2; i <= 50; i++) {
      source.add(i);
    }
    await pumpEventQueue();
    expect(seen, [1], reason: 'held back inside the window');

    await Future<void>.delayed(const Duration(milliseconds: 90));
    expect(seen, [1, 50], reason: 'latest value delivered, intermediates gone');

    await sub.cancel();
    await source.close();
  });

  test('the last value is never lost when the source ends', () async {
    final source = StreamController<int>(sync: true);
    final done = Completer<void>();
    final seen = <int>[];
    source.stream
        .throttleLatest(const Duration(seconds: 5))
        .listen(seen.add, onDone: done.complete);

    source
      ..add(1)
      ..add(2)
      ..add(3);
    await source.close();
    await done.future;
    expect(seen, [1, 3]);
  });

  test('a quiet period resets the window', () async {
    final source = StreamController<int>(sync: true);
    final seen = <int>[];
    final sub = source.stream
        .throttleLatest(const Duration(milliseconds: 40))
        .listen(seen.add);
    source.add(1);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    source.add(2);
    await pumpEventQueue();
    expect(seen, [1, 2]);
    await sub.cancel();
    await source.close();
  });

  test('errors pass through', () async {
    final source = StreamController<int>(sync: true);
    final errors = <Object>[];
    final sub = source.stream
        .throttleLatest(const Duration(milliseconds: 10))
        .listen((_) {}, onError: errors.add);
    source.addError(StateError('boom'));
    await pumpEventQueue();
    expect(errors, hasLength(1));
    await sub.cancel();
    await source.close();
  });
}
