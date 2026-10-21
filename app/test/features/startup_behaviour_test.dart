import 'package:encore/app/playback_providers.dart';
import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/playback/equalizer_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// Things that must happen without anyone opening a screen for them.
void main() {
  group('playback problems are shown (docs/23, B9)', () {
    testWidgets('a failed song tells the person', (tester) async {
      final app = await pumpApp(tester);

      app.facade.emitNotice(const PlaybackNotice(
          'Could not play "Song 7". Skipping to the next one.',
          isError: true));
      await settle(tester);

      expect(find.text('Could not play "Song 7". Skipping to the next one.'),
          findsOneWidget);
      await closeApp(tester, app.db);
    });

    testWidgets('a newer notice replaces the one on screen', (tester) async {
      final app = await pumpApp(tester);

      app.facade.emitNotice(const PlaybackNotice('First problem'));
      await settle(tester);
      app.facade.emitNotice(const PlaybackNotice('Second problem'));
      await settle(tester);

      expect(find.text('Second problem'), findsOneWidget);
      expect(find.text('First problem'), findsNothing);
      await closeApp(tester, app.db);
    });
  });

  group('the saved equaliser is applied at start-up (docs/23, B10)', () {
    testWidgets('without opening the equaliser screen', (tester) async {
      var built = 0;
      final app = await pumpApp(tester, overrides: [
        equalizerServiceProvider.overrideWith((ref) {
          built++;
          return EqualizerService(null);
        }),
      ]);

      expect(built, 1,
          reason: 'the service restores the saved curve when it is built; '
              'nothing built it until the person opened its screen');
      await closeApp(tester, app.db);
    });
  });

  group('close buttons have a name for screen readers (docs/23, B30)', () {
    for (final entry in const {
      'the player with nothing playing': '/player',
      'the lyrics with nothing playing': '/lyrics',
    }.entries) {
      testWidgets(entry.key, (tester) async {
        final app = await pumpApp(tester);
        final element = tester.element(find.byType(Scaffold).first);
        GoRouter.of(element).go(entry.value);
        await settle(tester);

        expect(find.byTooltip('Close'), findsOneWidget);
        await closeApp(tester, app.db);
      });
    }
  });
}
