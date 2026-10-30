import 'package:encore/data/db/app_database.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// What the player's buttons and the lines of its "..." menu say, as a person meets them for the first time. The owner, 2026-10-17, looking at
/// the player: "what does the lock icon mean? I do not think people would understand." Since 2026-10-24 the lock is a line of the menu
/// ("Private listening: off"), as Spotify has it, and the sentence appears when it is switched.
void main() {
  setUpAll(loadAppFonts);

  Future<AppDatabase> openPlayer(WidgetTester tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    await tester.tap(find.text('Opening The').first);
    await settle(tester);
    return app.db;
  }

  testWidgets('every button under the controls says what it is',
      (tester) async {
    final db = await openPlayer(tester);

    for (final tooltip in ['Queue', 'More options']) {
      expect(find.byTooltip(tooltip), findsOneWidget, reason: tooltip);
    }
    expect(find.byTooltip('Choose where to play'), findsNothing,
        reason: 'D-28: no device icon');
    await closeApp(tester, db);
  });

  testWidgets('every line of the "..." menu says what it does', (tester) async {
    final db = await openPlayer(tester);

    await tester.tap(find.byTooltip('More options'));
    await settle(tester);

    expect(find.text('Sleep timer'), findsOneWidget);
    for (final line in ['Playback speed', 'Private listening: off']) {
      expect(find.text(line), findsNothing, reason: 'D-23: $line is not here');
    }
    await closeApp(tester, db);
  });
}
