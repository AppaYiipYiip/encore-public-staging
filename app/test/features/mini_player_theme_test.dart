import 'package:encore/features/player/mini_player.dart';
import 'package:encore/features/settings/settings_controller.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

/// QA round 1, R1-6: in the light theme the mini player (always a dark tint of the cover) had dark grey words on it, hardly readable.
void main() {
  setUpAll(loadAppFonts);

  testWidgets('in the light theme the words on the dark bar are light',
      (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    final container =
        ProviderScope.containerOf(tester.element(find.byType(MiniPlayer)));
    container.read(settingsProvider.notifier).setThemeMode(ThemeMode.light);
    await tester.pump(const Duration(milliseconds: 400));
    await settle(tester);

    Color colorOf(String text) => tester
        .widget<Text>(find.descendant(
            of: find.byType(MiniPlayer), matching: find.text(text)))
        .style!
        .color!;
    expect(colorOf('Opening The').computeLuminance(), greaterThan(0.6));
    expect(colorOf('Periphery').computeLuminance(), greaterThan(0.4));
    await closeApp(tester, app.db);
  });
}
