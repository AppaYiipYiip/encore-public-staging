import 'package:encore/app/connection.dart';
import 'package:encore/domain/lyrics.dart';
import 'package:encore/features/jam/jam_providers.dart';
import 'package:encore/features/player/lyrics_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/test_app.dart';

/// Visual regression for the primary screens over a seeded library
/// (docs/05-testing-and-quality.md). Regenerate intentionally with
/// `flutter test --update-goldens test/features`.
const _sampleLyrics = TrackLyrics(
  synced: true,
  source: 'server',
  lines: [
    LyricLine(startMs: 0, text: 'Under it all'),
    LyricLine(startMs: 8000, text: 'A new world'),
    LyricLine(
        startMs: 16000, text: 'A new world made with the hands of madness'),
    LyricLine(startMs: 30000, text: 'These hands'),
    LyricLine(startMs: 40000, text: 'They will always do the cutting'),
    LyricLine(startMs: 52000, text: 'Piece by piece the pain gets worse'),
    LyricLine(startMs: 70000, text: 'If only I could see myself right now'),
  ],
);

void main() {
  setUpAll(loadAppFonts);

  Future<void> goTo(WidgetTester tester, String location) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go(location);
    await settle(tester);
  }

  testWidgets('home', (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    await settle(tester);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/home.png'),
    );
    await closeApp(tester, app.db);
  });

  // S-27 (D-34): the drawer the Home avatar opens. A plain server: only the rows that exist.
  testWidgets('you drawer', (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying(), overrides: [
      jamApiProvider.overrideWith((ref) async => null),
    ]);
    await settle(tester);
    await tester.tap(find.widgetWithText(CircleAvatar, 'M').first);
    await settle(tester);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/you_drawer.png'),
    );
    await closeApp(tester, app.db);
  });

  testWidgets('library list', (tester) async {
    // "Your music" is the state worth keeping a golden of; on automatic the
    // seed (6 albums) would show the whole server.
    SharedPreferences.setMockInitialValues({'encore.libraryScope': 'mine'});
    final app = await pumpApp(tester);
    await goTo(tester, '/library');
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/library_list.png'),
    );
    await closeApp(tester, app.db);
  });

  testWidgets('search browse', (tester) async {
    final app = await pumpApp(tester);
    await goTo(tester, '/search');
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/search_browse.png'),
    );
    await closeApp(tester, app.db);
  });

  testWidgets('search results are instant and offline', (tester) async {
    final app = await pumpApp(tester);
    await goTo(tester, '/search');
    await tester.enterText(find.byType(TextField), 'peri');
    await tester.pump(const Duration(milliseconds: 150));
    await settle(tester);
    expect(find.text('Periphery'), findsWidgets);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/search_results.png'),
    );
    await closeApp(tester, app.db);
  });

  testWidgets('album detail', (tester) async {
    final app = await pumpApp(tester);
    await goTo(tester, '/home/album/al3');
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/album.png'),
    );
    await closeApp(tester, app.db);
  });

  testWidgets('playlist without server cover shows the golden mosaic',
      (tester) async {
    final app = await pumpApp(tester);
    await goTo(tester, '/home/playlist/pl1');
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/playlist_mosaic.png'),
    );
    await closeApp(tester, app.db);
  });

  testWidgets('now playing', (tester) async {
    final app = await pumpApp(
      tester,
      playing: samplePlaying(),
      overrides: [
        currentLyricsProvider.overrideWith((ref, id) async => _sampleLyrics),
      ],
    );
    await goTo(tester, '/player');
    app.facade.emitPosition(const Duration(seconds: 62));
    await settle(tester);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/now_playing.png'),
    );
    await closeApp(tester, app.db);
  });

  testWidgets('now playing, waiting for the server', (tester) async {
    final app = await pumpApp(
      tester,
      playing: samplePlaying(isPlaying: false),
      overrides: [
        connectionGraceProvider.overrideWithValue(Duration.zero),
        serverFindingProvider
            .overrideWith((ref) => Stream.value(ServerFinding.silent)),
        currentLyricsProvider.overrideWith((ref, id) async => _sampleLyrics),
      ],
    );
    await goTo(tester, '/player');
    app.facade.emitPosition(const Duration(seconds: 62));
    await tester.pump(const Duration(milliseconds: 50));
    await settle(tester);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/now_playing_waiting.png'),
    );
    await closeApp(tester, app.db);
  });

  testWidgets('lyrics full screen', (tester) async {
    const lyrics = _sampleLyrics;
    final app = await pumpApp(
      tester,
      playing: samplePlaying(),
      overrides: [
        currentLyricsProvider.overrideWith((ref, id) async => lyrics),
      ],
    );
    await goTo(tester, '/lyrics');
    app.facade.emitPosition(const Duration(seconds: 41));
    await settle(tester);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/lyrics.png'),
    );
    await closeApp(tester, app.db);
  });

  testWidgets('settings', (tester) async {
    final app = await pumpApp(tester);
    await goTo(tester, '/settings');
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/settings.png'),
    );
    await closeApp(tester, app.db);
  });

  testWidgets('onboarding when no server is configured', (tester) async {
    final app = await pumpApp(tester, seeded: false);
    await settle(tester);
    expect(find.text('Connect'), findsWidgets);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/onboarding.png'),
    );
    await closeApp(tester, app.db);
  });
}
