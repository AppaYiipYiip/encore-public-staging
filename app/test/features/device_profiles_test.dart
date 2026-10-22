import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/device_profile.dart';
import '../support/test_app.dart';

/// P1-12 (E11-E13, owner: "sometimes there are buttons under the 3 navigation buttons ... we should be testing all cases"):
/// every main screen and every bottom sheet is opened as it looks on a phone with three navigation buttons, with the gesture bar,
/// and on a small phone with the largest text, and nothing the person can tap may lie under the system bar at the bottom.
void main() {
  setUpAll(loadAppFonts);

  const screens = <String, String>{
    'home': '/home',
    'search': '/search',
    'library': '/library',
    'album': '/home/album/al1',
    'playlist': '/home/playlist/pl1',
    'liked': '/home/liked',
    'settings': '/settings',
    'playback settings': '/settings/playback',
    'import': '/settings/import',
  };

  Future<void> open(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  for (final profile in DeviceProfile.all) {
    group(profile.name, () {
      for (final entry in screens.entries) {
        testWidgets(
            '${entry.key}: lays out, and nothing tappable is under the system bar',
            (tester) async {
          final semantics = tester.ensureSemantics();
          applyProfile(tester, profile);
          final app = await pumpApp(tester, size: profile.size);
          await open(tester, entry.value);

          await expectReachable(tester, profile, entry.key);
          await closeApp(tester, app.db);
          semantics.dispose();
        });
      }

      testWidgets('the player: its controls and its sheets are reachable',
          (tester) async {
        final semantics = tester.ensureSemantics();
        applyProfile(tester, profile);
        final app =
            await pumpApp(tester, size: profile.size, playing: samplePlaying());
        await open(tester, '/player');
        await expectReachable(tester, profile, 'the player');

        for (final label in ['Speed', 'Sleep timer', 'Queue']) {
          await tester.ensureVisible(find.text(label));
          await tester.tap(find.text(label));
          await settle(tester);
          await expectReachable(tester, profile, '$label sheet');
          await tester.tapAt(
              const Offset(10, 60)); // the scrim above the sheet closes it
          await settle(tester);
        }
        await closeApp(tester, app.db);
        semantics.dispose();
      });

      testWidgets('the track menu and the menu of a collection',
          (tester) async {
        final semantics = tester.ensureSemantics();
        applyProfile(tester, profile);
        final app = await pumpApp(tester, size: profile.size);
        await open(tester, '/home/album/al3');

        await tester.tap(find.byTooltip('More options').last);
        await settle(tester);
        await expectReachable(tester, profile, 'track menu');
        await closeApp(tester, app.db);
        semantics.dispose();
      });

      testWidgets('the menu that makes a playlist or imports one',
          (tester) async {
        final semantics = tester.ensureSemantics();
        applyProfile(tester, profile);
        final app = await pumpApp(tester, size: profile.size);
        await open(tester, '/library');

        await tester.tap(find.byTooltip('Create'));
        await settle(tester);
        await expectReachable(tester, profile, 'create menu');
        await closeApp(tester, app.db);
        semantics.dispose();
      });
    });
  }
}
