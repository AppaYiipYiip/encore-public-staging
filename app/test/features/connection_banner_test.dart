import 'dart:async';

import 'package:encore/app/connection.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/features/providers.dart' show downloadedIdsProvider;
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
      downloadedIdsProvider.overrideWith((ref) => Stream.value({'al1-t1'})),
    ]);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    expect(find.textContaining('You\'re offline'), findsOneWidget);
    expect(find.textContaining('Downloaded music still plays'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'without internet and with nothing downloaded it does not promise music that is not there (Q30 note, Q31)',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      connectionGraceProvider.overrideWithValue(Duration.zero),
      networkKindProvider.overrideWith((ref) => Stream.value(NetworkKind.none)),
      downloadedIdsProvider.overrideWith((ref) => Stream.value(<String>{})),
    ]);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    expect(find.textContaining('You\'re offline'), findsOneWidget);
    expect(find.textContaining('Downloaded music still plays'), findsNothing,
        reason: 'nothing is downloaded');
    expect(find.textContaining('Nothing can play until you reconnect'),
        findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a server that does not answer says the same calm thing as no internet, and can be put away (field test 2026-10-31)',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      connectionGraceProvider.overrideWithValue(Duration.zero),
      serverReachableProvider.overrideWith((ref) => Stream.value(false)),
      downloadedIdsProvider.overrideWith((ref) => Stream.value({'al1-t1'})),
    ]);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    expect(find.textContaining("You're offline"), findsOneWidget);
    expect(find.textContaining('Downloaded music still plays'), findsOneWidget);
    expect(find.textContaining("Can't reach"), findsNothing,
        reason: 'the radio is on and there is no data: that is being offline');

    await tester.tap(find.byTooltip('Dismiss'));
    await settle(tester);

    expect(find.textContaining("You're offline"), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'CN-11, O-6: an address that answers as another server is named, not hidden behind "You\'re offline"',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      connectionGraceProvider.overrideWithValue(Duration.zero),
      serverReachableProvider.overrideWith((ref) => Stream.value(false)),
      anotherServerAtProvider.overrideWith(
          (ref) => Stream.value(Uri.parse('http://192.168.1.10:4533'))),
      downloadedIdsProvider.overrideWith((ref) => Stream.value({'al1-t1'})),
    ]);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    expect(
        find.text('Another server answers at 192.168.1.10.'), findsOneWidget);
    expect(find.textContaining("You're offline"), findsNothing,
        reason: 'the phone is online: something answers, it is not the server');

    await tester.tap(find.byTooltip('Dismiss'));
    await settle(tester);

    expect(find.textContaining('Another server answers'), findsNothing,
        reason: 'said once, and put away with the cross');
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
