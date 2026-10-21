import 'package:encore/domain/lyrics.dart';
import 'package:encore/features/player/lyrics_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// B19: after a big seek the sung line is far from the screen. The list is lazy,
/// so that line has no widget yet; following used to give up for good.
void main() {
  setUpAll(loadAppFonts);

  final lyrics = TrackLyrics(
    synced: true,
    source: 'server',
    lines: [
      for (var i = 0; i < 300; i++)
        LyricLine(startMs: i * 2000, text: 'Line number $i'),
    ],
  );

  Future<void> openLyrics(WidgetTester tester) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/lyrics');
    await settle(tester);
  }

  bool onScreen(WidgetTester tester, String text) {
    final finder = find.text(text);
    if (finder.evaluate().isEmpty) return false;
    final centre = tester.getCenter(finder.first);
    final size = tester.view.physicalSize / tester.view.devicePixelRatio;
    return centre.dy > 0 && centre.dy < size.height;
  }

  testWidgets('a big seek brings the sung line on screen', (tester) async {
    final app = await pumpApp(
      tester,
      playing: samplePlaying(),
      overrides: [
        currentLyricsProvider.overrideWith((ref, id) async => lyrics),
      ],
    );
    await openLyrics(tester);
    app.facade.emitPosition(const Duration(seconds: 2));
    await settle(tester);
    expect(onScreen(tester, 'Line number 1'), isTrue, reason: 'near the start');

    // Line 250 starts at 500 s: hundreds of rows below anything that is built.
    app.facade.emitPosition(const Duration(seconds: 500));
    await settle(tester);

    expect(onScreen(tester, 'Line number 250'), isTrue,
        reason: 'the list must follow a jump far away, not stay at the top');
    await closeApp(tester, app.db);
  });

  testWidgets('and keeps following line by line afterwards', (tester) async {
    final app = await pumpApp(
      tester,
      playing: samplePlaying(),
      overrides: [
        currentLyricsProvider.overrideWith((ref, id) async => lyrics),
      ],
    );
    await openLyrics(tester);
    app.facade.emitPosition(const Duration(seconds: 500));
    await settle(tester);
    app.facade.emitPosition(const Duration(seconds: 504));
    await settle(tester);

    expect(onScreen(tester, 'Line number 252'), isTrue);
    await closeApp(tester, app.db);
  });
}
