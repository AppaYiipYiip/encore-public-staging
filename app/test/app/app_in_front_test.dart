import 'package:encore/app/app_in_front.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// docs/design S-95 (P2-29): the card is live while the app is in front and dated once the person has left it. Pulling the notification shade down
/// over the app only makes it "inactive": that is not leaving.
void main() {
  testWidgets('in front while resumed, and while the shade is pulled over it',
      (tester) async {
    final c = ProviderContainer();
    addTearDown(c.dispose);
    c.listen(appInFrontProvider, (_, __) {});

    expect(c.read(appInFrontProvider), isTrue);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    expect(c.read(appInFrontProvider), isTrue,
        reason: 'the shade, a phone call banner or the recents button');
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    expect(c.read(appInFrontProvider), isTrue);
  });

  testWidgets('left when hidden, paused or detached; back when resumed',
      (tester) async {
    final c = ProviderContainer();
    addTearDown(c.dispose);
    c.listen(appInFrontProvider, (_, __) {});
    void go(AppLifecycleState next) =>
        tester.binding.handleAppLifecycleStateChanged(next);

    // The way Android walks it: resumed, inactive, hidden, paused, (detached), and back the same way.
    go(AppLifecycleState.inactive);
    expect(c.read(appInFrontProvider), isTrue);
    go(AppLifecycleState.hidden);
    expect(c.read(appInFrontProvider), isFalse);
    go(AppLifecycleState.paused);
    expect(c.read(appInFrontProvider), isFalse);
    go(AppLifecycleState.detached);
    expect(c.read(appInFrontProvider), isFalse);
    go(AppLifecycleState.resumed);
    expect(c.read(appInFrontProvider), isTrue);
  });
}
