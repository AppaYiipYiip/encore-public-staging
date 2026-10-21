import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// The row of buttons under the player's controls, as a person meets it for the
/// first time. The owner, 2026-10-17, looking at the player: "what does the
/// lock icon mean? I do not think people would understand."
void main() {
  setUpAll(loadAppFonts);

  ProviderContainer containerOf(WidgetTester tester) =>
      ProviderScope.containerOf(tester.element(find.byType(Scaffold).first));

  Future<AppDatabase> openPlayer(WidgetTester tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    await tester.tap(find.text('Opening The').first);
    await settle(tester);
    return app.db;
  }

  testWidgets('every button under the controls says what it is',
      (tester) async {
    final db = await openPlayer(tester);

    for (final label in [
      'Devices',
      'Speed',
      'Sleep timer',
      'Private',
      'Queue'
    ]) {
      expect(find.text(label), findsOneWidget, reason: label);
    }
    await closeApp(tester, db);
  });

  testWidgets('turning on private listening says what it does', (tester) async {
    final db = await openPlayer(tester);

    await tester
        .tap(find.byTooltip('Private listening is off. Tap to turn it on'));
    await settle(tester);

    expect(containerOf(tester).read(settingsProvider).privateListening, isTrue);
    expect(find.textContaining('not shared with friends'), findsOneWidget,
        reason: 'a lock alone does not say it');
    await closeApp(tester, db);
  });

  testWidgets('turning it off says so', (tester) async {
    final db = await openPlayer(tester);
    await tester
        .tap(find.byTooltip('Private listening is off. Tap to turn it on'));
    await settle(tester);

    await tester
        .tap(find.byTooltip('Private listening is on. Tap to turn it off'));
    await settle(tester);

    expect(find.textContaining('Private listening is off'), findsWidgets);
    expect(
        containerOf(tester).read(settingsProvider).privateListening, isFalse);
    await closeApp(tester, db);
  });
}
