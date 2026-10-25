import 'package:encore/features/player/playback_facade.dart';
import 'package:encore/playback/queue_model.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

QueueSnapshot sampleQueue() => QueueSnapshot(
      currentIndex: 0,
      items: [
        for (var i = 0; i < 4; i++)
          QueueItem(
            uid: i + 1,
            id: 'q$i',
            title: 'Queued song $i',
            artist: 'Artist',
            durationSec: 200,
          ),
      ],
    );

void main() {
  setUpAll(loadAppFonts);

  Future<void> openPlayer(WidgetTester tester) async {
    await tester.tap(find.text('Opening The').first);
    await settle(tester);
  }

  testWidgets('the queue sheet shows now playing and what is next',
      (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    app.facade.emitQueue(sampleQueue());
    await openPlayer(tester);

    await tester.tap(find.byTooltip('Queue'));
    await settle(tester);

    expect(find.text('Now playing'), findsOneWidget);
    expect(find.text('Next up'), findsOneWidget);
    expect(find.text('Queued song 1'), findsOneWidget);
    expect(find.text('Queued song 3'), findsOneWidget);

    await closeApp(tester, app.db);
  });

  testWidgets('the player has a menu for the playing song (add to playlist)',
      (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    await openPlayer(tester);

    await tester.tap(find.byTooltip('More options').first);
    await settle(tester);

    expect(find.text('Add to playlist'), findsOneWidget);
    expect(find.text('Go to album'), findsOneWidget);
    expect(find.text('Go to artist'), findsOneWidget);

    await closeApp(tester, app.db);
  });

  testWidgets(
      'a catalogue sample has only the player\'s own menu: no library lines',
      (tester) async {
    final app = await pumpApp(
      tester,
      playing: PlaybackSnapshot(
        track: const NowPlayingTrack(
          id: 'preview-1',
          title: 'Sample song',
          artist: 'Someone',
          imageUrl: 'https://img/cover.jpg',
        ),
        isPlaying: true,
        duration: const Duration(seconds: 30),
        queueIndex: 0,
        queueLength: 1,
        sourceName: 'Preview',
      ),
    );
    await tester.tap(find.text('Sample song').first);
    await settle(tester);

    await tester.tap(find.byTooltip('More options'));
    await settle(tester);

    expect(find.text('Sleep timer'), findsOneWidget);
    expect(find.text('Add to playlist'), findsNothing);
    expect(find.text('Go to album'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('tapping a queued song jumps to it', (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    app.facade.emitQueue(sampleQueue());
    await openPlayer(tester);
    await tester.tap(find.byTooltip('Queue'));
    await settle(tester);

    await tester.tap(find.text('Queued song 2'));
    await settle(tester);

    expect(app.facade.calls, contains('jump(2)'));
    await closeApp(tester, app.db);
  });

  testWidgets('Clear empties the up-next list', (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    app.facade.emitQueue(sampleQueue());
    await openPlayer(tester);
    await tester.tap(find.byTooltip('Queue'));
    await settle(tester);

    await tester.tap(find.text('Clear'));
    await settle(tester);

    expect(app.facade.calls, contains('clearUpNext'));
    await closeApp(tester, app.db);
  });

  testWidgets('the sleep timer offers durations and end of song',
      (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    await openPlayer(tester);

    await tester.tap(find.byTooltip('More options'));
    await settle(tester);
    await tester.tap(find.text('Sleep timer'));
    await settle(tester);
    expect(find.text('15 minutes'), findsOneWidget);
    expect(find.text('End of this song'), findsOneWidget);

    await tester.tap(find.text('15 minutes'));
    await settle(tester);
    expect(app.facade.calls, contains('sleep(15)'));

    await closeApp(tester, app.db);
  });

  testWidgets('end of song sets the end-of-track timer', (tester) async {
    final app = await pumpApp(tester, playing: samplePlaying());
    await openPlayer(tester);
    await tester.tap(find.byTooltip('More options'));
    await settle(tester);
    await tester.tap(find.text('Sleep timer'));
    await settle(tester);
    await tester.tap(find.text('End of this song'));
    await settle(tester);
    expect(app.facade.calls, contains('sleepEnd(true)'));
    await closeApp(tester, app.db);
  });
}
