import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// Strict-accessibility gate: the main screens must lay out without overflow
/// at the largest text sizes Android offers (up to 2x), and their tap targets
/// and labels must pass Flutter's guidelines.
void main() {
  setUpAll(loadAppFonts);

  const screens = <String, String>{
    'home': '/home',
    'search': '/search',
    'library': '/library',
    'album': '/home/album/al1',
    'playlist': '/home/playlist/pl1',
    'liked': '/home/liked',
    'downloaded': '/home/downloaded',
    'settings': '/settings',
    'downloads settings': '/settings/downloads',
    'playback settings': '/settings/playback',
    'sync settings': '/settings/sync',
  };

  Future<void> open(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  group('large text does not overflow', () {
    for (final scale in const [1.5, 2.0]) {
      for (final entry in screens.entries) {
        testWidgets('${entry.key} at ${scale}x', (tester) async {
          tester.platformDispatcher.textScaleFactorTestValue = scale;
          addTearDown(tester.platformDispatcher.clearAllTestValues);
          final app = await pumpApp(tester);
          await open(tester, entry.value);

          expect(tester.takeException(), isNull,
              reason: '${entry.key} overflowed at ${scale}x text');
          await closeApp(tester, app.db);
        });
      }
    }

    testWidgets('now playing at 2x', (tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearAllTestValues);
      final app = await pumpApp(tester, playing: samplePlaying());
      await open(tester, '/player');

      expect(tester.takeException(), isNull);
      await closeApp(tester, app.db);
    });
  });

  group('tap targets and labels', () {
    for (final entry in screens.entries) {
      testWidgets('${entry.key}: 48 dp targets and labelled actions',
          (tester) async {
        final handle = tester.ensureSemantics();
        final app = await pumpApp(tester);
        await open(tester, entry.value);

        await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
        await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
        await closeApp(tester, app.db);
        handle.dispose();
      });
    }
  });
}
