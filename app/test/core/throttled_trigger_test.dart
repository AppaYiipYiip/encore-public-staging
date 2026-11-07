import 'package:encore/core/throttled_trigger.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets(
      'the first call runs at once; calls inside the window run once more at its end; a quiet spell runs the next call at once',
      (tester) async {
    var now = DateTime.utc(2026, 11, 7, 14);
    var runs = 0;
    final trigger = ThrottledTrigger(const Duration(seconds: 10), () => runs++,
        clock: () => now);

    trigger();
    expect(runs, 1, reason: 'the first call is not delayed');

    for (var i = 0; i < 5; i++) {
      now = now.add(const Duration(seconds: 1));
      await tester.pump(const Duration(seconds: 1));
      trigger();
    }
    expect(runs, 1, reason: 'five more calls in the window wait');

    now = now.add(const Duration(seconds: 5));
    await tester.pump(const Duration(seconds: 5));
    expect(runs, 2, reason: 'one more run at the end of the window');

    now = now.add(const Duration(minutes: 1));
    await tester.pump(const Duration(minutes: 1));
    trigger();
    expect(runs, 3, reason: 'after a quiet spell the call runs at once');

    trigger.dispose();
  });

  testWidgets('disposing drops a run that was waiting', (tester) async {
    var now = DateTime.utc(2026, 11, 7, 14);
    var runs = 0;
    final trigger = ThrottledTrigger(const Duration(seconds: 10), () => runs++,
        clock: () => now);
    trigger();
    now = now.add(const Duration(seconds: 2));
    trigger();
    trigger.dispose();
    await tester.pump(const Duration(seconds: 30));
    expect(runs, 1);
  });
}
