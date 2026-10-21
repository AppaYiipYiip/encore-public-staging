import 'package:encore/data/db/app_database.dart';
import 'package:encore/domain/lyrics.dart';
import 'package:encore/features/player/lyrics_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// Found on a friend's phone (2026-10-17, "the slider wouldn't work on the
/// lyrics page", "it goes to the end of the song out of nowhere"): the bar on
/// the lyrics page could not be dragged at all, the lyrics ran under the
/// controls, and once the controls had faded out a touch where the bar had been
/// landed on a lyric line, which jumps to that line (often near the end).
void main() {
  setUpAll(loadAppFonts);

  final lyrics = TrackLyrics(
    synced: true,
    source: 'server',
    lines: [
      for (var i = 0; i < 80; i++)
        LyricLine(startMs: i * 2500, text: 'Line number $i'),
    ],
  );

  Future<({AppDatabase db, FakePlaybackFacade facade})> open(
      WidgetTester tester) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 800),
      playing: samplePlaying(),
      overrides: [
        currentLyricsProvider.overrideWith((ref, id) async => lyrics),
      ],
    );
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/lyrics');
    await settle(tester);
    return (db: app.db, facade: app.facade);
  }

  testWidgets('looks the way it was drawn (golden)', (tester) async {
    final app = await pumpApp(
      tester,
      size: const Size(390, 800),
      playing: samplePlaying(),
      overrides: [
        currentLyricsProvider.overrideWith((ref, id) async => TrackLyrics(
              synced: true,
              source: 'server',
              lines: [
                const LyricLine(
                    startMs: 0, text: 'Rain keeps falling on the empty road'),
                const LyricLine(
                    startMs: 4000, text: 'Every window shows a different sky'),
                const LyricLine(
                    startMs: 8000,
                    text: 'Carry me back before the morning comes'),
                const LyricLine(
                    startMs: 12000,
                    text: 'I counted all the stars along the way'),
                const LyricLine(
                    startMs: 16000,
                    text: 'Nothing here is quite the way it seems'),
                const LyricLine(
                    startMs: 20000,
                    text: 'Hold the light until the night is done'),
                const LyricLine(
                    startMs: 24000, text: 'Tell me where the quiet river goes'),
                const LyricLine(
                    startMs: 28000, text: 'Sing it once and then we let it go'),
              ],
            )),
      ],
    );
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/lyrics');
    await settle(tester);
    app.facade.emitPosition(const Duration(seconds: 9));
    await settle(tester);

    await expectLater(find.byType(Scaffold).last,
        matchesGoldenFile('goldens/lyrics_controls.png'));
    await closeApp(tester, app.db);
  });

  testWidgets('the bar can be dragged to seek, as in the full player',
      (tester) async {
    final app = await open(tester);

    final bar = find.byType(Slider);
    expect(bar, findsOneWidget);
    await tester.drag(bar, const Offset(120, 0));
    await tester.pump();

    expect(app.facade.calls.where((c) => c.startsWith('seek')), hasLength(1));
    await closeApp(tester, app.db);
  });

  testWidgets(
      'the lyrics stop above the controls instead of running under them',
      (tester) async {
    final app = await open(tester);

    final controls = tester.getRect(find.byType(Slider));
    final list = tester.getRect(find.byType(ListView));

    expect(list.bottom, lessThanOrEqualTo(controls.top),
        reason: 'lyric text under the bar and the times hid them');
    await closeApp(tester, app.db);
  });

  testWidgets(
      'the title and the controls stay on the screen while the lyrics play',
      (tester) async {
    // The owner, 2026-10-17: "this looks hella empty". After a few seconds the
    // title and the controls used to fade away and left lyrics and nothing
    // else; Spotify keeps them.
    final app = await open(tester);

    await tester.pump(const Duration(seconds: 12));

    expect(find.byType(Slider), findsOneWidget);
    expect(find.byTooltip('Close lyrics'), findsOneWidget);
    for (final fade
        in tester.widgetList<AnimatedOpacity>(find.byType(AnimatedOpacity))) {
      expect(fade.opacity, 1.0, reason: 'nothing on this page fades out');
    }
    await closeApp(tester, app.db);
  });
}
