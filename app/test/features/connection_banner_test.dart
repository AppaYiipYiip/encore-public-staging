import 'dart:async';

import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// The strip above the player (owner, 2026-10-17: "a widget to show you lost
/// the internet").
void main() {
  setUpAll(loadAppFonts);

  testWidgets('without internet it says so, and that music still plays',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      connectionGraceProvider.overrideWithValue(Duration.zero),
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.none)),
    ]);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    expect(find.textContaining('You\'re offline'), findsOneWidget);
    expect(find.textContaining('Downloaded music still plays'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('a server that does not answer says so, and offers to try again',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      connectionGraceProvider.overrideWithValue(Duration.zero),
      serverReachableProvider.overrideWith((ref) => Stream.value(false)),
    ]);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    expect(find.text('Can\'t reach your server.'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('when everything works there is no strip at all', (tester) async {
    final app = await pumpApp(tester);
    await settle(tester);

    expect(find.textContaining('offline'), findsNothing);
    expect(find.textContaining('Can\'t reach'), findsNothing);
    await closeApp(tester, app.db);
  });

  group('whether the server answers', () {
    test(
        'a change announced right after the first value is not lost (the strip '
        'stayed up over a server that worked, 2026-10-18)', () async {
      // The answer arrives within milliseconds of a start from a share: before
      // the first version of the stream had subscribed to the changes.
      var reachable = false;
      final changes = StreamController<bool>.broadcast();
      final seen = <bool>[];
      final sub = reachabilityStream(() => reachable, changes.stream).listen(
        (value) {
          seen.add(value);
          if (seen.length == 1) {
            reachable = true;
            changes.add(true);
          }
        },
      );
      await pumpEventQueue();

      expect(seen, [false, true]);
      await sub.cancel();
      await changes.close();
    });

    test('it follows later changes and stops listening when cancelled',
        () async {
      const reachable = true;
      final changes = StreamController<bool>.broadcast();
      final seen = <bool>[];
      final sub =
          reachabilityStream(() => reachable, changes.stream).listen(seen.add);
      await pumpEventQueue();
      changes.add(false);
      await pumpEventQueue();
      expect(seen, [true, false]);

      await sub.cancel();
      expect(changes.hasListener, isFalse);
      await changes.close();
    });
  });
}
