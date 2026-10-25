import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// What the player's buttons and the lines of its "..." menu say, as a person meets them for the first time. The owner, 2026-10-17, looking at
/// the player: "what does the lock icon mean? I do not think people would understand." Since 2026-10-24 the lock is a line of the menu
/// ("Private listening: off"), as Spotify has it, and the sentence appears when it is switched.
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

  Future<void> tapMenuLine(WidgetTester tester, String line) async {
    await tester.tap(find.byTooltip('More options'));
    await settle(tester);
    await tester.tap(find.text(line));
    await settle(tester);
  }

  testWidgets('every button under the controls says what it is',
      (tester) async {
    final db = await openPlayer(tester);

    for (final tooltip in ['Choose where to play', 'Queue', 'More options']) {
      expect(find.byTooltip(tooltip), findsOneWidget, reason: tooltip);
    }
    await closeApp(tester, db);
  });

  testWidgets('every line of the "..." menu says what it does', (tester) async {
    final db = await openPlayer(tester);

    await tester.tap(find.byTooltip('More options'));
    await settle(tester);

    for (final line in [
      'Playback speed',
      'Sleep timer',
      'Private listening: off',
    ]) {
      expect(find.text(line), findsOneWidget, reason: line);
    }
    await closeApp(tester, db);
  });

  testWidgets('turning on private listening says what it does', (tester) async {
    final db = await openPlayer(tester);

    await tapMenuLine(tester, 'Private listening: off');

    expect(containerOf(tester).read(settingsProvider).privateListening, isTrue);
    expect(find.textContaining('not shared with friends'), findsOneWidget,
        reason: 'a lock alone does not say it');
    await closeApp(tester, db);
  });

  testWidgets('turning it off says so', (tester) async {
    final db = await openPlayer(tester);
    await tapMenuLine(tester, 'Private listening: off');

    await tapMenuLine(tester, 'Private listening: on');

    expect(find.textContaining('Private listening is off'), findsWidgets);
    expect(
        containerOf(tester).read(settingsProvider).privateListening, isFalse);
    await closeApp(tester, db);
  });
}
