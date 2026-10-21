import 'package:encore/features/player/speed_sheet.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

void main() {
  setUpAll(loadAppFonts);
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('labels read naturally', () {
    expect(speedLabel(1), '1x');
    expect(speedLabel(2), '2x');
    expect(speedLabel(1.25), '1.25x');
    expect(speedLabel(1.5), '1.5x');
    expect(speedLabel(0.75), '0.75x');
  });

  testWidgets('the player offers speeds, applies and remembers the choice',
      (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    await tester.tap(find.text('Opening The').first);
    await settle(tester);

    expect(find.byTooltip('Playback speed'), findsOneWidget);
    await tester.tap(find.byTooltip('Playback speed'));
    await settle(tester);
    expect(find.text('Playback speed'), findsWidgets);
    expect(find.text('1.25x'), findsOneWidget);

    await tester.tap(find.text('1.5x'));
    await settle(tester);

    expect(app.facade.calls, contains('speed(1.5)'));
    final container = ProviderScope.containerOf(
        tester.element(find.text('Opening The').first));
    expect(container.read(settingsProvider).playbackSpeed, 1.5);
    // The player shows that a non-default speed is active.
    expect(find.text('1.5x'), findsOneWidget);
    await closeApp(tester, app.db);
  });
}
