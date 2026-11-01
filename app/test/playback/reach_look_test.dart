import 'dart:async';

import 'package:encore/core/clock.dart';
import 'package:encore/playback/reach_look.dart';
import 'package:flutter_test/flutter_test.dart';

/// The one look at the server before a song that is not downloaded is refused (field test 2026-10-31, found by the code review: a look that
/// was still running made the callers behind it refuse at once, and every caller made its own look).
void main() {
  late FakeClock clock;
  late int asked;
  late Completer<bool>? gate;
  late bool answer;

  ReachLook make() => ReachLook(
        clock: clock,
        look: () async {
          asked++;
          if (gate != null) return gate!.future;
          return answer;
        },
      );

  setUp(() {
    clock = FakeClock(DateTime.utc(2026, 10, 31, 22));
    asked = 0;
    gate = null;
    answer = false;
  });

  test(
      'callers that arrive while the look is running wait for it and get its answer',
      () async {
    gate = Completer<bool>();
    final reach = make();

    final first = reach();
    final second = reach();
    gate!.complete(true);

    expect(await first, isTrue);
    expect(await second, isTrue,
        reason: 'not refused while the answer is still on its way');
    expect(asked, 1);
  });

  test('after a look that found nobody, nobody asks again for a few seconds',
      () async {
    final reach = make();

    expect(await reach(), isFalse);
    expect(await reach(), isFalse);
    expect(await reach(), isFalse);
    expect(asked, 1,
        reason: 'a list of songs that are not downloaded: one look');

    clock.advance(const Duration(seconds: 6));
    answer = true;
    expect(await reach(), isTrue);
    expect(asked, 2);
  });

  test('an answer of yes is not remembered: the next question is asked again',
      () async {
    answer = true;
    final reach = make();

    expect(await reach(), isTrue);
    answer = false;
    expect(await reach(), isFalse);
    expect(asked, 2);
  });

  test('a look that fails counts as nobody answering', () async {
    final reach = ReachLook(
      clock: clock,
      look: () async => throw StateError('no route'),
    );

    expect(await reach(), isFalse);
  });
}
