import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/instant/instant_controller.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// Settings, read the way a stranger reads them (docs/40, walk of 2026-10-18):
/// "'rebuild'? 'shared servers'? What is a 'download service'? Why are 'Import
/// music' and 'Get new music' two things?"
void main() {
  setUpAll(loadAppFonts);

  Future<AppDatabase> openSettings(WidgetTester tester,
      {bool instant = false}) async {
    final app = await pumpApp(tester,
        size: const Size(390, 1800),
        overrides: [instantAvailableProvider.overrideWithValue(instant)]);
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/settings');
    await settle(tester);
    return app.db;
  }

  testWidgets('every row says what it is for in everyday words',
      (tester) async {
    final db = await openSettings(tester);

    expect(find.text('Privacy & your music'), findsOneWidget);
    expect(find.text('Update now, fix a library that looks wrong'),
        findsOneWidget);
    for (final jargon in ['rebuild', 'shared servers', 'scrobble']) {
      expect(find.textContaining(jargon), findsNothing, reason: jargon);
    }
    await closeApp(tester, db);
  });

  testWidgets(
      'where songs can be played at once there is no "download service": '
      'there is Notifications', (tester) async {
    final db = await openSettings(tester, instant: true);

    expect(find.text('Get new music'), findsNothing);
    expect(find.text('Notifications'), findsOneWidget);
    await closeApp(tester, db);
  });

  testWidgets('without play-any-song the download service entry stays',
      (tester) async {
    final db = await openSettings(tester);

    expect(find.text('Get new music'), findsOneWidget);
    expect(find.text('Notifications'), findsNothing);
    await closeApp(tester, db);
  });

  testWidgets(
      'Notifications holds the three switches and nothing about a '
      'download service', (tester) async {
    final db = await openSettings(tester, instant: true);

    await tester.tap(find.text('Notifications'));
    await settle(tester);

    expect(find.text('New on your server'), findsOneWidget);
    expect(find.text('New releases you do not have'), findsOneWidget);
    expect(find.text('Imports and requests'), findsOneWidget);
    expect(find.textContaining('download service'), findsNothing);
    final container =
        ProviderScope.containerOf(tester.element(find.byType(Scaffold).first));
    final defaults = container.read(settingsProvider);
    expect([
      defaults.alertsOnServer,
      defaults.alertsReleases,
      defaults.alertsImports
    ], everyElement(isFalse),
        reason: 'ADR-R44: nothing is posted to the phone unless the person '
            'switches it on, so nothing asks for the permission at first run');
    await tester.tap(find.text('New on your server'));
    await settle(tester);
    expect(container.read(settingsProvider).alertsOnServer, isTrue);
    await closeApp(tester, db);
  });
}
