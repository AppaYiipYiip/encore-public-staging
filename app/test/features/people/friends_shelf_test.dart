import 'package:encore/features/people/people_providers.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_people_api.dart';
import '../../support/test_app.dart';

/// Home shows what the friends who chose to share are listening to (docs/35).
/// Nothing at all when nobody does, or when the server has no such service.
void main() {
  setUpAll(loadAppFonts);

  testWidgets('Home lists the friends who share, and what they play',
      (tester) async {
    final app = await pumpApp(tester, overrides: [
      friendsProvider.overrideWith((ref) => Stream.value([
            friendActivity('ben', 'Dogs'),
            friendActivity('tom', 'Sheep', playing: false),
          ])),
    ]);
    await settle(tester);

    expect(find.text('Friends'), findsOneWidget);
    expect(find.text('ben'), findsOneWidget);
    expect(find.text('Dogs • Pink Floyd'), findsWidgets);
    expect(find.text('Listening now'), findsOneWidget);
    expect(find.text('tom'), findsOneWidget);
    expect(find.text('Paused'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('a friend is read out whole to a screen reader', (tester) async {
    final handle = tester.ensureSemantics();
    final app = await pumpApp(tester, overrides: [
      friendsProvider
          .overrideWith((ref) => Stream.value([friendActivity('ben', 'Dogs')])),
    ]);
    await settle(tester);

    expect(find.bySemanticsLabel('ben, listening to Dogs by Pink Floyd'),
        findsOneWidget);
    await closeApp(tester, app.db);
    handle.dispose();
  });

  testWidgets('no Friends shelf when nobody shares', (tester) async {
    final app = await pumpApp(tester, overrides: [
      friendsProvider.overrideWith((ref) => Stream.value(const [])),
    ]);
    await settle(tester);

    expect(find.text('Friends'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('no Friends shelf on a server without the service',
      (tester) async {
    final app =
        await pumpApp(tester); // no session: the service is never even asked
    await settle(tester);

    expect(find.text('Friends'), findsNothing);
    await closeApp(tester, app.db);
  });
}
