import 'package:encore/app/connection.dart';
import 'package:encore/features/common/cover_art.dart';
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

  // P1-22 / D-63. The owner, looking at the player on his phone and on an
  // emulator, 6 Nov 2026: "the bottom part of the screen is empty, it looks
  // weird, it is ugly", and "android phones are weird, some of them are tall
  // some are wide". The page is laid out from the room it is given: the spare
  // height goes between the sections, never as an empty area under the controls.
  group('P1-22: the page uses the screen it is given', () {
    Future<Rect> queueButton(WidgetTester tester) async {
      await tester.ensureVisible(find.byTooltip('Queue'));
      await tester.pump();
      return tester.getRect(find.byTooltip('Queue'));
    }

    testWidgets(
        'a tall phone (411 x 914): the controls and the queue sit at the bottom, '
        'no dead area under them', (tester) async {
      final app = await pumpApp(tester,
          playing: samplePlaying(), size: const Size(411, 914));
      await openPlayer(tester);

      final queue = await queueButton(tester);
      // The page has no lyrics here (a song without them shows no card), so the
      // queue row is the last thing: at most one control row and the page's
      // own margin may stand below it. Before, about 230 logical pixels did.
      expect(914 - queue.bottom, lessThan(110),
          reason: 'what is left under the queue icon');
      // The cover is above the title, not squeezed against the top bar.
      final cover = tester.getRect(find.byType(CoverArt).first);
      final title = tester.getTopLeft(find.text('Opening The'));
      expect(cover.bottom, lessThan(title.dy));
      await closeApp(tester, app.db);
    });

    testWidgets(
        'a short phone with big text (411 x 731, text 1.3): everything is there '
        'and the page scrolls, nothing is cut off', (tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 1.3;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final app = await pumpApp(tester,
          playing: samplePlaying(), size: const Size(411, 731));
      await openPlayer(tester);

      // A layout error (an overflow) fails the test by itself; these say the
      // controls can be reached.
      expect(find.byTooltip('Close player'), findsOneWidget);
      final queue = await queueButton(tester);
      expect(queue.bottom, lessThanOrEqualTo(731));
      expect(queue.top, greaterThanOrEqualTo(0));
      await closeApp(tester, app.db);
    });

    testWidgets(
        'a wide or unfolded phone (920 x 1104): the cover beside the controls, '
        'nothing on top of anything', (tester) async {
      final app = await pumpApp(tester,
          playing: samplePlaying(), size: const Size(920, 1104));
      await openPlayer(tester);

      final cover = tester.getRect(find.byType(CoverArt).first);
      final title = tester.getRect(find.text('Opening The'));
      expect(cover.right, lessThanOrEqualTo(title.left),
          reason: 'the cover is on the left, the song on the right');
      expect(cover.height, greaterThan(300),
          reason: 'a real cover, not a chip');
      final queue = await queueButton(tester);
      expect(queue.right, lessThanOrEqualTo(920));
      await closeApp(tester, app.db);
    });

    testWidgets(
        'a phone on its side (914 x 411): the cover beside the controls, the '
        'controls scroll, nothing is cut off', (tester) async {
      final app = await pumpApp(tester,
          playing: samplePlaying(), size: const Size(914, 411));
      await openPlayer(tester);

      final cover = tester.getRect(find.byType(CoverArt).first);
      final title = tester.getRect(find.text('Opening The'));
      expect(cover.right, lessThanOrEqualTo(title.left));
      expect(cover.bottom, lessThanOrEqualTo(411));
      final queue = await queueButton(tester);
      expect(queue.bottom, lessThanOrEqualTo(411));
      await closeApp(tester, app.db);
    });
  });
}
