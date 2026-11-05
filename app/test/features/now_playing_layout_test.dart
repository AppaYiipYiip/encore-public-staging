import 'package:encore/app/connection.dart';
import 'package:encore/features/player/scrubber.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// Now playing is Spotify's arrangement and nothing more (owner, 2026-10-24; `docs/design/03` row 9): a chevron, "Playing from", a "..." menu,
/// a big cover, the title and the heart, the scrubber, the five controls, the device icon on the left and the queue icon on the right, and the
/// lyrics as a card further down. The speed, the sleep timer and private listening are lines of the "..." menu. A song waiting for its server shows
/// the same thin strip as everywhere else, at the top, and its scrubber is dashed with a hollow thumb.
void main() {
  setUpAll(loadAppFonts);

  Future<void> openPlayer(WidgetTester tester) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/player');
    await settle(tester);
  }

  testWidgets(
      'the player has the queue on the right and no device icon (D-28), '
      'no lyrics button, no speed or sleep buttons', (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    await openPlayer(tester);

    expect(find.byTooltip('Close player'), findsOneWidget);
    expect(find.byTooltip('More options'), findsOneWidget);
    // D-28 (AUDIT F45): the icon opened Android's system-wide output chooser, so it moved every app's sound. It is gone.
    expect(find.byTooltip('Choose where to play'), findsNothing);
    expect(find.byTooltip('Queue'), findsOneWidget);
    expect(find.text('Lyrics'), findsNothing,
        reason: 'lyrics are a card further down, not a button');
    expect(find.text('Speed'), findsNothing);
    expect(find.text('Sleep timer'), findsNothing);
    expect(find.text('Private'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'D-23: the sleep timer is in the "..." menu; there is no speed and no private listening',
      (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    await openPlayer(tester);

    await tester.tap(find.byTooltip('More options'));
    await settle(tester);

    expect(find.text('Sleep timer'), findsOneWidget);
    expect(find.text('Playback speed'), findsNothing);
    expect(find.text('Private listening: off'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song that waits for its server: the strip at the top, a '
      'dashed scrubber, the play button says Play', (tester) async {
    final app = await pumpApp(tester,
        playing: samplePlaying(isPlaying: false),
        overrides: [
          connectionGraceProvider.overrideWithValue(Duration.zero),
          serverReachableProvider.overrideWith((ref) => Stream.value(false)),
        ]);
    await openPlayer(tester);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    const stripText = "Can't reach your server.";
    expect(find.text(stripText), findsOneWidget);
    final strip = tester.getTopLeft(find.text(stripText));
    final title = tester.getTopLeft(find.text('Opening The'));
    expect(strip.dy, lessThan(title.dy), reason: 'at the top, above the song');
    final scrubber = tester.widget<Scrubber>(find.byType(Scrubber));
    expect(scrubber.waiting, isTrue);
    expect(
        find.byTooltip('Play').evaluate().isNotEmpty ||
            find.bySemanticsLabel('Play').evaluate().isNotEmpty,
        isTrue);
    await closeApp(tester, app.db);
  });

  testWidgets(
      'CN-11: a song that waits while another server answers at the address: the line says so, and the scrubber is dashed',
      (tester) async {
    final app = await pumpApp(tester,
        playing: samplePlaying(isPlaying: false),
        overrides: [
          connectionGraceProvider.overrideWithValue(Duration.zero),
          serverReachableProvider.overrideWith((ref) => Stream.value(false)),
          anotherServerAtProvider.overrideWith(
              (ref) => Stream.value(Uri.parse('http://192.168.1.10:4533'))),
        ]);
    await openPlayer(tester);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    expect(
        find.text('Another server answers at 192.168.1.10.'), findsOneWidget);
    expect(tester.widget<Scrubber>(find.byType(Scrubber)).waiting, isTrue,
        reason: 'the server is away for the player, whatever the strip says');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'a song that plays while the server is away (a downloaded file) '
      'keeps the ordinary scrubber', (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying(), overrides: [
      connectionGraceProvider.overrideWithValue(Duration.zero),
      serverReachableProvider.overrideWith((ref) => Stream.value(false)),
    ]);
    await openPlayer(tester);
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);

    expect(find.text("Can't reach your server."), findsOneWidget);
    expect(tester.widget<Scrubber>(find.byType(Scrubber)).waiting, isFalse);
    await closeApp(tester, app.db);
  });
}
