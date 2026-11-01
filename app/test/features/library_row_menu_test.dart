import 'package:encore/data/db/app_database.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// D-26 (F31): every row of Your Library has a visible "..." and a long press, and both open the collection menu (rename and delete for a
/// playlist the person made, "Play next", "Add to queue" and "Add to playlist" for the songs in it).
void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<({AppDatabase db, FakePlaybackFacade facade, int serverId})>
      openLibrary(WidgetTester tester) async {
    final app = await pumpApp(tester, size: const Size(390, 1400));
    await tester.tap(find.text('Your Library').last);
    await settle(tester);
    return app;
  }

  testWidgets(
      'a playlist the person made: the three dots open rename, delete and the queue actions',
      (tester) async {
    final app = await openLibrary(tester);

    await tester.tap(find.byTooltip('More options for Late night'));
    await settle(tester);

    expect(find.text('Rename playlist'), findsOneWidget);
    expect(find.text('Delete playlist'), findsOneWidget);
    expect(find.text('Play next'), findsOneWidget);
    expect(find.text('Add to queue'), findsOneWidget);
    expect(find.text('Add to playlist'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('a long press on the row opens the same menu', (tester) async {
    final app = await openLibrary(tester);

    await tester.longPress(find.text('Late night'));
    await settle(tester);

    expect(find.text('Rename playlist'), findsOneWidget);
    expect(find.text('Add to queue'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a playlist the server made cannot be renamed or deleted from its menu',
      (tester) async {
    final app = await openLibrary(tester);

    await tester.tap(find.byTooltip('More options for Phone Offline'));
    await settle(tester);

    expect(find.text('Rename playlist'), findsNothing);
    expect(find.text('Delete playlist'), findsNothing);
    expect(find.text('Add to queue'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('"Play next" from a row queues that playlist\'s songs',
      (tester) async {
    final app = await openLibrary(tester);

    await tester.tap(find.byTooltip('More options for Late night'));
    await settle(tester);
    await tester.tap(find.text('Play next'));
    await settle(tester);

    expect(app.facade.calls.where((c) => c.startsWith('next(')), hasLength(3),
        reason: 'Late night has three songs');
    await closeApp(tester, app.db);
  });

  testWidgets('the Liked Songs row has the menu too', (tester) async {
    final app = await openLibrary(tester);

    await tester.tap(find.byTooltip('More options for Liked Songs'));
    await settle(tester);

    expect(find.text('Add to queue'), findsOneWidget);
    expect(find.text('Rename playlist'), findsNothing);
    await closeApp(tester, app.db);
  });
}
